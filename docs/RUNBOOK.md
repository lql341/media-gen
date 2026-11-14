# 真机验证 Runbook

按顺序跑，**零成本的在前面**。每一步写清"通过长什么样"和它点亮 `docs/VERIFICATION.md` 矩阵里的哪一行。
跑完请把结果写回矩阵，不要把金额/token 抄进文档（CLI 会打印网关自己的 `usage`）。

```bash
cd <仓库根目录>
MEDIA=scripts/media.py
PROFILE=litellm            # scripts/setup.sh list 里显示的名字
MODEL_V=doubao-seedance-2-5 # 换成你端点上实际的视频模型
MODEL_I=gpt-image-1         # 换成你端点上实际的图片模型
```

付费调用计数：`video` 1 次、`remix` 1 次、`extend` 1 次、`image` 1 次、`speech` 1 次。
下面第 0–2 节总共只需要 **1 次**付费调用，其余全免费。

---

## 0. 前置（免费）

```bash
bash tests/run-all.sh                      # 先确认离线套件在本机是绿的
scripts/setup.sh status                    # 配置档 + 密钥来源
$MEDIA --profile $PROFILE doctor           # /models 可达、媒体模型清单
$MEDIA --profile $PROFILE models --kind video
```

- [ ] `run-all.sh` 结尾 `全部通过`
- [ ] `doctor` 打印 `结果 OK`
- [ ] 记下 `models` 里真实存在的 image / video / speech / transcription 模型 id，后面要用

## 1. 零成本探针（一个付费请求都不发）

| # | 目的 | 命令 | 通过标准 | 点亮的行 |
|---|---|---|---|---|
| 1.1 | 本地校验：时长 | `$MEDIA --profile $PROFILE video -p x --model $MODEL_V -s 2` | 本地报 `时长下限`，exit **2**，无请求 | local validation |
| 1.2 | 本地校验：尺寸 | `$MEDIA --profile $PROFILE image -p x --model $MODEL_I --size big` | 本地报 `--size 需要像素尺寸`，exit 2 | local validation |
| 1.3 | 计划预览 | 上面两条加 `--dry-run` | 打印 model/size/params/capability，无任务 | dry-run |
| 1.4 | 密钥白名单 | `$MEDIA --profile $PROFILE models --access` | 列出 `key 白名单共 N 个模型`；若报"无法读出"则该网关不暴露 | `models --access` |
| 1.5 | 能力缺口 | `$MEDIA --profile $PROFILE doctor --gaps` | 列出哪些 kind 有/没有 deployment | `doctor --gaps` |
| 1.6 | 验证矩阵 | `$MEDIA --profile $PROFILE doctor --matrix` | 表格里 ✅/⬜ 与你的端点相符 | `doctor --matrix` |
| 1.7 | 网关任务列表 | `$MEDIA --profile $PROFILE list --model $MODEL_V` | 有列表，或 CLI 明确说"网关丢参数，改用 tasks" | `list` |

## 2. 一次付费调用覆盖视频全链路

最小配置（4s / 480p）跑完整链路（计费 1 次），然后 `status` / `wait` / `download` 全部免费复用同一个任务。

```bash
# 2.1 建任务 + 轮询 + 下载，输出 JSON（计费 1 次）
$MEDIA --profile $PROFILE video -p "rainy neon street, slow push-in" \
       --model $MODEL_V -s 4 --ratio 16:9 --resolution 480p \
       --json --last-frame last.png -o out.mp4
TASK=<JSON 里的 task_id>

# 2.2 以下全部免费（同一个任务复用）
$MEDIA --profile $PROFILE status $TASK
$MEDIA --profile $PROFILE wait $TASK --interval 5 --timeout 600
$MEDIA --profile $PROFILE download $TASK again.mp4 --last-frame again.png
$MEDIA tasks --limit 5                    # 本地台账应能看到这条
```

- [ ] 2.1 输出是单行 JSON：`ok / task_id / file / usage` 都有，`out.mp4` 非空
- [ ] `--last-frame` 有尾帧就保存，没有就打印"未返回 last_frame_url"（网关不支持时属正常）
- [ ] 2.2 `status` 为 `completed`，带 `seconds` / `size`
- [ ] `wait` 立即返回（任务已完成）
- [ ] `download` 落盘非空，且与 2.1 的文件大小一致
- [ ] `tasks` 里该 id 的 `file` 指向刚下载的文件

点亮的行：`text → video`、`status / wait`、`download + --last-frame`、`--json`、`local ledger`、
`streamed download`。

只建任务、不等待（`--create-only`，**再计费 1 次**；它的输出是裸 task id，不带 `--json`）：

```bash
$MEDIA --profile $PROFILE video -p "draft" --model $MODEL_V -s 4 --create-only
```

图生视频（会再计费 1 次）：首帧图必须**公网可访问**，部分链路要求 `--ratio adaptive`：

```bash
$MEDIA --profile $PROFILE video -p "animate this" --model $MODEL_V -s 4 \
       --ratio adaptive --resolution 480p --image https://example.com/first.png -o i2v.mp4
```

## 3. remix / extend（各计费 1 次）

需要一个**已完成**的 `$TASK`：

```bash
$MEDIA --profile $PROFILE video -p "make it night" --model $MODEL_V \
       --remix $TASK -s 4 --interval 5 -o remix.mp4
$MEDIA --profile $PROFILE video -p "continue the shot" --model $MODEL_V \
       --extend $TASK -s 4 --interval 5 -o extend.mp4
```

- [ ] 两次都拿到新的 task id 并落盘
- [ ] `--remix`/`--extend` 同时给 `--last-frame` 时尾帧也会保存（0.12.0 起）

## 4. 图片（需要 image deployment，每张计费 1 次）

```bash
$MEDIA --profile $PROFILE image -p "a red apple on a white table" --model $MODEL_I -o apple.png
$MEDIA --profile $PROFILE image -p "make it blue" --model $MODEL_I \
       --image apple.png --mask apple.png -o edited.png      # /images/edits（mask 可省）
$MEDIA --profile $PROFILE image -p "a cat" --model $MODEL_I -n 3 -o batch.png   # → batch-1..3.png
```

- [ ] 单张落盘非空
- [ ] 带 `--image` 时走 `/images/edits` 成功（401 说明密钥白名单，不算通过）
- [ ] `-n 3` 产出三个文件，且没有无序号文件

## 5. 语音（需要 speech / transcription deployment）

先确认有没有权限（没权限会 `401 team not allowed`，零成本；**有权限就会真的合成并计费**）：

```bash
$MEDIA --profile $PROFILE speech -t hi --model tts-1 --dry-run   # 只打印计划，零成本
```

```bash
$MEDIA --profile $PROFILE speech -t "你好，这是一次验证" --model tts-1 --voice alloy -o a.mp3
$MEDIA --profile $PROFILE transcribe -f a.mp3 --model whisper-1 --language zh -o a.txt
```

- [ ] `a.mp3` 非空（`--format wav` 可指定后缀）
- [ ] `a.txt` 有文本

MCP 通道（GUI 客户端读不到 `SKILL.md`，这两条以前完全够不到）：

```bash
printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' \
  | python3 scripts/mcp_server.py | python3 -c 'import json,sys; print([t["name"] for t in json.load(sys.stdin)["result"]["tools"]])'
```

- [ ] 输出 7 个工具名，含 `media_speech` / `media_transcribe`

## 6. 图形客户端实连（免费）

把 `scripts/mcp_server.py` 按 `references/gui-clients.md` 挂到 WorkBuddy / DSH / Claude Desktop，
`scripts/setup.sh mcp` 会打印可直接粘贴的片段。

- [ ] 客户端能列出工具
- [ ] `media_models` 返回本机配置档里的模型
- [ ] `media_profiles` 能看到 `profile` / `protocol` / `base_url`，**看不到密钥**

## 7. 其他平台

**Linux（真机）**

```bash
bash tests/run-all.sh                          # 应保持全绿
scripts/setup.sh add k --protocol openai --base-url https://gw.example/v1 --store secret-tool
scripts/setup.sh audit                         # 只读，不解密
```

- [ ] `secret-tool` 路径可用（没有钥匙环时退化为 0600 文件或环境变量）
- [ ] `MEDIA_ALLOW_CREDENTIAL_DELETE` 未设置时 `rm` 不会删密钥

**Windows（真机）**

```powershell
.\scripts\setup.ps1 status
.\scripts\setup.ps1 add w --protocol openai --base-url https://gw.example/v1
.\scripts\setup.ps1 doctor
```

- [ ] 中文输出不乱码（0.13.1 起 stdout/stderr 强制 UTF-8）
- [ ] 无钥匙环时给出明确提示，而不是崩溃
- [ ] CI 已覆盖纯 Python 部分（registry + MCP），`setup.ps1` 仍需真机确认

## 8. 收尾：把结果写回去

1. `docs/VERIFICATION.md`：把对应行的 `⬜` 改成 `✅`，并把命令与观察结果补进上面的 live 表。
2. 本文件：勾掉对应小节。
3. 有配置/密钥变化时 `scripts/setup.sh export` 存档（不含密钥）。
4. 公开前最后跑一次 `bash scripts/sanitize-check.sh`。

不要记录：token 数、金额、完整任务 id、签名 URL、网关内部域名。
