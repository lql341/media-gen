# Non-official / in-house endpoints (`custom` and `command`)

The four built-in protocols cover OpenAI-compatible gateways and three vendor APIs. Two escape
hatches cover everything else, so a new endpoint never requires editing this repository.

## Option A — `custom`: describe the JSON shape

Best when the service is ordinary REST but with its own field names. Write a template file:

```json
{
  "auth": {"mode": "bearer"},
  "image": {
    "method": "POST", "path": "/v1/t2i",
    "body": {"model": "{model}", "prompt": "{prompt}", "size": "{size}", "n": "{n}"},
    "response": {"mode": "b64", "path": "data.0.image"}
  },
  "video": {
    "create": {"method": "POST", "path": "/v1/tasks",
               "body": {"model": "{model}", "input": {"text": "{prompt}"},
                        "seconds": "{seconds}", "size": "{size}"}},
    "task_id_path": "task.id",
    "status": {"path": "/v1/tasks/{task_id}"},
    "state": {"status_path": "state", "done": ["finished"], "failed": ["failed"],
              "error_path": "message", "video_url_path": "output.video_url",
              "seconds_path": "output.duration", "size_path": "output.size"},
    "fetch": {"mode": "url"}
  }
}
```

```bash
scripts/setup.sh add inhouse --protocol custom \
    --base-url https://inhouse.example/api --custom-file ./inhouse.json
scripts/setup.sh doctor --profile inhouse
scripts/media.py image -p "a cat" --model any --size 800x600 --profile inhouse
```

### Placeholders

`{model}` `{prompt}` `{size}` `{n}` `{seconds}` `{ratio}` `{resolution}` `{task_id}`
`{ref_base64}` `{ref_mime}` `{ref_data_uri}`.

- A string that is *only* a placeholder keeps the native JSON type, so `{"n": "{n}"}` sends a number
  and `{"seconds": "{seconds}"}` sends `4`, not `"4"`.
- `{ref_*}` exist only when `--image` was given; `{ref_data_uri}` is the ready-to-send form.
- Paths inside `response.path`, `task_id_path`, `state.*_path` are dotted: `data.0.image`,
  `output.video_url`. Numeric segments index into arrays.

### Auth

| `auth.mode` | Effect |
| --- | --- |
| `bearer` (default) | `Authorization: Bearer <key>` |
| `header` | `<auth.name>: <auth.prefix><key>`, e.g. `auth: {"mode":"header","name":"x-api-key","prefix":""}` |
| `query` | appends `?<auth.name>=<key>`, e.g. `{"mode":"query","name":"token"}` |

Keys are still resolved by the profile (env → credential store); they never appear in the template.

### Limits

- One request per step: no multi-step auth handshakes, no signed uploads. Use `command` for those.
- `response.mode` is `b64` or `url`; `fetch.mode` is `url` or `path`.
- Anything the template cannot express is a hint that you want `command`.

## Option B — `command`: wrap it in a script

For genuinely exotic protocols (signed forms, gRPC gateways, token exchange), point the profile at
commands that exchange JSON over stdin/stdout:

```bash
scripts/setup.sh add weird --protocol command --base-url unused://weird \
  --command-json '{"image":"~/bin/weird image","create":"~/bin/weird create",
                   "status":"~/bin/weird status","fetch":"~/bin/weird fetch"}'
```

Contract — stdin is JSON, stdout must be JSON, non-zero exit means failure and stderr is shown:

| Step | stdin | stdout |
| --- | --- | --- |
| `image` | `{model,prompt,size?,n,ref?}` | `{"b64": "…"}` or `{"url": "…"}` |
| `create` | `{model,prompt,seconds?,size?,ratio?,resolution?,ref?}` | `{"task_id": "…"}` |
| `status` | `{task_id}` | `{"status","url"?,"error"?,"seconds"?,"size"?}` |
| `fetch` | `{task_id,url?}` | raw bytes on stdout, or empty when `url` is provided |

The hook receives `MEDIA_BASE_URL` and `MEDIA_PROFILE_KEY` in its environment (never on the command
line, so `ps` cannot see the key). Statuses are the protocol-neutral ones:
`queued` / `processing` / `completed` / `failed`.

Example hook (~15 lines of shell around `curl`):

```bash
#!/usr/bin/env bash
set -euo pipefail
step="$1"; payload="$(cat)"
case "$step" in
  create) curl -sS -X POST "$MEDIA_BASE_URL/tasks" -H "Authorization: Bearer $MEDIA_PROFILE_KEY" \
            -H 'Content-Type: application/json' -d "$payload" | jq -c '{task_id: .job.id}' ;;
  status) id="$(jq -r .task_id <<<"$payload")"
          curl -sS "$MEDIA_BASE_URL/tasks/$id" -H "Authorization: Bearer $MEDIA_PROFILE_KEY" \
            | jq -c '{status: (if .state=="done" then "completed" else "processing" end), url: .result}' ;;
  fetch)  id="$(jq -r .task_id <<<"$payload")"
          curl -sS "$MEDIA_BASE_URL/tasks/$id/file" -H "Authorization: Bearer $MEDIA_PROFILE_KEY" ;;
esac
```

## Registering capabilities

The registry decides whether a model is image or video and what it accepts. For an in-house model
id, add a rule in `~/.config/media-gen/registry.json` (no repo change needed):

```json
{"rules": [
  {"match": ["inhouse-t2v-*"], "kind": "video",
   "duration": {"min": 2, "max": 8}, "size": {"form": "WxH"}, "image_input": true},
  {"match": ["inhouse-t2i"], "kind": "image", "size": {"form": "WxH"}, "n": true}
]}
```

Without a rule the CLI falls back to name heuristics (`*t2v*` → video, `*image*` → image) and, for
`run`, requires an explicit `image`/`video` subcommand.

## Verifying a custom endpoint

```bash
scripts/setup.sh show inhouse          # 模板/命令 + 密钥来源（脱敏）
scripts/media.py models --profile inhouse   # custom/command 没有 /models，返回能力表
scripts/media.py video -p test --model <id> -s 2 --dry-run --profile inhouse   # 先看归一化结果
scripts/media.py video -p test --model <id> -s 2 --interval 0 -o /tmp/t.mp4 --profile inhouse
```

The last command is the real test. If it fails, the error text names the step (`custom image.response`
or `command.status`), which is where to look first.
