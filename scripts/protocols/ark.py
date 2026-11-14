"""Volcengine Ark native protocol (Seedance video, Seedream images).

    POST /contents/generations/tasks   {model, content:[{type:text,text},…], ratio?, resolution?, duration?}
    GET  /contents/generations/tasks/<id>   {status: queued|running|succeeded|failed, content:{video_url}}
    POST /images/generations           {model, prompt, size?, response_format?}  → {data:[{url|b64_json}]}

Base URL is typically ``https://ark.cn-beijing.volces.com/api/v3``.
"""

from __future__ import annotations

import base64
import json

from . import ImageResult, MediaError, Protocol, VideoState, data_uri, error_message, guess_suffix


class ArkProtocol(Protocol):
    name = "ark"

    def image(
        self, model: str, prompt: str, *, size: str | None, n: int, ref: str | None,
        mask: str | None = None,
    ) -> list[ImageResult]:
        if mask:
            raise MediaError(f"{self.name} 协议不支持遮罩（mask）")
        body: dict = {"model": model, "prompt": prompt, "response_format": "b64_json"}
        if size:
            body["size"] = size
        if n and n > 1:
            body["sequential_image_generation"] = "disabled"
            body["n"] = n
        if ref:
            body["image"] = data_uri(ref)
        status, payload, raw = self._request("POST", self.endpoint.base_url + "/images/generations", body)
        if status >= 400:
            raise MediaError(f"POST /images/generations → {status}：{error_message(payload, raw)}")
        return _decode_image(payload)

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
        content: list[dict] = [{"type": "text", "text": prompt}]
        if ref:
            content.append({"type": "image_url", "image_url": {"url": data_uri(ref)}})
        body: dict = {"model": model, "content": content}
        if seconds is not None and seconds > 0:
            body["duration"] = seconds
        if ratio:
            body["ratio"] = ratio
        if resolution:
            body["resolution"] = resolution
        if size and not (ratio or resolution):
            # Ark speaks ratio+resolution; a WxH size can still be passed through
            # and is rejected with an actionable message if unsupported.
            body["size"] = size
        status, payload, raw = self._request(
            "POST", self.endpoint.base_url + "/contents/generations/tasks", body
        )
        if status >= 400:
            raise MediaError(f"POST /contents/generations/tasks → {status}：{error_message(payload, raw)}")
        task_id = payload.get("id") or (payload.get("data") or {}).get("task_id")
        if not task_id:
            raise MediaError(f"Ark 没有返回任务 id：{json.dumps(payload)[:300]}")
        return str(task_id)

    def video_status(self, task_id: str) -> VideoState:
        payload = self._json("GET", f"/contents/generations/tasks/{task_id}")
        content = payload.get("content") or {}
        status = str(payload.get("status", "unknown")).lower()
        mapping = {"succeeded": "completed", "success": "completed", "queued": "queued", "running": "processing"}
        error = payload.get("error")
        return VideoState(
            status=mapping.get(status, status),
            task_id=task_id,
            url=content.get("video_url"),
            error=str(error.get("message") or error) if error else None,
            seconds=_as_text(payload.get("duration")) or _as_text(payload.get("seconds")),
            size=_as_text(payload.get("resolution")),
            usage=payload.get("usage") or {},
            last_frame_url=content.get("last_frame_url"),
            extra={k: v for k, v in payload.items() if k not in ("content", "usage")},
        )

    def video_fetch(self, task_id: str, state: VideoState) -> bytes:
        if not state.url:
            raise MediaError(f"Ark 任务 {task_id} 已完成但没有 video_url")
        return self.fetch(state.url)


def _as_text(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _decode_image(payload: dict) -> list[ImageResult]:
    data = payload.get("data")
    if not isinstance(data, list) or not data:
        raise MediaError(f"Ark 图片响应里没有 data：{json.dumps(payload)[:300]}")
    results: list[ImageResult] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        encoded = entry.get("b64_json")
        if encoded:
            try:
                results.append(ImageResult(data=base64.b64decode(encoded), suffix=".png"))
            except (ValueError, TypeError):
                raise MediaError("Ark 图片响应里的 b64_json 不是合法 base64") from None
            continue
        url = entry.get("url")
        if url:
            results.append(ImageResult(data=b"", suffix=guess_suffix(url), url=str(url)))
    if not results:
        raise MediaError(f"Ark 图片响应既没有 b64_json 也没有 url：{json.dumps(payload)[:300]}")
    return results
