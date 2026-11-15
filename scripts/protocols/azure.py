"""Azure OpenAI protocol: the openai wire shape with Azure's paths and auth.

    base_url  https://<resource>.openai.azure.com
    profile   {"protocol": "azure", "query": {"api-version": "2024-10-21"}}

Paths are deployment-scoped (``/openai/deployments/<model>/…``) and authentication uses the
``api-key`` header instead of a bearer token. Audio (speech/transcriptions) and images
(generations/edits) are supported; Azure has no video generation route, which the adapter says
plainly instead of 404-ing at the wrong URL.
"""

from __future__ import annotations

from . import MediaError
from .openai import OpenAIProtocol


class AzureProtocol(OpenAIProtocol):
    name = "azure"

    def _request(self, method, url, body=None, headers=None, auth=True):  # type: ignore[override]
        if auth and self.endpoint.key:
            headers = dict(headers or {})
            headers["api-key"] = self.endpoint.key
        return super()._request(method, url, body, headers, auth=False)

    def _deployment_url(self, model: str, suffix: str) -> str:
        return f"{self.endpoint.base_url}/openai/deployments/{model}{suffix}"

    # images / audio 走 deployment 路径；这里替换基类里的固定路径
    def image(  # type: ignore[override]
        self, model, prompt, *, size, n, ref, mask=None, params=None
    ):
        from . import encode_multipart, file_part

        if ref:
            fields = {"prompt": prompt, "n": n, "response_format": "b64_json"}
            if size:
                fields["size"] = size
            for key, value in (params or {}).items():
                fields[str(key)] = value
            files = {"image": file_part(ref)}
            if mask:
                files["mask"] = file_part(mask)
            payload, content_type = encode_multipart(fields, files)
            status, data, raw = self._request(
                "POST", self._deployment_url(model, "/images/edits"), payload,
                headers={"Content-Type": content_type},
            )
            if status >= 400:
                raise MediaError(f"POST /images/edits → {status}：{_text(data, raw)}")
            return _decode(data)
        body = {"prompt": prompt, "n": n, "response_format": "b64_json"}
        if size:
            body["size"] = size
        for key, value in (params or {}).items():
            body[str(key)] = value
        status, data, raw = self._request(
            "POST", self._deployment_url(model, "/images/generations"), body
        )
        if status >= 400:
            raise MediaError(f"POST /images/generations → {status}：{_text(data, raw)}")
        return _decode(data)

    def speech(self, model, text, *, voice, fmt):  # type: ignore[override]
        body = {"input": text}
        if voice:
            body["voice"] = voice
        if fmt:
            body["response_format"] = fmt
        status, data, raw = self._request("POST", self._deployment_url(model, "/audio/speech"), body)
        if status >= 400:
            raise MediaError(f"POST /audio/speech → {status}：{_text(data, raw)}")
        return raw, "." + (fmt or "mp3").lstrip(".")

    def transcribe(self, model, path, *, language):  # type: ignore[override]
        from . import encode_multipart, file_part

        fields = {"response_format": "json"}
        if language:
            fields["language"] = language
        body, content_type = encode_multipart(fields, {"file": file_part(path)})
        status, data, raw = self._request(
            "POST", self._deployment_url(model, "/audio/transcriptions"), body,
            headers={"Content-Type": content_type},
        )
        if status >= 400:
            raise MediaError(f"POST /audio/transcriptions → {status}：{_text(data, raw)}")
        text = data.get("text") if isinstance(data, dict) else None
        if not text:
            raise MediaError(f"转写响应里没有 text：{raw[:200]!r}")
        return str(text)

    def video_create(self, *args, **kwargs):  # type: ignore[override]
        raise MediaError("Azure OpenAI 没有视频生成路由；视频请用 openai/ark/dashscope/minimax 之一")


def _decode(payload: dict):
    from .openai import _decode_image_response

    return _decode_image_response(payload)


def _text(payload: dict, raw: bytes) -> str:
    from . import error_message

    return error_message(payload, raw)
