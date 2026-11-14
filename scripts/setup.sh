#!/usr/bin/env bash
# media-gen 配置面板（多配置档：每个端点一个 profile）
#
#   scripts/setup.sh                       交互面板
#   scripts/setup.sh add <name> --protocol <openai|ark|dashscope|minimax|custom|command> --base-url <URL>
#   scripts/setup.sh modify <name>          交互修改（地址 / 密钥 / 协议 / 默认模型）
#   scripts/setup.sh show <name>            查看单个配置档（密钥脱敏）
#   scripts/setup.sh set-url <name> --base-url <URL>
#   scripts/setup.sh set-key <name>         只换密钥（隐藏输入）
#   scripts/setup.sh set-protocol <name> --protocol <p> [--custom-file F | --command-json J]
#   scripts/setup.sh rename <old> <new>
#   scripts/setup.sh use <name>            设为默认
#   scripts/setup.sh list                  列出配置档
#   scripts/setup.sh rm <name> [--keep-key] | rm --all
#   scripts/setup.sh export | import <file>  配置迁移（不含密钥）
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

usage() { sed -n '2,21p' "$0" | sed 's/^# \{0,1\}//'; }

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
  printf '1) 新增端点（add）\n2) 修改已有（modify）\n3) 设为默认（use）\n4) 列出（list）\n5) 查看单个（show）\n6) 状态（status）\n7) 自检（doctor）\n8) 迁移旧 seedance 配置\n9) 删除（rm）\n'
  local choice; choice=$(ask "选择" "6")
  case "$choice" in
    1) do_add ;;
    2) do_modify ;;
    3) cfg list; cfg use "$(ask '配置档名')" ;;
    4) cfg list ;;
    5) cfg list; cfg show "$(ask '配置档名')" ;;
    6) cfg status ;;
    7) "$PY" "$MEDIA" doctor ;;
    8) cfg migrate ;;
    9) cfg list; cfg rm "$(ask '配置档名')" ;;
    *) die "无效选择：$choice" ;;
  esac
}

do_modify() {
  cfg list
  local name; name=$(ask "要修改的配置档")
  [ -n "$name" ] || die "需要配置档名"
  cfg show "$name" >/dev/null || die "配置档 $name 不存在"
  printf '1) 地址  2) 密钥  3) 协议  4) 默认模型  5) 改名  6) 删除\n'
  local what; what=$(ask "修改哪一项" "1")
  case "$what" in
    1) cfg set-url "$name" --base-url "$(ask '新地址')" ;;
    2)
      need_tty
      local key; key=$(ask_secret)
      [ -n "$key" ] || die "未输入密钥，已取消"
      printf '%s' "$key" | cfg set-key "$name"
      ;;
    3)
      local proto; proto=$(ask "新协议（openai/ark/dashscope/minimax/custom/command）" "openai")
      if [ "$proto" = custom ]; then
        cfg set-protocol "$name" --protocol custom --custom-file "$(ask '模板文件路径')"
      elif [ "$proto" = command ]; then
        cfg set-protocol "$name" --protocol command --command-file "$(ask '命令表 JSON 文件路径')"
      else
        cfg set-protocol "$name" --protocol "$proto"
      fi
      ;;
    4)
      local kind model
      kind=$(ask "改图片还是视频默认模型（image/video）" "video")
      model=$(ask "模型 id")
      [ -n "$model" ] || die "模型 id 不能为空"
      if [ "$kind" = image ]; then
        cfg add "$name" --protocol "$(cfg get-protocol --profile "$name")" \
          --base-url "$(cfg get-base-url --profile "$name")" --default-image "$model"
      else
        cfg add "$name" --protocol "$(cfg get-protocol --profile "$name")" \
          --base-url "$(cfg get-base-url --profile "$name")" --default-video "$model"
      fi
      ;;
    5) cfg rename "$name" "$(ask '新名字')" ;;
    6) cfg rm "$name" ;;
    *) die "无效选择：$what" ;;
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
    add|use|rm|list|show|set-key|set-url|set-protocol|rename|export|import|migrate)
      cfg "$action" "$@" ;;
    modify) do_modify "$@" ;;
    status)  cfg status "$@" ;;
    doctor)  "$PY" "$MEDIA" doctor "$@" ;;
    "")      panel ;;
    -h|--help|help) usage ;;
    *) usage >&2; die "未知动作：$action" ;;
  esac
}

main "$@"
