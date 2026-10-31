#!/usr/bin/env bash
# scripts/verify_dmg.sh — 验收 DMG：能不能装、能不能真的跑起来
#
# CI（ci.yml 的 dmg job / release.yml 的 dmg job）和本地都用这一份，
# 免得两边断言各写一遍、慢慢跑偏。
#
# 用法:
#   scripts/verify_dmg.sh                          # 自动挑 dist/*.dmg
#   scripts/verify_dmg.sh dist/VideoToText-x.dmg
#   V2T_PORT=8799 scripts/verify_dmg.sh            # 换端口（本机已有实例在跑时）
#
# 断言：
#   1. DMG 里有 App、有 /Applications 软链、主程序可执行
#   2. 打包完整（base_library.zip / VERSION / 内置 ffmpeg）
#   3. ffmpeg 是静态链接（otool -L 不能指向 /opt/homebrew、/usr/local/opt）
#   4. 从挂载点直接启动 App（就是用户的真实路径），首页 HTTP 200 且含「蒸馏」
#   5. 进程数 ≤ 5 —— 曾经因为缺 freeze_support() 无限自我复制，这条抓回归
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

DMG="${1:-}"
if [[ -z "$DMG" ]]; then
  DMG="$(ls -t dist/*.dmg 2>/dev/null | head -1 || true)"
fi
[[ -n "$DMG" && -f "$DMG" ]] || { echo "✗ 找不到 DMG（先跑 scripts/build_dmg.sh）" >&2; exit 1; }

PORT="${V2T_PORT:-8766}"
LOG="$HOME/Library/Application Support/VideoToText/app.log"

echo "▸ 校验 ${DMG}（$(du -h "$DMG" | cut -f1)）"

MP="$(mktemp -d)"
APP_PID=""
cleanup() {
  if [[ -n "$APP_PID" ]]; then
    # 先 kill 再 wait：不 wait 的话 bash 会在脚本结束后甩一行 "Terminated: 15"，
    # 看着像失败，其实是我们自己收的尾巴
    kill "$APP_PID" 2>/dev/null || true
    wait "$APP_PID" 2>/dev/null || true
  fi
  hdiutil detach "$MP" -quiet 2>/dev/null || true
}
trap cleanup EXIT

# 上次运行被打断（比如 Ctrl-C 或 App 还占着挂载点）会留下一个 attached 的镜像，
# 再挂就报 "资源忙"，而且报错被 -quiet 吞掉，看起来像脚本莫名其妙退出。
DMG_ABS="$(cd "$(dirname "$DMG")" && pwd)/$(basename "$DMG")"
STALE="$(hdiutil info 2>/dev/null | awk -v p="$DMG_ABS" '
  /^image-path/ { cur = $3; next }
  /^\/dev\/disk/ { if (cur == p) { print $1; exit } }
')"
if [[ -n "$STALE" ]]; then
  echo "  · 清理上次残留的挂载 ${STALE}" >&2
  hdiutil detach "$STALE" -force -quiet 2>/dev/null || true
fi

hdiutil attach "$DMG" -mountpoint "$MP" -nobrowse -quiet \
  || { echo "✗ 挂载失败（镜像可能正被占用）" >&2; exit 1; }

# ---------- 1. 结构 ----------
APP="$MP/VideoToText.app"
[[ -d "$APP" ]]                     || { echo "✗ DMG 里没有 VideoToText.app"; exit 1; }
[[ -L "$MP/Applications" ]]         || { echo "✗ 缺少 Applications 软链（没法拖拽安装）"; exit 1; }
[[ -x "$APP/Contents/MacOS/VideoToText" ]] || { echo "✗ 主程序不可执行"; exit 1; }
echo "  ✓ 结构：App + Applications 软链"

# ---------- 2. 打包完整性 ----------
# 源码打进 PYZ 了，磁盘上没有 gui.py，只能查这些标志物
FW="$APP/Contents/Frameworks"
[[ -f "$FW/base_library.zip" ]]                  || { echo "✗ 缺 base_library.zip，打包不完整"; exit 1; }
[[ -f "$APP/Contents/Resources/VERSION" ]]       || { echo "✗ 缺 VERSION"; exit 1; }
echo "  ✓ 版本：$(cat "$APP/Contents/Resources/VERSION")"

# ---------- 3. 内置 ffmpeg 且必须静态 ----------
BIN="$(find "$APP/Contents" -name ffmpeg -type f | head -1)"
[[ -n "$BIN" ]] || { echo "✗ App 里没有 ffmpeg（用户装完转写会直接失败）"; exit 1; }
"$BIN" -version | head -1
if otool -L "$BIN" | grep -qE "/opt/homebrew|/usr/local/opt"; then
  echo "✗ ffmpeg 动态链接到本机 Homebrew，换台机器就跑不起来"
  otool -L "$BIN"
  exit 1
fi
echo "  ✓ ffmpeg 静态链接，可分发"

# ---------- 4. 真的启动一次 ----------
echo "▸ 从挂载点启动 App（端口 ${PORT}）…"
# 清掉上次的日志，免得把旧的成功记录当成这次的结果
# （CI 上是干净机器，这个目录还不存在，先建出来）
mkdir -p "$(dirname "$LOG")"
: > "$LOG" 2>/dev/null || true

V2T_SHOW=0 V2T_PORT="$PORT" "$APP/Contents/MacOS/VideoToText" > /tmp/v2t-boot.log 2>&1 &
APP_PID=$!

PAGE="$(mktemp)"
code=""
ok=0
for _ in $(seq 1 60); do
  code="$(curl -s -o "$PAGE" -w '%{http_code}' "http://127.0.0.1:${PORT}/" || true)"
  if [[ "$code" == "200" ]]; then ok=1; break; fi
  sleep 1
done

# 进程数要在 kill 之前数
NPROC="$(pgrep -f "VideoToText.app/Contents/MacOS" 2>/dev/null | wc -l | tr -d ' ')"

if [[ "$ok" != "1" ]]; then
  echo "✗ App 起不来（HTTP=${code:-none}）"
  echo "--- boot.log ---"; tail -40 /tmp/v2t-boot.log
  echo "--- app.log ---";  tail -60 "$LOG" 2>/dev/null || echo "(没有 app.log)"
  exit 1
fi

grep -q "蒸馏" "$PAGE" || { echo "✗ 首页内容不对（找不到第三模式）"; head -20 "$PAGE"; exit 1; }
echo "  ✓ 首页 HTTP 200，含「蒸馏」"

# ---------- 5. 进程数 ----------
# 正常 2 个：主进程 + multiprocessing 的 resource_tracker
if [[ "$NPROC" -gt 5 ]]; then
  echo "✗ 进程数异常（${NPROC}），疑似 multiprocessing 子进程把 App 又启动了一遍"
  echo "  检查 packaging/launcher.py 是否调用了 multiprocessing.freeze_support()"
  tail -40 "$LOG" 2>/dev/null || true
  exit 1
fi
echo "  ✓ 进程数 $NPROC"

echo "✓ DMG 验收通过"
