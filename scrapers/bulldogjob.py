"""bulldogjob.pl scraper.

Bulldogjob is a Polish dev-focused board. Their public XML API at
``/api/v2/jobs`` ignores all filter params and returns 50 mixed-category
jobs per call. The Next.js listing pages SSR a clean job array into
``__NEXT_DATA__.props.pageProps.jobs``, so we parse that.

The board is dev-heavy and currently has very few designer postings —
fetch hits ``/s/role,Designer`` which is the only filter URL that actually
narrows results. Expect 0 or a small handful of matches per tick.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx
from selectolax.parser import HTMLParser

from models import Job

SOURCE = "bulldogjob.pl"

_LISTING_URL = "https://bulldogjob.pl/companies/jobs/s/role,Designer"
_OFFER_BASE = "https://bulldogjob.pl/companies/jobs/"
_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 job-scraper/0.1"
_TIMEOUT = httpx.Timeout(15.0)

log = logging.getLogger(__name__)


def fetch() -> list[Job]:
    headers = {
        "User-Agent": _USER_AGENT,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "pl,en;q=0.9",
    }
    with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
        r = client.get(_LISTING_URL, headers=headers)
    r.raise_for_status()
    return _parse(r.text)


def _parse(html: str) -> list[Job]:
    parser = HTMLParser(html)
    nd = parser.css_first("script#__NEXT_DATA__")
    if nd is None:
        return []
    try:
        blob = json.loads(nd.text())
    except json.JSONDecodeError as e:
        log.warning("bulldogjob: __NEXT_DATA__ is not JSON: %s", e)
        return []

    raw_jobs = blob.get("props", {}).get("pageProps", {}).get("jobs", [])
    if not isinstance(raw_jobs, list):
        return []

    jobs: list[Job] = []
    seen_ids: set[str] = set()
    for raw in raw_jobs:
        if not isinstance(raw, dict):
            continue
        try:
            job = _to_job(raw)
        except (KeyError, TypeError, ValueError) as e:
            log.warning("bulldogjob: skipping unparseable entry: %s", e)
            continue
        if job is None:
            continue
        if job.id in seen_ids:
            continue
        seen_ids.add(job.id)
        jobs.append(job)
    return jobs


def _to_job(raw: dict[str, Any]) -> Job | None:
    job_id = raw.get("id")
    title = raw.get("position")
    if not isinstance(job_id, str) or not isinstance(title, str) or not title:
        return None
    company_obj = raw.get("company") or {}
    company = (company_obj.get("name") if isinstance(company_obj, dict) else None) or "—"

    seniority = raw.get("experienceLevel")
    if not isinstance(seniority, str) or not seniority:
        seniority = None

    salary = _format_salary(raw.get("denominatedSalaryLong"))

    return Job(
        id=f"{SOURCE}:{job_id}",
        source=SOURCE,
        title=title,
        company=company,
        location=_format_location(raw),
        seniority=seniority,
        salary=salary,
        url=f"{_OFFER_BASE}{job_id}",
        posted_at=None,
    )


def _format_location(raw: dict[str, Any]) -> str:
    """Bulldogjob's job has ``city`` (string, may be comma-joined like
    "Wroclaw, Warsaw") and ``remote`` (bool). We don't have an explicit
    onsite/hybrid flag, so emit both modes for city listings so either
    matches the user's defaults."""
    city = raw.get("city") or ""
    remote = raw.get("remote") is True
    parts: list[str] = []
    if city:
        parts.append(str(city).strip())
    if remote:
        parts.extend(["remote", "PL"])
    elif city:
        parts.extend(["hybrid", "onsite"])
    return ", ".join(parts)


def _format_salary(salary: Any) -> str | None:
    if not isinstance(salary, dict):
        return None
    if salary.get("hidden") is True:
        return None
    money = salary.get("money")
    currency = salary.get("currency")
    if money is None and currency is None:
        return None
    return " ".join(str(p) for p in (money, currency) if p)
