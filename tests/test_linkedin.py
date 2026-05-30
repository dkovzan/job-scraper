from datetime import datetime
from pathlib import Path

import pytest

from models import Job
from scrapers.linkedin import _parse, fetch

FIXTURE = Path(__file__).parent / "fixtures" / "linkedin_guest.html"

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
    assert (
        first.url == "https://www.linkedin.com/jobs/view/senior-ux-ui-designer-at-acme-3812345678"
    )
    assert first.salary is None
    assert first.posted_at == datetime(2026, 5, 28)


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
    no_id = '<div class="base-card"><h3 class="base-search-card__title">No URN No Link</h3></div>'
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


def test_registered_in_scrapers():
    from scrapers import SCRAPERS, linkedin

    assert linkedin.fetch in SCRAPERS


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
