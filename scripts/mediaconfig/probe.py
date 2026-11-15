"""只读探测端点的 /models。"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from .paths import *  # noqa: F401,F403

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


