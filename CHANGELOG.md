# Changelog

## 0.13.1 - 2026-11-15

首次 CI 跑出来的三个真问题。

- **Windows 上 Python 一输出中文就崩**（`mcp_server` 的 `initialize` 里有个 `…` 就直接
  `UnicodeEncodeError`，整个 MCP 服务器起不来）：新增 `media_config.ensure_utf8_stdio()`，
  `media.py` / `media_config.py` / `wizard.py` / `mcp_server.py` 四个入口在写任何输出前把
  stdout/stderr 切到 UTF-8；重定向到 `StringIO` 时自动跳过。
- **CI 的 macOS 任务起不来 mock server**：`test-cli.sh` 原来每个 0.1s 起一个 python 去解析端口日志
  （冷启动的 runner 上等不到），改成 `mock_server.py --port-file` + 进程存活检查。
- **矩阵里 python 3.9 在 ubuntu-latest 上不存在**（runner 已经升到 26.04）：3.9 固定跑
  ubuntu-22.04，3.12 跑 ubuntu-latest / macos-latest。

## 0.13.0 - 2026-11-15

视频不再整块进内存；第一次有 CI。

- **流式下载**：`Protocol.download(url, path)` 分块写 `<path>.part`，成功后 `os.replace` 到最终路径。
  失败/中断不会留下半个 mp4 覆盖掉上一次的好文件；只在还没写入任何字节时才重试 5xx/429。
- `Protocol.video_download(task_id, state, path)`：有直链的协议（ark / dashscope / minimax）直接流式落盘，
  `openai` 优先拉 `/videos/<id>/content`，网关没这条路由再退回 `result.url`；只有字节的协议
  （`custom` / `command`）退回 `video_fetch` + 原子写。
- `write_artifact()` 改走同一个 `write_atomic()`，图片落盘也变成“要么完整、要么没有”。
- **CI**（`.github/workflows/tests.yml`）：ubuntu/macos × python 3.9/3.12 跑 `tests/run-all.sh`，
  Windows 任务跑纯 Python 的 registry + MCP 两套；全部离线，不产生费用。

## 0.12.0 - 2026-11-15

MCP 通道补齐到与 CLI 同等的能力面（GUI 客户端读不到 SKILL.md，缺一个入参就是没法用）。

- **新增 `media_speech` / `media_transcribe`**：`/audio/speech` 与 `/audio/transcriptions` 以前只有 CLI
  能调，GUI 用户完全够不到。
- **`media_image` 补 `mask`**：`/images/edits` 的遮罩参数之前没透传。
- **`media_video` 补 `remix` / `extend` / `last_frame`**：同样的 CLI 能力，工具层缺失。
- **`media_task {action:"download"}` 补 `last_frame`**。
- **`--last-frame` 在 `--remix` / `--extend` 分支被静默忽略**（CLI 同样的问题）：尾帧保存抽成
  `save_last_frame()`，三处（普通视频 / remix / download）共用，不再各写一份。
- `media_models` 的 `kind` 枚举补上 `speech` / `transcription`。
- 文档同步：`SKILL.md`、`CAPABILITIES.md`、`references/gui-clients.md`、两份 README 的“five tools”都改成 7 个。

## 0.11.3 - 2026-11-15

三个真行为修复，都是“明明会出错却静默”的那种。

- **`wait` 多任务时一个失败不再吞掉其他结果**：之前 `[_state_dict(f.result()) for f in futures]`
  碰到第一个异常就整体中断，其余任务已经等到的 URL/用量全丢。现在逐任务收集，输出仍含成功的
  那些，stderr 说明哪几个没等到，退出码 1。
- **`-o` 支持 `~`**：`-o ~/x.png` 之前会在当前目录建一个名为 `~` 的目录（`--image` / `--mask` /
  `--last-frame` 都是展开的，只有输出路径漏了）。新增 `out_path()` 统一处理。
- **MCP 的 `error` 字段给出真实原因**：之前只是 `str(SystemExit)`，也就是 `"1"`/`"2"`，报错信息
  埋在 `log` 里。现在取 `die()` 写到 stderr 的 `error:` 那行。
- 删掉 `tests/test_protocols.py` 里 5 个同名重复定义（同名覆盖，前一份从不执行）——−72 行。
- `tests/mock_server.py`：任务 id 含 `fail` 时固定返回失败，用于上面的多任务用例。

## 0.11.2 - 2026-11-15

MCP reported a version that stopped matching `VERSION` two releases ago.

- `SERVER_INFO.version` is read from the `VERSION` file instead of a hardcoded `0.4.0`, so
  `initialize` can no longer advertise a stale number.
- `install.sh --copy` also copies `VERSION`; the installed skill (which is not the repo) reports the
  same version as the checkout.
- `tests/test_mcp.py` asserts `serverInfo.version == VERSION`, so the two cannot drift again.

## 0.11.1 - 2026-11-14

Vendor names removed from code and history; agent-auth import made explicit.

- Dropped `LEGACY_*` env aliases (only `MEDIA_*` and the older `SEEDANCE_*` are read now).
- The read-only "import a key from an agent's auth file" fallback no longer matches a hardcoded vendor:
  it is **off unless** `MEDIA_AGENT_AUTH_PROVIDER` (provider id in that file) or
  `MEDIA_AGENT_AUTH_BASE_HOST` (URL fragment to match in `models[]`) is set.
- `migrate` now also picks up a key from an agent auth file (previous behaviour when no legacy
  keychain item existed) and says exactly which env var enables it.
- `scripts/sanitize-check.sh` additionally flags the vendor identifier itself; the pattern is built at
  runtime so the script never matches its own source.
- Git history rewritten again with `git filter-repo` so no commit contains the vendor name, the
  private gateway host, or a personal path.
- **`MCP media_task wait` was unusable**: a single task id passed programmatically went through
  `list(args.task_id)` and was split into characters, so every GUI-side wait failed. `cmd_wait` now
  accepts a string or a list.
- **Credentials follow the endpoint's origin, not a string prefix.** `fetch()` compares
  scheme + host + port: `https://gw.example.com.evil.net/…` no longer matches `startswith(base_url)`
  (it used to receive `Authorization`), and same-host URLs outside the base path (`/files/…`,
  `/videos/<id>/content`) no longer lose it.
- Regression tests for both: `test_mcp.py` (wait) and `test_protocols.py` (origin check); both fail
  against the previous implementation.

## 0.11.0 - 2026-11-14

Readiness for publishing: verification matrix command, roadmap, redaction gate.

- **`media.py doctor --matrix`**: per-capability table for the current endpoint — verifiable now / needs
  a deployment / whether it costs money — so "what can I actually prove here" is one command.
- **`ROADMAP.md`**: 待验证 (waiting on environment, split into endpoint / paid / other OS / external
  accounts) vs 待开发 (not implemented), plus known boundaries that are not defects.
- **`scripts/sanitize-check.sh`**: redaction gate for personal paths, private gateway domains, vendor
  internal ids, task ids, key shapes and cost figures. It runs as the final step of `tests/run-all.sh`.
- Token/cost figures removed from committed docs (they belong to whoever runs the gateway; the CLI
  prints the live `usage` instead).

## 0.10.1 - 2026-11-14

Verification transparency + two more zero-cost live probes.

- `docs/VERIFICATION.md` now ends with a **verification matrix**: every capability marked live / mock /
  not implemented, with what blocks the rest. "Implemented" and "proven against the vendor" are kept
  apart on purpose.
- New live probes: `/images/edits` reachability (multipart accepted, rejected on allowlist → 401, no
  charge) and `--param` passthrough (invalid value rejected by the gateway → 400, proving it arrives
  without creating a task).

## 0.10.0 - 2026-11-14

The whole A–C backlog: diagnostics, remix/extend, plumbing, Azure, retries, ledger.

- **Diagnostics**: `doctor --gaps` reports which capability kinds this endpoint can actually verify;
  `models --access` reads the key's allowlist out of a single rejected bogus POST (creates nothing).
- **Gateway extras**: `video --remix <id>` / `--extend <id> -s N`, `list --model M`; when a gateway's
  list route drops `model` (as LiteLLM does here) the CLI says so and points at `tasks`.
- **Local ledger**: `~/.local/state/media-gen/tasks.jsonl` (0600) records every create/wait/download;
  `media.py tasks [--status] [--limit] [--json]`.
- **Parallel wait**: `wait id1 id2 …` polls with a thread pool (max 8).
- **`--json`** on image / video / wait / list / tasks for agents and CI.
- **`--param k=v`** (repeatable) forwards provider-specific knobs into the body or `extra_body`, with
  bool/int coercion and inclusion in `--dry-run`.
- **Profile `--header` / `--query`**: fixed headers (e.g. `OpenAI-Organization`) and query params
  (e.g. Azure `api-version`).
- **Azure OpenAI protocol**: deployment-scoped paths, `api-key` header, `/audio/*` and `/images/*`;
  video is refused with an explicit message instead of hitting a wrong URL.
- **GET retries**: polling/download retry on 429/5xx and network errors (`MEDIA_RETRY`, default 2,
  capped at 5, backoff 0.5 s → 1 s). Paid POSTs are never retried.
- **Registry** grown to 24 rules: Kling, Luma, Runway, Pika, Sora, Veo, Imagen/Gemini-image, FLUX,
  Stability, Recraft/Ideogram/Kolors/CogView/Hunyuan-image, MiniMax T2A, CosyVoice/Sambert,
  Paraformer/SenseVoice, OpenAI transcription.
- Tests: 39 protocol tests (extras: list, remix/extend, params, headers/query, Azure, no-retry-on-POST)
  and CLI coverage for `--json`, `--param`, ledger, parallel wait, list, remix/extend, `doctor --gaps`.

## 0.9.2 - 2026-11-14

macOS verification sweep, plus two small correctness fixes.

- `download <id> out --last-frame f.png`: fetch the尾帧 for an existing task (0 cost); when the
  gateway returns `last_frame_url: null` it says so instead of failing.
- 403 `team not allowed to access model` now carries a hint: it is an allowlist problem, not a missing
  model — run `media.py models` or ask the gateway operator.
- `speech --dry-run` reports `kind: speech` (was `audio`, inconsistent with the registry kinds).
- `docs/VERIFICATION.md`: live matrix with the exact commands and token costs (t2v, i2v, status, wait,
  download, last-frame-absent, 5 zero-cost negative paths, gateway model inventory), plus the list of
  capabilities that remain mock-only and why.

## 0.9.1 - 2026-11-14

Platform-branch tests, and a real bug they caught.

- `tests/test_platform.py`: exercises the **Linux** `secret-tool` path against a shim binary on PATH
  (store/lookup/clear round-trip, per-account items, delete gate), the **Linux-without-keyring**
  degradation (0600 file / env still work, `store_key` explains the alternatives), and the **Windows**
  branch (no backend → clear error). Also asserts `MEDIA_CREDENTIAL_STORE=none` never invokes the store.
- Fixed `store_key()` crashing with `NameError: item` for the credential-store path (accounts refactor
  dropped the local variable; the file-store tests never reached it).
- Note: these are simulated branches on macOS — a native Linux run is still required for the keyring
  proof; see the answer in the project thread.

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
- Live verification: 4 s / 480p / 9:16 image-to-video through a LiteLLM gateway, file downloaded;
  text-to-video and the read-only paths were already covered.
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
