from datetime import datetime

from models import Job, Profile


def _make_job(id_: str = "src:1", title: str = "UX Designer") -> Job:
    return Job(
        id=id_,
        source="src",
        title=title,
        company="Acme",
        location="Kraków, hybrid",
        seniority="mid",
        salary=None,
        url="https://example.com/1",
        posted_at=datetime(2026, 1, 1),
    )


def test_job_equality_uses_id_only():
    a = _make_job("src:1", title="Title A")
    b = _make_job("src:1", title="Title B")
    c = _make_job("src:2", title="Title A")
    assert a == b
    assert a != c


def test_job_hash_uses_id_only():
    a = _make_job("src:1", title="Title A")
    b = _make_job("src:1", title="Title B")
    assert hash(a) == hash(b)


def test_job_set_dedups_by_id():
    a = _make_job("src:1", title="Title A")
    b = _make_job("src:1", title="Title B")
    c = _make_job("src:2", title="Title A")
    assert {a, b, c} == {a, c}


def test_job_is_frozen():
    job = _make_job()
    try:
        job.title = "mutated"  # type: ignore[misc]
    except Exception:
        return
    raise AssertionError("Job should be immutable (frozen=True)")


def test_profile_basic():
    p = Profile(name="ui-ux", keywords=["UX Designer", "UI Designer"])
    assert p.name == "ui-ux"
    assert "UX Designer" in p.keywords


def test_profile_default_keywords_is_empty_list():
    p = Profile(name="empty")
    assert p.keywords == []
