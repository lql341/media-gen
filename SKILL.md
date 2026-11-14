---
name: media-gen
description: Generate images and videos with any configured media endpoint (OpenAI-compatible gateways such as LiteLLM, or Volcengine Ark, Alibaba DashScope Wan, MiniMax Hailuo native APIs). Use for text-to-image, text-to-video, image-to-video, task polling, and downloading finished media. Models are discovered from a capability registry, never hard-coded to one vendor.
license: MIT
compatibility: Requires python3 3.9+ (stdlib only). Needs at least one configured endpoint with an API key, added once with scripts/setup.sh.
---

# media-gen

One skill for **image and video generation**, not one vendor and not one gateway. Two
independent decisions decide what happens:

| Decision | Decided by | Where it lives |
|---|---|---|
| **Where** to send the request (URL, credentials, wire protocol) | a named *profile* | `~/.config/media-gen/config.json` + OS credential store |
| **How** to encode the request, and whether the model is image or video | the *capability registry* | `scripts/registry.json` (+ user override) |

Protocols implemented: `openai` (OpenAI-compatible: LiteLLM proxies, most gateways),
`ark` (Volcengine native: Seedance video, Seedream image), `dashscope` (Alibaba Wan),
`minimax` (Hailuo video, image-01), plus two escape hatches for **non-official endpoints**:
`custom` (a JSON template file describing an in-house REST shape) and `command` (a hook script that
exchanges JSON on stdin/stdout). The same model can be reached through a gateway, its native API, or
a company-internal service — the profile decides, and supporting a new endpoint never requires
editing this repository.

Never conclude that a model "does not exist" because one endpoint lacks it: ask the endpoint
(`models`) and remember that the gateway operator controls what is mounted and allowed.

## First use

- `scripts/setup.sh status` and `scripts/setup.sh list` first — configuration may already exist.
- Missing configuration → read `references/first-use.md`, then have the user run, in **their own
  terminal**: `scripts/setup.sh add <name> --protocol <p> --base-url <url>`.
- Prefer reusing an existing credential-store item (`--credential-ref`) over copying a secret.
- Never ask for, accept, echo, or store an API key in chat. The key prompt is hidden; the store is
  macOS Keychain / `secret-tool`; environment variables beat everything.
- Never invent a base URL. There is no built-in default endpoint, by design.

## Workflow

1. **Discover** what is available: `media.py models` (endpoint list ∩ registry, with kind).
   On a gateway the model list is authoritative; on a native API there is usually no `/models`,
   so pass `--model` explicitly.
2. **Draft cheaply.** Confirm duration/resolution/aspect before spending, unless the user already
   stated them. `--dry-run` prints the normalized plan without sending anything.
3. **Generate.** `media.py image …` is synchronous; `media.py video …` creates a task, polls, and
   downloads in one call. `media.py run --model M …` picks image or video from the registry.
4. **Report** the local file path first, then duration/size, then usage. Remote URLs are signed and
   expire; they are not deliverables.

## Commands

| Goal | Command |
|---|---|
| Configure interactively | `setup.sh` / `setup.ps1` (wizard: add, custom template, modify, remove, MCP snippet) |
| Configure by flags | `setup.sh add <name> --protocol <p> --base-url <URL>` (adds or updates) |
| Inspect / verify | `setup.sh list|show|status|doctor` |
| Change one thing | `setup.sh modify <name>` · `set-url` · `set-key` · `set-protocol` · `rename` |
| Remove (config only) | `setup.sh rm <name>` · `rm --all` — secrets are never deleted unless `MEDIA_ALLOW_CREDENTIAL_DELETE=1` |
| Audit the store | `setup.sh audit` (read-only: which items, which exact commands, is the delete gate set) |
| Reuse an existing store item | `setup.sh add <name> --credential-ref <service>:<account>` (no copy, no write) |
| Multiple accounts, one endpoint | `setup.sh add <name> --account <alias> … --key-stdin`, then `--profile <name>@<alias>` or `MEDIA_ACCOUNT` |
| Concurrent sessions | `MEDIA_PROFILE=<name>@<alias>` per process; accounts never fall back to the default account's key |
| Move configuration | `setup.sh export` / `import <file>` (no secrets) · `migrate` (from seedance) |
| What can this endpoint do? | `media.py models [--kind image|video|speech|transcription] [--json]` |
| Text to image | `media.py image -p "<prompt>" --model M [--size 1024x1024] [-n N] [-o out.png]` (`n>1` → `out-1.png`, `out-2.png`, …) |
| Image editing | `media.py image -p "<prompt>" --model M --image ref.png [--mask m.png] [-o out.png]` |
| Speech (TTS) | `media.py speech -t "<text>" --model tts-1 [--voice alloy] [--format mp3] [-o out.mp3]` |
| Transcription (STT) | `media.py transcribe -f audio.mp3 --model whisper-1 [--language zh] [-o out.txt]` |
| Text/image to video | `media.py video -p "<prompt>" --model M [-s 6] [--ratio 16:9] [--resolution 720p] [--image first.png] [-o out.mp4]` |
| Either, auto-detected | `media.py run --model M …` |
| Task status / wait / fetch | `media.py status <id>` · `wait <id>` · `download <id> out.mp4` |
| Show the request only | add `--dry-run` |

Parameter normalisation is the point of the registry: `--size` accepts `1024x1024` for every
protocol (`1024*1024` for DashScope, `width/height` for MiniMax); `-s` maps to `seconds`
(OpenAI/LiteLLM), `duration` (Ark/DashScope/MiniMax); `--ratio` + `--resolution` cover models
whose size is expressed as aspect ratio. Model-specific limits (duration range or enum) are
validated locally before any request.

## Failures worth knowing

| Symptom | Meaning | Action |
|---|---|---|
| `team not allowed to access model` | key's team allowlist excludes it | report the listed allowed models; do not retry |
| `404` on `/videos` or `/images/generations` | endpoint lacks that route | pick another profile or protocol |
| `429 No deployments available` | video model routed at a chat endpoint | stop; use this skill's CLI |
| duration/size rejected locally (exit 2) | registry constraint | use the printed range/enum |
| task `failed` | provider error in the payload | report verbatim; never silently retry a paid request |
| `custom 模板不存在` / `模板不是合法 JSON` | profile points at a missing/broken template | re-add with `--custom-file`, or fix the file under `~/.config/media-gen/custom/` |
| `command.status 失败（exit=…）` | the hook script failed | read its stderr (shown in the message); test the hook by hand with JSON on stdin |

Full detail: `references/troubleshooting.md`; per-provider quirks: `references/providers.md`.

## Graphical clients

GUI clients (WorkBuddy, DSH Desktop, Claude Desktop) cannot install skills and cannot use this as a
chat model. Attach `scripts/mcp_server.py` as an MCP server instead — five tools
(`media_profiles`, `media_models`, `media_image`, `media_video`, `media_task`). See
`references/gui-clients.md`; the wizard's menu item 8 prints a ready-to-paste snippet.

## Boundaries

- Generating costs money and takes minutes. Never fan out paid requests without the user's intent.
- Keep keys, signed URLs and endpoint internals out of committed files and public reports.
- A `custom`/`command` profile is only as trustworthy as its template/hook: verify once with a cheap
  `--dry-run` then a minimal real run before batch use. Read `references/custom-endpoints.md`.
- Image-to-video: the `openai` protocol sends multipart `input_reference` (works on OpenAI Videos and
  LiteLLM); Ark and MiniMax take local files (base64); DashScope needs a public URL and refuses
  locally with a hint.
- Speech output is raw audio; the suffix comes from `--format` (default `.mp3`). `run` refuses speech
  and transcription models and points at `speech` / `transcribe`.
- Native vendor TTS/STT is not guessed: wrap it with a `custom` template or a `command` hook.
