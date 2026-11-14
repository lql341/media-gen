"""MiniMax native protocol (Hailuo video, image-01).

    POST /video_generation            {model, prompt, duration?, resolution?, first_frame_image?}
    GET  /query/video_generation      ?task_id=…              {status: Queueing|Processing|Success|Fail}
    GET  /files/retrieve              ?file_id=…              {file:{download_url}}
    POST /image_generation            {model, prompt, aspect_ratio?, n?, response_format?}

Base URL is typically ``https://api.minimaxi.com/v1`` (international:
``https://api.minimax.io/v1``). Errors arrive as
``{"base_resp": {"status_code": 1004, "status_msg": "…"}}`` with HTTP 200, so the
payload has to be inspected, not just the status code.
"""

from __future__ import annotations

import base64
import json

from . import ImageResult, MediaError, Protocol, VideoState, data_uri, guess_suffix


class MinimaxProtocol(Protocol):
    name = "minimax"

    def _check(self, payload: dict, label: str) -> dict:
        base = payload.get("base_resp")
        if isinstance(base, dict):
            code = base.get("status_code")
            if code not in (0, None, "0"):
                message = base.get("status_msg") or f"status_code={code}"
                raise MediaError(f"{label} 失败：{message}")
        return payload

    # ------------------------------------------------------------- images

    def image(
        self, model: str, prompt: str, *, size: str | None, n: int, ref: str | None,
        mask: str | None = None,
    ) -> list[ImageResult]:
        if mask:
            raise MediaError(f"{self.name} 协议不支持遮罩（mask）")
        body: dict = {"model": model, "prompt": prompt, "n": n, "response_format": "base64"}
        if size:
            if "x" in size.lower() or "*" in size:
                width, height = _split_size(size)
                body["width"], body["height"] = width, height
            else:
                body["aspect_ratio"] = size
        if ref:
            body["subject_reference"] = [{"type": "character", "image_file": data_uri(ref)}]
        status, payload, raw = self._request("POST", self.endpoint.base_url + "/image_generation", body)
        if status >= 400:
            raise MediaError(f"POST /image_generation → {status}：{_text(payload, raw)}")
        self._check(payload, "MiniMax 图片生成")
        data = payload.get("data") or {}
        encoded_items = data.get("image_base64") or []
        if encoded_items:
            images: list[ImageResult] = []
            for encoded in encoded_items:
                try:
                    images.append(ImageResult(data=base64.b64decode(encoded), suffix=".jpeg"))
                except (ValueError, TypeError):
                    raise MediaError("MiniMax 返回的 image_base64 不是合法 base64") from None
            return images
        urls = data.get("image_urls") or []
        if urls:
            return [ImageResult(data=b"", suffix=guess_suffix(str(url)), url=str(url)) for url in urls]
        raise MediaError(f"MiniMax 图片响应里没有图像：{json.dumps(payload)[:300]}")

    # ------------------------------------------------------------- videos

    def video_create(
        self,
        model: str,
        prompt: str,
        *,
        seconds: int | None,
        size: str | None,
        resolution: str | None,
        ratio: str | None,
        ref: str | None,
    ) -> str:
        body: dict = {"model": model, "prompt": prompt}
        if seconds is not None and seconds > 0:
            body["duration"] = seconds
        if resolution:
            body["resolution"] = resolution
        if ref:
            body["first_frame_image"] = data_uri(ref)
        status, payload, raw = self._request("POST", self.endpoint.base_url + "/video_generation", body)
        if status >= 400:
            raise MediaError(f"POST /video_generation → {status}：{_text(payload, raw)}")
        self._check(payload, "MiniMax 视频生成")
        task_id = payload.get("task_id")
        if not task_id:
            raise MediaError(f"MiniMax 没有返回 task_id：{json.dumps(payload)[:300]}")
        return str(task_id)

    def video_status(self, task_id: str) -> VideoState:
        status_code, payload, raw = self._request(
            "GET", self.endpoint.base_url + f"/query/video_generation?task_id={task_id}"
        )
        if status_code >= 400:
            raise MediaError(f"GET /query/video_generation → {status_code}：{_text(payload, raw)}")
        self._check(payload, "MiniMax 任务查询")
        raw_status = str(payload.get("status", "unknown"))
        mapping = {
            "Queueing": "queued",
            "Preparing": "queued",
            "Processing": "processing",
            "Success": "completed",
            "Fail": "failed",
        }
        state = VideoState(
            status=mapping.get(raw_status, raw_status.lower()),
            task_id=task_id,
            error=None,
            extra={"raw_status": raw_status},
        )
        if state.status == "failed":
            state.error = str(payload.get("base_resp") or raw_status)
        if state.done and payload.get("file_id"):
            state.extra["file_id"] = payload["file_id"]
        return state

    def video_fetch(self, task_id: str, state: VideoState) -> bytes:
        file_id = state.extra.get("file_id") if isinstance(state.extra, dict) else None
        if not file_id:
            raise MediaError(f"MiniMax 任务 {task_id} 没有 file_id，无法取回文件")
        status_code, payload, raw = self._request(
            "GET", self.endpoint.base_url + f"/files/retrieve?file_id={file_id}"
        )
        if status_code >= 400:
            raise MediaError(f"GET /files/retrieve → {status_code}：{_text(payload, raw)}")
        self._check(payload, "MiniMax 文件检索")
        file_info = payload.get("file") or {}
        url = file_info.get("download_url")
        if not url:
            raise MediaError(f"MiniMax 文件检索没有 download_url：{json.dumps(payload)[:300]}")
        return self.fetch(str(url))


def _split_size(size: str) -> tuple[int, int]:
    cleaned = size.strip().lower().replace("*", "x").replace("×", "x")
    parts = cleaned.split("x")
    if len(parts) != 2 or not all(part.isdigit() and int(part) > 0 for part in parts):
        raise MediaError(f"尺寸格式不对：{size!r}（需要 1024x1024 这样的像素值）")
    return int(parts[0]), int(parts[1])


def _text(payload: dict, raw: bytes) -> str:
    base = payload.get("base_resp") if isinstance(payload, dict) else None
    if isinstance(base, dict) and base.get("status_msg"):
        return str(base["status_msg"])
    text = raw.decode("utf-8", "replace").strip()
    return text[:300] if text else "（响应无正文）"
