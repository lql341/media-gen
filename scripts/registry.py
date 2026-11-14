"""Model capability registry.

A model id is matched against an ordered rule list to decide *what it is*
(image or video) and *what it accepts* (duration range/enum, size syntax,
reference image). The wire protocol is decided by the configuration profile,
not here, so the same model can be reached through a LiteLLM proxy
(``protocol=openai``) or its provider's native API (``ark``/``dashscope``/
``minimax``).

Built-in rules live next to this file (``registry.json``); a user file at
``~/.config/media-gen/registry.json`` is merged on top, matching first.
"""

from __future__ import annotations

import fnmatch
import json
import os
from dataclasses import dataclass, field

HERE = os.path.dirname(os.path.abspath(__file__))
BUILTIN = os.path.join(HERE, "registry.json")


class RegistryError(RuntimeError):
    """A user-facing registry problem."""


@dataclass
class Capability:
    kind: str                      # "image" | "video"
    notes: str = ""
    duration: dict = field(default_factory=dict)
    size: dict = field(default_factory=dict)
    n: bool = False
    image_input: bool = False
    pattern: str = ""

    def durations(self) -> tuple[int | None, int | None, int | None]:
        """(min, max, auto) — auto is the sentinel meaning 'let the model choose'."""
        return (
            self.duration.get("min"),
            self.duration.get("max"),
            self.duration.get("auto"),
        )

    def duration_choices(self) -> list[int]:
        value = self.duration.get("enum")
        return list(value) if isinstance(value, list) else []

    def size_form(self) -> str:
        return str(self.size.get("form", "WxH"))

    def describe(self) -> str:
        parts = [self.kind]
        lo, hi, auto = self.durations()
        choices = self.duration_choices()
        if choices:
            parts.append("duration∈{" + ",".join(str(c) for c in choices) + "}s")
        elif lo is not None and hi is not None:
            tail = f"/{auto}=auto" if auto is not None else ""
            parts.append(f"duration {lo}-{hi}s{tail}")
        if self.size:
            allowed = self.size.get("resolutions") or self.size.get("aspects")
            if allowed:
                parts.append(f"size:{self.size_form()}∈{{{','.join(str(a) for a in allowed)}}}")
            else:
                parts.append(f"size:{self.size_form()}")
        if self.image_input:
            parts.append("image-input")
        if self.n:
            parts.append("n>1")
        return " · ".join(parts)


def _load(path: str) -> list[dict]:
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as error:
        raise RegistryError(f"能力表无法解析（{path}）：{error}") from None
    rules = data.get("rules") if isinstance(data, dict) else None
    if not isinstance(rules, list):
        raise RegistryError(f"能力表格式不对（{path}）：需要 {{\"rules\": [...]}}")
    out = []
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        match = rule.get("match")
        if isinstance(match, str):
            match = [match]
        if not isinstance(match, list) or not match:
            continue
        if rule.get("kind") not in ("image", "video", "audio"):
            continue
        out.append({**rule, "match": [str(pattern) for pattern in match]})
    return out


def load_rules(override_path: str | None = None) -> list[dict]:
    """User rules first (so they win), then built-ins."""
    user_path = override_path or os.environ.get("MEDIA_REGISTRY", "")
    if not user_path:
        xdg = os.environ.get("XDG_CONFIG_HOME", "")
        root = xdg if xdg.startswith("/") else os.path.join(os.path.expanduser("~"), ".config")
        user_path = os.path.join(root, "media-gen", "registry.json")
    return _load(user_path) + _load(BUILTIN)


def _matches(model: str, pattern: str) -> bool:
    return fnmatch.fnmatchcase(model, pattern) or fnmatch.fnmatchcase(model.lower(), pattern.lower())


def resolve(model: str, rules: list[dict] | None = None) -> Capability | None:
    for rule in rules if rules is not None else load_rules():
        if any(_matches(model, pattern) for pattern in rule["match"]):
            return Capability(
                kind=rule["kind"],
                notes=str(rule.get("notes", "")),
                duration=rule.get("duration") or {},
                size=rule.get("size") or {},
                n=bool(rule.get("n")),
                image_input=bool(rule.get("image_input")),
                pattern=",".join(rule["match"]),
            )
    return None


def guess_kind(model: str) -> str:
    """Best-effort kind when the registry has no rule."""
    lowered = model.lower()
    video_hints = ("video", "t2v", "i2v", "sora", "veo", "hailuo", "kling")
    image_hints = ("image", "t2i", "dall", "flux", "sd", "imagen", "kolors")
    if any(hint in lowered for hint in video_hints):
        return "video"
    if any(hint in lowered for hint in image_hints):
        return "image"
    return "unknown"


def validate_size(model: str, size: str, capability: Capability | None) -> str:
    """Normalize ``--size`` into the form this model expects.

    Accepts ``1024x1024``, ``1024*1024``, ``1024X1024`` and returns the same
    number formatted per the registry (``WxH`` vs ``W*H``), or the raw value for
    ``resolution``/``aspect`` forms.
    """
    form = capability.size_form() if capability else "WxH"
    if form in ("resolution", "aspect"):
        return size.strip()
    cleaned = size.strip().lower().replace("*", "x").replace("×", "x")
    parts = cleaned.split("x")
    if len(parts) != 2 or not all(part.isdigit() and int(part) > 0 for part in parts):
        raise RegistryError(
            f"{model} 的 --size 需要像素尺寸（如 1024x1024）；收到 {size!r}。"
            + (" 该模型用分辨率档位时请写 --resolution。" if form == "resolution" else "")
        )
    width, height = (int(parts[0]), int(parts[1]))
    return f"{width}*{height}" if form == "W*H" else f"{width}x{height}"


def check_duration(model: str, seconds: int, capability: Capability | None) -> int:
    if capability is None:
        return seconds
    choices = capability.duration_choices()
    if choices and seconds not in choices:
        raise RegistryError(
            f"{model} 的时长是枚举值 {choices}；收到 {seconds}s"
        )
    lo, hi, auto = capability.durations()
    if auto is not None and seconds == auto:
        return seconds
    if lo is not None and seconds < lo:
        raise RegistryError(f"{model} 的时长下限是 {lo}s；收到 {seconds}s")
    if hi is not None and seconds > hi:
        raise RegistryError(f"{model} 的时长上限是 {hi}s；收到 {seconds}s")
    return seconds
