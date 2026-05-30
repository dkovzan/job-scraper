"""linkedin.com scraper.

LinkedIn's public job-search page fetches its results from an unauthenticated
guest endpoint that returns a clean HTML fragment of job cards:

    /jobs-guest/jobs/api/seeMoreJobPostings/search?keywords=...&location=...

LinkedIn TLS-fingerprints clients and rate-limits/blocks datacenter IPs (it
returns 429 or its custom 999 status), so we use curl_cffi with Chrome
impersonation (same as scrapers/theprotocol.py). When blocked, fetch() returns
an empty list and the orchestrator logs and continues.

Guest cards carry no salary and no explicit work-mode, so salary is always None
and city listings are tagged hybrid/onsite to match the other Polish boards.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from datetime import datetime

from curl_cffi import requests as cffi
from selectolax.parser import HTMLParser, Node

from models import Job

SOURCE = "linkedin.com"

# First page only (~25 cards); pagination is intentionally out of scope.
_SEARCH_URL = (
    "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
    "?keywords=UX%2FUI%20designer&location=Poland&start=0"
)
_TIMEOUT = 20
_IMPERSONATE = "chrome120"

_URN_ID = re.compile(r"urn:li:jobPosting:(\d+)")
_URL_ID = re.compile(r"/jobs/view/[^/]*?(\d+)")
_HOST = re.compile(r"^https?://[\w.]*\blinkedin\.com", re.IGNORECASE)
_REMOTE = re.compile(r"\(remote\)|^remote\b", re.IGNORECASE)
_SENIORITY_PATTERN = re.compile(
    r"\b(junior|mid|regular|senior|lead|principal|staff|head|starszy|młodszy)\b",
    re.IGNORECASE,
)

# LinkedIn anglicizes / strips diacritics from Polish city names ("Warsaw",
# "Cracow"). The downstream location filter folds diacritics and matches on
# word boundaries against config cities like "Kraków", so we restore the native
# Polish form here. Keyed by diacritic-free lowercase name.
_CITY_EN_TO_PL: dict[str, str] = {
    "warsaw": "Warszawa",
    "cracow": "Kraków",
    "krakow": "Kraków",
    "lodz": "Łódź",
    "gdansk": "Gdańsk",
    "wroclaw": "Wrocław",
    "poznan": "Poznań",
}

log = logging.getLogger(__name__)


def _parse(html: str) -> list[Job]:
    parser = HTMLParser(html)
    cards = parser.css("div.base-card")
    jobs: list[Job] = []
    seen_ids: set[str] = set()
    for card in cards:
        try:
            job = _to_job(card)
        except (KeyError, AttributeError, ValueError) as e:
            log.warning("linkedin: skipping unparseable card: %s", e)
            continue
        if job is None or job.id in seen_ids:
            continue
        seen_ids.add(job.id)
        jobs.append(job)
    return jobs


def _to_job(card: Node) -> Job | None:
    job_id = _extract_id(card)
    if job_id is None:
        return None

    title = _text(card.css_first("h3.base-search-card__title"))
    if not title:
        return None

    company = _text(card.css_first("h4.base-search-card__subtitle")) or "—"
    location = _format_location(_text(card.css_first("span.job-search-card__location")))
    seniority = _extract_seniority(title)
    url = _clean_url(card)
    posted_at = _parse_dt(card)

    return Job(
        id=f"{SOURCE}:{job_id}",
        source=SOURCE,
        title=title,
        company=company,
        location=location,
        seniority=seniority,
        salary=None,
        url=url,
        posted_at=posted_at,
    )


def _extract_id(card: Node) -> str | None:
    urn = card.attributes.get("data-entity-urn") or ""
    m = _URN_ID.search(urn)
    if m:
        return m.group(1)
    link = card.css_first("a.base-card__full-link")
    href = (link.attributes.get("href") if link else "") or ""
    m = _URL_ID.search(href)
    return m.group(1) if m else None


def _clean_url(card: Node) -> str:
    link = card.css_first("a.base-card__full-link")
    href = (link.attributes.get("href") if link else "") or ""
    href = href.split("?", 1)[0]
    # LinkedIn's guest API serves regional hosts (e.g. pl.linkedin.com);
    # normalize to the canonical www host so URLs are deterministic.
    return _HOST.sub("https://www.linkedin.com", href)


def _normalize_city(city: str) -> str:
    key = "".join(
        c for c in unicodedata.normalize("NFKD", city) if not unicodedata.combining(c)
    ).casefold()
    return _CITY_EN_TO_PL.get(key, city)


def _format_location(raw: str) -> str:
    raw = raw.strip()
    if not raw:
        return ""
    if _REMOTE.search(raw):
        return "Remote, PL"
    # Take the leading city token (LinkedIn gives "City, Region, Country").
    city = _normalize_city(raw.split(",", 1)[0].strip())
    return f"{city}, hybrid, onsite"


def _extract_seniority(title: str) -> str | None:
    m = _SENIORITY_PATTERN.search(title)
    return m.group(1).lower() if m else None


def _parse_dt(card: Node) -> datetime | None:
    t = card.css_first("time")
    dt = (t.attributes.get("datetime") if t else "") or ""
    if not dt:
        return None
    try:
        return datetime.fromisoformat(dt.replace("Z", "+00:00"))
    except ValueError:
        return None


def _text(node: Node | None) -> str:
    if node is None:
        return ""
    return " ".join(node.text(strip=True).split())


def fetch() -> list[Job]:
    try:
        r = cffi.get(_SEARCH_URL, impersonate=_IMPERSONATE, timeout=_TIMEOUT)
    except cffi.RequestsError as e:  # pragma: no cover (network)
        log.warning("linkedin.com: request failed: %s", e)
        return []

    if r.status_code != 200:
        # 429 / 999 are LinkedIn's datacenter-IP throttle responses.
        log.warning("linkedin.com: unexpected status %d — returning 0 jobs", r.status_code)
        return []
    if not r.text.strip():
        log.warning("linkedin.com: empty body — returning 0 jobs")
        return []
    return _parse(r.text)
