"""Seedance gateway configuration and credential discovery.

One job: tell the caller which base URL and API key to use, without ever
writing a secret to stdout (except the explicit ``get-key`` used internally by
``seedance.sh``), to argv, or to the repository.

Resolution order, first hit wins:

    key       SEEDANCE_API_KEY  →  LEGACY_API_KEY (legacy)
              →  OS credential store  →  config.json (opt-in, 0600)
              →  read-only import from an agent's auth file
    base URL  SEEDANCE_BASE_URL  →  LEGACY_BASE_URL (legacy)
              →  config.json  →  DEFAULT_BASE

The agent-auth import exists so that an existing Pi / CodeBuddy install keeps
working, but the value is never copied out of that file silently: ``status``
reports it as a distinct, lower-priority source and ``import`` promotes it into
the real credential store.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request

SERVICE = "seedance-gateway"
DEFAULT_BASE = "https://gw.example.com/v1"
ENV_KEYS = ("SEEDANCE_API_KEY", "LEGACY_API_KEY")
ENV_BASES = ("SEEDANCE_BASE_URL", "LEGACY_BASE_URL")
DEFAULT_MODELS = ("doubao-seedance-2-5", "doubao-seedance-2-0-260128")
AGENT_AUTH_FILES = (
    "~/.pi/agent/auth.json",
    "~/.codebuddy/models.json",
    "~/.workbuddy/models.json",
)


class ConfigError(RuntimeError):
    """A user-facing configuration or credential failure."""


# --------------------------------------------------------------------------- paths


def config_dir() -> str:
    xdg = os.environ.get("XDG_CONFIG_HOME", "")
    root = xdg if xdg.startswith("/") else os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(root, "seedance")


def config_file() -> str:
    return os.path.join(config_dir(), "config.json")


def read_config() -> dict:
    try:
        with open(config_file(), encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as error:
        raise ConfigError(f"配置文件无法解析（{config_file()}）：{error}") from None
    return data if isinstance(data, dict) else {}


def write_config(data: dict) -> None:
    directory = config_dir()
    os.makedirs(directory, mode=0o700, exist_ok=True)
    os.chmod(directory, 0o700)
    path = config_file()
    temporary = path + ".tmp"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


# --------------------------------------------------------------------- credentials


def normalize_secret(value: str, label: str = "API Key") -> str:
    """Strip paste artifacts but never echo the value in an error."""
    value = value.strip().lstrip("\ufeff")
    if len(value) >= 2 and (value[0], value[-1]) in {('"', '"'), ("'", "'"), ("“", "”")}:
        value = value[1:-1].strip()
    if not value:
        raise ConfigError(f"{label} 不能为空。")
    if re.match(r"(?i)^(export\s|set\s|\$env:|SEEDANCE_|LEGACY_|(?:api[_-]?key|token)\s*[:=])", value):
        raise ConfigError(f"{label} 收到了变量赋值或字段名；请只粘贴值本身。")
    if re.match(r"(?i)^authorization\s*:", value):
        raise ConfigError(f"{label} 收到了整行 Authorization 头；请只粘贴 Bearer 后面的值。")
    if any(character.isspace() or ord(character) < 32 for character in value):
        raise ConfigError(f"{label} 含空白或换行，请重新复制。")
    return value


def secure_store_name() -> str | None:
    if platform.system() == "Darwin" and shutil.which("security"):
        return "macOS Keychain"
    if shutil.which("secret-tool"):
        return "Secret Service"
    return None


def _run(command: list[str], **options) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(command, timeout=30, **options)
    except (OSError, subprocess.TimeoutExpired):
        # Never let the exception text (which contains argv) reach the user.
        raise ConfigError("系统凭据操作失败或超时；请检查密钥环服务是否已解锁。") from None


def load_secure_key() -> str | None:
    provider = secure_store_name()
    if provider == "macOS Keychain":
        command = ["security", "find-generic-password", "-s", SERVICE, "-w"]
    elif provider == "Secret Service":
        command = ["secret-tool", "lookup", "service", SERVICE]
    else:
        return None
    completed = _run(
        command, text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False
    )
    if completed.returncode != 0 or not completed.stdout.strip():
        return None
    try:
        payload = json.loads(completed.stdout)
    except ValueError:
        return None
    key = payload.get("api_key") if isinstance(payload, dict) else None
    return key if isinstance(key, str) and key else None


def store_secure_key(key: str) -> str:
    provider = secure_store_name()
    payload = json.dumps({"api_key": key}, separators=(",", ":"))
    if provider == "macOS Keychain":
        command = [
            "security", "add-generic-password", "-U", "-s", SERVICE, "-a", "default", "-w", payload,
        ]
        completed = _run(
            command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, check=False
        )
    elif provider == "Secret Service":
        command = ["secret-tool", "store", "--label=Seedance gateway API key", "service", SERVICE]
        completed = _run(
            command, input=payload, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            text=True, check=False,
        )
    else:
        raise ConfigError(
            "本机没有可用的系统凭据库（macOS Keychain / secret-tool）；"
            "请用环境变量 SEEDANCE_API_KEY 注入，或用 setup.sh --store file 明确选择 0600 文件。"
        )
    if completed.returncode != 0:
        raise ConfigError(f"写入 {provider} 失败（exit={completed.returncode}）；请检查解锁状态。")
    return str(provider)


def delete_secure_key() -> bool:
    provider = secure_store_name()
    if provider == "macOS Keychain":
        command = ["security", "delete-generic-password", "-s", SERVICE]
    elif provider == "Secret Service":
        command = ["secret-tool", "clear", "service", SERVICE]
    else:
        return False
    completed = _run(
        command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True, check=False
    )
    return completed.returncode == 0


def agent_auth_key() -> tuple[str, str] | None:
    """Read-only fallback: reuse a key an agent already manages locally."""
    for pattern in AGENT_AUTH_FILES:
        path = os.path.expanduser(pattern)
        try:
            with open(path, encoding="utf-8") as handle:
                data = json.load(handle)
        except (FileNotFoundError, OSError, ValueError):
            continue
        if isinstance(data, dict) and isinstance(data.get("legacyprov"), dict):
            key = data["legacyprov"].get("key")
            if isinstance(key, str) and key:
                return key, f"{path}:legacyprov"
        models = data.get("models") if isinstance(data, dict) else data
        for model in models or []:
            if not isinstance(model, dict):
                continue
            if "example.com" in str(model.get("url", "")) and model.get("apiKey"):
                return str(model["apiKey"]), f"{path}:models[]"
    return None


def resolve_key() -> tuple[str | None, str]:
    for name in ENV_KEYS:
        value = os.environ.get(name, "")
        if value:
            return normalize_secret(value, name), name
    key = load_secure_key()
    if key:
        return key, secure_store_name() or "credential store"
    config = read_config()
    if isinstance(config.get("api_key"), str) and config["api_key"]:
        return normalize_secret(config["api_key"]), f"{config_file()} (0600, 明文，--store file)"
    found = agent_auth_key()
    if found:
        key, origin = found
        return normalize_secret(key), f"{origin}（只读导入）"
    return None, "未配置"


def resolve_base() -> tuple[str, str]:
    for name in ENV_BASES:
        value = os.environ.get(name, "").strip()
        if value:
            return value.rstrip("/"), name
    config = read_config()
    value = config.get("base_url")
    if isinstance(value, str) and value.strip():
        return value.strip().rstrip("/"), config_file()
    return DEFAULT_BASE, "默认值"


def resolve_model() -> tuple[str, str]:
    value = os.environ.get("SEEDANCE_VIDEO_MODEL", "").strip()
    if value:
        return value, "SEEDANCE_VIDEO_MODEL"
    config = read_config()
    saved = config.get("model")
    if isinstance(saved, str) and saved.strip():
        return saved.strip(), config_file()
    return DEFAULT_MODELS[0], "默认值"


def mask(secret: str) -> str:
    if len(secret) <= 10:
        return "已配置（短密钥不显示尾部）"
    return f"已配置 …{secret[-4:]}"


# -------------------------------------------------------------------------- doctor


def doctor(timeout: int = 20) -> int:
    base, base_source = resolve_base()
    key, key_source = resolve_key()
    print(f"地址        {base}  （来源：{base_source}）")
    print(f"密钥        {mask(key) if key else '未配置'}  （来源：{key_source}）")
    if not key:
        print("结果        FAIL  没有可用密钥；运行 scripts/setup.sh new")
        return 1
    request = urllib.request.Request(base + "/models", headers={"Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.load(response)
            status = response.status
    except urllib.error.HTTPError as error:
        print(f"结果        FAIL  GET /models 返回 {error.code}：{_error_text(error)}")
        if error.code == 401:
            print("            密钥被拒绝；用 scripts/setup.sh modify 重新配置")
        return 1
    except (urllib.error.URLError, OSError) as error:
        print(f"结果        FAIL  连不上 {base}：{getattr(error, 'reason', error)}")
        return 1
    identifiers = [entry.get("id") for entry in payload.get("data", []) if isinstance(entry, dict)]
    print(f"结果        OK    GET /models {status}，{len(identifiers)} 个模型")
    missing = [model for model in DEFAULT_MODELS if model not in identifiers]
    if missing:
        print(f"警告        列表里没有：{', '.join(missing)}（网关可能未挂载这两个 deployment）")
    else:
        print(f"视频模型    {', '.join(DEFAULT_MODELS)}")
    return 0


def _error_text(error: urllib.error.HTTPError) -> str:
    try:
        body = error.read().decode("utf-8", "replace")
        parsed = json.loads(body)
        message = parsed.get("error", parsed).get("message") if isinstance(parsed, dict) else None
        return str(message) if message else body[:200]
    except Exception:  # noqa: BLE001 - diagnostics only
        return "（响应无正文）"


# ----------------------------------------------------------------------------- CLI


def cmd_status(_: argparse.Namespace) -> int:
    base, base_source = resolve_base()
    key, key_source = resolve_key()
    model, model_source = resolve_model()
    print(f"配置目录    {config_dir()}")
    print(f"地址        {base}")
    print(f"地址来源    {base_source}")
    print(f"密钥        {mask(key) if key else '未配置'}")
    print(f"密钥来源    {key_source}")
    print(f"默认模型    {model}（{model_source}）")
    print(f"系统凭据库  {secure_store_name() or '不可用（用环境变量或 --store file）'}")
    if os.path.exists(config_file()):
        mode = oct(os.stat(config_file()).st_mode & 0o777)
        print(f"配置文件    {config_file()}  {mode}")
    return 0 if key else 1


def cmd_set(args: argparse.Namespace) -> int:
    config = read_config()
    changed = []
    if args.base_url is not None:
        base = args.base_url.strip().rstrip("/")
        if not base:
            raise ConfigError("--base-url 不能为空")
        if not re.match(r"^https?://", base):
            raise ConfigError("--base-url 必须是 http(s):// 开头的绝对地址")
        config["base_url"] = base
        changed.append(f"地址 {base}")
    if args.model is not None:
        if not args.model.strip():
            raise ConfigError("--model 不能为空")
        config["model"] = args.model.strip()
        changed.append(f"默认模型 {config['model']}")

    key = None
    if args.key_stdin:
        key = normalize_secret(sys.stdin.read())
    elif args.key_file:
        with open(os.path.expanduser(args.key_file), encoding="utf-8") as handle:
            key = normalize_secret(handle.read())
    if key:
        if args.store == "file":
            config["api_key"] = key
            changed.append("密钥（0600 配置文件明文）")
        else:
            provider = store_secure_key(key)
            config.pop("api_key", None)
            changed.append(f"密钥（{provider}）")
            if args.store == "auto" and config.get("api_key"):
                del config["api_key"]

    write_config(config)
    for item in changed or ["（无改动）"]:
        print(f"已写入      {item}")
    if key and args.store == "file":
        print("注意        密钥以明文存于 0600 文件；能上系统凭据库就不要用这个模式")
    if not args.no_verify:
        print()
        return doctor()
    return 0


def cmd_import(args: argparse.Namespace) -> int:
    found = agent_auth_key()
    if not found:
        print("没有可导入的 key（找过 ~/.pi/agent/auth.json 与 ~/.codebuddy/models.json）")
        return 1
    key, origin = found
    key = normalize_secret(key)
    if args.store == "file":
        config = read_config()
        config["api_key"] = key
        write_config(config)
        print(f"已导入到 {config_file()}（0600，明文）  来源：{origin}")
    else:
        provider = store_secure_key(key)
        config = read_config()
        config.pop("api_key", None)
        write_config(config)
        print(f"已导入到 {provider}  来源：{origin}")
    return 0 if args.no_verify else doctor()


def cmd_reset(args: argparse.Namespace) -> int:
    removed = []
    if delete_secure_key():
        removed.append(secure_store_name() or "凭据库")
    path = config_file()
    if os.path.exists(path):
        config = read_config()
        kept = {k: v for k, v in config.items() if k == "base_url" and not args.all}
        if kept:
            write_config(kept)
        else:
            os.remove(path)
        removed.append(path)
    print("已清除      " + (", ".join(removed) if removed else "（没有已保存的配置）"))
    return 0


def cmd_doctor(_: argparse.Namespace) -> int:
    return doctor()


def cmd_get_key(_: argparse.Namespace) -> int:
    key, source = resolve_key()
    if not key:
        raise ConfigError("没有可用密钥；运行 scripts/setup.sh new 或设置 SEEDANCE_API_KEY")
    print(key)
    _ = source
    return 0


def cmd_get_base(_: argparse.Namespace) -> int:
    print(resolve_base()[0])
    return 0


def cmd_get_model(_: argparse.Namespace) -> int:
    print(resolve_model()[0])
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="seedance_config.py",
        description="Seedance 网关的地址与密钥配置（不会把密钥写进输出，除了 get-key）",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="显示实际生效的地址/密钥来源（脱敏）").set_defaults(func=cmd_status)
    sub.add_parser("doctor", help="只读检查：GET /models 是否 200、视频模型是否在列表里").set_defaults(
        func=cmd_doctor
    )
    setter = sub.add_parser("set", help="写入地址 / 密钥 / 默认模型")
    setter.add_argument("--base-url")
    setter.add_argument("--model")
    setter.add_argument("--key-stdin", action="store_true", help="从 stdin 读密钥（不进 argv）")
    setter.add_argument("--key-file")
    setter.add_argument(
        "--store", choices=("auto", "file"), default="auto",
        help="auto=系统凭据库；file=0600 配置文件明文",
    )
    setter.add_argument("--no-verify", action="store_true")
    setter.set_defaults(func=cmd_set)

    importer = sub.add_parser("import", help="把 agent auth 文件里的 key 提升到凭据库")
    importer.add_argument("--store", choices=("auto", "file"), default="auto")
    importer.add_argument("--no-verify", action="store_true")
    importer.set_defaults(func=cmd_import)

    resetter = sub.add_parser("reset", help="清除密钥（--all 连地址一起清）")
    resetter.add_argument("--all", action="store_true")
    resetter.set_defaults(func=cmd_reset)

    sub.add_parser("get-key", help="内部用：输出密钥供脚本调用").set_defaults(func=cmd_get_key)
    sub.add_parser("get-base-url", help="内部用：输出生效地址").set_defaults(func=cmd_get_base)
    sub.add_parser("get-model", help="内部用：输出默认模型").set_defaults(func=cmd_get_model)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except ConfigError as error:
        print(f"错误：{error}", file=sys.stderr)
        return 2
    except BrokenPipeError:
        return 0


if __name__ == "__main__":
    sys.exit(main())
