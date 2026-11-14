# Verification record — macOS, real gateway (2026-11-14)

What was actually executed, and what is still simulated. Re-run any row with the command shown.
Deliberately no token/cost figures: the CLI prints the gateway's own `usage` per run.

> 想从头复验一遍：按 [`RUNBOOK.md`](RUNBOOK.md) 的顺序跑（零成本在前，全套真机验证只需 1 次付费调用）。

## Live: calls that produced (or were meant to produce) media

| # | Capability | Command | Result | Cost |
| --- | --- | --- | --- | --- |
| 1 | text → video | `media.py video -p "…" -s 4 --ratio 16:9 --resolution 480p -o out.mp4` | ✅ 854x480, 689 KB | billed |
| 2 | text → video (vertical) | `video -s 10 --ratio 9:16 --resolution 720p` | ✅ 720x1280, 8 MB | billed |
| 3 | **image → video** | `video -p … -s 4 --ratio adaptive --resolution 480p --image https://…/640x480.png` | ✅ 1.5 MB | billed |

Token/cost figures are intentionally **not** recorded here: they belong to whichever gateway the user
runs against, and a copied number goes stale. `media.py video` prints the gateway's own `usage` after
every run — that is the number to trust.
| 4 | task status | `status <completed id>` | ✅ `status=completed, seconds=10, size=720x1280` | 0 |
| 5 | wait (already done) | `wait <completed id>` | ✅ returns immediately | 0 |
| 6 | download | `download <id> out.mp4` | ✅ 10 500 791 bytes | 0 |
| 7 | last frame (absent) | `download <id> out.mp4 --last-frame last.png` | ✅ prints "该任务没有返回 last_frame_url" instead of failing | 0 |

The gateway's Seedance deployment returns `result.last_frame_url: null`, so the *positive* last-frame
path is only covered by the mock; the CLI behaviour when it is absent is verified live.

## Live: zero-cost negative paths

| # | Check | Command | Observed |
| --- | --- | --- | --- |
| 8 | duration below the model minimum | `video -p x --model doubao-seedance-2-5 -s 2` | local: `时长下限是 4s；收到 2s` (no request) |
| 9 | wrong size syntax | `image -p x --model doubao-seedream-4-0 --size big` | local: `--size 需要像素尺寸` |
| 10 | model outside the key's allowlist | `image -p x --model wan2.5-t2i-preview` | `401 team not allowed…` + a hint pointing at `models` (no task created) |
| 11 | audio model outside the allowlist | `transcribe -f a.mp3 --model whisper-1` | same 401 with the allowlist (no task created) |
| 12 | unknown task id | `status video_does_not_exist` | gateway 500 (`APIConnectionError` from its own fallback route) |
| 13 | dry-run for image / video / speech | `… --dry-run` | prints the plan, sends nothing |

## Model inventory on this gateway

`media.py models` → 4 media-relevant ids, all video:

```
doubao-seedance-2-0-260128  video  duration 4-30s/-1=auto · size:WxH∈{480p,720p,1080p}
doubao-seedance-2-5         video  …
```

No image (other than `gemini-embedding-2`), speech or transcription deployment is mounted, and the
key's team allowlist confirms it: requesting `gpt-image-1`, `wan*`, `MiniMax-Hailuo*`, `tts-1`,
`whisper-1` returns the allowlist, which contains only chat models plus the two Seedance ids.

## Live: diagnostics added in 0.10.0

| # | Check | Command | Observed |
| --- | --- | --- | --- |
| 14 | capability gaps | `media.py doctor --gaps` | lists `video` as verifiable and `image` / `speech` / `transcription` as not (no deployment) |
| 15 | key allowlist | `media.py models --access` | 53 models read from the 401 body with a single bogus POST; no task created |
| 16 | gateway task list | `media.py list --model doubao-seedance-2-5` | gateway answers `400 LLM Provider NOT provided` (its list route drops `model`); CLI explains and points at `tasks` |
| 17 | param planning | `media.py video … --param watermark=false --param seed=42 --dry-run` | plan shows `params: {watermark: false, seed: 42}` |
| 18 | GET retry | one `doctor` run during a TLS handshake timeout | retried, then succeeded on the next invocation |

## Live: two more zero-cost probes (0.10.x)

| # | Check | Command | Observed |
| --- | --- | --- | --- |
| 19 | `/images/edits` route reachable | `media.py image -p … --model gpt-image-1 --image ref.png` | `POST /images/edits → 401 team not allowed` — multipart accepted, rejected on allowlist (not a format error), no charge |
| 20 | `--param` really reaches the gateway | `media.py video … --param ratio=bogus_value` | `400 Unsupported ratio for this model` — passthrough proven without creating a task |

## Simulated (code path exercised, no vendor involved)

| Capability | How it is covered |
| --- | --- |
| image generation / editing / batch | `tests/mock_server.py` `/v1/images/generations`, `/v1/images/edits` (multipart) |
| speech / transcription | mock `/v1/audio/speech`, `/v1/audio/transcriptions` (multipart) |
| ark / dashscope / minimax protocols | mock routes for each wire shape; request bodies asserted |
| custom / command protocols | mock + a real shell hook script |
| Linux `secret-tool` store | `tests/test_platform.py` with a `secret-tool` shim on PATH |
| Windows branch | `platform.system()` faked to Windows (no keyring backend → documented error) |

## What still needs a different environment

- A gateway with image / speech / transcription deployments (their live paths).
- A native Linux box (keyring integration for real; `tests/run-all.sh` runs there unchanged).
- A Windows machine (`setup.ps1`, `%USERPROFILE%`, no-keyring fallback).
- Vendor-native `ark` / `dashscope` / `minimax` endpoints (all mock so far).


# Verification matrix (tick these when the environment allows)

`L` = live against a real gateway · `M` = mock/unit only · `–` = not implemented

| Capability | Code | Verified | Blocked by |
| --- | --- | --- | --- |
| text → video | L | ✅ 2 runs | — |
| image → video (public URL, `ratio=adaptive`) | L | ✅ 1 run | — |
| status / wait / wait (parallel) | L | ✅ | — |
| download + `--last-frame` (absent branch) | L | ✅ | — |
| `doctor`, `doctor --gaps`, `models`, `models --access` | L | ✅ | — |
| `list` (gateway task list) | L | ✅ (gateway defect found) | gateway drops `model` |
| `--param` passthrough | L | ✅ rejected-value probe | — |
| local validation (duration / size) | L | ✅ | — |
| GET retry | L | ✅ (transient TLS timeout) | — |
| local ledger (`tasks`) | L | ✅ | — |
| image generation (`/images/generations`) | M | ⬜ | no image deployment on this key |
| image editing (`/images/edits`) | M | ⬜ (route reachability proven, 401) | same |
| batch images (`-n N`) | M | ⬜ | same |
| speech (`/audio/speech`) | M | ⬜ (401 allowlist) | no speech deployment |
| transcription (`/audio/transcriptions`) | M | ⬜ (401 allowlist) | no transcription deployment |
| remix / extend | M | ⬜ | would create a billable task |
| `--create-only` | M | ⬜ | creates a billable task |
| `--json` (image / video / list) | M | ⬜ | needs a successful call |
| profile `--header` / `--query` | M | ⬜ | needs an endpoint that echoes them |
| `azure` protocol | M | ⬜ | needs an Azure resource |
| `ark` / `dashscope` / `minimax` native | M | ⬜ | needs those API keys |
| `custom` / `command` protocols | M | ⬜ | needs the in-house endpoint |
| MCP server with a GUI client | M | ⬜ | needs WorkBuddy / DSH Desktop |
| Linux keyring (`secret-tool`) | M (simulated) | ⬜ | needs a Linux box |
| Windows (`setup.ps1`, no keyring) | M + CI (real Windows: registry, MCP) | ⬜ | `setup.ps1` and the bash suites still need a Windows box |
| streamed download (`.part` → atomic rename) | M | ✅ | mock: chunked write, no leftovers on 404 |
| `/videos/edits`, `/videos/characters`, `/images/variations` | – | — | not implemented (routes exist upstream) |
| native vendor TTS/STT for ark/dashscope/minimax | – | — | deliberate; use `custom`/`command` |
| parallel *generation* (not just waiting) | – | — | not implemented |
| cost estimation | – | — | deliberate (no price tables) |

Nothing in the `⬜` rows is guessed-wrong in code: each has either a mock suite or a documented
refusal. The distinction matters — "implemented" ≠ "proven against the vendor".
