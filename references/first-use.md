# First use: what to prepare and where to get it

Introduce this before asking for anything: a Seedance skill needs **two** pieces of local
configuration, and neither may travel through chat.

| What | Example | Where it comes from |
| --- | --- | --- |
| Gateway base URL | `https://gw.example.com/v1` | whoever operates the LiteLLM gateway (for the gateway: the model-service console) |
| API key | `sk-…` (a virtual key) | the same console, as a key scoped to the LLM routes |

The gateway must implement **OpenAI Videos style routes** (`POST /videos`,
`GET /videos/<id>`, `GET /videos/<id>/content`). Any LiteLLM instance with a Seedance deployment
does; a plain OpenAI-compatible chat endpoint does not.

## Check before asking

```bash
scripts/setup.sh status     # what is already configured, and from where
scripts/setup.sh doctor     # read-only: GET /models + are both video models listed
```

If `status` already reports a key source, reuse it. Do not ask the user again, and do not migrate
credentials without being asked.

## What the user runs (their own terminal)

The agent must substitute the resolved absolute path for `<skill-dir>` and keep the quotes:

```bash
bash "<skill-dir>/scripts/setup.sh" new       # interactive: URL + hidden key prompt
bash "<skill-dir>/scripts/setup.sh" doctor    # verify
```

Non-interactive equivalents (CI, dotfiles, first-boot scripts):

```bash
SEEDANCE_API_KEY="$KEY" bash "<skill-dir>/scripts/setup.sh" new --no-verify --base-url https://gw.example/v1
bash "<skill-dir>/scripts/setup.sh" new --key-from-agent    # reuse ~/.pi/agent/auth.json (or CodeBuddy's models.json)
printf '%s' "$KEY" | bash "<skill-dir>/scripts/setup.sh" new --key-stdin --store auto
```

## Rules for the agent

1. Ask for **one** missing thing at a time: base URL, then key. Never both in one message.
2. Never request the key, a key screenshot, or the contents of `auth.json` in chat. Give the
   command; the value stays in the user's terminal.
3. Do not launch a hidden interactive prompt from a tool call — `setup.sh new` needs a real TTY.
4. Never write a key into `SKILL.md`, `references/`, `.env` committed to git, or a shell command
   line: argv is visible to other local users via `ps`.
5. After the user acts, re-run `scripts/setup.sh status` (masked) or `doctor` before generating.
6. Say which source is in use: environment variable, Keychain, `config.json`, or the read-only
   agent-auth import. They behave differently when the user later rotates a key.

## Example introduction

> Generating video needs two local settings: the gateway base URL (the LiteLLM endpoint that serves
> the Seedance models) and an API key for it. Please run this in your terminal and paste neither
> into chat:
>
> `bash "<skill-dir>/scripts/setup.sh" new`
>
> It stores the key in the macOS Keychain (or `secret-tool` on Linux). Afterwards
> `scripts/setup.sh status` shows which source is active, with only the last four characters of the
> key visible. Generating is billed per video token, so tell me duration and resolution before the
> first run.
