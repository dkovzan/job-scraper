# LinkedIn scraper — design

**Date:** 2026-05-30
**Status:** approved, pre-implementation

## Goal

Add a sixth job source — LinkedIn — to the scraper, surfacing UX/UI designer
postings in Poland. It must plug into the existing `fetch() -> list[Job]`
contract with no changes to the orchestrator, filters, or delivery path.

## Constraints & known risks

- **Datacenter-IP blocking.** LinkedIn aggressively rate-limits / blocks
  datacenter IPs and may return `429` or its `999` status. The production
  scraper runs on GitHub Actions runners (datacenter IPs), so it may return
  `0` jobs in CI while working from a residential IP. This is accepted: the
  scraper degrades to an empty list, which `_scrape_all` in `main.py` handles
  by logging and continuing. **Best-effort by design.**
- **No auth.** We use only the public, unauthenticated guest jobs endpoint.
  No cookies, no `li_at` secret.
- **ToS.** This is best-effort scraping of public listings, consistent with
  how the other five sources are scraped.

## Approach (chosen)

LinkedIn's public job-search page calls a guest endpoint that returns a clean
HTML fragment of job cards without login:

```
https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search
    ?keywords=UX%2FUI%20designer&location=Poland&start=0
```

LinkedIn TLS-fingerprints clients, so the transport is `curl_cffi` with Chrome
impersonation — identical to the existing `scrapers/theprotocol.py` pattern,
rather than plain `httpx`.

Alternatives rejected:
- **Authenticated scrape (`li_at` cookie):** more data but fragile, ToS-risky,
  needs a secret. Overkill.
- **Scrape the full `/jobs/search` SPA HTML:** heavier and JS-rendered; the
  guest API is what that page calls internally. Strictly worse.

## Component: `scrapers/linkedin.py`

Single module exposing `fetch() -> list[Job]`, mirroring the other scrapers.

- **`fetch()`** — `curl_cffi.requests.get(_SEARCH_URL, impersonate="chrome120",
  timeout=20)`. On `RequestsError`, non-200 status (notably `429` / `999`), or
  empty body: log a warning and return `[]`. Otherwise hand the HTML to
  `_parse`.
- **`_parse(html)`** — `selectolax` over the fragment; iterate the job cards
  (`li > div.base-card`), build one `Job` per card, dedup by id, and skip
  unparseable cards via the same defensive `try/except` the other scrapers use.

### Field mapping → `Job`

| Job field   | Source |
|-------------|--------|
| `id`        | `linkedin.com:<id>` — from `data-entity-urn="urn:li:jobPosting:<id>"`; fallback to the id parsed out of the offer URL |
| `source`    | `"linkedin.com"` |
| `title`     | `.base-search-card__title` text |
| `company`   | `.base-search-card__subtitle` text (fallback `"—"`) |
| `location`  | `.job-search-card__location` text, normalized to the PL convention below |
| `seniority` | regex-extracted from the title (same approach as `nofluffjobs.py`) |
| `salary`    | `None` — guest cards effectively never carry salary |
| `url`       | `a.base-card__full-link` href, query string stripped |
| `posted_at` | `time[datetime]` attribute, parsed; `None` if absent |

### Location normalization (PL convention)

Matches the other Polish-board scrapers so existing `defaults.locations`
clauses match:
- location text contains "remote" → `"Remote, PL"`
- otherwise → `"<city>, hybrid, onsite"` (no explicit work-mode on guest cards,
  so emit both so onsite/hybrid defaults can match)

## Wiring

- Add `linkedin.fetch` to `SCRAPERS` in `scrapers/__init__.py` (one line, plus
  the module import).

## Tests

- `tests/fixtures/linkedin_guest.html` — a saved guest-API fragment.
- `tests/test_linkedin.py` — mirrors `tests/test_nofluffjobs.py`:
  - fixture present / has expected shape
  - `_parse` returns `Job`s with correct `source`, `id` prefix, non-empty
    title/company, LinkedIn offer URL
  - ids stable across runs and unique
  - remote listings tagged with `PL`; city listings carry `hybrid` + `onsite`
  - seniority, when present, appears in the title
  - `_parse` handles empty and malformed HTML
  - `fetch` is callable (live network deferred to the integration smoke step)
- Add a LinkedIn entry to `scripts/capture_fixtures.py` to refresh the fixture.

## Out of scope

- Salary extraction (guest cards lack it — always `None`).
- Proxy support / IP rotation (may revisit if CI blocking proves total).
- Pagination beyond the first page (~10 cards); `seen_jobs` dedup + twice-daily
  cron makes one page sufficient.
