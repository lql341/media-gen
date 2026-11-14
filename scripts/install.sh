#!/usr/bin/env bash
# 把 media-gen 技能装到本机 agent 的技能目录。
#
#   ./scripts/install.sh                 自动挑位置（默认符号链接）
#   ./scripts/install.sh --pi            装到 Pi（~/.agents/skills）
#   ./scripts/install.sh --claude        装到 Claude Code（~/.claude/skills）
#   ./scripts/install.sh --codex         装到 Codex（~/.codex/skills）
#   ./scripts/install.sh --copy          复制而不是符号链接
#   ./scripts/install.sh --uninstall     删除安装点（不动本仓库）
set -euo pipefail

SKILL_NAME="media-gen"
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="auto"; LINK=yes; ACTION=install

for arg in "$@"; do
  case "$arg" in
    --pi|--agents) TARGET="agents" ;;
    --claude) TARGET="claude" ;;
    --codex) TARGET="codex" ;;
    --copy) LINK=no ;;
    --link) LINK=yes ;;
    --uninstall) ACTION=uninstall ;;
    -h|--help) sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "未知参数: $arg" >&2; exit 1 ;;
  esac
done

[ -f "$SRC_DIR/SKILL.md" ] || { echo "错误: 仓库根缺少 SKILL.md" >&2; exit 1; }

if [ "$TARGET" = auto ]; then
  if [ -d "$HOME/.agents" ]; then TARGET=agents
  elif [ -n "${CLAUDE_CONFIG_DIR:-}" ] || [ -d "$HOME/.claude" ]; then TARGET=claude
  elif [ -n "${CODEX_HOME:-}" ] || [ -d "$HOME/.codex" ]; then TARGET=codex
  else TARGET=agents; fi
fi

case "$TARGET" in
  agents) DST_ROOT="$HOME/.agents/skills" ;;
  claude) DST_ROOT="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/skills" ;;
  codex)  DST_ROOT="${CODEX_HOME:-$HOME/.codex}/skills" ;;
esac
DST="$DST_ROOT/$SKILL_NAME"

echo "==> 源:   $SRC_DIR"
echo "==> 目标: $DST"

if [ "$ACTION" = uninstall ]; then
  if [ -L "$DST" ]; then rm -f "$DST"; echo "已删除符号链接"
  elif [ -d "$DST" ]; then bak="$DST.bak.$(date +%Y%m%d%H%M%S)"; mv "$DST" "$bak"; echo "已移除目录（备份：${bak}）"
  else echo "未安装"; fi
  exit 0
fi

mkdir -p "$DST_ROOT"

if [ "$LINK" = yes ]; then
  if [ -L "$DST" ]; then
    current=$(readlink "$DST")
    [ "$current" = "$SRC_DIR" ] || { echo "已存在指向别处的链接：${current}（先 --uninstall）" >&2; exit 1; }
  elif [ -d "$DST" ]; then
    bak="$DST.bak.$(date +%Y%m%d%H%M%S)"; mv "$DST" "$bak"; echo "旧的实体目录已备份到 $bak"
  fi
  ln -sfn "$SRC_DIR" "$DST"
  echo "==> 已建立符号链接（改仓库即生效）"
else
  [ -L "$DST" ] && rm -f "$DST"
  mkdir -p "$DST/scripts" "$DST/references" "$DST/tests"
  cp "$SRC_DIR/SKILL.md" "$DST/SKILL.md"
  cp "$SRC_DIR"/references/*.md "$DST/references/"
  cp "$SRC_DIR"/scripts/*.py "$SRC_DIR"/scripts/*.sh "$SRC_DIR"/scripts/*.json "$DST/scripts/"
  [ -f "$SRC_DIR/VERSION" ] && cp "$SRC_DIR/VERSION" "$DST/VERSION"
  [ -d "$SRC_DIR/scripts/protocols" ] && cp -r "$SRC_DIR/scripts/protocols" "$DST/scripts/"
  chmod +x "$DST"/scripts/*.sh "$DST"/scripts/*.py
  echo "==> 已复制（仓库改动后需重跑本脚本）"
fi

echo
echo "下一步：重开 agent（或 /reload）→ /skill:$SKILL_NAME"
echo "配置端点：$DST/scripts/setup.sh add <name> --protocol openai --base-url https://host/v1"
