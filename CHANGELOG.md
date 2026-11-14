# Changelog

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
