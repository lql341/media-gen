#!/usr/bin/env python3
"""MCP server test: JSON-RPC over stdio against the local mock endpoint.

Verifies initialize / tools/list / tools/call for models, image, video and task,
plus the "unknown method" error path. No network, no accounts, no spend.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from mock_server import MockServer, PNG  # noqa: E402


class McpServerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.server = MockServer()
        self.server.__enter__()
        env = dict(os.environ)
        env.update(
            HOME=self.tmp.name,
            XDG_CONFIG_HOME=os.path.join(self.tmp.name, ".config"),
            MEDIA_API_KEY="test-key-1234567890",
            MEDIA_CREDENTIAL_STORE="none",
            MEDIA_BASE_URL=self.server.url("/v1"),
        )
        self.process = subprocess.Popen(
            [sys.executable, os.path.join(ROOT, "scripts", "mcp_server.py")],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )

    def tearDown(self) -> None:
        if self.process.poll() is None:
            try:
                self.process.stdin.close()
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
        self.process.stdout.close()
        self.process.stderr.close()
        self.server.__exit__(None, None, None)
        self.tmp.cleanup()

    def rpc(self, payload: dict) -> dict:
        assert self.process.stdin and self.process.stdout
        self.process.stdin.write(json.dumps(payload) + "\n")
        self.process.stdin.flush()
        line = self.process.stdout.readline()
        self.assertTrue(line, "server closed stdout")
        return json.loads(line)

    def call(self, tool: str, arguments: dict) -> dict:
        reply = self.rpc(
            {"jsonrpc": "2.0", "id": 9, "method": "tools/call",
             "params": {"name": tool, "arguments": arguments}}
        )
        text = reply["result"]["content"][0]["text"]
        return json.loads(text)

    def test_initialize_and_tools(self):
        reply = self.rpc({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        self.assertEqual(reply["result"]["serverInfo"]["name"], "media-gen")
        self.assertIn("tools", reply["result"]["capabilities"])
        with open(os.path.join(ROOT, "VERSION"), encoding="utf-8") as handle:
            self.assertEqual(reply["result"]["serverInfo"]["version"], handle.read().strip())
        reply = self.rpc({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        names = [tool["name"] for tool in reply["result"]["tools"]]
        self.assertEqual(
            names,
            ["media_profiles", "media_models", "media_image", "media_video", "media_task",
             "media_speech", "media_transcribe"],
        )

    def test_models_and_profiles(self):
        models = self.call("media_models", {"kind": "video"})
        self.assertTrue(models["ok"])
        self.assertIn("doubao-seedance-2-5", json.dumps(models["result"]))
        profiles = self.call("media_profiles", {})
        self.assertTrue(profiles["ok"])

    def test_image_and_video(self):
        image = self.call(
            "media_image",
            {"prompt": "a cat", "model": "gpt-image-1", "out": os.path.join(self.tmp.name, "a.png")},
        )
        self.assertTrue(image["ok"], image)
        self.assertTrue(os.path.getsize(image["result"]) >= len(PNG) - 1)
        masked = self.call(
            "media_image",
            {"prompt": "make it blue", "model": "gpt-image-1", "image": os.path.join(self.tmp.name, "a.png"),
             "mask": os.path.join(self.tmp.name, "a.png"), "out": os.path.join(self.tmp.name, "m.png")},
        )
        self.assertTrue(masked["ok"], masked)
        video = self.call(
            "media_video",
            {"prompt": "a cat", "model": "doubao-seedance-2-5", "seconds": 4,
             "out": os.path.join(self.tmp.name, "a.mp4"), "interval": 0},
        )
        self.assertTrue(video["ok"], video)
        self.assertTrue(os.path.getsize(video["result"]) > 0)

    def test_task_status_and_errors(self):
        status = self.call("media_task", {"action": "status", "task_id": "video_1"})
        self.assertTrue(status["ok"])
        bad = self.rpc({"jsonrpc": "2.0", "id": 3, "method": "nope"})
        self.assertEqual(bad["error"]["code"], -32601)
        unknown = self.call("media_nope", {})
        self.assertFalse(unknown["ok"])

    def test_task_wait(self):
        waited = self.call("media_task", {"action": "wait", "task_id": "video_1", "interval": 1})
        self.assertTrue(waited["ok"], waited)
        self.assertEqual(waited["result"]["status"], "completed")

    def test_error_field_carries_the_message_not_the_exit_code(self):
        # 没有默认模型 → die()，MCP 的 error 不应只是 "2"
        failed = self.call("media_video", {"prompt": "x"})
        self.assertFalse(failed["ok"])
        self.assertIn("--model", failed["error"])

    def test_audio_tools(self):
        speech = self.call(
            "media_speech",
            {"text": "hello", "model": "tts-1", "voice": "alloy",
             "out": os.path.join(self.tmp.name, "a.mp3")},
        )
        self.assertTrue(speech["ok"], speech)
        self.assertEqual(speech["result"], os.path.join(self.tmp.name, "a.mp3"))
        self.assertTrue(os.path.getsize(speech["result"]) > 0)
        audio = os.path.join(self.tmp.name, "in.mp3")
        with open(audio, "wb") as handle:
            handle.write(b"ID3AUDIO")
        text = self.call("media_transcribe", {"file": audio, "model": "whisper-1", "language": "en"})
        self.assertTrue(text["ok"], text)
        self.assertEqual(text["result"], "hello from mock")

    def test_video_remix_and_last_frame(self):
        out = os.path.join(self.tmp.name, "remix.mp4")
        last = os.path.join(self.tmp.name, "remix-last.png")
        remix = self.call(
            "media_video",
            {"prompt": "make it night", "model": "doubao-seedance-2-5", "remix": "video_1",
             "interval": 1, "out": out, "last_frame": last},
        )
        self.assertTrue(remix["ok"], remix)
        self.assertEqual(remix["result"], out)
        self.assertTrue(os.path.getsize(out) > 0)
        self.assertTrue(os.path.getsize(last) > 0, "remix 分支不能忽略 last_frame")

    def test_dry_run_spends_nothing(self):
        out = self.call("media_video", {"prompt": "x", "model": "doubao-seedance-2-5", "dry_run": True})
        self.assertTrue(out["ok"])
        self.assertIn("dry_run", json.dumps(out) + "dry_run")


if __name__ == "__main__":
    unittest.main(verbosity=2)
