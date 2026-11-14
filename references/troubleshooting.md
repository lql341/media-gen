# Troubleshooting

Start with the read-only checks; they distinguish configuration from gateway problems:

```bash
scripts/setup.sh status     # which URL/key is actually in effect, and from where
scripts/setup.sh doctor     # GET /models, HTTP status, are both video models listed
```

## Configuration

| Symptom | Cause | Fix |
| --- | --- | --- |
| `没有可用密钥；运行 scripts/setup.sh new` | nothing configured anywhere | `scripts/setup.sh new`, or export `SEEDANCE_API_KEY` |
| `doctor` → `FAIL 密钥被拒绝` (401) | key rotated, or wrong gateway | `scripts/setup.sh modify` |
| `doctor` → `FAIL 连不上` | DNS/proxy/URL typo | check `scripts/setup.sh status` for the URL in effect; `SEEDANCE_BASE_URL` overrides everything |
| status shows source `只读导入` | key came from an agent's own file | rotate in that file, or `scripts/setup.sh modify` to promote a new key |
| A shell `export SEEDANCE_API_KEY=…` wins unexpectedly | env beats credential store | unset it, or update it |
| `写入 macOS Keychain 失败` / `secret-tool` error | keyring locked or missing | unlock the keyring, install `libsecret-tools` (Debian/Ubuntu), or use `--store file` with 0600 |
| `setup.sh new` says it needs a terminal | agent tool call has no TTY | the user runs it in their own terminal, or use `--key-stdin` / `--key-from-agent` |

## Request rejections

| Message | Meaning | Fix |
| --- | --- | --- |
| `429 No deployments available for selected model` | a video model was routed at a chat endpoint | stop; use `scripts/seedance.sh`, never retry |
| `400 seconds must be an integer` | duration not numeric | `--seconds 4..30` or `-1` |
| `400 duration must be an integer in 4..30 or -1` | duration out of range | clamp it |
| `400 prompt is required for video generation` | empty prompt | pass `-p "<text>"` |
| `400 Unsupported Volcengine video size` | `--size` not whitelisted | `--ratio` + `--resolution` |
| `400 Resolution 'x' is not supported by this model` | bad `--resolution` | `480p` / `720p` / `1080p` |
| `409` from `download` | clip still rendering | `scripts/seedance.sh wait <id>` first |
| `404 Not Found` on `/videos` | gateway does not expose the Videos route | wrong base URL, or not a LiteLLM/Videos-compatible gateway |

## Downloads

| Symptom | Cause | Fix |
| --- | --- | --- |
| 0-byte file | `307` redirect not followed | the script uses `curl -L`; do not hand-roll curl without it |
| Signed URL works in a browser, fails in a script | URL expired (24 h on the reference gateway) | re-fetch with `download <id>` — the task still exists until deleted |
| `DELETE /videos/<id>` then `download` fails | task removed | nothing to recover; regenerate if the artifact was not saved |

## Long or stuck tasks

- Typical wall clock is 1.5–5 minutes: queueing plus generation. `wait` polls every 10 s and gives
  up after `--timeout` (default 1800 s) instead of hammering the gateway.
- `status` showing `processing` for many minutes with `progress: null` is normal on the reference
  gateway; it does not report a percentage.
- `failed` carries an `error` object. Report it verbatim; do not silently retry a paid request.

## Things that are not bugs

- The model never appears in `/model` or a client model picker: it has no chat deployment.
- `model` in a completed task is a gateway-internal UUID: that is the deployment, not your alias.
- `result.width` / `result.height` are null: read the top-level `size` instead.
