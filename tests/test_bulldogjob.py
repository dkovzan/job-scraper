from pathlib import Path

import pytest

from models import Job
from scrapers.bulldogjob import _parse, fetch

FIXTURE = Path(__file__).parent / "fixtures" / "bulldogjob_design.html"


@pytest.fixture
def html() -> str:
    return FIXTURE.read_text(encoding="utf-8")


def test_fixture_present(html):
    assert "__NEXT_DATA__" in html
    assert len(html) > 100_000


def test_parse_returns_jobs(html):
    jobs = _parse(html)
    assert len(jobs) >= 5
    for j in jobs:
        assert isinstance(j, Job)
        assert j.source == "bulldogjob.pl"
        assert j.id.startswith("bulldogjob.pl:")
        assert j.title
        assert j.company
        assert j.url.startswith("https://bulldogjob.pl/companies/jobs/")


def test_ids_stable_across_runs(html):
    a = [j.id for j in _parse(html)]
    b = [j.id for j in _parse(html)]
    assert a == b


def test_ids_unique(html):
    ids = [j.id for j in _parse(html)]
    assert len(ids) == len(set(ids))


def test_seniority_propagated_when_present(html):
    jobs = _parse(html)
    # Bulldogjob always populates experienceLevel.
    assert any(j.seniority is not None for j in jobs)


def test_remote_listings_tagged_with_pl(html):
    jobs = _parse(html)
    remote = [j for j in jobs if "remote" in j.location.lower()]
    if not remote:
        pytest.skip("fixture has no remote listings")
    for j in remote:
        assert "PL" in j.location


def test_city_listings_have_hybrid_and_onsite(html):
    jobs = _parse(html)
    cities = [j for j in jobs if j.location and "remote" not in j.location.lower()]
    if not cities:
        pytest.skip("fixture has no city-only listings")
    for j in cities:
        assert "hybrid" in j.location and "onsite" in j.location


def test_parse_handles_missing_next_data():
    assert _parse("<html><body>no next data here</body></html>") == []


def test_parse_handles_empty_jobs():
    minimal = (
        "<html><body>"
        '<script id="__NEXT_DATA__" type="application/json">'
        '{"props":{"pageProps":{"jobs":[]}}}'
        "</script></body></html>"
    )
    assert _parse(minimal) == []


def test_parse_handles_malformed_json():
    minimal = (
        "<html><body>"
        '<script id="__NEXT_DATA__" type="application/json">not json {</script>'
        "</body></html>"
    )
    assert _parse(minimal) == []


def test_parse_skips_entries_missing_id_or_title():
    minimal = (
        "<html><body>"
        '<script id="__NEXT_DATA__" type="application/json">'
        '{"props":{"pageProps":{"jobs":['
        '{"id":"1","position":""},'
        '{"position":"only title"},'
        '{"id":"3-good","position":"OK Job","company":{"name":"Acme"}}'
        "]}}}"
        "</script></body></html>"
    )
    jobs = _parse(minimal)
    assert len(jobs) == 1
    assert jobs[0].id == "bulldogjob.pl:3-good"


def test_fetch_is_callable():
    assert callable(fetch)
