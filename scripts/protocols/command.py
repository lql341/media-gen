"""Command protocol: wrap any in-house API in a script.

For endpoints whose protocol is genuinely exotic (signed forms, gRPC gateways,
multi-step auth), declarative templates run out. A profile can instead point at
commands that exchange JSON on stdin/stdout:

    ~/.config/media-gen/config.json
    {"profiles": {"inhouse": {
        "protocol": "command",
        "base_url": "unused://inhouse",
        "command": {
          "image":  "~/bin/inhouse image",
          "create": "~/bin/inhouse create",
          "status": "~/bin/inhouse status",
          "fetch":  "~/bin/inhouse fetch"
        }}}}

Contracts (stdin JSON → stdout JSON, non-zero exit = failure with stderr text):

    image   {model, prompt, size?, n, ref?}     → {"b64": "…"}  or  {"url": "https://…"}
    create  {model, prompt, seconds?, size?, ratio?, resolution?, ref?} → {"task_id": "…"}
    status  {task_id}                            → {"status", "url"?, "error"?, "seconds"?, "size"?}
    fetch   {task_id, url?}                      → raw bytes (video/mp4) on stdout

This keeps the skill generic: a new vendor can be supported without touching this
repository, and without putting a key in the command line.
"""

from __future__ import annotations

import base64
import json
import shlex
import subprocess

from . import ImageResult, MediaError, Protocol, VideoState, guess_suffix


class CommandProtocol(Protocol):
    name = "command"
    supports = ("image", "video")

    def __init__(self, endpoint, spec: dict | None = None):
        super().__init__(endpoint)
        self.spec = spec or {}

    # ------------------------------------------------------------------ utils

    def _commands(self) -> dict:
        commands = self.spec.get("command")
        if not isinstance(commands, dict):
            raise MediaError("command 协议需要在配置档里提供 command: {image|create|status|fetch}")
        return commands

    def _run(self, action: str, payload: dict) -> bytes:
        commands = self._commands()
        if action not in commands:
            raise MediaError(f"配置档没有 command.{action}；{action} 这一步无法执行")
        argv = shlex.split(str(commands[action]))
        if not argv:
            raise MediaError(f"command.{action} 为空")
        env = {
            "MEDIA_BASE_URL": self.endpoint.base_url,
            "MEDIA_PROFILE_KEY": self.endpoint.key,
            "PATH": "/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
            "HOME": __import__("os").environ.get("HOME", ""),
        }
        try:
            completed = subprocess.run(
                argv,
                input=json.dumps(payload).encode("utf-8"),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=self.endpoint.timeout,
                env=env,
                check=False,
            )
        except FileNotFoundError:
            raise MediaError(f"找不到命令：{argv[0]}") from None
        except subprocess.TimeoutExpired:
            raise MediaError(f"命令超时（{self.endpoint.timeout}s）：{argv[0]}") from None
        if completed.returncode != 0:
            detail = completed.stderr.decode("utf-8", "replace").strip() or "（无错误输出）"
            raise MediaError(f"command.{action} 失败（exit={completed.returncode}）：{detail[:300]}")
        return completed.stdout

    def _json(self, action: str, payload: dict) -> dict:
        raw = self._run(action, payload)
        try:
            parsed = json.loads(raw or b"{}")
        except ValueError:
            raise MediaError(f"command.{action} 的输出不是 JSON：{raw[:200]!r}") from None
        if not isinstance(parsed, dict):
            raise MediaError(f"command.{action} 的输出必须是 JSON 对象")
        if parsed.get("error"):
            raise MediaError(f"command.{action} 报错：{parsed['error']}")
        return parsed

    # ---------------------------------------------------------------- actions

    def image(
        self, model: str, prompt: str, *, size: str | None, n: int, ref: str | None, mask: str | None = None
    ) -> list[ImageResult]:
        payload = {"model": model, "prompt": prompt, "n": n}
        if size:
            payload["size"] = size
        if ref:
            payload["ref"] = ref
        if mask:
            payload["mask"] = mask
        result = self._json("image", payload)
        # 单张：{b64} / {url}；多张：{images:[{b64|url}, …]}
        entries = result.get("images")
        entries = entries if isinstance(entries, list) and entries else [result]
        images: list[ImageResult] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            encoded = entry.get("b64") or entry.get("b64_json")
            if encoded:
                try:
                    images.append(ImageResult(data=base64.b64decode(encoded), suffix=".png"))
                except (ValueError, TypeError):
                    raise MediaError("command.image 返回的 b64 不是合法 base64") from None
                continue
            url = entry.get("url")
            if url:
                images.append(ImageResult(data=b"", suffix=guess_suffix(str(url)), url=str(url)))
        if not images:
            raise MediaError("command.image 需要返回 {b64}/{url}，或 {images:[{b64|url}, …]}")
        return images

    def video_create(self, model, prompt, *, seconds, size, resolution, ratio, ref):
        payload = {"model": model, "prompt": prompt}
        for key, value in (
            ("seconds", seconds), ("size", size), ("ratio", ratio), ("resolution", resolution), ("ref", ref),
        ):
            if value is not None:
                payload[key] = value
        result = self._json("create", payload)
        task_id = result.get("task_id") or result.get("id")
        if not task_id:
            raise MediaError("command.create 需要返回 {task_id}")
        return str(task_id)

    def speech(self, model: str, text: str, *, voice: str | None, fmt: str | None) -> tuple[bytes, str]:
        payload = {"model": model, "input": text}
        if voice:
            payload["voice"] = voice
        if fmt:
            payload["format"] = fmt
        raw = self._run("speech", payload)
        if not raw:
            raise MediaError("command.speech 没有输出音频字节")
        return raw, "." + (fmt or "mp3").lstrip(".")

    def transcribe(self, model: str, path: str, *, language: str | None) -> str:
        payload = {"model": model, "file": path}
        if language:
            payload["language"] = language
        result = self._json("transcribe", payload)
        text = result.get("text")
        if not text:
            raise MediaError("command.transcribe 需要返回 {text}")
        return str(text)

    def video_status(self, task_id: str) -> VideoState:
        result = self._json("status", {"task_id": task_id})
        return VideoState(
            status=str(result.get("status", "unknown")),
            task_id=task_id,
            url=result.get("url"),
            error=result.get("error"),
            seconds=str(result["seconds"]) if result.get("seconds") is not None else None,
            size=str(result["size"]) if result.get("size") is not None else None,
            extra={},
        )

    def video_fetch(self, task_id: str, state: VideoState) -> bytes:
        raw = self._run("fetch", {"task_id": task_id, "url": state.url})
        if not raw:
            if state.url:
                return self.fetch(state.url)
            raise MediaError(f"command.fetch 没有输出，且任务 {task_id} 没有 URL")
        return raw
