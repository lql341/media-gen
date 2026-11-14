---
name: seedance
description: Generate, poll, and download short videos with Seedance video models (doubao-seedance-2-5, doubao-seedance-2-0-260128) through a LiteLLM gateway's Videos route. Use for text-to-video, image-to-video, task status, or downloading a finished clip. These are video-only deployments, not chat models.
license: MIT
compatibility: Requires curl and python3 on macOS or Linux. Needs a gateway base URL and an API key, configured once with scripts/setup.sh.
---

# Seedance video generation

Seedance models are **video-only deployments** behind a LiteLLM gateway. They appear in
`GET /models` but `/chat/completions` and `/responses` answer
`429 No deployments available for selected model`. Never select them with `/model`, never add them
to `models.json` (Pi, CodeBuddy, or any client), and never retry a 429: it means a video model was
routed at a chat endpoint.

The only entry point is this skill's scripts, which speak the gateway's Videos route:
`POST /videos` → `GET /videos/<id>` → `GET /videos/<id>/content`.

## First use and configuration

- On first use, check whether configuration already exists: `scripts/setup.sh status`. If the key
  is missing, read `references/first-use.md` and explain what is needed, where to obtain it, and
  the exact local command — in the user's language.
- Never ask for an API key, never accept a key pasted into chat, and never echo one. Give the user
  the command to run in their own terminal; the prompt is hidden there. Read `references/setup.md`
  for credential-store details.
- The skill resolves configuration in this order: `SEEDANCE_API_KEY` / `LEGACY_API_KEY` →
  OS credential store (macOS Keychain, `secret-tool`) → `~/.config/seedance/config.json` (0600) →
  read-only import from `~/.pi/agent/auth.json` or `~/.codebuddy/models.json`.
- `scripts/setup.sh new|modify|status|doctor|reset` is the configuration lifecycle.
  `scripts/setup.sh doctor` is read-only: it checks `GET /models` and whether both video models are
  present. Reuse working configuration without re-entry.

## Money and time

- Every generation is billed as video tokens; the rate depends on the provider's price list, the
  duration, and the resolution. A 480p draft costs a fraction of a 720p/1080p render, and duration
  scales roughly linearly. Wall clock is minutes, not seconds (queueing plus generation).
- Confirm duration and resolution before spending unless the user already stated both. Use
  `gen --dry-run` to show the request without creating a task.
- Prefer one shot: `run` creates, polls, and downloads in a single call. Use `gen` + `wait` only
  when the user wants a task id to keep, resume later, or fan out several clips.

## Commands

Run scripts relative to this skill directory:

| Goal | Command |
|---|---|
| Configure gateway URL + key | `scripts/setup.sh new` |
| Show effective URL/key source (masked) | `scripts/setup.sh status` |
| Read-only connectivity check | `scripts/setup.sh doctor` |
| End to end: create → poll → download | `scripts/seedance.sh run -p "<prompt>" [opts] -o out.mp4` |
| Create a task only | `scripts/seedance.sh gen -p "<prompt>" [opts]` (stdout = `video_...`) |
| Inspect a task | `scripts/seedance.sh status <id>` |
| Wait for completion | `scripts/seedance.sh wait <id> [--timeout 1800]` |
| Download a finished clip | `scripts/seedance.sh download <id> out.mp4` |
| Show the request, spend nothing | `scripts/seedance.sh gen -p "<prompt>" [opts] --dry-run` |

Options: `--model`, `--seconds` (`4..30`, or `-1` = model picks), `--size 1280x720`,
`--ratio 16:9|9:16|1:1`, `--resolution 480p|720p|1080p`, `--image <first-frame.jpg>`
(image-to-video via multipart `input_reference`).

## Reporting results

- Report the downloaded file path first; `result.url` is a signed object-storage link that expires
  (24 h on the reference gateway), so it is not a deliverable on its own.
- Include duration, pixel size, and the token usage the gateway returns in the summary.
- Keep provider internals, signed URLs, and keys out of committed files and public reports.

## Failure playbook

| Symptom | Meaning | Action |
|---|---|---|
| `429 No deployments available` | video model called as chat | stop; use these scripts |
| `400 seconds must be an integer` | non-numeric duration | integer `4..30` or `-1` |
| `400 duration must be an integer in 4..30 or -1` | out-of-range duration | clamp it |
| `400 Unsupported Volcengine video size` | `WxH` not in the model's list | use `--ratio` + `--resolution` |
| `400 Resolution 'x' is not supported` | bad `--resolution` | `480p` / `720p` / `1080p` |
| `409` on download | clip still rendering | `wait <id>` first |
| `307` then an empty file | redirect not followed | the script passes `-L`; do not hand-roll curl |

Read `references/routing.md` for the route shape and measured payloads,
`references/troubleshooting.md` for the full table.

## Stable entrypoints

- `scripts/setup.sh`: configuration panel (`new`, `modify`, `status`, `doctor`, `reset`).
- `scripts/seedance_config.py`: `status`, `doctor`, `set`, `import`, `reset`; also the internal
  `get-key` / `get-base-url` / `get-model` used by the CLI.
- `scripts/seedance.sh`: `gen`, `status`, `wait`, `download`, `run`.
- `scripts/install.sh`: link or copy this skill into `~/.agents/skills`, `~/.claude/skills`, or
  `~/.codex/skills`.
