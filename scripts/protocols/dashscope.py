"""Alibaba Cloud DashScope / Bailian native protocol (Wan image & video).

    POST /services/aigc/text2image/image-synthesis   (header X-DashScope-Async: enable)
    POST /services/aigc/video-generation/video-synthesis
    GET  /tasks/<task_id>                            {output:{task_status, results|video_url}}

Base URL is typically ``https://dashscope.aliyuncs.com/api/v1``. Sizes use the
``1024*1024`` syntax, durations are seconds, and image-to-video needs a publicly
reachable ``img_url`` (the HTTP API does not accept local paths or base64).
"""

from __future__ import annotations

import json

from . import ImageResult, MediaError, Protocol, VideoState, error_message, guess_suffix

DONE = {"SUCCEEDED", "SUCCESS", "SUCCEED"}
FAILED = {"FAILED", "CANCELED", "UNKNOWN"}


class DashScopeProtocol(Protocol):
    name = "dashscope"

    def _submit(self, path: str, body: dict, label: str) -> str:
        status, payload, raw = self._request(
            "POST",
            self.endpoint.base_url + path,
            body,
            headers={"X-DashScope-Async": "enable"},
        )
        if status >= 400:
            raise MediaError(f"POST {label} → {status}：{error_message(payload, raw)}")
        task_id = (payload.get("output") or {}).get("task_id")
        if not task_id:
            raise MediaError(f"DashScope 没有返回 task_id：{json.dumps(payload)[:300]}")
        return str(task_id)

    def _task(self, task_id: str) -> dict:
        status, payload, raw = self._request("GET", self.endpoint.base_url + f"/tasks/{task_id}")
        if status >= 400:
            raise MediaError(f"GET /tasks/{task_id} → {status}：{error_message(payload, raw)}")
        return payload.get("output") or {}

    # ------------------------------------------------------------- images

    def image(
        self, model: str, prompt: str, *, size: str | None, n: int, ref: str | None,
        mask: str | None = None,
    ) -> list[ImageResult]:
        if mask:
            raise MediaError(f"{self.name} 协议不支持遮罩（mask）")
        parameters: dict = {"n": n}
        if size:
            parameters["size"] = size
        if ref:
            raise MediaError("DashScope 文生图不支持参考图；图生图请用 wan*-imageedit 或换协议")
        body = {"model": model, "input": {"prompt": prompt}, "parameters": parameters}
        task_id = self._submit("/services/aigc/text2image/image-synthesis", body, "/text2image/image-synthesis")
        output = self._task(task_id)
        state = str(output.get("task_status", "")).upper()
        if state in FAILED:
            raise MediaError(f"DashScope 图片任务失败：{output.get('message') or state}")
        results = output.get("results") or []
        if not results:
            raise MediaError(f"DashScope 图片任务 {task_id} 没有返回结果（status={state}）")
        images: list[ImageResult] = []
        for entry in results:
            url = entry.get("url") if isinstance(entry, dict) else None
            if url:
                images.append(ImageResult(data=b"", suffix=guess_suffix(str(url)), url=str(url)))
        if not images:
            raise MediaError(f"DashScope 图片结果没有 url：{json.dumps(results[0])[:200]}")
        return images

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
        inputs: dict = {"prompt": prompt}
        if ref:
            if not ref.startswith(("http://", "https://")):
                raise MediaError(
                    "DashScope 图生视频的 img_url 必须是公网可访问的 URL（本机文件不行）；"
                    "先把首帧图上传到可访问的地址，或改用 ark / minimax 协议"
                )
            inputs["img_url"] = ref
        parameters: dict = {}
        if size:
            parameters["size"] = size
        if resolution:
            parameters["resolution"] = resolution
        if ratio:
            parameters["aspect_ratio"] = ratio
        if seconds is not None and seconds > 0:
            parameters["duration"] = seconds
        body = {"model": model, "input": inputs, "parameters": parameters}
        return self._submit(
            "/services/aigc/video-generation/video-synthesis", body, "/video-generation/video-synthesis"
        )

    def video_status(self, task_id: str) -> VideoState:
        output = self._task(task_id)
        raw_status = str(output.get("task_status", "unknown")).upper()
        if raw_status in DONE:
            status = "completed"
        elif raw_status in FAILED:
            status = "failed"
        elif raw_status in ("PENDING",):
            status = "queued"
        elif raw_status in ("RUNNING",):
            status = "processing"
        else:
            status = raw_status.lower()
        return VideoState(
            status=status,
            task_id=task_id,
            url=output.get("video_url"),
            error=output.get("message") if status == "failed" else None,
            seconds=_as_text(output.get("duration")),
            size=_as_text(output.get("size")),
            usage=output.get("usage") or {},
            extra={"raw_status": raw_status},
        )

    def video_fetch(self, task_id: str, state: VideoState) -> bytes:
        if not state.url:
            raise MediaError(f"DashScope 任务 {task_id} 已完成但没有 video_url")
        return self.fetch(state.url)


def _as_text(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)
