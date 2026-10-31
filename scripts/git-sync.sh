#!/usr/bin/env bash
# scripts/git-sync.sh — 一条命令让本地仓库和远端保持一致
#
# 做的事（顺序固定，出错就停）：
#   1. git pull --rebase --autostash   先把远端的新提交接上，本地改动暂存不丢
#   2. git add -A && git commit        有改动就提交（没有就跳过）
#   3. git push                        推回远端
#
# 为什么是 rebase 而不是 merge：自动同步天天跑，merge commit 会把历史糊成一片。
#
# 用法:
#   scripts/git-sync.sh                     # 默认：pull → commit → push
#   scripts/git-sync.sh --message "xxx"     # 自定义提交信息
#   scripts/git-sync.sh --pull-only         # 只拉不推（定时更新代码用）
#   scripts/git-sync.sh --no-commit         # 只同步，不自动提交本地改动
#   scripts/git-sync.sh --install-hooks     # 装 post-commit 钩子（提交后自动 push）
#
# 定时跑（每 30 分钟拉一次远端）:
#   crontab -e
#   */30 * * * * /绝对路径/scripts/git-sync.sh --pull-only >> ~/.video2text-sync.log 2>&1
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

MSG=""
PULL_ONLY=0
DO_COMMIT=1

while [[ $# -gt 0 ]]; do
  case "$1" in
    --message|-m) MSG="${2:-}"; shift 2 ;;
    --pull-only)  PULL_ONLY=1; shift ;;
    --no-commit)  DO_COMMIT=0; shift ;;
    --install-hooks)
      mkdir -p .githooks
      chmod +x .githooks/* 2>/dev/null || true
      git config core.hooksPath .githooks
      echo "✓ 已启用 .githooks（post-commit 会自动 push）"
      exit 0 ;;
    -h|--help) sed -n '2,25p' "$0"; exit 0 ;;
    *) echo "未知参数: $1" >&2; exit 2 ;;
  esac
done

if ! git rev-parse --git-dir >/dev/null 2>&1; then
  echo "✗ 当前目录不是 git 仓库：$ROOT" >&2
  exit 1
fi

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
echo "▸ 分支 ${BRANCH}"

# ---------- 1. 拉取 ----------
if git remote get-url origin >/dev/null 2>&1; then
  echo "▸ 拉取远端更新…"
  if git pull --rebase --autostash origin "${BRANCH}" 2>&1 | sed 's/^/  /'; then
    :
  else
    echo "✗ 拉取失败（可能有冲突）。已用 --autostash，本地改动还在工作区。" >&2
    echo "  手动处理后重跑：git rebase --continue" >&2
    exit 1
  fi
else
  echo "· 没有 origin 远端，跳过拉取"
fi

if [[ "$PULL_ONLY" == "1" ]]; then
  echo "✓ 已同步到 $(git log --oneline -1)"
  exit 0
fi

# ---------- 2. 提交 ----------
if [[ "$DO_COMMIT" == "1" ]]; then
  if [[ -n "$(git status --porcelain)" ]]; then
    [[ -z "$MSG" ]] && MSG="chore: 自动同步 $(date '+%Y-%m-%d %H:%M')"
    echo "▸ 提交本地改动：$MSG"
    git add -A
    # 万一 pre-commit 钩子改文件，重试一次
    git commit -q -m "$MSG" || git commit -q -m "$MSG"
  else
    echo "· 工作区干净，无需提交"
  fi
fi

# ---------- 3. 推送 ----------
if git remote get-url origin >/dev/null 2>&1; then
  echo "▸ 推送到 origin/${BRANCH}…"
  git push -q origin "${BRANCH}"
  echo "✓ 已推送：$(git log --oneline -1)"
else
  echo "· 没有 origin 远端，跳过推送"
fi
