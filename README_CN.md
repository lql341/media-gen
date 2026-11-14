# media-gen — 给编码 agent 用的图片 / 视频生成技能

一个 [Agent Skill](https://agentskills.io/specification)：通过**你自己配置的端点**生成图片和视频
——OpenAI 兼容网关（LiteLLM、OpenAI）或各家原生 API（火山 Ark、阿里云百炼 Wan、MiniMax）。
不绑定厂商，也不绑定某个网关。

```bash
scripts/setup.sh add litellm --protocol openai --base-url https://gw.example/v1
scripts/media.py models
scripts/media.py image -p "白桌上一颗红苹果" --model gpt-image-1 -o apple.png
scripts/media.py video -p "雨夜霓虹街道，缓慢推镜" --model doubao-seedance-2-5 -s 5 -o street.mp4
```

## 两个独立的决定

| 决定 | 由谁决定 | 存哪 |
| --- | --- | --- |
| **发到哪**（地址、密钥、协议） | 命名配置档（profile） | `~/.config/media-gen/config.json` + 系统凭据库 |
| **这个模型是什么、能收什么参数**（图片/视频、时长、尺寸写法） | 能力注册表 | `scripts/registry.json` + `~/.config/media-gen/registry.json` |

正因为拆开了，才通用：同一个 `wan2.5-t2v`，既可以经网关（`protocol=openai`）走，也可以直连百炼
（`protocol=dashscope`）；`--size`、`-s`、`--ratio/--resolution` 由 CLI 归一化成该协议要的形状。

## 协议

| 协议 | 端点形态 | 图片 | 视频 |
| --- | --- | --- | --- |
| `openai` | OpenAI 兼容 / LiteLLM | `/images/generations` | `/videos` + 轮询 |
| `ark` | `https://ark.cn-beijing.volces.com/api/v3` | `/images/generations` | `/contents/generations/tasks` |
| `dashscope` | `https://dashscope.aliyuncs.com/api/v1` | 异步任务 | 异步任务 |
| `minimax` | `https://api.minimaxi.com/v1` | `/image_generation` | `/video_generation`（取文件两跳） |
| `custom` | 任何 REST | 模板 | 模板 | 用一个 JSON 文件描述自家接口的字段形状 |
| `command` | 任意 | 钩子脚本 | 钩子脚本 | 脚本用 stdin/stdout 交换 JSON |

每个协议的**验证程度**写在 [`references/providers.md`](references/providers.md)：哪些是真机跑过、
哪些只对着本地 mock 验证过协议形状——不吹。

## 安装

```bash
git clone https://github.com/lql341/media-gen.git ~/src/media-gen
bash ~/src/media-gen/scripts/install.sh          # 符号链接到 ~/.agents/skills
bash ~/src/media-gen/scripts/install.sh --codex  # 或 --claude / --copy / --uninstall
```

重开 agent（或 `/reload`）后用 `/skill:media-gen`，或者直接说要图片/视频。

## 配置

交互向导（macOS / Linux / Windows PowerShell 同一套界面）：

```bash
scripts/setup.sh          # macOS / Linux
.\scripts\setup.ps1       # Windows PowerShell
```

也支持全参数化：

```bash
# 新增 / 更新端点
scripts/setup.sh add <name> --protocol <openai|ark|dashscope|minimax|custom|command> \
    --base-url <URL> [--key-stdin | --key-file PATH] \
    [--default-image M] [--default-video M] [--set-default]
# 非官方接口
scripts/setup.sh add inhouse --protocol custom  --custom-file ./inhouse.json --base-url https://…/api
scripts/setup.sh add weird   --protocol command --command-json '{"create":"~/bin/x create","status":"…","fetch":"…"}'

# 生命周期
scripts/setup.sh modify <name>            # 交互改：地址 / 密钥 / 协议 / 默认模型
scripts/setup.sh set-url <name> --base-url <URL>
printf '%s' "$KEY" | scripts/setup.sh set-key <name>
scripts/setup.sh set-protocol <name> --protocol <p> [--custom-file F | --command-json J]
scripts/setup.sh rename <old> <new>
scripts/setup.sh rm <name> [--keep-key]   # 或 rm --all
scripts/setup.sh export | import <file>   # 只搬配置，不含密钥

# 查看与自检
scripts/setup.sh list | show <name> | status [--profile P] | doctor [--profile P]
scripts/setup.sh migrate                  # 迁移旧的 seedance 配置
```

密钥优先级：`MEDIA_API_KEY_<PROFILE>` → `MEDIA_API_KEY` → 系统凭据库 → 配置文件内明文
（`--store file`，0600）→ agent auth 文件只读导入。**没有默认端点、没有默认模型**——都归部署方决定。

同一个端点可以有多个**账户**（同 URL、不同密钥/工作区）：`setup.sh add <name> --account team --key-stdin`，
之后用 `<name>@team`、`--account team` 或 `MEDIA_ACCOUNT=team` 选择；**具名账户绝不回退**到默认账户的密钥，
所以两个会话可以各自用自己的密钥并发跑。详见 `references/setup.md`。

凭据库只在真正需要时才访问：`MEDIA_CREDENTIAL_STORE=file|none` 可完全绕开，单进程内查询带缓存
（一次 `list` 只查一遍），`MEDIA_DEBUG_STORE=1` 会把每次访问打到 stderr。测试全部以 `none` 运行并断言
零次凭据库操作。

## 使用

| 目的 | 命令 |
| --- | --- |
| 看能生成什么 | `media.py models [--kind image|video]` |
| 图片 | `media.py image -p "<提示词>" --model M [--size 1024x1024] [-n N] [-o out.png]` |
| 视频 | `media.py video -p "<提示词>" --model M [-s 6] [--ratio 16:9] [--resolution 720p] [--image 首帧图] [-o out.mp4]` |
| 自动判种类 | `media.py run --model M …` |
| 换账户 | `media.py --profile <name>@<alias>` / `--account <alias>` / `MEDIA_ACCOUNT` |
| 任务 | `media.py status <id>` · `wait` · `download` · `--create-only` |
| 不花钱 | 加 `--dry-run` |

## 目录与测试

```bash
bash tests/run-all.sh     # 六套离线测试：registry 单测、六种协议 mock、配置优先级与生命周期、
                          # 交互向导（管道驱动）、MCP server（stdio）、CLI 端到端；零凭据库访问
```

非官方端点（`custom` 模板 / `command` 钩子）见 [`references/custom-endpoints.md`](references/custom-endpoints.md)；
交互向导与跨平台入口见 [`references/interactive.md`](references/interactive.md)；
图形客户端（WorkBuddy / DSH / Claude Desktop / CodeBuddy）走 MCP，见
[`references/gui-clients.md`](references/gui-clients.md)。

协议适配器是对着 `tests/mock_server.py`（按各家文档实现的本地 mock）跑的，**不联网、不要账号、不花钱**。
仓库不配 CI（私有仓库 + Actions 分钟数不免费）。

## 迁移

从只支持 seedance 的旧技能升级：见 [MIGRATION.md](MIGRATION.md)。

## 许可证

MIT，见 [LICENSE](LICENSE)。
