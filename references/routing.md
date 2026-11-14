# Video routes on a LiteLLM gateway

Everything here was observed against a LiteLLM proxy fronting Volcengine Seedance deployments.
A different gateway may differ in details; the route shape is what the scripts rely on, and the
base URL is configurable.

## Why a chat endpoint does not work

| Route | Result |
| --- | --- |
| `POST /chat/completions` | `429 No deployments available for selected model` |
| `POST /responses` | `429 No deployments available for selected model` |
| `POST /images/generations` | `503 ... No deployment for image model ... image_pricing_strategy` |
| `GET /models` | lists the model IDs, with no type metadata (`owned_by: openai`) |

The model is attached to a **video** deployment. A `429` of this exact shape is not a rate limit and
must not be retried.

## Route shape

| Method | Path | Notes |
| --- | --- | --- |
| POST | `/videos` | returns `{"id":"video_...","object":"video","status":"queued"}` immediately |
| GET | `/videos/<id>` | `queued` → `processing` → `completed` / `failed` |
| GET | `/videos/<id>/content` | binary; answers **307** to object storage, so follow redirects |
| DELETE | `/videos/<id>` | idempotent cleanup |
| POST | `/videos/<id>/remix` | derive a new clip from an existing one |
| POST | `/videos/extensions` | extend a clip |
| POST | `/videos/edits` | edit a clip |
| POST | `/videos/characters` | reusable character reference |
| GET | `/videos?model=<id>` | list tasks; omitting the model is a 400 on the reference gateway |

`POST /videos` is declared as `multipart/form-data` in the gateway's OpenAPI document, but a plain
`application/json` body works for text-to-video. Image-to-video needs multipart so that
`input_reference` can carry the file.

## Request fields

| Field | Type | Notes |
| --- | --- | --- |
| `model` | string | required; the model ID from `GET /models` |
| `prompt` | string | required unless the gateway is configured for raw provider input |
| `seconds` | int | `4..30`, or `-1` to let the model choose |
| `size` | string | e.g. `1280x720`; must be in the model's whitelist |
| `extra_body.ratio` | string | provider-native aspect ratio (`16:9`, `9:16`, `1:1`, …) |
| `extra_body.resolution` | string | provider-native resolution (`480p`, `720p`, `1080p`) |
| `input_reference` | file | first frame for image-to-video (multipart field) |

Validation is provider-side and the error text names the offending field, so treat rejections as
documentation:

- `seconds` non-numeric → `BadRequestError: seconds must be an integer`
- `seconds` out of range → `duration must be an integer in 4..30 or -1`
- unknown size → `Unsupported Volcengine video size. Pass extra_body.ratio and extra_body.resolution for this size.`
- unknown resolution → `Resolution '<x>' is not supported by this model`

## Completed task shape

```json
{"object":"video","status":"completed","seconds":"10","size":"1280x720",
 "model":"<gateway-internal deployment id>",
 "usage":{"completion_tokens":216900,"total_tokens":216900,
          "video_resolution":"720p","has_video_input":false},
 "result":{"url":"https://<object-storage>/...","last_frame_url":null,
           "duration":10.0,"width":null,"height":null,"format":"mp4"}}
```

- `model` echoes the gateway's internal deployment identifier, not the ID you sent.
- Pixel dimensions live in the top-level `size`; `result.width` / `result.height` were null on the
  reference gateway.
- `seconds` is a string, `result.duration` is a float.
- `result.url` is signed and expires (24 h on the reference gateway). Download with `content` when
  you need a durable artifact; `last_frame_url` is what chain/extension workflows feed back.

## Cost shape

Billing is per video token, so cost scales with duration and resolution:

| Request | Output | `completion_tokens` |
| --- | --- | --- |
| `seconds=4`, `resolution=480p` | 854x480 | 38 830 |
| `seconds=5`, default size | model-chosen | varies |
| `seconds=10`, `size=1280x720` | 1280x720 | 216 900 |

Treat these as orders of magnitude for planning, not as a price list: rate cards live at the
gateway, not in this skill.
