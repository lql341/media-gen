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
    ImageResult, MediaError, Protocol, VideoState, data_uri, encode_multipart,
    error_message, file_part, guess_suffix,
)


_LOGGED_VARIANTS: list[str] = []


class OpenAIProtocol(Protocol):
    name = "openai"

    def _video_multipart(self, model, prompt, seconds, size, extra, ref):
        fields = {"model": model, "prompt": prompt}
        for key, value in (("seconds", seconds), ("size", size)):
            if value is not None:
                fields[key] = value
        if extra:
            fields["extra_body"] = json.dumps(extra, ensure_ascii=False)
        payload, content_type = encode_multipart(fields, {"input_reference": file_part(ref)})
        return self._request("POST", self.endpoint.base_url + "/videos", payload,
                             headers={"Content-Type": content_type})

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
        self, model: str, prompt: str, *, size: str | None, n: int, ref: str | None,
        mask: str | None = None, params: dict | None = None,
    ) -> list[ImageResult]:
        if ref:
            # 参考图 / 遮罩：/images/edits（multipart）
            fields = {"model": model, "prompt": prompt, "n": n, "response_format": "b64_json"}
            if size:
                fields["size"] = size
            for key, value in (params or {}).items():
                fields[str(key)] = value
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
        if params:
            body.update({str(k): v for k, v in params.items()})
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
        params: dict | None = None,
    ) -> str:
        body: dict = {"model": model, "prompt": prompt}
        if seconds is not None:
            body["seconds"] = seconds
        if size:
            body["size"] = size
        extra: dict = dict(params or {})
        if ratio:
            extra["ratio"] = ratio
        if resolution:
            extra["resolution"] = resolution
        if extra:
            body["extra_body"] = extra
        if ref:
            # 图生视频。标准形态是 multipart + input_reference（OpenAI Videos / LiteLLM 的 OpenAPI
            # 就是这么声明的），但网关实现对 JSON-only 的也不少，所以按顺序试，只在 4xx 校验失败时
            # 才换下一种（4xx 不会建出计费任务，换法安全）。
            reference_uri = ref if str(ref).startswith(("http://", "https://")) else data_uri(ref)
            # 首帧任务的网关语义：ratio 必须 adaptive，且尺寸要走 extra_body 的原生参数
            native = dict(extra)
            native.setdefault("ratio", ratio or "adaptive")
            if resolution:
                native.setdefault("resolution", resolution)
            body_for_ref = {key: value for key, value in body.items() if key != "size"}
            attempts = [
                *(
                    []
                    if str(ref).startswith(("http://", "https://"))
                    else [("multipart input_reference",
                           lambda: self._video_multipart(model, prompt, seconds, size, extra, ref))]
                ),
                (
                    "json input_reference",
                    lambda: self._request("POST", self.endpoint.base_url + "/videos",
                                          {**body_for_ref, "input_reference": reference_uri,
                                           **({"extra_body": native} if native else {})}),
                ),
                (
                    "json image",
                    lambda: self._request("POST", self.endpoint.base_url + "/videos",
                                          {**body_for_ref, "image": reference_uri,
                                           **({"extra_body": native} if native else {})}),
                ),
                (
                    "json content[]",
                    lambda: self._request("POST", self.endpoint.base_url + "/videos", {
                        "model": model,
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": reference_uri}},
                        ],
                        **({"seconds": seconds} if seconds is not None else {}),
                        **({"extra_body": native} if native else {}),
                    }),
                ),
            ]
            last_error = ""
            for label, attempt in attempts:
                status, payload, raw = attempt()
                if status < 400:
                    if label != "multipart input_reference":
                        _LOGGED_VARIANTS.append(label)
                        print(f"note: 网关不接受 multipart，已回退到 {label}", file=__import__("sys").stderr)
                    break
                last_error = f"{label}: {status} {error_message(payload, raw)}"
                if status not in (400, 415, 422):
                    raise MediaError(f"POST /videos → {status}：{error_message(payload, raw)}")
            else:
                raise MediaError(f"POST /videos 的四种首帧传法都被拒绝（最后一次：{last_error}）")
        else:
            status, payload, raw = self._request("POST", self.endpoint.base_url + "/videos", body)
            if status >= 400:
                raise MediaError(f"POST /videos → {status}：{error_message(payload, raw)}")
        task_id = payload.get("id") or payload.get("task_id")
        if not task_id:
            raise MediaError(f"POST /videos 没有返回任务 id：{json.dumps(payload)[:300]}")
        return str(task_id)

    def video_list(self, model: str, limit: int = 20) -> list[dict]:
        payload = self._json("GET", f"/videos?model={model}")
        items = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            items = payload.get("videos") if isinstance(payload, dict) else None
        return [item for item in (items or []) if isinstance(item, dict)][:limit]

    def video_remix(self, task_id: str, prompt: str) -> str:
        status, payload, raw = self._request(
            "POST", self.endpoint.base_url + f"/videos/{task_id}/remix", {"prompt": prompt}
        )
        if status >= 400:
            raise MediaError(f"POST /videos/{task_id}/remix → {status}：{error_message(payload, raw)}")
        new_id = payload.get("id") or payload.get("task_id") or payload.get("video_id")
        if not new_id:
            raise MediaError(f"remix 没有返回新任务 id：{json.dumps(payload)[:300]}")
        return str(new_id)

    def video_extend(self, task_id: str, prompt: str, seconds: int | None) -> str:
        body: dict = {"video_id": task_id, "prompt": prompt}
        if seconds is not None:
            body["seconds"] = seconds
        status, payload, raw = self._request(
            "POST", self.endpoint.base_url + "/videos/extensions", body
        )
        if status >= 400:
            raise MediaError(f"POST /videos/extensions → {status}：{error_message(payload, raw)}")
        new_id = payload.get("id") or payload.get("task_id") or payload.get("video_id")
        if not new_id:
            raise MediaError(f"extensions 没有返回新任务 id：{json.dumps(payload)[:300]}")
        return str(new_id)

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

    def video_download(self, task_id: str, state: VideoState, path: str) -> int:
        """优先流式拉 /videos/<id>/content（带凭据）；网关没这条路由时退回 result.url。"""
        try:
            return self.download(self.endpoint.base_url + f"/videos/{task_id}/content", path)
        except MediaError as error:
            if not state.url:
                raise MediaError(str(error)) from None
            return self.download(state.url, path)

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
