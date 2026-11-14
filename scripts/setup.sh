#!/usr/bin/env bash
# media-gen 配置入口（macOS / Linux）。交互界面在 Python 里实现，三个平台同一套：
# 同一目录还有 setup.ps1（Windows PowerShell），它们都只是转调 wizard.py / media_config.py。
#
#   scripts/setup.sh                      交互向导（推荐：新增/修改/删除/模板生成/MCP 片段）
#   scripts/setup.sh add <name> --protocol <openai|ark|dashscope|minimax|custom|command> --base-url <URL> [...]
#   scripts/setup.sh list | show <name> | audit | status [--profile P] | doctor [--profile P]
#   scripts/setup.sh set-url <name> --base-url <URL>
#   scripts/setup.sh set-key <name>        （stdin 传密钥）
#   scripts/setup.sh set-protocol <name> --protocol <p> [--custom-file F | --command-json J]
#   scripts/setup.sh rename <old> <new> | rm <name> [--keep-key] | rm --all
#   scripts/setup.sh export | import <file> | migrate
#
# 密钥默认进系统凭据库（macOS Keychain / secret-tool），Windows 无凭据库时落 0600 文件或环境变量。
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PY="${PYTHON:-python3}"

die() { printf 'error: %s\n' "$*" >&2; exit 1; }
command -v "$PY" >/dev/null 2>&1 || die "需要 python3（macOS: brew install python3 / Debian: apt install python3）"

usage() { sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'; }

action="${1:-}"
[ $# -gt 0 ] && shift || true

case "$action" in
  "")            exec "$PY" "$SCRIPT_DIR/wizard.py" ;;
  -h|--help|help) usage ;;
  doctor)        exec "$PY" "$SCRIPT_DIR/media.py" ${1:+"$@"} doctor ;;
  add)           exec "$PY" "$SCRIPT_DIR/media_config.py" add "$@" ;;
  use|list|show|audit|rm|rename|export|import|migrate) exec "$PY" "$SCRIPT_DIR/media_config.py" "$action" "$@" ;;
  set-key)       exec "$PY" "$SCRIPT_DIR/media_config.py" set-key "$@" ;;
  set-url)       exec "$PY" "$SCRIPT_DIR/media_config.py" set-url "$@" ;;
  set-protocol)  exec "$PY" "$SCRIPT_DIR/media_config.py" set-protocol "$@" ;;
  status)        exec "$PY" "$SCRIPT_DIR/media_config.py" status "$@" ;;
  modify|custom) exec "$PY" "$SCRIPT_DIR/wizard.py" "$action" ;;
  *)             usage >&2; die "未知动作：$action" ;;
esac
