"""theprotocol.it scraper.

theprotocol.it is fronted by Cloudflare's "Just a moment…" challenge, which
plain ``httpx`` can't bypass. We use ``curl_cffi`` to send a request with
Chrome's TLS fingerprint, which clears the challenge and returns the same
SSR'd page a real browser would.

The page embeds a clean ``__NEXT_DATA__`` JSON blob; offers live at
``props.pageProps.offersResponse.offers``.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any

from curl_cffi import requests as cffi
from selectolax.parser import HTMLParser

from models import Job

SOURCE = "theprotocol.it"

_LISTING_URL = "https://theprotocol.it/filtry/ux-ui;sp/praca"
_OFFER_BASE = "https://theprotocol.it/szczegoly/"
_TIMEOUT = 20
_IMPERSONATE = "chrome120"

_CHALLENGE_BODY_MARKER = re.compile(r"Just a moment", re.IGNORECASE)

# Polish work-mode tokens used by theprotocol → tokens used in defaults.locations.
_WORK_MODE_PL_TO_EN: dict[str, str] = {
    "stacjonarna": "onsite",
    "hybrydowa": "hybrid",
    "zdalna": "remote",
    "mobilna": "onsite",
}

log = logging.getLogger(__name__)


def fetch() -> list[Job]:
    try:
        r = cffi.get(_LISTING_URL, impersonate=_IMPERSONATE, timeout=_TIMEOUT)
    except cffi.RequestsError as e:  # pragma: no cover (network)
        log.warning("theprotocol.it: request failed: %s", e)
        return []

    if _is_cf_challenge(r):
        log.warning(
            "theprotocol.it: still blocked by Cloudflare (status=%d) — returning 0 jobs",
            r.status_code,
        )
        return []
    if r.status_code != 200:
        log.warning("theprotocol.it: unexpected status %d", r.status_code)
        return []
    return _parse(r.text)


def _is_cf_challenge(response: Any) -> bool:
    if response.headers.get("cf-mitigated") == "challenge":
        return True
    if response.status_code == 403 and _CHALLENGE_BODY_MARKER.search(response.text):
        return True
    return False


def _parse(html: str) -> list[Job]:
    parser = HTMLParser(html)
    nd = parser.css_first("script#__NEXT_DATA__")
    if nd is None:
        return []
    try:
        blob = json.loads(nd.text())
    except json.JSONDecodeError:
        return []

    offers = blob.get("props", {}).get("pageProps", {}).get("offersResponse", {}).get("offers", [])
    if not isinstance(offers, list):
        return []

    jobs: list[Job] = []
    seen_ids: set[str] = set()
    for raw in offers:
        if not isinstance(raw, dict):
            continue
        try:
            job = _to_job(raw)
        except (KeyError, TypeError, ValueError) as e:
            log.warning("theprotocol: skipping unparseable offer: %s", e)
            continue
        if job is None or job.id in seen_ids:
            continue
        seen_ids.add(job.id)
        jobs.append(job)
    return jobs


def _to_job(raw: dict[str, Any]) -> Job | None:
    offer_id = raw.get("id")
    title = raw.get("title")
    if not isinstance(offer_id, str) or not isinstance(title, str) or not title:
        return None

    employer = raw.get("employer")
    company = employer if isinstance(employer, str) and employer else "—"

    seniority = _extract_seniority(raw)
    salary = _format_salary(raw.get("salary"))
    location = _format_location(raw)

    offer_url_name = raw.get("offerUrlName")
    url = (
        f"{_OFFER_BASE}{offer_url_name}"
        if isinstance(offer_url_name, str) and offer_url_name
        else _LISTING_URL
    )

    return Job(
        id=f"{SOURCE}:{offer_id}",
        source=SOURCE,
        title=title,
        company=company,
        location=location,
        seniority=seniority,
        salary=salary,
        url=url,
        posted_at=_parse_dt(raw.get("publicationDateUtc")),
    )


def _extract_seniority(raw: dict[str, Any]) -> str | None:
    levels = raw.get("positionLevels")
    if not isinstance(levels, list) or not levels:
        return None
    first = levels[0]
    if isinstance(first, dict):
        v = first.get("value")
        if isinstance(v, str) and v:
            return v.lower()
    return None


def _format_location(raw: dict[str, Any]) -> str:
    workplaces = raw.get("workplace") or []
    work_modes = raw.get("workModes") or []

    cities: list[str] = []
    if isinstance(workplaces, list):
        for wp in workplaces:
            if isinstance(wp, dict):
                city = wp.get("city") or wp.get("location")
                if isinstance(city, str) and city:
                    cities.append(city)
    seen_cities: set[str] = set()
    cities = [c for c in cities if not (c in seen_cities or seen_cities.add(c))]

    modes_en: list[str] = []
    if isinstance(work_modes, list):
        for m in work_modes:
            if isinstance(m, str):
                en = _WORK_MODE_PL_TO_EN.get(m.lower())
                if en and en not in modes_en:
                    modes_en.append(en)

    is_remote = "remote" in modes_en

    parts: list[str] = []
    if cities:
        parts.extend(cities)
    if modes_en:
        parts.extend(modes_en)
        if is_remote:
            parts.append("PL")
    elif cities:
        # No explicit work-mode on the offer — assume hybrid/onsite so the
        # user's defaults can match either, matching the other Polish-board
        # scrapers' convention.
        parts.extend(["hybrid", "onsite"])
    return ", ".join(parts)


def _format_salary(salary: Any) -> str | None:
    if not isinstance(salary, dict):
        return None
    lo = salary.get("from") or salary.get("min")
    hi = salary.get("to") or salary.get("max")
    cur = salary.get("currency") or ""
    kind = salary.get("type") or salary.get("contractType") or ""
    if lo is None and hi is None:
        return None
    if lo is not None and hi is not None:
        rng = f"{lo} – {hi}"
    else:
        rng = str(lo if lo is not None else hi)
    bits = [rng, str(cur).upper(), str(kind).upper()]
    return " ".join(b for b in bits if b)


def _parse_dt(s: Any) -> datetime | None:
    if not isinstance(s, str) or not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
