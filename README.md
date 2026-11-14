# media-gen — image and video generation skill for coding agents

An [Agent Skill](https://agentskills.io/specification) that generates **images and videos** through
any endpoint you configure: an OpenAI-compatible gateway (LiteLLM, OpenAI), or a provider's native
API (Volcengine Ark, Alibaba DashScope/Wan, MiniMax). No vendor and no gateway is hard-coded.

```bash
scripts/setup.sh add litellm --protocol openai --base-url https://gw.example/v1
scripts/media.py models
scripts/media.py image -p "a red apple on a white table" --model gpt-image-1 -o apple.png
scripts/media.py video -p "rainy neon street, slow push-in" --model doubao-seedance-2-5 -s 5 -o street.mp4
```

## Two independent decisions

| Decision | Made by | Stored in |
| --- | --- | --- |
| **Where** the request goes (URL, key, wire protocol) | a named profile | `~/.config/media-gen/config.json` + OS credential store |
| **What** the model is and accepts (image/video, duration, size syntax) | the capability registry | `scripts/registry.json` + `~/.config/media-gen/registry.json` |

That split is what makes it generic: the same `wan2.5-t2v` model is reached through a gateway
(`protocol=openai`) or through DashScope directly (`protocol=dashscope`), and the CLI normalises
`--size`, `-s`, `--ratio`/`--resolution` into whatever that protocol wants.

## Protocols

| Protocol | Endpoint style | Image | Video | Notes |
| --- | --- | --- | --- | --- |
| `openai` | OpenAI-compatible / LiteLLM | `/images/generations` | `/videos` + poll | the safest choice for gateways |
| `ark` | `https://ark.cn-beijing.volces.com/api/v3` | `/images/generations` | `/contents/generations/tasks` | Seedance video, Seedream image |
| `dashscope` | `https://dashscope.aliyuncs.com/api/v1` | async task API | async task API | Wan t2i/t2v/i2v, `1024*1024` sizes |
| `minimax` | `https://api.minimaxi.com/v1` | `/image_generation` | `/video_generation` + 2-hop fetch | Hailuo, enum durations |
| `custom` | anything REST | template | template | describe an in-house JSON shape in a file |
| `command` | anything at all | hook script | hook script | script exchanges JSON on stdin/stdout |

Verification status per protocol is stated honestly in
[`references/providers.md`](references/providers.md): live vs. validated against a local mock of the
documented wire format.

## Install

```bash
git clone https://github.com/lql341/media-gen.git ~/src/media-gen
bash ~/src/media-gen/scripts/install.sh              # symlink into ~/.agents/skills
bash ~/src/media-gen/scripts/install.sh --codex      # or --claude / --copy / --uninstall
```

Reopen the agent (or `/reload`), then `/skill:media-gen …` or just ask for an image/video.

## Configure

Interactive wizard (same on macOS, Linux and Windows PowerShell):

```bash
scripts/setup.sh          # macOS / Linux
.\scripts\setup.ps1       # Windows PowerShell
```

Or drive it with flags:

```bash
# add / update an endpoint
scripts/setup.sh add <name> --protocol <openai|ark|dashscope|minimax|custom|command> \
    --base-url <URL> [--key-stdin | --key-file PATH] \
    [--default-image M] [--default-video M] [--set-default]
# non-official endpoints
scripts/setup.sh add inhouse --protocol custom  --custom-file ./inhouse.json  --base-url https://…/api
scripts/setup.sh add weird   --protocol command --command-json '{"create":"~/bin/x create","status":"…","fetch":"…"}'

# lifecycle
scripts/setup.sh modify <name>            # interactive: URL / key / protocol / default models
scripts/setup.sh set-url <name> --base-url <URL>
printf '%s' "$KEY" | scripts/setup.sh set-key <name>
scripts/setup.sh set-protocol <name> --protocol <p> [--custom-file F | --command-json J]
scripts/setup.sh rename <old> <new>
scripts/setup.sh rm <name> [--keep-key]   # or: rm --all
scripts/setup.sh export | import <file>   # configuration only, never secrets

# verify
scripts/setup.sh list | show <name> | status [--profile P] | doctor [--profile P]
scripts/setup.sh migrate                  # import an existing seedance config/credential
```

Key resolution: `MEDIA_API_KEY_<PROFILE>` → `MEDIA_API_KEY` → OS credential store → inline key
(`--store file`, 0600) → read-only import from an agent's auth file. Keys never enter argv, shell
history, logs, or the repository. There is **no default endpoint and no default model**.

Profiles can carry several accounts (same endpoint, different keys/workspaces) selected per process
with `<name>@<alias>`, `--account`, or `MEDIA_ACCOUNT`; a named account never falls back to the
default account's key. See `references/setup.md#multiple-accounts-and-concurrent-sessions`.

The keyring is only touched when it is consulted: `MEDIA_CREDENTIAL_STORE=file|none` keeps it out of
the loop, lookups are cached per process, and `MEDIA_DEBUG_STORE=1` prints each access. The test
suite runs with `none` and asserts zero keyring operations.

## Use

| Goal | Command |
| --- | --- |
| discover | `media.py models [--kind image|video] [--json]` |
| pick an account | `media.py --profile <name>@<alias> …` or `--account <alias>` / `MEDIA_ACCOUNT` |
| image | `media.py image -p "<prompt>" --model M [--size 1024x1024] [-n N] [--image ref.png --mask m.png] [-o out.png]` (batch → `out-1.png`, …) |
| speech | `media.py speech -t "<text>" --model tts-1 [--voice alloy] [--format mp3] [-o out.mp3]` |
| transcribe | `media.py transcribe -f audio.mp3 --model whisper-1 [--language zh] [-o out.txt]` |
| video | `media.py video -p "<prompt>" --model M [-s 6] [--ratio 16:9] [--resolution 720p] [--image first.png] [--last-frame f.png] [-o out.mp4]` |
| either | `media.py run --model M …` (kind from the registry) |
| tasks | `media.py status <id>` · `wait <id>` · `download <id> out.mp4` · `--create-only` |
| no spend | add `--dry-run` |

## Layout

```text
SKILL.md                       routing by intent, money discipline, failure table
references/first-use.md        what to prepare, what the user runs
references/setup.md            profiles, precedence, rotation, CI, security
references/routing-image.md    image routes per protocol
references/routing-video.md    video routes per protocol (poll + fetch, image-to-video, last frame)
references/audio.md            speech synthesis + transcription
CAPABILITIES.md                the full capability matrix (operations × protocols × verification)
docs/VERIFICATION.md           what was executed against a real gateway, with commands and costs
references/providers.md        per-provider quirks + verification status
references/custom-endpoints.md  custom templates + command hooks for in-house APIs
references/interactive.md      wizard flows, cross-platform entry points, credential-store switch
references/gui-clients.md      MCP server for WorkBuddy / DSH / Claude Desktop / CodeBuddy
scripts/wizard.py              interactive setup (stdlib, getpass, Windows-safe)
scripts/mcp_server.py          stdio MCP server: media_profiles/models/image/video/task
scripts/setup.ps1              PowerShell entry point
references/troubleshooting.md  full error table
scripts/media.py               CLI: models / image / video / run / status / wait / download / doctor
scripts/media_config.py        profiles + credentials (status/add/use/rm/migrate)
scripts/registry.py|.json      capability registry and normalisation
scripts/protocols/             openai · ark · dashscope · minimax
scripts/setup.sh               configuration panel
scripts/install.sh             install into an agent's skills directory
scripts/seedance.sh            deprecated shim → media.py video
tests/                         offline suites incl. a scripted mock server
MIGRATION.md                   moving from the seedance-only skill
```

## Tests

```bash
bash tests/run-all.sh
```

Six suites, all offline: registry unit tests, protocol adapters against a scripted mock server
(create → poll → download, request bodies inspected), configuration/credential precedence in a
temp `HOME`, the interactive wizard (piped answers), the MCP server over stdio, and CLI end-to-end
through the mock. No network, no account, no spend, **and no keyring access**
(`MEDIA_CREDENTIAL_STORE=none`, asserted). There is no CI workflow on purpose.

## License

MIT — see [LICENSE](LICENSE).
