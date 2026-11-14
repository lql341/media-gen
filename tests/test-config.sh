#!/usr/bin/env bash
# 配置档与凭据解析的离线测试：临时 HOME，不碰真实配置，不写系统凭据库。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CFG="$ROOT/scripts/media_config.py"
PY="${PYTHON:-python3}"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
export HOME="$TMP/home"
export XDG_CONFIG_HOME="$TMP/home/.config"
mkdir -p "$HOME"
unset MEDIA_API_KEY MEDIA_BASE_URL MEDIA_PROFILE MEDIA_PROTOCOL \
      MEDIA_API_KEY_DEFAULT MEDIA_API_KEY_LITELLM SEEDANCE_API_KEY LEGACY_API_KEY 2>/dev/null || true

fail=0
check() { if printf '%s' "$3" | grep -qF "$2"; then printf 'ok    %s\n' "$1"; else printf 'FAIL  %s\n      期望: %s\n      实际: %s\n' "$1" "$2" "$3"; fail=1; fi; }
expect_exit() { local label="$1" want="$2"; shift 2; local rc=0; "$@" >/dev/null 2>&1 || rc=$?; if [ "$rc" = "$want" ]; then printf 'ok    %s（exit=%s）\n' "$label" "$rc"; else printf 'FAIL  %s（exit=%s 期望 %s）\n' "$label" "$rc" "$want"; fail=1; fi; }

echo "== 没有配置时的行为"
expect_exit "无配置档时报错" 2 "$PY" "$CFG" status
out=$("$PY" "$CFG" status 2>&1 || true)
check "报错指出 setup.sh add" "setup.sh add" "$out"

echo "== 新增配置档（密钥 0600 明文，仅测试用）"
printf 'file-store-key-1234567890' | "$PY" "$CFG" add default --protocol openai --base-url https://gw.example/v1 --key-stdin --store file --default-video doubao-seedance-2-5 >/dev/null
mode=$(stat -f %Lp "$HOME/.config/media-gen/config.json" 2>/dev/null || stat -c %a "$HOME/.config/media-gen/config.json")
check "配置文件 0600" "600" "$mode"
out=$("$PY" "$CFG" status)
check "status 显示 protocol" "openai" "$out"
check "status 密钥脱敏" "…7890" "$out"
if printf '%s' "$out" | grep -q "file-store-key-1234567890"; then echo "FAIL  status 泄露完整密钥"; fail=1; else echo "ok    status 不泄露完整密钥"; fi
check "list 标出默认档" "* default" "$("$PY" "$CFG" list)"

echo "== 多配置档与歧义"
"$PY" "$CFG" add ark --protocol ark --base-url https://ark.example/api/v3 --store file >/dev/null
check "list 有两行" "ark" "$("$PY" "$CFG" list)"
"$PY" "$CFG" use ark >/dev/null
check "use 切换默认" "ark" "$(MEDIA_API_KEY=x-1234567890 "$PY" "$CFG" status | awk '/配置档/ {print $2}' | sed 's/（.*//')"
out=$(MEDIA_PROFILE=default "$PY" "$CFG" status)
check "--profile 覆盖默认" "openai" "$out"

echo "== 密钥优先级"
check "通用 MEDIA_API_KEY 最高" "env-key-1234567890" \
  "$(MEDIA_API_KEY=env-key-1234567890 "$PY" "$CFG" get-key --profile default)"
check "按档位命名的变量可取" "profile-key-1234567890" \
  "$(MEDIA_PROFILE=default MEDIA_API_KEY_DEFAULT=profile-key-1234567890 "$PY" "$CFG" get-key)"
check "配置档里的明文兜底" "file-store-key-1234567890" \
  "$("$PY" "$CFG" get-key --profile default)"

echo "== 地址覆盖与协议"
check "MEDIA_BASE_URL 覆盖地址" "https://override.example/v9" \
  "$(MEDIA_BASE_URL=https://override.example/v9 "$PY" "$CFG" get-base-url --profile default)"
check "get-protocol" "ark" "$("$PY" "$CFG" get-protocol --profile ark)"
expect_exit "错误协议被拒绝" 2 env MEDIA_PROTOCOL=smtp MEDIA_BASE_URL=https://x/y "$PY" "$CFG" get-key

echo "== 旧 seedance 配置兼容"
rm -rf "$HOME/.config/media-gen"
mkdir -p "$HOME/.config/seedance" "$HOME/.pi/agent"
printf '{"base_url":"https://legacy.example/v1"}\n' >"$HOME/.config/seedance/config.json"
printf '{"legacyprov":{"type":"api_key","key":"legacy-agent-key-99887766"}}\n' >"$HOME/.pi/agent/auth.json"
out=$("$PY" "$CFG" status)
check "自动识别 legacy 档" "legacy" "$out"
check "legacy 地址来自旧配置" "https://legacy.example/v1" "$out"
check "legacy 密钥来自 agent auth" "legacy-agent-key-99887766" "$("$PY" "$CFG" get-key)"

echo "== migrate"
"$PY" "$CFG" migrate --name old --store file >/dev/null
check "migrate 生成配置档" "old" "$("$PY" "$CFG" list)"
check "migrate 保留地址" "https://legacy.example/v1" "$("$PY" "$CFG" get-base-url --profile old)"
check "migrate 保留密钥" "legacy-agent-key-99887766" "$("$PY" "$CFG" get-key --profile old)"

echo "== 删除"
"$PY" "$CFG" rm old >/dev/null
expect_exit "删除后不再存在" 2 "$PY" "$CFG" get-base-url --profile old

echo
if [ "$fail" = 0 ]; then echo "全部通过"; else echo "有失败项"; exit 1; fi
