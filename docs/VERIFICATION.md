# Verification record — macOS, real gateway (2026-11-14)

What was actually executed, and what is still simulated. Re-run any row with the command shown;
costs are what the gateway reported in `usage`.

## Live: calls that produced (or were meant to produce) media

| # | Capability | Command | Result | Cost |
| --- | --- | --- | --- | --- |
| 1 | text → video | `media.py video -p "…" -s 4 --ratio 16:9 --resolution 480p -o out.mp4` | ✅ 854x480, 689 KB | 38 830 tokens |
| 2 | text → video (vertical) | `video -s 10 --ratio 9:16 --resolution 720p` | ✅ 720x1280, 8 MB | 216 900 tokens |
| 3 | **image → video** | `video -p … -s 4 --ratio adaptive --resolution 480p --image https://…/640x480.png` | ✅ 1.5 MB | 39 820 tokens |
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
