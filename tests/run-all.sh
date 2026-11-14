#!/usr/bin/env bash
# 跑全部离线测试：不需要网络、账号或任何付费调用。
set -euo pipefail
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PY="${PYTHON:-python3}"
# 调试输出落到固定文件，便于做“没有删除凭据”的断言
export MEDIA_DEBUG_STORE=1
exec > >(tee /tmp/media-gen-test.log) 2>&1

echo "=== registry 单元测试"
"$PY" "$HERE/test_registry.py"
echo
echo "=== protocol 适配器（本地 mock 服务）"
"$PY" "$HERE/test_protocols.py"
echo
echo "=== 交互向导（管道驱动）"
bash "$HERE/test_wizard.sh"
echo
echo "=== MCP server（图形客户端通道）"
"$PY" "$HERE/test_mcp.py"
echo
echo "=== 配置与凭据"
bash "$HERE/test-config.sh"
echo
echo "=== CLI 端到端（本地 mock 服务）"
bash "$HERE/test-cli.sh"
echo "=== 安全断言：整套测试没有删除/写入系统凭据库"
if grep -q "store: delete" /tmp/media-gen-test.log 2>/dev/null; then
  echo "FAIL  测试期间出现了凭据库删除操作"; exit 1
fi
echo "ok    无凭据库删除"

echo
echo "全部通过"
