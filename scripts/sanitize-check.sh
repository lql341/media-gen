#!/usr/bin/env bash
# 公开前的脱敏闸门：扫描仓库里不该出现的个人/内部信息。
#
#   bash scripts/sanitize-check.sh
#
# 检查项：本机绝对路径、真实网关域名、云厂商内部 id、任务 id、密钥形态、个人账号、计费数字。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

say() { printf '%s\n' "$*"; }
fail=0
scan() {  # scan 说明 正则
  local label="$1" pattern="$2" hits
  hits="$(grep -rnE "$pattern" --include='*.md' --include='*.py' --include='*.sh' --include='*.json' --include='*.ps1' . 2>/dev/null \
    | grep -v '^./.git/' | grep -v 'scripts/sanitize-check.sh' || true)"
  if [ -n "$hits" ]; then
    say "x $label"
    printf '%s\n' "$hits" | sed 's/^/    /'
    fail=1
  else
    say "ok $label"
  fi
}

say "== 脱敏检查（${ROOT}）"
scan "本机绝对路径" "(^|[^A-Za-z0-9_$])/(Users|home)/[A-Za-z0-9._-]+"
# 只查私有网关；ark / dashscope / minimax 的官方域名是公开文档，不需要脱敏
# 厂商域名/标识的字面量不写在这里，避免脚本自己被检出
vendor_tag="sc""net"
scan "私有网关域名与厂商标识" "${vendor_tag}\\.cn|${vendor_tag}|$(printf %s "$vendor_tag" | tr a-z A-Z)_"
scan "云厂商内部 id" "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|/[0-9]{9,}/Video"
scan "真实任务 id" "video_[A-Za-z0-9+/=]{40,}"
scan "密钥形态" "sk-[A-Za-z0-9]{16,}|gho_[A-Za-z0-9]{20,}|Bearer [A-Za-z0-9]{24,}"
# 不把用户名写死在脚本里：运行时取 HOME 的 basename
local_user="$(basename "${HOME:-/nonexistent}")"
scan "本机用户名（仓库 owner 名允许出现在 clone URL）" "/Users/${local_user}|/home/${local_user}"
scan "计费数字" "[0-9]{2} ?[0-9]{3} tokens|completion_tokens\":[0-9]{4,}"

if [ "$fail" -ne 0 ]; then
  say ""
  say "有命中项：公开前请逐条处理（改占位符 / 删数字 / 移出文档）。"
  exit 1
fi
say ""
say "全部通过：未发现需要脱敏的内容。"
