#!/usr/bin/env python3
"""media-gen CLI — a thin front end over ``api.py``.

    media.py models [--kind image|video|speech|transcription] [--json] [--access]
    media.py image  -p "<prompt>" [--model M] [--size 1024x1024] [-n N] [--image ref] [-o out]
    media.py video  -p "<prompt>" [--model M] [-s SECONDS] [--ratio] [--resolution] [--image] [-o]
    media.py run    …   same flags, kind inferred from the registry
    media.py speech -t "<text>" · transcribe -f audio.mp3
    media.py status <id> | wait <id>… | download <id> [out]
    media.py tasks | list --model M | doctor [--gaps] [--matrix]

Argument parsing, printing and exit codes live here; every request is built in
``api.py`` so the MCP server takes exactly the same path. ``--profile`` selects
the endpoint; ``MEDIA_*`` environment variables override configuration.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import api
import media_config as config
import registry
from protocols import MediaError

DEFAULT_INTERVAL = api.DEFAULT_INTERVAL
DEFAULT_TIMEOUT = api.DEFAULT_TIMEOUT

#: doctor 报告里逐模型描述能力，与 api 保持同一份实现
capability_line = api.capability_line


# --------------------------------------------------------------------- helpers


def die(message: str, code: int = 1) -> "NoReturn":  # type: ignore[name-defined]
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(code)


def announce(message: str) -> None:
    print(message, file=sys.stderr)


# -------------------------------------------------------------------- commands


def cmd_models(args) -> int:
    result = api.models(args.profile, kind=args.kind, access=args.access,
                        timeout=args.timeout_seconds, verbose=args.verbose, log=announce)
    rows = result["models"]
    if result["note"]:
        print(result["note"])
    if args.json:
        print(json.dumps({"profile": result["profile_config"], "models": rows},
                         ensure_ascii=False, indent=2))
        return 0
    if not rows:
        print("没有匹配的模型；端点未暴露 /models 时请直接用 --model")
        return 0
    width = max(len(row["model"]) for row in rows)
    for row in rows:
        print(f"{row['model']:<{width}}  {row['kind']:<7}  {row['capability']}")
    return 0


def cmd_image(args) -> int:
    params = api.parse_params(args.param)
    if args.dry_run:
        name, profile, _ = api.context(args.profile, timeout=args.timeout_seconds,
                                       verbose=args.verbose, log=announce)
        model = api.pick_model(args.model, profile, "image")
        size = api.normalize_image_size(model, args.size)
        print(json.dumps(
            api.plan_image(name, profile, model, args.prompt, size, args.n,
                           args.image, getattr(args, "mask", None), params),
            ensure_ascii=False, indent=2))
        return 0
    result = api.image(args.profile, model=args.model, prompt=args.prompt, size=args.size,
                       n=args.n, ref=args.image, mask=getattr(args, "mask", None),
                       params=params, out=args.out, timeout=args.timeout_seconds,
                       verbose=args.verbose, log=announce)
    if args.json:
        print(json.dumps({"ok": True, "model": result["model"], "size": result["size"],
                          "files": result["files"], "count": result["count"]},
                         ensure_ascii=False))
        return 0
    for path in result["files"]:
        print(path)
    return 0


def cmd_video(args) -> int:
    params = api.parse_params(args.param)
    if args.dry_run:
        name, profile, _ = api.context(args.profile, timeout=args.timeout_seconds,
                                       verbose=args.verbose, log=announce)
        model = api.pick_model(args.model, profile, "video")
        print(json.dumps(
            api.plan_video(name, profile, model, args.prompt,
                           api.normalize_seconds(model, args.seconds),
                           api.normalize_image_size(model, args.size),
                           args.ratio, args.resolution, args.image, params),
            ensure_ascii=False, indent=2))
        return 0
    result = api.video(args.profile, model=args.model, prompt=args.prompt,
                       seconds=args.seconds, size=args.size, ratio=args.ratio,
                       resolution=args.resolution, ref=args.image, params=params,
                       out=args.out, create_only=args.create_only,
                       remix=getattr(args, "remix", None), extend=getattr(args, "extend", None),
                       last_frame=getattr(args, "last_frame", None),
                       interval=args.interval, timeout=args.timeout,
                       request_timeout=args.timeout_seconds,
                       verbose=args.verbose, log=announce)
    if args.create_only:
        # 只建任务时输出裸 id，便于脚本直接接 status/wait
        print(result["task_id"])
        return 0
    if result["remixed"]:
        announce(f"完成：{result['bytes']} 字节")
        if args.json:
            print(json.dumps({"ok": True, "task_id": result["task_id"], "file": result["file"],
                              "seconds": result["seconds"], "size": result["size"],
                              "url": result["url"]}, ensure_ascii=False))
            return 0
        print(result["file"])
        return 0
    announce("完成：" + " · ".join(
        part for part in (
            f"{result['seconds']}s" if result["seconds"] else "",
            result["size"] or "",
            f"{result['bytes']} 字节",
        ) if part
    ))
    if result["url"]:
        announce(f"远端地址 {result['url']}")
    if result["usage"]:
        announce(f"用量 {json.dumps(result['usage'], ensure_ascii=False)}")
    if args.json:
        print(json.dumps({
            "ok": True, "task_id": result["task_id"], "model": result["model"],
            "profile": result["profile"], "status": result["status"],
            "seconds": result["seconds"], "size": result["size"], "file": result["file"],
            "url": result["url"], "last_frame_url": result["last_frame_url"],
            "usage": result["usage"],
        }, ensure_ascii=False))
        return 0
    print(result["file"])
    return 0


def cmd_status(args) -> int:
    print(json.dumps(api.status(args.profile, args.task_id, timeout=args.timeout_seconds,
                                verbose=args.verbose), ensure_ascii=False, indent=2))
    return 0


def cmd_wait(args) -> int:
    result = api.wait(args.profile, args.task_id, timeout=args.timeout, interval=args.interval,
                      timeout_seconds=args.timeout_seconds, verbose=args.verbose, log=announce)
    payload = result["results"]
    value = payload if len(payload) > 1 else payload[0]
    print(json.dumps(value, ensure_ascii=False) if args.json
          else json.dumps(value, ensure_ascii=False, indent=2))
    return 1 if result["failed"] else 0


def cmd_download(args) -> int:
    result = api.download(args.profile, args.task_id, out=args.out,
                          last_frame=getattr(args, "last_frame", None),
                          timeout=args.timeout_seconds, verbose=args.verbose, log=announce)
    print(result["file"])
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
    if kind == "speech":
        die(f"{model} 是语音合成模型；用 speech 子命令：media.py speech -t \"文本\" --model {model}")
    if kind == "transcription":
        die(f"{model} 是语音转写模型；用 transcribe 子命令：media.py transcribe -f audio.mp3 --model {model}")
    die(f"无法判断 {model} 是图片还是视频模型；用 image 或 video 子命令显式指定")


def cmd_speech(args) -> int:
    if args.dry_run:
        name, profile, _ = api.context(args.profile, timeout=args.timeout_seconds,
                                       verbose=args.verbose, log=announce)
        model = api.audio_model(args.model, profile, "audio")
        print(json.dumps(api.plan_speech(name, profile, model, args.text, args.voice, args.format),
                         ensure_ascii=False, indent=2))
        return 0
    result = api.speech(args.profile, model=args.model, text=args.text, voice=args.voice,
                        fmt=args.format, out=args.out, timeout=args.timeout_seconds,
                        verbose=args.verbose, log=announce)
    print(result["file"])
    return 0


def cmd_transcribe(args) -> int:
    if args.dry_run:
        name, profile, _ = api.context(args.profile, timeout=args.timeout_seconds,
                                       verbose=args.verbose, log=announce)
        model = api.audio_model(args.model, profile, "transcription")
        print(json.dumps(api.plan_transcribe(name, profile, model, args.file, args.language),
                         ensure_ascii=False, indent=2))
        return 0
    result = api.transcribe(args.profile, model=args.model, file=args.file,
                            language=args.language, out=args.out,
                            timeout=args.timeout_seconds, verbose=args.verbose, log=announce)
    print(result["file"] or result["text"])
    return 0


def cmd_list(args) -> int:
    _, profile = config.require_profile(args.profile)
    model = args.model or (profile.get("default_models") or {}).get("video")
    if not model:
        die("list 需要 --model（或给 profile 配 default_models.video）", 2)
    items = api.remote_tasks(args.profile, model, limit=args.limit,
                             timeout=args.timeout_seconds)
    if args.json:
        print(json.dumps({"ok": True, "profile": args.profile, "model": model, "tasks": items},
                         ensure_ascii=False, indent=2))
        return 0
    if not items:
        print(f"（{model} 在 {args.profile or '默认配置档'} 上没有返回任务；网关可能未实现列表路由）")
        return 0
    for item in items:
        print(f"{str(item.get('id', ''))[:24]:<26}{str(item.get('status', '')):<12}"
              f"{str(item.get('seconds', '')):<5}{item.get('size') or ''}")
    return 0


def cmd_tasks(args) -> int:
    entries = api.tasks(args.status, args.limit)
    if args.json:
        print(json.dumps(entries, ensure_ascii=False, indent=2))
        return 0
    if not entries:
        print("（台账为空；生成立即会记录，文件在 ~/.local/state/media-gen/tasks.jsonl）")
        return 0
    print(f"{'at':<20}{'status':<11}{'id':<22}{'model':<22}file")
    for entry in entries:
        print(f"{str(entry.get('at', '')):<20}{str(entry.get('status', '')):<11}"
              f"{str(entry.get('id', ''))[:20]:<22}{str(entry.get('model') or '')[:20]:<22}"
              f"{entry.get('file') or ''}")
    return 0


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
            try:
                spec = api.protocol_spec(name, profile) or {}
            except api.UsageError as error:
                print(f"结果        FAIL  {error}")
                return 2
            parts = [kind for kind in ("image", "video") if kind in spec]
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
    if getattr(args, "gaps", False):
        print()
        print_verification_gaps(listed)
    if getattr(args, "matrix", False):
        print()
        print_verification_matrix(listed, profile)
    return 0


#: 能力 → (所需模型族, 是否需要付费调用, 备注)
MATRIX_ROWS = [
    ("文生视频 t2v", "video", False, "端点有 video deployment 即可验证"),
    ("图生视频 i2v", "video", False, "需要公网首帧 URL 或原生协议"),
    ("任务 status/wait/download", "video", False, "对已有任务零花费"),
    ("remix / extend", "video", True, "会新建任务，按 token 计费"),
    ("文生图 t2i", "image", False, "需要 image deployment"),
    ("图片编辑 /images/edits", "image", False, "需要 image deployment"),
    ("批量出图 -n", "image", False, "需要 image deployment"),
    ("语音合成 TTS", "speech", False, "需要 speech deployment"),
    ("语音转写 STT", "transcription", False, "需要 transcription deployment"),
]


def pad(text: str, width: int) -> str:
    """按显示宽度补空格（CJK 占 2 列），让终端表格对齐。"""
    import unicodedata

    def display_width(value: str) -> int:
        return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in value)

    current = display_width(text)
    return text + " " * max(1, width - current)


def print_verification_matrix(listed: list[str], profile: dict) -> None:
    """对照当前端点，算出这台机器上哪些能力可以真机验证。"""
    present: dict[str, list[str]] = {"image": [], "video": [], "speech": [], "transcription": []}
    for model in listed:
        capability = registry.resolve(model)
        kind = capability.kind if capability else registry.guess_kind(model)
        if kind in present:
            present[kind].append(model)
    print(f"验证矩阵（端点 {profile['base_url']}，protocol {profile['protocol']}）")
    print(f"  {pad('能力', 26)}{pad('可验证', 14)}{pad('付费', 6)}说明")
    ticked = 0
    for label, kind, paid, note in MATRIX_ROWS:
        available = bool(present.get(kind))
        if available:
            ticked += 1
        mark = "✅ 可以" if available else "⬜ 缺 deployment"
        print(f"  {pad(label, 26)}{pad(mark, 14)}{pad('是' if paid else '否', 6)}{note}")
    print()
    total = len(MATRIX_ROWS)
    print(f"  小结：{ticked}/{total} 项可在本端点上真机验证；"
          f"缺 {', '.join(k for k in ('image', 'video', 'speech', 'transcription') if not present.get(k)) or '无'}")
    if present.get("video"):
        print(f"  视频模型：{', '.join(present['video'][:3])}")
    print("  说明：标 ⬜ 的项仍由离线测试（mock）覆盖；换到带对应 deployment 的端点后重跑本命令即可。")


def print_verification_gaps(listed: list[str]) -> None:
    """这个端点上哪些能力因为缺少 deployment 而无法验证。"""
    present = {"image": [], "video": [], "speech": [], "transcription": []}
    for model in listed:
        capability = registry.resolve(model)
        kind = capability.kind if capability else registry.guess_kind(model)
        if kind in present:
            present[kind].append(model)
    print("可验证（端点有 deployment）：")
    for kind, models in present.items():
        if models:
            print(f"  {kind:<14}{', '.join(models[:6])}{' …' if len(models) > 6 else ''}")
    gaps = [kind for kind, models in present.items() if not models]
    if gaps:
        print("无法验证（端点没有这类 deployment，只能靠 mock/单测）：")
        for kind in gaps:
            print(f"  {kind:<14}—")
        print("  提示：换到带对应 deployment 的网关后，先跑 `media.py models --access` 再逐项补验")
    else:
        print("四类能力（image / video / speech / transcription）在这个端点上都能验证")


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
    p_models.add_argument("--kind", choices=("image", "video", "speech", "transcription"))
    p_models.add_argument("--json", action="store_true")
    p_models.add_argument("--access", action="store_true",
                          help="用一次无效模型探测 key 的白名单（不建任务、不花钱）")
    p_models.set_defaults(func=cmd_models)

    def add_generation_flags(p, kind: str) -> None:
        p.add_argument("-p", "--prompt", required=True)
        p.add_argument("--model")
        p.add_argument("-o", "--out", help="输出文件路径")
        p.add_argument("--image", help="参考图/首帧图：本地文件路径，或 http(s) URL（网关可能只接受 URL）")
        p.add_argument("--dry-run", action="store_true", help="只打印将要发送的内容，不花钱")
        p.add_argument("--param", action="append", metavar="K=V", help="透传各家私有参数（可重复，如 watermark=false）")
        p.add_argument("--json", action="store_true", help="机器可读输出")
        p.add_argument("--interval", type=int, default=DEFAULT_INTERVAL, help="视频轮询间隔（秒）")
        p.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="视频等待上限（秒）")
        if kind == "image":
            p.add_argument("--size", help="像素尺寸，如 1024x1024（会自动转成模型要求的分隔符）")
            p.add_argument("--mask", help="遮罩图（仅 /images/edits 支持）")
            p.add_argument("-n", type=int, default=1)
        else:
            p.add_argument("--size", help="像素尺寸，如 1280x720")
            p.add_argument("-s", "--seconds", type=int, help="时长（秒）；-1 表示让模型自选")
            p.add_argument("--ratio", help="宽高比，如 16:9（部分协议用）")
            p.add_argument("--resolution", help="分辨率档位，如 720p / 1080P")
            p.add_argument("--create-only", action="store_true", help="只建任务并打印任务 id")
            p.add_argument("--remix", metavar="TASK_ID", help="基于已有视频改（POST /videos/<id>/remix）")
            p.add_argument("--extend", metavar="TASK_ID", help="延长已有视频（POST /videos/extensions）")
            p.add_argument("--last-frame", help="把完成任务的尾帧图片保存到该路径")

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

    p_wait = sub.add_parser("wait", help="等到视频任务完成（可一次给多个 id，并发等待）")
    p_wait.add_argument("task_id", nargs="+")
    p_wait.add_argument("--interval", type=int, default=DEFAULT_INTERVAL)
    p_wait.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    p_wait.add_argument("--json", action="store_true")
    p_wait.set_defaults(func=cmd_wait)

    p_download = sub.add_parser("download", help="下载已完成的视频")
    p_download.add_argument("task_id")
    p_download.add_argument("out", nargs="?")
    p_download.add_argument("--last-frame", help="同时保存尾帧到该路径（任务未提供时只提示）")
    p_download.set_defaults(func=cmd_download)

    p_speech = sub.add_parser("speech", help="语音合成（/audio/speech，返回音频文件）")
    p_speech.add_argument("-t", "--text", required=True, help="要合成的文本")
    p_speech.add_argument("--model")
    p_speech.add_argument("--voice")
    p_speech.add_argument("--format", help="mp3 / wav / opus …（默认由服务端决定）")
    p_speech.add_argument("-o", "--out", help="输出文件路径")
    p_speech.add_argument("--dry-run", action="store_true")
    p_speech.set_defaults(func=cmd_speech)

    p_transcribe = sub.add_parser("transcribe", help="语音转写（/audio/transcriptions）")
    p_transcribe.add_argument("-f", "--file", required=True, help="音频文件")
    p_transcribe.add_argument("--model")
    p_transcribe.add_argument("--language")
    p_transcribe.add_argument("-o", "--out", help="写入文本文件（默认打到 stdout）")
    p_transcribe.add_argument("--dry-run", action="store_true")
    p_transcribe.set_defaults(func=cmd_transcribe)

    p_list = sub.add_parser("list", help="网关侧任务列表（GET /videos?model=）")
    p_list.add_argument("--model")
    p_list.add_argument("--limit", type=int, default=20)
    p_list.add_argument("--json", action="store_true")
    p_list.set_defaults(func=cmd_list)

    p_tasks = sub.add_parser("tasks", help="本地任务台账（~/.local/state/media-gen/tasks.jsonl）")
    p_tasks.add_argument("--status")
    p_tasks.add_argument("--limit", type=int, default=20)
    p_tasks.add_argument("--json", action="store_true")
    p_tasks.set_defaults(func=cmd_tasks)

    p_doctor = sub.add_parser("doctor", help="只读自检：配置、/models、媒体模型覆盖情况")
    p_doctor.add_argument("--gaps", action="store_true", help="列出该端点上无法验证的能力")
    p_doctor.add_argument("--matrix", action="store_true",
                          help="按能力列出本端点能否真机验证（可验证/缺 deployment + 是否付费）")
    p_doctor.set_defaults(func=cmd_doctor)
    return parser


def main(argv: list[str] | None = None) -> int:
    config.ensure_utf8_stdio()
    args = build_parser().parse_args(argv)
    if getattr(args, "account", None):
        # 账户选择落在环境里，供 media_config.require_profile 统一解析（与 MEDIA_ACCOUNT 同义）
        os.environ["MEDIA_ACCOUNT"] = str(args.account)
    try:
        return int(args.func(args) or 0)
    except api.UsageError as error:
        die(str(error), 2)
    except registry.RegistryError as error:
        die(str(error), 2)
    except config.ConfigError as error:
        die(str(error), 2)
    except MediaError as error:
        message = str(error)
        if "not allowed to access model" in message:
            message += (
                "\n提示：这不是模型不存在，而是这把 key 的团队白名单里没有它。"
                "先运行 media.py models 看当前可用列表，或让网关管理员放开。"
            )
        die(message)
    except KeyboardInterrupt:
        print("已中断", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
