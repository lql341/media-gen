"""配置文件与路径：profile 文件、自定义模板、JSON 读写、校验。"""

from __future__ import annotations

import json
import os
import re


PROTOCOLS = ("openai", "azure", "ark", "dashscope", "minimax", "custom", "command")


SERVICE = "media-gen"


LEGACY_SERVICE = "seedance-gateway"


ENV_KEY = ("MEDIA_API_KEY", "SEEDANCE_API_KEY")


ENV_BASE = ("MEDIA_BASE_URL", "SEEDANCE_BASE_URL")


PROFILE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$")


ACCOUNT_RE = PROFILE_RE


class ConfigError(RuntimeError):
    """A user-facing configuration or credential failure."""


def split_profile_spec(spec: str) -> tuple[str, str | None]:
    """`litellm@team` → ("litellm", "team")；没有 @ 时账户为 None。"""
    text = str(spec or "").strip()
    if not text:
        return "", None
    if "@" not in text:
        return text, None
    name, _, account = text.partition("@")
    if not name or not account:
        raise ConfigError(f"配置档写法应为 <name>@<account>：{spec}")
    return name, account


def store_item_name(profile: str, account: str | None) -> str:
    """凭据库里的 account 字段：默认账户用档案名，别名用 `<profile>@<account>`。"""
    return f"{profile}@{account}" if account else profile


def pathlib_read(path: str) -> str:
    with open(os.path.expanduser(path), encoding="utf-8") as handle:
        return handle.read()


def parse_pairs(values: list[str] | None) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for item in values or []:
        key, separator, value = str(item).partition("=")
        if not separator or not key.strip():
            raise ConfigError(f"需要 K=V 形式：{item}")
        parsed[key.strip()] = value.strip()
    return parsed


def validate_base_url(protocol: str, base: str) -> str:
    """command 协议可以拿占位地址（如 unused://inhouse），其余必须是 http(s)。"""
    base = base.strip().rstrip("/")
    if not base:
        raise ConfigError("--base-url 不能为空")
    if protocol == "command":
        if "://" not in base:
            raise ConfigError("command 协议的 --base-url 只是标识，可以是 unused://<name>")
        return base
    if not re.match(r"^https?://", base):
        raise ConfigError("--base-url 必须是 http(s):// 开头的绝对地址")
    return base


def config_dir() -> str:
    xdg = os.environ.get("XDG_CONFIG_HOME", "")
    root = xdg if xdg.startswith("/") else os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(root, "media-gen")


def config_file() -> str:
    return os.path.join(config_dir(), "config.json")


def custom_spec_path(profile: str) -> str:
    return os.path.join(config_dir(), "custom", f"{profile}.json")


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


