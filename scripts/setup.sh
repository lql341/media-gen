#!/usr/bin/env bash
# media-gen 配置面板（多配置档：每个端点一个 profile）
#
#   scripts/setup.sh                       交互面板
#   scripts/setup.sh add <name> --protocol <openai|ark|dashscope|minimax> --base-url <URL>
#   scripts/setup.sh use <name>            设为默认
#   scripts/setup.sh list                  列出配置档
#   scripts/setup.sh rm <name> [--keep-key]
#   scripts/setup.sh status [--profile P]  当前生效的地址/密钥来源（脱敏）
#   scripts/setup.sh doctor [--profile P]  只读：GET /models + 媒体模型覆盖情况
#   scripts/setup.sh migrate               把旧 seedance 配置迁成 profile
#
# 密钥不进 argv、不进仓库：默认进系统凭据库（macOS Keychain / secret-tool），
# 环境变量 MEDIA_API_KEY[_<PROFILE>] 永远优先。
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
CONFIG="$SCRIPT_DIR/media_config.py"
MEDIA="$SCRIPT_DIR/media.py"
PY="${PYTHON:-python3}"

die() { printf 'error: %s\n' "$*" >&2; exit 1; }
cfg() { "$PY" "$CONFIG" "$@"; }

usage() { sed -n '2,19p' "$0" | sed 's/^# \{0,1\}//'; }

ask() {
  local prompt="$1" default="${2:-}" answer
  if [ -n "$default" ]; then printf '%s [%s]: ' "$prompt" "$default" >&2; else printf '%s: ' "$prompt" >&2; fi
  read -r answer || true
  printf '%s' "${answer:-$default}"
}

ask_secret() {
  local answer
  printf 'API Key（输入不显示，留空=暂不保存）: ' >&2
  read -r -s answer || true
  printf '\n' >&2
  printf '%s' "$answer"
}

need_tty() { [ -t 0 ] || die "交互配置需要终端；非交互请给 --key-stdin / 环境变量 MEDIA_API_KEY"; }

panel() {
  printf '\n== media-gen 配置 ==\n'
  printf '1) 新增/更新端点（add）\n2) 设为默认（use）\n3) 列出（list）\n4) 状态（status）\n5) 自检（doctor）\n6) 迁移旧 seedance 配置\n7) 删除（rm）\n'
  local choice; choice=$(ask "选择" "4")
  case "$choice" in
    1) do_add ;;
    2) cfg list; cfg use "$(ask '配置档名')" ;;
    3) cfg list ;;
    4) cfg status ;;
    5) "$PY" "$MEDIA" doctor ;;
    6) cfg migrate ;;
    7) cfg list; cfg rm "$(ask '配置档名')" ;;
    *) die "无效选择：$choice" ;;
  esac
}

do_add() {
  need_tty
  printf '\n-- 新增/更新端点 --\n'
  printf 'protocol: openai（OpenAI/LiteLLM 兼容网关）· ark（火山原生）· dashscope（阿里云百炼）· minimax（MiniMax 原生）\n' >&2
  local name protocol base key extra
  name=$(ask "配置档名" "default")
  protocol=$(ask "protocol" "openai")
  base=$(ask "base_url（必填）")
  [ -n "$base" ] || die "base_url 不能为空"
  key=$(ask_secret)
  extra=()
  local img vid
  img=$(ask "默认图片模型（可留空）" "")
  vid=$(ask "默认视频模型（可留空）" "")
  [ -n "$img" ] && extra+=(--default-image "$img")
  [ -n "$vid" ] && extra+=(--default-video "$vid")
  if [ -n "$key" ]; then
    printf '%s' "$key" | cfg add "$name" --protocol "$protocol" --base-url "$base" --key-stdin --set-default "${extra[@]}"
  else
    cfg add "$name" --protocol "$protocol" --base-url "$base" --set-default "${extra[@]}"
  fi
  printf '\n建议立刻验证：scripts/setup.sh doctor --profile %s\n' "$name" >&2
}

main() {
  command -v "$PY" >/dev/null 2>&1 || die "需要 python3"
  local action="${1:-}"; [ $# -gt 0 ] && shift || true
  case "$action" in
    add|use|rm|list|migrate) cfg "$action" "$@" ;;
    status)  cfg status "$@" ;;
    doctor)  "$PY" "$MEDIA" doctor "$@" ;;
    "")      panel ;;
    -h|--help|help) usage ;;
    *) usage >&2; die "未知动作：$action" ;;
  esac
}

main "$@"
