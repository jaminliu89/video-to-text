#!/usr/bin/env bash
# scripts/build_release.sh — 打可分发包
#
# 产物（输出到 dist/）：
#   video2text-<version>.tar.gz      源码包（含 docs/tests，不含 cache/output）
#   video2text-<version>.zip         同上，Windows 友好
#   video2text-<version>-<sha>.tar.gz  按 commit 命名的快照（main 每次构建用）
#   SHA256SUMS.txt                   校验和
#
# 用法:
#   scripts/build_release.sh                # 版本取 VERSION 文件
#   VERSION=0.6.0 scripts/build_release.sh  # 临时覆盖
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

VERSION="${VERSION:-$(cat VERSION 2>/dev/null || echo 0.0.0)}"
SHA="$(git rev-parse --short=7 HEAD 2>/dev/null || echo nogit)"
NAME="video2text-${VERSION}"
SNAP="video2text-${VERSION}-${SHA}"

DIST="$ROOT/dist"
rm -rf "$DIST"
mkdir -p "$DIST"

# git archive 只打被追踪的文件：天然排除 cache/ output/ .env 等
make_archive() {
  local prefix="$1" out="$2"
  if git rev-parse --git-dir >/dev/null 2>&1; then
    git archive --format="$3" --prefix="${prefix}/" -o "$out" HEAD
  else
    echo "✗ 不在 git 仓库里，无法打包" >&2
    exit 1
  fi
}

make_archive "$NAME" "$DIST/$NAME.tar.gz" tar.gz
make_archive "$SNAP" "$DIST/$SNAP.tar.gz" tar.gz
make_archive "$NAME" "$DIST/$NAME.zip" zip

# 校验和（macOS 没有 sha256sum，用 shasum -a 256 兼容）
cd "$DIST"
if command -v sha256sum >/dev/null 2>&1; then
  sha256sum ./*.tar.gz ./*.zip > SHA256SUMS.txt
else
  shasum -a 256 ./*.tar.gz ./*.zip > SHA256SUMS.txt
fi

echo "✓ 构建完成 v$VERSION ($SHA)"
ls -lh "$DIST"
