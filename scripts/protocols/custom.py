"""Declarative "custom" protocol: describe an in-house endpoint with templates.

Many non-official endpoints are one JSON shape away from the built-in protocols.
Instead of writing Python, describe the shape once in a file and reference it from
the profile:

    ~/.config/media-gen/custom/<profile>.json
    {
      "auth": {"mode": "bearer"},                     // or header/query
      "image": {
        "method": "POST", "path": "/v1/t2i",
        "body": {"model": "{model}", "prompt": "{prompt}", "size": "{size}"},
        "response": {"mode": "b64", "path": "data.0.image"}
      },
      "video": {
        "create": {"method": "POST", "path": "/v1/tasks",
                   "body": {"model": "{model}", "input": {"text": "{prompt}"},
                            "seconds": "{seconds}", "size": "{size}"}},
        "task_id_path": "task.id",
        "status": {"path": "/v1/tasks/{task_id}"},
        "state": {"status_path": "state", "done": ["finished"], "failed": ["failed"],
                  "error_path": "message", "video_url_path": "output.video_url",
                  "seconds_path": "output.duration", "size_path": "output.size"},
        "fetch": {"mode": "url"}                      // or {"mode":"path","path":"/v1/tasks/{task_id}/file"}
      }
    }

Placeholders: {model} {prompt} {size} {n} {seconds} {ratio} {resolution}
{ref_base64} {ref_mime} {ref_data_uri} {task_id}. A placeholder that is the whole
string keeps its native JSON type (so `{"n": "{n}"}` sends a number).
"""

from __future__ import annotations

import base64
import json
import mimetypes
import urllib.parse

from . import ImageResult, MediaError, Protocol, VideoState, guess_suffix


class CustomProtocol(Protocol):
    name = "custom"
    supports = ("image", "video")

    def __init__(self, endpoint, spec: dict | None = None):
        super().__init__(endpoint)
        self.spec = spec or {}
        auth = self.spec.get("auth") or {}
        self.auth_mode = str(auth.get("mode", "bearer"))
        self.auth_name = str(auth.get("name") or ("Authorization" if self.auth_mode == "header" else "token"))
        self.auth_prefix = str(auth.get("prefix", "Bearer "))

    # ------------------------------------------------------------------ auth

    def _request(self, method, url, body=None, headers=None, auth=True):  # type: ignore[override]
        if auth and self.endpoint.key:
            headers = dict(headers or {})
            if self.auth_mode == "query":
                separator = "&" if "?" in url else "?"
                url = url + separator + urllib.parse.urlencode({self.auth_name: self.endpoint.key})
            elif self.auth_mode == "header":
                headers[self.auth_name] = f"{self.auth_prefix}{self.endpoint.key}"
            else:
                headers["Authorization"] = f"Bearer {self.endpoint.key}"
        return super()._request(method, url, body, headers, auth=False)

    # ------------------------------------------------------------ templating

    def _values(self, **kwargs) -> dict:
        values = {key: value for key, value in kwargs.items() if value is not None}
        ref = values.pop("ref", None)
        if ref:
            mime, _ = mimetypes.guess_type(ref)
            mime = mime or "image/png"
            with open(ref, "rb") as handle:
                encoded = base64.b64encode(handle.read()).decode("ascii")
            values.update(
                {"ref_base64": encoded, "ref_mime": mime, "ref_data_uri": f"data:{mime};base64,{encoded}"}
            )
        return values

    def _render(self, template, values: dict):
        if isinstance(template, dict):
            return {key: self._render(value, values) for key, value in template.items()}
        if isinstance(template, list):
            return [self._render(item, values) for item in template]
        if not isinstance(template, str):
            return template
        if template.startswith("{") and template.endswith("}") and template.count("{") == 1:
            key = template[1:-1]
            return values.get(key, template)
        rendered = template
        for key, value in values.items():
            rendered = rendered.replace("{" + key + "}", str(value))
        return rendered

    def _path(self, template, values: dict) -> str:
        rendered = str(self._render(template, values))
        if rendered.startswith(("http://", "https://")):
            return rendered
        return self.endpoint.base_url + (rendered if rendered.startswith("/") else "/" + rendered)

    # ------------------------------------------------------------------ image

    def image(self, model: str, prompt: str, *, size: str | None, n: int, ref: str | None) -> ImageResult:
        config = self.spec.get("image")
        if not isinstance(config, dict):
            raise MediaError("该 custom 配置没有 image 段")
        values = self._values(model=model, prompt=prompt, size=size, n=n, ref=ref)
        method = str(config.get("method", "POST")).upper()
        url = self._path(config.get("path", "/"), values)
        body = self._render(config.get("body"), values)
        status, payload, raw = self._request(method, url, body if isinstance(body, dict) else None)
        if status >= 400:
            raise MediaError(f"{method} {url} → {status}：{_err(payload, raw)}")
        response = config.get("response") or {}
        mode = str(response.get("mode", "b64"))
        path = response.get("path")
        if mode == "b64":
            data = _dig(payload, path) if path else payload.get("b64")
            if not isinstance(data, str) or not data:
                raise MediaError(f"custom image: 在 {path or 'b64'} 找不到 base64 数据")
            return ImageResult(data=base64.b64decode(data), suffix=".png")
        if mode == "url":
            data = _dig(payload, path) if path else payload.get("url")
            if not isinstance(data, str) or not data:
                raise MediaError(f"custom image: 在 {path or 'url'} 找不到图片地址")
            return ImageResult(data=b"", suffix=guess_suffix(data), url=data)
        raise MediaError(f"custom image.response.mode={mode} 不受支持（b64 / url）")

    # ------------------------------------------------------------------ video

    def video_create(self, model, prompt, *, seconds, size, resolution, ratio, ref):
        create = self.spec.get("video", {}).get("create")
        if not isinstance(create, dict):
            raise MediaError("该 custom 配置没有 video.create 段")
        values = self._values(
            model=model, prompt=prompt, size=size, n=None, seconds=seconds,
            ratio=ratio, resolution=resolution, ref=ref,
        )
        method = str(create.get("method", "POST")).upper()
        url = self._path(create.get("path", "/"), values)
        body = self._render(create.get("body"), values)
        status, payload, raw = self._request(method, url, body if isinstance(body, dict) else None)
        if status >= 400:
            raise MediaError(f"{method} {url} → {status}：{_err(payload, raw)}")
        path = self.spec.get("video", {}).get("task_id_path", "id")
        task_id = _dig(payload, path)
        if not task_id:
            raise MediaError(f"custom video: 在 {path} 找不到任务 id")
        return str(task_id)

    def video_status(self, task_id: str) -> VideoState:
        video = self.spec.get("video") or {}
        status_config = video.get("status") or {"path": "/tasks/{task_id}"}
        state_config = video.get("state") or {}
        values = {"task_id": task_id}
        url = self._path(status_config.get("path", "/tasks/{task_id}"), values)
        method = str(status_config.get("method", "GET")).upper()
        status, payload, raw = self._request(method, url)
        if status >= 400:
            raise MediaError(f"{method} {url} → {status}：{_err(payload, raw)}")
        raw_status = str(_dig(payload, state_config.get("status_path", "status")) or "unknown")
        done = {str(v) for v in state_config.get("done", ["completed", "succeeded", "success"])}
        failed = {str(v) for v in state_config.get("failed", ["failed", "error", "cancelled"])}
        if raw_status in done:
            normalised = "completed"
        elif raw_status in failed:
            normalised = "failed"
        elif raw_status.lower() in ("queued", "pending", "waiting"):
            normalised = "queued"
        else:
            normalised = "processing"
        error_path = state_config.get("error_path")
        return VideoState(
            status=normalised,
            task_id=task_id,
            url=_dig(payload, state_config.get("video_url_path", "output.video_url"))
            if normalised == "completed"
            else None,
            error=str(_dig(payload, error_path)) if normalised == "failed" and error_path else None,
            seconds=_as_text(_dig(payload, state_config.get("seconds_path"))),
            size=_as_text(_dig(payload, state_config.get("size_path"))),
            extra={"raw_status": raw_status},
        )

    def video_fetch(self, task_id: str, state: VideoState) -> bytes:
        fetch_config = (self.spec.get("video") or {}).get("fetch") or {"mode": "url"}
        mode = str(fetch_config.get("mode", "url"))
        if mode == "url":
            if not state.url:
                raise MediaError(f"custom video: 任务 {task_id} 没有可用 URL")
            return self.fetch(state.url)
        if mode == "path":
            url = self._path(fetch_config.get("path", "/tasks/{task_id}/content"), {"task_id": task_id})
            status, _, raw = self._request("GET", url)
            if status >= 400:
                raise MediaError(f"GET {url} → {status}")
            return raw
        raise MediaError(f"custom video.fetch.mode={mode} 不受支持（url / path）")


def _dig(payload, path):
    if not path:
        return None
    current = payload
    for part in str(path).split("."):
        if isinstance(current, list):
            if not part.isdigit():
                return None
            index = int(part)
            if index >= len(current):
                return None
            current = current[index]
        elif isinstance(current, dict):
            current = current.get(part)
        else:
            return None
        if current is None:
            return None
    return current


def _as_text(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _err(payload, raw: bytes) -> str:
    if isinstance(payload, dict):
        for key in ("error", "message", "msg", "detail"):
            value = payload.get(key)
            if isinstance(value, dict):
                value = value.get("message") or value.get("msg")
            if value:
                return str(value)
    text = raw.decode("utf-8", "replace").strip()
    return text[:300] if text else "（响应无正文）"
