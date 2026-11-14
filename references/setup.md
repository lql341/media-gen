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

## Security notes

- The CLI sends `Authorization` from Python (never through argv or shell history), and only to the
  configured base URL — artifact downloads from foreign hosts are fetched without credentials.
- `media_config.py` never puts a key value in an exception message; pasted `export …` lines and
  whole `Authorization:` headers are rejected rather than stored.
- `--store file` exists for machines without a keyring; it prints a warning and stays `0600`.
