#!/usr/bin/env python3
"""In-process API shared by the CLI (``media.py``) and the MCP server.

Functions take plain arguments, return plain dicts and raise:

* ``UsageError``  — the request itself is invalid (CLI exit code 2)
* ``MediaError``  — the endpoint refused or failed (CLI exit code 1)
* ``ConfigError`` / ``RegistryError`` propagate unchanged

Nothing here prints or exits. Both front ends (argparse/stdio vs JSON-RPC) are
then thin: they only format what this module returns, which keeps the two entry
points from drifting apart — the ``media_task wait`` bug in 0.11.1 was a
front-end argument mismatch, not an endpoint problem.
"""

from __future__ import annotations

import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

import media_config as config
import registry
from protocols import Endpoint, MediaError, VideoState, load_protocol, write_atomic

#: 进度/提示输出（CLI 传 announce，MCP 不传），签名与 print 到 stderr 一致。
Log = Callable[[str], None]


DEFAULT_INTERVAL = int(os.environ.get("MEDIA_POLL_INTERVAL", "10"))
DEFAULT_TIMEOUT = int(os.environ.get("MEDIA_POLL_TIMEOUT", "1800"))


class UsageError(RuntimeError):
    """调用方参数不合法；CLI 以 exit 2 退出。"""


def noop(_message: str) -> None:
    return None


# ------------------------------------------------------------------ planning


def parse_params(values) -> dict:
    params: dict = {}
    for item in values or []:
        key, separator, value = str(item).partition("=")
        if not separator or not key.strip():
            raise UsageError(f"--param 需要 K=V 形式：{item}")
        text = value.strip()
        if text.lower() in ("true", "false"):
            params[key.strip()] = text.lower() == "true"
        elif text.lstrip("-").isdigit():
            params[key.strip()] = int(text)
        else:
            params[key.strip()] = text
    return params


def context(
    profile_name: str | None = None,
    *,
    timeout: int = 120,
    verbose: bool = False,
    log: Log = noop,
) -> tuple[str, dict, object]:
    name, profile = config.require_profile(profile_name)
    key, key_source = config.resolve_key(name, profile)
    if not key:
        raise config.ConfigError(
            f"配置档 {name} 没有可用密钥；运行 scripts/setup.sh add {name} --protocol "
            f"{profile['protocol']} --base-url {profile['base_url']}，或设置 MEDIA_API_KEY"
        )
    if verbose:
        log(f"配置档 {name} · protocol {profile['protocol']} · 密钥来自 {key_source}")
    endpoint = Endpoint(
        protocol=profile["protocol"],
        base_url=profile["base_url"],
        key=key,
        timeout=int(timeout or 120),
        headers=profile.get("headers") if isinstance(profile.get("headers"), dict) else None,
        query=profile.get("query") if isinstance(profile.get("query"), dict) else None,
    )
    return name, profile, load_protocol(profile["protocol"])(endpoint, protocol_spec(name, profile))


def protocol_spec(name: str, profile: dict) -> dict | None:
    """custom 读模板文件，command 读命令表；其余协议不需要 spec。"""
    protocol = profile.get("protocol")
    if protocol == "custom":
        path = profile.get("custom_file") or str(config.custom_spec_path(name))
        path = os.path.expanduser(path)
        if not os.path.isfile(path):
            raise UsageError(
                f"custom 模板不存在：{path}；用 setup.sh add {name} --protocol custom --custom-file <文件>"
            )
        try:
            with open(path, encoding="utf-8") as handle:
                spec = json.load(handle)
        except ValueError as error:
            raise UsageError(f"custom 模板不是合法 JSON（{path}）：{error}") from None
        if not isinstance(spec, dict) or not ({"image", "video"} & set(spec)):
            raise UsageError(f"custom 模板至少要有 image 或 video 段：{path}")
        return spec
    if protocol == "command":
        commands = profile.get("command")
        if not isinstance(commands, dict) or not commands:
            raise UsageError(
                f"command 协议需要在配置档里提供 command 命令表"
                f"（setup.sh add {name} --protocol command --command-json …）"
            )
        return {"command": commands}
    return None


def registry_models(kind: str) -> list[str]:
    found = []
    for rule in registry.load_rules():
        if rule.get("kind") == kind:
            found.extend(pattern.replace("*", "") for pattern in rule["match"])
    return [model for model in found if model]


def pick_model(model: str | None, profile: dict, kind: str) -> str:
    if model:
        return model
    env = os.environ.get(f"MEDIA_{kind.upper()}_MODEL", "")
    if env:
        return env
    defaults = profile.get("default_models") or {}
    saved = defaults.get(kind) if isinstance(defaults, dict) else None
    if isinstance(saved, str) and saved:
        return saved
    known = registry_models(kind)
    hint = f"；例如 {known[0]}" if known else ""
    raise UsageError(
        f"{kind} 需要 --model（或用 setup.sh add … --default-{kind} 保存默认值）{hint}"
    )


def capability_line(model: str) -> str:
    capability = registry.resolve(model)
    return capability.describe() if capability else f"{registry.guess_kind(model)}（未在能力表中）"


def normalize_image_size(model: str, size: str | None) -> str | None:
    if not size:
        return None
    return registry.validate_size(model, size, registry.resolve(model))


def normalize_seconds(model: str, seconds: int | None) -> int | None:
    if seconds is None:
        return None
    return registry.check_duration(model, seconds, registry.resolve(model))


# ------------------------------------------------------------------- outputs


def default_output(kind: str) -> str:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    return f"media-{stamp}.{'mp4' if kind == 'video' else 'png'}"


def out_path(value: str | None, kind: str) -> str:
    """-o 展开 ~（agent 常把 "~/x.png" 原样传进来），否则会建出一个名为 ~ 的目录。"""
    return os.path.expanduser(value) if value else default_output(kind)


def variant_path(base: str, index: int, suffix: str | None) -> str:
    """批量图片：<stem>-1<suffix>、<stem>-2<suffix> …（保留原扩展名，缺失时用服务端后缀）"""
    root, extension = os.path.splitext(base)
    extension = extension or (suffix or ".png")
    return f"{root}-{index}{extension}"


def write_artifact(path: str, payload: bytes) -> None:
    write_atomic(path, payload)


def save_last_frame(protocol, state: VideoState, target: str | None, log: Log = noop) -> None:
    """把任务的尾帧写到 target；网关没给 last_frame_url 时只提示，不算失败。"""
    if not target:
        return
    if not state.last_frame_url:
        log("该任务没有返回 last_frame_url，未保存尾帧（网关不支持时属正常）")
        return
    data = protocol.fetch(state.last_frame_url)
    write_artifact(os.path.expanduser(target), data)
    log(f"尾帧已保存 {target}（{len(data)} 字节）")


# -------------------------------------------------------------------- ledger


def state_dir() -> str:
    base = os.environ.get("XDG_STATE_HOME", "")
    root = base if base.startswith("/") else os.path.join(os.path.expanduser("~"), ".local", "state")
    return os.path.join(root, "media-gen")


def ledger_path() -> str:
    return os.path.join(state_dir(), "tasks.jsonl")


def record_task(entry: dict, log: Log = noop) -> None:
    """追加一条任务记录（本地台账；失败只提示，不影响主流程）。"""
    try:
        directory = state_dir()
        os.makedirs(directory, mode=0o700, exist_ok=True)
        entry = dict(entry)
        entry["at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        with open(ledger_path(), "a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        os.chmod(ledger_path(), 0o600)
    except OSError as error:
        log(f"（任务台账写入失败：{error}）")


def load_ledger() -> list[dict]:
    try:
        with open(ledger_path(), encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]
    except FileNotFoundError:
        return []
    except (OSError, ValueError):
        return []


# ------------------------------------------------------------------ commands


def plan_image(name: str, profile: dict, model: str, prompt: str, size, n: int,
               ref, mask, params) -> dict:
    return {
        "profile": name,
        "protocol": profile["protocol"],
        "kind": "image",
        "model": model,
        "prompt": prompt,
        "size": size,
        "n": n,
        "reference": ref,
        "mask": mask,
        "params": params,
        "capability": capability_line(model),
    }


def image(
    profile_name: str | None,
    *,
    model: str | None,
    prompt: str,
    size: str | None = None,
    n: int = 1,
    ref: str | None = None,
    mask: str | None = None,
    params: dict | None = None,
    out: str | None = None,
    timeout: int = 120,
    verbose: bool = False,
    log: Log = noop,
) -> dict:
    name, profile, protocol = context(profile_name, timeout=timeout, verbose=verbose, log=log)
    resolved = pick_model(model, profile, "image")
    normalized = normalize_image_size(resolved, size)
    if n > 1:
        capability = registry.resolve(resolved)
        if capability is not None and not capability.n:
            raise UsageError(f"{resolved} 不支持 n>1（能力表未标注 n）")
    reference = ref or None
    if reference and not str(reference).startswith(("http://", "https://")):
        reference = os.path.expanduser(reference)
        if not os.path.isfile(reference):
            raise UsageError(f"找不到参考图（也不是 http(s) URL）：{ref}")
    mask_path = os.path.expanduser(mask) if mask else None
    if mask_path and not os.path.isfile(mask_path):
        raise UsageError(f"找不到遮罩图：{mask_path}")
    results = protocol.image(resolved, prompt, size=normalized, n=n, ref=reference,
                             mask=mask_path, params=params or {})
    if not results:
        raise MediaError("服务端没有返回任何图片")
    base_out = out_path(out, "image")
    written: list[str] = []
    for index, result in enumerate(results, 1):
        payload = result.data
        if not payload and result.url:
            log(f"从 {result.url[:80]}… 下载图片")
            payload = protocol.fetch(result.url)
        if not payload:
            raise MediaError(f"第 {index} 张图片没有内容")
        path = base_out if len(results) == 1 else variant_path(base_out, index, result.suffix)
        write_artifact(path, payload)
        written.append(path)
        log(f"#{index} {len(payload)} 字节" + (f" · {result.url}" if result.url else ""))
    log(f"模型 {resolved} · {normalized or '默认尺寸'} · {len(written)} 张")
    return {
        "profile": name,
        "protocol": profile["protocol"],
        "model": resolved,
        "size": normalized,
        "files": written,
        "count": len(written),
    }


def plan_video(name: str, profile: dict, model: str, prompt: str, seconds, size,
               ratio, resolution, first_frame, params) -> dict:
    return {
        "profile": name,
        "protocol": profile["protocol"],
        "kind": "video",
        "model": model,
        "prompt": prompt,
        "seconds": seconds,
        "size": size,
        "ratio": ratio,
        "resolution": resolution,
        "first_frame": first_frame,
        "params": params,
        "capability": capability_line(model),
    }


def video(
    profile_name: str | None,
    *,
    model: str | None,
    prompt: str,
    seconds: int | None = None,
    size: str | None = None,
    ratio: str | None = None,
    resolution: str | None = None,
    ref: str | None = None,
    params: dict | None = None,
    out: str | None = None,
    create_only: bool = False,
    remix: str | None = None,
    extend: str | None = None,
    last_frame: str | None = None,
    interval: int = DEFAULT_INTERVAL,
    timeout: int = DEFAULT_TIMEOUT,
    request_timeout: int = 120,
    verbose: bool = False,
    log: Log = noop,
) -> dict:
    name, profile, protocol = context(profile_name, timeout=request_timeout, verbose=verbose, log=log)
    resolved = pick_model(model, profile, "video")
    normalized_size = normalize_image_size(resolved, size)
    normalized_seconds = normalize_seconds(resolved, seconds)
    reference = ref or None
    if reference and not str(reference).startswith(("http://", "https://")):
        reference = os.path.expanduser(reference)
        if not os.path.isfile(reference):
            raise UsageError(f"找不到首帧图（也不是 http(s) URL）：{ref}")

    base_id = remix or extend
    if base_id:
        action = "remix" if remix else "extend"
        log(f"{action} {base_id} → 新任务（{resolved}）")
        creator = protocol.video_remix if remix else protocol.video_extend
        task_id = creator(base_id, prompt) if remix else creator(base_id, prompt, normalized_seconds)
    else:
        log(f"创建任务：{resolved}（{capability_line(resolved)}）")
        task_id = protocol.video_create(
            resolved, prompt, seconds=normalized_seconds, size=normalized_size,
            resolution=resolution, ratio=ratio, ref=reference, params=params or {},
        )
    log(f"task {task_id}")
    record_task({"id": task_id, "kind": "video", "model": resolved, "profile": name,
                 "status": "created", "seconds": normalized_seconds, "size": normalized_size,
                 "file": None, "url": None}, log)
    if create_only:
        return {"ok": True, "task_id": task_id, "model": resolved, "profile": name,
                "protocol": profile["protocol"], "status": "created", "create_only": True,
                "seconds": normalized_seconds, "size": normalized_size, "file": None}

    state = wait_for(protocol, task_id, timeout, interval, log)
    target = out_path(out, "video")
    written = protocol.video_download(task_id, state, target)
    save_last_frame(protocol, state, last_frame, log)
    record_task({"id": task_id, "kind": "video", "model": resolved, "profile": name,
                 "status": state.status, "seconds": state.seconds, "size": state.size,
                 "file": target, "url": state.url, "usage": state.usage}, log)
    return {
        "ok": True,
        "task_id": task_id,
        "model": resolved,
        "profile": name,
        "protocol": profile["protocol"],
        "status": state.status,
        "seconds": state.seconds,
        "size": state.size,
        "file": target,
        "bytes": written,
        "url": state.url,
        "last_frame_url": state.last_frame_url,
        "usage": state.usage,
        "remixed": bool(base_id),
    }


def audio_model(model: str | None, profile: dict, kind: str) -> str:
    """speech / transcription 的默认模型，来源顺序：--model → env → profile.default_models。"""
    env_name = "MEDIA_AUDIO_MODEL" if kind == "audio" else "MEDIA_TRANSCRIBE_MODEL"
    defaults = profile.get("default_models")
    saved = defaults.get(kind) if isinstance(defaults, dict) else None
    resolved = model or os.environ.get(env_name, "") or (saved if isinstance(saved, str) else "")
    if not resolved:
        raise UsageError(
            f"{'speech' if kind == 'audio' else 'transcribe'} 需要 --model"
            f"（或用 setup.sh add … --default-{kind} 保存默认值）"
        )
    return resolved


def plan_speech(name: str, profile: dict, model: str, text: str, voice, fmt) -> dict:
    return {"profile": name, "protocol": profile["protocol"], "kind": "speech",
            "model": model, "input": text, "voice": voice, "format": fmt}


def plan_transcribe(name: str, profile: dict, model: str, file: str, language) -> dict:
    return {"profile": name, "protocol": profile["protocol"], "kind": "transcription",
            "model": model, "file": os.path.expanduser(file), "language": language}


def speech(
    profile_name: str | None,
    *,
    model: str | None,
    text: str,
    voice: str | None = None,
    fmt: str | None = None,
    out: str | None = None,
    timeout: int = 120,
    verbose: bool = False,
    log: Log = noop,
) -> dict:
    name, profile, protocol = context(profile_name, timeout=timeout, verbose=verbose, log=log)
    resolved = audio_model(model, profile, "audio")
    payload, suffix = protocol.speech(resolved, text, voice=voice, fmt=fmt)
    target = os.path.expanduser(out) if out else f"media-{time.strftime('%Y%m%d-%H%M%S')}{suffix}"
    write_artifact(target, payload)
    log(f"模型 {resolved} · {len(payload)} 字节")
    return {"profile": name, "protocol": profile["protocol"], "model": resolved,
            "file": target, "bytes": len(payload)}


def transcribe(
    profile_name: str | None,
    *,
    model: str | None,
    file: str,
    language: str | None = None,
    out: str | None = None,
    timeout: int = 120,
    verbose: bool = False,
    log: Log = noop,
) -> dict:
    name, profile, protocol = context(profile_name, timeout=timeout, verbose=verbose, log=log)
    resolved = audio_model(model, profile, "transcription")
    path = os.path.expanduser(file)
    if not os.path.isfile(path):
        raise UsageError(f"找不到音频文件：{path}")
    text = protocol.transcribe(resolved, path, language=language)
    target = None
    if out:
        target = os.path.expanduser(out)
        write_artifact(target, (text + "\n").encode("utf-8"))
        log(f"{len(text)} 字符 → {target}")
    return {"profile": name, "protocol": profile["protocol"], "model": resolved,
            "text": text, "chars": len(text), "file": target}


# ------------------------------------------------------------ task lifecycle


def state_dict(state: VideoState) -> dict:
    return {
        "status": state.status,
        "task_id": state.task_id,
        "seconds": state.seconds,
        "size": state.size,
        "url": state.url,
        "last_frame_url": state.last_frame_url,
        "usage": state.usage,
        "raw": state.extra,
    }


def status(profile_name: str | None, task_id: str, *, timeout: int = 120,
           verbose: bool = False) -> dict:
    _, _, protocol = context(profile_name, timeout=timeout, verbose=verbose)
    return state_dict(protocol.video_status(task_id))


def wait_for(protocol, task_id: str, timeout: int, interval: int, log: Log = noop) -> VideoState:
    started = time.time()
    while True:
        state = protocol.video_status(task_id)
        if state.done:
            log(f"状态 {state.status}")
            return state
        if state.failed:
            raise MediaError(f"任务 {task_id} {state.status}：{state.error or '（无错误信息）'}")
        elapsed = int(time.time() - started)
        if elapsed > timeout:
            raise MediaError(
                f"等待超时（{timeout}s），最后状态 {state.status}；"
                f"任务 {task_id} 仍在运行，可稍后 status/wait"
            )
        log(f"状态 {state.status}（{elapsed}s）")
        time.sleep(interval)


def wait(
    profile_name: str | None,
    task_ids,
    *,
    timeout: int = DEFAULT_TIMEOUT,
    interval: int = DEFAULT_INTERVAL,
    timeout_seconds: int = 120,
    verbose: bool = False,
    log: Log = noop,
) -> dict:
    """等一个或多个任务。程序化调用可能传单个字符串，这里统一成列表。"""
    _, _, protocol = context(profile_name, timeout=timeout_seconds, verbose=verbose, log=log)
    ids = [task_ids] if isinstance(task_ids, str) else list(task_ids)
    if len(ids) == 1:
        return {"results": [state_dict(wait_for(protocol, ids[0], timeout, interval, log))],
                "failed": []}

    log(f"并发等待 {len(ids)} 个任务（间隔 {interval}s，上限 {timeout}s）")
    results: list[dict] = []
    failed: list[str] = []
    with ThreadPoolExecutor(max_workers=min(len(ids), 8)) as pool:
        futures = [(task, pool.submit(wait_for, protocol, task, timeout, interval, log))
                   for task in ids]
        # 一个任务失败不能把其他任务已经等到的结果一起丢掉
        for task, future in futures:
            try:
                results.append(state_dict(future.result()))
            except MediaError as error:
                log(f"任务 {task} 失败：{error}")
                failed.append(task)
    record_task({"id": ",".join(ids), "kind": "video", "status": "waited",
                 "model": None, "profile": None, "seconds": None, "size": None,
                 "file": None, "url": None}, log)
    if failed:
        log(f"{len(failed)}/{len(ids)} 个任务未完成：{', '.join(failed)}"
            f"；下面只含已等到的 {len(results)} 个")
    if not results:
        raise MediaError(f"没有任务等到结果（失败：{', '.join(failed)}）")
    return {"results": results, "failed": failed}


def download(
    profile_name: str | None,
    task_id: str,
    *,
    out: str | None = None,
    last_frame: str | None = None,
    timeout: int = 120,
    verbose: bool = False,
    log: Log = noop,
) -> dict:
    _, _, protocol = context(profile_name, timeout=timeout, verbose=verbose, log=log)
    state = protocol.video_status(task_id)
    if not state.done:
        raise MediaError(f"任务 {task_id} 尚未完成（{state.status}）；先运行 wait")
    target = out_path(out, "video")
    written = protocol.video_download(task_id, state, target)
    log(f"{written} 字节")
    save_last_frame(protocol, state, last_frame, log)
    return {"ok": True, "task_id": task_id, "file": target, "bytes": written,
            "status": state.status, "seconds": state.seconds, "size": state.size,
            "url": state.url}


# ------------------------------------------------------------- discovery


def probe_allowlist(protocol) -> list[str] | None:
    """发一个必然被拒的请求，从报错里解析团队白名单（不建任务，不花钱）。"""
    # 用一个不可能存在的模型名发一次 POST：无论被拒是"白名单"还是"模型不存在"，都不会建出计费任务；
    # 不用 GET /videos/<假 id>，那在某些网关上会卡到超时而不是返回白名单。
    probe = {"model": "__media_gen_allowlist_probe__", "prompt": "probe"}
    try:
        status_code, payload, raw = protocol._request(
            "POST", protocol.endpoint.base_url + "/images/generations", probe
        )
        text = f"{status_code} {payload}"
    except MediaError as error:
        text = str(error)
    match = re.search(r"can only access models=\s*\[(.*?)\]", str(text), re.S)
    if not match:
        return None
    return [item.strip().strip("'\"") for item in match.group(1).split(",") if item.strip()]


def models(
    profile_name: str | None,
    *,
    kind: str | None = None,
    access: bool = False,
    timeout: int = 120,
    verbose: bool = False,
    log: Log = noop,
) -> dict:
    name, profile, protocol = context(profile_name, timeout=timeout, verbose=verbose, log=log)
    listed: list[str] | None = None
    try:
        listed = protocol.list_models()
    except MediaError as error:
        log(f"（无法列出端点模型：{error}）")
    rows: list[dict] = []
    if listed:
        for model in listed:
            capability = registry.resolve(model)
            resolved_kind = capability.kind if capability else registry.guess_kind(model)
            if kind and resolved_kind != kind:
                continue
            rows.append({"model": model, "kind": resolved_kind,
                         "capability": capability.describe() if capability else "",
                         "source": "endpoint"})
    else:
        for rule in registry.load_rules():
            if kind and rule.get("kind") != kind:
                continue
            rows.append({"model": ", ".join(rule["match"]), "kind": rule["kind"],
                         "capability": str(rule.get("notes", "")), "source": "registry"})
    note = ""
    if access:
        allowed = probe_allowlist(protocol)
        if allowed:
            rows = [row for row in rows if row["model"] in allowed] or [
                {"model": model,
                 "kind": (registry.resolve(model).kind if registry.resolve(model)
                          else registry.guess_kind(model)),
                 "capability": "", "source": "allowlist"} for model in allowed
            ]
            note = f"# key 白名单共 {len(allowed)} 个模型（探测结果，未建任务）"
        else:
            note = "# 无法从网关读出白名单（该端点报错不含清单）"
    return {"profile": name, "profile_config": profile, "models": rows, "note": note}


def profiles() -> list[dict]:
    found = config.profiles()
    default = config.read_config().get("default")
    rows = []
    for name in sorted(found):
        entry = found[name]
        key, source = config.resolve_key(name, entry)
        rows.append({
            "profile": name,
            "default": name == default,
            "protocol": entry.get("protocol"),
            "base_url": entry.get("base_url"),
            "default_models": entry.get("default_models") or {},
            "key": config.mask(key) if key else None,
            "key_source": source,
        })
    return rows


def remote_tasks(
    profile_name: str | None, model: str, *, limit: int = 20, timeout: int = 120
) -> list:
    name, profile, protocol = context(profile_name, timeout=timeout)
    if not hasattr(protocol, "video_list"):
        raise UsageError(f"{profile['protocol']} 协议没有任务列表路由")
    try:
        return protocol.video_list(model, limit=limit)
    except MediaError as error:
        if "LLM Provider NOT provided" in str(error):
            raise MediaError(
                f"{name} 的任务列表路由没有把 model 转发给上游（网关侧问题，不是本地参数错）。\n"
                f"  可改用本地台账：media.py tasks\n"
                f"  或直接按 id 查询：media.py status <id>"
            ) from None
        raise


def tasks(status_filter: str | None = None, limit: int | None = None) -> list[dict]:
    entries = load_ledger()
    if status_filter:
        entries = [entry for entry in entries if str(entry.get("status")) == status_filter]
    if limit:
        entries = entries[-int(limit):]
    return entries
