"""media_config.py 的命令行入口（add / show / rm / export / migrate …）。"""

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
from .profiles import *  # noqa: F401,F403
from .profiles import _legacy_profile
from .store import *  # noqa: F401,F403
from .store import _debug_store, _delete_store_item, _read_store, _store_has
from .probe import *  # noqa: F401,F403

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
            accounts = profile.get("accounts") if isinstance(profile.get("accounts"), dict) else {}
            for account in sorted(accounts):
                merged = apply_account(name, profile, account)
                try:
                    has = resolve_key(f"{name}@{account}", merged)[0] is not None
                except ConfigError:
                    has = False
                print(f"    @{account:<10} {merged.get('base_url', '')}  {'密钥已存' if has else '无密钥'}")
        return 0

    if args.command == "use":
        config = read_config()
        name, account = split_profile_spec(args.name)
        if name not in profiles():
            raise ConfigError(f"没有名为 {name} 的配置档")
        if account:
            apply_account(name, profiles()[name], account)   # 校验账户存在
        config["default"] = f"{name}@{account}" if account else name
        write_config(config)
        print(f"默认配置档 → {args.name}")
        return 0

    if args.command == "rm":
        config = read_config()
        found = config.get("profiles") or {}
        if getattr(args, "all", False):
            names = list(found)
            for name in names:
                if not args.keep_key:
                    try:
                        delete_key(name)
                    except ConfigError as error:
                        _debug_store(f"keep {SERVICE}/{name}：{error}".splitlines()[0])
                spec = custom_spec_path(name)
                if os.path.exists(spec):
                    os.remove(spec)
            config.pop("profiles", None)
            config.pop("default", None)
            write_config(config)
            print(f"已删除 {len(names)} 个配置档" + ("" if args.keep_key else "，并清除其密钥"))
            return 0
        if not args.name:
            raise ConfigError("rm 需要一个配置档名，或用 --all 删除全部")
        if args.name not in found:
            raise ConfigError(f"没有名为 {args.name} 的配置档")
        if getattr(args, "account", None):
            accounts = dict(found[args.name].get("accounts") or {})
            if args.account not in accounts:
                raise ConfigError(f"{args.name} 没有账户 {args.account}")
            accounts.pop(args.account)
            if accounts:
                found[args.name] = {**found[args.name], "accounts": accounts}
            else:
                entry = {k: v for k, v in found[args.name].items() if k != "accounts"}
                found[args.name] = entry
            config["profiles"] = found
            write_config(config)
            removed = False
            if not args.keep_key:
                try:
                    removed = delete_key(args.name, args.account)
                except ConfigError as error:
                    print(f"提示：{str(error).splitlines()[0]}")
            print(f"已删除账户 {args.name}@{args.account}" + ("，并清除其密钥" if removed else ""))
            return 0
        del found[args.name]
        config["profiles"] = found
        if config.get("default") == args.name:
            config.pop("default", None)
        write_config(config)
        removed_key = False
        if not args.keep_key:
            try:
                removed_key = delete_key(args.name)
            except ConfigError as error:
                print(f"提示：{str(error).splitlines()[0]}")
                print(f"      配置已删除，但密钥保留；要一并删除：{describe_delete(args.name)}")
        spec = custom_spec_path(args.name)
        if os.path.exists(spec):
            os.remove(spec)
        print(f"已删除配置档 {args.name}" + ("，并清除其密钥" if removed_key else ""))
        return 0

    if args.command == "migrate":
        legacy = _legacy_profile()
        old_key = _read_store(LEGACY_SERVICE, "default")
        # 密钥来源按优先级：旧凭据库条目 → agent auth 文件（需 MEDIA_AGENT_AUTH_PROVIDER/HOST）
        from_agent = None
        if not old_key:
            from_agent = agent_auth_key()
            if from_agent:
                old_key = from_agent[0]
        if not legacy and not old_key:
            print(
                "没有可迁移的旧配置（既无旧的 seedance 配置文件，也无旧凭据库条目）。\n"
                "  如果密钥在某个 agent 的 auth 文件里，先设置 MEDIA_AGENT_AUTH_PROVIDER（该文件里的 provider 名）\n"
                "  或 MEDIA_AGENT_AUTH_BASE_HOST（models[] 里的 URL 域名片段）再重试。"
            )
            return 1
        if legacy:
            legacy_source = legacy_config_file()
        elif from_agent:
            legacy_source = from_agent[1]
            legacy = {"protocol": "openai", "base_url": os.environ.get("MEDIA_BASE_URL", "").strip()}
        else:
            legacy_source = f"{secure_store_name()}（{LEGACY_SERVICE}）"
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
        if args.delete_legacy:
            if not _store_has(LEGACY_SERVICE, "default"):
                print("旧条目不存在，无需删除")
            elif not delete_allowed():
                print("未删除旧条目（默认保护）：")
                print(f"  MEDIA_ALLOW_CREDENTIAL_DELETE=1 后重跑，或手工执行：")
                print(f"  security delete-generic-password -s {LEGACY_SERVICE} -a default")
            else:
                removed = _delete_store_item(LEGACY_SERVICE, "default")
                print("旧条目已删除" if removed else "旧条目删除失败（请检查解锁状态）")
        elif _store_has(LEGACY_SERVICE, "default"):
            print(f"旧条目 {LEGACY_SERVICE}/default 保留（只读兼容）；要清理见 setup.sh audit")
        return 0

    if args.command == "audit":
        found = profiles()
        print(f"服务名        {SERVICE}（旧：{LEGACY_SERVICE}）")
        print(f"凭据库        {secure_store_name() or '不可用'}")
        print(f"凭据库模式    MEDIA_CREDENTIAL_STORE={credential_store_mode()}")
        print(f"删除闸门      MEDIA_ALLOW_CREDENTIAL_DELETE={'1（允许）' if delete_allowed() else '未设置（默认不删）'}")
        if not found:
            print("配置档        （无）")
        for name in sorted(found):
            accounts = found[name].get("accounts")
            if isinstance(accounts, dict):
                for account in sorted(accounts):
                    item = store_item_name(name, account)
                    exists = "有" if _store_has(SERVICE, item) else "无"
                    print(f"  {name}@{account:<10} 条目: {exists:<2} 删除命令: {describe_delete(name, account)}")
            ref = found[name].get("credential_ref")
            if isinstance(ref, str) and ref:
                service, account = parse_credential_ref(ref)
                exists = "有" if _store_has(service, account) else "无"
                print(f"  {name:<14} 复用条目 {service}/{account}: {exists}（不复制、不删除）")
            else:
                exists = "有" if _store_has(SERVICE, name) else "无"
                print(f"  {name:<14} 条目: {exists:<2} 删除命令: {describe_delete(name)}")
        legacy_exists = _store_has(LEGACY_SERVICE, "default")
        print()
        print(f"旧条目 {LEGACY_SERVICE}/default 条目: {'有' if legacy_exists else '无'}（本工具不会删除它）")
        if legacy_exists:
            print("  本工具不会删除它；要复用/搬家：")
            print(f"    {sys.argv[0]} migrate --to <profile>              # 复制到 media-gen/<profile>")
            print(f"    {sys.argv[0]} migrate --to <profile> --delete-legacy --store auto   # 复制后删除旧条目（需闸门）")
            print(f"    手工删除：MEDIA_ALLOW_CREDENTIAL_DELETE=1 后执行 "
                  f"security delete-generic-password -s {LEGACY_SERVICE} -a default")
        return 0

    if args.command == "show":
        found = profiles()
        if args.name not in found:
            raise ConfigError(f"没有名为 {args.name} 的配置档")
        profile = dict(found[args.name])
        key, key_source = resolve_key(args.name, profile)
        profile.pop("api_key", None)
        cleaned_accounts = {}
        for account_name, account_entry in (profile.get("accounts") or {}).items():
            if not isinstance(account_entry, dict):
                continue
            cleaned = dict(account_entry)
            if cleaned.pop("api_key", None):
                cleaned["api_key"] = "（已隐藏）"
            cleaned_accounts[account_name] = cleaned
        if cleaned_accounts:
            profile["accounts"] = cleaned_accounts
        print(json.dumps({"profile": args.name, "config": profile, "key_source": key_source,
                          "key": mask(key) if key else None}, ensure_ascii=False, indent=2))
        return 0

    if args.command == "set-key":
        if args.name not in profiles():
            raise ConfigError(f"没有名为 {args.name} 的配置档")
        if getattr(args, "account", None):
            apply_account(args.name, profiles()[args.name], args.account)   # 校验账户存在
        key = normalize_secret(sys.stdin.read())
        config = read_config()
        entry = dict((config.get("profiles") or {})[args.name])
        if args.store == "file":
            entry["api_key"] = key
            profiles_block = dict(config.get("profiles") or {})
            profiles_block[args.name] = entry
            config["profiles"] = profiles_block
            write_config(config)
            print(f"密钥已写入 {config_file()}（0600 明文）")
        else:
            provider = store_key(args.name, key, getattr(args, "account", None))
            entry.pop("api_key", None)
            profiles_block = dict(config.get("profiles") or {})
            profiles_block[args.name] = entry
            config["profiles"] = profiles_block
            write_config(config)
            print(f"密钥已写入 {provider}")
        return 0

    if args.command == "set-url":
        config = read_config()
        block = config.get("profiles") or {}
        if args.name not in block:
            raise ConfigError(f"没有名为 {args.name} 的配置档")
        base = validate_base_url(block[args.name].get("protocol", "openai"), args.base_url)
        block[args.name]["base_url"] = base
        config["profiles"] = block
        write_config(config)
        print(f"{args.name} 的地址 → {base}")
        return 0

    if args.command == "set-protocol":
        config = read_config()
        block = config.get("profiles") or {}
        if args.name not in block:
            raise ConfigError(f"没有名为 {args.name} 的配置档")
        entry = dict(block[args.name])
        entry["protocol"] = args.protocol
        entry.pop("custom_file", None)
        entry.pop("command", None)
        if args.protocol == "custom":
            if not args.custom_file:
                raise ConfigError("custom 协议需要 --custom-file")
            spec = read_json(os.path.expanduser(args.custom_file))
            if not isinstance(spec, dict) or not ({"image", "video"} & set(spec)):
                raise ConfigError("模板文件至少要有 image 或 video 段")
            target = custom_spec_path(args.name)
            write_json(target, spec)
            entry["custom_file"] = target
            print(f"模板已复制到 {target}")
        elif args.protocol == "command":
            raw = args.command_json or (pathlib_read(args.command_file) if args.command_file else "")
            if not raw:
                raise ConfigError("command 协议需要 --command-json 或 --command-file")
            try:
                commands = json.loads(raw)
            except ValueError as error:
                raise ConfigError(f"命令表不是合法 JSON：{error}") from None
            entry["command"] = {str(k): str(v) for k, v in commands.items()}
        block[args.name] = entry
        config["profiles"] = block
        write_config(config)
        print(f"{args.name} 的协议 → {args.protocol}")
        return 0

    if args.command == "set-credential-ref":
        config = read_config()
        block = config.get("profiles") or {}
        if args.name not in block:
            raise ConfigError(f"没有名为 {args.name} 的配置档")
        entry = dict(block[args.name])
        value = (args.ref or "").strip()
        if not value:
            entry.pop("credential_ref", None)
            print(f"{args.name} 不再复用外部条目（改回使用 media-gen/{args.name}）")
        else:
            service, account = parse_credential_ref(value)
            if not _store_has(service, account):
                raise ConfigError(f"凭据库条目 {service}/{account} 不存在")
            entry["credential_ref"] = f"{service}:{account}"
            print(f"{args.name} 将复用 {service}/{account}（不复制密钥）")
        block[args.name] = entry
        config["profiles"] = block
        write_config(config)
        return 0

    if args.command == "rename":
        config = read_config()
        block = config.get("profiles") or {}
        if args.old not in block:
            raise ConfigError(f"没有名为 {args.old} 的配置档")
        if not PROFILE_RE.match(args.new):
            raise ConfigError("新名字只能用字母、数字、点、下划线、横线（≤32）")
        if args.new in block:
            raise ConfigError(f"{args.new} 已存在")
        entry = dict(block.pop(args.old))
        block[args.new] = entry
        config["profiles"] = block
        if config.get("default") == args.old:
            config["default"] = args.new
        write_config(config)
        moved_key = False
        stored = _read_store(SERVICE, args.old)
        if stored:
            store_key(args.new, stored)
            delete_key(args.old)
            moved_key = True
        if entry.get("custom_file"):
            old_spec = custom_spec_path(args.old)
            if os.path.exists(old_spec):
                os.replace(old_spec, custom_spec_path(args.new))
                block[args.new]["custom_file"] = custom_spec_path(args.new)
                write_config(config)
        print(f"{args.old} → {args.new}" + ("（密钥条目已搬移）" if moved_key else ""))
        return 0

    if args.command == "export":
        config = read_config()
        block = {}
        for name, entry in (config.get("profiles") or {}).items():
            clean = {key: value for key, value in entry.items() if key != "api_key"}
            if isinstance(clean.get("accounts"), dict):
                clean["accounts"] = {
                    account: {k: v for k, v in account_entry.items() if k != "api_key"}
                    if isinstance(account_entry, dict) else account_entry
                    for account, account_entry in clean["accounts"].items()
                }
            if clean.get("custom_file"):
                clean["custom_file_content"] = read_json(clean["custom_file"])
            block[name] = clean
        print(json.dumps({"version": 1, "default": config.get("default"), "profiles": block},
                         ensure_ascii=False, indent=2))
        return 0

    if args.command == "import":
        payload = read_json(os.path.expanduser(args.file))
        incoming = payload.get("profiles") if isinstance(payload, dict) else None
        if not isinstance(incoming, dict) or not incoming:
            raise ConfigError('导入文件需要 {"profiles": {...}}')
        config = read_config()
        block = dict(config.get("profiles") or {})
        for name, entry in incoming.items():
            if not PROFILE_RE.match(name):
                continue
            entry = dict(entry)
            embedded = entry.pop("custom_file_content", None)
            if embedded:
                write_json(custom_spec_path(name), embedded)
                entry["custom_file"] = custom_spec_path(name)
            block[name] = entry
        config["profiles"] = block
        if payload.get("default") in block and not config.get("default"):
            config["default"] = payload["default"]
        elif not config.get("default") and len(block) == 1:
            config["default"] = next(iter(block))
        write_config(config)
        print(f"已导入 {len(incoming)} 个配置档（密钥需另行 set-key）")
        return 0

    # add
    if not PROFILE_RE.match(args.name):
        raise ConfigError("配置档名只能包含字母、数字、点、下划线、横线（最多 32 字符）")
    config = read_config()
    found = config.get("profiles")
    found = found if isinstance(found, dict) else {}
    entry = dict(found.get(args.name) or {})
    entry["protocol"] = args.protocol
    base = validate_base_url(args.protocol, args.base_url)
    account_flag = getattr(args, "account", None)
    if not (account_flag and isinstance(found.get(args.name), dict)):
        entry["base_url"] = base
    if args.protocol == "custom":
        if not args.custom_file:
            raise ConfigError("custom 协议需要 --custom-file <模板文件>（见 references/custom-endpoints.md）")
        source = os.path.expanduser(args.custom_file)
        with open(source, encoding="utf-8") as handle:
            try:
                spec = json.load(handle)
            except ValueError as error:
                raise ConfigError(f"模板文件不是合法 JSON：{error}") from None
        if not isinstance(spec, dict) or not ({"image", "video"} & set(spec)):
            raise ConfigError("模板文件至少要有 image 或 video 段")
        target = custom_spec_path(args.name)
        write_json(target, spec)
        entry["custom_file"] = target
        print(f"模板已复制到 {target}")
    elif args.protocol == "command":
        if args.command_json:
            try:
                commands = json.loads(args.command_json)
            except ValueError as error:
                raise ConfigError(f"--command-json 不是合法 JSON：{error}") from None
        elif args.command_file:
            commands = json.loads(pathlib_read(args.command_file))
        else:
            raise ConfigError('command 协议需要 --command-json 或 --command-file（至少 create/status/fetch）')
        if not isinstance(commands, dict) or not ({"image", "create"} & set(commands)):
            raise ConfigError("命令表至少要有 image，或 create + status + fetch")
        entry["command"] = {str(k): str(v) for k, v in commands.items()}
    else:
        entry.pop("custom_file", None)
        entry.pop("command", None)

    headers = parse_pairs(getattr(args, "header", None))
    query = parse_pairs(getattr(args, "query", None))
    if headers:
        entry["headers"] = headers
    if query:
        entry["query"] = query
    if args.credential_ref:
        service, account = parse_credential_ref(args.credential_ref)
        if not _store_has(service, account):
            raise ConfigError(f"凭据库条目 {service}/{account} 不存在；先用 audit 确认")
        entry["credential_ref"] = f"{service}:{account}"
        entry.pop("api_key", None)
        print(f"将复用凭据库条目 {service}/{account}（不复制密钥）")
    defaults = dict(entry.get("default_models") or {})
    if args.default_image:
        defaults["image"] = args.default_image
    if args.default_video:
        defaults["video"] = args.default_video
    if getattr(args, "default_speech", None):
        defaults["speech"] = args.default_speech
    if getattr(args, "default_transcription", None):
        defaults["transcription"] = args.default_transcription
    if defaults and not account_flag:
        entry["default_models"] = defaults

    key = None
    if args.key_stdin:
        key = normalize_secret(sys.stdin.read())
    elif args.key_file:
        with open(os.path.expanduser(args.key_file), encoding="utf-8") as handle:
            key = normalize_secret(handle.read())

    if account_flag:
        if not ACCOUNT_RE.match(account_flag):
            raise ConfigError("账户别名只能用字母、数字、点、下划线、横线（≤32）")
        accounts = dict(entry.get("accounts") or {})
        account_entry = dict(accounts.get(account_flag) or {})
        account_entry["base_url"] = base
        if defaults:
            account_entry["default_models"] = defaults
        if args.credential_ref:
            account_entry["credential_ref"] = args.credential_ref
            account_entry.pop("api_key", None)
        if key:
            if args.store == "file":
                account_entry["api_key"] = key
            else:
                account_entry.pop("api_key", None)
                print(f"密钥已写入 {store_key(args.name, key, account_flag)}")
        accounts[account_flag] = account_entry
        entry["accounts"] = accounts
        entry.setdefault("base_url", base)
        entry.pop("api_key", None) if key and args.store != "file" else None
        print(f"账户 {args.name}@{account_flag} 已写入（独立密钥条目 {store_item_name(args.name, account_flag)}）")
    else:
        if key:
            if args.store == "file":
                entry["api_key"] = key
            else:
                entry.pop("api_key", None)
                print(f"密钥已写入 {store_key(args.name, key)}")

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
    ensure_utf8_stdio()
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
    p_add.add_argument("--default-speech")
    p_add.add_argument("--default-transcription")
    p_add.add_argument("--set-default", action="store_true")
    p_add.add_argument("--custom-file", help="custom 协议的模板文件（会复制到 ~/.config/media-gen/custom/<name>.json）")
    p_add.add_argument("--command-json", help='command 协议的命令表，如 {"create":"…","status":"…","fetch":"…"}')
    p_add.add_argument("--command-file", help="command 命令表的 JSON 文件")
    p_add.add_argument("--credential-ref", help="复用已有凭据库条目，格式 service:account（如 seedance-gateway:default）")
    p_add.add_argument("--header", action="append", metavar="K=V", help="profile 级固定请求头（可重复，如 OpenAI-Organization=org_x）")
    p_add.add_argument("--query", action="append", metavar="K=V", help="profile 级固定 query（可重复，如 api-version=2024-10-01）")
    p_add.add_argument("--account", help="新增/更新该配置档下的账户别名（同端点、独立密钥；如 team）")
    p_use = sub.add_parser("use", help="设为默认配置档")
    p_use.add_argument("name")
    p_rm = sub.add_parser("rm", help="删除配置档（--all 删全部）")
    p_rm.add_argument("name", nargs="?")
    p_rm.add_argument("--keep-key", action="store_true")
    p_rm.add_argument("--all", action="store_true", help="删除所有配置档（含密钥条目）")
    p_rm.add_argument("--account", help="只删除该配置档下的某个账户别名")
    sub.add_parser("list", help="列出配置档")
    sub.add_parser("audit", help="只读：本工具可能触及的凭据库条目及对应命令（不读密钥、不删除）")
    p_show = sub.add_parser("show", help="显示某个配置档的完整配置（密钥脱敏）")
    p_show.add_argument("name")
    p_setkey = sub.add_parser("set-key", help="只换密钥（stdin）")
    p_setkey.add_argument("name")
    p_setkey.add_argument("--store", choices=("auto", "file"), default="auto")
    p_setkey.add_argument("--account")
    p_setkey.add_argument("--no-verify", action="store_true")
    p_seturl = sub.add_parser("set-url", help="只换地址")
    p_seturl.add_argument("name")
    p_seturl.add_argument("--base-url", required=True)
    p_setproto = sub.add_parser("set-protocol", help="只换协议（必要时配套 --custom-file / --command-json）")
    p_setproto.add_argument("name")
    p_setproto.add_argument("--protocol", required=True, choices=PROTOCOLS)
    p_setproto.add_argument("--custom-file")
    p_setproto.add_argument("--command-json")
    p_setproto.add_argument("--command-file")
    p_cref = sub.add_parser("set-credential-ref", help="让配置档复用已有凭据库条目（service:account）")
    p_cref.add_argument("name")
    p_cref.add_argument("--ref", help="service:account；传空字符串则清除")
    p_rename = sub.add_parser("rename", help="重命名配置档（密钥条目一起搬）")
    p_rename.add_argument("old")
    p_rename.add_argument("new")
    p_export = sub.add_parser("export", help="导出配置（不含密钥）到 stdout")
    p_import = sub.add_parser("import", help="导入配置（文件里不应有密钥）")
    p_import.add_argument("file")
    p_mig = sub.add_parser("migrate", help="把旧的 seedance 配置/凭据迁到 media-gen")
    p_mig.add_argument("--name", default="legacy")
    p_mig.add_argument("--to", dest="name", help="目标配置档名（同 --name）")
    p_mig.add_argument("--delete-legacy", action="store_true", help="复制成功后删除旧 seedance-gateway 条目（需 MEDIA_ALLOW_CREDENTIAL_DELETE=1）")
    p_mig.add_argument("--store", choices=("auto", "file"), default="auto")
    args = parser.parse_args(argv)

    try:
        if args.command in (
            "add", "use", "rm", "list", "migrate", "show", "set-key", "set-url", "audit",
            "set-protocol", "rename", "export", "import", "set-credential-ref",
        ):
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


