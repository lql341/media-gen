#!/usr/bin/env python3
"""Platform branches: Linux `secret-tool` store, Linux without a keyring, Windows.

This machine is macOS, so the other branches are exercised by faking `platform.system()`
and (for Linux) by putting a real `secret-tool`-compatible shim on PATH. That verifies the
code path — a native Linux run is still the only way to prove the keyring integration.
"""

from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))

import media_config as config  # noqa: E402

SHIM = """#!/usr/bin/env bash
set -u
store="{store}"
cmd="${{1:-}}"
shift || true
case "$cmd" in
  store)
    label=""; service=""; account=""
    while [ $# -gt 0 ]; do
      case "$1" in
        --label=*) label="${{1#*=}}"; shift ;;
        service) service="$2"; shift 2 ;;
        account) account="$2"; shift 2 ;;
        *) shift ;;
      esac
    done
    payload="$(cat)"
    mkdir -p "$(dirname "$store")"
    printf '%s\\t%s\\n' "$service/$account" "$payload" >> "$store"
    ;;
  lookup)
    service=""; account=""
    while [ $# -gt 0 ]; do
      case "$1" in
        service) service="$2"; shift 2 ;;
        account) account="$2"; shift 2 ;;
        *) shift ;;
      esac
    done
    [ -f "$store" ] || exit 1
    grep "^$service/$account	" "$store" | tail -1 | cut -f2-
    ;;
  clear)
    service=""; account=""
    while [ $# -gt 0 ]; do
      case "$1" in
        service) service="$2"; shift 2 ;;
        account) account="$2"; shift 2 ;;
        *) shift ;;
      esac
    done
    [ -f "$store" ] || exit 0
    grep -v "^$service/$account	" "$store" > "$store.tmp" || true
    mv "$store.tmp" "$store"
    ;;
esac
"""


class PlatformBranches(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = self.tmp.name
        self.store = os.path.join(root, "shim-store.tsv")
        self.bin = os.path.join(root, "bin")
        os.makedirs(self.bin)
        for name in ("security",):  # 确保 macOS 分支不会被误用
            path = os.path.join(self.bin, name)
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("#!/usr/bin/env bash\nexit 1\n")
            os.chmod(path, stat.S_IRWXU)
        self.env = {
            "HOME": root,
            "XDG_CONFIG_HOME": os.path.join(root, ".config"),
            "PATH": self.bin + os.pathsep + os.environ.get("PATH", ""),
            "MEDIA_CREDENTIAL_STORE": "auto",
        }
        config._STORE_CACHE.clear()
        # 本套测试故意走 shim 存储（临时文件），把调试日志截获，避免污染“零凭据库删除”的断言
        self.log: list[str] = []
        self._debug_patch = mock.patch.object(
            config, "_debug_store", side_effect=lambda message: self.log.append(message)
        )
        self._debug_patch.start()

    def tearDown(self) -> None:
        self._debug_patch.stop()
        config._STORE_CACHE.clear()
        self.tmp.cleanup()

    def _install_secret_tool(self) -> None:
        path = os.path.join(self.bin, "secret-tool")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(SHIM.format(store=self.store))
        os.chmod(path, stat.S_IRWXU)

    def test_linux_secret_tool_roundtrip(self) -> None:
        self._install_secret_tool()
        with mock.patch.dict(os.environ, self.env, clear=False), \
                mock.patch.object(config.platform, "system", return_value="Linux"):
            self.assertEqual(config.secure_store_name(), "Secret Service")
            provider = config.store_key("litellm", "linux-key-1234", None)
            self.assertEqual(provider, "Secret Service")
            self.assertEqual(config._read_store(config.SERVICE, "litellm"), "linux-key-1234")
            # 账户条目独立
            config.store_key("litellm", "team-key-5678", "team")
            self.assertEqual(config._read_store(config.SERVICE, "litellm@team"), "team-key-5678")
            # 删除需要闸门
            with self.assertRaises(config.ConfigError):
                config.delete_key("litellm", "team")
            with mock.patch.dict(os.environ, {"MEDIA_ALLOW_CREDENTIAL_DELETE": "1"}):
                self.assertTrue(config.delete_key("litellm", "team"))
            self.assertIsNone(config._read_store(config.SERVICE, "litellm@team"))

    def test_linux_without_keyring_degrades(self) -> None:
        with mock.patch.dict(os.environ, self.env, clear=False), \
                mock.patch.object(config.platform, "system", return_value="Linux"):
            self.assertIsNone(config.secure_store_name())
            with self.assertRaises(config.ConfigError) as raised:
                config.store_key("litellm", "k-1234567890", None)
            self.assertIn("MEDIA_API_KEY", str(raised.exception))
            # 没有凭据库时，0600 明文 / 环境变量仍然可用
            config.write_config({"profiles": {"p": {"protocol": "openai",
                                                   "base_url": "https://gw/v1",
                                                   "api_key": "inline-key-1234"}}})
            name, profile = config.require_profile("p")
            self.assertEqual(config.resolve_key(name, profile)[0], "inline-key-1234")

    def test_windows_has_no_keyring_backend(self) -> None:
        with mock.patch.dict(os.environ, self.env, clear=False), \
                mock.patch.object(config.platform, "system", return_value="Windows"):
            self.assertIsNone(config.secure_store_name())
            with self.assertRaises(config.ConfigError) as raised:
                config.store_key("litellm", "k-1234567890", None)
            self.assertIn("没有可用的系统凭据库", str(raised.exception))

    def test_store_mode_none_never_calls_out(self) -> None:
        self._install_secret_tool()
        env = dict(self.env, MEDIA_CREDENTIAL_STORE="none")
        with mock.patch.dict(os.environ, env, clear=False), \
                mock.patch.object(config.platform, "system", return_value="Linux"):
            self.assertIsNone(config.secure_store_name())
            config._read_store(config.SERVICE, "litellm")
            self.assertFalse(os.path.exists(self.store), "store 不应被访问")


if __name__ == "__main__":
    unittest.main(verbosity=2)
