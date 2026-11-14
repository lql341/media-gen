"""media-gen configuration: named endpoints (profiles) + credentials.

The skill is not tied to one gateway. A *profile* is one endpoint plus the wire
protocol it speaks; a *model* is resolved to a kind (image/video) by the
registry, and the profile decides how the request is encoded.

    ~/.config/media-gen/config.json
    {
      "default": "litellm",
      "profiles": {
        "litellm":   {"protocol": "openai",    "base_url": "https://gw.example/v1"},
        "ark":       {"protocol": "ark",       "base_url": "https://ark.cn-beijing.volces.com/api/v3"},
        "dashscope": {"protocol": "dashscope", "base_url": "https://dashscope.aliyuncs.com/api/v1"},
        "minimax":   {"protocol": "minimax",   "base_url": "https://api.minimaxi.com/v1"}
      }
    }

Secrets never live in that file unless the user explicitly asks for it
(``--store file``). Default is the OS credential store, item per profile:
service ``media-gen``, account ``<profile>``. Environment variables always win:

    MEDIA_API_KEY / MEDIA_API_KEY_<PROFILE> / MEDIA_BASE_URL / MEDIA_PROFILE
    (legacy: SEEDANCE_API_KEY, LEGACY_API_KEY, SEEDANCE_BASE_URL, LEGACY_BASE_URL)

Legacy seedance installs keep working: the Keychain item ``seedance-gateway``,
``~/.config/seedance/config.json`` and the old env vars are read as fallbacks.
"""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request

SERVICE = "media-gen"
LEGACY_SERVICE = "seedance-gateway"
PROTOCOLS = ("openai", "ark", "dashscope", "minimax")

ENV_KEY = ("MEDIA_API_KEY", "SEEDANCE_API_KEY", "LEGACY_API_KEY")
ENV_BASE = ("MEDIA_BASE_URL", "SEEDANCE_BASE_URL", "LEGACY_BASE_URL")
PROFILE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$")


class ConfigError(RuntimeError):
    """A user-facing configuration or credential failure."""


# ------------------------------------------------------------------ locations


def config_dir() -> str:
    xdg = os.environ.get("XDG_CONFIG_HOME", "")
    root = xdg if xdg.startswith("/") else os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(root, "media-gen")


def config_file() -> str:
    return os.path.join(config_dir(), "config.json")


def registry_override_file() -> str:
    return os.path.join(config_dir(), "registry.json")


def legacy_config_file() -> str:
    xdg = os.environ.get("XDG_CONFIG_HOME", "")
    root = xdg if xdg.startswith("/") else os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(root, "seedance", "config.json")


def read_json(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as error:
        raise ConfigError(f"配置文件无法解析（{path}）：{error}") from None
    return data if isinstance(data, dict) else {}


def write_json(path: str, data: dict) -> None:
    directory = os.path.dirname(path)
    os.makedirs(directory, mode=0o700, exist_ok=True)
    os.chmod(directory, 0o700)
    temporary = path + ".tmp"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def read_config() -> dict:
    return read_json(config_file())


def write_config(data: dict) -> None:
    write_json(config_file(), data)


# ------------------------------------------------------------------- profiles


def _legacy_profile() -> dict:
    """Build a profile out of a pre-media-gen seedance install, if any."""
    config = read_json(legacy_config_file())
    base = config.get("base_url")
    if not isinstance(base, str) or not base.strip():
        return {}
    return {"protocol": "openai", "base_url": base.strip().rstrip("/")}


def profiles() -> dict[str, dict]:
    config = read_config()
    found = config.get("profiles")
    found = found if isinstance(found, dict) else {}
    if not found:
        legacy = _legacy_profile()
        if legacy:
            return {"legacy": legacy}
        return {}
    return {name: value for name, value in found.items() if isinstance(value, dict)}


def active_profile_name(explicit: str | None = None) -> str | None:
    if explicit:
        if explicit not in profiles():
            raise ConfigError(
                f"没有名为 {explicit} 的配置档；已有：{', '.join(sorted(profiles())) or '（空）'}"
            )
        return explicit
    env = os.environ.get("MEDIA_PROFILE", "").strip()
    if env:
        return active_profile_name(env)
    config = read_config()
    default = config.get("default")
    if isinstance(default, str) and default in profiles():
        return default
    names = sorted(profiles())
    if len(names) == 1:
        return names[0]
    return None


def env_only_profile() -> dict | None:
    """MEDIA_BASE_URL alone (no saved profile) is enough to run — handy in CI."""
    base = os.environ.get("MEDIA_BASE_URL", "").strip() or os.environ.get("SEEDANCE_BASE_URL", "").strip()
    if not base:
        return None
    protocol = os.environ.get("MEDIA_PROTOCOL", "openai").strip() or "openai"
    if protocol not in PROTOCOLS:
        raise ConfigError(f"MEDIA_PROTOCOL={protocol} 不受支持（可选：{', '.join(PROTOCOLS)}）")
    return {"protocol": protocol, "base_url": base.rstrip("/")}


def require_profile(explicit: str | None = None) -> tuple[str, dict]:
    name = active_profile_name(explicit)
    if not name:
        from_env = env_only_profile()
        if from_env and not explicit:
            return "env", from_env
        available = sorted(profiles())
        if available:
            raise ConfigError(
                f"有多个配置档，请指定 --profile（可选：{', '.join(available)}）或先 setup.sh use <name>"
            )
        raise ConfigError(
            "还没有任何配置档；运行 scripts/setup.sh add <name> --protocol <openai|ark|dashscope|minimax> "
            "--base-url https://host/v1"
        )
    profile = dict(profiles()[name])
    protocol = str(profile.get("protocol", "openai"))
    if protocol not in PROTOCOLS:
        raise ConfigError(f"配置档 {name} 的 protocol={protocol} 不受支持（可选：{', '.join(PROTOCOLS)}）")
    profile["protocol"] = protocol
    base = profile.get("base_url")
    override = os.environ.get("MEDIA_BASE_URL", "").strip() or os.environ.get("SEEDANCE_BASE_URL", "").strip()
    if override:
        base = override
    if not isinstance(base, str) or not base.strip():
        raise ConfigError(f"配置档 {name} 缺少 base_url；用 setup.sh add 重新配置")
    profile["base_url"] = base.strip().rstrip("/")
    return name, profile


# ---------------------------------------------------------------- credentials


def normalize_secret(value: str, label: str = "API Key") -> str:
    value = value.strip().lstrip("\ufeff")
    if len(value) >= 2 and (value[0], value[-1]) in {('"', '"'), ("'", "'"), ("“", "”")}:
        value = value[1:-1].strip()
    if not value:
        raise ConfigError(f"{label} 不能为空。")
    if re.match(r"(?i)^(export\s|set\s|\$env:|MEDIA_|SEEDANCE_|LEGACY_|(?:api[_-]?key|token)\s*[:=])", value):
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
        raise ConfigError("系统凭据操作失败或超时；请检查密钥环服务是否已解锁。") from None


def _read_store(service: str, account: str) -> str | None:
    provider = secure_store_name()
    if provider == "macOS Keychain":
        command = ["security", "find-generic-password", "-s", service, "-a", account, "-w"]
    elif provider == "Secret Service":
        command = ["secret-tool", "lookup", "service", service, "account", account]
    else:
        return None
    completed = _run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False)
    if completed.returncode != 0 or not completed.stdout.strip():
        return None
    try:
        payload = json.loads(completed.stdout)
    except ValueError:
        return None
    key = payload.get("api_key") if isinstance(payload, dict) else None
    return key if isinstance(key, str) and key else None


def store_key(profile: str, key: str) -> str:
    provider = secure_store_name()
    payload = json.dumps({"api_key": key}, separators=(",", ":"))
    if provider == "macOS Keychain":
        command = ["security", "add-generic-password", "-U", "-s", SERVICE, "-a", profile, "-w", payload]
        completed = _run(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, check=False)
    elif provider == "Secret Service":
        command = [
            "secret-tool", "store", "--label=media-gen API key", "service", SERVICE, "account", profile,
        ]
        completed = _run(
            command, input=payload, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, check=False
        )
    else:
        raise ConfigError(
            "本机没有可用的系统凭据库（macOS Keychain / secret-tool）；"
            "用环境变量 MEDIA_API_KEY 注入，或 setup.sh add --store file（0600 明文）"
        )
    if completed.returncode != 0:
        raise ConfigError(f"写入 {provider} 失败（exit={completed.returncode}）；请检查解锁状态。")
    return str(provider)


def delete_key(profile: str) -> bool:
    provider = secure_store_name()
    if provider == "macOS Keychain":
        command = ["security", "delete-generic-password", "-s", SERVICE, "-a", profile]
    elif provider == "Secret Service":
        command = ["secret-tool", "clear", "service", SERVICE, "account", profile]
    else:
        return False
    completed = _run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True, check=False)
    return completed.returncode == 0


def agent_auth_key() -> tuple[str, str] | None:
    """Read-only fallback: reuse a key an agent already manages locally."""
    for pattern in ("~/.pi/agent/auth.json", "~/.codebuddy/models.json", "~/.workbuddy/models.json"):
        path = os.path.expanduser(pattern)
        data = read_json(path) if os.path.exists(path) else {}
        if not data:
            continue
        if isinstance(data.get("legacyprov"), dict):
            key = data["legacyprov"].get("key")
            if isinstance(key, str) and key:
                return key, f"{path}:legacyprov"
        models = data.get("models") if isinstance(data.get("models"), list) else data
        for model in models or []:
            if isinstance(model, dict) and "example.com" in str(model.get("url", "")) and model.get("apiKey"):
                return str(model["apiKey"]), f"{path}:models[]"
    return None


def resolve_key(profile_name: str, profile: dict) -> tuple[str | None, str]:
    env_specific = f"MEDIA_API_KEY_{re.sub(r'[^A-Za-z0-9]', '_', profile_name).upper()}"
    for name in (env_specific, *ENV_KEY):
        value = os.environ.get(name, "")
        if value:
            return normalize_secret(value, name), name
    stored = _read_store(SERVICE, profile_name)
    if stored:
        return stored, secure_store_name() or "credential store"
    if profile_name == "legacy":
        stored = _read_store(LEGACY_SERVICE, "default")
        if stored:
            return stored, f"{secure_store_name()}（旧条目 {LEGACY_SERVICE}）"
    inline = profile.get("api_key")
    if isinstance(inline, str) and inline:
        return normalize_secret(inline), f"{config_file()} (0600, 明文，--store file)"
    found = agent_auth_key()
    if found:
        key, origin = found
        return normalize_secret(key), f"{origin}（只读导入）"
    return None, "未配置"


def mask(secret: str) -> str:
    if len(secret) <= 10:
        return "已配置（短密钥不显示尾部）"
    return f"已配置 …{secret[-4:]}"


# --------------------------------------------------------------------- doctor


def _error_text(error: urllib.error.HTTPError) -> str:
    try:
        body = error.read().decode("utf-8", "replace")
        parsed = json.loads(body)
        message = parsed.get("error", parsed)
        if isinstance(message, dict):
            message = message.get("message") or message.get("msg")
        return str(message) if message else body[:200]
    except Exception:  # noqa: BLE001 - diagnostics only
        return "（响应无正文）"


def probe_models(profile: dict, key: str, timeout: int = 20) -> list[str] | None:
    """Return the model list when the endpoint exposes one, else None."""
    url = profile["base_url"] + "/models"
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as error:
        if error.code in (404, 405):
            return None
        raise ConfigError(f"GET /models 返回 {error.code}：{_error_text(error)}") from None
    except (urllib.error.URLError, OSError) as error:
        raise ConfigError(f"连不上 {profile['base_url']}：{getattr(error, 'reason', error)}") from None
    data = payload.get("data") if isinstance(payload, dict) else None
    if isinstance(data, list):
        return [entry.get("id") for entry in data if isinstance(entry, dict) and entry.get("id")]
    return None


def _manage(args) -> int:
    """Profile lifecycle: add / use / rm / list / migrate."""
    if args.command == "list":
        config = read_config()
        default = config.get("default")
        found = profiles()
        if not found:
            print("（还没有配置档；setup.sh add <name> --protocol … --base-url …）")
            return 0
        for name in sorted(found):
            mark = "*" if name == default else " "
            profile = found[name]
            # 用完整解析（含旧条目 / agent 导入），否则会误报“无密钥”
            stored = resolve_key(name, profile)[0] is not None
            print(
                f"{mark} {name:<12} {profile.get('protocol', 'openai'):<10} {profile.get('base_url', '')}"
                + ("  密钥已存" if stored else "  无密钥")
            )
        return 0

    if args.command == "use":
        config = read_config()
        if args.name not in profiles():
            raise ConfigError(f"没有名为 {args.name} 的配置档")
        config["default"] = args.name
        write_config(config)
        print(f"默认配置档 → {args.name}")
        return 0

    if args.command == "rm":
        config = read_config()
        found = config.get("profiles") or {}
        if args.name not in found:
            raise ConfigError(f"没有名为 {args.name} 的配置档")
        del found[args.name]
        config["profiles"] = found
        if config.get("default") == args.name:
            config.pop("default", None)
        write_config(config)
        removed_key = False if args.keep_key else delete_key(args.name)
        print(f"已删除配置档 {args.name}" + ("，并清除其密钥" if removed_key else ""))
        return 0

    if args.command == "migrate":
        legacy = _legacy_profile()
        old_key = _read_store(LEGACY_SERVICE, "default")
        if not legacy and not old_key:
            found = agent_auth_key()
            if not found:
                print("没有可迁移的旧配置（既无 ~/.config/seedance/config.json，也无旧 Keychain 条目）")
                return 1
            legacy = {"protocol": "openai", "base_url": os.environ.get(ENV_BASE[1], "")}
            old_key = found[0]
            legacy_source = found[1]
        else:
            legacy_source = legacy_config_file() if legacy else f"{secure_store_name()}（{LEGACY_SERVICE}）"
        if not legacy.get("base_url"):
            raise ConfigError("旧配置里没有 base_url；用 setup.sh add 手动配置")
        config = read_config()
        found = config.get("profiles")
        found = found if isinstance(found, dict) else {}
        found[args.name] = {
            "protocol": "openai",
            "base_url": legacy["base_url"].rstrip("/"),
            "default_models": {"video": "doubao-seedance-2-5"},
        }
        config["profiles"] = found
        if not config.get("default"):
            config["default"] = args.name
        write_config(config)
        if old_key:
            old_key = normalize_secret(old_key)
            if args.store == "file":
                current = read_config()
                current["profiles"][args.name]["api_key"] = old_key
                write_config(current)
                print(f"密钥已写入 {config_file()}（0600 明文）")
            else:
                print(f"密钥已写入 {store_key(args.name, old_key)}")
        print(f"已迁移到配置档 {args.name}（来源：{legacy_source}）")
        return 0

    # add
    if not PROFILE_RE.match(args.name):
        raise ConfigError("配置档名只能包含字母、数字、点、下划线、横线（最多 32 字符）")
    config = read_config()
    found = config.get("profiles")
    found = found if isinstance(found, dict) else {}
    entry = dict(found.get(args.name) or {})
    entry["protocol"] = args.protocol
    base = args.base_url.strip().rstrip("/")
    if not re.match(r"^https?://", base):
        raise ConfigError("--base-url 必须是 http(s):// 开头的绝对地址")
    entry["base_url"] = base
    defaults = dict(entry.get("default_models") or {})
    if args.default_image:
        defaults["image"] = args.default_image
    if args.default_video:
        defaults["video"] = args.default_video
    if defaults:
        entry["default_models"] = defaults
    key = None
    if args.key_stdin:
        key = normalize_secret(sys.stdin.read())
    elif args.key_file:
        with open(os.path.expanduser(args.key_file), encoding="utf-8") as handle:
            key = normalize_secret(handle.read())
    if key:
        if args.store == "file":
            entry["api_key"] = key
        else:
            entry.pop("api_key", None)
            print(f"密钥已写入 {store_key(args.name, key)}")
    elif entry.get("api_key") and args.store == "auto":
        raise ConfigError("配置里已有明文 api_key；要用系统凭据库请先 setup.sh rm 再重新添加")
    found[args.name] = entry
    config["profiles"] = found
    if args.set_default or not config.get("default"):
        config["default"] = args.name
    write_config(config)
    print(f"已写入配置档 {args.name}（{args.protocol} · {base}）")
    if args.store == "file" and key:
        print("注意      密钥以明文存于 0600 文件；能上系统凭据库就不要用这个模式")
    return 0


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="media_config.py", description="media-gen 配置与凭据")
    sub = parser.add_subparsers(dest="command", required=True)
    p_status = sub.add_parser("status", help="显示配置档与凭据来源（脱敏）")
    p_status.add_argument("--profile")
    p_key = sub.add_parser("get-key", help="内部用：输出密钥")
    p_key.add_argument("--profile")
    p_base = sub.add_parser("get-base-url", help="内部用：输出地址")
    p_base.add_argument("--profile")
    p_proto = sub.add_parser("get-protocol", help="内部用：输出 protocol")
    p_proto.add_argument("--profile")
    p_add = sub.add_parser("add", help="新增/更新配置档")
    p_add.add_argument("name")
    p_add.add_argument("--protocol", required=True, choices=PROTOCOLS)
    p_add.add_argument("--base-url", required=True)
    p_add.add_argument("--store", choices=("auto", "file"), default="auto")
    p_add.add_argument("--key-stdin", action="store_true")
    p_add.add_argument("--key-file")
    p_add.add_argument("--default-image")
    p_add.add_argument("--default-video")
    p_add.add_argument("--set-default", action="store_true")
    p_use = sub.add_parser("use", help="设为默认配置档")
    p_use.add_argument("name")
    p_rm = sub.add_parser("rm", help="删除配置档")
    p_rm.add_argument("name")
    p_rm.add_argument("--keep-key", action="store_true")
    sub.add_parser("list", help="列出配置档")
    p_mig = sub.add_parser("migrate", help="把旧的 seedance 配置/凭据迁到 media-gen")
    p_mig.add_argument("--name", default="legacy")
    p_mig.add_argument("--store", choices=("auto", "file"), default="auto")
    args = parser.parse_args(argv)

    try:
        if args.command in ("add", "use", "rm", "list", "migrate"):
            return _manage(args)
        name, profile = require_profile(args.profile)
        key, key_source = resolve_key(name, profile)
        if args.command == "get-key":
            if not key:
                raise ConfigError("没有可用密钥；运行 scripts/setup.sh add <name> ... 或设置 MEDIA_API_KEY")
            print(key)
            return 0
        if args.command == "get-base-url":
            print(profile["base_url"])
            return 0
        if args.command == "get-protocol":
            print(profile["protocol"])
            return 0
        print(f"配置目录    {config_dir()}")
        print(f"配置档      {name}")
        print(f"protocol    {profile['protocol']}")
        print(f"地址        {profile['base_url']}")
        print(f"密钥        {mask(key) if key else '未配置'}")
        print(f"密钥来源    {key_source}")
        others = [p for p in sorted(profiles()) if p != name]
        print(f"其它配置档  {', '.join(others) if others else '（无）'}")
        print(f"系统凭据库  {secure_store_name() or '不可用（用环境变量或 --store file）'}")
        return 0 if key else 1
    except ConfigError as error:
        print(f"错误：{error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
