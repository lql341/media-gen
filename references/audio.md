# Speech synthesis (`/audio/speech`)

One more medium, same plumbing: a profile, a registry rule, one request.

```bash
scripts/media.py speech -t "公司年会将在本周五下午三点开始" --model tts-1 -o brief.mp3
scripts/media.py speech -t "hello" --model gpt-4o-mini-tts --voice alloy --format wav -o hello.wav
scripts/setup.sh add openai --default-audio tts-1        # 保存默认模型
```

Protocol support:

| Protocol | Implemented | Notes |
| --- | --- | --- |
| `openai` | yes | `POST /audio/speech {model, input, voice?, response_format?}` → audio bytes |
| `ark` / `dashscope` / `minimax` | no | they need their own endpoints; use `command` to wrap one |
| `custom` / `command` | no (by design) | a TTS endpoint with an unusual shape is best wrapped by a `command` hook |

Details worth knowing:

- The reply is raw audio, not JSON: the file suffix comes from `--format`, otherwise `.mp3`.
- `voice` and `format` are passed through untouched; unknown values are rejected by the server with a
  readable error.
- Registry rules cover `tts-1*`, `gpt-4o-mini-tts*`, `speech-*`, `cosyvoice*`. `models --kind audio`
  lists them; `run` refuses an audio model and points at `speech`, because "generate from this model"
  is ambiguous for text-to-speech.
- Billing is per character/token at the provider; there is no draft mode, so `--dry-run` (which prints
  the request without sending it) is the cheap check.
