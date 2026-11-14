# Configuration and credentials

## Layout

| Item | Location | Notes |
| --- | --- | --- |
| profiles (URL, protocol, default models) | `~/.config/media-gen/config.json` (`0600`, dir `0700`) | respects `XDG_CONFIG_HOME` |
| capability overrides | `~/.config/media-gen/registry.json` | merged ahead of the built-in registry |
| keys | OS credential store, item per profile | service `media-gen`, account `<profile>` |
| keys (opt-in) | `config.json` → `profiles.<name>.api_key` | only with `--store file`; plaintext 0600 |

## Resolution order

Profile: `--profile` → `MEDIA_PROFILE` → `config.json`'s `default` → the only profile if exactly
one exists. With no profiles at all, `MEDIA_BASE_URL` (+ optional `MEDIA_PROTOCOL`) is enough to
run — useful in CI and for one-off尝试.

Key: `MEDIA_API_KEY_<PROFILE>` → `MEDIA_API_KEY` → credential store for that profile → legacy
`seedance-gateway` item (only for a profile named `legacy`) → `config.json` inline key → read-only
import from `~/.pi/agent/auth.json` / `~/.codebuddy/models.json`.

Base URL: `MEDIA_BASE_URL` (or legacy `SEEDANCE_BASE_URL`) overrides the profile's URL.

Model: `--model` → `MEDIA_IMAGE_MODEL` / `MEDIA_VIDEO_MODEL` → profile `default_models.<kind>`.
There is **no default endpoint and no default model**: both are deployment decisions.

## Lifecycle

| Need | Command |
| --- | --- |
| add or replace an endpoint | `setup.sh add <name> --protocol <p> --base-url <URL>` |
| change only the URL | `setup.sh set-url <name> --base-url <URL>` |
| rotate only the key | `printf '%s' "$KEY" \| setup.sh set-key <name>` |
| change protocol (with template/hook) | `setup.sh set-protocol <name> --protocol <p> [--custom-file F \| --command-json J]` |
| rename a profile | `setup.sh rename <old> <new>` (moves its credential entry) |
| interactive edit | `setup.sh modify <name>` |
| inspect one | `setup.sh show <name>` (masked) |
| copy configuration to another machine | `setup.sh export > cfg.json` · `setup.sh import cfg.json` (no secrets) |
| delete one / all | `setup.sh rm <name> [--keep-key]` · `setup.sh rm --all` |

`add` on an existing name updates it; omitting the key keeps the stored one.

## Non-official endpoints

`protocol=custom` needs `--custom-file` (copied to `~/.config/media-gen/custom/<name>.json`), and
`protocol=command` needs `--command-json`/`--command-file` with the hook table. Their base URL may be
an identifier (`unused://inhouse`) for `command`. See `custom-endpoints.md` for the template format,
placeholders, auth modes and the hook contract.

## Commands

```bash
scripts/setup.sh add <name> --protocol openai --base-url https://host/v1 \
    [--key-stdin | --key-file PATH] [--store auto|file] \
    [--default-image M] [--default-video M] [--set-default]
scripts/setup.sh use <name>          # make it the default profile
scripts/setup.sh list                # * marks the default
scripts/setup.sh rm <name> [--keep-key]
scripts/setup.sh status [--profile P]
scripts/setup.sh migrate [--name legacy]   # from ~/.config/seedance + old Keychain item
```

`status` never prints a full key (last four characters only). The only command that emits a key is
`media_config.py get-key`, used internally by the CLI.

## Rotation

- Store-backed key: `scripts/setup.sh add <name> --protocol … --base-url …` again with the new key.
- Env-backed: rotate the variable; it always wins over the store, so a stale `export` in a shell
  profile looks like "the old key still works".
- Confirm with `scripts/setup.sh status` (source column) and `scripts/setup.sh doctor`.

## CI

```bash
export MEDIA_API_KEY="$SECRET"
export MEDIA_BASE_URL="https://gw.example/v1"
export MEDIA_PROTOCOL="openai"          # omit if a profile already points at this URL
python3 scripts/media.py models
```

Nothing is written to disk in this mode. There is no Windows credential-store backend: use
environment variables there.

## Interactive wizard and the credential-store switch

`scripts/setup.sh` (macOS/Linux) and `scripts/setup.ps1` (Windows) both run
`scripts/wizard.py`; see `interactive.md` for the flows and `gui-clients.md` for MCP clients.

| `MEDIA_CREDENTIAL_STORE` | Behaviour |
| --- | --- |
| `auto` (default) | OS credential store when available |
| `file` | never touch the keyring; `0600` config file only |
| `none` | never read or write the keyring; keys from `MEDIA_API_KEY[_<PROFILE>]` |

`MEDIA_NO_KEYCHAIN=1` is an alias for `none`. Lookups are cached per process, so one run of
`status`/`list`/`doctor` performs at most one store read per profile. `MEDIA_DEBUG_STORE=1` prints
each access (`store: read media-gen/litellm via macOS Keychain`) so you can audit it. The test suite
runs with `none` and asserts zero keyring operations.

## Reuse an existing store item instead of copying it

A profile can point at any existing credential-store item, so a secret that already lives in the
Keychain (from an earlier install, another tool, or a `seedance-gateway` legacy item) is used in
place — nothing is copied, nothing is written:

```bash
scripts/setup.sh add litellm --protocol openai --base-url https://gw/v1 \
    --credential-ref seedance-gateway:default
scripts/setup.sh set-credential-ref litellm --ref ""     # forget it, go back to media-gen/litellm
```

Resolution order for the key becomes: env → `credential_ref` → `media-gen/<profile>` → legacy
`seedance-gateway` (only for a profile literally named `legacy`) → inline 0600 key → agent auth
import. `audit` shows which item each profile uses and whether it exists, **without decrypting it**
(it uses `security find-generic-password` without `-w`).

## Deleting secrets is opt-in (default: never)

`setup.sh rm` removes the **configuration**, not your secret. Deleting the credential-store item
requires an explicit gate:

```bash
MEDIA_ALLOW_CREDENTIAL_DELETE=1 scripts/setup.sh rm <name>
# or do it yourself:
security delete-generic-password -s media-gen -a <name>      # macOS
secret-tool clear service media-gen account <name>            # Linux
```

`scripts/setup.sh audit` is read-only and prints exactly which store items the tool could touch, the
exact command for each, whether the gate is set, and whether the legacy `seedance-gateway` item
exists (it is never deleted by this tool). No command ever deletes by service name alone — the
account is always part of the query, so one profile can never remove another.

## Security notes

- The CLI sends `Authorization` from Python (never through argv or shell history), and only to the
  configured base URL — artifact downloads from foreign hosts are fetched without credentials.
- `media_config.py` never puts a key value in an exception message; pasted `export …` lines and
  whole `Authorization:` headers are rejected rather than stored.
- `--store file` exists for machines without a keyring; it prints a warning and stays `0600`.
- Deleting a secret is refused unless `MEDIA_ALLOW_CREDENTIAL_DELETE=1`; the CLI prints the exact
  command instead of running it. The test suite asserts that it performs no store deletes at all.
- No command ever prompts for the keyring interactively: `security`/`secret-tool` are called
  non-interactively and failures degrade to "no key" rather than a modal dialog.
