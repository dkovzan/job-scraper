import json
from pathlib import Path

import state
from models import Profile

# ---------- subscriptions ----------


def test_subscriptions_round_trip(tmp_path: Path):
    path = tmp_path / "subs.json"
    data = {
        "123": [Profile(name="ui-ux", keywords=["UI Designer", "UX Designer"])],
        "456": [
            Profile(name="qa", keywords=["QA Automation"]),
            Profile(name="be", keywords=["Backend"]),
        ],
    }
    state.save_subscriptions(path, data)
    assert state.load_subscriptions(path) == data


def test_subscriptions_file_format_matches_spec(tmp_path: Path):
    path = tmp_path / "subs.json"
    state.save_subscriptions(
        path,
        {"123456789": [Profile(name="ui-ux", keywords=["UI Designer", "UX Designer"])]},
    )
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw == {
        "123456789": {
            "profiles": [{"name": "ui-ux", "keywords": ["UI Designer", "UX Designer"]}],
        }
    }


def test_subscriptions_missing_file_returns_empty(tmp_path: Path):
    assert state.load_subscriptions(tmp_path / "missing.json") == {}


def test_subscriptions_skips_malformed_entries(tmp_path: Path):
    path = tmp_path / "subs.json"
    path.write_text(
        json.dumps(
            {
                "ok": {"profiles": [{"name": "p1", "keywords": ["a"]}]},
                "bad-payload": "not-a-dict",
                "no-profiles": {"other": 1},
                "bad-profile": {
                    "profiles": [
                        {"keywords": ["x"]},
                        {"name": "good", "keywords": ["b"]},
                    ]
                },
            }
        ),
        encoding="utf-8",
    )
    loaded = state.load_subscriptions(path)
    assert loaded == {
        "ok": [Profile(name="p1", keywords=["a"])],
        "no-profiles": [],
        "bad-profile": [Profile(name="good", keywords=["b"])],
    }


# ---------- seen_jobs ----------


def test_seen_jobs_round_trip(tmp_path: Path):
    path = tmp_path / "seen.json"
    data = {"123": ["src:a", "src:b", "src:c"], "456": ["src:x"]}
    state.save_seen_jobs(path, data)
    assert state.load_seen_jobs(path) == data


def test_seen_jobs_missing_file_returns_empty(tmp_path: Path):
    assert state.load_seen_jobs(tmp_path / "missing.json") == {}


def test_seen_jobs_trim_keeps_most_recent(tmp_path: Path):
    path = tmp_path / "seen.json"
    ids = [f"id{i}" for i in range(10)]
    state.save_seen_jobs(path, {"123": ids}, max_per_user=5)
    assert state.load_seen_jobs(path) == {"123": ["id5", "id6", "id7", "id8", "id9"]}


def test_seen_jobs_trim_no_op_under_limit(tmp_path: Path):
    path = tmp_path / "seen.json"
    state.save_seen_jobs(path, {"123": ["a", "b", "c"]}, max_per_user=10)
    assert state.load_seen_jobs(path) == {"123": ["a", "b", "c"]}


def test_seen_jobs_default_trim_is_5000(tmp_path: Path):
    path = tmp_path / "seen.json"
    ids = [f"id{i}" for i in range(5100)]
    state.save_seen_jobs(path, {"123": ids})
    loaded = state.load_seen_jobs(path)
    assert len(loaded["123"]) == 5000
    # last 5000 → starts at id100
    assert loaded["123"][0] == "id100"
    assert loaded["123"][-1] == "id5099"


# ---------- offset ----------


def test_offset_round_trip(tmp_path: Path):
    path = tmp_path / "offset.txt"
    state.save_offset(path, 42)
    assert state.load_offset(path) == 42


def test_offset_missing_file_returns_zero(tmp_path: Path):
    assert state.load_offset(tmp_path / "missing.txt") == 0


def test_offset_blank_file_returns_zero(tmp_path: Path):
    path = tmp_path / "offset.txt"
    path.write_text("", encoding="utf-8")
    assert state.load_offset(path) == 0


def test_offset_invalid_content_returns_zero(tmp_path: Path):
    path = tmp_path / "offset.txt"
    path.write_text("not a number", encoding="utf-8")
    assert state.load_offset(path) == 0


def test_offset_handles_trailing_newline(tmp_path: Path):
    path = tmp_path / "offset.txt"
    path.write_text("12345\n", encoding="utf-8")
    assert state.load_offset(path) == 12345


# ---------- failure_counts ----------


def test_failure_counts_round_trip(tmp_path: Path):
    path = tmp_path / "fc.json"
    data = {"justjoin.it": 0, "pracuj.pl": 2, "nofluffjobs.com": 0}
    state.save_failure_counts(path, data)
    assert state.load_failure_counts(path) == data


def test_failure_counts_missing_file_returns_empty(tmp_path: Path):
    assert state.load_failure_counts(tmp_path / "missing.json") == {}


def test_failure_counts_skips_non_int(tmp_path: Path):
    path = tmp_path / "fc.json"
    path.write_text(json.dumps({"good": 3, "bad": "nope", "also_bad": None}), encoding="utf-8")
    assert state.load_failure_counts(path) == {"good": 3}


# ---------- general ----------


def test_save_creates_parent_directory(tmp_path: Path):
    path = tmp_path / "deep" / "nested" / "subs.json"
    state.save_subscriptions(path, {"1": [Profile(name="x", keywords=["X"])]})
    assert path.exists()


def test_corrupt_json_treated_as_empty(tmp_path: Path):
    p = tmp_path / "subs.json"
    p.write_text("not valid json {{{", encoding="utf-8")
    assert state.load_subscriptions(p) == {}
    assert state.load_seen_jobs(p) == {}
    assert state.load_failure_counts(p) == {}
