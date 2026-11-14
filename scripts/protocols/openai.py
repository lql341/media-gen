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

from . import (
    Endpoint, ImageResult, MediaError, Protocol, VideoState, data_uri, encode_multipart,
    error_message, file_part, guess_suffix,
)


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

    def image(
        self, model: str, prompt: str, *, size: str | None, n: int, ref: str | None, mask: str | None = None
    ) -> list[ImageResult]:
        if ref:
            # 参考图 / 遮罩：/images/edits（multipart）
            fields = {"model": model, "prompt": prompt, "n": n, "response_format": "b64_json"}
            if size:
                fields["size"] = size
            files = {"image": file_part(ref)}
            if mask:
                files["mask"] = file_part(mask)
            body, content_type = encode_multipart(fields, files)
            status, payload, raw = self._request(
                "POST", self.endpoint.base_url + "/images/edits", body,
                headers={"Content-Type": content_type},
            )
            if status >= 400:
                raise MediaError(f"POST /images/edits → {status}：{error_message(payload, raw)}")
            return _decode_image_response(payload)
        body: dict = {"model": model, "prompt": prompt, "n": n, "response_format": "b64_json"}
        if size:
            body["size"] = size
        status, payload, raw = self._request(
            "POST", self.endpoint.base_url + "/images/generations", body
        )
        if status >= 400:
            raise MediaError(f"POST /images/generations → {status}：{error_message(payload, raw)}")
        return _decode_image_response(payload)

    def speech(self, model: str, text: str, *, voice: str | None, fmt: str | None) -> tuple[bytes, str]:
        body: dict = {"model": model, "input": text}
        if voice:
            body["voice"] = voice
        if fmt:
            body["response_format"] = fmt
        status, payload, raw = self._request("POST", self.endpoint.base_url + "/audio/speech", body)
        if status >= 400:
            raise MediaError(f"POST /audio/speech → {status}：{error_message(payload, raw)}")
        if not raw:
            raise MediaError("POST /audio/speech 没有返回音频内容")
        suffix = "." + (fmt or "mp3").lstrip(".")
        return raw, suffix

    def transcribe(self, model: str, path: str, *, language: str | None) -> str:
        fields = {"model": model, "response_format": "json"}
        if language:
            fields["language"] = language
        body, content_type = encode_multipart(fields, {"file": file_part(path)})
        status, payload, raw = self._request(
            "POST", self.endpoint.base_url + "/audio/transcriptions", body,
            headers={"Content-Type": content_type},
        )
        if status >= 400:
            raise MediaError(f"POST /audio/transcriptions → {status}：{error_message(payload, raw)}")
        text = payload.get("text") if isinstance(payload, dict) else None
        if not text:
            raise MediaError(f"转写响应里没有 text：{raw[:200]!r}")
        return str(text)

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
            # 图生视频：multipart + input_reference（OpenAI Videos / LiteLLM 的标准形态）
            fields = {"model": model, "prompt": prompt}
            for key, value in (("seconds", seconds), ("size", size)):
                if value is not None:
                    fields[key] = value
            if extra:
                fields["extra_body"] = json.dumps(extra, ensure_ascii=False)
            body_bytes, content_type = encode_multipart(fields, {"input_reference": file_part(ref)})
            status, payload, raw = self._request(
                "POST", self.endpoint.base_url + "/videos", body_bytes,
                headers={"Content-Type": content_type},
            )
        else:
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
            last_frame_url=result.get("last_frame_url"),
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
