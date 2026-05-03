"""nofluffjobs.com scraper.

NFJ exposes a JSON API at ``/api/posting`` but it ignores filter params and
returns ~145 MB of all 19 000+ postings on every call. The category landing
page (``/pl/design``) is the practical alternative: it ships ~750 KB of HTML
with 20 design listings as Angular SSR'd cards. We parse those.
"""

from __future__ import annotations

import logging
import re

import httpx
from selectolax.parser import HTMLParser, Node

from models import Job

SOURCE = "nofluffjobs.com"

_LANDING_URL = "https://nofluffjobs.com/pl/design"
_OFFER_BASE = "https://nofluffjobs.com"
_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 job-scraper/0.1"
_TIMEOUT = httpx.Timeout(15.0)

_SENIORITY_PATTERN = re.compile(
    r"\b(junior|mid|regular|senior|lead|principal|staff|head|starszy|młodszy)\b",
    re.IGNORECASE,
)
_NEW_BADGE = re.compile(r"\s*NOWA\s*$", re.IGNORECASE)

log = logging.getLogger(__name__)


def fetch() -> list[Job]:
    """Pull the design landing page and parse its 20 SSR'd cards."""
    headers = {
        "User-Agent": _USER_AGENT,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "pl,en;q=0.9",
    }
    with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
        r = client.get(_LANDING_URL, headers=headers)
    r.raise_for_status()
    return _parse(r.text)


def _parse(html: str) -> list[Job]:
    parser = HTMLParser(html)
    cards = [a for a in parser.css("a") if (a.attributes.get("href") or "").startswith("/pl/job/")]
    jobs: list[Job] = []
    seen_slugs: set[str] = set()
    for card in cards:
        try:
            job = _to_job(card)
        except (KeyError, AttributeError, ValueError) as e:
            log.warning("nofluffjobs: skipping unparseable card: %s", e)
            continue
        if job is None:
            continue
        slug = job.id.split(":", 1)[1]
        # The landing HTML occasionally repeats the same listing twice; dedup.
        if slug in seen_slugs:
            continue
        seen_slugs.add(slug)
        jobs.append(job)
    return jobs


def _to_job(card: Node) -> Job | None:
    href = card.attributes.get("href")
    if not href or not href.startswith("/pl/job/"):
        return None
    slug = href[len("/pl/job/") :]
    if not slug:
        return None

    title = _text(card.css_first('[data-cy="title position on the job offer listing"]'))
    title = _strip_new_badge(title)
    if not title:
        return None

    company = _text(card.css_first("h4.company-name")) or "—"
    salary_text = _text(card.css_first('[data-cy="salary ranges on the job offer listing"]'))
    location_text = _text(card.css_first('[data-cy="location on the job offer listing"]'))
    salary = _normalise_salary(salary_text)
    location = _format_location(location_text)
    seniority = _extract_seniority(title)

    return Job(
        id=f"{SOURCE}:{slug}",
        source=SOURCE,
        title=title,
        company=company,
        location=location,
        seniority=seniority,
        salary=salary,
        url=f"{_OFFER_BASE}{href}",
        posted_at=None,
    )


def _text(node: Node | None) -> str:
    if node is None:
        return ""
    return " ".join(node.text(strip=True).split())


def _strip_new_badge(s: str) -> str:
    return _NEW_BADGE.sub("", s).strip()


def _normalise_salary(s: str) -> str | None:
    """Card salary text is squashed (no spaces around dash); split it back out."""
    if not s:
        return None
    # Insert spaces around an en-dash that has no surrounding spaces.
    s = re.sub(r"(\d)–(\d)", r"\1 – \2", s)
    # Normalize "21 840– 23 520PLN" → "21 840 – 23 520 PLN"
    s = re.sub(r"(\d)–\s+", r"\1 – ", s)
    s = re.sub(r"(\d)([A-Z]{3})", r"\1 \2", s)
    return s.strip()


def _format_location(raw: str) -> str:
    """NFJ location text is one of:
      - "Zdalnie"          → fully remote (Polish board, treat as PL)
      - "Zdalnie+1"        → remote with one alt
      - "Warszawa"         → onsite/hybrid in city
      - "Warszawa+1"       → city plus alt
    For the city case we don't get an explicit work-mode tag from the
    listing, so emit both ``onsite`` and ``hybrid`` so the user's defaults
    can match either. Remote listings get the ``PL`` country tag.
    """
    raw = raw.strip()
    raw = re.sub(r"\+\d+\s*$", "", raw).strip()  # drop "+1" alt-locations suffix
    if not raw:
        return ""
    if raw.lower().startswith("zdaln"):
        return "Remote, PL"
    return f"{raw}, hybrid, onsite"


def _extract_seniority(title: str) -> str | None:
    m = _SENIORITY_PATTERN.search(title)
    return m.group(1).lower() if m else None
