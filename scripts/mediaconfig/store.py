"""凭据：系统凭据库 / 0600 文件 / 环境变量，解析顺序与删除闸门。"""

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

from .paths import *  # noqa: F401,F403

def normalize_secret(value: str, label: str = "API Key") -> str:
    value = value.strip().lstrip("\ufeff")
    if len(value) >= 2 and (value[0], value[-1]) in {('"', '"'), ("'", "'"), ("“", "”")}:
        value = value[1:-1].strip()
    if not value:
        raise ConfigError(f"{label} 不能为空。")
    if re.match(r"(?i)^(export\s|set\s|\$env:|MEDIA_|SEEDANCE_|(?:api[_-]?key|token)\s*[:=])", value):
        raise ConfigError(f"{label} 收到了变量赋值或字段名；请只粘贴值本身。")
    if re.match(r"(?i)^authorization\s*:", value):
        raise ConfigError(f"{label} 收到了整行 Authorization 头；请只粘贴 Bearer 后面的值。")
    if any(character.isspace() or ord(character) < 32 for character in value):
        raise ConfigError(f"{label} 含空白或换行，请重新复制。")
    return value


_STORE_CACHE: dict[tuple[str, str], str | None] = {}


def credential_store_mode() -> str:
    value = os.environ.get("MEDIA_CREDENTIAL_STORE", "auto").strip().lower()
    if os.environ.get("MEDIA_NO_KEYCHAIN", "").strip() in ("1", "true", "yes"):
        return "none"
    return value if value in ("auto", "file", "none") else "auto"


def secure_store_name() -> str | None:
    if credential_store_mode() == "none":
        return None
    if platform.system() == "Darwin" and shutil.which("security"):
        return "macOS Keychain"
    if shutil.which("secret-tool"):
        return "Secret Service"
    return None


def _store_has(service: str, account: str) -> bool:
    """Existence check only — unlike _read_store, this never decrypts the secret."""
    provider = secure_store_name()
    if provider is None:
        return False
    if provider == "macOS Keychain":
        command = ["security", "find-generic-password", "-s", service, "-a", account]
    else:
        command = ["secret-tool", "lookup", "service", service, "account", account]
    _debug_store(f"exists {service}/{account} via {provider}")
    completed = _run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True, check=False)
    return completed.returncode == 0


def _debug_store(message: str) -> None:
    if os.environ.get("MEDIA_DEBUG_STORE", "").strip() in ("1", "true", "yes"):
        print(f"store: {message}", file=sys.stderr)


def _run(command: list[str], **options) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(command, timeout=30, **options)
    except (OSError, subprocess.TimeoutExpired):
        raise ConfigError("系统凭据操作失败或超时；请检查密钥环服务是否已解锁。") from None


def _read_store(service: str, account: str) -> str | None:
    key = (service, account)
    if key in _STORE_CACHE:
        return _STORE_CACHE[key]
    provider = secure_store_name()
    if provider is None:
        _debug_store(f"skip {service}/{account}（MEDIA_CREDENTIAL_STORE={credential_store_mode()}）")
        _STORE_CACHE[key] = None
        return None
    _debug_store(f"read {service}/{account} via {provider}")
    value = _read_store_uncached(service, account, provider)
    _STORE_CACHE[key] = value
    return value


def _read_store_uncached(service: str, account: str, provider: str) -> str | None:
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


def store_key(profile: str, key: str, account: str | None = None) -> str:
    if credential_store_mode() == "none":
        raise ConfigError(
            "MEDIA_CREDENTIAL_STORE=none：本进程不会写系统凭据库；"
            "改用环境变量 MEDIA_API_KEY 或 --store file"
        )
    item = store_item_name(profile, account)
    provider = secure_store_name()
    payload = json.dumps({"api_key": key}, separators=(",", ":"))
    if provider == "macOS Keychain":
        command = ["security", "add-generic-password", "-U", "-s", SERVICE, "-a", item, "-w", payload]
        completed = _run(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, check=False)
    elif provider == "Secret Service":
        command = [
            "secret-tool", "store", "--label=media-gen API key", "service", SERVICE, "account", item,
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


def delete_allowed() -> bool:
    """Deleting a stored secret is opt-in via MEDIA_ALLOW_CREDENTIAL_DELETE=1 (no implicit path)."""
    return os.environ.get("MEDIA_ALLOW_CREDENTIAL_DELETE", "").strip() == "1"


def describe_delete(profile: str) -> str:
    provider = secure_store_name()
    if provider == "macOS Keychain":
        return f'security delete-generic-password -s {SERVICE} -a {profile}'
    if provider == "Secret Service":
        return f'secret-tool clear service {SERVICE} account {profile}'
    return "（本机没有可用的系统凭据库）"


def _delete_store_item(service: str, account: str) -> bool:
    provider = secure_store_name()
    if provider is None:
        return False
    _STORE_CACHE.pop((service, account), None)
    if provider == "macOS Keychain":
        command = ["security", "delete-generic-password", "-s", service, "-a", account]
    else:
        command = ["secret-tool", "clear", "service", service, "account", account]
    _debug_store(f"delete {service}/{account}")
    completed = _run(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, check=False)
    return completed.returncode == 0


def delete_key(profile: str, account: str | None = None) -> bool:
    """Delete one profile's secret. Never runs unless MEDIA_ALLOW_CREDENTIAL_DELETE=1."""
    if not delete_allowed():
        raise ConfigError(
            "未删除凭据库条目（默认保护）。如需删除，显式执行：\n"
            f"  MEDIA_ALLOW_CREDENTIAL_DELETE=1 {sys.argv[0]} rm {profile}\n"
            f"  或手工：{describe_delete(profile)}"
        )
    return _delete_store_item(SERVICE, store_item_name(profile, account))


def agent_auth_key() -> tuple[str, str] | None:
    """Read-only fallback: reuse a key an agent already manages locally.

    Which provider to look for is a deployment detail, not a hardcoded vendor name:
    set ``MEDIA_AGENT_AUTH_PROVIDER`` (e.g. the provider id used in that agent's
    auth file) and, optionally, ``MEDIA_AGENT_AUTH_BASE_HOST`` to match a model
    list entry by URL host. Without them the import is off.
    """
    provider = os.environ.get("MEDIA_AGENT_AUTH_PROVIDER", "").strip()
    host = os.environ.get("MEDIA_AGENT_AUTH_BASE_HOST", "").strip()
    if not provider and not host:
        return None
    for pattern in ("~/.pi/agent/auth.json", "~/.codebuddy/models.json", "~/.workbuddy/models.json"):
        path = os.path.expanduser(pattern)
        data = read_json(path) if os.path.exists(path) else {}
        if not data:
            continue
        if provider and isinstance(data.get(provider), dict):
            key = data[provider].get("key")
            if isinstance(key, str) and key:
                return key, f"{path}:{provider}"
        if host:
            models = data.get("models") if isinstance(data.get("models"), list) else data
            for model in models or []:
                if isinstance(model, dict) and host in str(model.get("url", "")) and model.get("apiKey"):
                    return str(model["apiKey"]), f"{path}:models[]"
    return None


def parse_credential_ref(value: str) -> tuple[str, str]:
    """`service:account`（account 省略时取 default）。"""
    text = str(value).strip()
    service, _, account = text.partition(":")
    if not service:
        raise ConfigError("credential_ref 需要 service:account，例如 seedance-gateway:default")
    return service, (account or "default")


def resolve_key(profile_name: str, profile: dict) -> tuple[str | None, str]:
    profile_base, spec_account = split_profile_spec(profile_name)
    profile_name = profile_base or profile_name
    account = profile.get("_account") or spec_account
    suffix = re.sub(r"[^A-Za-z0-9]", "_", str(account or "")).upper()
    names = []
    if suffix:
        names.append(f"MEDIA_API_KEY_{re.sub(r'[^A-Za-z0-9]', '_', profile_name).upper()}_{suffix}")
    names.append(f"MEDIA_API_KEY_{re.sub(r'[^A-Za-z0-9]', '_', profile_name).upper()}")
    names.extend(ENV_KEY)
    for name in names:
        value = os.environ.get(name, "")
        if value:
            return normalize_secret(value, name), name
    ref = profile.get("credential_ref")
    if isinstance(ref, str) and ref:
        service, account = parse_credential_ref(ref)
        stored = _read_store(service, account)
        if stored:
            return stored, f"{secure_store_name() or 'credential store'}（复用条目 {service}/{account}）"
    item = store_item_name(profile_name, account)
    stored = _read_store(SERVICE, item)
    if stored:
        return stored, f"{secure_store_name() or 'credential store'}（{SERVICE}/{item}）"
    if account:
        inline = profile.get("api_key")
        if isinstance(inline, str) and inline:
            return normalize_secret(inline), f"{config_file()}（账户 {profile_name}@{account}，0600 明文）"
        # 具名账户绝不回退到默认账户 / 其它账户的条目
        raise ConfigError(
            f"账户 {profile_name} 的密钥条目 {SERVICE}/{item} 不存在，且具名账户不回退。"
            f"先配置：setup.sh add {profile_name} --account {account} … --key-stdin"
        )
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


def ensure_utf8_stdio() -> None:
    """Windows 控制台默认不是 UTF-8（cp1252/cp936）：中文输出会 UnicodeEncodeError。

    在写任何东西之前把 stdout/stderr 切到 UTF-8；被重定向到 StringIO 时跳过。
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass


def mask(secret: str) -> str:
    if len(secret) <= 10:
        return "已配置（短密钥不显示尾部）"
    return f"已配置 …{secret[-4:]}"


