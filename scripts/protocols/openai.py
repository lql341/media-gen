"""OpenAI-compatible media endpoints: images (sync) and videos (async).

Covers OpenAI itself, LiteLLM proxies, and anything else that speaks:

    POST /images/generations   {model, prompt, size?, n?, response_format?}
    POST /videos               {model, prompt, size?, seconds?}   (multipart optional)
    GET  /videos/<id>          {status, ...}
    GET  /videos/<id>/content  binary (may answer 307 to object storage)

Some deployments only implement the Videos routes (a LiteLLM gateway serving
Seedance, for example); some only implement images. Capabilities are reported by
the endpoint's own errors, not guessed here.
"""

from __future__ import annotations

import base64
import json

from . import Endpoint, ImageResult, MediaError, Protocol, VideoState, data_uri, error_message, guess_suffix


class OpenAIProtocol(Protocol):
    name = "openai"

    def list_models(self) -> list[str] | None:
        status, payload, raw = self._request("GET", self.endpoint.base_url + "/models")
        if status == 404 or status == 405:
            return None
        if status >= 400:
            raise MediaError(f"GET /models → {status}：{error_message(payload, raw)}")
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list):
            return None
        return [entry["id"] for entry in data if isinstance(entry, dict) and entry.get("id")]

    # ------------------------------------------------------------- images

    def image(self, model: str, prompt: str, *, size: str | None, n: int, ref: str | None) -> list[ImageResult]:
        body: dict = {"model": model, "prompt": prompt, "n": n, "response_format": "b64_json"}
        if size:
            body["size"] = size
        if ref:
            # Image editing is a different route; sending it through the plain
            # generation route is silently ignored by most gateways, so be explicit.
            raise MediaError(
                "openai 协议的图片参考图需要 /images/edits（multipart）；"
                "先不带 --image 生成，或改用支持 image_input 的原生协议"
            )
        status, payload, raw = self._request(
            "POST", self.endpoint.base_url + "/images/generations", body
        )
        if status >= 400:
            raise MediaError(f"POST /images/generations → {status}：{error_message(payload, raw)}")
        return _decode_image_response(payload)

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
        if seconds is not None:
            body["seconds"] = seconds
        if size:
            body["size"] = size
        extra: dict = {}
        if ratio:
            extra["ratio"] = ratio
        if resolution:
            extra["resolution"] = resolution
        if extra:
            body["extra_body"] = extra
        if ref:
            raise MediaError(
                "openai 协议的首帧图需要 multipart input_reference；"
                "请用 --image 配合支持它的网关，或改用 ark / dashscope / minimax 原生协议"
            )
        status, payload, raw = self._request("POST", self.endpoint.base_url + "/videos", body)
        if status >= 400:
            raise MediaError(f"POST /videos → {status}：{error_message(payload, raw)}")
        task_id = payload.get("id") or payload.get("task_id")
        if not task_id:
            raise MediaError(f"POST /videos 没有返回任务 id：{json.dumps(payload)[:300]}")
        return str(task_id)

    def video_status(self, task_id: str) -> VideoState:
        payload = self._json("GET", f"/videos/{task_id}")
        result = payload.get("result") or {}
        state = VideoState(
            status=str(payload.get("status", "unknown")),
            task_id=task_id,
            url=result.get("url") or payload.get("url"),
            error=_error_of(payload),
            seconds=_as_text(payload.get("seconds") or result.get("duration")),
            size=_as_text(payload.get("size")),
            usage=payload.get("usage") or {},
            extra={k: v for k, v in payload.items() if k not in ("id", "object", "result", "usage")},
        )
        return state

    def video_fetch(self, task_id: str, state: VideoState) -> bytes:
        status, _, raw = self._request("GET", self.endpoint.base_url + f"/videos/{task_id}/content")
        if status < 400 and raw:
            return raw
        if state.url:
            return self.fetch(state.url)
        raise MediaError(f"GET /videos/{task_id}/content → {status}，且没有可用的 result.url")


def _error_of(payload: dict) -> str | None:
    error = payload.get("error")
    if not error:
        return None
    if isinstance(error, dict):
        return str(error.get("message") or error.get("code") or error)
    return str(error)


def _as_text(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _decode_image_response(payload: dict) -> list[ImageResult]:
    data = payload.get("data")
    if not isinstance(data, list) or not data:
        raise MediaError(f"图片响应里没有 data：{json.dumps(payload)[:300]}")
    results: list[ImageResult] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        revised = entry.get("revised_prompt")
        encoded = entry.get("b64_json") or entry.get("b64")
        if encoded:
            try:
                results.append(ImageResult(data=base64.b64decode(encoded), suffix=".png", revised_prompt=revised))
            except (ValueError, TypeError):
                raise MediaError("图片响应里的 b64_json 不是合法 base64") from None
            continue
        url = entry.get("url")
        if url:
            results.append(ImageResult(data=b"", suffix=guess_suffix(url), url=str(url), revised_prompt=revised))
    if not results:
        raise MediaError(f"图片响应既没有 b64_json 也没有 url：{json.dumps(payload)[:300]}")
    return results
