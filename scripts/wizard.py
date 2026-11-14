#!/usr/bin/env python3
"""Cross-platform interactive wizard for media-gen.

Works the same on macOS, Linux and Windows (PowerShell included): pure stdlib,
`getpass` for hidden key input, no ANSI tricks, no shell dependency. The shell and
PowerShell wrappers (`setup.sh`, `setup.ps1`) only locate `python3` and call this.

    python3 scripts/wizard.py            # menu
    python3 scripts/wizard.py add        # add/update an endpoint
    python3 scripts/wizard.py custom     # build a `custom` template step by step
    python3 scripts/wizard.py verify     # doctor for every profile

Every prompt has a default, so piping answers in also works (used by the tests).
"""

from __future__ import annotations

import getpass
import json
import os
import platform
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import media_config as config  # noqa: E402

PROTOCOL_HELP = [
    ("openai", "OpenAI 兼容网关（LiteLLM / OpenAI / 自家代理），/images/generations + /videos"),
    ("ark", "火山引擎 Ark 原生（Seedance 视频 / Seedream 图片）"),
    ("dashscope", "阿里云百炼原生（Wan 文生图 / 文生视频 / 图生视频）"),
    ("minimax", "MiniMax 原生（Hailuo 视频 / image-01 图片）"),
    ("custom", "非官方接口：用 JSON 模板描述字段（本向导可逐项生成）"),
    ("command", "非官方接口：用钩子脚本交换 JSON（最灵活）"),
]

DEFAULT_BASE = {
    "ark": "https://ark.cn-beijing.volces.com/api/v3",
    "dashscope": "https://dashscope.aliyuncs.com/api/v1",
    "minimax": "https://api.minimaxi.com/v1",
    "command": "unused://inhouse",
}


# --------------------------------------------------------------------- helpers


def out(text: str = "") -> None:
    print(text)


def ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        answer = input(f"{prompt}{suffix}: ")
    except EOFError:
        return default
    answer = answer.strip()
    return answer or default


def ask_bool(prompt: str, default: bool = True) -> bool:
    answer = ask(prompt + (" (Y/n)" if default else " (y/N)"), "y" if default else "n").lower()
    return answer in ("y", "yes", "是", "1", "true")


def ask_secret(prompt: str = "API Key（输入不显示，留空=不保存）") -> str:
    if not sys.stdin.isatty():
        # 管道/CI 场景：getpass 会打一堆告警，退回普通读取（值同样不进 argv）
        return ask(prompt, "")
    try:
        return getpass.getpass(prompt + ": ").strip()
    except (EOFError, KeyboardInterrupt):
        return ""
    except Exception:  # getpass 在某些 Windows 管道环境下会失败
        return ask(prompt, "")


def die(message: str, code: int = 1) -> "NoReturn":  # type: ignore[name-defined]
    print(f"错误：{message}", file=sys.stderr)
    raise SystemExit(code)


def profiles() -> dict:
    return config.profiles()


def save_profile(name: str, entry: dict, set_default: bool) -> None:
    current = config.read_config()
    block = dict(current.get("profiles") or {})
    block[name] = entry
    current["profiles"] = block
    if set_default or not current.get("default"):
        current["default"] = name
    config.write_config(current)


def apply_key(name: str, entry: dict, key: str) -> dict:
    """Store the key in the credential store, falling back to a 0600 file."""
    if not key:
        return entry
    provider = config.secure_store_name()
    if provider:
        try:
            stored = config.store_key(name, key)
        except config.ConfigError as error:
            out(f"  写入 {provider} 失败：{error}")
            if ask_bool("  改为写入 0600 配置文件（明文）？", True):
                entry["api_key"] = key
                out(f"  密钥写入 {config.config_file()}（0600 明文）")
            else:
                out("  已跳过保存：请用环境变量 MEDIA_API_KEY 注入")
            return entry
        entry.pop("api_key", None)
        out(f"  密钥已存入 {stored}")
    else:
        if ask_bool("  本机没有系统凭据库，是否写入 0600 配置文件（明文）？", True):
            entry["api_key"] = key
            out(f"  密钥写入 {config.config_file()}（0600 明文）")
        else:
            out("  已跳过保存：请用环境变量 MEDIA_API_KEY" + ("" if name == "default" else f"_{name.upper()}") + " 注入")
    return entry


def pick_protocol(default: str = "openai") -> str:
    out("\n可选协议：")
    for index, (name, description) in enumerate(PROTOCOL_HELP, 1):
        out(f"  {index}) {name:<10} {description}")
    answer = ask("协议（序号或名字）", default)
    if answer.isdigit():
        index = int(answer)
        if 1 <= index <= len(PROTOCOL_HELP):
            return PROTOCOL_HELP[index - 1][0]
        die("序号超出范围")
    names = [name for name, _ in PROTOCOL_HELP]
    if answer not in names:
        die(f"未知协议 {answer}")
    return answer


def verify(name: str | None = None) -> None:
    import subprocess

    arguments = [sys.executable, os.path.join(HERE, "media.py")]
    if name:
        arguments += ["--profile", name]
    arguments.append("doctor")
    subprocess.run(arguments, check=False)


# ------------------------------------------------------------------------ add


def flow_add(name: str | None = None) -> None:
    out("\n== 新增 / 更新端点 ==")
    name = name or ask("配置档名（如 litellm / ark / inhouse）", "default")
    if not name:
        die("配置档名不能为空")
    protocol = pick_protocol()
    default_base = DEFAULT_BASE.get(protocol, "")
    base = ask("base_url（必填）", default_base)
    if not base:
        die("base_url 不能为空")
    try:
        base = config.validate_base_url(protocol, base)
    except config.ConfigError as error:
        die(str(error))

    account = ask("账户别名（同一端点不同密钥/工作区；留空=默认账户）", "")
    if account and not config.ACCOUNT_RE.match(account):
        die("账户别名只能用字母、数字、点、下划线、横线（≤32）")
    entry: dict = {"protocol": protocol, "base_url": base}
    existing = profiles().get(name) or {}
    if existing.get("default_models"):
        entry["default_models"] = dict(existing["default_models"])

    if protocol == "custom":
        spec_path = ask("custom 模板文件路径（留空=现在逐项生成）", str(config.custom_spec_path(name)))
        if spec_path and os.path.isfile(os.path.expanduser(spec_path)):
            with open(os.path.expanduser(spec_path), encoding="utf-8") as handle:
                spec = json.load(handle)
            config.write_json(config.custom_spec_path(name), spec)
            entry["custom_file"] = config.custom_spec_path(name)
            out(f"  模板已复制到 {entry['custom_file']}")
        else:
            spec = build_custom_spec(name)
            config.write_json(config.custom_spec_path(name), spec)
            entry["custom_file"] = config.custom_spec_path(name)
    elif protocol == "command":
        out("  钩子命令表：至少 image，或 create + status + fetch")
        commands = {}
        for step in ("image", "create", "status", "fetch"):
            value = ask(f"  {step} 命令（留空跳过）", "")
            if value:
                commands[step] = value
        if not commands:
            die("至少要给一条命令")
        entry["command"] = commands

    image_model = ask("默认图片模型（可留空）", entry.get("default_models", {}).get("image", ""))
    video_model = ask("默认视频模型（可留空）", entry.get("default_models", {}).get("video", ""))
    defaults = dict(entry.get("default_models") or {})
    if image_model:
        defaults["image"] = image_model
    if video_model:
        defaults["video"] = video_model
    if defaults:
        entry["default_models"] = defaults

    if account:
        accounts = dict(entry.get("accounts") or existing.get("accounts") or {})
        account_entry = dict(accounts.get(account) or {})
        account_entry["base_url"] = base
        if entry.get("default_models"):
            account_entry["default_models"] = entry["default_models"]
        key = ask_secret("账户 API Key（留空=不保存）")
        if key:
            provider = config.secure_store_name()
            if provider:
                try:
                    config.store_key(name, key, account)
                    out(f"  密钥已存入 {provider}（{config.store_item_name(name, account)}）")
                except config.ConfigError as error:
                    out(f"  写入 {provider} 失败：{error}")
                    if ask_bool("  改为写入 0600 配置文件？", True):
                        account_entry["api_key"] = key
            elif ask_bool("  无系统凭据库，写入 0600 配置文件？", True):
                account_entry["api_key"] = key
        accounts[account] = account_entry
        entry["accounts"] = accounts
        entry.pop("api_key", None)
    else:
        entry = apply_key(name, entry, ask_secret())
    save_profile(name, entry, True if account else ask_bool(f"是否把 {name} 设为默认配置档？", True))
    if account:
        current = config.read_config()
        current["default"] = f"{name}@{account}"
        config.write_config(current)
    out(f"\n已保存{'账户 ' + name + '@' + account if account else '配置档 ' + name}（{protocol} · {base}）")
    if ask_bool("现在做一次只读自检（doctor）？", True):
        verify(name)


# --------------------------------------------------------------------- custom


def build_custom_spec(name: str) -> dict:
    out("\n-- custom 模板生成器 --")
    out("回答几个问题即可；所有路径都是点号路径，数组用数字下标（如 data.0.image）。")
    spec: dict = {}
    auth_mode = ask("认证方式（bearer/header/query）", "bearer")
    auth: dict = {"mode": auth_mode}
    if auth_mode in ("header", "query"):
        auth["name"] = ask("认证参数名（如 x-api-key / token）", "x-api-key" if auth_mode == "header" else "token")
        if auth_mode == "header":
            auth["prefix"] = ask("认证前缀", "")
    spec["auth"] = auth

    if ask_bool("这个端点支持图片生成？", True):
        out("  图片：一次请求直接返回")
        image: dict = {
            "method": ask("  请求方法", "POST"),
            "path": ask("  请求路径（相对 base_url）", "/v1/t2i"),
            "response": {"mode": ask("  返回形式（b64/url）", "b64"), "path": ask("  返回内容字段", "data.0.image")},
        }
        body: dict = {"model": "{model}", "prompt": "{prompt}"}
        if ask_bool("  要发送 size？", True):
            body["size"] = "{size}"
        if ask_bool("  要发送 n？", False):
            body["n"] = "{n}"
        image["body"] = body
        spec["image"] = image

    if ask_bool("这个端点支持视频生成（异步任务）？", True):
        out("  视频：create → status → fetch")
        create_path = ask("  建任务路径", "/v1/tasks")
        status_path = ask("  查任务路径（用 {task_id}）", "/v1/tasks/{task_id}")
        body = {"model": "{model}", "prompt": "{prompt}"}
        if ask_bool("  要发送 seconds？", True):
            body["seconds"] = "{seconds}"
        spec["video"] = {
            "create": {"method": "POST", "path": create_path, "body": body},
            "task_id_path": ask("  任务 id 字段", "task.id"),
            "status": {"path": status_path},
            "state": {
                "status_path": ask("  状态字段", "state"),
                "done": [ask("  '完成'的取值", "finished")],
                "failed": [ask("  '失败'的取值", "failed")],
                "error_path": ask("  错误信息字段", "message"),
                "video_url_path": ask("  视频地址字段", "output.video_url"),
                "seconds_path": ask("  时长字段（可留空）", ""),
                "size_path": ask("  尺寸字段（可留空）", ""),
            },
            "fetch": {"mode": ask("  下载方式（url/path）", "url")},
        }
        fetch_mode = spec["video"]["fetch"]["mode"]
        if fetch_mode == "path":
            spec["video"]["fetch"]["path"] = ask("  下载路径（用 {task_id}）", "/v1/tasks/{task_id}/file")

    out("\n模板预览：")
    out(json.dumps(spec, ensure_ascii=False, indent=2))
    if not ask_bool("保存这个模板？", True):
        die("已取消", 0)
    return spec


def flow_custom() -> None:
    name = ask("配置档名", "inhouse")
    base = ask("base_url", "https://inhouse.example/api")
    spec = build_custom_spec(name)
    config.write_json(config.custom_spec_path(name), spec)
    entry = {"protocol": "custom", "base_url": config.validate_base_url("custom", base),
             "custom_file": config.custom_spec_path(name)}
    entry = apply_key(name, entry, ask_secret())
    save_profile(name, entry, ask_bool("设为默认配置档？", False))
    out(f"\n已保存 {name}，模板在 {config.custom_spec_path(name)}")
    if ask_bool("现在自检？", True):
        verify(name)


# -------------------------------------------------------------------- modify


def flow_modify() -> None:
    found = profiles()
    if not found:
        die("还没有配置档；先选 1 新增")
    out("\n已有配置档：")
    for name in sorted(found):
        mark = "*" if name == config.read_config().get("default") else " "
        out(f" {mark} {name:<14} {found[name].get('protocol'):<10} {found[name].get('base_url')}")
    name = ask("要修改哪个", sorted(found)[0])
    if name not in found:
        die(f"没有 {name}")
    entry = dict(found[name])
    out("1) 地址  2) 密钥  3) 协议  4) 默认模型  5) 改名  6) 设为默认")
    choice = ask("修改哪一项", "1")
    if choice == "1":
        entry["base_url"] = config.validate_base_url(entry["protocol"], ask("新地址", entry["base_url"]))
        save_profile(name, entry, False)
        out("地址已更新")
    elif choice == "2":
        entry = apply_key(name, entry, ask_secret())
        save_profile(name, entry, False)
    elif choice == "3":
        protocol = pick_protocol(entry.get("protocol", "openai"))
        entry["protocol"] = protocol
        entry.pop("custom_file", None)
        entry.pop("command", None)
        if protocol == "custom":
            spec = build_custom_spec(name)
            config.write_json(config.custom_spec_path(name), spec)
            entry["custom_file"] = config.custom_spec_path(name)
        elif protocol == "command":
            commands = {}
            for step in ("image", "create", "status", "fetch"):
                value = ask(f"  {step} 命令（留空跳过）", "")
                if value:
                    commands[step] = value
            entry["command"] = commands
        save_profile(name, entry, False)
        out(f"协议已更新为 {protocol}")
    elif choice == "4":
        defaults = dict(entry.get("default_models") or {})
        kind = ask("改哪个（image/video）", "video")
        defaults[kind] = ask("模型 id", defaults.get(kind, ""))
        entry["default_models"] = defaults
        save_profile(name, entry, False)
    elif choice == "5":
        new_name = ask("新名字", name)
        current = config.read_config()
        block = dict(current.get("profiles") or {})
        block[new_name] = block.pop(name)
        current["profiles"] = block
        if current.get("default") == name:
            current["default"] = new_name
        config.write_config(current)
        stored = config._read_store(config.SERVICE, name)
        if stored:
            config.store_key(new_name, stored)
            config.delete_key(name)
        spec = config.custom_spec_path(name)
        if os.path.exists(spec):
            os.replace(spec, config.custom_spec_path(new_name))
        out(f"已改名 {name} → {new_name}")
    elif choice == "6":
        current = config.read_config()
        current["default"] = name
        config.write_config(current)
        out(f"默认配置档 → {name}")
    else:
        die("无效选择")
    if ask_bool("现在自检？", True):
        verify(name)


def flow_remove() -> None:
    found = profiles()
    if not found:
        die("还没有配置档")
    for name in sorted(found):
        out(f"  {name}")
    name = ask("要删除哪个（留空=全部）", "")
    if not name:
        if not ask_bool("确认删除全部配置档及其密钥？", False):
            return
        current = config.read_config()
        for key in list(found):
            try:
                config.delete_key(key)
            except config.ConfigError as error:
                out(f"提示：{str(error).splitlines()[0]}")
            spec = config.custom_spec_path(key)
            if os.path.exists(spec):
                os.remove(spec)
        current.pop("profiles", None)
        current.pop("default", None)
        config.write_config(current)
        out("已删除全部配置档")
        return
    if name not in found:
        die(f"没有 {name}")
    out("默认不会删除系统凭据库里的密钥条目（需要显式闸门），配置会被删除。")
    keep = ask_bool("保留密钥条目？", True)
    current = config.read_config()
    block = dict(current.get("profiles") or {})
    block.pop(name, None)
    current["profiles"] = block
    if current.get("default") == name:
        current.pop("default", None)
    config.write_config(current)
    if not keep:
        try:
            config.delete_key(name)
        except config.ConfigError as error:
            out(f"提示：{str(error).splitlines()[0]}")
    spec = config.custom_spec_path(name)
    if os.path.exists(spec):
        os.remove(spec)
    out(f"已删除 {name}")


def flow_mcp() -> None:
    """打印各客户端的 MCP 注册片段（图形客户端靠 MCP 拿到交互能力）。"""
    python = sys.executable
    server = os.path.join(HERE, "mcp_server.py")
    snippet = {"mcpServers": {"media-gen": {
        "command": python, "args": [server], "env": {"MEDIA_PROFILE": "<profile>"}
    }}}
    out("\nMCP 服务器（这个技能同时是一个 MCP server，图形客户端用它就能交互生成）")
    out(f"  命令：{python} {server}")
    out("\n通用 JSON（pi 的 ~/.pi/agent/mcp.json、Claude Desktop、WorkBuddy/DSH Desktop 等）：")
    out(json.dumps(snippet, ensure_ascii=False, indent=2))
    out("\nCodeBuddy：codebuddy mcp add media-gen -s user -- %s %s" % (python, server))
    out("Windows PowerShell 里路径用反斜杠并加引号；python 用 `python` 或解释器绝对路径。")


MENU = [
    ("add", "新增 / 更新端点（交互）"),
    ("custom", "生成 custom 模板（非官方接口，逐项问答）"),
    ("modify", "修改已有配置档（地址 / 密钥 / 协议 / 默认模型 / 改名）"),
    ("remove", "删除配置档"),
    ("list", "列出配置档"),
    ("doctor", "自检（只读）"),
    ("migrate", "迁移旧的 seedance 配置"),
    ("mcp", "查看图形客户端的 MCP 注册片段"),
    ("quit", "退出"),
]


def menu() -> None:
    out("media-gen 交互配置")
    out(f"  平台 {platform.system()} · python {platform.python_version()} · 配置目录 {config.config_dir()}")
    for index, (_, label) in enumerate(MENU, 1):
        out(f"  {index}) {label}")
    answer = ask("选择", "1")
    if answer.isdigit() and 1 <= int(answer) <= len(MENU):
        action = MENU[int(answer) - 1][0]
    else:
        action = answer
    dispatch(action)


def dispatch(action: str) -> None:
    found = profiles()
    if action == "add":
        return flow_add()
    if action == "custom":
        return flow_custom()
    if action == "modify":
        return flow_modify()
    if action == "remove":
        return flow_remove()
    if action == "list":
        if not found:
            out("（还没有配置档）")
            return
        default = config.read_config().get("default")
        for name in sorted(found):
            key, source = config.resolve_key(name, found[name])
            out(f"{'*' if name == default else ' '} {name:<14} {found[name].get('protocol'):<10} "
                f"{found[name].get('base_url')}  {'密钥:' + (config.mask(key) if key else '无')}")
        return
    if action == "doctor":
        verify()
        return
    if action == "migrate":
        import subprocess

        subprocess.run([sys.executable, os.path.join(HERE, "media_config.py"), "migrate"], check=False)
        return
    if action == "mcp":
        return flow_mcp()
    if action in ("quit", "q", ""):
        return
    die(f"未知动作 {action}；可选：add custom modify remove list doctor migrate mcp")


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        if not arguments:
            menu()
        else:
            dispatch(arguments[0])
    except config.ConfigError as error:
        die(str(error), 2)
    except KeyboardInterrupt:
        out("\n已中断")
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
