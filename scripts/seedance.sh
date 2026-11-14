#!/usr/bin/env bash
# 兼容 shim：旧的 seedance 命令 → media-gen 的视频子命令。
#
#   scripts/seedance.sh run  -p "<提示词>" [-s N] [-o out.mp4]
#   scripts/seedance.sh gen  -p "<提示词>" …      （只建任务，stdout 是任务 id）
#   scripts/seedance.sh status <id> | wait <id> | download <id> <out>
#
# 新代码请直接用：scripts/media.py video|status|wait|download
set -euo pipefail
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
MEDIA="$HERE/media.py"
PY="${PYTHON:-python3}"

cmd="${1:-}"; [ $# -gt 0 ] && shift || true
printf '注意：seedance.sh 已迁移为 media.py video（本 shim 只为兼容旧命令）\n' >&2

case "$cmd" in
  run)
    out=""; args=()
    while [ $# -gt 0 ]; do
      case "$1" in
        -o|--out) out="$2"; shift 2 ;;
        *) args+=("$1"); shift ;;
      esac
    done
    if [ -n "$out" ]; then exec "$PY" "$MEDIA" video "${args[@]}" -o "$out"; fi
    exec "$PY" "$MEDIA" video "${args[@]}"
    ;;
  gen)   # 旧语义：只建任务，stdout 打任务 id
    exec "$PY" "$MEDIA" video --create-only "$@"
    ;;
  status)   exec "$PY" "$MEDIA" status "$@" ;;
  wait)     exec "$PY" "$MEDIA" wait "$@" ;;
  download|dl) exec "$PY" "$MEDIA" download "$@" ;;
  ""|-h|--help|help)
    sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
  *) echo "未知命令：$cmd" >&2; exit 2 ;;
esac
