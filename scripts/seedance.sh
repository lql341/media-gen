#!/usr/bin/env bash
# 通过 LiteLLM 网关的 OpenAI Videos 风格路由调用 Seedance 视频模型
#   doubao-seedance-2-5 / doubao-seedance-2-0-260128
#
#   POST   /videos                  建任务，立刻返回 video_... id（status=queued）
#   GET    /videos/<id>             轮询（queued → processing → completed/failed）
#   GET    /videos/<id>/content     下载成片（307，必须跟随重定向）
#   DELETE /videos/<id>             删除
#
# 这两个模型只有 video deployment：打 /chat/completions 会得到
#   429 No deployments available for selected model
# 它们不能当 chat 模型用，也不能写进任何客户端的 models.json。
#
# 计费按视频 token 计（随分辨率、时长与提供商价格表变化），run 之前先想清楚。
#
# 配置（地址 + 密钥）不写在本文件里：见 scripts/seedance_config.py 与 scripts/setup.sh。
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
CONFIG="$SCRIPT_DIR/seedance_config.py"
PY="${PYTHON:-python3}"

die() { printf 'error: %s\n' "$*" >&2; exit 1; }
need() { command -v "$1" >/dev/null 2>&1 || die "缺少依赖：$1"; }

# 地址、密钥、默认模型统一由 config 模块解析：
# 环境变量 → 系统凭据库 → config.json（0600） → agent auth 文件（只读导入）
cfg() { "$PY" "$CONFIG" "$@"; }

BASE=""
MODEL=""
KEY=""
resolve_config() {
  [ -n "$BASE" ] && return 0
  BASE=$(cfg get-base-url) || die "没有网关地址；运行 scripts/setup.sh new --base-url https://host/v1"
  MODEL=$(cfg get-model) || MODEL="doubao-seedance-2-5"
  KEY=$(cfg get-key) || die "没有可用密钥；运行 scripts/setup.sh new（或设置 SEEDANCE_API_KEY）"
}

api_key() { resolve_config; printf '%s' "$KEY"; }

# 认证头走 curl 的 --config（从 fd 读），不上命令行：
# 否则 `ps -ax` 能看到 `Authorization: Bearer <key>`，同机其它用户即可读走密钥。
auth_config() { printf 'header = "Authorization: Bearer %s"\n' "$(api_key)"; }

api() {  # api METHOD PATH [JSON_BODY] [-F ...]
  local method="$1" path="$2"; shift 2
  resolve_config
  curl -sS -m "${SEEDANCE_TIMEOUT:-120}" -X "$method" "$BASE$path" \
    --config <(auth_config) "$@"
}

# 把字段拼成请求体；-1 表示让模型自选时长（网关只接受 4..30 或 -1）
build_body() {
  "$PY" - <<'PY'
import json, os
body = {"model": os.environ["SD_MODEL"], "prompt": os.environ["SD_PROMPT"]}
if os.environ.get("SD_SECONDS"): body["seconds"] = int(os.environ["SD_SECONDS"])
if os.environ.get("SD_SIZE"): body["size"] = os.environ["SD_SIZE"]
extra = {}
if os.environ.get("SD_RATIO"): extra["ratio"] = os.environ["SD_RATIO"]
if os.environ.get("SD_RESOLUTION"): extra["resolution"] = os.environ["SD_RESOLUTION"]
if extra: body["extra_body"] = extra
print(json.dumps(body, ensure_ascii=False))
PY
}

field() {  # field JSON_KEY  （从 stdin 的 JSON 里取值，缺失输出空）
  "$PY" -c '
import json, sys
key = sys.argv[1]
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(1)
for part in key.split("."):
    d = d.get(part) if isinstance(d, dict) else None
    if d is None: break
if d is None:
    print("")
elif isinstance(d, (dict, list)):
    print(json.dumps(d, ensure_ascii=False))
else:
    print(d)
' "$1"
}

cmd_gen() {
  # dry-run 不该要求密钥：模型名直接问 config（缺省回落到内置值），地址/密钥留给 api()
  SD_MODEL=$(cfg get-model 2>/dev/null || printf 'doubao-seedance-2-5')
  SD_PROMPT=""; SD_SECONDS=""; SD_SIZE=""; SD_RATIO=""; SD_RESOLUTION=""
  local image="" dry=0
  while [ $# -gt 0 ]; do
    case "$1" in
      --model)      SD_MODEL="$2"; shift 2 ;;
      --prompt|-p)  SD_PROMPT="$2"; shift 2 ;;
      --seconds|-s) SD_SECONDS="$2"; shift 2 ;;
      --size)       SD_SIZE="$2"; shift 2 ;;
      --ratio)      SD_RATIO="$2"; shift 2 ;;
      --resolution) SD_RESOLUTION="$2"; shift 2 ;;
      --image|-i)   image="$2"; shift 2 ;;
      --dry-run)    dry=1; shift ;;
      *) die "gen: 未知参数 $1" ;;
    esac
  done
  [ -n "$SD_PROMPT" ] || die "gen: 需要 --prompt"
  [ -n "$image" ] && [ ! -f "$image" ] && die "gen: 找不到参考图 $image"
  export SD_MODEL SD_PROMPT SD_SECONDS SD_SIZE SD_RATIO SD_RESOLUTION

  local body; body="$(build_body)"
  if [ "$dry" = 1 ]; then
    printf 'POST %s/videos\n%s\n' "$BASE" "$body"
    [ -n "$image" ] && printf '(multipart: model/prompt/seconds + input_reference=%s)\n' "$image"
    return 0
  fi

  local resp
  if [ -n "$image" ]; then
    local args=(-F "model=$SD_MODEL" -F "prompt=$SD_PROMPT" -F "input_reference=@$image")
    [ -n "$SD_SECONDS" ] && args+=(-F "seconds=$SD_SECONDS")
    if [ -n "$SD_SIZE" ]; then args+=(-F "size=$SD_SIZE"); fi
    if [ -n "$SD_RATIO" ]; then args+=(-F "extra_body={\"ratio\":\"$SD_RATIO\"${SD_RESOLUTION:+,\"resolution\":\"$SD_RESOLUTION\"}}"); fi
    resp="$(api POST /videos "${args[@]}")"
  else
    resp="$(api POST /videos -H 'Content-Type: application/json' -d "$body")"
  fi

  local id; id="$(printf '%s' "$resp" | field id || true)"
  if [ -z "$id" ]; then printf '%s\n' "$resp" >&2; die "gen: 建任务失败"; fi
  printf '%s\n' "$id"
  printf 'status: %s\n' "$(printf '%s' "$resp" | field status || true)" >&2
}

cmd_status() { local id="${1:?status: 需要 video id}"; api GET "/videos/$id"; }

cmd_wait() {
  local id="${1:?wait: 需要 video id}"; shift || true
  local timeout=1800 interval=10
  while [ $# -gt 0 ]; do
    case "$1" in
      --timeout) timeout="$2"; shift 2 ;;
      --interval) interval="$2"; shift 2 ;;
      *) die "wait: 未知参数 $1" ;;
    esac
  done
  local start now resp st
  start="$(date +%s)"
  while :; do
    resp="$(api GET "/videos/$id")"
    st="$(printf '%s' "$resp" | field status || true)"
    case "$st" in
      completed) printf '%s\n' "$resp"; return 0 ;;
      failed|cancelled|error) printf '%s\n' "$resp"; die "wait: 任务状态 $st" ;;
    esac
    now="$(date +%s)"
    if [ $((now - start)) -ge "$timeout" ]; then
      printf 'timeout after %ss, last status=%s\n' "$timeout" "${st:-unknown}" >&2
      printf '%s\n' "$resp" >&2
      return 1
    fi
    printf '  %s (%ss)\n' "${st:-unknown}" "$((now - start))" >&2
    sleep "$interval"
  done
}

cmd_download() {
  local id="${1:?download: 需要 video id}" out="${2:-}"
  [ -n "$out" ] || out="seedance-$(date +%Y%m%d-%H%M%S).mp4"
  resolve_config
  curl -sSL -m "${SEEDANCE_DOWNLOAD_TIMEOUT:-600}" "$BASE/videos/$id/content" \
    --config <(auth_config) -o "$out"
  printf '%s (%s)\n' "$out" "$(wc -c <"$out" | tr -d ' ')" >&2
}

cmd_run() {
  local out=""
  local args=()
  while [ $# -gt 0 ]; do
    case "$1" in
      -o|--out) out="$2"; shift 2 ;;
      *) args+=("$1"); shift ;;
    esac
  done
  local id; id="$(cmd_gen "${args[@]}")"
  printf 'task: %s\n' "$id" >&2
  local resp; resp="$(cmd_wait "$id")"
  local secs size res tok
  secs="$(printf '%s' "$resp" | field seconds || true)"
  [ -n "$secs" ] || secs="$(printf '%s' "$resp" | field result.duration || true)"
  size="$(printf '%s' "$resp" | field size || true)"
  res="$(printf '%s' "$resp" | field usage.video_resolution || true)"
  tok="$(printf '%s' "$resp" | field usage.completion_tokens || true)"
  printf 'duration: %ss  size: %s  resolution: %s  tokens: %s\n' \
    "$secs" "$size" "$res" "$tok" >&2
  printf 'url: %s\n' "$(printf '%s' "$resp" | field result.url || true)" >&2
  [ -n "$out" ] || out="seedance-$(date +%Y%m%d-%H%M%S).mp4"
  cmd_download "$id" "$out"
  printf '%s\n' "$out"
}

usage() {
  cat <<'USAGE'
通过 LiteLLM 网关的 Videos 路由调用 Seedance 视频模型（doubao-seedance-2-5 / -2-0-260128）

用法：seedance.sh <命令> [参数]

  gen      --prompt <文本> [--model M] [--seconds N] [--size 1280x720]
           [--ratio 16:9 --resolution 720p] [--image 首帧图] [--dry-run]
                                     建任务，只打印 video id（stdout）
  status   <id>                      查任务状态（原始 JSON）
  wait     <id> [--timeout 1800] [--interval 10]
                                     轮询到 completed，打印完成的 JSON
  download <id> [out.mp4]            下载成片（跟随 307）
  run      同上 gen 的参数 [-o out.mp4]
                                     建任务 → 轮询 → 下载，stdout 只输出文件路径

参数说明
  --seconds  4..30，或 -1 让模型自选（具体默认值由模型决定）
  --size     如 1280x720；不支持的尺寸会提示改用 --ratio + --resolution
  --ratio/--resolution  火山原生比例（16:9、9:16、1:1…）与分辨率（480p/720p/1080p）
  --image    提供首帧图 = 图生视频（走 multipart 的 input_reference）

配置（首次使用先跑 scripts/setup.sh new）
  SEEDANCE_API_KEY       网关 API Key（旧名 LEGACY_API_KEY 仍可用）
  SEEDANCE_BASE_URL      网关地址（旧名 LEGACY_BASE_URL 仍可用）
  SEEDANCE_VIDEO_MODEL   覆盖默认模型
  SEEDANCE_TIMEOUT       单次请求超时（秒，默认 120）
  不设这些时依次读：系统凭据库 → ~/.config/seedance/config.json
  → ~/.pi/agent/auth.json / ~/.codebuddy/models.json（只读导入）
  查看实际生效来源：python3 scripts/seedance_config.py status

示例
  scripts/seedance.sh run -p "a cat walking on grass, cinematic" -s 5 -o cat.mp4
  scripts/seedance.sh gen -p "city at night, rain" --ratio 16:9 --resolution 720p
  scripts/seedance.sh wait video_xxx > task.json
  scripts/seedance.sh download video_xxx out.mp4
  scripts/seedance.sh gen -p test --dry-run        # 不花钱，只看请求体
USAGE
}

main() {
  need curl; need "$PY"
  local cmd="${1:-}"
  [ $# -gt 0 ] && shift
  case "$cmd" in
    gen)      cmd_gen "$@" ;;
    status)   cmd_status "$@" ;;
    wait)     cmd_wait "$@" ;;
    download|dl) cmd_download "$@" ;;
    run)      cmd_run "$@" ;;
    ""|-h|--help|help) usage ;;
    *) usage >&2; die "未知命令：$cmd" ;;
  esac
}

main "$@"
