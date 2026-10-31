#!/usr/bin/env bash
# scripts/verify_dmg.sh — 验收 DMG：能不能装、能不能真的跑起来
#
# CI（ci.yml 的 dmg job / release.yml 的 dmg job）和本地都用这一份，
# 免得两边断言各写一遍、慢慢跑偏。默认把 dist/ 下所有 DMG 都验一遍。
#
# 用法:
#   scripts/verify_dmg.sh                          # 验 dist/*.dmg（全部）
#   scripts/verify_dmg.sh dist/VideoToText-x.dmg   # 只验一个
#   V2T_PORT=8799 scripts/verify_dmg.sh            # 浏览器版换端口（本机已有实例时）
#
# 断言（两个变体都跑）：
#   1. DMG 里有 App、有 /Applications 软链、主程序可执行
#   2. 打包完整（base_library.zip / VERSION / 内置 ffmpeg）
#   3. 文件名里的变体（-native 后缀）和包内 NATIVE_DEFAULT 标记一致
#   4. ffmpeg 是静态链接（otool -L 不能指向 /opt/homebrew、/usr/local/opt）
#   5. V2T_SELFTEST=1 自检通过：依赖图完整，且"原生包一定有 webview、浏览器包一定没有"
#   6. 从挂载点直接启动 App（就是用户的真实路径），首页 HTTP 200 且含「蒸馏」
#   7. 进程数：浏览器版 2 个、窗口版 3 个（多一个 pywebview 窗口进程），上限 5
#      —— 曾经因为缺 freeze_support() 无限自我复制，这条抓回归
#
# 窗口版的界面断言需要图形会话（Aqua）。CI 机器上如果没有，会退化成
# "只验服务端 + 依赖图"，并明确打一行 SKIP，而不是假装通过。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PORT="${V2T_PORT:-8766}"
LOG="$HOME/Library/Application Support/VideoToText/app.log"

MP=""
APP_PID=""
PAT=""

cleanup() {
  if [[ -n "$APP_PID" ]]; then
    # 先 kill 再 wait：不 wait 的话 bash 会在脚本结束后甩一行 "Terminated: 15"，
    # 看着像失败，其实是我们自己收的尾巴
    kill "$APP_PID" 2>/dev/null || true
    wait "$APP_PID" 2>/dev/null || true
    APP_PID=""
  fi
  # SIGTERM 不会跑 Python 的 atexit，multiprocessing 的守护子进程（窗口进程、
  # resource_tracker）不会被自动回收，手动扫一遍，免得残留到下一次验收里
  if [[ -n "$PAT" ]]; then
    pkill -f "$PAT" 2>/dev/null || true
    PAT=""
  fi
  if [[ -n "$MP" ]]; then
    hdiutil detach "$MP" -quiet 2>/dev/null || true
    MP=""
  fi
}
trap cleanup EXIT

mount_dmg() {
  local dmg="$1" mnt="$2"
  # 上次运行被打断（比如 Ctrl-C 或 App 还占着挂载点）会留下一个 attached 的镜像，
  # 再挂就报 "资源忙"，而且报错被 -quiet 吞掉，看起来像脚本莫名其妙退出。
  local dmg_abs stale
  dmg_abs="$(cd "$(dirname "$dmg")" && pwd)/$(basename "$dmg")"
  stale="$(hdiutil info 2>/dev/null | awk -v p="$dmg_abs" '
    /^image-path/ { cur = $3; next }
    /^\/dev\/disk/ { if (cur == p) { print $1; exit } }
  ')"
  if [[ -n "$stale" ]]; then
    echo "  · 清理上次残留的挂载 ${stale}" >&2
    hdiutil detach "$stale" -force -quiet 2>/dev/null || true
  fi
  hdiutil attach "$dmg" -mountpoint "$mnt" -nobrowse -quiet \
    || { echo "✗ 挂载失败（镜像可能正被占用）" >&2; return 1; }
}

# 等端口出现（窗口版是自己挑端口的，事先不知道是 8000-8999 里的哪个）
discover_port() {
  local pid="$1" port=""
  # -a 是必须的：lsof 的选择条件默认是"或"，只写 -p 和 -i 会列出全机器的监听端口，
  # 第一次跑就抓到了 rapportd 的 56236，然后 curl 一个没人管的端口，报 HTTP=000。
  port="$(lsof -nP -a -p "$pid" -iTCP -sTCP:LISTEN 2>/dev/null \
          | awk '/LISTEN/ { n = $9; sub(/.*:/, "", n); print n; exit }')"
  echo "$port"
}

verify_one() {
  local dmg="$1"
  echo
  echo "▸ 校验 ${dmg}（$(du -h "$dmg" | cut -f1)）"

  MP="$(mktemp -d)"
  mount_dmg "$dmg" "$MP" || { MP=""; return 1; }

  # ---------- 1. 结构 ----------
  local app exe bin
  app="$(find "$MP" -maxdepth 1 -name "*.app" -type d 2>/dev/null | head -1)"
  [[ -n "$app" ]] || { echo "✗ DMG 里没有 .app"; return 1; }
  exe="$(basename "$app" .app)"
  bin="$app/Contents/MacOS/$exe"
  [[ -L "$MP/Applications" ]] || { echo "✗ 缺少 Applications 软链（没法拖拽安装）"; return 1; }
  [[ -x "$bin" ]]            || { echo "✗ 主程序不可执行：$exe"; return 1; }
  echo "  ✓ 结构：${exe}.app + Applications 软链"

  # ---------- 2. 打包完整性 ----------
  # 源码打进 PYZ 了，磁盘上没有 gui.py，只能查这些标志物
  local fw
  fw="$app/Contents/Frameworks"
  [[ -f "$fw/base_library.zip" ]]            || { echo "✗ 缺 base_library.zip，打包不完整"; return 1; }
  [[ -f "$app/Contents/Resources/VERSION" ]] || { echo "✗ 缺 VERSION"; return 1; }
  echo "  ✓ 版本：$(cat "$app/Contents/Resources/VERSION")"

  # ---------- 3. 变体标记与文件名一致 ----------
  local flag want_native expect
  flag="$(cat "$app/Contents/Resources/NATIVE_DEFAULT" 2>/dev/null || echo "")"
  [[ -n "$flag" ]] || { echo "✗ 缺 NATIVE_DEFAULT（launcher 会静默退回浏览器模式）"; return 1; }
  expect="0"
  case "$(basename "$dmg")" in *-native.dmg) expect="1" ;; esac
  if [[ "$flag" != "$expect" ]]; then
    echo "✗ 变体错位：文件名暗示 native=${expect}，包内标记是 ${flag}"
    return 1
  fi
  want_native="$flag"
  if [[ "$want_native" == "1" ]]; then
    echo "  ✓ 变体：原生窗口（NATIVE_DEFAULT=1）"
  else
    echo "  ✓ 变体：浏览器（NATIVE_DEFAULT=0）"
  fi

  # ---------- 4. 内置 ffmpeg 且必须静态 ----------
  local ffb
  ffb="$(find "$app/Contents" -name ffmpeg -type f | head -1)"
  [[ -n "$ffb" ]] || { echo "✗ App 里没有 ffmpeg（用户装完转写会直接失败）"; return 1; }
  "$ffb" -version | head -1
  if otool -L "$ffb" | grep -qE "/opt/homebrew|/usr/local/opt"; then
    echo "✗ ffmpeg 动态链接到本机 Homebrew，换台机器就跑不起来"
    otool -L "$ffb"
    return 1
  fi
  echo "  ✓ ffmpeg 静态链接，可分发"

  # ---------- 5. 依赖图自检（不需要图形界面） ----------
  # 冻结后的包最常见的翻车是依赖没打进去：进程活着、窗口没有、日志一行 ModuleNotFoundError。
  # launcher 的 V2T_SELFTEST 模式同时验证"该有的有、不该有的没有"。
  local st out
  st="$(mktemp)"
  if ! V2T_SELFTEST=1 "$bin" > "$st" 2>&1; then
    echo "✗ 自检失败："
    sed 's/^/    /' "$st"
    return 1
  fi
  out="$(cat "$st")"
  echo "$out" | sed -n 's/^\[selftest\] /  · /p'
  if [[ "$want_native" == "1" ]]; then
    echo "$out" | grep -q "webview=ok" || { echo "✗ 窗口版里没有 pywebview"; return 1; }
  else
    echo "$out" | grep -q "webview=missing" || {
      echo "✗ 浏览器版里混进了 pywebview（体积白涨，说明 spec 的 EXCLUDES 失效了）"; return 1; }
  fi
  echo "  ✓ 依赖图自检通过"

  # ---------- 6. 真的启动一次 ----------
  # 清掉上次的日志，免得把旧的成功记录当成这次的结果
  # （CI 上是干净机器，这个目录还不存在，先建出来）
  mkdir -p "$(dirname "$LOG")"
  : > "$LOG" 2>/dev/null || true

  # 同一变体的僵尸进程会让进程数断言失真（上一次被打断时留下的）
  # 用 "( |$)" 收尾：不加边界的话 "…/VideoToText" 会连 "…/VideoToTextNative" 一起匹上，
  # 两个变体挨着验时进程数就串了
  PAT="Contents/MacOS/${exe}( |\$)"
  pkill -f "$PAT" 2>/dev/null || true

  local gui_ok=0
  if [[ "$(launchctl managername 2>/dev/null || true)" == "Aqua" ]]; then gui_ok=1; fi

  local target_port="$PORT" native_window=0
  if [[ "$want_native" == "1" && "$gui_ok" == "1" ]]; then
    # 不传 V2T_PORT / V2T_NATIVE：让包自己按 NATIVE_DEFAULT 决定，这才是用户双击的路径
    native_window=1
    echo "▸ 从挂载点启动 App（窗口版，端口由 App 自选）…"
    "$bin" > /tmp/v2t-boot.log 2>&1 &
    APP_PID=$!
    target_port=""
    local i
    for i in $(seq 1 60); do
      target_port="$(discover_port "$APP_PID")"
      [[ -n "$target_port" ]] && break
      sleep 1
    done
    if [[ -z "$target_port" ]]; then
      echo "✗ App 起来了但没有任何监听端口"
      echo "--- boot.log ---"; tail -40 /tmp/v2t-boot.log || true
      echo "--- app.log ---";  tail -60 "$LOG" 2>/dev/null || true
      return 1
    fi
    echo "  · App 自己挑了端口 ${target_port}"
  else
    if [[ "$want_native" == "1" ]]; then
      echo "  · SKIP 原生窗口断言：当前没有图形会话（launchctl managername != Aqua）"
      echo "    改为强制浏览器模式冒烟，只验服务端和依赖图"
    fi
    echo "▸ 从挂载点启动 App（端口 ${target_port}）…"
    V2T_SHOW=0 V2T_PORT="$target_port" V2T_NATIVE=0 "$bin" > /tmp/v2t-boot.log 2>&1 &
    APP_PID=$!
  fi

  local page code ok
  page="$(mktemp)"
  code=""
  ok=0
  for _ in $(seq 1 60); do
    code="$(curl -s -o "$page" -w '%{http_code}' "http://127.0.0.1:${target_port}/" || true)"
    if [[ "$code" == "200" ]]; then ok=1; break; fi
    sleep 1
  done

  # 进程数要在 kill 之前数
  local nproc nchild
  nproc="$(pgrep -f "$PAT" 2>/dev/null | wc -l | tr -d ' ')"
  nchild="$(pgrep -P "$APP_PID" 2>/dev/null | wc -l | tr -d ' ')"

  if [[ "$ok" != "1" ]]; then
    echo "✗ App 起不来（HTTP=${code:-none}）"
    echo "--- boot.log ---"; tail -40 /tmp/v2t-boot.log || true
    echo "--- app.log ---";  tail -60 "$LOG" 2>/dev/null || echo "(没有 app.log)"
    return 1
  fi

  grep -q "蒸馏" "$page" || { echo "✗ 首页内容不对（找不到第三模式）"; head -20 "$page"; return 1; }
  echo "  ✓ 首页 HTTP 200，含「蒸馏」"

  # launcher 实际选中的界面模式，必须和包的变体一致
  if grep -q "界面模式：原生窗口" "$LOG"; then
    [[ "$want_native" == "1" ]] || { echo "✗ 浏览器版却开了原生窗口"; return 1; }
    echo "  ✓ 日志确认：走了原生窗口"
  else
    grep -q "界面模式：浏览器" "$LOG" || echo "  ! 日志里没看到界面模式（老版本日志？）"
  fi

  # ---------- 7. 进程数 ----------
  # 浏览器版：主进程 + resource_tracker = 2
  # 窗口版：  再加一个 pywebview 窗口进程 = 3
  if [[ "$nproc" -gt 5 ]]; then
    echo "✗ 进程数异常（${nproc}），疑似 multiprocessing 子进程把 App 又启动了一遍"
    echo "  检查 packaging/launcher.py 是否调用了 multiprocessing.freeze_support()"
    tail -40 "$LOG" 2>/dev/null || true
    return 1
  fi
  if [[ "$native_window" == "1" && "$nchild" -lt 2 ]]; then
    echo "✗ 窗口版只有 ${nchild} 个子进程，pywebview 窗口进程没起来（大概率缺 hiddenimports）"
    tail -40 "$LOG" 2>/dev/null || true
    return 1
  fi
  echo "  ✓ 进程数 ${nproc}（子进程 ${nchild}）"

  cleanup
  echo "✓ 通过"
  return 0
}

DMGS=()
if [[ -n "${1:-}" ]]; then
  DMGS=("$1")
else
  while IFS= read -r line; do
    [[ -n "$line" ]] && DMGS+=("$line")
  done < <(ls -t dist/*.dmg 2>/dev/null || true)
fi

if [[ ${#DMGS[@]} -eq 0 ]]; then
  echo "✗ 找不到 DMG（先跑 scripts/build_dmg.sh）" >&2
  exit 1
fi

fail=0
for d in "${DMGS[@]}"; do
  [[ -f "$d" ]] || { echo "✗ 文件不存在：$d" >&2; fail=1; continue; }
  verify_one "$d" || fail=1
done

if [[ "$fail" != "0" ]]; then
  echo
  echo "✗ 有 DMG 没通过验收" >&2
  exit 1
fi

echo
echo "✓ 全部 DMG 验收通过（${#DMGS[@]} 个）"
