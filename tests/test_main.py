"""End-to-end tests for the orchestrator's subscription + cap logic, with a
fake send_func so we don't hit Telegram."""

import json
from datetime import datetime
from pathlib import Path

from config import load_config
from main import _collect_matches_for_user, _run_with_subscriptions
from models import Job, Profile

ROOT = Path(__file__).resolve().parent.parent


def _job(id_: str, title: str = "UX Designer") -> Job:
    return Job(
        id=id_,
        source="src",
        title=title,
        company="Acme",
        location="Kraków, hybrid",
        seniority="mid",
        salary=None,
        url=f"https://example.com/{id_}",
        posted_at=datetime(2026, 1, 1),
    )


def _real_cfg():
    return load_config(ROOT / "config.toml")


# ---------- _collect_matches_for_user ----------


def test_collect_matches_skips_already_seen():
    cfg = _real_cfg()
    profile = Profile(name="p", keywords=["UX Designer"])
    jobs = [_job(f"src:{i}") for i in range(3)]
    existing = ["src:1"]
    matches = _collect_matches_for_user([profile], jobs, cfg, existing)
    ids = [j.id for j, _ in matches]
    assert ids == ["src:0", "src:2"]


def test_collect_matches_picks_first_matching_profile():
    cfg = _real_cfg()
    profiles = [
        Profile(name="qa", keywords=["QA Automation"]),
        Profile(name="ui-ux", keywords=["UX Designer"]),
    ]
    jobs = [_job("src:1", title="UX Designer")]
    matches = _collect_matches_for_user(profiles, jobs, cfg, [])
    assert len(matches) == 1
    assert matches[0][1].name == "ui-ux"


def test_collect_matches_dedups_within_run():
    cfg = _real_cfg()
    profile = Profile(name="p", keywords=["UX Designer"])
    same_id = _job("src:1")
    matches = _collect_matches_for_user([profile], [same_id, same_id], cfg, [])
    assert len(matches) == 1


# ---------- _run_with_subscriptions: per-user cap ----------


def _write_subs(state_dir: Path, profiles_by_chat: dict[str, list[Profile]]) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    raw = {
        chat_id: {"profiles": [{"name": p.name, "keywords": list(p.keywords)} for p in profs]}
        for chat_id, profs in profiles_by_chat.items()
    }
    (state_dir / "subscriptions.json").write_text(json.dumps(raw), encoding="utf-8")


def test_per_user_cap_marks_excess_as_seen(tmp_path: Path):
    state_dir = tmp_path / "state"
    _write_subs(state_dir, {"1": [Profile(name="p", keywords=["UX Designer"])]})

    jobs = [_job(f"src:{i}") for i in range(5)]
    sent: list[tuple[str, str]] = []

    rc = _run_with_subscriptions(
        jobs,
        _real_cfg(),
        state_dir,
        max_per_user=2,
        send=lambda cid, job, profile: sent.append((cid, job.id)) or True,
    )
    assert rc == 0

    # Cap honoured: only 2 sends attempted.
    assert sent == [("1", "src:0"), ("1", "src:1")]

    # All 5 matches in seen-set, even the 3 beyond the cap.
    seen = json.loads((state_dir / "seen_jobs.json").read_text(encoding="utf-8"))
    assert seen["1"] == [f"src:{i}" for i in range(5)]


def test_send_failure_still_marks_seen(tmp_path: Path):
    state_dir = tmp_path / "state"
    _write_subs(state_dir, {"1": [Profile(name="p", keywords=["UX Designer"])]})

    jobs = [_job(f"src:{i}") for i in range(3)]
    rc = _run_with_subscriptions(
        jobs,
        _real_cfg(),
        state_dir,
        max_per_user=10,
        send=lambda cid, job, profile: False,  # everything fails
    )
    assert rc == 0
    seen = json.loads((state_dir / "seen_jobs.json").read_text(encoding="utf-8"))
    assert seen["1"] == ["src:0", "src:1", "src:2"]


def test_no_subscriptions_returns_early(tmp_path: Path):
    state_dir = tmp_path / "state"
    state_dir.mkdir()

    sent: list = []
    rc = _run_with_subscriptions(
        [_job("src:1")],
        _real_cfg(),
        state_dir,
        max_per_user=10,
        send=lambda *a: sent.append(a) or True,
    )
    assert rc == 0
    assert sent == []
    assert not (state_dir / "seen_jobs.json").exists()


def test_per_user_seen_isolation(tmp_path: Path):
    state_dir = tmp_path / "state"
    profile = Profile(name="p", keywords=["UX Designer"])
    _write_subs(state_dir, {"1": [profile], "2": [profile]})

    # Pre-seed user 1 having seen src:0; user 2 hasn't seen anything.
    (state_dir / "seen_jobs.json").write_text(json.dumps({"1": ["src:0"]}), encoding="utf-8")

    jobs = [_job("src:0"), _job("src:1")]
    sent: list[tuple[str, str]] = []
    _run_with_subscriptions(
        jobs,
        _real_cfg(),
        state_dir,
        max_per_user=10,
        send=lambda cid, job, profile: sent.append((cid, job.id)) or True,
    )

    # User 1: only src:1 (src:0 seen). User 2: both.
    assert sorted(sent) == [("1", "src:1"), ("2", "src:0"), ("2", "src:1")]
