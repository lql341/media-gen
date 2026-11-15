# 已完成 / 待验证 / 待开发

分三类：**已完成**（已发布，不应再列为待办）、**待验证**（代码已实现，等待环境）、**待开发**（尚未实现）。
待验证项不因 mock 通过而划掉：mock 通过不等于对过真实厂商。

## 一、已完成（最近三个版本，已发布）

| 版本 | 内容 |
| --- | --- |
| 0.11.1 | MCP `wait` 不再把任务 id 拆成字符；下载凭据按 scheme+host+port 判断同源 |
| 0.11.2 | MCP `serverInfo.version` 从 `VERSION` 读，不再写死 |
| 0.11.3 | `wait` 多任务失败隔离；`-o` 展开 `~`；MCP `error` 给出真实原因 |
| 0.12.0 | MCP 补齐 `speech` / `transcribe` / `mask` / `remix` / `extend` / `last_frame`；`--last-frame` 在 remix 分支不再被静默忽略 |
| 0.13.0 | 视频流式下载（`.part` → 原子替换）、`write_artifact` 原子写、首个 CI |
| 0.13.1 | Windows UTF-8 输出（MCP 在 cp1252 上无法启动）、CI 矩阵与冷启动处理、`docs/RUNBOOK.md` |

## 二、待验证（代码已实现，等环境）

### 需要带对应 deployment 的端点

| 项 | 现状 | 需要什么 | 验证方式 |
| --- | --- | --- | --- |
| 文生图 `/images/generations` | mock 通过 | 挂了 image deployment 的 key | `media.py image -p … --model <id>` |
| 图片编辑 `/images/edits` | mock + 路由可达性真机（401 白名单） | 同上 | `media.py image -p … --image ref.png` |
| 批量出图 `-n N` | mock 通过 | 同上 | 同上加 `-n 3`，确认三个文件落盘 |
| 语音合成 `/audio/speech` | mock + 401 白名单 | 挂了 speech deployment | `media.py speech -t … --model <id>` |
| 语音转写 `/audio/transcriptions` | mock + 401 白名单 | 挂了 transcription deployment | `media.py transcribe -f a.mp3 --model <id>` |

### 需要花一次钱（用最小配置 480p · 4s，金额与 tokens 由端点的 `usage` 打印，不记在这里）

`--create-only`、`--json`、`wait` 超时分支已于 0.13.x 真机验证（`docs/VERIFICATION.md` 第 21–25 条）。
以下两条代码路径可用，但本网关的上游不支持，需要更换端点才能验证：

| 项 | 现状 | 验证方式 |
| --- | --- | --- |
| `--remix` | 真机试过：网关回 `video remix is not supported for Volcengine video` | 换一个实现了 `POST /videos/<id>/remix` 的端点 |
| `--extend` | 真机试过：上游 LiteLLM `transform_video_extension_request()` 不接受 `model` 入参 | 换端点，或等上游修复 |

### 需要换环境

| 项 | 现状 | 需要什么 |
| --- | --- | --- |
| Linux 真机 + `secret-tool` 钥匙环 | 用 shim 模拟通过 | 一台 Linux；`bash tests/run-all.sh` |
| Windows / `setup.ps1` / 无钥匙环降级 | 纯 Python 部分（registry + MCP）已由 CI 在真实 Windows 上跑；`setup.ps1` 与 bash 套件仍只有模拟 | 一台 Windows（PowerShell 5 或 7） |
| Windows Credential Manager | 未实现 | 可参考 Python 标准库 `ctypes` 调 `Advapi32` 的通用做法 |
| MCP server 接图形客户端 | 仅 stdio JSON-RPC 单测 | WorkBuddy / DSH Desktop / Claude Desktop 实连 |

### 需要外部账号

| 项 | 现状 |
| --- | --- |
| `azure` 协议（deployment 路径 + `api-key`） | mock 通过，需 Azure OpenAI 资源 |
| `ark` 原生（Seedance/Seedream） | mock 通过，需火山 Ark key |
| `dashscope` 原生（Wan 图/视频） | mock 通过，需百炼 key |
| `minimax` 原生（Hailuo / image-01） | mock 通过，需 MiniMax key |
| `custom` 模板 / `command` 钩子 | mock + 真实 shell 钩子通过，需自家接口 |
| profile `--header` / `--query` | mock 通过，需一个会回显请求头的端点 |

## 三、待开发（尚未实现）

| 项 | 说明 | 优先级 |
| --- | --- | --- |
| `/videos/edits`、`/videos/characters` | 网关 OpenAPI 里有，CLI 未接 | 中 |
| `/images/variations` | OpenAI 图变体路由 | 低 |
| 并行**生成**（非并行等待） | 现在只有 `wait id1 id2`；批量建任务仍是串行 | 中 |
| 各家原生 TTS/STT（ark/dashscope/minimax） | 刻意不猜字段；先用 `custom`/`command` 包 | 低 |
| 成本预估 | 刻意不内嵌价目表（会过期） | 低 |
| POST 5xx 重试 | 付费请求永不重试（设计如此）；可选"显式 --retry-paid" | 低 |
| 声音克隆 / 多说话人 / 音乐生成 | 属于另一个技能的量级 | 不做 |
| 音频输出格式转换（wav↔mp3） | 依赖 ffmpeg，暂不做 | 不做 |

## 四、已知边界（不是缺陷）

- 视频模型只有 video deployment：不能出现在 `/model` 选择器，也不能写进任何 `models.json`。
- 网关的任务列表路由可能丢参数（本机实测如此）→ 用本地台账 `media.py tasks`。
- 首帧图在 LiteLLM→火山链路上必须是公网 URL，且 `ratio=adaptive`（实测）。
- 删除密钥必须显式 `MEDIA_ALLOW_CREDENTIAL_DELETE=1`；`audit` 只读不解密。
- **`--remix` / `--extend` 在本网关不可用**（实测）：前者由上游直接抛 `NotImplemented`，后者上游
  `transform_video_extension_request()` 多收了一个 `model`。请求体本身没错
  （remix `{prompt}`、extend `{video_id, prompt, seconds}`），问题在网关侧。
- 本网关的 Seedance 部署 `result.last_frame_url` 恒为 `null`：`--last-frame` 的成功路径只能由 mock 覆盖。

## 五、怎么用这张表

按步骤复验：**[`docs/RUNBOOK.md`](docs/RUNBOOK.md)**（零成本探针在前，全套真机验证只需 1 次付费调用）。

```bash
media.py doctor --matrix     # 当前端点：哪些格子可以真机打勾
media.py doctor --gaps       # 缺哪一类 deployment
media.py models --access     # 这把 key 实际能用什么（零花费）
bash tests/run-all.sh        # 离线回归（零花费、零凭据库操作）
```

打勾后请更新 `docs/VERIFICATION.md` 的矩阵，并把命令与结果一并记录；该表是"已验证"的唯一凭据。
