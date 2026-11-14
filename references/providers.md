# Per-provider notes and verification status

Honest status table — what has been exercised end to end, and what is written from public protocol
documentation only. "Mock" means the adapter was validated against a scripted local server
implementing the documented wire format; it does **not** mean it was run against the live vendor.

| Protocol | Models | Verified how | Notes |
| --- | --- | --- | --- |
| `openai` | any OpenAI-compatible image/video endpoint | live: text-to-video, **image-to-video (URL)**, batch, edits, speech, transcribe; mock: everything else | the safest choice for gateways; see the i2v ladder below |
| `ark` | `doubao-seedance-*`, `doubao-seedream-*` | mock | same vendor family as the live-tested gateway models |
| `dashscope` | `wan*-t2i/t2v/i2v` | mock | async task API, `1024*1024` sizes, public `img_url` required for i2v |
| `minimax` | `MiniMax-Hailuo-*`, `image-01` | mock | duration enum 6/10 s; `768P`/`1080P`; file retrieval is a second hop |

## Parameter quirks the registry + adapters absorb

| Need | openai | ark | dashscope | minimax |
| --- | --- | --- | --- | --- |
| duration field | `seconds` | `duration` | `parameters.duration` | `duration` (enum 6/10) |
| size syntax | `size: "1280x720"` | `ratio` + `resolution`, or `size` | `size: "1280*720"` | `resolution: "1080P"` or `width`/`height` |
| aspect ratio | `extra_body.ratio` | `ratio` | `parameters.aspect_ratio` | `aspect_ratio` |
| first-frame image | multipart `input_reference` | `content[].image_url` (data URI) | `input.img_url` (public URL) | `first_frame_image` (data URI) |
| async wrapper | task id + `/videos/<id>` | `/contents/generations/tasks` | `X-DashScope-Async` + `/tasks/<id>` | `/query/video_generation` then `/files/retrieve` |
| errors | HTTP 4xx/5xx JSON | HTTP 4xx/5xx JSON | HTTP 4xx + `output.message` | HTTP 200 + `base_resp.status_code` |

## Adding a provider

1. Add a rule to `scripts/registry.json` if the model id family is new (`match`, `kind`, duration,
   size form). Users can override without touching the repo:
   `~/.config/media-gen/registry.json` with the same shape.
2. Add `scripts/protocols/<name>.py` implementing `image()`, `video_create()`, `video_status()`,
   `video_fetch()` on top of `Protocol` (`_request`, `_json`, `fetch` are provided).
3. Register it in `protocols/__init__.py::load_protocol` and in `media_config.PROTOCOLS`.
4. Add mock routes to `tests/mock_server.py` and a test class in `tests/test_protocols.py`. The
   suite must exercise create → poll → download and inspect the request body.
5. Document the quirks above and flip the verification column honestly.


## Field notes: image-to-video through a LiteLLM gateway (measured)

A LiteLLM proxy fronting Volcengine Seedance does **not** accept what the OpenAPI document suggests.
Measured behaviour, in the order the adapter now tries them:

| Attempt | Result |
| --- | --- |
| `multipart/form-data` + `input_reference` (as declared in the gateway's own OpenAPI) | `400 Invalid request format: 'str' object has no attribute 'pop'` — the proxy parses the body as JSON |
| JSON + `input_reference: "data:…"` | `400` (field ignored/unknown) |
| JSON + `image: "data:…"` | `400` (field ignored/unknown) |
| JSON + `content: [{type:text},{type:image_url,image_url:{url}}]` with `ratio=adaptive` and provider params in `extra_body` | **works** |

Two additional rules learned the hard way:

- With a first frame, `ratio` must be `adaptive`; sending `size` is rejected with
  `first_frame task requires ratio='adaptive'; use extra_body with native parameters instead of size`.
  The adapter therefore drops `size` and sets `ratio=adaptive` automatically for reference runs.
- The reference **must be a public URL**. A base64 `data:` URI is rejected by the provider with
  `invalid_reference_image_url`. Local files therefore only work on adapters that accept data URIs
  (`ark` native, `minimax`).

The retry ladder is safe: it only advances on `400/415/422`, i.e. requests the gateway rejected before
creating a billable task.


## Gateway extras, measured

| Route | LiteLLM → Volcengine (this mac) | Notes |
| --- | --- | --- |
| `GET /videos?model=<id>` | `400 LLM Provider NOT provided` | the proxy drops the query and forwards `model=''`; the CLI now says so and points at the local ledger |
| `POST /videos/<id>/remix` | not exercised live (would create a billable task) | adapter implemented, covered by mock |
| `POST /videos/extensions` | not exercised live | adapter implemented, covered by mock |

Network note: the gateway occasionally times out on TLS handshake; GET retries (`MEDIA_RETRY`, default
2) absorb most of it, and `doctor` is idempotent so re-running is free.
