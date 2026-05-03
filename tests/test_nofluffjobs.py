from pathlib import Path

import pytest

from models import Job
from scrapers.nofluffjobs import _parse, fetch

FIXTURE = Path(__file__).parent / "fixtures" / "nofluffjobs_design.html"


@pytest.fixture
def html() -> str:
    return FIXTURE.read_text(encoding="utf-8")


def test_fixture_present_and_html_shape(html):
    assert "/pl/job/" in html
    assert len(html) > 100_000  # NFJ landing pages are ~750 KB


def test_parse_returns_jobs(html):
    jobs = _parse(html)
    assert len(jobs) >= 5
    for j in jobs:
        assert isinstance(j, Job)
        assert j.source == "nofluffjobs.com"
        assert j.id.startswith("nofluffjobs.com:")
        assert j.title
        assert j.company
        assert j.url.startswith("https://nofluffjobs.com/pl/job/")


def test_ids_stable_across_runs(html):
    ids_a = [j.id for j in _parse(html)]
    ids_b = [j.id for j in _parse(html)]
    assert ids_a == ids_b


def test_ids_unique(html):
    ids = [j.id for j in _parse(html)]
    assert len(ids) == len(set(ids))


def test_remote_locations_tagged_with_pl(html):
    jobs = _parse(html)
    remote = [j for j in jobs if "remote" in j.location.lower()]
    if not remote:
        pytest.skip("fixture has no remote-only listings")
    for j in remote:
        assert "PL" in j.location


def test_city_locations_have_hybrid_and_onsite(html):
    jobs = _parse(html)
    cities = [j for j in jobs if "remote" not in j.location.lower() and j.location]
    if not cities:
        pytest.skip("fixture has no city-only listings")
    for j in cities:
        assert "hybrid" in j.location and "onsite" in j.location


def test_seniority_extracted_from_title_when_present(html):
    jobs = _parse(html)
    # At least one fixture title should contain a seniority keyword.
    matched = [j for j in jobs if j.seniority is not None]
    if matched:
        for j in matched:
            assert j.seniority.lower() in j.title.lower()


def test_salary_when_present_has_currency(html):
    jobs = _parse(html)
    salaries = [j.salary for j in jobs if j.salary]
    if salaries:
        # NFJ ranges always include a currency token.
        assert any("PLN" in s or "EUR" in s or "USD" in s for s in salaries)


def test_parse_skips_malformed_cards():
    minimal = '<html><body><a href="/pl/job/no-title-card">x</a></body></html>'
    assert _parse(minimal) == []


def test_parse_handles_empty_html():
    assert _parse("") == []
    assert _parse("<html><body></body></html>") == []


def test_fetch_is_callable():
    # Just check the symbol; live network test is in the integration smoke step.
    assert callable(fetch)
