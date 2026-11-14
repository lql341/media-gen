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
`minimax` (Hailuo video, image-01). The same model can be reached through a gateway or its
native API — the profile decides.

Never conclude that a model "does not exist" because one endpoint lacks it: ask the endpoint
(`models`) and remember that the gateway operator controls what is mounted and allowed.

## First use

- `scripts/setup.sh status` and `scripts/setup.sh list` first — configuration may already exist.
- Missing configuration → read `references/first-use.md`, then have the user run, in **their own
  terminal**: `scripts/setup.sh add <name> --protocol <p> --base-url <url>`.
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
| Configure / inspect / verify | `setup.sh add|use|list|status|doctor|rm|migrate` |
| What can this endpoint do? | `media.py models [--kind image|video] [--json]` |
| Text to image | `media.py image -p "<prompt>" --model M [--size 1024x1024] [-n N] [-o out.png]` |
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

Full detail: `references/troubleshooting.md`; per-provider quirks: `references/providers.md`.

## Boundaries

- Generating costs money and takes minutes. Never fan out paid requests without the user's intent.
- Keep keys, signed URLs and endpoint internals out of committed files and public reports.
- Image-to-video needs a reference image the protocol accepts: Ark and MiniMax take local files
  (base64), DashScope needs a public URL. The CLI refuses locally with a hint instead of failing
  server-side.
