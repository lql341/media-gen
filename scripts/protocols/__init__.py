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
import urllib.parse
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
    headers: dict | None = None      # profile 级固定请求头（如 OpenAI-Organization）
    query: dict | None = None        # profile 级固定 query（如 Azure 的 api-version）


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
    last_frame_url: str | None = None

    @property
    def done(self) -> bool:
        return self.status in ("completed", "succeeded", "success")

    @property
    def failed(self) -> bool:
        return self.status in ("failed", "error", "cancelled", "canceled")


def encode_multipart(fields: dict, files: dict) -> tuple[bytes, str]:
    """把字段与文件编码成 multipart/form-data（stdlib 实现，用于 /videos 与 /images/edits）。

    files: {field_name: (filename, bytes, mime)}
    """
    import uuid

    boundary = "----media-gen-" + uuid.uuid4().hex
    chunks: list[bytes] = []
    for name, value in fields.items():
        if value is None:
            continue
        chunks.append(f'--{boundary}\r\n'.encode())
        chunks.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        chunks.append(str(value).encode("utf-8"))
        chunks.append(b"\r\n")
    for name, (filename, payload, mime) in files.items():
        chunks.append(f'--{boundary}\r\n'.encode())
        chunks.append(
            f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'.encode()
        )
        chunks.append(f"Content-Type: {mime}\r\n\r\n".encode())
        chunks.append(payload)
        chunks.append(b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def file_part(path: str) -> tuple[str, bytes, str]:
    import os as _os

    mime, _ = mimetypes.guess_type(path)
    with open(path, "rb") as handle:
        payload = handle.read()
    return _os.path.basename(path), payload, mime or "application/octet-stream"


def data_uri(path: str) -> str:
    mime, _ = mimetypes.guess_type(path)
    mime = mime or "image/png"
    with open(path, "rb") as handle:
        payload = base64.b64encode(handle.read()).decode("ascii")
    return f"data:{mime};base64,{payload}"


def write_atomic(path: str, payload: bytes) -> None:
    """先写 ``<path>.part`` 再 rename：中断/失败不会留下半个文件。"""
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    temporary = f"{path}.part"
    try:
        with open(temporary, "wb") as handle:
            handle.write(payload)
        os.replace(temporary, path)
    except OSError:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


class Protocol:
    name = ""
    supports = ("image", "video")

    def __init__(self, endpoint: Endpoint, spec: dict | None = None):
        self.endpoint = endpoint
        self.spec = spec or {}

    # ---------------------------------------------------------------- http

    def _with_query(self, url: str) -> str:
        if not self.endpoint.query:
            return url
        separator = "&" if "?" in url else "?"
        return url + separator + urllib.parse.urlencode(self.endpoint.query)

    def _build_headers(self, auth: bool, extra: dict | None = None) -> dict:
        """auth < profile 固定头 < 调用方显式头。"""
        headers: dict[str, str] = {}
        if auth and self.endpoint.key:
            headers["Authorization"] = f"Bearer {self.endpoint.key}"
        if self.endpoint.headers:
            headers.update({str(k): str(v) for k, v in self.endpoint.headers.items()})
        if extra:
            headers.update(extra)
        return headers

    def _request(
        self,
        method: str,
        url: str,
        body: dict | bytes | None = None,
        headers: dict | None = None,
        auth: bool = True,
    ) -> tuple[int, dict, bytes]:
        url = self._with_query(url)
        data = None
        extra = {"Accept": "application/json"}
        if isinstance(body, dict):
            data = json.dumps(body).encode("utf-8")
            extra["Content-Type"] = "application/json"
        elif isinstance(body, bytes):
            data = body
        request_headers = self._build_headers(auth, {**extra, **(headers or {})})
        attempts = 1 + (retry_count() if method == "GET" else 0)
        last: tuple[int, dict, bytes] | None = None
        for attempt in range(attempts):
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
                if attempt + 1 < attempts:
                    import time as _time

                    _time.sleep(0.5 * (2 ** attempt))
                    continue
                reason = getattr(error, "reason", error)
                raise MediaError(f"连不上 {url}：{reason}") from None
            last = (status, {}, raw)
            if status in (429, 500, 502, 503, 504) and attempt + 1 < attempts:
                import time as _time

                _time.sleep(0.5 * (2 ** attempt))
                continue
            break
        status, _, raw = last if last else (0, {}, b"")
        content_type = locals().get("content_type", "") or ""
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

    def _same_origin(self, url: str) -> bool:
        """是否就是配置档端点本身（凭据只发给它）。

        不能用字符串前缀：``https://gw.example.com.evil.net`` 也以
        ``https://gw.example.com`` 开头，那样会把 Authorization 发给外站。
        """
        def parts(value: str):
            try:
                split = urllib.parse.urlsplit(value)
                scheme = split.scheme.lower()
                return scheme, (split.hostname or "").lower(), split.port or (443 if scheme == "https" else 80)
            except ValueError:   # 端口不是数字之类：当作不同源
                return None

        here = parts(self.endpoint.base_url)
        return here is not None and parts(url) == here

    def fetch(self, url: str) -> bytes:
        """Download an artifact URL. Never send our credentials to a foreign host."""
        status, _, raw = self._request("GET", url, auth=self._same_origin(url))
        if status >= 400:
            raise MediaError(f"下载 {url} → {status}")
        return raw

    def download(self, url: str, path: str, *, chunk: int = 1 << 20) -> int:
        """把产物流式写到 ``path``（先 ``.part`` 再原子替换），返回字节数。

        视频动辄几十上百 MB，不再整块读进内存；只在还没有写入任何字节时重试，
        否则可能把一段残片当成完整文件保留下来。
        """
        url = self._with_query(url)
        headers = self._build_headers(self._same_origin(url), {"Accept": "*/*"})
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        temporary = f"{path}.part"
        attempts = 1 + retry_count()
        for attempt in range(attempts):
            written = 0
            try:
                request = urllib.request.Request(url, headers=headers, method="GET")
                with urllib.request.urlopen(request, timeout=self.endpoint.timeout) as response:
                    with open(temporary, "wb") as handle:
                        while True:
                            block = response.read(chunk)
                            if not block:
                                break
                            handle.write(block)
                            written += len(block)
                os.replace(temporary, path)
                return written
            except urllib.error.HTTPError as error:
                self._drop(temporary)
                if error.code in (429, 500, 502, 503, 504) and attempt + 1 < attempts:
                    import time as _time

                    _time.sleep(0.5 * (2 ** attempt))
                    continue
                raise MediaError(f"下载 {url} → {error.code}") from None
            except (urllib.error.URLError, OSError) as error:
                self._drop(temporary)
                if written == 0 and attempt + 1 < attempts:
                    import time as _time

                    _time.sleep(0.5 * (2 ** attempt))
                    continue
                reason = getattr(error, "reason", error)
                raise MediaError(f"下载 {url} 失败（已写 {written} 字节）：{reason}") from None
        raise MediaError(f"下载 {url} 失败")

    @staticmethod
    def _drop(path: str) -> None:
        try:
            os.unlink(path)
        except OSError:
            pass

    # ------------------------------------------------------------ interface

    def list_models(self) -> list[str] | None:
        return None

    def image(
        self, model: str, prompt: str, *, size: str | None, n: int, ref: str | None,
        mask: str | None = None, params: dict | None = None,
    ) -> list[ImageResult]:
        raise MediaError(f"{self.name} 协议不支持图片生成")

    def speech(self, model: str, text: str, *, voice: str | None, fmt: str | None) -> tuple[bytes, str]:
        raise MediaError(f"{self.name} 协议不支持语音合成（/audio/speech）")

    def transcribe(self, model: str, path: str, *, language: str | None) -> str:
        raise MediaError(f"{self.name} 协议不支持语音转写（/audio/transcriptions）")

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
        raise MediaError(f"{self.name} 协议不支持视频生成")

    def video_status(self, task_id: str) -> VideoState:
        raise MediaError(f"{self.name} 协议不支持视频任务查询")

    def video_fetch(self, task_id: str, state: VideoState) -> bytes:
        raise MediaError(f"{self.name} 协议不支持视频下载")

    def video_download(self, task_id: str, state: VideoState, path: str) -> int:
        """把完成的视频写到 path。有直链就流式下载，只有字节的协议退回 video_fetch。"""
        if state.url:
            return self.download(state.url, path)
        payload = self.video_fetch(task_id, state)
        write_atomic(path, payload)
        return len(payload)


def retry_count() -> int:
    """GET 重试次数（轮询/下载抗抖动）；默认 2，可用 MEDIA_RETRY 调整。"""
    raw = os.environ.get("MEDIA_RETRY", "2").strip()
    try:
        return max(0, min(5, int(raw)))
    except ValueError:
        return 2


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
    # 网关把后端 Python 栈整个回给我们时，只留第一段（异常摘要），不要把栈帧塞给用户
    traceback_at = text.find("\nTraceback (most recent call last)")
    if traceback_at > 0:
        text = text[:traceback_at].strip()
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
    from . import ark, azure, command, custom, dashscope, minimax, openai

    table = {
        "openai": openai.OpenAIProtocol,
        "azure": azure.AzureProtocol,
        "ark": ark.ArkProtocol,
        "dashscope": dashscope.DashScopeProtocol,
        "minimax": minimax.MinimaxProtocol,
        # 非官方端点：声明式模板 / 命令钩子
        "custom": custom.CustomProtocol,
        "command": command.CommandProtocol,
    }
    try:
        return table[name]
    except KeyError:
        raise MediaError(f"未知协议 {name}；可选：{', '.join(sorted(table))}") from None
