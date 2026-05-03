"""justjoin.it scraper.

Hits the public listings API used by the justjoin.it SPA, filtered to the
design vertical (categoryId=14), and maps each entry to a Job.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import httpx

from models import Job

SOURCE = "justjoin.it"
DESIGN_CATEGORY_ID = 14
ITEMS_PER_PAGE = 20

_API_URL = "https://api.justjoin.it/v2/user-panel/offers"
_OFFER_PAGE_URL = "https://justjoin.it/job-offer/{slug}"
_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 job-scraper/0.1"
_TIMEOUT = httpx.Timeout(10.0)

# Map upstream workplaceType values to the mode tokens used in defaults.locations.
_WORKPLACE_TO_MODE: dict[str, str] = {
    "office": "onsite",
    "hybrid": "hybrid",
    "remote": "remote",
}

log = logging.getLogger(__name__)


def fetch() -> list[Job]:
    """Pull the latest page of design listings and map them to Jobs."""
    url = f"{_API_URL}?categories[]={DESIGN_CATEGORY_ID}&itemsPerPage={ITEMS_PER_PAGE}&page=1"
    headers = {
        "User-Agent": _USER_AGENT,
        "Accept": "application/json",
        "Origin": "https://justjoin.it",
        "Referer": "https://justjoin.it/",
        "Version": "2",
    }
    with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
        r = client.get(url, headers=headers)
    r.raise_for_status()
    return _parse(r.json())


def _parse(payload: Any) -> list[Job]:
    listings = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(listings, list):
        return []
    jobs: list[Job] = []
    for entry in listings:
        if not isinstance(entry, dict):
            continue
        try:
            jobs.append(_to_job(entry))
        except (KeyError, TypeError, ValueError) as e:
            log.warning("justjoin: skipping unparseable entry: %s", e)
    return jobs


def _to_job(entry: dict[str, Any]) -> Job:
    slug = entry["slug"]
    title = entry["title"]
    company = entry.get("companyName") or "—"
    seniority = entry.get("experienceLevel") or None
    return Job(
        id=f"{SOURCE}:{slug}",
        source=SOURCE,
        title=title,
        company=company,
        location=_format_location(entry),
        seniority=seniority,
        salary=_format_salary(entry.get("employmentTypes")),
        url=_OFFER_PAGE_URL.format(slug=slug),
        posted_at=_parse_dt(entry.get("publishedAt")),
    )


def _format_location(entry: dict[str, Any]) -> str:
    city = (entry.get("city") or "").strip()
    workplace = (entry.get("workplaceType") or "").strip().lower()
    mode = _WORKPLACE_TO_MODE.get(workplace, workplace)
    parts: list[str] = []
    if city:
        parts.append(city)
    if mode:
        parts.append(mode)
    # justjoin.it is a Polish board — flag remote listings with PL so the
    # country=PL+remote default clause can match them.
    if mode == "remote":
        parts.append("PL")
    return ", ".join(parts)


def _format_salary(employment_types: Any) -> str | None:
    if not isinstance(employment_types, list) or not employment_types:
        return None
    parts: list[str] = []
    for et in employment_types:
        if not isinstance(et, dict):
            continue
        lo, hi = et.get("from"), et.get("to")
        cur = (et.get("currency") or "").upper()
        kind = (et.get("type") or "").upper()
        if lo is None and hi is None:
            continue
        if lo is not None and hi is not None:
            rng = f"{lo:,}–{hi:,}".replace(",", " ")
        else:
            rng = f"{lo if lo is not None else hi:,}".replace(",", " ")
        bits = [rng, cur, kind]
        parts.append(" ".join(b for b in bits if b))
    return " / ".join(parts) if parts else None


def _parse_dt(s: Any) -> datetime | None:
    if not isinstance(s, str) or not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
