"""A tiny scripted HTTP server used by the tests.

It implements just enough of each wire protocol that the adapters can be
exercised end to end (create → poll → download) without any network access,
account, or money:

    openai     /v1/models, /v1/images/generations, /v1/videos…
    ark        /api/v3/contents/generations/tasks…, /api/v3/images/generations
    dashscope  /api/v1/services/aigc/…, /api/v1/tasks/<id>
    minimax    /v1/video_generation, /v1/query/video_generation, /v1/files/retrieve, /v1/image_generation

Run standalone for manual poking::

    python3 tests/mock_server.py            # prints {"port": …} then serves
"""

from __future__ import annotations

import base64
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PNG = b"\x89PNG\r\n\x1a\nFAKE"
MP4 = b"\x00\x00\x00\x18ftypmp42FAKE"
B64_PNG = base64.b64encode(PNG).decode("ascii")


class State:
    def __init__(self) -> None:
        self.video_polls = 0
        self.calls: list[tuple[str, str, dict]] = []
        self.fail_video = False
        self.video_mode = "eventual"  # eventual | fail
        self.content_types: list[str] = []
        self.headers: list[dict] = []
        self.queries: list[str] = []
        self.paths: list[str] = []

    def record(self, method: str, path: str, body: dict) -> None:
        self.calls.append((method, path, body))


def make_handler(state: State):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args) -> None:  # silence
            return

        # ---------------------------------------------------------- helpers
        def _send(self, status: int, payload: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def _json(self, status: int, payload: dict) -> None:
            self._send(status, json.dumps(payload).encode("utf-8"), "application/json")

        def _body(self) -> dict:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            self.raw_body = raw
            self.content_type = self.headers.get("Content-Type", "")

            state.content_types.append(self.content_type)
            try:
                return json.loads(raw or b"{}")
            except ValueError:
                return {}

        def _base(self) -> str:
            host = self.headers.get("Host") or "127.0.0.1"
            return f"http://{host}"

        # ------------------------------------------------------------- GET
        def do_GET(self) -> None:  # noqa: N802
            path = self.path.split("?", 1)[0]
            state.record("GET", path, {})

            state.headers.append({k.lower(): v for k, v in self.headers.items()})
            state.paths.append(path)
            state.queries.append(self.path.split("?", 1)[1] if "?" in self.path else "")
            if path in ("/v1/models", "/models"):
                return self._json(
                    200,
                    {
                        "object": "list",
                        "data": [
                            {"id": "doubao-seedance-2-5", "object": "model"},
                            {"id": "wan2.5-t2i-preview", "object": "model"},
                            {"id": "gpt-image-1", "object": "model"},
                            {"id": "tts-1", "object": "model"},
                            {"id": "whisper-1", "object": "model"},
                            {"id": "text-only-model", "object": "model"},
                        ],
                    },
                )
            if path.startswith("/v1/videos/") and path.endswith("/content"):
                return self._send(200, MP4, "video/mp4")
            if path == "/v1/videos":
                return self._json(200, {"data": [
                    {"id": "video_1", "status": "completed", "seconds": "5", "size": "1280x720"},
                    {"id": "video_2", "status": "processing", "seconds": "5", "size": "1280x720"},
                ]})
            if path.startswith("/v1/videos/"):
                state.video_polls += 1
                # 任务 id 里带 fail 时固定返回失败，供测试“多任务里有一个挂掉”的分支
                if state.video_mode == "fail" or "fail" in path:
                    return self._json(200, {"id": "video_1", "status": "failed", "error": {"message": "boom"}})
                if state.video_polls < 2:
                    return self._json(200, {"id": "video_1", "status": "processing"})
                return self._json(
                    200,
                    {
                        "id": "video_1",
                        "status": "completed",
                        "seconds": "5",
                        "size": "1280x720",
                        "usage": {"completion_tokens": 1},
                        "result": {
                            "url": self._base() + "/v1/videos/video_1/content",
                            "last_frame_url": self._base() + "/files/last.png",
                        },
                    },
                )
            if path.startswith("/api/v3/contents/generations/tasks/"):
                task = path.rsplit("/", 1)[-1]
                return self._json(
                    200,
                    {
                        "id": task,
                        "status": "succeeded",
                        "content": {"video_url": self._base() + "/files/ark.mp4"},
                        "duration": 5,
                        "resolution": "720p",
                    },
                )
            if path.startswith("/api/v1/tasks/"):
                task = path.rsplit("/", 1)[-1]
                if task == "t1":
                    return self._json(
                        200,
                        {
                            "output": {
                                "task_status": "SUCCEEDED",
                                "results": [{"url": self._base() + "/files/dash.png"}],
                            }
                        },
                    )
                return self._json(
                    200,
                    {
                        "output": {
                            "task_status": "SUCCEEDED",
                            "video_url": self._base() + "/files/dash.mp4",
                            "duration": 5,
                        }
                    },
                )
            if path == "/v1/query/video_generation":
                return self._json(
                    200,
                    {"status": "Success", "file_id": "f1", "base_resp": {"status_code": 0, "status_msg": "ok"}},
                )
            if path == "/v1/files/retrieve":
                return self._json(
                    200, {"file": {"download_url": self._base() + "/files/minimax.mp4"}, "base_resp": {"status_code": 0}}
                )
            if path.startswith("/custom/tasks/"):
                return self._json(
                    200,
                    {
                        "state": "finished",
                        "output": {"video_url": self._base() + "/files/custom.mp4"},
                        "output_meta": {"duration": 4, "size": "640x360"},
                    },
                )
            if path.startswith("/files/"):
                suffix = path.rsplit(".", 1)[-1]
                if suffix == "mp4":
                    return self._send(200, MP4, "video/mp4")
                return self._send(200, PNG, "image/png")
            return self._json(404, {"error": {"message": f"no route {path}"}})

        # ------------------------------------------------------------ POST
        def do_POST(self) -> None:  # noqa: N802
            path = self.path.split("?", 1)[0]
            state.headers.append({k.lower(): v for k, v in self.headers.items()})
            state.paths.append(path)
            state.queries.append(self.path.split("?", 1)[1] if "?" in self.path else "")
            body = self._body()
            state.record("POST", path, body)

            if path in ("/v1/images/generations", "/images/generations"):
                model = str(body.get("model", ""))
                if model == "url-image":
                    return self._json(200, {"data": [{"url": self._base() + "/files/openai.png"}]})
                if model == "batch-image":
                    return self._json(200, {"data": [
                        {"b64_json": B64_PNG},
                        {"url": self._base() + "/files/openai.png"},
                        {"b64_json": B64_PNG},
                    ]})
                return self._json(200, {"data": [{"b64_json": B64_PNG}]})
            if "/openai/deployments/" in path and path.endswith("/images/edits"):
                if "multipart/form-data" not in self.headers.get("Content-Type", ""):
                    return self._json(400, {"error": {"message": "expected multipart"}})
                return self._json(200, {"data": [{"b64_json": B64_PNG}]})
            if path in ("/v1/images/edits", "/images/edits"):
                ctype = self.headers.get("Content-Type", "")
                if "multipart/form-data" not in ctype:
                    return self._json(400, {"error": {"message": "expected multipart"}})
                return self._json(200, {"data": [{"b64_json": B64_PNG}]})
            if path in ("/v1/audio/transcriptions", "/audio/transcriptions"):
                ctype = self.headers.get("Content-Type", "")
                if "multipart/form-data" not in ctype:
                    return self._json(400, {"error": {"message": "expected multipart"}})
                return self._json(200, {"text": "hello from mock"})
            if path in ("/custom/speech",):
                return self._send(200, b"WAVFAKE", "audio/wav")
            if path in ("/custom/transcribe",):
                if "multipart/form-data" not in self.headers.get("Content-Type", ""):
                    return self._json(400, {"error": {"message": "expected multipart"}})
                return self._json(200, {"data": {"text": "custom transcript"}})
            if path in ("/v1/audio/speech", "/audio/speech"):
                if body.get("input") is None:
                    return self._json(400, {"error": {"message": "input required"}})
                return self._send(200, b"ID3FAKEAUDIO", "audio/mpeg")
            if path in ("/v1/videos", "/videos"):
                return self._json(200, {"id": "video_1", "object": "video", "status": "queued"})
            if path == "/api/v3/contents/generations/tasks":
                return self._json(200, {"id": "cgt-1"})
            if path == "/api/v3/images/generations":
                return self._json(200, {"data": [{"b64_json": B64_PNG}]})
            if path == "/api/v1/services/aigc/text2image/image-synthesis":
                return self._json(200, {"output": {"task_id": "t1"}})
            if path == "/api/v1/services/aigc/video-generation/video-synthesis":
                return self._json(200, {"output": {"task_id": "t2"}})
            if path == "/v1/video_generation":
                return self._json(200, {"task_id": "m1", "base_resp": {"status_code": 0, "status_msg": "ok"}})
            if path == "/custom/t2i":
                return self._json(200, {"data": {"image": B64_PNG}})
            if path == "/custom/batch":
                return self._json(200, {"data": {"images": [
                    {"url": self._base() + "/files/a.png"},
                    {"url": self._base() + "/files/b.png"},
                ]}})
            if path == "/custom/tasks":
                return self._json(200, {"task": {"id": "c1"}})
            if path.endswith("/remix"):
                return self._json(200, {"id": "video_remix_1", "status": "queued"})
            if path == "/v1/videos/extensions":
                return self._json(200, {"id": "video_ext_1", "status": "queued"})
            if "/openai/deployments/" in path and path.endswith("/images/generations"):
                return self._json(200, {"data": [{"b64_json": B64_PNG}]})
            if path == "/v1/image_generation":
                return self._json(200, {"data": {"image_base64": [B64_PNG]}, "base_resp": {"status_code": 0}})
            return self._json(404, {"error": {"message": f"no route {path}"}})

    return Handler


class MockServer:
    def __init__(self, state: State | None = None):
        self.state = state or State()
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.state))
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self) -> "MockServer":
        self.thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()

    @property
    def port(self) -> int:
        return self.httpd.server_address[1]

    def url(self, prefix: str) -> str:
        return f"http://127.0.0.1:{self.port}{prefix}"


if __name__ == "__main__":
    import sys

    server = MockServer()
    server.thread.start()
    print(json.dumps({"port": server.port}), flush=True)
    try:
        server.thread.join()
    except KeyboardInterrupt:
        sys.exit(0)
