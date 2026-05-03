"""Read/write helpers for the four files that live on the parallel ``state``
branch (checked out into ``.state/`` at workflow time).

All loaders return an empty container when the underlying file is missing,
so the first ever run on a fresh checkout doesn't crash. All savers
``mkdir(parents=True)`` their target directory so a missing ``.state/`` dir
isn't fatal either.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from models import Profile

# failure_counts.json has no path key in config.toml — it's a Phase 7
# concern; expose a default filename here so callers don't hardcode it.
FAILURE_COUNTS_FILENAME = "failure_counts.json"

DEFAULT_MAX_SEEN_IDS = 5000


# ----------- subscriptions.json -----------


def load_subscriptions(path: str | Path) -> dict[str, list[Profile]]:
    """``{chat_id: [Profile, ...]}``. Missing file → ``{}``."""
    raw = _read_json(path)
    if not isinstance(raw, dict):
        return {}
    out: dict[str, list[Profile]] = {}
    for chat_id, payload in raw.items():
        if not isinstance(payload, dict):
            continue
        profiles = payload.get("profiles", [])
        if not isinstance(profiles, list):
            continue
        out[str(chat_id)] = [_profile_from_dict(p) for p in profiles if _is_valid_profile_dict(p)]
    return out


def save_subscriptions(path: str | Path, data: dict[str, list[Profile]]) -> None:
    out = {
        str(chat_id): {
            "profiles": [{"name": pr.name, "keywords": list(pr.keywords)} for pr in profiles]
        }
        for chat_id, profiles in data.items()
    }
    _write_json(path, out)


def _profile_from_dict(p: dict[str, Any]) -> Profile:
    return Profile(name=str(p["name"]), keywords=[str(k) for k in p.get("keywords", [])])


def _is_valid_profile_dict(p: Any) -> bool:
    return (
        isinstance(p, dict)
        and isinstance(p.get("name"), str)
        and isinstance(p.get("keywords", []), list)
    )


# ----------- seen_jobs.json -----------


def load_seen_jobs(path: str | Path) -> dict[str, list[str]]:
    """``{chat_id: [job_id, ...]}`` (oldest first). Missing file → ``{}``."""
    raw = _read_json(path)
    if not isinstance(raw, dict):
        return {}
    out: dict[str, list[str]] = {}
    for chat_id, ids in raw.items():
        if isinstance(ids, list):
            out[str(chat_id)] = [str(i) for i in ids]
    return out


def save_seen_jobs(
    path: str | Path,
    data: dict[str, list[str]],
    max_per_user: int = DEFAULT_MAX_SEEN_IDS,
) -> None:
    """Write seen-job IDs, trimming each user's list to the last ``max_per_user``
    entries (FIFO — keep the most recent)."""
    trimmed = {
        str(chat_id): list(ids[-max_per_user:] if max_per_user > 0 else [])
        for chat_id, ids in data.items()
    }
    _write_json(path, trimmed)


# ----------- tg_offset.txt -----------


def load_offset(path: str | Path) -> int:
    """Last-processed Telegram update_id. Missing/blank/invalid → 0."""
    p = Path(path)
    if not p.exists():
        return 0
    try:
        return int(p.read_text(encoding="utf-8").strip() or "0")
    except (OSError, ValueError):
        return 0


def save_offset(path: str | Path, offset: int) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"{int(offset)}\n", encoding="utf-8")


# ----------- failure_counts.json -----------


def load_failure_counts(path: str | Path) -> dict[str, int]:
    """``{source_name: consecutive_failure_count}``. Missing file → ``{}``."""
    raw = _read_json(path)
    if not isinstance(raw, dict):
        return {}
    out: dict[str, int] = {}
    for k, v in raw.items():
        try:
            out[str(k)] = int(v)
        except (TypeError, ValueError):
            continue
    return out


def save_failure_counts(path: str | Path, data: dict[str, int]) -> None:
    out = {str(k): int(v) for k, v in data.items()}
    _write_json(path, out)


# ----------- io helpers -----------


def _read_json(path: str | Path) -> Any:
    p = Path(path)
    if not p.exists():
        return None
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return None
    if not text.strip():
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _write_json(path: str | Path, data: Any) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
