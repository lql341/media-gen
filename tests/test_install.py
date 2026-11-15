#!/usr/bin/env python3
"""install.sh --copy 的清单测试：装出来的目录必须与 install-manifest.txt 完全一致。

漏加清单项 = 装好的技能缺文件，而这种错误在仓库里跑测试是看不出来的（仓库里文件都在）。
"""

from __future__ import annotations

import glob
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
MANIFEST = os.path.join(ROOT, "scripts", "install-manifest.txt")


#: 刻意不带进安装目录的仓库文件：开发用，技能运行不需要。
IGNORED = (
    ".gitignore", ".gitattributes", ".github/", "tests/", "CHANGELOG.md",
    "README.md", "README_CN.md", "scripts/install-manifest.txt",
)


def tracked_files() -> set[str]:
    """仓库里被 git 跟踪的文件（避免把本机产物算进来）。"""
    listed = subprocess.run(["git", "-C", ROOT, "ls-files"], capture_output=True, text=True)
    if listed.returncode != 0:
        raise unittest.SkipTest("需要 git 才能列出仓库文件")
    return {
        path for path in listed.stdout.split()
        if not any(path == item or path.startswith(item) for item in IGNORED)
    }


def expected_files() -> set[str]:
    """清单展开的结果（用来发现清单里写了但文件不存在的条目）。"""
    wanted: set[str] = set()
    with open(MANIFEST, encoding="utf-8") as handle:
        for line in handle:
            entry = line.strip()
            if not entry or entry.startswith("#"):
                continue
            for match in glob.glob(os.path.join(ROOT, entry)):
                if os.path.isfile(match):
                    wanted.add(os.path.relpath(match, ROOT))
    return wanted


def installed_files(root: str) -> set[str]:
    found: set[str] = set()
    for dirpath, _, files in os.walk(root):
        for name in files:
            found.add(os.path.relpath(os.path.join(dirpath, name), root))
    return found


class InstallCopyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dst = os.path.join(cls.tmp.name, ".agents", "skills", "media-gen")
        env = dict(os.environ)
        env.update(HOME=cls.tmp.name, XDG_CONFIG_HOME=os.path.join(cls.tmp.name, ".config"))
        cls.result = subprocess.run(
            ["bash", os.path.join(ROOT, "scripts", "install.sh"), "--pi", "--copy"],
            capture_output=True, text=True, env=env,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def test_install_succeeds(self):
        self.assertEqual(self.result.returncode, 0, self.result.stderr)

    def test_installed_tree_matches_repo(self):
        """仓库里每个非开发文件都必须装进去；新增文件忘了写清单会在这里失败。"""
        installed = installed_files(self.dst)
        missing = tracked_files() - installed
        extra = installed - tracked_files()
        self.assertFalse(missing, f"没有装进安装目录：{sorted(missing)}")
        self.assertFalse(extra, f"安装目录多出文件：{sorted(extra)}")

    def test_manifest_matches_installed(self):
        self.assertEqual(installed_files(self.dst), expected_files())

    def test_runtime_files_are_present(self):
        for rel in (
            "SKILL.md", "VERSION", "CAPABILITIES.md",
            "scripts/media.py", "scripts/setup.sh", "scripts/setup.ps1",
            "scripts/protocols/openai.py", "scripts/registry.json",
            "references/setup.md", "docs/RUNBOOK.md",
        ):
            self.assertTrue(os.path.isfile(os.path.join(self.dst, rel)), rel)

    def test_manifest_has_no_stale_entries(self):
        # 清单里每一行都得匹配到文件；匹配不到说明删了文件却没改清单
        with open(MANIFEST, encoding="utf-8") as handle:
            for line in handle:
                entry = line.strip()
                if not entry or entry.startswith("#"):
                    continue
                self.assertTrue(
                    glob.glob(os.path.join(ROOT, entry)), f"清单项没有对应文件：{entry}"
                )

    def test_installed_copy_reports_the_same_version(self):
        env = dict(os.environ)
        env.update(HOME=self.tmp.name, XDG_CONFIG_HOME=os.path.join(self.tmp.name, ".config"))
        reply = subprocess.run(
            [sys.executable, os.path.join(self.dst, "scripts", "mcp_server.py")],
            input=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}) + "\n",
            capture_output=True, text=True, env=env, timeout=30,
        )
        payload = json.loads(reply.stdout.splitlines()[0])
        with open(os.path.join(ROOT, "VERSION"), encoding="utf-8") as handle:
            self.assertEqual(payload["result"]["serverInfo"]["version"], handle.read().strip())


if __name__ == "__main__":
    unittest.main(verbosity=2)
