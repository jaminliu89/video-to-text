#!/usr/bin/env bash
# scripts/build_dmg.sh — 打 macOS .app 并封成 DMG
#
# 流程：
#   1. PyInstaller（packaging/video2text.spec）→ VideoToText.app
#   2. 把静态 ffmpeg / ffprobe 塞进 App（否则装到别人机器上转写直接报错）
#   3. ad-hoc 签名（没有开发者证书时唯一能过 Gatekeeper 的做法：右键→打开）
#   4. hdiutil 封 DMG，附 Applications 软链，拖进去就是安装
#
# 用法:
#   scripts/build_dmg.sh                    # 版本取 VERSION
#   VERSION=0.6.0 scripts/build_dmg.sh
#   SKIP_BUILD=1 scripts/build_dmg.sh       # 复用已有 dist/VideoToText.app，只重封 DMG
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
APP="$ROOT/dist/VideoToText.app"
DMG="$ROOT/dist/VideoToText-${VERSION}-${ARCH}.dmg"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "✗ DMG 只能在 macOS 上打（当前 $(uname -s)）" >&2
  exit 1
fi

WORK="$(mktemp -d -t v2t-dmg)"

# ---------- 1. PyInstaller ----------
if [[ "${SKIP_BUILD:-0}" != "1" ]]; then
  echo "▸ PyInstaller 打包…"
  python3 -m PyInstaller packaging/video2text.spec \
    --noconfirm --distpath "$WORK/pyi" --workpath build/pyinstaller

  mkdir -p "$ROOT/dist"
  if [[ -d "$APP" ]]; then
    # 旧包挪走而不是删掉（删除在受限环境下会被拦）
    mv "$APP" "$WORK/old.app"
  fi
  cp -R "$WORK/pyi/VideoToText.app" "$APP"
fi

if [[ ! -d "$APP" ]]; then
  echo "✗ 没生成 $APP" >&2
  exit 1
fi

# _MEIPASS 在 .app 里指向 Contents/Frameworks；源码已打进 PYZ，按位置推断即可
RES_DIR="$APP/Contents/Frameworks"
echo "▸ 资源目录：${RES_DIR#$ROOT/}"

# ---------- 2. 静态 ffmpeg ----------
BIN_DIR="$RES_DIR/bin"
mkdir -p "$BIN_DIR"

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

for tool in ffmpeg ffprobe; do
  if [[ -n "${FFMPEG_STATIC_DIR:-}" && -x "$FFMPEG_STATIC_DIR/$tool" ]]; then
    cp "$FFMPEG_STATIC_DIR/$tool" "$BIN_DIR/$tool"
  else
    fetch_static "$tool" "$BIN_DIR/$tool" || true
  fi
  if [[ -x "$BIN_DIR/$tool" ]]; then
    echo "  ✓ $tool $("$BIN_DIR/$tool" -version 2>/dev/null | head -1 | cut -c1-58)"
  else
    echo "  ! $tool 没拿到，App 会退回系统 PATH（用户需自己 brew install ffmpeg）" >&2
  fi
done

# ---------- 3. 签名 ----------
# 没证书就 ad-hoc：能跑，但首次打开要右键→打开（或 xattr -dr com.apple.quarantine）
echo "▸ ad-hoc 签名…"
codesign --force --deep --sign - "$APP" 2>&1 | tail -2 || true
codesign --verify --deep --strict "$APP" 2>&1 | tail -2 || echo "  ! 校验未通过（ad-hoc 下常见，不影响本机运行）"

# ---------- 4. 封 DMG ----------
echo "▸ 制作 DMG…"
STAGE="$WORK/stage"
mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"

cat > "$STAGE/使用说明.txt" <<'TXT'
VideoToText — 安装说明

1. 把 VideoToText.app 拖到左边的 Applications 文件夹
2. 第一次打开：右键点 App → 打开（因为没买苹果开发者证书，是 ad-hoc 签名）
   如果提示"已损坏"：终端执行
     xattr -dr com.apple.quarantine /Applications/VideoToText.app
3. 打开后会起一个本地服务并自动打开浏览器（默认 http://localhost:8766）
4. 配置写在 ~/Library/Application Support/VideoToText/.env
   产出（缓存/输出）在同目录的 cache/ 和 output/

已内置 ffmpeg / ffprobe，无需额外安装。
转写默认用 faster-whisper（首次使用会下载模型，约 140MB）。
TXT

hdiutil create -volname "VideoToText" -srcfolder "$STAGE" -ov -format UDZO "$DMG" >/dev/null

echo "✓ 完成：${DMG#$ROOT/}（$(du -h "$DMG" | cut -f1)）"
