"""profile 组合：默认档、账户（@alias）、环境变量与旧版 seedance 兼容。"""

from __future__ import annotations

import os

from .paths import *  # noqa: F401,F403

def _legacy_profile() -> dict:
    """Build a profile out of a pre-media-gen seedance install, if any."""
    config = read_json(legacy_config_file())
    base = config.get("base_url")
    if not isinstance(base, str) or not base.strip():
        return {}
    profile = {"protocol": "openai", "base_url": base.strip().rstrip("/")}
    # 旧配置里的 model 字段就是默认视频模型，继承过来免得用户重填
    model = config.get("model")
    if isinstance(model, str) and model.strip():
        profile["default_models"] = {"video": model.strip()}
    return profile


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
    if isinstance(default, str) and default:
        default_name, _ = split_profile_spec(default)
        if default_name in profiles():
            return default_name
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


def apply_account(profile_name: str, profile: dict, account: str | None) -> dict:
    """把 accounts.<alias> 的覆盖（base_url / default_models / credential_ref）叠上去。"""
    if not account:
        return profile
    if not ACCOUNT_RE.match(account):
        raise ConfigError(f"账户别名只能用字母、数字、点、下划线、横线（≤32）：{account}")
    accounts = profile.get("accounts")
    accounts = accounts if isinstance(accounts, dict) else {}
    override = accounts.get(account)
    if not isinstance(override, dict):
        raise ConfigError(
            f"配置档 {profile_name} 没有账户 {account}；已有账户：{', '.join(sorted(accounts)) or '（无）'}。"
            f"新增：setup.sh add {profile_name} --account {account} --protocol … --base-url …"
        )
    merged = dict(profile)
    # 具名账户不继承默认账户的密钥/条目引用（只有它自己声明的才算）
    merged.pop("api_key", None)
    merged.pop("credential_ref", None)
    for key in ("base_url", "credential_ref", "default_models", "api_key"):
        if key in override:
            merged[key] = override[key]
    merged["_account"] = account
    return merged


def require_profile(explicit: str | None = None) -> tuple[str, dict]:
    raw = explicit or os.environ.get("MEDIA_PROFILE", "").strip()
    if not raw:
        configured_default = read_config().get("default")
        raw = configured_default if isinstance(configured_default, str) else ""
    spec_name, spec_account = split_profile_spec(raw) if raw else ("", None)
    name = active_profile_name(spec_name or None)
    if not name:
        if spec_account or os.environ.get("MEDIA_ACCOUNT", "").strip():
            raise ConfigError(
                "还没有任何配置档，无法选择账户；先 setup.sh add <name> --protocol … --base-url … --account <alias>"
            )
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
            "--base-url https://host/v1（custom/command 见 references/custom-endpoints.md）"
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
    account = spec_account or (os.environ.get("MEDIA_ACCOUNT", "").strip() or None)
    if account:
        profile = apply_account(name, profile, account)
        return f"{name}@{account}", profile
    return name, profile


