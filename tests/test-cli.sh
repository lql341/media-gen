#!/usr/bin/env bash
# CLI 端到端测试：起本地 mock 服务，跑通 models / image / video / status / wait / download。
# 不联网、不需要账号、不产生任何费用。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLI="$ROOT/scripts/media.py"
PY="${PYTHON:-python3}"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"; [ -n "${SERVER_PID:-}" ] && kill "$SERVER_PID" 2>/dev/null || true' EXIT
export HOME="$TMP/home"
export XDG_CONFIG_HOME="$TMP/home/.config"
mkdir -p "$HOME"
unset MEDIA_PROFILE MEDIA_PROTOCOL MEDIA_API_KEY MEDIA_API_KEY_DEFAULT 2>/dev/null || true

SERVER_PID=""
PORT=""
start_server() {
  "$PY" "$ROOT/tests/mock_server.py" >"$TMP/server.log" 2>&1 &
  SERVER_PID=$!
  for _ in $(seq 1 100); do
    PORT=$("$PY" - "$TMP/server.log" <<'PY' 2>/dev/null || true
import json, sys
try:
    print(json.loads(open(sys.argv[1]).readline().strip())["port"])
except Exception:
    pass
PY
    )
    [ -n "$PORT" ] && return 0
    sleep 0.05
  done
  echo "mock server 未能启动" >&2; cat "$TMP/server.log" >&2; exit 1
}

fail=0
check() { if printf '%s' "$3" | grep -qF "$2"; then printf 'ok    %s\n' "$1"; else printf 'FAIL  %s\n      期望: %s\n      实际: %s\n' "$1" "$2" "$3"; fail=1; fi; }
expect_exit() { local label="$1" want="$2"; shift 2; local rc=0; "$@" >/dev/null 2>&1 || rc=$?; if [ "$rc" = "$want" ]; then printf 'ok    %s（exit=%s）\n' "$label" "$rc"; else printf 'FAIL  %s（exit=%s 期望 %s）\n' "$label" "$rc" "$want"; fail=1; fi; }

echo "== 语法与帮助"
for f in "$ROOT"/scripts/*.sh "$ROOT"/tests/*.sh; do bash -n "$f" || { echo "FAIL  语法: $f"; fail=1; }; done
"$PY" -c "import ast,sys;[ast.parse(open(p).read()) for p in sys.argv[1:]]" "$ROOT"/scripts/*.py "$ROOT"/scripts/protocols/*.py
echo "ok    bash -n 与 python 语法全部通过"
check "--help 列出子命令" "video" "$("$PY" "$CLI" --help)"

start_server
BASE="http://127.0.0.1:$PORT/v1"
export MEDIA_BASE_URL="$BASE"
export MEDIA_API_KEY="test-key-1234567890"
echo "== mock 服务就绪（${BASE}）"

echo "== models"
out=$("$PY" "$CLI" models)
check "识别 seedance 为 video" "doubao-seedance-2-5  video" "$out"
check "识别 wan t2i 为 image" "wan2.5-t2i-preview   image" "$out"
check "未知模型标 unknown" "text-only-model" "$out"
check "--kind 过滤" "1" "$("$PY" "$CLI" models --kind video | wc -l | tr -d ' ')"
check "--json 可解析" '"kind": "video"' "$("$PY" "$CLI" models --json)"

echo "== dry-run 不产生请求"
out=$("$PY" "$CLI" image -p "a cat" --model gpt-image-1 --size 1024x1024 --dry-run)
check "image dry-run 有 capability" '"capability"' "$out"
out=$("$PY" "$CLI" video -p "a cat" --model doubao-seedance-2-5 -s 5 --dry-run)
check "video dry-run 有 seconds" '"seconds": 5' "$out"
if printf '%s' "$out" | grep -q "task "; then echo "FAIL  dry-run 建了任务"; fail=1; else echo "ok    dry-run 未建任务"; fi

echo "== 图片：b64 与 url 两种返回"
check "b64 落盘" "$TMP/a.png" "$("$PY" "$CLI" image -p "a cat" --model gpt-image-1 -o "$TMP/a.png" 2>/dev/null)"
[ -s "$TMP/a.png" ] && echo "ok    b64 文件非空" || { echo "FAIL  b64 文件为空"; fail=1; }
check "url 落盘" "$TMP/b.png" "$("$PY" "$CLI" image -p "a cat" --model url-image -o "$TMP/b.png" 2>/dev/null)"
[ -s "$TMP/b.png" ] && echo "ok    url 文件非空" || { echo "FAIL  url 文件为空"; fail=1; }

echo "== 视频全流程"
out=$("$PY" "$CLI" video -p "a cat" --model doubao-seedance-2-5 -s 5 --interval 0 -o "$TMP/v.mp4" 2>"$TMP/v.log")
check "run 打印路径" "$TMP/v.mp4" "$out"
check "完成后报告时长" "5s" "$(cat "$TMP/v.log")"
[ -s "$TMP/v.mp4" ] && echo "ok    视频文件非空" || { echo "FAIL  视频文件为空"; fail=1; }

echo "== 任务查询"
check "status 返回 JSON" '"task_id"' "$("$PY" "$CLI" status video_1)"
check "wait 输出 completed" '"completed"' "$("$PY" "$CLI" wait video_1 --interval 0)"
check "download 复用完成的产物" "$TMP/d.mp4" "$("$PY" "$CLI" download video_1 "$TMP/d.mp4" 2>/dev/null)"

echo "== run 自动判种类"
check "run 走图片路径" "$TMP/c.png" "$("$PY" "$CLI" run -p "a cat" --model wan2.5-t2i-preview --size 1024x1024 -o "$TMP/c.png" 2>/dev/null)"
check "run 走视频路径" "$TMP/e.mp4" "$("$PY" "$CLI" run -p "a cat" --model doubao-seedance-2-5 -s 5 --interval 0 -o "$TMP/e.mp4" 2>/dev/null)"

echo "== 校验与报错"
expect_exit "时长越界被本地拦下" 2 "$PY" "$CLI" video -p x --model doubao-seedance-2-5 -s 2
expect_exit "尺寸格式错误" 2 "$PY" "$CLI" image -p x --model gpt-image-1 --size big
expect_exit "缺 --model" 2 "$PY" "$CLI" video -p x
out=$("$PY" "$CLI" video -p x 2>&1 || true)
check "缺模型提示 setup.sh" "setup.sh" "$out"
expect_exit "缺 prompt" 2 "$PY" "$CLI" image --model gpt-image-1

echo "== 无密钥时报错可行动"
out=$(env -u MEDIA_API_KEY HOME="$TMP/empty" "$PY" "$CLI" models 2>&1 || true)
check "提示配置端点" "setup.sh" "$out"

echo
if [ "$fail" = 0 ]; then echo "全部通过"; else echo "有失败项"; exit 1; fi
