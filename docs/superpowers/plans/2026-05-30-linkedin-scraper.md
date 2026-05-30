# LinkedIn Scraper Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add LinkedIn as a sixth job source, surfacing UX/UI designer postings in Poland via LinkedIn's public guest jobs API, plugged into the existing `fetch() -> list[Job]` contract.

**Architecture:** A single `scrapers/linkedin.py` module exposing `fetch()`, transported over `curl_cffi` with Chrome TLS impersonation (same pattern as `scrapers/theprotocol.py`). It hits the unauthenticated guest endpoint `/jobs-guest/jobs/api/seeMoreJobPostings/search`, which returns an HTML fragment of job cards, and parses them with `selectolax`. Blocking (`429`/`999` from datacenter IPs) degrades to an empty list — `_scrape_all` in `main.py` already handles that by logging and continuing.

**Tech Stack:** Python 3.11+, `curl_cffi` (already a dependency), `selectolax` (already a dependency), `pytest`, `ruff`.

---

## File Structure

- **Create:** `scrapers/linkedin.py` — the scraper module (`fetch()` + `_parse()` + helpers).
- **Create:** `tests/test_linkedin.py` — unit tests, primarily against deterministic inline HTML plus the committed fixture.
- **Create:** `tests/fixtures/linkedin_guest.html` — a saved guest-API fragment (captured from the live site, or hand-built from the documented card structure if capture is blocked).
- **Modify:** `scrapers/__init__.py` — register `linkedin.fetch` in `SCRAPERS`.
- **Modify:** `scripts/capture_fixtures.py` — add a `capture_linkedin()` entry so the fixture can be refreshed.

### LinkedIn guest job-card structure (reference)

The guest endpoint returns a fragment of `<li>` elements, each containing a card like:

```html
<li>
  <div class="base-card relative ... job-search-card"
       data-entity-urn="urn:li:jobPosting:3812345678">
    <a class="base-card__full-link"
       href="https://www.linkedin.com/jobs/view/ux-ui-designer-at-acme-3812345678?refId=abc&trackingId=xyz">
      <span class="sr-only">UX/UI Designer</span>
    </a>
    <div class="base-search-card__info">
      <h3 class="base-search-card__title">UX/UI Designer</h3>
      <h4 class="base-search-card__subtitle">
        <a class="hidden-nested-link" href="...">Acme Sp. z o.o.</a>
      </h4>
      <div class="base-search-card__metadata">
        <span class="job-search-card__location">Warsaw, Mazowieckie, Poland</span>
        <time class="job-search-card__listdate" datetime="2026-05-28">2 days ago</time>
      </div>
    </div>
  </div>
</li>
```

---

## Task 1: Scaffold the module and parse a single card (TDD)

**Files:**
- Create: `scrapers/linkedin.py`
- Test: `tests/test_linkedin.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_linkedin.py` with a deterministic inline fragment (two cards: one city, one remote) and the first assertions:

```python
from datetime import datetime

from models import Job
from scrapers.linkedin import _parse, fetch

SAMPLE_HTML = """
<li>
  <div class="base-card job-search-card" data-entity-urn="urn:li:jobPosting:3812345678">
    <a class="base-card__full-link"
       href="https://www.linkedin.com/jobs/view/senior-ux-ui-designer-at-acme-3812345678?refId=abc&trackingId=xyz">
      <span class="sr-only">Senior UX/UI Designer</span>
    </a>
    <div class="base-search-card__info">
      <h3 class="base-search-card__title"> Senior UX/UI Designer </h3>
      <h4 class="base-search-card__subtitle"><a href="#">Acme Sp. z o.o.</a></h4>
      <div class="base-search-card__metadata">
        <span class="job-search-card__location">Warsaw, Mazowieckie, Poland</span>
        <time class="job-search-card__listdate" datetime="2026-05-28">2 days ago</time>
      </div>
    </div>
  </div>
</li>
<li>
  <div class="base-card job-search-card" data-entity-urn="urn:li:jobPosting:3899999999">
    <a class="base-card__full-link"
       href="https://www.linkedin.com/jobs/view/product-designer-3899999999">
      <span class="sr-only">Product Designer</span>
    </a>
    <div class="base-search-card__info">
      <h3 class="base-search-card__title">Product Designer</h3>
      <h4 class="base-search-card__subtitle"><a href="#">Beta Studio</a></h4>
      <div class="base-search-card__metadata">
        <span class="job-search-card__location">Poland (Remote)</span>
      </div>
    </div>
  </div>
</li>
"""


def test_parse_returns_jobs_with_correct_shape():
    jobs = _parse(SAMPLE_HTML)
    assert len(jobs) == 2
    for j in jobs:
        assert isinstance(j, Job)
        assert j.source == "linkedin.com"
        assert j.id.startswith("linkedin.com:")
        assert j.title
        assert j.company
        assert j.url.startswith("https://www.linkedin.com/jobs/view/")


def test_parse_extracts_first_card_fields():
    first = _parse(SAMPLE_HTML)[0]
    assert first.id == "linkedin.com:3812345678"
    assert first.title == "Senior UX/UI Designer"
    assert first.company == "Acme Sp. z o.o."
    assert first.url == "https://www.linkedin.com/jobs/view/senior-ux-ui-designer-at-acme-3812345678"
    assert first.salary is None
    assert first.posted_at == datetime(2026, 5, 28)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_linkedin.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scrapers.linkedin'`.

- [ ] **Step 3: Write minimal implementation**

Create `scrapers/linkedin.py`:

```python
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
from datetime import datetime
from typing import Any

from curl_cffi import requests as cffi
from selectolax.parser import HTMLParser, Node

from models import Job

SOURCE = "linkedin.com"

_SEARCH_URL = (
    "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
    "?keywords=UX%2FUI%20designer&location=Poland&start=0"
)
_TIMEOUT = 20
_IMPERSONATE = "chrome120"

_URN_ID = re.compile(r"urn:li:jobPosting:(\d+)")
_URL_ID = re.compile(r"/jobs/view/(?:[^/]*-)?(\d+)")
_SENIORITY_PATTERN = re.compile(
    r"\b(junior|mid|regular|senior|lead|principal|staff|head|starszy|młodszy)\b",
    re.IGNORECASE,
)

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
    return href.split("?", 1)[0]


def _format_location(raw: str) -> str:
    raw = raw.strip()
    if not raw:
        return ""
    if "remote" in raw.lower():
        return "Remote, PL"
    # Take the leading city token (LinkedIn gives "City, Region, Country").
    city = raw.split(",", 1)[0].strip()
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_linkedin.py -v`
Expected: PASS (both tests).

- [ ] **Step 5: Commit**

```bash
git add scrapers/linkedin.py tests/test_linkedin.py
git commit -m "feat(linkedin): parse guest job cards into Jobs"
```

---

## Task 2: Location convention, dedup, stability, and malformed-input tests

**Files:**
- Modify: `tests/test_linkedin.py`
- Modify: `scrapers/linkedin.py` (only if a test fails)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_linkedin.py`:

```python
def test_remote_location_tagged_with_pl():
    jobs = _parse(SAMPLE_HTML)
    remote = [j for j in jobs if "remote" in j.location.lower()]
    assert remote, "sample has a remote listing"
    for j in remote:
        assert j.location == "Remote, PL"


def test_city_location_has_hybrid_and_onsite():
    jobs = _parse(SAMPLE_HTML)
    city = [j for j in jobs if "remote" not in j.location.lower() and j.location]
    assert city, "sample has a city listing"
    for j in city:
        assert "hybrid" in j.location and "onsite" in j.location


def test_seniority_extracted_from_title_when_present():
    first = _parse(SAMPLE_HTML)[0]  # "Senior UX/UI Designer"
    assert first.seniority == "senior"


def test_ids_stable_and_unique():
    ids_a = [j.id for j in _parse(SAMPLE_HTML)]
    ids_b = [j.id for j in _parse(SAMPLE_HTML)]
    assert ids_a == ids_b
    assert len(ids_a) == len(set(ids_a))


def test_url_query_string_stripped():
    first = _parse(SAMPLE_HTML)[0]
    assert "?" not in first.url


def test_duplicate_cards_deduped():
    jobs = _parse(SAMPLE_HTML + SAMPLE_HTML)
    assert len(jobs) == 2


def test_parse_skips_card_without_id_or_title():
    no_id = (
        '<div class="base-card">'
        '<h3 class="base-search-card__title">No URN No Link</h3></div>'
    )
    no_title = (
        '<div class="base-card" data-entity-urn="urn:li:jobPosting:1">'
        '<a class="base-card__full-link" href="https://www.linkedin.com/jobs/view/x-1"></a>'
        "</div>"
    )
    assert _parse(no_id) == []
    assert _parse(no_title) == []


def test_parse_handles_empty_html():
    assert _parse("") == []
    assert _parse("<html><body></body></html>") == []


def test_fetch_is_callable():
    assert callable(fetch)
```

- [ ] **Step 2: Run tests to verify they pass (parser already satisfies them)**

Run: `pytest tests/test_linkedin.py -v`
Expected: PASS for all. (These tests exercise behavior already implemented in Task 1; if any fail, fix `scrapers/linkedin.py` minimally until green — do not change the tests.)

- [ ] **Step 3: Commit**

```bash
git add tests/test_linkedin.py scrapers/linkedin.py
git commit -m "test(linkedin): cover location convention, dedup, malformed input"
```

---

## Task 3: Register the scraper in the pipeline

**Files:**
- Modify: `scrapers/__init__.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_linkedin.py`:

```python
def test_registered_in_scrapers():
    from scrapers import SCRAPERS
    from scrapers import linkedin

    assert linkedin.fetch in SCRAPERS
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_linkedin.py::test_registered_in_scrapers -v`
Expected: FAIL — `linkedin.fetch` not in `SCRAPERS`.

- [ ] **Step 3: Register the scraper**

Edit `scrapers/__init__.py`. Change the import line:

```python
from . import bulldogjob, justjoin, linkedin, nofluffjobs, pracuj, theprotocol
```

And add `linkedin.fetch` to the `SCRAPERS` list:

```python
SCRAPERS: list[Callable[[], list[Job]]] = [
    justjoin.fetch,
    nofluffjobs.fetch,
    bulldogjob.fetch,
    theprotocol.fetch,
    pracuj.fetch,
    linkedin.fetch,
]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_linkedin.py::test_registered_in_scrapers -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scrapers/__init__.py tests/test_linkedin.py
git commit -m "feat(linkedin): register scraper in the pipeline"
```

---

## Task 4: Add fixture-capture support and capture a real fixture

**Files:**
- Modify: `scripts/capture_fixtures.py`
- Create: `tests/fixtures/linkedin_guest.html`

- [ ] **Step 1: Add the capture function**

In `scripts/capture_fixtures.py`, add this function after `capture_pracuj()`:

```python
def capture_linkedin() -> None:
    """LinkedIn TLS-fingerprints clients; use Chrome impersonation. The guest
    endpoint returns an HTML fragment of ~10 job cards with no login."""
    from curl_cffi import requests as cffi

    url = (
        "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
        "?keywords=UX%2FUI%20designer&location=Poland&start=0"
    )
    print(f"GET {url}", file=sys.stderr)
    r = cffi.get(url, impersonate="chrome120", timeout=20)
    r.raise_for_status()
    out = FIXTURES / "linkedin_guest.html"
    FIXTURES.mkdir(parents=True, exist_ok=True)
    out.write_text(r.text, encoding="utf-8")
    print(f"wrote {out} ({len(r.text)} bytes)", file=sys.stderr)
```

And add it to the `CAPTURES` dict:

```python
CAPTURES = {
    "justjoin": capture_justjoin,
    "nofluffjobs": capture_nofluffjobs,
    "bulldogjob": capture_bulldogjob,
    "theprotocol": capture_theprotocol,
    "pracuj": capture_pracuj,
    "linkedin": capture_linkedin,
}
```

- [ ] **Step 2: Capture the fixture from the live site**

Run: `python scripts/capture_fixtures.py linkedin`
Expected: writes `tests/fixtures/linkedin_guest.html`.

**If the capture is blocked** (HTTP error / `429` / `999` — likely from a datacenter IP, possible from home): hand-build `tests/fixtures/linkedin_guest.html` by wrapping at least two copies of the reference card structure (top of this plan, with distinct `urn:li:jobPosting` ids and titles) in `<ul>...</ul>`. Verify the real selectors against the live DOM (open the search URL in a browser, inspect a card) before relying on the captured markup; adjust `scrapers/linkedin.py` selectors if LinkedIn's class names have changed since this plan was written.

- [ ] **Step 3: Add a fixture-shape test**

Append to `tests/test_linkedin.py`:

```python
from pathlib import Path

import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "linkedin_guest.html"


@pytest.fixture
def fixture_html() -> str:
    if not FIXTURE.exists():
        pytest.skip("linkedin_guest.html fixture not captured")
    return FIXTURE.read_text(encoding="utf-8")


def test_fixture_parses_to_jobs(fixture_html):
    jobs = _parse(fixture_html)
    assert len(jobs) >= 1
    for j in jobs:
        assert j.source == "linkedin.com"
        assert j.id.startswith("linkedin.com:")
        assert j.title
        assert j.url.startswith("https://www.linkedin.com/jobs/view/")
```

Move the `from pathlib import Path` / `import pytest` imports to the top of the
file with the other imports if your linter prefers (ruff `I` will flag it; see
Task 5).

- [ ] **Step 4: Run the test**

Run: `pytest tests/test_linkedin.py::test_fixture_parses_to_jobs -v`
Expected: PASS (or SKIP if the fixture could not be captured — acceptable for commit, but prefer a real fixture).

- [ ] **Step 5: Commit**

```bash
git add scripts/capture_fixtures.py tests/fixtures/linkedin_guest.html tests/test_linkedin.py
git commit -m "feat(linkedin): fixture capture support + saved fixture"
```

---

## Task 5: Full verification (suite + lint)

**Files:** none (verification only)

- [ ] **Step 1: Run the full test suite**

Run: `pytest`
Expected: all tests pass (existing + new LinkedIn tests).

- [ ] **Step 2: Lint and format checks**

Run: `ruff check .`
Expected: no errors. Fix any import-ordering (`I`) or other findings in `scrapers/linkedin.py`, `tests/test_linkedin.py`, `scripts/capture_fixtures.py`.

Run: `ruff format --check .`
Expected: no reformatting needed. If it reports files, run `ruff format .` and re-run the check.

- [ ] **Step 3: Commit any lint/format fixes**

```bash
git add -A
git commit -m "style(linkedin): satisfy ruff lint/format"
```

(Skip this commit if Steps 1–2 were already clean.)

---

## Out of scope (per spec)

- Salary extraction (guest cards lack it — always `None`).
- Proxy / IP rotation.
- Pagination beyond the first page (~10 cards).
- A README update (the source list in `README.md` mentions five boards; updating
  it is optional polish, not required by this plan — add `linkedin.com` to the
  parenthetical in `README.md:3` if desired).
