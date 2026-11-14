#!/usr/bin/env python3
"""media-gen MCP server (stdio, newline-delimited JSON-RPC).

Graphical clients that cannot install an Agent Skill — WorkBuddy, DSH Desktop,
Claude Desktop, CodeBuddy — can still drive media generation by attaching this
server. It exposes the same registry/profile/credential machinery as the CLI:

    media_profiles   list configured endpoints (no secrets)
    media_models     what this endpoint can generate (image/video + constraints)
    media_image      text→image, returns the saved file path
    media_video      text/image→video: create, poll, download
    media_task       status | wait | download for an existing task

Register it (paths must be absolute):

    {"mcpServers": {"media-gen": {"command": "/usr/bin/python3",
                                  "args": ["/abs/path/scripts/mcp_server.py"],
                                  "env": {"MEDIA_PROFILE": "litellm"}}}}

No third-party dependencies; the server never prints keys.
"""

from __future__ import annotations

import io
import json
import os
import sys
from contextlib import redirect_stderr, redirect_stdout
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import media as cli  # noqa: E402
import media_config as config  # noqa: E402

SERVER_INFO = {"name": "media-gen", "version": "0.4.0"}
PROTOCOL_VERSION = "2024-11-05"


def _args(**kwargs):
    base = {
        "profile": os.environ.get("MEDIA_PROFILE") or None,
        "timeout_seconds": 120,
        "verbose": False,
        "dry_run": False,
        "param": [],
        "json": False,
    }
    base.update(kwargs)
    return SimpleNamespace(**base)


def _capture(func, args) -> dict:
    """Run a CLI command, keep stdout (the result) and stderr (the log) apart."""
    out_buffer, err_buffer = io.StringIO(), io.StringIO()
    try:
        with redirect_stdout(out_buffer), redirect_stderr(err_buffer):
            func(args)
    except SystemExit as exit_error:  # die() raises this
        return {"ok": False, "error": str(exit_error) or "命令失败", "log": err_buffer.getvalue().strip()}
    stdout = out_buffer.getvalue().strip()
    result: dict[str, object] = {"ok": True, "log": err_buffer.getvalue().strip()}
    if stdout.startswith("{"):
        try:
            result["result"] = json.loads(stdout)
            return result
        except ValueError:
            pass
    result["result"] = stdout
    return result


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
                "kind": {"type": "string", "enum": ["image", "video"]},
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
                "profile": {"type": "string"},
                "interval": {"type": "integer"},
                "timeout": {"type": "integer"},
            },
            "required": ["action", "task_id"],
        },
    },
]


def call_tool(name: str, arguments: dict) -> dict:
    if name == "media_profiles":
        found = config.profiles()
        default = config.read_config().get("default")
        rows = []
        for profile_name in sorted(found):
            entry = found[profile_name]
            key, source = config.resolve_key(profile_name, entry)
            rows.append(
                {
                    "profile": profile_name,
                    "default": profile_name == default,
                    "protocol": entry.get("protocol"),
                    "base_url": entry.get("base_url"),
                    "default_models": entry.get("default_models") or {},
                    "key": config.mask(key) if key else None,
                    "key_source": source,
                }
            )
        return {"ok": True, "result": rows}

    if name == "media_models":
        args = _args(kind=arguments.get("kind"), json=True, profile=arguments.get("profile") or None)
        return _capture(cli.cmd_models, args)

    if name == "media_image":
        def _image(args):
            outcome = _capture(cli.cmd_image, args)
            if outcome.get("ok"):
                lines = [line for line in str(outcome.get("result", "")).splitlines() if line.strip()]
                outcome["result"] = lines if len(lines) > 1 else (lines[0] if lines else "")
            return outcome

        args = _args(
            prompt=arguments.get("prompt"),
            model=arguments.get("model"),
            size=arguments.get("size"),
            n=int(arguments.get("n") or 1),
            image=arguments.get("image"),
            out=arguments.get("out"),
            dry_run=bool(arguments.get("dry_run")),
            param=list(arguments.get("param") or []),
            profile=arguments.get("profile") or None,
        )
        return _image(args)

    if name == "media_video":
        args = _args(
            prompt=arguments.get("prompt"),
            model=arguments.get("model"),
            seconds=arguments.get("seconds"),
            size=arguments.get("size"),
            ratio=arguments.get("ratio"),
            resolution=arguments.get("resolution"),
            image=arguments.get("image"),
            out=arguments.get("out"),
            create_only=bool(arguments.get("create_only")),
            dry_run=bool(arguments.get("dry_run")),
            interval=int(arguments.get("interval") or cli.DEFAULT_INTERVAL),
            timeout=int(arguments.get("timeout") or cli.DEFAULT_TIMEOUT),
            param=list(arguments.get("param") or []),
            profile=arguments.get("profile") or None,
        )
        return _capture(cli.cmd_video, args)

    if name == "media_task":
        action = arguments.get("action")
        task_id = arguments.get("task_id")
        profile = arguments.get("profile") or None
        if action == "status":
            return _capture(cli.cmd_status, _args(task_id=task_id, profile=profile))
        if action == "wait":
            return _capture(
                cli.cmd_wait,
                _args(
                    task_id=task_id,
                    profile=profile,
                    interval=int(arguments.get("interval") or cli.DEFAULT_INTERVAL),
                    timeout=int(arguments.get("timeout") or cli.DEFAULT_TIMEOUT),
                ),
            )
        if action == "download":
            return _capture(cli.cmd_download, _args(task_id=task_id, out=arguments.get("out"), profile=profile))
        return {"ok": False, "error": f"未知 action：{action}"}

    return {"ok": False, "error": f"未知工具：{name}"}


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
