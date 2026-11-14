# First use: what to prepare

This skill is not bound to any gateway. First use needs **one endpoint** and **one key** for it,
plus the protocol that endpoint speaks. Ask for exactly that, one item at a time.

| Item | Example | Where it comes from |
| --- | --- | --- |
| base URL | `https://gw.example/v1` | whoever runs the endpoint (LiteLLM gateway, cloud provider) |
| protocol | `openai` / `ark` / `dashscope` / `minimax` | which wire format that endpoint speaks |
| API key | `sk-…` | the endpoint's console; keep it out of chat |

Protocol choice:

- `openai` — any OpenAI-compatible endpoint, including a LiteLLM proxy that fronts Seedance/Wan/
  Hailuo deployments. `/images/generations` and `/videos`.
- `ark` — Volcengine Ark native (`https://ark.cn-beijing.volces.com/api/v3`).
- `dashscope` — Alibaba Cloud Bailian native (`https://dashscope.aliyuncs.com/api/v1`).
- `minimax` — MiniMax native (`https://api.minimaxi.com/v1`, international `api.minimax.io`).

## Check before asking

```bash
scripts/setup.sh list
scripts/setup.sh status            # masked key, source, protocol
scripts/setup.sh doctor            # read-only: GET /models + which media models are visible
```

If a profile already works, reuse it. Do not migrate or reconfigure without being asked.

## What the user runs (in their own terminal)

```bash
bash "<skill-dir>/scripts/setup.sh" add litellm --protocol openai --base-url https://gw.example/v1
bash "<skill-dir>/scripts/setup.sh" doctor --profile litellm
```

The key prompt is hidden. Non-interactive equivalents:

```bash
printf '%s' "$KEY" | bash "<skill-dir>/scripts/setup.sh" add ark --protocol ark \
  --base-url https://ark.cn-beijing.volces.com/api/v3 --key-stdin
MEDIA_API_KEY="$KEY" MEDIA_BASE_URL=https://gw.example/v1 python3 "<skill-dir>/scripts/media.py" models
bash "<skill-dir>/scripts/setup.sh" migrate        # from an existing seedance config
```

## Rules for the agent

1. One question at a time; never ask for the key or a screenshot of it.
2. Never launch the interactive `add` from a tool call (it needs a TTY) — print the command.
3. Never write a key into `SKILL.md`, `references/`, committed `.env`, or a command line (argv is
   world-readable via `ps`).
4. Say which profile and which protocol are in use; "the gateway is down" and "this key is not
   allowed to use this model" look different and need different answers.
5. After the user acts, run `setup.sh status` (masked) and `media.py models` before generating.
