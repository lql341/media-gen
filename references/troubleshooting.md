# Troubleshooting

Read-only checks first:

```bash
scripts/setup.sh list                 # which profiles exist, which is default
scripts/setup.sh status [--profile P] # protocol, URL, key source (masked)
scripts/setup.sh doctor [--profile P] # GET /models + which registry models are visible
```

## Configuration

| Symptom | Cause | Fix |
| --- | --- | --- |
| `还没有任何配置档` | nothing configured | `setup.sh add <name> --protocol … --base-url …` |
| `有多个配置档，请指定 --profile` | no default set | `setup.sh use <name>` or pass `--profile` |
| `配置档 X 缺少 base_url` | profile edited by hand | re-add it |
| `密钥被拒绝` (401) in doctor | rotated key / wrong endpoint | re-add with the new key |
| key source is `只读导入` | imported from an agent's own file | rotate there, or `setup.sh add … --key-stdin` |
| `MEDIA_API_KEY` wins unexpectedly | env beats the store | unset it or update it |
| `protocol=smtp 不受支持` | typo in `MEDIA_PROTOCOL` | `openai` / `ark` / `dashscope` / `minimax` |

## Model / capability

| Symptom | Cause | Fix |
| --- | --- | --- |
| `team not allowed to access model` | key's team allowlist | the错误 lists allowed models; pick one or ask the operator |
| `404` on `/images/generations` or `/videos` | endpoint lacks the route | another profile, or the native protocol |
| model unknown to the registry | id family not covered | add a rule to `~/.config/media-gen/registry.json` |
| `时长下限/上限是 …` | registry constraint | use the printed range/enum |
| `时长是枚举值 [6, 10]` | MiniMax-style enum | pass 6 or 10 |
| `--size 需要像素尺寸` | model wants pixels | `1024x1024` |
| `size:resolution∈{768P,1080P}` | model wants a resolution tier | `--resolution 1080P` |

## Requests

| Symptom | Cause | Fix |
| --- | --- | --- |
| `429 No deployments available` | video model called as chat | use this CLI, never retry |
| `图生视频的 img_url 必须是公网可访问的 URL` | DashScope needs a URL | upload the first frame, or use ark/minimax |
| `openai 协议的首帧图需要 multipart` | protocol limitation | native protocol for image-to-video |
| task `failed` with a provider message | provider-side error | report verbatim; a retry is a new paid request |
| `等待超时` | long queue | task id was printed; use `status` / `wait` / `download` later |

## Downloads

| Symptom | Cause | Fix |
| --- | --- | --- |
| 0-byte file | redirect not followed / no content route | the adapters follow redirects; check the signed URL is still valid |
| URL works in a browser, not later | signed URL expired | `media.py download <task_id> out.mp4` |
| `MiniMax 任务没有 file_id` | status polled before it existed | `wait` again |

## Non-official endpoints

| Symptom | Cause | Fix |
| --- | --- | --- |
| `custom 模板不存在` | profile points at a missing file | re-add with `--custom-file`, or write `~/.config/media-gen/custom/<name>.json` |
| `custom image.response.mode=… 不受支持` | template typo | only `b64` / `url` (and `url` / `path` for fetch) |
| `custom video: 在 task.id 找不到任务 id` | wrong `task_id_path` | fix the dotted path (`task.id`, `data.0.id`) |
| `command 协议需要在配置档里提供 command` | profile lacks the hook table | `set-protocol --protocol command --command-json …` |
| `command.create 失败（exit=N）` | hook failed | run the hook manually with JSON on stdin; stderr is echoed |
| `command.fetch 没有输出` | hook printed nothing | return raw bytes, or return a URL and set `fetch`/`status.url` |
| `--base-url 必须是 http(s)://` | used with `custom` but value is an identifier | `command` allows `unused://…`; `custom` needs a real URL |

## Not bugs

- `models` shows `unknown` for chat models: the registry only classifies media families.
- A native protocol has no `/models`: pass `--model` explicitly.
- The same model id can appear through different profiles with different quirks — that is the
  profile's protocol, not a bug.
