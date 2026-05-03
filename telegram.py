"""Low-level wrapper around the Telegram Bot HTTP API.

Module-level ``send_message`` posts to ``sendMessage`` with retry handling for
429 (sleeps the server-supplied ``retry_after`` and retries). After a
successful send, sleeps a randomised 1–2s to stay below Telegram's per-bot
rate limit. ``format_job`` renders a ``Job`` into the Markdown layout from
the spec.

Note: this top-level module shadows the third-party ``python-telegram-bot``
package (which also installs as ``telegram``). We don't depend on PTB; this
is intentional and matches the repo layout in the spec.
"""

from __future__ import annotations

import logging
import os
import random
import time
from collections.abc import Callable
from dataclasses import dataclass

import httpx

from models import Job, Profile

log = logging.getLogger(__name__)

API_BASE = "https://api.telegram.org"
DEFAULT_PARSE_MODE = "Markdown"

_HTTP_TIMEOUT = httpx.Timeout(15.0)
_THROTTLE_RANGE = (1.0, 2.0)
_MAX_429_RETRIES = 3


@dataclass(frozen=True)
class SendResult:
    chat_id: str
    ok: bool
    error: str | None = None


def get_bot_token() -> str:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN env var not set")
    return token


def make_client() -> httpx.Client:
    """Create an httpx.Client suitable for re-use across sends in one run."""
    return httpx.Client(timeout=_HTTP_TIMEOUT, base_url=API_BASE)


def send_message(
    chat_id: str | int,
    text: str,
    parse_mode: str | None = DEFAULT_PARSE_MODE,
    *,
    client: httpx.Client | None = None,
    sleeper: Callable[[float], None] = time.sleep,
    rng: Callable[[float, float], float] = random.uniform,
) -> SendResult:
    """POST to sendMessage. On 429, honour ``retry_after`` and retry up to
    ``_MAX_429_RETRIES`` times. After a successful send, sleep 1–2s.

    Pass ``client`` to share an HTTP connection across sends. ``sleeper`` /
    ``rng`` are injectable to keep tests fast and deterministic.
    """
    own_client = client is None
    if own_client:
        client = make_client()
    try:
        return _send(client, chat_id, text, parse_mode, sleeper, rng)
    finally:
        if own_client:
            client.close()


def _send(
    client: httpx.Client,
    chat_id: str | int,
    text: str,
    parse_mode: str | None,
    sleeper: Callable[[float], None],
    rng: Callable[[float, float], float],
) -> SendResult:
    url = f"/bot{get_bot_token()}/sendMessage"
    payload: dict[str, object] = {"chat_id": str(chat_id), "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode

    for attempt in range(1, _MAX_429_RETRIES + 1):
        try:
            r = client.post(url, json=payload)
        except httpx.HTTPError as e:
            log.warning("telegram send transport error for chat %s: %s", chat_id, e)
            return SendResult(str(chat_id), ok=False, error=f"transport: {e}")

        if r.status_code == 200:
            sleeper(rng(*_THROTTLE_RANGE))
            return SendResult(str(chat_id), ok=True)

        if r.status_code == 429:
            retry_after = _parse_retry_after(r)
            log.warning(
                "telegram 429 for chat %s; retrying after %.1fs (attempt %d/%d)",
                chat_id,
                retry_after,
                attempt,
                _MAX_429_RETRIES,
            )
            sleeper(retry_after)
            continue

        err = f"HTTP {r.status_code}: {r.text[:200]}"
        log.warning("telegram send failed for chat %s: %s", chat_id, err)
        return SendResult(str(chat_id), ok=False, error=err)

    return SendResult(str(chat_id), ok=False, error=f"exceeded {_MAX_429_RETRIES} 429 retries")


def _parse_retry_after(response: httpx.Response) -> float:
    try:
        body = response.json()
    except ValueError:
        body = {}
    raw = body.get("parameters", {}).get("retry_after") if isinstance(body, dict) else None
    try:
        return float(raw) if raw is not None else 1.0
    except (TypeError, ValueError):
        return 1.0


# ----------- formatting -----------


def format_job(job: Job, profile: Profile) -> str:
    """Render a job into the spec'd Markdown layout."""
    seniority = _esc(job.seniority) if job.seniority else "—"
    salary = _esc(job.salary) if job.salary else "—"
    return (
        f"*{_esc(job.title)}* — {_esc(job.company)}\n"
        f"📍 {_esc(job.location)}  •  {seniority}\n"
        f"💰 {salary}\n"
        f"🔗 {_esc(job.url)}\n"
        f"_via {_esc(job.source)} • matched: {_esc(profile.name)}_"
    )


def _esc(s: str) -> str:
    """Minimal Telegram Markdown V1 escape — back-slash the chars that would
    otherwise open formatting (``_*[`\\``)."""
    return (
        s.replace("\\", "\\\\")
        .replace("_", "\\_")
        .replace("*", "\\*")
        .replace("[", "\\[")
        .replace("`", "\\`")
    )
