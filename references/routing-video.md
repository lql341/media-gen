# Video routes

Video is **asynchronous** everywhere: create a task, poll, then fetch bytes. The CLI hides the
difference between the three shapes below.

## openai (OpenAI Videos API / LiteLLM /videos)

```
POST /videos            {"model": "…", "prompt": "…", "seconds": 5, "size": "1280x720"}
                        (+ "extra_body": {"ratio": "16:9", "resolution": "720p"} for providers that want those)
→ {"id": "video_…", "status": "queued"}
GET  /videos/<id>       → {"status": "queued|processing|completed|failed", "result": {"url": …}, "usage": {…}}
GET  /videos/<id>/content   → binary (may answer 307 to object storage: follow redirects)
```

`seconds` accepts `-1` on some deployments, meaning "let the model choose".

**Image-to-video** goes through the same route as multipart:

```
POST /videos   (multipart/form-data)
model=…  prompt=…  seconds=5  [size=1280x720]  [extra_body={"ratio":"16:9","resolution":"720p"}]
input_reference=@first-frame.png
```

That is the documented shape in both OpenAI's Videos API and LiteLLM's `/videos`
(`input_reference` is a binary field). The CLI switches to multipart automatically when `--image` is
given, so the same command works for text-to-video and image-to-video.

**Last frame**: completed tasks may carry `result.last_frame_url`. Pass `--last-frame out.png` to
`media.py video` (or `download`) and the adapter fetches and saves it — useful for chaining clips
where the end of one is the start of the next. `status` prints `last_frame_url` too.

Only video deployments answer here. A chat endpoint returns
`429 No deployments available for selected model` — that is not a rate limit and must not be retried.

## ark (Volcengine Seedance)

```
POST /contents/generations/tasks
{ "model": "doubao-seedance-2-5",
  "content": [ {"type": "text", "text": "…"}, {"type": "image_url", "image_url": {"url": "data:…"}} ],
  "duration": 5, "ratio": "16:9", "resolution": "720p" }
→ {"id": "cgt-…"}
GET /contents/generations/tasks/<id>
→ {"status": "queued|running|succeeded|failed", "content": {"video_url": "https://…"}}
```

Aspect ratio and resolution are first-class here; `--size WxH` is forwarded as `size` only when no
ratio/resolution was given.

## dashscope (Alibaba Wan t2v / i2v)

```
POST /services/aigc/video-generation/video-synthesis     (Header: X-DashScope-Async: enable)
{ "model": "wan2.5-t2v-preview", "input": {"prompt": "…", "img_url": "https://…"},
  "parameters": {"size": "1280*720", "duration": 5} }
→ {"output": {"task_id": "…"}}
GET /tasks/<id> → {"output": {"task_status": "PENDING|RUNNING|SUCCEEDED|FAILED", "video_url": …}}
```

`img_url` must be publicly reachable; the adapter refuses a local path with a clear message.

## minimax (Hailuo)

```
POST /video_generation   {"model": "MiniMax-Hailuo-02", "prompt": "…", "duration": 6,
                          "resolution": "1080P", "first_frame_image": "data:image/jpeg;base64,…"}
→ {"task_id": "…", "base_resp": {"status_code": 0}}
GET /query/video_generation?task_id=…   → {"status": "Queueing|Processing|Success|Fail", "file_id": …}
GET /files/retrieve?file_id=…           → {"file": {"download_url": "https://…"}}
```

Duration is an enum (6 or 10 s) and resolution is `768P`/`1080P`; both are validated locally from
the registry before any request. Errors arrive with HTTP 200 inside `base_resp`, so the adapter
inspects the payload.

## Polling

`media.py video` creates, polls (default every 10 s, up to 1800 s) and downloads. Use
`--create-only` when you want the task id to keep, `status` / `wait` to resume, and `download` to
re-fetch a finished task (signed URLs expire).
