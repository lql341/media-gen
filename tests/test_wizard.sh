#!/usr/bin/env bash
# 交互向导的非交互测试：把答案管道喂进去，验证配置与 custom 模板的落盘结果。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${PYTHON:-python3}"
CFG="$ROOT/scripts/media_config.py"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
export HOME="$TMP/home"
export XDG_CONFIG_HOME="$TMP/home/.config"
mkdir -p "$HOME"
export MEDIA_CREDENTIAL_STORE=none      # 绝不碰本机凭据库
export MEDIA_DEBUG_STORE=1              # 若有任何凭据库访问，会打到 stderr
unset MEDIA_API_KEY MEDIA_BASE_URL MEDIA_PROFILE 2>/dev/null || true

fail=0
check() { if printf '%s' "$3" | grep -qF "$2"; then printf 'ok    %s\n' "$1"; else printf 'FAIL  %s\n      期望: %s\n      实际: %s\n' "$1" "$2" "$3"; fail=1; fi; }

echo "== 向导：新增 openai 端点（管道喂答案）"
# 名字 / 协议 / base_url / 图片模型 / 视频模型 / key / 设为默认 / 自检
answers='litellm\n1\nhttps://gw.example/v1\n\n\ntest-key-1234567890\ny\ny\nn\n'
out=$(printf "$answers" | "$PY" "$ROOT/scripts/wizard.py" add 2>&1)
check "向导报告已保存" "已保存配置档 litellm" "$out"
check "协议正确" "openai" "$("$PY" "$CFG" get-protocol --profile litellm)"
check "地址正确" "https://gw.example/v1" "$("$PY" "$CFG" get-base-url --profile litellm)"
check "默认配置档" "litellm" "$("$PY" "$CFG" list | sed -n 's/^\* //p' | awk '{print $1}')"
out=$("$PY" "$CFG" status)
check "密钥已保存（脱敏）" "…7890" "$out"
if printf '%s' "$out" | grep -q "test-key-1234567890"; then echo "FAIL  status 泄露密钥"; fail=1; else echo "ok    status 不泄露密钥"; fi

echo "== 向导：custom 模板逐项生成"
# 名字 / base_url / 认证方式 / 支持图片 y / 方法 / 路径 / 返回形式 / 返回字段 / 发 size y / 发 n n
# / 支持视频 y / create 路径 / status 路径 / 发 seconds y / id 字段 / 状态字段 / 完成值 / 失败值
# / 错误字段 / 视频地址字段 / 时长字段 / 尺寸字段 / 下载方式 / 保存 y / key / 默认 n / 自检 n
custom_answers='inhouse\nhttps://inhouse.example/api\nbearer\ny\nPOST\n/v1/t2i\nb64\ndata.0.image\ny\nn\ny\n/v1/tasks\n/v1/tasks/{task_id}\ny\ntask.id\nstate\nfinished\nfailed\nmessage\noutput.video_url\noutput.duration\noutput.size\nurl\ny\nkey-1234567890\ny\nn\nn\n'
out=$(printf "$custom_answers" | "$PY" "$ROOT/scripts/wizard.py" custom 2>&1)
check "custom 已保存" "已保存 inhouse" "$out"
spec="$HOME/.config/media-gen/custom/inhouse.json"
[ -f "$spec" ] && echo "ok    模板文件存在" || { echo "FAIL  模板未落盘"; fail=1; }
check "模板含 image 段" '"image"' "$(cat "$spec")"
check "模板含 video.state" '"done"' "$(cat "$spec")"
check "协议为 custom" "custom" "$("$PY" "$CFG" get-protocol --profile inhouse)"

echo "== 向导：list 与 doctor 不崩"
check "list 能看到两个档" "inhouse" "$("$PY" "$ROOT/scripts/wizard.py" list)"
out=$("$PY" "$ROOT/scripts/wizard.py" doctor 2>&1 || true)
check "doctor 有输出" "结果" "$out"

echo "== 向导：删除"
printf 'litellm\nn\n' | "$PY" "$ROOT/scripts/wizard.py" remove >/dev/null
if "$PY" "$CFG" get-base-url --profile litellm >/dev/null 2>&1; then echo "FAIL  litellm 未删除"; fail=1; else echo "ok    litellm 已删除"; fi

echo "== 凭据库访问应为零"
if printf '%s' "$out" | grep -q "store: read"; then
  echo "FAIL  向导访问了系统凭据库"; fail=1
else
  echo "ok    MEDIA_CREDENTIAL_STORE=none 下没有凭据库访问"
fi

echo
if [ "$fail" = 0 ]; then echo "全部通过"; else echo "有失败项"; exit 1; fi
