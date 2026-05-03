from pathlib import Path
from types import SimpleNamespace

import pytest

from models import Job
from scrapers.theprotocol import _is_cf_challenge, _parse, fetch

FIXTURE = Path(__file__).parent / "fixtures" / "theprotocol_design.html"


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
        assert j.source == "theprotocol.it"
        assert j.id.startswith("theprotocol.it:")
        assert j.title
        assert j.company
        assert j.url.startswith("https://theprotocol.it/szczegoly/")


def test_ids_stable_across_runs(html):
    a = [j.id for j in _parse(html)]
    b = [j.id for j in _parse(html)]
    assert a == b


def test_ids_unique(html):
    ids = [j.id for j in _parse(html)]
    assert len(ids) == len(set(ids))


def test_seniority_extracted_from_position_levels(html):
    jobs = _parse(html)
    seniorities = {j.seniority for j in jobs if j.seniority}
    assert seniorities, "expected some offers to expose seniority"
    # theprotocol uses lowercase enum values; sanity-check they're short
    # alphabetic tokens (the filter handles whatever shows up).
    for s in seniorities:
        assert s.isalpha() and 3 <= len(s) <= 12


def test_remote_listings_tagged_with_pl(html):
    jobs = _parse(html)
    remote = [j for j in jobs if "remote" in j.location.lower()]
    if not remote:
        pytest.skip("fixture has no fully-remote listings")
    for j in remote:
        assert "PL" in j.location


def test_city_listings_have_mode_token(html):
    jobs = _parse(html)
    cities = [j for j in jobs if j.location and "remote" not in j.location.lower()]
    if not cities:
        pytest.skip("fixture has no city-only listings")
    for j in cities:
        loc = j.location.lower()
        assert "onsite" in loc or "hybrid" in loc, f"no mode in {j.location!r}"


def test_posted_at_parsed_when_available(html):
    jobs = _parse(html)
    assert any(j.posted_at is not None for j in jobs)


def test_parse_handles_empty_html():
    assert _parse("") == []
    assert _parse("<html></html>") == []


def test_parse_handles_malformed_json():
    minimal = (
        "<html><body>"
        '<script id="__NEXT_DATA__" type="application/json">not json</script>'
        "</body></html>"
    )
    assert _parse(minimal) == []


def test_parse_handles_no_offers_in_blob():
    minimal = (
        "<html><body>"
        '<script id="__NEXT_DATA__" type="application/json">'
        '{"props":{"pageProps":{}}}'
        "</script></body></html>"
    )
    assert _parse(minimal) == []


# ---------- CF challenge detection ----------


def _resp(status: int, headers: dict | None = None, text: str = "") -> SimpleNamespace:
    return SimpleNamespace(status_code=status, headers=headers or {}, text=text)


def test_cf_challenge_detected_via_header():
    assert _is_cf_challenge(_resp(403, {"cf-mitigated": "challenge"}, "x"))


def test_cf_challenge_detected_via_body():
    assert _is_cf_challenge(_resp(403, {}, "<html>Just a moment...</html>"))


def test_cf_challenge_not_triggered_on_200():
    assert not _is_cf_challenge(_resp(200, {}, "<html>data</html>"))


def test_fetch_is_callable():
    assert callable(fetch)
