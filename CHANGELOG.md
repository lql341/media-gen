# Changelog

## 0.1.0 - 2026-11-14

Initial release, extracted from the `arch-config` monorepo where the script and skill first lived.

- `scripts/seedance.sh`: `gen` / `status` / `wait` / `download` / `run` over a LiteLLM gateway's
  Videos route (`POST /videos`, `GET /videos/<id>`, `GET /videos/<id>/content`), with `--dry-run`,
  `--ratio`/`--resolution` fallbacks when `--size` is rejected, and a bounded `wait` poller.
- `scripts/seedance_config.py`: base URL / API key / default model resolution
  (environment → OS credential store → `~/.config/seedance/config.json` 0600 → read-only import
  from `~/.pi/agent/auth.json` or CodeBuddy `models.json`), `status` with masking, `doctor` that
  verifies `GET /models` and both video model IDs, and `reset`.
- `scripts/setup.sh`: `new` / `modify` / `status` / `doctor` / `reset`; hidden key prompt, refuses to
  run without a TTY, supports `--key-from-agent` and `--key-stdin` for non-interactive use.
- `scripts/install.sh`: symlink (default) or copy into `~/.agents/skills`, `~/.claude/skills`,
  `~/.codex/skills`.
- `SKILL.md` plus `references/first-use.md`, `setup.md`, `routing.md`, `troubleshooting.md`.
- Credentials never enter `argv`: the `Authorization` header is passed to `curl` through
  `--config` on a file descriptor, so it is absent from `ps` output and shell history.
- Offline test suites: `tests/test-config.sh`, `tests/test-cli.sh`.
- No CI workflow: private repository, tests run locally before tagging.
