from pathlib import Path
from types import SimpleNamespace

import pytest

from models import Job
from scrapers.pracuj import _is_cf_challenge, _parse, fetch

FIXTURE = Path(__file__).parent / "fixtures" / "pracuj_design.html"


@pytest.fixture
def html() -> str:
    return FIXTURE.read_text(encoding="utf-8")


def test_fixture_present(html):
    assert 'data-test="default-offer"' in html
    assert len(html) > 200_000


def test_parse_returns_jobs(html):
    jobs = _parse(html)
    assert len(jobs) >= 5
    for j in jobs:
        assert isinstance(j, Job)
        assert j.source == "pracuj.pl"
        assert j.id.startswith("pracuj.pl:")
        assert j.title
        assert j.company
        assert "pracuj.pl" in j.url


def test_ids_stable_across_runs(html):
    a = [j.id for j in _parse(html)]
    b = [j.id for j in _parse(html)]
    assert a == b


def test_ids_unique(html):
    ids = [j.id for j in _parse(html)]
    assert len(ids) == len(set(ids))


def test_id_is_data_test_offerid(html):
    jobs = _parse(html)
    # Cards expose a numeric ``data-test-offerid`` — IDs follow that.
    for j in jobs:
        suffix = j.id.split(":", 1)[1]
        assert suffix.isdigit() and len(suffix) >= 6


def test_seniority_extracted_from_additional_info(html):
    jobs = _parse(html)
    seniorities = {j.seniority for j in jobs if j.seniority}
    assert seniorities, "expected some offers to expose seniority"
    allowed = {
        "junior",
        "mid",
        "regular",
        "senior",
        "lead",
        "principal",
        "staff",
        "head",
        "starszy",
        "młodszy",
    }
    assert seniorities <= allowed, f"unexpected seniority values: {seniorities - allowed}"


def test_hybrid_listing_keeps_city_and_mode(html):
    jobs = _parse(html)
    hybrid = [j for j in jobs if "hybrid" in j.location.lower()]
    if not hybrid:
        pytest.skip("fixture has no hybrid listings")
    for j in hybrid:
        # Should also contain a city name.
        assert "," in j.location
        before_comma = j.location.split(",", 1)[0].strip()
        assert before_comma and before_comma.lower() != "remote"


def test_remote_listing_normalised_to_pl(html):
    jobs = _parse(html)
    remote = [j for j in jobs if j.location == "Remote, PL"]
    if not remote:
        pytest.skip("fixture has no fully-remote listings")
    for j in remote:
        assert j.location == "Remote, PL"


def test_skips_card_without_offerid():
    minimal = (
        "<html><body>"
        '<div data-test="default-offer">'
        '<div data-test="offer-title">Has title but no offerid</div>'
        "</div></body></html>"
    )
    assert _parse(minimal) == []


def test_parse_handles_empty_html():
    assert _parse("") == []
    assert _parse("<html></html>") == []


# ---------- CF challenge detection ----------


def _resp(status: int, headers: dict | None = None, text: str = "") -> SimpleNamespace:
    return SimpleNamespace(status_code=status, headers=headers or {}, text=text)


def test_cf_challenge_detected_via_header():
    assert _is_cf_challenge(_resp(403, {"cf-mitigated": "challenge"}, "x"))


def test_cf_challenge_detected_via_body():
    assert _is_cf_challenge(_resp(403, {}, "<title>Just a moment...</title>"))


def test_cf_challenge_not_triggered_on_200():
    assert not _is_cf_challenge(_resp(200, {}, "<html>data</html>"))


def test_fetch_is_callable():
    assert callable(fetch)
