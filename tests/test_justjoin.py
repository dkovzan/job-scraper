import json
from pathlib import Path

import pytest

from models import Job
from scrapers import SCRAPERS
from scrapers.justjoin import _parse, fetch

FIXTURE = Path(__file__).parent / "fixtures" / "justjoin_listings.json"


@pytest.fixture
def payload() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_fixture_has_at_least_5_design_listings(payload):
    listings = payload["data"]
    assert len(listings) >= 5
    assert all(e["categoryId"] == 14 for e in listings)


def test_parse_returns_jobs(payload):
    jobs = _parse(payload)
    assert len(jobs) == len(payload["data"])
    for j in jobs:
        assert isinstance(j, Job)
        assert j.source == "justjoin.it"
        assert j.id.startswith("justjoin.it:")
        assert j.title
        assert j.company
        assert j.url.startswith("https://justjoin.it/job-offer/")


def test_ids_stable_across_runs(payload):
    a = [j.id for j in _parse(payload)]
    b = [j.id for j in _parse(payload)]
    assert a == b


def test_id_uses_slug(payload):
    first = payload["data"][0]
    job = _parse(payload)[0]
    assert job.id == f"justjoin.it:{first['slug']}"


def test_workplace_office_maps_to_onsite(payload):
    office_slugs = {e["slug"] for e in payload["data"] if e.get("workplaceType") == "office"}
    if not office_slugs:
        pytest.skip("fixture has no workplaceType=office entries")
    for j in _parse(payload):
        slug = j.id.split(":", 1)[1]
        if slug in office_slugs:
            assert "onsite" in j.location, f"expected 'onsite' in {j.location!r}"


def test_workplace_remote_tagged_with_pl(payload):
    remote_slugs = {e["slug"] for e in payload["data"] if e.get("workplaceType") == "remote"}
    if not remote_slugs:
        pytest.skip("fixture has no workplaceType=remote entries")
    for j in _parse(payload):
        slug = j.id.split(":", 1)[1]
        if slug in remote_slugs:
            assert "remote" in j.location.lower()
            assert "PL" in j.location


def test_seniority_populated_when_available(payload):
    jobs = _parse(payload)
    assert any(j.seniority is not None for j in jobs)


def test_posted_at_parsed_when_available(payload):
    jobs = _parse(payload)
    assert any(j.posted_at is not None for j in jobs)


def test_parse_skips_malformed_entries():
    malformed = {"data": [{"no_slug": "yes"}, None, "not-a-dict"]}
    assert _parse(malformed) == []


def test_parse_handles_empty_payload():
    assert _parse({"data": []}) == []
    assert _parse({}) == []


def test_scrapers_registry_includes_justjoin():
    assert fetch in SCRAPERS
