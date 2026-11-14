#!/usr/bin/env bash
# 跑全部离线测试：不需要网络、账号或任何付费调用。
set -euo pipefail
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PY="${PYTHON:-python3}"

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
echo
echo "全部通过"
