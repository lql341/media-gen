#!/usr/bin/env python3
"""media-gen CLI — image and video generation over any configured endpoint.

    media.py models [--kind image|video] [--json]
    media.py image  -p "<prompt>" [--model M] [--size 1024x1024] [-n N] [--image ref.png] [-o out.png]
    media.py video  -p "<prompt>" [--model M] [-s SECONDS] [--size|--ratio/--resolution] [--image first.png] [-o out.mp4]
    media.py run    …   same flags as image/video, kind inferred from the model
    media.py status <task_id> | wait <task_id> | download <task_id> <out>
    media.py doctor

Every command accepts ``--profile`` (endpoint) and honours environment
overrides (``MEDIA_PROFILE``, ``MEDIA_BASE_URL``, ``MEDIA_API_KEY``). The wire
protocol comes from the profile (``openai``/``ark``/``dashscope``/``minimax``);
the model's capabilities come from the registry. Nothing here is tied to one
gateway or one model family.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

import media_config as config
import registry
from protocols import Endpoint, MediaError, VideoState, load_protocol

DEFAULT_INTERVAL = int(os.environ.get("MEDIA_POLL_INTERVAL", "10"))
DEFAULT_TIMEOUT = int(os.environ.get("MEDIA_POLL_TIMEOUT", "1800"))


# --------------------------------------------------------------------- helpers


def die(message: str, code: int = 1) -> "NoReturn":  # type: ignore[name-defined]
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(code)


def announce(message: str) -> None:
    print(message, file=sys.stderr)


def make_context(args) -> tuple[str, dict, object]:
    name, profile = config.require_profile(getattr(args, "profile", None))
    key, key_source = config.resolve_key(name, profile)
    if not key:
        die(
            f"配置档 {name} 没有可用密钥；运行 scripts/setup.sh add {name} --protocol "
            f"{profile['protocol']} --base-url {profile['base_url']}，或设置 MEDIA_API_KEY"
        )
    if getattr(args, "verbose", False):
        announce(f"配置档 {name} · protocol {profile['protocol']} · 密钥来自 {key_source}")
    endpoint = Endpoint(
        protocol=profile["protocol"],
        base_url=profile["base_url"],
        key=key,
        timeout=int(getattr(args, "timeout_seconds", 0) or 120),
    )
    spec = protocol_spec(name, profile)
    protocol = load_protocol(profile["protocol"])(endpoint, spec)
    return name, profile, protocol


def protocol_spec(name: str, profile: dict) -> dict | None:
    """custom 读模板文件，command 读命令表；其余协议不需要 spec。"""
    protocol = profile.get("protocol")
    if protocol == "custom":
        path = profile.get("custom_file") or str(config.custom_spec_path(name))
        path = os.path.expanduser(path)
        if not os.path.isfile(path):
            die(f"custom 模板不存在：{path}；用 setup.sh add {name} --protocol custom --custom-file <文件>", 2)
        try:
            with open(path, encoding="utf-8") as handle:
                spec = json.load(handle)
        except ValueError as error:
            die(f"custom 模板不是合法 JSON（{path}）：{error}", 2)
        if not isinstance(spec, dict) or not ({"image", "video"} & set(spec)):
            die(f"custom 模板至少要有 image 或 video 段：{path}", 2)
        return spec
    if protocol == "command":
        commands = profile.get("command")
        if not isinstance(commands, dict) or not commands:
            die(f"command 协议需要在配置档里提供 command 命令表（setup.sh add {name} --protocol command --command-json …）", 2)
        return {"command": commands}
    return None


def pick_model(args, profile: dict, kind: str) -> str:
    explicit = getattr(args, "model", None)
    if explicit:
        return explicit
    env = os.environ.get(f"MEDIA_{kind.upper()}_MODEL", "")
    if env:
        return env
    defaults = profile.get("default_models") or {}
    saved = defaults.get(kind) if isinstance(defaults, dict) else None
    if isinstance(saved, str) and saved:
        return saved
    known = [
        model
        for model in _registry_models(kind)
        if model != ""
    ]
    hint = f"；例如 {known[0]}" if known else ""
    die(f"{kind} 需要 --model（或用 setup.sh add … --default-{kind} 保存默认值）{hint}", 2)


def _registry_models(kind: str) -> list[str]:
    found = []
    for rule in registry.load_rules():
        if rule.get("kind") == kind:
            found.extend(pattern.replace("*", "") for pattern in rule["match"])
    return found


def normalize_image_size(model: str, size: str | None) -> str | None:
    if not size:
        return None
    capability = registry.resolve(model)
    return registry.validate_size(model, size, capability)


def normalize_seconds(model: str, seconds: int | None) -> int | None:
    if seconds is None:
        return None
    return registry.check_duration(model, seconds, registry.resolve(model))


def capability_line(model: str) -> str:
    capability = registry.resolve(model)
    return capability.describe() if capability else f"{registry.guess_kind(model)}（未在能力表中）"


def write_artifact(path: str, payload: bytes) -> None:
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(payload)


def default_output(kind: str) -> str:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    return f"media-{stamp}.{'mp4' if kind == 'video' else 'png'}"


# -------------------------------------------------------------------- commands


def cmd_models(args) -> int:
    _, profile, protocol = make_context(args)
    listed = None
    try:
        listed = protocol.list_models()
    except MediaError as error:
        announce(f"（无法列出端点模型：{error}）")
    rows = []
    if listed:
        for model in listed:
            capability = registry.resolve(model)
            kind = capability.kind if capability else registry.guess_kind(model)
            if args.kind and kind != args.kind:
                continue
            rows.append(
                {
                    "model": model,
                    "kind": kind,
                    "capability": capability.describe() if capability else "",
                    "source": "endpoint",
                }
            )
    else:
        for rule in registry.load_rules():
            if args.kind and rule.get("kind") != args.kind:
                continue
            rows.append(
                {
                    "model": ", ".join(rule["match"]),
                    "kind": rule["kind"],
                    "capability": str(rule.get("notes", "")),
                    "source": "registry",
                }
            )
    if args.json:
        print(json.dumps({"profile": profile, "models": rows}, ensure_ascii=False, indent=2))
        return 0
    if not rows:
        print("没有匹配的模型；端点未暴露 /models 时请直接用 --model")
        return 0
    width = max(len(row["model"]) for row in rows)
    for row in rows:
        print(f"{row['model']:<{width}}  {row['kind']:<7}  {row['capability']}")
    return 0


def cmd_image(args) -> int:
    name, profile, protocol = make_context(args)
    model = pick_model(args, profile, "image")
    size = normalize_image_size(model, args.size)
    if args.dry_run:
        print(
            json.dumps(
                {
                    "profile": name,
                    "protocol": profile["protocol"],
                    "kind": "image",
                    "model": model,
                    "prompt": args.prompt,
                    "size": size,
                    "n": args.n,
                    "reference": args.image,
                    "capability": capability_line(model),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    if args.n > 1:
        capability = registry.resolve(model)
        if capability is not None and not capability.n:
            die(f"{model} 不支持 n>1（能力表未标注 n）")
    ref = os.path.expanduser(args.image) if args.image else None
    if ref and not os.path.isfile(ref):
        die(f"找不到参考图：{ref}")
    result = protocol.image(model, args.prompt, size=size, n=args.n, ref=ref)
    payload = result.data
    if not payload and result.url:
        announce(f"从 {result.url[:80]}… 下载图片")
        payload = protocol.fetch(result.url)
    if not payload:
        die("服务端没有返回图片内容")
    out = args.out or default_output("image")
    write_artifact(out, payload)
    announce(f"模型 {model} · {size or '默认尺寸'} · {len(payload)} 字节")
    if result.url:
        announce(f"远端地址 {result.url}")
    print(out)
    return 0


def cmd_video(args) -> int:
    name, profile, protocol = make_context(args)
    model = pick_model(args, profile, "video")
    size = normalize_image_size(model, args.size)
    seconds = normalize_seconds(model, args.seconds)
    if args.dry_run:
        print(
            json.dumps(
                {
                    "profile": name,
                    "protocol": profile["protocol"],
                    "kind": "video",
                    "model": model,
                    "prompt": args.prompt,
                    "seconds": seconds,
                    "size": size,
                    "ratio": args.ratio,
                    "resolution": args.resolution,
                    "first_frame": args.image,
                    "capability": capability_line(model),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    ref = os.path.expanduser(args.image) if args.image else None
    if ref and not os.path.isfile(ref):
        die(f"找不到首帧图：{ref}")
    announce(f"创建任务：{model}（{capability_line(model)}）")
    task_id = protocol.video_create(
        model,
        args.prompt,
        seconds=seconds,
        size=size,
        resolution=args.resolution,
        ratio=args.ratio,
        ref=ref,
    )
    announce(f"task {task_id}")
    if getattr(args, "create_only", False):
        print(task_id)
        return 0
    state = wait_for(protocol, task_id, args.timeout, args.interval)
    payload = protocol.video_fetch(task_id, state)
    out = args.out or default_output("video")
    write_artifact(out, payload)
    announce(
        "完成："
        + " · ".join(
            part
            for part in (
                f"{state.seconds}s" if state.seconds else "",
                state.size or "",
                f"{len(payload)} 字节",
            )
            if part
        )
    )
    if state.url:
        announce(f"远端地址 {state.url}")
    if state.usage:
        announce(f"用量 {json.dumps(state.usage, ensure_ascii=False)}")
    print(out)
    return 0


def wait_for(protocol, task_id: str, timeout: int, interval: int) -> VideoState:
    started = time.time()
    while True:
        state = protocol.video_status(task_id)
        if state.done:
            announce(f"状态 {state.status}")
            return state
        if state.failed:
            die(f"任务 {task_id} {state.status}：{state.error or '（无错误信息）'}")
        elapsed = int(time.time() - started)
        if elapsed > timeout:
            die(f"等待超时（{timeout}s），最后状态 {state.status}；任务 {task_id} 仍在运行，可稍后 status/wait")
        announce(f"状态 {state.status}（{elapsed}s）")
        time.sleep(interval)


def cmd_status(args) -> int:
    _, _, protocol = make_context(args)
    state = protocol.video_status(args.task_id)
    payload = {
        "status": state.status,
        "task_id": state.task_id,
        "seconds": state.seconds,
        "size": state.size,
        "url": state.url,
        "error": state.error,
        "usage": state.usage,
        "raw": state.extra,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def cmd_wait(args) -> int:
    _, _, protocol = make_context(args)
    state = wait_for(protocol, args.task_id, args.timeout, args.interval)
    print(
        json.dumps(
            {
                "status": state.status,
                "task_id": state.task_id,
                "seconds": state.seconds,
                "size": state.size,
                "url": state.url,
                "usage": state.usage,
                "raw": state.extra,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def cmd_download(args) -> int:
    _, _, protocol = make_context(args)
    state = protocol.video_status(args.task_id)
    if not state.done:
        die(f"任务 {args.task_id} 尚未完成（{state.status}）；先运行 wait")
    payload = protocol.video_fetch(args.task_id, state)
    out = args.out or default_output("video")
    write_artifact(out, payload)
    announce(f"{len(payload)} 字节")
    print(out)
    return 0


def cmd_run(args) -> int:
    model = args.model or os.environ.get("MEDIA_MODEL", "")
    if not model:
        die("run 需要 --model（或用 MEDIA_MODEL），因为要先判断是图片还是视频")
    capability = registry.resolve(model)
    kind = capability.kind if capability else registry.guess_kind(model)
    if kind == "image":
        return cmd_image(args)
    if kind == "video":
        return cmd_video(args)
    die(f"无法判断 {model} 是图片还是视频模型；用 image 或 video 子命令显式指定")


def cmd_doctor(args) -> int:
    try:
        name, profile = config.require_profile(getattr(args, "profile", None))
    except config.ConfigError as error:
        print(f"配置        FAIL  {error}")
        return 2
    key, key_source = config.resolve_key(name, profile)
    print(f"配置目录    {config.config_dir()}")
    print(f"配置档      {name}（protocol {profile['protocol']}）")
    print(f"地址        {profile['base_url']}")
    print(f"密钥        {config.mask(key) if key else '未配置'}")
    print(f"密钥来源    {key_source}")
    if not key:
        print("结果        FAIL  没有可用密钥")
        return 1
    try:
        listed = protocol_models(profile, key)
    except config.ConfigError as error:
        print(f"结果        FAIL  {error}")
        return 1
    if listed is None:
        if profile["protocol"] == "custom":
            spec_path = profile.get("custom_file") or config.custom_spec_path(name)
            parts = [kind for kind in ("image", "video") if kind in (protocol_spec(name, profile) or {})]
            print(f"结果        OK    custom 模板（{os.path.basename(str(spec_path))}）：支持 {', '.join(parts) or '（空）'}")
        elif profile["protocol"] == "command":
            commands = (profile.get("command") or {}).keys()
            print(f"结果        OK    command 钩子：{', '.join(sorted(commands))}")
        else:
            print("结果        OK    端点没有 /models（原生协议），按 --model 直接调用")
        return 0
    media = [model for model in listed if registry.resolve(model) or registry.guess_kind(model) != "unknown"]
    print(f"结果        OK    GET /models 200，{len(listed)} 个模型")
    if media:
        print("媒体模型    " + ", ".join(f"{model}[{capability_line(model)}]" for model in media[:12]))
        if len(media) > 12:
            print(f"            …另有 {len(media) - 12} 个")
    else:
        print("媒体模型    端点未暴露任何图片/视频模型；能力表里的模型名可直接试 --model")
    missing = [rule["match"][0] for rule in registry.load_rules() if not _any_match(listed, rule)]
    if missing:
        print(f"未挂载      {', '.join(missing[:6])}{' …' if len(missing) > 6 else ''}")
    return 0


def _any_match(models: list[str], rule: dict) -> bool:
    return any(registry._matches(model, pattern) for model in models for pattern in rule["match"])


def protocol_models(profile: dict, key: str) -> list[str] | None:
    if profile["protocol"] != "openai":
        return None
    return config.probe_models(profile, key)


# ------------------------------------------------------------------------ main


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="media-gen",
        description="图片/视频生成：协议由配置档决定（openai / ark / dashscope / minimax），模型能力由 registry 决定",
    )
    parser.add_argument("--profile", help="配置档，可写 <name> 或 <name>@<account>（默认取配置里的 default）")
    parser.add_argument("--account", help="账户别名（等价于 --profile <name>@<account>），会话内可并发使用不同账户")
    parser.add_argument("--timeout-seconds", type=int, default=120, help="单次 HTTP 超时（默认 120）")
    parser.add_argument("--verbose", action="store_true", help="打印密钥来源等诊断信息")
    sub = parser.add_subparsers(dest="command", required=True)

    p_models = sub.add_parser("models", help="列出端点/能力表里的媒体模型")
    p_models.add_argument("--kind", choices=("image", "video"))
    p_models.add_argument("--json", action="store_true")
    p_models.set_defaults(func=cmd_models)

    def add_generation_flags(p, kind: str) -> None:
        p.add_argument("-p", "--prompt", required=True)
        p.add_argument("--model")
        p.add_argument("-o", "--out", help="输出文件路径")
        p.add_argument("--image", help="参考图/首帧图（本地文件）")
        p.add_argument("--dry-run", action="store_true", help="只打印将要发送的内容，不花钱")
        p.add_argument("--interval", type=int, default=DEFAULT_INTERVAL, help="视频轮询间隔（秒）")
        p.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="视频等待上限（秒）")
        if kind == "image":
            p.add_argument("--size", help="像素尺寸，如 1024x1024（会自动转成模型要求的分隔符）")
            p.add_argument("-n", type=int, default=1)
        else:
            p.add_argument("--size", help="像素尺寸，如 1280x720")
            p.add_argument("-s", "--seconds", type=int, help="时长（秒）；-1 表示让模型自选")
            p.add_argument("--ratio", help="宽高比，如 16:9（部分协议用）")
            p.add_argument("--resolution", help="分辨率档位，如 720p / 1080P")
            p.add_argument("--create-only", action="store_true", help="只建任务并打印任务 id")

    p_image = sub.add_parser("image", help="文生图（同步返回）")
    add_generation_flags(p_image, "image")
    p_image.set_defaults(func=cmd_image)

    p_video = sub.add_parser("video", help="文生视频/图生视频（异步任务）")
    add_generation_flags(p_video, "video")
    p_video.set_defaults(func=cmd_video)

    p_run = sub.add_parser("run", help="按模型能力自动选 image 或 video")
    add_generation_flags(p_run, "video")   # 已含 --size / -s / --ratio / --resolution
    p_run.add_argument("-n", type=int, default=1)
    p_run.set_defaults(func=cmd_run)

    p_status = sub.add_parser("status", help="查视频任务状态")
    p_status.add_argument("task_id")
    p_status.set_defaults(func=cmd_status)

    p_wait = sub.add_parser("wait", help="等到视频任务完成")
    p_wait.add_argument("task_id")
    p_wait.add_argument("--interval", type=int, default=DEFAULT_INTERVAL)
    p_wait.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    p_wait.set_defaults(func=cmd_wait)

    p_download = sub.add_parser("download", help="下载已完成的视频")
    p_download.add_argument("task_id")
    p_download.add_argument("out", nargs="?")
    p_download.set_defaults(func=cmd_download)

    p_doctor = sub.add_parser("doctor", help="只读自检：配置、/models、媒体模型覆盖情况")
    p_doctor.set_defaults(func=cmd_doctor)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if getattr(args, "account", None):
        # 账户选择落在环境里，供 media_config.require_profile 统一解析（与 MEDIA_ACCOUNT 同义）
        os.environ["MEDIA_ACCOUNT"] = str(args.account)
    try:
        return int(args.func(args) or 0)
    except registry.RegistryError as error:
        die(str(error), 2)
    except config.ConfigError as error:
        die(str(error), 2)
    except MediaError as error:
        die(str(error))
    except KeyboardInterrupt:
        print("已中断", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
