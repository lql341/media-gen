#!/usr/bin/env python3
"""media-gen MCP server (stdio, newline-delimited JSON-RPC).

Graphical clients that cannot install an Agent Skill — WorkBuddy, DSH Desktop,
Claude Desktop, CodeBuddy — can still drive media generation by attaching this
server. It exposes the same registry/profile/credential machinery as the CLI:

    media_profiles   list configured endpoints (no secrets)
    media_models     what this endpoint can generate (image/video/speech/transcription + constraints)
    media_image      text→image, returns the saved file path
    media_video      text/image→video: create, poll, download (also remix / extend)
    media_task       status | wait | download for an existing task
    media_speech     text→audio (/audio/speech), returns the saved file path
    media_transcribe audio→text (/audio/transcriptions), returns the transcript

Register it (paths must be absolute):

    {"mcpServers": {"media-gen": {"command": "/usr/bin/python3",
                                  "args": ["/abs/path/scripts/mcp_server.py"],
                                  "env": {"MEDIA_PROFILE": "litellm"}}}}

No third-party dependencies; the server never prints keys.
"""

from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import api  # noqa: E402
import media_config as config  # noqa: E402
from protocols import MediaError  # noqa: E402

def read_version() -> str:
    """版本只以仓库根目录的 VERSION 为准，避免这里写死的常量再次过期。"""
    try:
        with open(os.path.join(os.path.dirname(HERE), "VERSION"), encoding="utf-8") as handle:
            return handle.read().strip() or "unknown"
    except OSError:
        return "unknown"


SERVER_INFO = {"name": "media-gen", "version": read_version()}
PROTOCOL_VERSION = "2024-11-05"


def _envelope(ok: bool, result=None, error: str | None = None, log: list[str] | None = None) -> dict:
    payload: dict = {"ok": ok}
    if result is not None:
        payload["result"] = result
    if error is not None:
        payload["error"] = error
    if log:
        payload["log"] = "\n".join(log).strip()
    return payload


def _profile(arguments: dict) -> str | None:
    return arguments.get("profile") or os.environ.get("MEDIA_PROFILE") or None


def _params(arguments: dict) -> list:
    return list(arguments.get("param") or [])


# ------------------------------------------------------------------ MCP tools

TOOLS = [
    {
        "name": "media_profiles",
        "description": "List configured media endpoints (profiles): name, protocol, base URL, default models. Secrets are never returned.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "media_models",
        "description": "List what the selected endpoint can generate: model id, kind (image/video) and constraints (duration, size syntax). Pass kind to filter.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["image", "video", "speech", "transcription"]},
                "profile": {"type": "string"},
            },
        },
    },
    {
        "name": "media_image",
        "description": "Generate an image from a prompt and save it locally. Returns the file path. Costs money on most endpoints.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string"},
                "model": {"type": "string"},
                "size": {"type": "string", "description": "e.g. 1024x1024"},
                "n": {"type": "integer", "minimum": 1},
                "image": {"type": "string", "description": "reference image for /images/edits"},
                "mask": {"type": "string", "description": "mask image (only /images/edits)"},
                "out": {"type": "string", "description": "output file path"},
                "profile": {"type": "string"},
                "dry_run": {"type": "boolean", "description": "show the request only, spend nothing"},
                "param": {"type": "array", "items": {"type": "string"},
                          "description": "provider-specific parameters as key=value, e.g. watermark=false"},
            },
            "required": ["prompt"],
        },
    },
    {
        "name": "media_video",
        "description": "Generate a video (text-to-video or image-to-video): creates the task, polls until done and downloads the file. Returns the path. Slow and billed per token.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string"},
                "model": {"type": "string"},
                "seconds": {"type": "integer", "description": "duration; -1 lets the model choose"},
                "size": {"type": "string"},
                "ratio": {"type": "string", "description": "e.g. 16:9"},
                "resolution": {"type": "string", "description": "e.g. 720p / 1080P"},
                "image": {"type": "string", "description": "local first-frame image path"},
                "out": {"type": "string"},
                "profile": {"type": "string"},
                "create_only": {"type": "boolean", "description": "return the task id instead of waiting"},
                "remix": {"type": "string", "description": "task id to remix (POST /videos/<id>/remix)"},
                "extend": {"type": "string", "description": "task id to extend (POST /videos/extensions)"},
                "last_frame": {"type": "string", "description": "also save the last frame image here"},
                "dry_run": {"type": "boolean"},
                "param": {"type": "array", "items": {"type": "string"},
                          "description": "provider-specific parameters as key=value"},
            },
            "required": ["prompt"],
        },
    },
    {
        "name": "media_task",
        "description": "Inspect (status), wait for, or download an existing video task.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["status", "wait", "download"]},
                "task_id": {"type": "string"},
                "out": {"type": "string"},
                "last_frame": {"type": "string", "description": "download: also save the last frame here"},
                "profile": {"type": "string"},
                "interval": {"type": "integer"},
                "timeout": {"type": "integer"},
            },
            "required": ["action", "task_id"],
        },
    },
    {
        "name": "media_speech",
        "description": "Text to speech (/audio/speech): returns the saved audio file path. Needs an endpoint with a speech deployment.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "model": {"type": "string"},
                "voice": {"type": "string"},
                "format": {"type": "string", "description": "mp3 / wav / opus …"},
                "out": {"type": "string"},
                "profile": {"type": "string"},
                "dry_run": {"type": "boolean"},
            },
            "required": ["text"],
        },
    },
    {
        "name": "media_transcribe",
        "description": "Speech to text (/audio/transcriptions): returns the transcript. Needs a transcription deployment.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file": {"type": "string", "description": "local audio file path"},
                "model": {"type": "string"},
                "language": {"type": "string", "description": "e.g. zh"},
                "out": {"type": "string", "description": "write the transcript to this file (default: return it)"},
                "profile": {"type": "string"},
                "dry_run": {"type": "boolean"},
            },
            "required": ["file"],
        },
    },
]


def call_tool(name: str, arguments: dict) -> dict:
    """All tools go through ``api`` — the same code path as the CLI."""
    log: list[str] = []
    profile = _profile(arguments)
    try:
        if name == "media_profiles":
            return _envelope(True, api.profiles())

        if name == "media_models":
            outcome = api.models(profile, kind=arguments.get("kind"), log=log.append)
            return _envelope(True, {"profile": outcome["profile"],
                                    "models": outcome["models"],
                                    "note": outcome["note"]}, log=log)

        if name == "media_image":
            outcome = api.image(
                profile,
                model=arguments.get("model"),
                prompt=arguments.get("prompt"),
                size=arguments.get("size"),
                n=int(arguments.get("n") or 1),
                ref=arguments.get("image"),
                mask=arguments.get("mask"),
                params=api.parse_params(_params(arguments)),
                out=arguments.get("out"),
                log=log.append,
            )
            files = outcome["files"]
            return _envelope(True, files if len(files) > 1 else files[0], log=log)

        if name == "media_video":
            outcome = api.video(
                profile,
                model=arguments.get("model"),
                prompt=arguments.get("prompt"),
                seconds=arguments.get("seconds"),
                size=arguments.get("size"),
                ratio=arguments.get("ratio"),
                resolution=arguments.get("resolution"),
                ref=arguments.get("image"),
                params=api.parse_params(_params(arguments)),
                out=arguments.get("out"),
                create_only=bool(arguments.get("create_only")),
                remix=arguments.get("remix") or None,
                extend=arguments.get("extend") or None,
                last_frame=arguments.get("last_frame") or None,
                interval=int(arguments.get("interval") or api.DEFAULT_INTERVAL),
                timeout=int(arguments.get("timeout") or api.DEFAULT_TIMEOUT),
                log=log.append,
            )
            if outcome.get("create_only"):
                return _envelope(True, outcome["task_id"], log=log)
            return _envelope(True, outcome["file"], log=log)

        if name == "media_speech":
            outcome = api.speech(
                profile,
                model=arguments.get("model"),
                text=arguments.get("text"),
                voice=arguments.get("voice"),
                fmt=arguments.get("format"),
                out=arguments.get("out"),
                log=log.append,
            )
            return _envelope(True, outcome["file"], log=log)

        if name == "media_transcribe":
            outcome = api.transcribe(
                profile,
                model=arguments.get("model"),
                file=arguments.get("file"),
                language=arguments.get("language"),
                out=arguments.get("out"),
                log=log.append,
            )
            return _envelope(True, outcome["file"] or outcome["text"], log=log)

        if name == "media_task":
            action = arguments.get("action")
            task_id = arguments.get("task_id")
            if action == "status":
                return _envelope(True, api.status(profile, task_id), log=log)
            if action == "wait":
                outcome = api.wait(
                    profile, [task_id],
                    timeout=int(arguments.get("timeout") or api.DEFAULT_TIMEOUT),
                    interval=int(arguments.get("interval") or api.DEFAULT_INTERVAL),
                    log=log.append,
                )
                payload = outcome["results"][0] if outcome["results"] else None
                if outcome["failed"]:
                    return _envelope(False, payload, f"任务 {task_id} 未完成", log)
                return _envelope(True, payload, log=log)
            if action == "download":
                outcome = api.download(profile, task_id, out=arguments.get("out"),
                                       last_frame=arguments.get("last_frame") or None,
                                       log=log.append)
                return _envelope(True, outcome["file"], log=log)
            return _envelope(False, error=f"未知 action：{action}")

        return _envelope(False, error=f"未知工具：{name}")

    except (api.UsageError, config.ConfigError, MediaError) as error:
        return _envelope(False, error=str(error), log=log)


# ------------------------------------------------------------------- JSON-RPC


def respond(message_id, result=None, error=None) -> dict:
    payload: dict = {"jsonrpc": "2.0", "id": message_id}
    if error is not None:
        payload["error"] = error
    else:
        payload["result"] = result
    return payload


def handle(request: dict) -> dict | None:
    method = request.get("method")
    request_id = request.get("id")
    if method == "initialize":
        return respond(
            request_id,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": SERVER_INFO,
                "instructions": (
                    "Image/video generation through the user's configured endpoints. "
                    "Call media_models first, confirm duration/resolution before spending, "
                    "and prefer dry_run for planning."
                ),
            },
        )
    if method in ("notifications/initialized", "initialized"):
        return None
    if method == "ping":
        return respond(request_id, {})
    if method == "tools/list":
        return respond(request_id, {"tools": TOOLS})
    if method == "tools/call":
        params = request.get("params") or {}
        name = params.get("name")
        arguments = params.get("arguments") or {}
        try:
            outcome = call_tool(str(name), arguments)
        except Exception as error:  # noqa: BLE001 - never kill the server on one call
            outcome = {"ok": False, "error": f"{type(error).__name__}: {error}"}
        text = json.dumps(outcome, ensure_ascii=False, indent=2)
        return respond(
            request_id,
            {"content": [{"type": "text", "text": text}], "isError": not outcome.get("ok", False)},
        )
    return respond(request_id, error={"code": -32601, "message": f"method not found: {method}"})


def serve() -> int:
    config.ensure_utf8_stdio()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except ValueError:
            print(json.dumps(respond(None, error={"code": -32700, "message": "parse error"})), flush=True)
            continue
        reply = handle(request) if isinstance(request, dict) else None
        if reply is not None:
            print(json.dumps(reply, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(serve())
    except KeyboardInterrupt:
        sys.exit(0)
