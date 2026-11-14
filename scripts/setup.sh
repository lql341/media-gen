#!/usr/bin/env bash
# Seedance 网关配置面板（地址 + API Key）。
#
#   scripts/setup.sh               交互面板
#   scripts/setup.sh new           首次配置
#   scripts/setup.sh modify        换地址 / 换密钥 / 换默认模型
#   scripts/setup.sh status        看实际生效的地址与密钥来源（脱敏）
#   scripts/setup.sh doctor        只读检查 GET /models 与视频模型是否在列表
#   scripts/setup.sh reset [--all] 清除密钥（--all 连地址一起清）
#
# 非交互（CI / 工作站初始化）：
#   SEEDANCE_API_KEY=... scripts/setup.sh new --no-verify --base-url https://gw.example/v1
#   scripts/setup.sh new --key-from-agent          # 复用 ~/.pi/agent/auth.json 里的 key
#   printf '%s' "$KEY" | scripts/setup.sh new --key-stdin --store auto
#
# 密钥只在本机终端输入，不回显、不进 argv、不写仓库。
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
CONFIG="$SCRIPT_DIR/seedance_config.py"
PY="${PYTHON:-python3}"

ACTION=""
BASE_URL=""
STORE="auto"
MODEL=""
KEY_FROM_AGENT=no
KEY_STDIN=no
VERIFY=yes
CLEAR_ALL=no

usage() { sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }
cfg() { "$PY" "$CONFIG" "$@"; }

while [ $# -gt 0 ]; do
  case "$1" in
    new|modify|status|doctor|reset) ACTION="$1"; shift ;;
    --base-url) BASE_URL="$2"; shift 2 ;;
    --base-url=*) BASE_URL="${1#*=}"; shift ;;
    --model) MODEL="$2"; shift 2 ;;
    --model=*) MODEL="${1#*=}"; shift ;;
    --store) STORE="$2"; shift 2 ;;
    --store=*) STORE="${1#*=}"; shift ;;
    --key-from-agent) KEY_FROM_AGENT=yes; shift ;;
    --key-stdin) KEY_STDIN=yes; shift ;;
    --no-verify) VERIFY=no; shift ;;
    --all) CLEAR_ALL=yes; shift ;;
    -h|--help|help) usage; exit 0 ;;
    *) die "未知参数：$1" ;;
  esac
done

need_tty() {
  [ -t 0 ] || die "配置需要交互式终端；非交互请用 --key-stdin / --key-from-agent 或环境变量 SEEDANCE_API_KEY"
}

ask() {  # ask 提示 默认值 -> stdout
  local prompt="$1" default="${2:-}" answer
  if [ -n "$default" ]; then
    printf '%s [%s]: ' "$prompt" "$default" >&2
  else
    printf '%s: ' "$prompt" >&2
  fi
  read -r answer || true
  printf '%s' "${answer:-$default}"
}

ask_secret() {  # 不回显；空输入表示保留现值
  local answer
  printf '网关 API Key（输入不显示，留空=保留现有配置）: ' >&2
  read -r -s answer || true
  printf '\n' >&2
  printf '%s' "$answer"
}

current_base() { cfg get-base-url 2>/dev/null || printf ''; }
current_model() { cfg get-model 2>/dev/null || printf ''; }

write_config() {  # write_config <base> <model> [key]
  local base="$1" model="$2" key="${3:-}"
  local args=(set --store "$STORE")
  [ "$VERIFY" = yes ] || args+=(--no-verify)
  [ -n "$base" ] && args+=(--base-url "$base")
  [ -n "$model" ] && args+=(--model "$model")
  if [ -n "$key" ]; then
    printf '%s' "$key" | cfg "${args[@]}" --key-stdin
  else
    cfg "${args[@]}"
  fi
}

panel() {
  printf '\n== Seedance 网关配置 ==\n'
  printf '1) 首次配置（new）\n'
  printf '2) 修改地址/密钥（modify）\n'
  printf '3) 查看状态（status）\n'
  printf '4) 只读检查（doctor）\n'
  printf '5) 清除密钥（reset）\n'
  local choice
  choice=$(ask "选择" "3")
  case "$choice" in
    1) do_write new ;;
    2) do_write modify ;;
    3) cfg status ;;
    4) cfg doctor ;;
    5) do_reset ;;
    *) die "无效选择：$choice" ;;
  esac
}

do_write() {  # do_write new|modify
  local action="$1"
  printf '\n-- %s --\n' "$action"
  printf '网关地址要指向 LiteLLM（或任何实现 OpenAI Videos 路由的服务），形如 https://host/v1\n' >&2
  local base model key
  base="$BASE_URL"
  [ -n "$base" ] || base=$(ask "网关地址" "$(current_base)")
  model="$MODEL"
  [ -n "$model" ] || model=$(ask "默认模型" "$(current_model)")
  key=""
  if [ "$KEY_FROM_AGENT" = yes ]; then
    cfg import --store "$STORE" || die "导入失败"
    write_config "$base" "$model"
    return 0
  fi
  if [ "$KEY_STDIN" = yes ]; then
    key=$(cat)
  elif [ ! -t 0 ]; then
    die "非交互模式请显式给 --key-stdin 或 --key-from-agent"
  else
    key=$(ask_secret)
  fi
  write_config "$base" "$model" "$key"
}

do_reset() {
  local args=()
  [ "$CLEAR_ALL" = yes ] && args+=(--all)
  printf '这会清除本机保存的 Seedance 密钥。继续？[y/N]: ' >&2
  local answer; read -r answer || true
  case "$answer" in
    y|Y|yes|YES) cfg reset "${args[@]}" ;;
    *) echo "已取消" ;;
  esac
}

main() {
  command -v "$PY" >/dev/null 2>&1 || die "需要 python3"
  [ -f "$CONFIG" ] || die "缺少 $CONFIG"
  case "$ACTION" in
    status) cfg status ;;
    doctor) cfg doctor ;;
    reset)  do_reset ;;
    new|modify)
      if [ "$KEY_FROM_AGENT" = no ] && [ "$KEY_STDIN" = no ] && [ -n "${SEEDANCE_API_KEY:-}${LEGACY_API_KEY:-}" ]; then
        # 已经有环境变量就直接落盘/入库，不必再问一遍；这之后环境变量仍然优先
        printf '检测到环境变量里的密钥，正在 %s 模式下保存（之后可用 setup.sh status 复核来源）。\n' "$STORE" >&2
        write_config "$BASE_URL" "$MODEL" "${SEEDANCE_API_KEY:-${LEGACY_API_KEY:-}}"
      else
        if [ "$KEY_STDIN" = no ] && [ "$KEY_FROM_AGENT" = no ] && [ -z "${SEEDANCE_API_KEY:-}${LEGACY_API_KEY:-}" ]; then
          need_tty
        fi
        do_write "$ACTION"
      fi
      ;;
    "")   panel ;;
    *)    usage >&2; die "未知动作：$ACTION" ;;
  esac
}

main "$@"
