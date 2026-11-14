# Changelog

## 0.9.0 - 2026-11-14

Image-to-video that actually works against a real LiteLLM gateway, plus honest notes about it.

- The `openai` adapter now tries four reference-image encodings in order and stops at the first that
  the gateway accepts: multipart `input_reference` → JSON `input_reference` → JSON `image` → JSON
  `content[]` with `image_url`. The ladder only advances on `400/415/422`, which never creates a
  billable task.
- `--image` accepts an `http(s)` URL as well as a local path. For first-frame runs the adapter drops
  `size`, sets `ratio=adaptive`, and forwards `ratio`/`resolution` through `extra_body` — all three are
  required by Volcengine-backed gateways and were learned from live 400s.
- Measured findings documented in `references/providers.md` and `references/routing-video.md`: the
  gateway rejects multipart despite declaring it, rejects `data:` URIs as reference images, and
  rejects `size` for first-frame tasks.
- Live verification: 4 s / 480p / 9:16 image-to-video through the the gateway gateway, 39 820 tokens, file
  downloaded; text-to-video, batch, edits, speech and transcribe were already covered.
- `CAPABILITIES.md` verification column updated to separate live from mock.

## 0.8.0 - 2026-11-14

Speech-to-text, and audio for non-official endpoints — the multimodal surface is now complete.

- **Transcription**: `media.py transcribe -f audio.mp3 --model whisper-1 [--language] [-o out.txt]`
  over multipart `/audio/transcriptions`; registry gains the `transcription` kind
  (`whisper-*`, `gpt-4o(-mini)-transcribe*`, `paraformer*`), `models --kind transcription` lists them,
  and `run` points at `transcribe`.
- **Audio in `custom` / `command`**: a template can declare `speech` (raw bytes + `response.suffix`)
  and `transcribe` (`response.text_path`); a command hook can implement `speech` (stdout bytes) and
  `transcribe` (`{"text": …}`). Native vendor audio APIs stay unimplemented on purpose — wrap them
  instead of guessing.
- `audio` kind split into `speech` and `transcription`; `add --default-speech` /
  `--default-transcription`; `models --kind` accepts all four kinds.
- **`CAPABILITIES.md`**: one page listing every operation × protocol × verification level, the
  registry fields, configuration/safety surface, agent integrations and the test matrix.
- Tests: multipart transcription, custom speech/transcribe, command speech/transcribe, CLI
  transcribe (stdout and `-o`), and the `run` pointer for both new kinds.

## 0.7.0 - 2026-11-14

The remaining route gaps: image-to-video on gateways, image editing, last frames, speech.

- **Image-to-video over the `openai` protocol**: with `--image` the CLI now posts multipart
  `input_reference` to `/videos` — the documented shape for OpenAI's Videos API and LiteLLM's
  `/videos` (their OpenAPI declares exactly that binary field). No more "use a native protocol" for
  gateways. Verified against the gateway's own `openapi.json`, not against marketing docs.
- **Image editing**: `--image` (plus optional `--mask`) switches `/images/generations` →
  multipart `/images/edits`; native protocols keep their own reference mechanism and DashScope still
  refuses locally with a hint.
- **Last frame**: `VideoState.last_frame_url` is parsed and exposed; `--last-frame out.png` saves it
  after a run (useful for chaining clips), and `status` prints it.
- **Speech**: new `media.py speech -t … --model tts-1 [--voice] [--format] [-o out.mp3]` over
  `/audio/speech`; registry gains the `audio` kind (`tts-1*`, `gpt-4o-mini-tts*`, `speech-*`,
  `cosyvoice*`), `models --kind audio` lists them, and `run` points at `speech` instead of guessing.
- Shared stdlib multipart encoder (no `requests` dependency) used by both multipart paths.
- Tests: multipart edit, multipart i2v (content-type asserted), last-frame fetch, speech bytes, plus
  CLI end-to-end for all four; mock server grew `/images/edits`, `/audio/speech` and a last-frame URL.

## 0.6.0 - 2026-11-14

Batch images are no longer truncated to the first result.

- Every protocol returns a **list** of images: `openai`/`ark` (`data[]`), `dashscope` (`results[]`),
  `minimax` (`image_base64[]` / `image_urls[]`), `custom` (a list path with optional `item` selector),
  `command` (single `{b64|url}` or `{images:[…]}`).
- `media.py image -n N` saves all of them: single result keeps `out.png`, several become
  `out-1.png`, `out-2.png`, …; every path is printed on stdout.
- MCP `media_image` returns an array when more than one image was produced.
- Tests: batch assertions in the protocol suite (openai 3 images, custom list template, command
  `images` list) and in the CLI suite (three files on disk, naming, no stray un-numbered file).

## 0.5.0 - 2026-11-14

Multiple accounts per endpoint, safe for concurrent sessions.

- **Accounts**: `setup.sh add <name> --account <alias> … --key-stdin` attaches a second key (and
  optional `base_url` / default models / `credential_ref`) to the same profile. Selected by
  `<name>@<alias>`, `--profile <name>@<alias>`, `--account`, or `MEDIA_ACCOUNT`; the saved default may
  include an alias (`use litellm@team`).
- **No fallback between accounts**: a named account never borrows the default account's key or store
  item; a missing item fails with the exact entry to create. Per-account env var
  `MEDIA_API_KEY_<PROFILE>_<ACCOUNT>` wins over the generic ones.
- **Per-process selection** means two agent sessions can drive two accounts simultaneously without
  touching each other's configuration.
- Credential items are named `media-gen/<profile>@<alias>`; `audit` lists them all with exact delete
  commands, `rm <name> --account <alias>` removes one account, `show` / `export` mask per-account keys.
- Wizard asks for an optional alias in the add flow and sets the account as default when used.
- Tests: account isolation, per-account base URL, env precedence, default-with-alias, no-fallback,
  masking in `show`/`export`, and `--account` handling in the CLI.

## 0.4.2 - 2026-11-14

Reuse older credentials instead of duplicating them.

- **`--credential-ref <service>:<account>`** on `add`, plus `set-credential-ref`: a profile can use an
  existing credential-store item in place (e.g. the legacy `seedance-gateway/default`) with no copy
  and no write. Resolution order: env → `credential_ref` → `media-gen/<profile>` → legacy item →
  inline 0600 key → agent auth import.
- **`migrate --to <profile> [--delete-legacy]`**: copies the old config + secret under the new name,
  and deleting the old item still requires `MEDIA_ALLOW_CREDENTIAL_DELETE=1`.
- **`audit` never decrypts**: existence is checked with `security find-generic-password` *without*
  `-w` (and `secret-tool lookup` only where unavoidable), and the legacy item is always reported as
  read-only.
- Docs: MIGRATION.md documents the three options (reuse in place / copy / copy+delete), setup.md and
  troubleshooting updated.

## 0.4.1 - 2026-11-14

Safety fix: nothing deletes a stored secret by default any more.

- `setup.sh rm` / `rm --all` now remove **configuration only**. Deleting the credential-store item
  requires `MEDIA_ALLOW_CREDENTIAL_DELETE=1`; otherwise the CLI prints the exact
  `security delete-generic-password -s media-gen -a <name>` command and keeps the secret.
- New read-only `setup.sh audit`: profiles, whether a store item exists for each, the exact delete
  command, the current `MEDIA_CREDENTIAL_STORE` mode, and whether the delete gate is open. The legacy
  `seedance-gateway` item is listed as read-only and is never removed by this tool.
- Deletion always addresses `-s SERVICE -a ACCOUNT`; there is no service-only delete path, so one
  profile cannot remove another (or an unrelated item).
- Tests: `test-config.sh` asserts the gate behaviour, and `tests/run-all.sh` asserts the whole suite
  performs zero credential-store deletions and zero writes.
- Docs: setup/troubleshooting/SKILL document the gate, the audit command and the manual one-liners.

## 0.4.0 - 2026-11-14

Interactive, cross-platform, and reachable from GUI clients.

- **Wizard** (`scripts/wizard.py`, stdlib only): add / custom-template builder / modify / remove /
  list / doctor / migrate / MCP snippet. Hidden key input via `getpass`, with a visible fallback when
  stdin is piped so automation works. Same UX on macOS, Linux and Windows.
- **`scripts/setup.ps1`**: PowerShell entry point forwarding to the same wizard; resolves `python3`,
  `python`, `py -3`, or `$env:MEDIA_PYTHON`.
- **MCP server** (`scripts/mcp_server.py`): stdio JSON-RPC exposing `media_profiles`, `media_models`,
  `media_image`, `media_video`, `media_task` — the supported way for WorkBuddy / DSH Desktop /
  Claude Desktop / CodeBuddy, which cannot install skills and must not treat this as a chat model.
- **Credential-store control**: `MEDIA_CREDENTIAL_STORE=auto|file|none` (`MEDIA_NO_KEYCHAIN=1` alias),
  per-process caching of store reads (one lookup per profile per run), and `MEDIA_DEBUG_STORE=1` to
  print every access. Tests run with `none` and assert zero keyring operations.
- Wizard falls back to the `0600` file when the keyring is unavailable or locked, instead of aborting.
- Docs: `interactive.md`, `gui-clients.md`; setup/troubleshooting/SKILL/README updated.
- Tests: +`test_wizard.sh` (piped answers, incl. custom template) and +`test_mcp.py` (initialize,
  tools/list, image, video, task, unknown-method), both offline.

## 0.3.0 - 2026-11-14

Non-official endpoints, plus a real configuration lifecycle.

- **`custom` protocol**: describe an in-house REST service with a JSON template — request
  method/path/body templates with placeholders (`{model}` `{prompt}` `{size}` `{seconds}`
  `{ref_data_uri}` …), dotted response paths, configurable auth (`bearer` / `header` / `query`),
  and either `url` or `path` download. Templated under `~/.config/media-gen/custom/<profile>.json`.
- **`command` protocol**: point a profile at hook commands that exchange JSON on stdin/stdout
  (`image` / `create` / `status` / `fetch`), so exotic protocols (signed forms, token exchange) need
  no repo change. The key is passed via environment, never argv.
- **Configuration lifecycle**: `modify` (interactive), `set-url`, `set-key`, `set-protocol`,
  `rename` (moves the credential entry too), `show`, `export` / `import` (never include secrets),
  `rm --all`, and `add` doubles as update while keeping the stored key.
- Registry remains the single place for capabilities; `~/.config/media-gen/registry.json` covers
  in-house model ids without touching the repo.
- Tests: +2 protocols (custom, command) with 22 protocol tests total; lifecycle assertions for
  URL/key/protocol changes, rename, export/import, `rm --all`.
- Docs: `references/custom-endpoints.md` (templates, placeholders, auth modes, hook contract,
  verification recipe); every other doc updated to mention the two escape hatches.

## 0.2.0 - 2026-11-14

Renamed from `seedance` (0.1.0) and generalised from one gateway + one model family to
model-agnostic image/video generation.

- **Profiles**: any number of named endpoints, each with a wire protocol and its own credential.
  `setup.sh add|use|list|rm|status|doctor|migrate`; a profile can also come entirely from
  `MEDIA_BASE_URL` + `MEDIA_PROTOCOL` for CI.
- **Capability registry** (`scripts/registry.json` + `~/.config/media-gen/registry.json`):
  model id patterns decide kind (image/video) and constraints (duration range or enum, size syntax,
  reference-image support), so no vendor logic lives in the code.
- **Four wire protocols**: `openai` (OpenAI/LiteLLM), `ark` (Volcengine native), `dashscope`
  (Alibaba Wan), `minimax` (Hailuo). Parameter mapping absorbs the differences: `seconds` vs
  `duration`, `1280x720` vs `1280*720` vs `width`/`height`, `ratio`+`resolution`, async task APIs,
  two-hop file retrieval.
- **Unified CLI** (`scripts/media.py`): `models`, `image`, `video`, `run`, `status`, `wait`,
  `download`, plus `--dry-run` and `--create-only`.
- **Local validation** of duration/size against the registry before any paid request.
- **Offline test suite** with a scripted mock server per protocol, so adapters are verified without
  accounts or spend; verification status per protocol is documented honestly.
- Credentials: per-profile OS credential entries (`media-gen`), env overrides
  (`MEDIA_API_KEY_<PROFILE>` → `MEDIA_API_KEY`), read-only import from agent auth files, and
  migration from the old `seedance-gateway` Keychain item / `~/.config/seedance/config.json`.
- `scripts/seedance.sh` kept as a deprecation shim mapping to `media.py video`.

## 0.1.0 - 2026-11-14

Initial release as `seedance`: a five-command CLI over a LiteLLM gateway's Videos route for
`doubao-seedance-2-5` / `doubao-seedance-2-0-260128`, with explicit gateway URL, key in the OS
credential store, and offline tests. Tagged `v0.1.0`.
