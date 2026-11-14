# Migrating from `seedance` (0.1.0)

## What changed

| Before (seedance 0.1.0) | Now (media-gen) |
| --- | --- |
| one gateway, hard-coded default URL | named profiles; **no default URL** |
| `SEEDANCE_API_KEY` / `LEGACY_API_KEY` | `MEDIA_API_KEY` (old names still read) |
| Keychain item `seedance-gateway` | item `media-gen` per profile (old item read as `legacy`) |
| `~/.config/seedance/config.json` | `~/.config/media-gen/config.json` (old file read as `legacy`) |
| `scripts/seedance.sh run/gen/status/wait/download` | `scripts/media.py video …` (shim kept) |
| video only | image + video, four protocols |

## Steps

```bash
git pull                     # or re-clone; the skill is the repository
scripts/setup.sh migrate     # creates profile "legacy" from the old config + old Keychain item
scripts/setup.sh list
scripts/setup.sh status --profile legacy
scripts/setup.sh add litellm --protocol openai --base-url https://<your-gateway>/v1 \
    --default-video doubao-seedance-2-5 --set-default
scripts/setup.sh doctor --profile litellm
scripts/setup.sh rm legacy --keep-key    # once the new profile works
```

Then reinstall the skill under its new name and remove the old one:

```bash
bash scripts/install.sh --pi          # ~/.agents/skills/media-gen
bash ~/Downloads/agent/skills/seedance/scripts/install.sh --uninstall 2>/dev/null || true
```

## Command mapping

| Old | New |
| --- | --- |
| `seedance.sh run -p … -s 5 -o out.mp4` | `media.py video -p … -s 5 -o out.mp4` |
| `seedance.sh gen -p …` (prints id) | `media.py video -p … --create-only` |
| `seedance.sh status <id>` | `media.py status <id>` |
| `seedance.sh wait <id>` | `media.py wait <id>` |
| `seedance.sh download <id> out.mp4` | `media.py download <id> out.mp4` |
| `seedance.sh gen -p … --dry-run` | `media.py video -p … --dry-run` |

`scripts/seedance.sh` still exists as a shim so old habits keep working; it prints a deprecation
notice and forwards to `media.py video`.
