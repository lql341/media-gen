# Image routes

Images are **synchronous**: one request, one response with bytes or a URL. If a provider is
asynchronous (DashScope Wan), the `dashscope` adapter polls the task and returns the result, so the
CLI surface stays the same.

## openai (OpenAI / LiteLLM / compatible gateways)

```
POST /images/generations
{ "model": "gpt-image-1", "prompt": "…", "n": 1,
  "size": "1024x1024", "response_format": "b64_json" }
→ { "data": [ { "b64_json": "…" } ] }        or   { "data": [ { "url": "https://…" } ] }
```

Both response shapes are handled: base64 is decoded, URLs are downloaded (without leaking the API
key to the artifact host). `--size` is formatted as `WxH`; `-n` is passed through only when the
registry marks the model as supporting `n>1`.

Reference images (editing) live on a different route (`/images/edits`, multipart). The adapter
refuses `--image` with a pointer instead of silently ignoring it.

## ark (Volcengine Seedream)

```
POST /images/generations
{ "model": "doubao-seedream-4-0", "prompt": "…", "size": "1024x1024",
  "response_format": "b64_json", "image": "data:image/png;base64,…" }
```

Native Ark accepts a base64 data URI for image-guided generation, so `--image` works locally.

## dashscope (Alibaba Wan t2i)

```
POST /services/aigc/text2image/image-synthesis      (Header: X-DashScope-Async: enable)
{ "model": "wan2.5-t2i-preview", "input": {"prompt": "…"},
  "parameters": {"size": "1024*1024", "n": 1} }
→ {"output": {"task_id": "…"}}
GET /tasks/<task_id> → {"output": {"task_status": "SUCCEEDED", "results": [{"url": …}]}}
```

Sizes use the `1024*1024` syntax — the registry tells the CLI to reformat `--size` accordingly.
Results are URLs on a CDN, downloaded without credentials.

## minimax (image-01)

```
POST /image_generation
{ "model": "image-01", "prompt": "…", "n": 1, "response_format": "base64",
  "width": 1024, "height": 1024 }        or   { "aspect_ratio": "16:9" }
→ {"data": {"image_base64": ["…"]}}      or   {"data": {"image_urls": ["…"]}}
```

MiniMax takes pixel dimensions or an aspect ratio, never a `WxH` string: the adapter splits
`--size 1024x1024` into `width`/`height`, and passes non-pixel values as `aspect_ratio`.

## Cost discipline

Image calls are usually cheaper than video but not free. `--dry-run` shows the normalized plan
(model, size, n, protocol) without sending anything; use it before batch requests.
