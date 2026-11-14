#!/usr/bin/env bash
# CLI 行为的离线测试：只跑 --dry-run 和参数校验，不建任务、不调用网关、不花钱。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLI="$ROOT/scripts/seedance.sh"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
export HOME="$TMP/home"
export XDG_CONFIG_HOME="$TMP/home/.config"
mkdir -p "$HOME"

fail=0
check() {
  if printf '%s' "$3" | grep -qF "$2"; then printf 'ok    %s\n' "$1"
  else printf 'FAIL  %s\n      期望包含: %s\n      实际: %s\n' "$1" "$2" "$3"; fail=1; fi
}
expect_fail() {  # expect_fail 描述 命令...
  local label="$1"; shift
  local rc=0
  "$@" >/dev/null 2>&1 || rc=$?
  if [ "$rc" != 0 ]; then printf 'ok    %s（exit=%s）\n' "$label" "$rc"
  else printf 'FAIL  %s 应当非零退出\n' "$label"; fail=1; fi
}

echo "== 帮助与语法"
check "--help 列出子命令" "run" "$("$CLI" --help)"
for f in "$ROOT"/scripts/*.sh "$ROOT"/tests/*.sh; do
  bash -n "$f" || { echo "FAIL  语法错误: $f"; fail=1; }
done
echo "ok    bash -n 全部通过"

echo "== dry-run 不需要密钥、不产生请求"
out=$(env -u SEEDANCE_API_KEY -u LEGACY_API_KEY SEEDANCE_BASE_URL=https://gw.example/v1 \
  "$CLI" gen -p "a cat" -s 4 --dry-run)
check "dry-run 打印 model" '"model"' "$out"
check "dry-run 打印 prompt" '"a cat"' "$out"
check "dry-run 打印时长" '"seconds": 4' "$out"
out=$(env -u SEEDANCE_API_KEY SEEDANCE_BASE_URL=https://gw.example/v1 \
  "$CLI" gen -p "x" --ratio 16:9 --resolution 480p --dry-run)
check "ratio/resolution 进 extra_body" '"extra_body"' "$out"
if printf '%s' "$out" | grep -q "Bearer"; then
  echo "FAIL  dry-run 输出里出现 Authorization"; fail=1
else
  echo "ok    输出不含 Authorization"
fi

echo "== 参数校验"
expect_fail "缺少 --prompt" env SEEDANCE_BASE_URL=https://gw.example/v1 "$CLI" gen --dry-run
expect_fail "未知参数" env SEEDANCE_BASE_URL=https://gw.example/v1 "$CLI" gen -p x --nope --dry-run
expect_fail "status 缺少 id" "$CLI" status
expect_fail "wait 缺少 id" "$CLI" wait
expect_fail "未知子命令" "$CLI" nope
expect_fail "找不到参考图" env SEEDANCE_BASE_URL=https://gw.example/v1 \
  "$CLI" gen -p x --image /nonexistent/first.jpg --dry-run

echo "== 无密钥时报错指向 setup"
out=$(env -u SEEDANCE_API_KEY -u LEGACY_API_KEY HOME="$TMP/empty" \
  SEEDANCE_BASE_URL=https://gw.example/v1 "$CLI" gen -p x 2>&1 || true)
check "提示运行 setup.sh" "setup.sh" "$out"

echo
if [ "$fail" = 0 ]; then echo "全部通过"; else echo "有失败项"; exit 1; fi
