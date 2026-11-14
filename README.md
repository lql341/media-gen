# seedance — video generation skill for coding agents

An [Agent Skill](https://agentskills.io/specification) that lets a coding agent generate short
videos with **Seedance** models (`doubao-seedance-2-5`, `doubao-seedance-2-0-260128`) through a
LiteLLM gateway's Videos route.

Works with any agent that can read a `SKILL.md` and run a shell script — Pi, Claude Code, Codex.
The script alone is a complete CLI, so the skill is optional convenience.

```text
scripts/seedance.sh run -p "rainy neon street, slow push-in" -s 5 --ratio 16:9 --resolution 720p -o out.mp4
```

## Why a skill instead of an extension or an MCP server

| Option | What the model sees | Clients | Cost to maintain |
| --- | --- | --- | --- |
| Bundled script only | nothing — you have to name it | any shell | lowest |
| **Agent Skill (this repo)** | one line in the system prompt, full text on demand | Pi, Claude Code (same spec) | one Markdown file |
| Agent extension / custom tool | a resident tool definition | one client | TypeScript following that client's API |
| MCP server | a resident tool | any MCP client | extra process + protocol |

Generation is slow (1.5–5 min) and billed per video token, so the hard part is **behaviour**:
confirm duration before spending, never retry a `429`, switch to `--ratio` when `--size` is
rejected. That belongs in instructions, not in a tool schema.

## Install

```bash
git clone https://github.com/<you>/seedance.git ~/src/seedance
bash ~/src/seedance/scripts/install.sh            # symlink into ~/.agents/skills (Pi / Claude Code)
bash ~/src/seedance/scripts/install.sh --copy     # copy instead of symlink
bash ~/src/seedance/scripts/install.sh --uninstall
```

`--pi`, `--claude`, `--codex` force a target directory. Reopen the agent (or `/reload`), then:

```text
/skill:seedance generate a 5 second clip: rainy neon street, slow push-in
```

## Configure

Two settings, both local, neither of which should ever appear in chat. **The base URL has no
built-in default** — a fresh install refuses to run until you configure one, because the gateway
belongs to whoever deploys it:

```bash
scripts/setup.sh new        # asks for the gateway base URL (required), then the API key (hidden input)
scripts/setup.sh status     # which URL/key is in effect, and from where (key masked)
scripts/setup.sh doctor     # read-only: GET /models + are both video models listed
scripts/setup.sh modify     # rotate the key or change the URL
scripts/setup.sh reset [--all]
```

Resolution order, first hit wins:

| Value | Order |
| --- | --- |
| key | `SEEDANCE_API_KEY` → OS credential store (Keychain / `secret-tool`) → `~/.config/seedance/config.json` (`--store file`, plaintext 0600) → read-only import from `~/.pi/agent/auth.json` / `~/.codebuddy/models.json` |
| base URL | `SEEDANCE_BASE_URL` → `config.json` → **required, no built-in default** |
| model | `SEEDANCE_VIDEO_MODEL` → `config.json` → `doubao-seedance-2-5` |

The key is passed to `curl` through `--config` on a file descriptor, so it never shows up in `ps`
output or shell history. `status` prints only the last four characters. Details and CI recipes:
[`references/setup.md`](references/setup.md).

## Use

| Goal | Command |
| --- | --- |
| create → poll → download | `scripts/seedance.sh run -p "<prompt>" [opts] -o out.mp4` |
| create only | `scripts/seedance.sh gen -p "<prompt>" [opts]` → `video_...` |
| status / wait | `scripts/seedance.sh status <id>` · `wait <id> [--timeout 1800]` |
| download | `scripts/seedance.sh download <id> out.mp4` |
| show the request, spend nothing | `gen -p "<prompt>" [opts] --dry-run` |

Options: `--model`, `--seconds` (`4..30` or `-1`), `--size 1280x720`, `--ratio 16:9|9:16|1:1`,
`--resolution 480p|720p|1080p`, `--image <first frame.jpg>`.

These models are **video-only deployments**. `/chat/completions` answers
`429 No deployments available for selected model`, so they cannot be selected with `/model` and
must not be added to any client's `models.json`. Route shape and measured payloads:
[`references/routing.md`](references/routing.md).

## Cost

Billed per video token, so cost follows duration and output resolution. This repo carries no rate
table on purpose: prices change per gateway, and a stale number is worse than none — ask the gateway
operator for the current price list.

Practical rule the skill enforces: draft at the lowest resolution and shortest duration that answers
the question, then render the keeper at the resolution you need. Generation takes minutes, not
seconds, so `--dry-run` is the cheap way to check the request.

## Layout

```text
SKILL.md                    routing, money/time rules, command table, failure table
references/first-use.md     what to prepare, where to get it, what the user runs
references/setup.md         credential sources, precedence, rotation, CI, security notes
references/routing.md       Videos route shape, request fields, completed-task payload
references/troubleshooting.md  full error table
scripts/seedance.sh         CLI: gen / status / wait / download / run
scripts/seedance_config.py  config + credential resolution, status, doctor
scripts/setup.sh            configuration panel (new / modify / status / doctor / reset)
scripts/install.sh          install this skill into an agent's skills directory
tests/                      offline tests: no network calls, no paid requests
```

## Tests

```bash
bash tests/test-config.sh   # precedence, 0600 perms, masking, reset, doctor failure paths
bash tests/test-cli.sh      # --help, --dry-run, argument validation, no key leakage
```

Both run against a temporary `HOME`, never touch your real configuration, and never create a video
task.

There is deliberately **no CI workflow**: the repository is private, GitHub Actions minutes are not
free, and both suites are offline and fast. Run them before tagging a release.

## License

MIT — see [LICENSE](LICENSE).
