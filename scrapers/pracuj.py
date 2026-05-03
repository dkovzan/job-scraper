"""pracuj.pl scraper.

pracuj.pl is the largest Polish job board. It is fronted by Cloudflare's
challenge, so we use ``curl_cffi`` (Chrome TLS fingerprint) to fetch the
listing page. The cards are stable: each ``[data-test='default-offer']``
exposes everything we need via specific ``data-test`` attributes.
"""

from __future__ import annotations

import logging
import re

from curl_cffi import requests as cffi
from selectolax.parser import HTMLParser, Node

from models import Job

SOURCE = "pracuj.pl"

# Filter-by-keyword URL — narrower (and more reliable) than the numeric
# category codes in the cc= query param.
_LISTING_URL = "https://it.pracuj.pl/praca/ux%20designer"
_OFFER_BASE = "https://www.pracuj.pl"
_TIMEOUT = 20
_IMPERSONATE = "chrome120"

_CHALLENGE_BODY_MARKER = re.compile(r"Just a moment", re.IGNORECASE)
_SENIORITY_PATTERN = re.compile(
    r"\b(junior|mid|regular|senior|lead|principal|staff|head|starszy|młodszy)\b",
    re.IGNORECASE,
)

# Polish work-mode keywords pracuj uses → tokens used in defaults.locations.
_WORK_MODE_PL_TO_EN: list[tuple[str, str]] = [
    ("hybrydowa", "hybrid"),
    ("zdalna", "remote"),
    ("stacjonarna", "onsite"),
    ("mobilna", "onsite"),
]

log = logging.getLogger(__name__)


def fetch() -> list[Job]:
    try:
        r = cffi.get(_LISTING_URL, impersonate=_IMPERSONATE, timeout=_TIMEOUT)
    except cffi.RequestsError as e:  # pragma: no cover (network)
        log.warning("pracuj.pl: request failed: %s", e)
        return []

    if _is_cf_challenge(r):
        log.warning(
            "pracuj.pl: still blocked by Cloudflare (status=%d) — returning 0 jobs",
            r.status_code,
        )
        return []
    if r.status_code != 200:
        log.warning("pracuj.pl: unexpected status %d", r.status_code)
        return []
    return _parse(r.text)


def _is_cf_challenge(response) -> bool:
    if response.headers.get("cf-mitigated") == "challenge":
        return True
    if response.status_code == 403 and _CHALLENGE_BODY_MARKER.search(response.text):
        return True
    return False


def _parse(html: str) -> list[Job]:
    parser = HTMLParser(html)
    cards = parser.css("[data-test='default-offer']")
    jobs: list[Job] = []
    seen_ids: set[str] = set()
    for card in cards:
        try:
            job = _to_job(card)
        except (KeyError, AttributeError, ValueError) as e:
            log.warning("pracuj: skipping unparseable card: %s", e)
            continue
        if job is None or job.id in seen_ids:
            continue
        seen_ids.add(job.id)
        jobs.append(job)
    return jobs


def _to_job(card: Node) -> Job | None:
    offer_id = card.attributes.get("data-test-offerid")
    if not offer_id:
        return None

    link = card.css_first("[data-test='link-offer-title']") or card.css_first(
        "[data-test='link-offer']"
    )
    title = _text(card.css_first("[data-test='offer-title']"))
    if not title and link is not None:
        title = _text(link)
    if not title:
        return None

    href = ""
    if link is not None:
        href = link.attributes.get("href") or ""
    if href and not href.startswith("http"):
        href = f"{_OFFER_BASE}{href if href.startswith('/') else '/' + href}"

    company = _text(card.css_first("[data-test='text-company-name']")) or "—"
    salary_raw = _text(card.css_first("[data-test='offer-salary']"))
    salary = _normalise_whitespace(salary_raw) or None

    additional_info = _collect_additional_info(card)
    seniority = _extract_seniority(additional_info, title)
    location = _format_location(card, additional_info)

    return Job(
        id=f"{SOURCE}:{offer_id}",
        source=SOURCE,
        title=title,
        company=company,
        location=location,
        seniority=seniority,
        salary=salary,
        url=href or _LISTING_URL,
        posted_at=None,
    )


def _text(node: Node | None) -> str:
    if node is None:
        return ""
    return _normalise_whitespace(node.text(strip=True))


def _normalise_whitespace(s: str) -> str:
    return " ".join(s.split())


def _collect_additional_info(card: Node) -> list[str]:
    """Pracuj puts seniority / work-mode / contract type into a series of
    ``offer-additional-info-N`` spans (N = 0..7+). Position varies, so we
    grab them all and let extractors search by keyword."""
    out: list[str] = []
    for i in range(10):
        el = card.css_first(f"[data-test='offer-additional-info-{i}']")
        if el is None:
            continue
        text = _text(el)
        if text:
            out.append(text)
    return out


def _extract_seniority(infos: list[str], title: str) -> str | None:
    haystack = " | ".join(infos + [title])
    m = _SENIORITY_PATTERN.search(haystack)
    return m.group(1).lower() if m else None


def _format_location(card: Node, infos: list[str]) -> str:
    """Build a location string the same way other Polish-board scrapers do:
    fully remote → ``Remote, PL``; otherwise ``<city>, <mode>`` (default to
    ``hybrid, onsite`` if no explicit work-mode tag was present)."""
    region = _text(card.css_first("[data-test='text-region']"))
    mode = _detect_mode(infos)

    if mode == "remote":
        return "Remote, PL"

    city = re.split(r"[,(]", region)[0].strip() if region else ""
    parts: list[str] = []
    if city:
        parts.append(city)
    if mode:
        parts.append(mode)
    elif city:
        parts.extend(["hybrid", "onsite"])
    return ", ".join(parts)


def _detect_mode(infos: list[str]) -> str | None:
    haystack = " ".join(infos).lower()
    for token, mapped in _WORK_MODE_PL_TO_EN:
        if token in haystack:
            return mapped
    return None
