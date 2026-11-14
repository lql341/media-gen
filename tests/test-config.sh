#!/usr/bin/env bash
# 配置与凭据解析的离线测试：不需要网络，不读写真实用户配置，不产生任何视频任务。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CFG="$ROOT/scripts/seedance_config.py"
PY="${PYTHON:-python3}"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
export HOME="$TMP/home"
export XDG_CONFIG_HOME="$TMP/home/.config"
mkdir -p "$HOME"
unset SEEDANCE_API_KEY LEGACY_API_KEY SEEDANCE_BASE_URL LEGACY_BASE_URL SEEDANCE_VIDEO_MODEL 2>/dev/null || true

fail=0
check() {  # check 描述 期望子串 实际
  local label="$1" expected="$2" actual="$3"
  if printf '%s' "$actual" | grep -qF "$expected"; then
    printf 'ok    %s\n' "$label"
  else
    printf 'FAIL  %s\n      期望包含: %s\n      实际: %s\n' "$label" "$expected" "$actual"
    fail=1
  fi
}
expect_exit() {  # expect_exit 描述 期望码 命令...
  local label="$1" expected="$2"; shift 2
  local rc=0
  "$@" >/dev/null 2>&1 || rc=$?
  if [ "$rc" = "$expected" ]; then printf 'ok    %s\n' "$label"
  else printf 'FAIL  %s（exit=%s，期望 %s）\n' "$label" "$rc" "$expected"; fail=1; fi
}

echo "== 环境变量最高优先级"
out=$(SEEDANCE_API_KEY=test-key-1234567890 "$PY" "$CFG" status)
check "status 报告环境变量来源" "SEEDANCE_API_KEY" "$out"
check "status 只显示密钥尾部" "…7890" "$out"
if printf '%s' "$out" | grep -q "test-key-1234567890"; then
  echo "FAIL  status 泄露了完整密钥"; fail=1
else
  echo "ok    status 不泄露完整密钥"
fi
check "get-key 输出原值" "test-key-1234567890" "$(SEEDANCE_API_KEY=test-key-1234567890 "$PY" "$CFG" get-key)"
check "旧变量名 LEGACY_API_KEY 仍可用" "legacy-key-abcdef1234" "$(LEGACY_API_KEY=legacy-key-abcdef1234 "$PY" "$CFG" get-key)"

echo "== 地址优先级与落盘"
check "无配置时用默认地址" "https://gw.example.com/v1" "$("$PY" "$CFG" get-base-url)"
"$PY" "$CFG" set --base-url https://gw.example/v1 --no-verify >/dev/null
check "set 写入后生效" "https://gw.example/v1" "$("$PY" "$CFG" get-base-url)"
mode=$(stat -f %Lp "$HOME/.config/seedance/config.json" 2>/dev/null || stat -c %a "$HOME/.config/seedance/config.json")
check "配置文件 0600" "600" "$mode"
check "环境变量覆盖配置文件" "https://env.example/v1" \
  "$(SEEDANCE_BASE_URL=https://env.example/v1 "$PY" "$CFG" get-base-url)"
check "地址尾部斜杠被规范化" "https://gw.example/v1" \
  "$("$PY" "$CFG" get-base-url)"

echo "== agent auth 只读导入"
mkdir -p "$HOME/.pi/agent"
printf '{"legacyprov":{"type":"api_key","key":"agent-file-key-99887766"}}\n' >"$HOME/.pi/agent/auth.json"
check "从 auth.json 读取" "agent-file-key-99887766" "$("$PY" "$CFG" get-key)"
out=$("$PY" "$CFG" status)
check "来源标注为只读导入" "只读导入" "$out"

echo "== 校验与清理"
expect_exit "空密钥被拒绝" 2 bash -c "printf '  \\n' | '$PY' '$CFG' set --key-stdin --store file --no-verify"
expect_exit "整行 export 被拒绝" 2 bash -c "printf 'export SEEDANCE_API_KEY=abc\\n' | '$PY' '$CFG' set --key-stdin --store file --no-verify"
expect_exit "非 http(s) 地址被拒绝" 2 "$PY" "$CFG" set --base-url "gw.example/v1" --no-verify
"$PY" "$CFG" reset --all >/dev/null
check "reset --all 清掉地址" "https://gw.example.com/v1" "$("$PY" "$CFG" get-base-url)"
if [ -e "$HOME/.config/seedance/config.json" ]; then
  echo "FAIL  config.json 应已删除"; fail=1
else
  echo "ok    config.json 已删除"
fi

echo "== doctor 离线失败路径"
out=$(SEEDANCE_API_KEY=k-1234567890 SEEDANCE_BASE_URL=http://127.0.0.1:9/v1 "$PY" "$CFG" doctor 2>&1 || true)
check "连不上时报告 FAIL" "FAIL" "$out"

echo
if [ "$fail" = 0 ]; then echo "全部通过"; else echo "有失败项"; exit 1; fi
