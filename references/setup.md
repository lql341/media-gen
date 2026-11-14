# Configuration and credential sources

## Where configuration lives

| Item | Location | Notes |
| --- | --- | --- |
| Base URL, default model | `~/.config/seedance/config.json` (`0600`, dir `0700`) | respects `XDG_CONFIG_HOME` |
| API key | OS credential store (default) | macOS Keychain / `secret-tool` |
| API key (opt-in) | same `config.json` as `api_key` | only with `--store file`; plaintext, 0600 |
| Nothing | environment variables | best for CI and ephemeral shells |

Service name in the credential store: `seedance-gateway`, account `default`.
Read it back manually if needed:

```bash
security find-generic-password -s seedance-gateway -w | python3 -c 'import json,sys; print(json.load(sys.stdin)["api_key"][-4:])'
secret-tool lookup service seedance-gateway      # Linux
```

## Resolution order

Key (`scripts/seedance_config.py get-key`):

1. `SEEDANCE_API_KEY`, then legacy `LEGACY_API_KEY`
2. OS credential store
3. `config.json` → `api_key` (only if the user chose `--store file`)
4. read-only import from `~/.pi/agent/auth.json` (`legacyprov.key`), `~/.codebuddy/models.json`,
   `~/.workbuddy/models.json` (first model whose `url` contains `example.com`)

Base URL (`get-base-url`): `SEEDANCE_BASE_URL` → legacy `LEGACY_BASE_URL` → `config.json`.

There is **no built-in default gateway**: `get-base-url` fails with a pointer to `setup.sh` until one
is configured. That is deliberate — the gateway belongs to whoever deploys the models, and guessing
one would ship someone's endpoint as if it were universal.

Model (`get-model`): `SEEDANCE_VIDEO_MODEL` → `config.json` → `doubao-seedance-2-5`.

`status` prints the source for each value and never prints a full key. `get-key` is the only
command that emits one, and it is meant for `seedance.sh` calling it, not for humans.

## Migration and rotation

```bash
scripts/setup.sh new --key-from-agent   # promote an existing Pi / CodeBuddy key into the store
scripts/setup.sh modify                 # replace the key or URL, keeps the other
scripts/setup.sh reset                  # delete the key, keep the URL
scripts/setup.sh reset --all            # delete key and URL
```

If the key lives in an agent's own file (source shows `只读导入` / "read-only import"), rotating the
gateway key means updating **that** file, or promoting the new key with `setup.sh modify`. An
environment variable beats everything, so a stale `export SEEDANCE_API_KEY=…` in a shell profile
will silently win over the credential store — check `status` before blaming the gateway.

## Non-interactive and CI

```bash
export SEEDANCE_API_KEY="$(cat "$SECRET_FILE")"
export SEEDANCE_BASE_URL="https://gw.example/v1"
bash scripts/setup.sh doctor          # read-only verification, no state written
```

No `config.json` is written in this mode. Do not bake keys into images, CI logs, or shell history;
inject them as environment variables from the CI secret store. There is no Windows credential-store
backend: use environment variables there.

## Multiple gateways or accounts

Not supported yet (single saved profile). Use env vars per process for a second gateway:

```bash
SEEDANCE_BASE_URL=https://other-gw/v1 SEEDANCE_API_KEY=... scripts/seedance.sh run -p "..."
```

## Security notes

- The CLI passes the `Authorization` header through `curl --config` on a file descriptor, so the key
  never appears in `ps` output or shell history.
- An interactive key prompt is hidden (`read -s`); pasted quotes and `export FOO=…` lines are
  rejected rather than stored.
- `seedance_config.py` never includes a key value in an exception message, and `status` masks
  everything except the last four characters.
