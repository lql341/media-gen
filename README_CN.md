# seedance — 给编码 agent 用的视频生成技能

一个 [Agent Skill](https://agentskills.io/specification)：让 agent 通过 LiteLLM 网关的 Videos
路由调用 **Seedance** 视频模型（`doubao-seedance-2-5`、`doubao-seedance-2-0-260128`）。

Pi、Claude Code、Codex 都能用——只要能读 `SKILL.md` 并执行 shell 脚本。脚本本身就是完整 CLI，
技能只是让它“知道什么时候用、怎么花得值”。

```text
scripts/seedance.sh run -p "雨夜霓虹街道，缓慢推镜" -s 5 --ratio 16:9 --resolution 720p -o out.mp4
```

## 为什么是技能，不是扩展 / MCP server

| 方案 | 模型看到的 | 客户端 | 维护 |
| --- | --- | --- | --- |
| 只有脚本 | 什么都没有，靠你点名 | 任何 shell | 最低 |
| **技能（本仓库）** | 系统提示里一行，命中才读全文 | Pi、Claude Code（同一套规范） | 一个 Markdown |
| 客户端扩展 / 自定义 tool | 常驻一个工具定义 | 只有那一个 | 跟着客户端 API 的 TypeScript |
| MCP server | 常驻一个工具 | 任何 MCP 客户端 | 多一个进程 + 协议层 |

生成慢（1.5–5 分钟）且按视频 token 计费，真正要管的是**行为**：先确认时长再花钱、`429` 不重试、
`--size` 被拒就换 `--ratio`。这些属于指令，塞不进工具 schema。

## 安装

```bash
git clone https://github.com/<you>/seedance.git ~/src/seedance
bash ~/src/seedance/scripts/install.sh            # 符号链接到 ~/.agents/skills
bash ~/src/seedance/scripts/install.sh --copy     # 复制而不是链接
bash ~/src/seedance/scripts/install.sh --uninstall
```

`--pi` / `--claude` / `--codex` 可强制目标目录。重开 agent（或 `/reload`）后：

```text
/skill:seedance 生成一个 5 秒的视频：雨夜霓虹街道，缓慢推镜
```

## 配置

只有两项，都在本机，都不该进聊天。**网关地址没有内置默认值**——网关归部署方所有，新机器必须先配，
否则脚本直接拒绝运行：

```bash
scripts/setup.sh new        # 先问网关地址（必填），再问 API Key（输入不回显）
scripts/setup.sh status     # 实际生效的地址/密钥来源（密钥脱敏）
scripts/setup.sh doctor     # 只读：GET /models + 两个视频模型是否在列表
scripts/setup.sh modify     # 换密钥或换地址
scripts/setup.sh reset [--all]
```

解析顺序，先命中者胜：

| 值 | 顺序 |
| --- | --- |
| 密钥 | `SEEDANCE_API_KEY` → 系统凭据库（Keychain / `secret-tool`）→ `~/.config/seedance/config.json`（`--store file`，明文 0600）→ 只读导入 `~/.pi/agent/auth.json` / `~/.codebuddy/models.json` |
| 地址 | `SEEDANCE_BASE_URL` → `config.json` → **必填，无内置默认值** |
| 模型 | `SEEDANCE_VIDEO_MODEL` → `config.json` → `doubao-seedance-2-5` |

密钥通过 `curl --config` 走文件描述符传给 curl，不会出现在 `ps` 或 shell 历史里；`status` 只显示
后四位。细节与 CI 用法见 [`references/setup.md`](references/setup.md)，首次配置话术见
[`references/first-use.md`](references/first-use.md)。

## 使用

| 目的 | 命令 |
| --- | --- |
| 建任务 → 轮询 → 下载 | `scripts/seedance.sh run -p "<提示词>" [参数] -o out.mp4` |
| 只建任务 | `scripts/seedance.sh gen -p "<提示词>" [参数]` → `video_...` |
| 查状态 / 等待 | `scripts/seedance.sh status <id>` · `wait <id> [--timeout 1800]` |
| 下载 | `scripts/seedance.sh download <id> out.mp4` |
| 只看请求体，不花钱 | `gen -p "<提示词>" [参数] --dry-run` |

参数：`--model`、`--seconds`（`4..30` 或 `-1`）、`--size 1280x720`、
`--ratio 16:9|9:16|1:1`、`--resolution 480p|720p|1080p`、`--image <首帧图>`。

这两个模型是**只有 video deployment** 的模型：`/chat/completions` 会返回
`429 No deployments available for selected model`，所以既不能在 `/model` 里选，也不能写进任何
客户端的 `models.json`。路由形态与实测 payload 见 [`references/routing.md`](references/routing.md)。

## 成本

按视频 token 计费，成本随时长与输出分辨率变化。本仓库**不附带价目表**：价格随网关而异，
写死一个过期数字比不写更糟——向网关运营方要当前的价目。

技能强制的工作方式：先用最低分辨率 + 最短时长出草稿，确认构图后再用真正需要的分辨率出成品；
生成是分钟级而不是秒级，所以 `--dry-run` 是不花钱确认请求的正确方式。

## 目录

```text
SKILL.md                       路由、钱与时间的纪律、命令表、失败对照表
references/first-use.md        首次使用要准备什么、从哪拿、用户跑什么命令
references/setup.md            凭据来源、优先级、轮换、CI、安全说明
references/routing.md          Videos 路由形态、请求字段、完成任务 payload
references/troubleshooting.md  完整错误对照表
scripts/seedance.sh            CLI：gen / status / wait / download / run
scripts/seedance_config.py     地址与密钥解析、status、doctor
scripts/setup.sh               配置面板（new / modify / status / doctor / reset）
scripts/install.sh             安装到 agent 的技能目录
tests/                         离线测试：不联网、不产生付费请求
```

## 测试

```bash
bash tests/test-config.sh   # 优先级、0600 权限、脱敏、reset、doctor 失败路径
bash tests/test-cli.sh      # --help、--dry-run、参数校验、不泄露密钥
```

两者都在临时 `HOME` 下运行，不碰真实配置，也不会建任何视频任务。

**不配置 CI**：仓库是私有的，Actions 分钟数不免费，而这两套测试离线、秒级，发版前本地跑一遍即可。

## 许可证

MIT，见 [LICENSE](LICENSE)。
