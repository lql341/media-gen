# Interactive setup (macOS · Linux · Windows PowerShell)

All interactive UX lives in `scripts/wizard.py` (stdlib only). The shell and PowerShell starters
only locate Python, so the three platforms behave identically:

| Platform | Entry point |
| --- | --- |
| macOS / Linux | `scripts/setup.sh` |
| Windows (PowerShell 5+ / 7) | `.\scripts\setup.ps1` |
| anywhere, directly | `python3 scripts/wizard.py` |

Windows note: `py -3` is used when `python3` is missing; override with `$env:MEDIA_PYTHON`.

## Menu

```
1) 新增 / 更新端点（交互）
2) 生成 custom 模板（非官方接口，逐项问答）
3) 修改已有配置档（地址 / 密钥 / 协议 / 默认模型 / 改名）
4) 删除配置档
5) 列出配置档
6) 自检（只读）
7) 迁移旧的 seedance 配置
8) 查看图形客户端的 MCP 注册片段
9) 退出
```

Add flow: profile name → protocol (numbered list with one-line descriptions) → base URL (per-protocol
default pre-filled, still asked) → default image model → default video model → API key (hidden) →
set as default? → run `doctor`.

Custom flow asks only what the template needs — request method/path, response mode (`b64`/`url`) and
dotted path, task id path, status field, done/failed values, video URL / duration / size paths, fetch
mode — then prints the JSON for review before saving.

## Keys and the credential store

- Hidden input via `getpass`; when stdin is not a TTY (CI, piped answers) it falls back to a visible
  read so automation still works.
- With no system credential store (Windows, headless Linux) the wizard offers: write to the `0600`
  config file, or skip and use `MEDIA_API_KEY`.

### `MEDIA_CREDENTIAL_STORE` — stop touching the keyring

| Value | Behaviour |
| --- | --- |
| `auto` (default) | use macOS Keychain / `secret-tool` when available |
| `file` | never touch the keyring; only the `0600` config file |
| `none` | never read or write the keyring; keys must come from environment variables |

`MEDIA_NO_KEYCHAIN=1` is an alias for `none`. Lookups are also **cached per process** (one Keychain
call per profile per run, not one per prompt), and `MEDIA_DEBUG_STORE=1` prints every store access to
stderr so you can see exactly what happened:

```
$ MEDIA_DEBUG_STORE=1 MEDIA_CREDENTIAL_STORE=none scripts/setup.sh list
store: skip media-gen/litellm（MEDIA_CREDENTIAL_STORE=none）
```

The test suites run with `MEDIA_CREDENTIAL_STORE=none`, so `bash tests/run-all.sh` performs zero
keyring operations — that is asserted, not assumed.

## Non-interactive equivalents

Every wizard step has a flag form, so scripts and CI never need the TUI:

```bash
scripts/setup.sh add litellm --protocol openai --base-url https://gw/v1 \
    --default-video doubao-seedance-2-5 --set-default --key-stdin < key.txt
scripts/setup.sh set-url litellm --base-url https://gw2/v1
scripts/setup.sh rename litellm primary
scripts/setup.sh rm --all
```

On Windows the same flags work through `setup.ps1`:

```powershell
Get-Content key.txt | .\scripts\setup.ps1 add litellm --protocol openai --base-url https://gw/v1 --key-stdin
.\scripts\setup.ps1 doctor
```
