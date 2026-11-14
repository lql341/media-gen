# Graphical clients (WorkBuddy, DSH Desktop, Claude Desktop, CodeBuddy)

Graphical clients cannot install an Agent Skill, and `media-gen` is **not a chat model** — it cannot
be added to their model picker. The supported path is **MCP**: the repository ships
`scripts/mcp_server.py`, a dependency-free stdio server, and every client that speaks MCP can attach
it and then ask for images/videos in normal chat.

## Why not a model entry

These clients configure chat models (`models.json`, provider tables). `media-gen` drives *other*
endpoints' image/video routes; there is no chat deployment behind it. Adding it as a model would only
produce connection errors.

## One server, five tools

| Tool | Purpose |
| --- | --- |
| `media_profiles` | which endpoints are configured (no secrets) |
| `media_models` | what the endpoint can generate, with constraints |
| `media_image` | text→image, returns the saved file path |
| `media_video` | text/image→video: create, poll, download |
| `media_task` | `status` / `wait` / `download` for an existing task |

The server uses the same profiles, registry and credential resolution as the CLI, so configuring
once with `setup.sh` covers every client. Set `MEDIA_PROFILE` in the server's environment (or pass
`profile` per call).

## Register it

Use **absolute** paths; substitute your interpreter (`/usr/bin/python3`, `python`, `py -3`, a venv).

pi (`~/.pi/agent/mcp.json`):

```json
{"mcpServers": {"media-gen": {
  "command": "/usr/bin/python3",
  "args": ["/abs/path/to/media-gen/scripts/mcp_server.py"],
  "env": {"MEDIA_PROFILE": "litellm"}
}}}
```

Claude Desktop / WorkBuddy / DSH Desktop (same JSON shape, their own config file):

```json
{"mcpServers": {"media-gen": {"command": "/usr/bin/python3",
  "args": ["/abs/path/to/media-gen/scripts/mcp_server.py"],
  "env": {"MEDIA_PROFILE": "litellm"}}}}
```

CodeBuddy:

```bash
codebuddy mcp add media-gen -s user -- /usr/bin/python3 /abs/path/to/media-gen/scripts/mcp_server.py
```

Windows PowerShell (paths in quotes, backslashes):

```powershell
.\scripts\setup.ps1 mcp     # prints a ready-to-paste snippet with this machine's paths
```

## What the client sees

- Tool list with an `instructions` string telling the model to check `media_models` first, confirm
  duration/resolution before spending, and prefer `dry_run` for planning.
- Tool results are JSON: `{"ok": true, "result": "<path>", "log": "…"}`; failures return
  `isError: true` with the same shape, so the chat shows a real error instead of a silent failure.
- Progress: `media_video` blocks until the clip is downloaded (minutes). Clients with long tool
  timeouts are fine; if a client times out, use `create_only: true` to get the task id, then
  `media_task {action: "wait"}`.

## Practical guardrails

- Spend discipline lives in the tool descriptions and in `SKILL.md`; a GUI client has no skill, so the
  server's `instructions` field carries the short version.
- Keep the key out of the client config: let the server resolve it from the OS credential store or
  `MEDIA_*` env vars. Never paste a key into a screenshot-friendly config UI.
- On Windows without a keyring, either set `MEDIA_API_KEY` in the MCP server's `env` block (visible in
  the client config — acceptable for a personal machine) or use `MEDIA_CREDENTIAL_STORE=file`.
