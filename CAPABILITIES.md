# media-gen capability checklist

One skill, five media operations, six wire protocols, no vendor lock-in. Everything below is
implemented in this repository; the "verified" column says how it was checked.

## Operations

| Operation | Command | Notes |
| --- | --- | --- |
| Text → image | `media.py image -p … --model M` | sync, b64 or url response, batch (`-n`) saves every image |
| Image → image (edit) | `media.py image -p … --model M --image ref.png [--mask m.png]` | multipart `/images/edits` (openai), inline data URI (ark), `subject_reference` (minimax) |
| Text → video | `media.py video -p … --model M [-s N] [--ratio] [--resolution]` | async: create → poll → download |
| Image → video | `media.py video -p … --image first.png` or `--image https://…/first.png` | openai: multipart → JSON fallbacks (gateways may need a public URL and `ratio=adaptive`); ark: data URI; dashscope: public URL; minimax: data URI |
| Last frame | `media.py video … --last-frame f.png` | parses `result.last_frame_url`; enables clip chaining |
| Text → speech | `media.py speech -t … --model tts-1 [--voice] [--format]` | raw audio bytes; suffix from `--format` |
| Speech → text | `media.py transcribe -f audio.mp3 --model whisper-1 [--language]` | multipart upload, returns/prints text |
| Task control | `media.py status / wait / download / --create-only` | resumable, bounded polling |
| Planning | `--dry-run` on every generation command | prints the normalized plan, sends nothing |

## Protocols

| Protocol | Images | Edit | Video | i2v | Speech | Transcribe | Verified |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `openai` (OpenAI, LiteLLM, compatible gateways) | yes | yes | yes | yes (multipart, with JSON fallbacks) | yes | yes | **live**: t2v, i2v (public URL), batch; mock: rest |
| `ark` (Volcengine Seedance/Seedream) | yes | yes (data URI) | yes | yes (data URI) | — | — | mock |
| `dashscope` (Alibaba Wan) | yes | — (clear error) | yes | public URL only | — | — | mock |
| `minimax` (Hailuo video, image-01) | yes | yes (`subject_reference`) | yes | yes (`first_frame_image`) | — | — | mock |
| `custom` (declarative JSON template) | yes | template `{ref_*}` | yes | template `{ref_*}` | yes (`speech` section) | yes (`transcribe` section) | mock |
| `command` (hook script contract) | yes | `{ref}` in payload | yes | `{ref}` in payload | yes (`speech` hook) | yes (`transcribe` hook) | mock |

"mock" means validated end-to-end against `tests/mock_server.py`, a scripted implementation of the
documented wire shape — not against the vendor. Native vendor TTS/transcription is intentionally not
guessed; wrap it with a `custom`/`command` profile instead.

## Model capability registry

`scripts/registry.json` (plus `~/.config/media-gen/registry.json` override) classifies model ids and
their constraints: kind (`image`/`video`/`speech`/`transcription`), duration range or enum, size
syntax (`WxH` / `W*H` / resolution / aspect), reference-image support, batch support. Unknown ids are
labelled `unknown` and still usable with an explicit subcommand.

## Configuration

| Need | Feature |
| --- | --- |
| Endpoints | any number of profiles: `openai`/`ark`/`dashscope`/`minimax`/`custom`/`command` |
| Accounts | several keys per endpoint (`<profile>@<alias>`, `--account`, `MEDIA_ACCOUNT`), no fallback between accounts |
| Lifecycle | `add` (add or update), `modify`, `set-url`, `set-key`, `set-protocol`, `set-credential-ref`, `rename`, `show`, `export`/`import`, `rm`, `rm --account`, `rm --all` |
| Legacy | reads `~/.config/seedance/config.json` + `seedance-gateway` item; `migrate --to <profile>` copies, `--delete-legacy` (gated) removes |
| Secrets | env → `credential_ref` → `media-gen/<profile>[@alias]` → inline 0600 → agent-auth import; `MEDIA_CREDENTIAL_STORE=auto|file|none`, per-process cache, `MEDIA_DEBUG_STORE=1` |
| Safety | deletes require `MEDIA_ALLOW_CREDENTIAL_DELETE=1`; `audit` is read-only and never decrypts; deletions are always `-s service -a account` |
| Entry points | `setup.sh` (macOS/Linux), `setup.ps1` (Windows PowerShell), `wizard.py` (interactive, cross-platform) |

## Agent integrations

| Integration | How |
| --- | --- |
| Agent Skill | `SKILL.md` + `references/`; `/skill:media-gen` in Pi, `~/.agents/skills` (shared with Claude Code) |
| MCP server | `scripts/mcp_server.py`: `media_profiles`, `media_models`, `media_image`, `media_video`, `media_task` for WorkBuddy / DSH Desktop / Claude Desktop / CodeBuddy |
| Plain CLI | `scripts/media.py` for scripts, cron, CI |

## Tests (offline, no accounts, no spend)

| Suite | Covers |
| --- | --- |
| `tests/test_registry.py` | kind resolution, size normalisation, duration range/enum, user override |
| `tests/test_protocols.py` (32) | all six protocols: create → poll → download, request bodies, multipart, batch, last frame, speech, transcribe, error shapes |
| `tests/test_wizard.sh` | interactive add + custom template builder via piped answers |
| `tests/test_mcp.py` | JSON-RPC initialize/list/call, image, video, task, unknown method |
| `tests/test-config.sh` | profiles, accounts, env precedence, masking, migration, delete gate |
| `tests/test-cli.sh` | dry-run, batch, edits, i2v, last frame, speech, transcribe, validation |

`tests/run-all.sh` also asserts the whole suite performs **zero credential-store reads/writes/deletes**
and that no key is ever printed.
