"""Wire protocols for media generation.

Each protocol module implements the same small interface so the CLI does not
care whether it talks to a LiteLLM proxy, Volcengine Ark, DashScope, or
MiniMax:

    Protocol.list_models()                     -> list[str] | None
    Protocol.image(model, prompt, ...)         -> ImageResult          (sync)
    Protocol.video_create(model, prompt, ...)  -> str                 (task id)
    Protocol.video_status(task_id)             -> VideoState
    Protocol.video_fetch(task_id, state)       -> bytes

Protocols are selected by the configuration profile, so the same model id can be
reached through a gateway (``openai``) or its native API.
"""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field


class MediaError(RuntimeError):
    """A user-facing request or protocol failure."""


@dataclass
class Endpoint:
    protocol: str
    base_url: str
    key: str
    timeout: int = 120


@dataclass
class ImageResult:
    data: bytes
    suffix: str = ".png"
    url: str | None = None
    revised_prompt: str | None = None


@dataclass
class VideoState:
    status: str
    task_id: str
    url: str | None = None
    error: str | None = None
    seconds: str | None = None
    size: str | None = None
    usage: dict = field(default_factory=dict)
    extra: dict = field(default_factory=dict)

    @property
    def done(self) -> bool:
        return self.status in ("completed", "succeeded", "success")

    @property
    def failed(self) -> bool:
        return self.status in ("failed", "error", "cancelled", "canceled")


def data_uri(path: str) -> str:
    mime, _ = mimetypes.guess_type(path)
    mime = mime or "image/png"
    with open(path, "rb") as handle:
        payload = base64.b64encode(handle.read()).decode("ascii")
    return f"data:{mime};base64,{payload}"


class Protocol:
    name = ""
    supports = ("image", "video")

    def __init__(self, endpoint: Endpoint):
        self.endpoint = endpoint

    # ---------------------------------------------------------------- http

    def _request(
        self,
        method: str,
        url: str,
        body: dict | bytes | None = None,
        headers: dict | None = None,
        auth: bool = True,
    ) -> tuple[int, dict, bytes]:
        data = None
        request_headers = {"Accept": "application/json"}
        if isinstance(body, dict):
            data = json.dumps(body).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
        elif isinstance(body, bytes):
            data = body
        if auth and self.endpoint.key:
            request_headers["Authorization"] = f"Bearer {self.endpoint.key}"
        if headers:
            request_headers.update(headers)
        request = urllib.request.Request(url, data=data, headers=request_headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.endpoint.timeout) as response:
                raw = response.read()
                status = response.status
                content_type = response.headers.get("Content-Type", "")
        except urllib.error.HTTPError as error:
            raw = error.read()
            status = error.code
            content_type = error.headers.get("Content-Type", "") if error.headers else ""
        except (urllib.error.URLError, OSError) as error:
            reason = getattr(error, "reason", error)
            raise MediaError(f"连不上 {url}：{reason}") from None
        if "json" in content_type:
            try:
                return status, json.loads(raw or b"{}"), raw
            except ValueError:
                return status, {}, raw
        return status, {}, raw

    def _json(self, method: str, path: str, body: dict | None = None, headers: dict | None = None) -> dict:
        status, payload, raw = self._request(method, self.endpoint.base_url + path, body, headers)
        if status >= 400 or (not payload and raw and status != 200):
            raise MediaError(f"{method} {path} → {status}：{error_message(payload, raw)}")
        return payload

    def fetch(self, url: str) -> bytes:
        """Download an artifact URL. Never send our credentials to a foreign host."""
        same_host = url.startswith(self.endpoint.base_url)
        status, _, raw = self._request("GET", url, auth=same_host)
        if status >= 400:
            raise MediaError(f"下载 {url} → {status}")
        return raw

    # ------------------------------------------------------------ interface

    def list_models(self) -> list[str] | None:
        return None

    def image(self, model: str, prompt: str, *, size: str | None, n: int, ref: str | None) -> ImageResult:
        raise MediaError(f"{self.name} 协议不支持图片生成")

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
        raise MediaError(f"{self.name} 协议不支持视频生成")

    def video_status(self, task_id: str) -> VideoState:
        raise MediaError(f"{self.name} 协议不支持视频任务查询")

    def video_fetch(self, task_id: str, state: VideoState) -> bytes:
        raise MediaError(f"{self.name} 协议不支持视频下载")


def error_message(payload: dict, raw: bytes = b"") -> str:
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            message = error.get("message") or error.get("msg") or error.get("code")
            if message:
                return str(message)
        if isinstance(error, str) and error:
            return error
        for key in ("message", "msg", "detail", "base_resp"):
            value = payload.get(key)
            if isinstance(value, dict):
                value = value.get("status_msg") or value.get("message")
            if value:
                return str(value)
    text = raw.decode("utf-8", "replace").strip()
    return text[:400] if text else "（响应无正文）"


def guess_suffix(url: str | None, content_type: str = "", default: str = ".png") -> str:
    if url:
        path = url.split("?", 1)[0]
        suffix = os.path.splitext(path)[1].lower()
        if suffix in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
            return suffix
    if "jpeg" in content_type:
        return ".jpg"
    if "webp" in content_type:
        return ".webp"
    return default


def load_protocol(name: str):
    from . import ark, dashscope, minimax, openai

    table = {
        "openai": openai.OpenAIProtocol,
        "ark": ark.ArkProtocol,
        "dashscope": dashscope.DashScopeProtocol,
        "minimax": minimax.MinimaxProtocol,
    }
    try:
        return table[name]
    except KeyError:
        raise MediaError(f"未知协议 {name}；可选：{', '.join(sorted(table))}") from None
