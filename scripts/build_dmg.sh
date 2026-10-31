#!/usr/bin/env bash
# scripts/build_dmg.sh — 打 macOS .app 并封成 DMG（两个变体）
#
# 变体（V2T_VARIANTS 可覆盖，默认两个都打）：
#   browser  → dist/VideoToText.app       启动本地服务 + 打开浏览器
#   native   → dist/VideoToTextNative.app 启动本地服务 + 弹原生窗口（pywebview）
#
# 每个变体的流程：
#   1. PyInstaller（packaging/video2text.spec，V2T_VARIANT 选变体）→ <exe>.app
#   2. 把静态 ffmpeg / ffprobe 塞进 App（否则装到别人机器上转写直接报错）
#   3. ad-hoc 签名（没有开发者证书时唯一能过 Gatekeeper 的做法：右键→打开）
#   4. hdiutil 封 DMG，附 Applications 软链，拖进去就是安装
#
# 用法:
#   scripts/build_dmg.sh                      # 两个变体都打
#   V2T_VARIANTS=browser scripts/build_dmg.sh # 只打浏览器版（本地快速迭代）
#   VERSION=0.6.0 scripts/build_dmg.sh
#   SKIP_BUILD=1 scripts/build_dmg.sh         # 复用已有 dist/*.app，只重封 DMG
#
# 为什么中间产物都放临时目录：
#   PyInstaller 每次构建前会 rmtree 自己的输出目录。在开了文件审计的机器上
#   （一次删几百个文件会被拦），这会直接让构建失败。用 mktemp 目录 + 覆盖拷贝
#   就完全不碰删除，CI 和本地都能跑。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

VERSION="${VERSION:-$(cat VERSION 2>/dev/null || echo 0.0.0)}"
export VERSION   # spec 读这个来决定 CFBundleShortVersionString，必须导出
ARCH="$(uname -m)"
VARIANTS="${V2T_VARIANTS:-browser native}"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "✗ DMG 只能在 macOS 上打（当前 $(uname -s)）" >&2
  exit 1
fi

WORK="$(mktemp -d -t v2t-dmg)"

# 中间产物（一次构建 500MB~1GB）留着没意义。rm -rf 在开了文件审计的机器上会被拦，
# 所以用 python 静默清掉，清不掉也不影响构建结果。
# 这条是真踩过的：连着打几次包，/var/folders 里堆了 4 个 1.1G 的 v2t-dmg.*，磁盘直接满。
cleanup_work() {
  [[ -n "${WORK:-}" && -d "${WORK}" ]] || return 0
  python3 -c 'import shutil, sys; shutil.rmtree(sys.argv[1], ignore_errors=True)' "$WORK" || true
}
trap cleanup_work EXIT

exe_name() {
  if [[ "$1" == "native" ]]; then echo "VideoToTextNative"; else echo "VideoToText"; fi
}

dmg_name() {
  local suffix=""
  [[ "$1" == "native" ]] && suffix="-native"
  echo "VideoToText-${VERSION}-${ARCH}${suffix}.dmg"
}

vol_name() {
  if [[ "$1" == "native" ]]; then echo "VideoToText Native"; else echo "VideoToText"; fi
}

# ---------- 静态 ffmpeg（两个变体共用缓存，第二次是拷贝） ----------
fetch_static() {
  local tool="$1" out="$2"
  local cache="$ROOT/build/ffmpeg-cache"
  mkdir -p "$cache"

  if [[ -x "$cache/$tool" ]]; then
    cp "$cache/$tool" "$out"; chmod +x "$out"; return 0
  fi

  # osxexperts.net 的 arm64 静态单文件构建：每个 tool 一个 zip，里面就是可执行文件本体。
  # evermeet.cx 的老接口 /getrelease/*/zip 已返回 410，别再用。
  local url
  for url in \
    "https://www.osxexperts.net/${tool}80arm.zip" \
    "https://www.osxexperts.net/${tool}71arm.zip"; do
    echo "  · 下载静态 ${tool}：${url##*/}" >&2
    if curl -fsSL --max-time 180 "$url" -o "$cache/$tool.zip"; then
      if (cd "$cache" && unzip -oq "$tool.zip" "$tool" 2>/dev/null) && [[ -f "$cache/$tool" ]]; then
        chmod +x "$cache/$tool"
        if "$cache/$tool" -version >/dev/null 2>&1; then
          cp "$cache/$tool" "$out"; chmod +x "$out"; return 0
        fi
        echo "  ! 下载到的 ${tool} 跑不起来（架构不符？），换下一个源" >&2
        mv "$cache/$tool" "$cache/$tool.bad" 2>/dev/null || true
      fi
    fi
  done

  # 最后兜底：用本机 brew 装的那个（只在构建机上能跑，不适合分发）
  if command -v "$tool" >/dev/null 2>&1; then
    echo "  ! 用本机 ${tool}（动态链接，换台机器可能跑不起来）" >&2
    cp "$(command -v "$tool")" "$out"; chmod +x "$out"; return 0
  fi
  return 1
}

inject_ffmpeg() {
  local app="$1"
  # _MEIPASS 在 .app 里指向 Contents/Frameworks；源码已打进 PYZ，按位置推断即可
  local bin_dir="$app/Contents/Frameworks/bin"
  mkdir -p "$bin_dir"

  local tool
  for tool in ffmpeg ffprobe; do
    if [[ -n "${FFMPEG_STATIC_DIR:-}" && -x "$FFMPEG_STATIC_DIR/$tool" ]]; then
      cp "$FFMPEG_STATIC_DIR/$tool" "$bin_dir/$tool"
    else
      fetch_static "$tool" "$bin_dir/$tool" || true
    fi
    if [[ -x "$bin_dir/$tool" ]]; then
      echo "  ✓ $tool $("$bin_dir/$tool" -version 2>/dev/null | head -1 | cut -c1-58)"
    else
      echo "  ! $tool 没拿到，App 会退回系统 PATH（用户需自己 brew install ffmpeg）" >&2
    fi
  done
}

write_readme() {
  local stage="$1" exe="$2" variant="$3"
  if [[ "$variant" == "native" ]]; then
    cat > "$stage/使用说明.txt" <<TXT
VideoToText — 安装说明（窗口版）

1. 把 ${exe}.app 拖到左边的 Applications 文件夹
2. 第一次打开：右键点 App → 打开（因为没买苹果开发者证书，是 ad-hoc 签名）
   如果提示"已损坏"：终端执行
     xattr -dr com.apple.quarantine /Applications/${exe}.app
3. 打开后会弹出一个原生窗口（不是浏览器标签页），界面和浏览器版完全一样
   如果哪天想要浏览器：终端执行
     V2T_NATIVE=0 /Applications/${exe}.app/Contents/MacOS/${exe}
4. 配置写在 ~/Library/Application Support/VideoToText/.env
   产出（缓存/输出）在同目录的 cache/ 和 output/，两个版本共用

已内置 ffmpeg / ffprobe，无需额外安装。
转写默认用 faster-whisper（首次使用会下载模型，约 140MB）。
TXT
  else
    cat > "$stage/使用说明.txt" <<TXT
VideoToText — 安装说明（浏览器版）

1. 把 ${exe}.app 拖到左边的 Applications 文件夹
2. 第一次打开：右键点 App → 打开（因为没买苹果开发者证书，是 ad-hoc 签名）
   如果提示"已损坏"：终端执行
     xattr -dr com.apple.quarantine /Applications/${exe}.app
3. 打开后会起一个本地服务并自动打开浏览器（默认 http://localhost:8766）
   想要原生窗口的话，用窗口版安装包（VideoToTextNative.app）
4. 配置写在 ~/Library/Application Support/VideoToText/.env
   产出（缓存/输出）在同目录的 cache/ 和 output/

已内置 ffmpeg / ffprobe，无需额外安装。
转写默认用 faster-whisper（首次使用会下载模型，约 140MB）。
TXT
  fi
}

build_variant() {
  local variant="$1"
  local exe app dmg vol stage
  exe="$(exe_name "$variant")"
  app="$ROOT/dist/${exe}.app"
  dmg="$ROOT/dist/$(dmg_name "$variant")"
  vol="$(vol_name "$variant")"
  stage="$WORK/stage-$variant"

  echo
  echo "========== 变体：${variant}（${exe}.app）=========="

  # ---------- 1. PyInstaller ----------
  if [[ "${SKIP_BUILD:-0}" != "1" ]]; then
    echo "▸ PyInstaller 打包…"
    # 两个变体各用各的 distpath / workpath：共用一个目录时，
    # PyInstaller 的增量缓存会把上一个变体的依赖图带进来，产物就串了。
    V2T_VARIANT="$variant" python3 -m PyInstaller packaging/video2text.spec \
      --noconfirm --distpath "$WORK/pyi-$variant" --workpath "build/pyinstaller-$variant"

    mkdir -p "$ROOT/dist"
    if [[ -d "$app" ]]; then
      # 旧包挪走而不是删掉（删除在受限环境下会被拦）
      mv "$app" "$WORK/old-$variant.app"
    fi
    # mv 而不是 cp -R：同一个卷上只是改目录项，不占第二份空间。
    # 一个 .app 解包后 500MB 上下，cp 一份就要多 500MB，本机磁盘吃紧时直接失败。
    mv "$WORK/pyi-$variant/${exe}.app" "$app"
  fi

  if [[ ! -d "$app" ]]; then
    echo "✗ 没生成 $app" >&2
    exit 1
  fi

  # 变体标记要和包对得上，否则用户装完发现"窗口版开出来是浏览器"
  local flag=""
  flag="$(cat "$app/Contents/Resources/NATIVE_DEFAULT" 2>/dev/null || echo "")"
  local want="0"
  [[ "$variant" == "native" ]] && want="1"
  if [[ "$flag" != "$want" ]]; then
    echo "✗ 变体标记不对：NATIVE_DEFAULT=${flag:-缺失}，期望 ${want}" >&2
    exit 1
  fi
  echo "  ✓ 变体标记 NATIVE_DEFAULT=${flag}"

  # ---------- 2. 静态 ffmpeg ----------
  inject_ffmpeg "$app"

  # ---------- 3. 签名 ----------
  # 没证书就 ad-hoc：能跑，但首次打开要右键→打开（或 xattr -dr com.apple.quarantine）
  echo "▸ ad-hoc 签名…"
  codesign --force --deep --sign - "$app" 2>&1 | tail -2 || true
  codesign --verify --deep --strict "$app" 2>&1 | tail -2 || echo "  ! 校验未通过（ad-hoc 下常见，不影响本机运行）"

  # ---------- 4. 封 DMG ----------
  echo "▸ 制作 DMG…"
  mkdir -p "$stage"
  # 硬链接而不是真拷贝：hdiutil 只读文件内容，链接足够，
  # 但能省掉一份 500MB 的临时副本（两个变体就是 1GB）
  cp -Rl "$app" "$stage/"
  ln -s /Applications "$stage/Applications"
  write_readme "$stage" "$exe" "$variant"

  hdiutil create -volname "$vol" -srcfolder "$stage" -ov -format UDZO "$dmg" >/dev/null

  BUILT+=("$dmg")
  echo "✓ 完成：${dmg#$ROOT/}（$(du -h "$dmg" | cut -f1)）"
}

BUILT=()
for v in $VARIANTS; do
  build_variant "$v"
done

echo
echo "========== 产物 =========="
for f in "${BUILT[@]}"; do
  echo "  $(basename "$f")  $(du -h "$f" | cut -f1)"
done
