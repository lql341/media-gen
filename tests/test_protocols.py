#!/usr/bin/env python3
"""Protocol tests against a scripted local server: no network, no accounts, no money.

Each adapter has to complete create → poll → download, and the request bodies are
inspected so that parameter mapping (duration field, size syntax, reference image,
async headers) cannot silently regress.
"""

from __future__ import annotations

import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))

from mock_server import MP4, PNG, MockServer  # noqa: E402
from protocols import Endpoint, MediaError, load_protocol  # noqa: E402


def endpoint(server: MockServer, protocol: str, prefix: str) -> Endpoint:
    return Endpoint(protocol=protocol, base_url=server.url(prefix), key="test-key-1234567890", timeout=10)


class OpenAITest(unittest.TestCase):
    def test_image_b64(self):
        with MockServer() as server:
            protocol = load_protocol("openai")(endpoint(server, "openai", "/v1"))
            result = protocol.image("gpt-image-1", "a cat", size="1024x1024", n=1, ref=None)
            self.assertEqual(result[0].data, PNG)
            body = [call for call in server.state.calls if call[1] == "/v1/images/generations"][0][2]
            self.assertEqual(body["size"], "1024x1024")
            self.assertEqual(body["response_format"], "b64_json")

    def test_image_url_shaped_response(self):
        with MockServer() as server:
            protocol = load_protocol("openai")(endpoint(server, "openai", "/v1"))
            result = protocol.image("url-image", "a cat", size=None, n=1, ref=None)
            self.assertEqual(result[0].data, b"")
            self.assertTrue(result[0].url.endswith("/files/openai.png"))
            self.assertEqual(protocol.fetch(result[0].url), PNG)

    def test_image_batch_returns_all(self):
        with MockServer() as server:
            protocol = load_protocol("openai")(endpoint(server, "openai", "/v1"))
            results = protocol.image("batch-image", "a cat", size=None, n=3, ref=None)
            self.assertEqual(len(results), 3)
            self.assertEqual(results[0].data, PNG)
            self.assertTrue(results[1].url.endswith("/files/openai.png"))
            body = [call for call in server.state.calls if call[1] == "/v1/images/generations"][0][2]
            self.assertEqual(body["n"], 3)

    def test_video_create_poll_download(self):
        with MockServer() as server:
            protocol = load_protocol("openai")(endpoint(server, "openai", "/v1"))
            task = protocol.video_create(
                "doubao-seedance-2-5", "a cat", seconds=5, size="1280x720",
                resolution=None, ratio=None, ref=None,
            )
            self.assertEqual(task, "video_1")
            body = [call for call in server.state.calls if call[1] == "/v1/videos"][0][2]
            self.assertEqual(body["seconds"], 5)
            state = protocol.video_status(task)
            self.assertIn(state.status, ("processing", "completed"))
            state = protocol.video_status(task)
            self.assertTrue(state.done)
            self.assertEqual(protocol.video_fetch(task, state), MP4)

    def test_image_edit_uses_multipart_edits(self):
        import tempfile

        with MockServer() as server:
            protocol = load_protocol("openai")(endpoint(server, "openai", "/v1"))
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as handle:
                handle.write(b"\x89PNG\r\n\x1a\nREF")
                ref = handle.name
            try:
                results = protocol.image("gpt-image-1", "make it blue", size="512x512", n=1, ref=ref)
                self.assertEqual(results[0].data, PNG)
            finally:
                os.unlink(ref)
            call = [c for c in server.state.calls if c[1] == "/v1/images/edits"][0]
            self.assertTrue(call is not None)

    def test_video_with_reference_uses_multipart(self):
        import tempfile

        with MockServer() as server:
            protocol = load_protocol("openai")(endpoint(server, "openai", "/v1"))
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as handle:
                handle.write(b"\x89PNG\r\n\x1a\nREF")
                ref = handle.name
            try:
                task = protocol.video_create(
                    "doubao-seedance-2-5", "animate this", seconds=5, size=None,
                    resolution="720p", ratio="16:9", ref=ref,
                )
                self.assertEqual(task, "video_1")
            finally:
                os.unlink(ref)

    def test_last_frame_url_is_exposed(self):
        with MockServer() as server:
            protocol = load_protocol("openai")(endpoint(server, "openai", "/v1"))
            task = protocol.video_create("doubao-seedance-2-5", "x", seconds=5, size=None,
                                         resolution=None, ratio=None, ref=None)
            protocol.video_status(task)
            state = protocol.video_status(task)
            self.assertTrue(state.done)
            self.assertTrue(state.last_frame_url.endswith("/files/last.png"))
            self.assertEqual(protocol.fetch(state.last_frame_url), PNG)

    def test_speech(self):
        with MockServer() as server:
            protocol = load_protocol("openai")(endpoint(server, "openai", "/v1"))
            payload, suffix = protocol.speech("tts-1", "hello", voice="alloy", fmt="mp3")
            self.assertEqual(payload, b"ID3FAKEAUDIO")
            self.assertEqual(suffix, ".mp3")
            body = [c for c in server.state.calls if c[1] == "/v1/audio/speech"][0][2]
            self.assertEqual(body["input"], "hello")
            self.assertEqual(body["voice"], "alloy")

    def test_transcribe_uses_multipart(self):
        import tempfile

        with MockServer() as server:
            protocol = load_protocol("openai")(endpoint(server, "openai", "/v1"))
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as handle:
                handle.write(b"ID3AUDIO")
                audio = handle.name
            try:
                text = protocol.transcribe("whisper-1", audio, language="zh")
                self.assertEqual(text, "hello from mock")
            finally:
                os.unlink(audio)
            self.assertTrue(any("multipart/form-data" in ctype for ctype in server.state.content_types))

    def test_custom_speech_and_transcribe(self):
        spec = {
            "speech": {"path": "/custom/speech", "body": {"model": "{model}", "input": "{text}"},
                       "response": {"suffix": "wav"}},
            "transcribe": {"path": "/custom/transcribe", "response": {"text_path": "data.text"}},
        }
        with MockServer() as server:
            protocol = load_protocol("custom")(endpoint(server, "custom", "/"), spec)
            payload, suffix = protocol.speech("m", "hello", voice=None, fmt=None)
            self.assertEqual(payload, b"WAVFAKE")
            self.assertEqual(suffix, ".wav")
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as handle:
                handle.write(b"ID3")
                path = handle.name
            try:
                self.assertEqual(protocol.transcribe("m", path, language=None), "custom transcript")
            finally:
                os.unlink(path)

    def test_command_speech_and_transcribe(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            script = os.path.join(tmpdir, "hook.sh")
            with open(script, "w", encoding="utf-8") as handle:
                handle.write(
                    "#!/usr/bin/env bash\nset -eu\n"
                    "case \"$1\" in\n"
                    "  speech) printf 'AUDIOBYTES' ;;\n"
                    "  transcribe) printf '{\"text\": \"command transcript\"}' ;;\n"
                    "esac\n"
                )
            os.chmod(script, 0o755)
            server = MockServer()
            protocol = load_protocol("command")(endpoint(server, "command", "/"),
                                               {"command": {"speech": script + " speech",
                                                            "transcribe": script + " transcribe"}})
            payload, suffix = protocol.speech("m", "hi", voice=None, fmt="wav")
            self.assertEqual(payload, b"AUDIOBYTES")
            self.assertEqual(suffix, ".wav")
            self.assertEqual(protocol.transcribe("m", __file__, language=None), "command transcript")

    def test_video_ratio_resolution_goes_into_extra_body(self):
        with MockServer() as server:
            protocol = load_protocol("openai")(endpoint(server, "openai", "/v1"))
            protocol.video_create(
                "doubao-seedance-2-5", "a cat", seconds=-1, size=None,
                resolution="720p", ratio="16:9", ref=None,
            )
            body = [call for call in server.state.calls if call[1] == "/v1/videos"][0][2]
            self.assertEqual(body["extra_body"], {"ratio": "16:9", "resolution": "720p"})

    def test_video_failure_is_reported(self):
        with MockServer() as server:
            server.state.video_mode = "fail"
            protocol = load_protocol("openai")(endpoint(server, "openai", "/v1"))
            state = protocol.video_status("video_1")
            self.assertTrue(state.failed)
            self.assertEqual(state.error, "boom")

    # 参考图现在是支持的（multipart），见 test_video_with_reference_uses_multipart

    def test_transcribe_uses_multipart(self):
        import tempfile

        with MockServer() as server:
            protocol = load_protocol("openai")(endpoint(server, "openai", "/v1"))
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as handle:
                handle.write(b"ID3AUDIO")
                audio = handle.name
            try:
                text = protocol.transcribe("whisper-1", audio, language="zh")
                self.assertEqual(text, "hello from mock")
            finally:
                os.unlink(audio)
            self.assertTrue(any("multipart/form-data" in ctype for ctype in server.state.content_types))

    def test_custom_speech_and_transcribe(self):
        spec = {
            "speech": {"path": "/custom/speech", "body": {"model": "{model}", "input": "{text}"},
                       "response": {"suffix": "wav"}},
            "transcribe": {"path": "/custom/transcribe", "response": {"text_path": "data.text"}},
        }
        with MockServer() as server:
            protocol = load_protocol("custom")(endpoint(server, "custom", "/"), spec)
            payload, suffix = protocol.speech("m", "hello", voice=None, fmt=None)
            self.assertEqual(payload, b"WAVFAKE")
            self.assertEqual(suffix, ".wav")
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as handle:
                handle.write(b"ID3")
                path = handle.name
            try:
                self.assertEqual(protocol.transcribe("m", path, language=None), "custom transcript")
            finally:
                os.unlink(path)

    def test_command_speech_and_transcribe(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            script = os.path.join(tmpdir, "hook.sh")
            with open(script, "w", encoding="utf-8") as handle:
                handle.write(
                    "#!/usr/bin/env bash\nset -eu\n"
                    "case \"$1\" in\n"
                    "  speech) printf 'AUDIOBYTES' ;;\n"
                    "  transcribe) printf '{\"text\": \"command transcript\"}' ;;\n"
                    "esac\n"
                )
            os.chmod(script, 0o755)
            server = MockServer()
            protocol = load_protocol("command")(endpoint(server, "command", "/"),
                                               {"command": {"speech": script + " speech",
                                                            "transcribe": script + " transcribe"}})
            payload, suffix = protocol.speech("m", "hi", voice=None, fmt="wav")
            self.assertEqual(payload, b"AUDIOBYTES")
            self.assertEqual(suffix, ".wav")
            self.assertEqual(protocol.transcribe("m", __file__, language=None), "command transcript")

    def test_video_ratio_resolution_goes_into_extra_body(self):
        with MockServer() as server:
            protocol = load_protocol("openai")(endpoint(server, "openai", "/v1"))
            protocol.video_create(
                "doubao-seedance-2-5", "a cat", seconds=-1, size=None,
                resolution="720p", ratio="16:9", ref=None,
            )
            body = [call for call in server.state.calls if call[1] == "/v1/videos"][0][2]
            self.assertEqual(body["extra_body"], {"ratio": "16:9", "resolution": "720p"})

    def test_video_failure_is_reported(self):
        with MockServer() as server:
            server.state.video_mode = "fail"
            protocol = load_protocol("openai")(endpoint(server, "openai", "/v1"))
            state = protocol.video_status("video_1")
            self.assertTrue(state.failed)
            self.assertEqual(state.error, "boom")

    def test_reference_image_goes_multipart(self):
        import tempfile

        with MockServer() as server:
            protocol = load_protocol("openai")(endpoint(server, "openai", "/v1"))
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as handle:
                handle.write(b"\x89PNG\r\n\x1a\nREF")
                ref = handle.name
            try:
                task = protocol.video_create(
                    "doubao-seedance-2-5", "x", seconds=5, size=None,
                    resolution=None, ratio=None, ref=ref,
                )
                self.assertEqual(task, "video_1")
            finally:
                os.unlink(ref)
            # 有首帧图时必须是 multipart（input_reference），不是 JSON
            self.assertTrue(any("multipart/form-data" in ctype for ctype in server.state.content_types))


class ArkTest(unittest.TestCase):
    def test_image(self):
        with MockServer() as server:
            protocol = load_protocol("ark")(endpoint(server, "ark", "/api/v3"))
            self.assertEqual(protocol.image("doubao-seedream-4-0", "a cat", size="1024x1024", n=1, ref=None)[0].data, PNG)

    def test_video_body_and_download(self):
        with MockServer() as server:
            protocol = load_protocol("ark")(endpoint(server, "ark", "/api/v3"))
            task = protocol.video_create(
                "doubao-seedance-2-5", "a cat", seconds=5, size=None,
                resolution="720p", ratio="16:9", ref=None,
            )
            body = [call for call in server.state.calls if call[1] == "/api/v3/contents/generations/tasks"][0][2]
            self.assertEqual(body["duration"], 5)
            self.assertEqual(body["ratio"], "16:9")
            self.assertEqual(body["resolution"], "720p")
            self.assertEqual(body["content"][0], {"type": "text", "text": "a cat"})
            state = protocol.video_status(task)
            self.assertTrue(state.done)
            self.assertEqual(protocol.video_fetch(task, state), MP4)


class DashScopeTest(unittest.TestCase):
    def test_image_is_async(self):
        with MockServer() as server:
            protocol = load_protocol("dashscope")(endpoint(server, "dashscope", "/api/v1"))
            result = protocol.image("wan2.5-t2i-preview", "a cat", size="1024*1024", n=1, ref=None)
            self.assertTrue(result[0].url.endswith("/files/dash.png"))
            self.assertEqual(protocol.fetch(result[0].url), PNG)
            body = [
                call for call in server.state.calls
                if call[1] == "/api/v1/services/aigc/text2image/image-synthesis"
            ][0][2]
            self.assertEqual(body["parameters"]["size"], "1024*1024")

    def test_video_task_and_status_mapping(self):
        with MockServer() as server:
            protocol = load_protocol("dashscope")(endpoint(server, "dashscope", "/api/v1"))
            task = protocol.video_create(
                "wan2.5-t2v-preview", "a cat", seconds=5, size="1280*720",
                resolution=None, ratio=None, ref=None,
            )
            body = [
                call for call in server.state.calls
                if call[1] == "/api/v1/services/aigc/video-generation/video-synthesis"
            ][0][2]
            self.assertEqual(body["parameters"]["duration"], 5)
            self.assertEqual(body["parameters"]["size"], "1280*720")
            state = protocol.video_status(task)
            self.assertEqual(state.status, "completed")
            self.assertEqual(protocol.video_fetch(task, state), MP4)

    def test_local_reference_image_is_refused(self):
        with MockServer() as server:
            protocol = load_protocol("dashscope")(endpoint(server, "dashscope", "/api/v1"))
            with self.assertRaises(MediaError) as raised:
                protocol.video_create(
                    "wan2.5-i2v-preview", "x", seconds=5, size=None,
                    resolution=None, ratio=None, ref=os.path.abspath(__file__),
                )
            self.assertIn("URL", str(raised.exception))


class MinimaxTest(unittest.TestCase):
    def test_image(self):
        with MockServer() as server:
            protocol = load_protocol("minimax")(endpoint(server, "minimax", "/v1"))
            self.assertEqual(protocol.image("image-01", "a cat", size="1024x1024", n=1, ref=None)[0].data, PNG)
            body = [call for call in server.state.calls if call[1] == "/v1/image_generation"][0][2]
            self.assertEqual((body["width"], body["height"]), (1024, 1024))

    def test_video_file_retrieval(self):
        with MockServer() as server:
            protocol = load_protocol("minimax")(endpoint(server, "minimax", "/v1"))
            task = protocol.video_create(
                "MiniMax-Hailuo-02", "a cat", seconds=6, size=None,
                resolution="1080P", ratio=None, ref=None,
            )
            body = [call for call in server.state.calls if call[1] == "/v1/video_generation"][0][2]
            self.assertEqual(body["duration"], 6)
            self.assertEqual(body["resolution"], "1080P")
            state = protocol.video_status(task)
            self.assertTrue(state.done)
            self.assertEqual(state.extra.get("file_id"), "f1")
            self.assertEqual(protocol.video_fetch(task, state), MP4)

    def test_base_resp_error_is_surfaced(self):
        with MockServer() as server:
            protocol = load_protocol("minimax")(endpoint(server, "minimax", "/v1"))
            with self.assertRaises(MediaError):
                protocol._check({"base_resp": {"status_code": 1004, "status_msg": "invalid api key"}}, "请求")


CUSTOM_SPEC = {
    "image": {
        "method": "POST", "path": "/custom/t2i",
        "body": {"model": "{model}", "prompt": "{prompt}", "size": "{size}"},
        "response": {"mode": "b64", "path": "data.image"},
    },
    "video": {
        "create": {"method": "POST", "path": "/custom/tasks",
                   "body": {"model": "{model}", "input": {"text": "{prompt}"}, "seconds": "{seconds}"}},
        "task_id_path": "task.id",
        "status": {"path": "/custom/tasks/{task_id}"},
        "state": {"status_path": "state", "done": ["finished"], "failed": ["failed"],
                  "video_url_path": "output.video_url",
                  "seconds_path": "output_meta.duration", "size_path": "output_meta.size"},
        "fetch": {"mode": "url"},
    },
}


class CustomProtocolTest(unittest.TestCase):
    def test_image_template(self):
        with MockServer() as server:
            protocol = load_protocol("custom")(
                endpoint(server, "custom", "/"), CUSTOM_SPEC
            )
            result = protocol.image("any-model", "a cat", size="800x600", n=1, ref=None)
            self.assertEqual(result[0].data, PNG)
            body = [call for call in server.state.calls if call[1] == "/custom/t2i"][0][2]
            self.assertEqual(body, {"model": "any-model", "prompt": "a cat", "size": "800x600"})

    def test_video_flow_and_nested_paths(self):
        with MockServer() as server:
            protocol = load_protocol("custom")(endpoint(server, "custom", "/"), CUSTOM_SPEC)
            task = protocol.video_create(
                "any-model", "a cat", seconds=4, size=None, resolution=None, ratio=None, ref=None
            )
            self.assertEqual(task, "c1")
            body = [call for call in server.state.calls if call[1] == "/custom/tasks"][0][2]
            self.assertEqual(body["input"], {"text": "a cat"})
            self.assertEqual(body["seconds"], 4)
            state = protocol.video_status(task)
            self.assertTrue(state.done)
            self.assertEqual(state.seconds, "4")
            self.assertEqual(state.size, "640x360")
            self.assertEqual(protocol.video_fetch(task, state), MP4)

    def test_image_list_template(self):
        spec = {
            "image": {
                "method": "POST", "path": "/custom/batch", "body": {"prompt": "{prompt}"},
                "response": {"mode": "url", "path": "data.images", "item": "url"},
            }
        }
        with MockServer() as server:
            protocol = load_protocol("custom")(endpoint(server, "custom", "/"), spec)
            results = protocol.image("m", "p", size=None, n=2, ref=None)
            self.assertEqual(len(results), 2)
            self.assertTrue(results[0].url.endswith("/files/a.png"))

    def test_missing_section_is_explained(self):
        with MockServer() as server:
            protocol = load_protocol("custom")(endpoint(server, "custom", "/"), {"video": {}})
            with self.assertRaises(MediaError) as raised:
                protocol.image("m", "p", size=None, n=1, ref=None)
            self.assertIn("image", str(raised.exception))


class CommandProtocolTest(unittest.TestCase):
    def _hook(self, tmpdir: str) -> str:
        script = os.path.join(tmpdir, "hook.sh")
        with open(script, "w", encoding="utf-8") as handle:
            handle.write(
                "#!/usr/bin/env bash\nset -eu\naction=\"$1\"\n"
                "case \"$action\" in\n"
                "  image) printf '{\"b64\": \"UE5HREFUQQ==\"}' ;;\n"
                "  create) printf '{\"task_id\": \"t-1\"}' ;;\n"
                "  status) printf '{\"status\": \"completed\", \"seconds\": 4}' ;;\n"
                "  fetch) printf 'MP4DATA' ;;\n"
                "  boom) echo 'nope' >&2; exit 3 ;;\n"
                "esac\n"
            )
        os.chmod(script, 0o755)
        return script

    def test_image_and_video(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            hook = self._hook(tmpdir)
            spec = {"command": {"image": f"{hook} image", "create": f"{hook} create",
                                "status": f"{hook} status", "fetch": f"{hook} fetch"}}
            server = MockServer()
            protocol = load_protocol("command")(endpoint(server, "command", "/"), spec)
            self.assertEqual(protocol.image("m", "p", size=None, n=1, ref=None)[0].data, b"PNGDATA")
            task = protocol.video_create("m", "p", seconds=4, size=None, resolution=None, ratio=None, ref=None)
            self.assertEqual(task, "t-1")
            state = protocol.video_status(task)
            self.assertTrue(state.done)
            self.assertEqual(state.seconds, "4")
            self.assertEqual(protocol.video_fetch(task, state), b"MP4DATA")

    def test_command_images_list(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            script = os.path.join(tmpdir, "multi.sh")
            with open(script, "w", encoding="utf-8") as handle:
                handle.write(
                    "#!/usr/bin/env bash\nset -eu\n"
                    "printf '{\"images\": [{\"b64\": \"UE5HREFUQQ==\"}, {\"url\": \"http://127.0.0.1:9/x.png\"}]}'\n"
                )
            os.chmod(script, 0o755)
            server = MockServer()
            protocol = load_protocol("command")(endpoint(server, "command", "/"), {"command": {"image": script}})
            results = protocol.image("m", "p", size=None, n=2, ref=None)
            self.assertEqual(len(results), 2)
            self.assertEqual(results[0].data, b"PNGDATA")

    def test_failure_carries_stderr(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            hook = self._hook(tmpdir)
            spec = {"command": {"image": f"{hook} boom"}}
            server = MockServer()
            protocol = load_protocol("command")(endpoint(server, "command", "/"), spec)
            with self.assertRaises(MediaError) as raised:
                protocol.image("m", "p", size=None, n=1, ref=None)
            self.assertIn("nope", str(raised.exception))

    def test_missing_command_is_explained(self):
        server = MockServer()
        protocol = load_protocol("command")(endpoint(server, "command", "/"), {"command": {}})
        with self.assertRaises(MediaError) as raised:
            protocol.video_status("t-1")
        self.assertIn("command.status", str(raised.exception))


class ErrorShapeTest(unittest.TestCase):
    def test_http_error_message_is_extracted(self):
        with MockServer() as server:
            protocol = load_protocol("openai")(endpoint(server, "openai", "/v1"))
            with self.assertRaises(MediaError) as raised:
                protocol._json("GET", "/no-such-route")
            self.assertIn("no route", str(raised.exception).lower())

    def test_unknown_protocol(self):
        with self.assertRaises(MediaError):
            load_protocol("smtp")


if __name__ == "__main__":
    unittest.main(verbosity=2)
