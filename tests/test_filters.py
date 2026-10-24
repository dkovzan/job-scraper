from datetime import datetime

import pytest

from config import DefaultsConfig, LocationClause
from filters import match_job
from models import Job, Profile


@pytest.fixture
def defaults() -> DefaultsConfig:
    return DefaultsConfig(
        locations=(
            LocationClause(city="Kraków", country=None, modes=("onsite", "hybrid", "remote")),
            LocationClause(city=None, country="PL", modes=("remote",)),
        ),
    )


@pytest.fixture
def ui_ux() -> Profile:
    return Profile(
        name="ui-ux",
        keywords=["UI Designer", "UX Designer", "UI/UX", "Product Designer", "Projektant UX"],
    )


def _job(
    *,
    id_: str = "src:1",
    title: str = "UX Designer",
    location: str = "Kraków, hybrid",
    seniority: str | None = "mid",
) -> Job:
    return Job(
        id=id_,
        source="src",
        title=title,
        company="Acme",
        location=location,
        seniority=seniority,
        salary=None,
        url="https://example.com/1",
        posted_at=datetime(2026, 1, 1),
    )


# ---------- keyword ----------


def test_keyword_positive(ui_ux: Profile, defaults: DefaultsConfig):
    assert match_job(_job(title="UX Designer", seniority=None), ui_ux, defaults)


def test_keyword_negative(ui_ux: Profile, defaults: DefaultsConfig):
    assert not match_job(_job(title="Backend Engineer"), ui_ux, defaults)


def test_keyword_case_insensitive(ui_ux: Profile, defaults: DefaultsConfig):
    assert match_job(_job(title="ui designer"), ui_ux, defaults)


def test_keyword_diacritics_insensitive(defaults: DefaultsConfig):
    profile = Profile(name="p", keywords=["Projektant interfejsów"])
    assert match_job(_job(title="Projektant interfejsow w aplikacji"), profile, defaults)
    profile2 = Profile(name="p", keywords=["Krakow"])
    assert match_job(
        _job(title="Designer Kraków team", location="Kraków, hybrid"), profile2, defaults
    )


def test_empty_profile_keywords_rejects_everything(defaults: DefaultsConfig):
    profile = Profile(name="empty", keywords=[])
    assert not match_job(_job(), profile, defaults)


# ---------- seniority ----------


def test_seniority_missing_kept(ui_ux: Profile, defaults: DefaultsConfig):
    assert match_job(_job(seniority=None), ui_ux, defaults)


def test_unknown_seniority_is_kept_for_selected_level(defaults: DefaultsConfig):
    junior_only = Profile(name="ui-ux", keywords=["UX Designer"], seniority=("junior",))
    assert match_job(_job(seniority=None), junior_only, defaults)


def test_default_profile_accepts_all_levels(ui_ux: Profile, defaults: DefaultsConfig):
    assert match_job(_job(seniority="junior"), ui_ux, defaults)
    assert match_job(_job(seniority="mid"), ui_ux, defaults)
    assert match_job(_job(seniority="Senior"), ui_ux, defaults)


@pytest.mark.parametrize(
    ("level", "seniority", "title"),
    [
        ("junior", "junior", "UX Designer"),
        ("junior", None, "Młodszy UX Designer"),
        ("middle", "mid", "UX Designer"),
        ("middle", "regular", "UX Designer"),
        ("senior", "Senior", "UX Designer"),
        ("senior", None, "Lead UX Designer"),
        ("senior", None, "Starszy UX Designer"),
    ],
)
def test_profile_seniority_selection_filters_recognized_levels(
    defaults: DefaultsConfig, level: str, seniority: str | None, title: str
):
    profile = Profile(name="ui-ux", keywords=["UX Designer"], seniority=(level,))
    assert match_job(_job(seniority=seniority, title=title), profile, defaults)
    other_level = next(item for item in ("junior", "middle", "senior") if item != level)
    other_profile = Profile(name="ui-ux", keywords=["UX Designer"], seniority=(other_level,))
    assert not match_job(_job(seniority=seniority, title=title), other_profile, defaults)


# ---------- seniority labels in titles ----------


def test_seniority_senior_in_title_kept_by_default(
    ui_ux: Profile, defaults: DefaultsConfig
):
    """Title-only level labels are classified when a board omits the field."""
    assert match_job(
        _job(title="Senior UX Designer", seniority=None), ui_ux, defaults
    )


# ---------- location ----------


def test_location_city_match(ui_ux: Profile, defaults: DefaultsConfig):
    assert match_job(_job(location="Kraków, hybrid"), ui_ux, defaults)


def test_location_city_diacritic_insensitive(ui_ux: Profile, defaults: DefaultsConfig):
    assert match_job(_job(location="Krakow, hybrid"), ui_ux, defaults)


def test_location_city_wrong_mode_rejected(ui_ux: Profile):
    only_hybrid = DefaultsConfig(
        locations=(LocationClause(city="Kraków", country=None, modes=("hybrid",)),),
    )
    assert not match_job(_job(location="Kraków, onsite"), ui_ux, only_hybrid)


def test_location_country_remote_match(ui_ux: Profile, defaults: DefaultsConfig):
    assert match_job(_job(location="Remote (PL)"), ui_ux, defaults)


def test_location_country_code_word_bounded(ui_ux: Profile, defaults: DefaultsConfig):
    # 'PL' must not be matched as a substring inside 'Pleszew'.
    assert not match_job(_job(location="Pleszew, onsite"), ui_ux, defaults)


def test_location_other_city_rejected(ui_ux: Profile, defaults: DefaultsConfig):
    assert not match_job(_job(location="Berlin, onsite"), ui_ux, defaults)


def test_location_no_clauses_kept(ui_ux: Profile):
    no_loc = DefaultsConfig(locations=())
    assert match_job(_job(seniority="junior"), ui_ux, no_loc)


# ---------- combined ----------


def test_match_requires_all_three_filters(ui_ux: Profile, defaults: DefaultsConfig):
    junior_only = Profile(name=ui_ux.name, keywords=ui_ux.keywords, seniority=("junior",))
    # Right keyword, wrong seniority.
    assert not match_job(
        _job(title="UX Designer", seniority="Senior", location="Kraków, hybrid"),
        junior_only,
        defaults,
    )
    # Right keyword + seniority, wrong location.
    assert not match_job(
        _job(title="UX Designer", seniority="mid", location="Berlin, onsite"),
        ui_ux,
        defaults,
    )
    # All three OK.
    assert match_job(
        _job(title="UX Designer", seniority="junior", location="Kraków, hybrid"),
        junior_only,
        defaults,
    )
