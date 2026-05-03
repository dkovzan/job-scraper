from pathlib import Path

import pytest

from config import load_config

ROOT = Path(__file__).resolve().parent.parent


def test_loads_real_config_toml():
    cfg = load_config(ROOT / "config.toml")

    assert cfg.telegram.bot_token_env == "TELEGRAM_BOT_TOKEN"
    assert cfg.telegram.allowed_chats_env == "ALLOWED_CHAT_IDS"

    assert cfg.state.seen_file == "seen_jobs.json"
    assert cfg.state.subscriptions_file == "subscriptions.json"
    assert cfg.state.offset_file == "tg_offset.txt"
    assert cfg.state.max_seen_ids == 5000

    assert "junior" in cfg.defaults.seniority
    assert "mid" in cfg.defaults.seniority

    krakow = next((loc for loc in cfg.defaults.locations if loc.city == "Kraków"), None)
    assert krakow is not None
    assert "hybrid" in krakow.modes

    pl_remote = next((loc for loc in cfg.defaults.locations if loc.country == "PL"), None)
    assert pl_remote is not None
    assert pl_remote.modes == ("remote",)


def test_missing_telegram_section_raises(tmp_path: Path):
    p = tmp_path / "c.toml"
    p.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match=r"missing section \[telegram\]"):
        load_config(p)


def test_missing_telegram_key_raises(tmp_path: Path):
    p = tmp_path / "c.toml"
    p.write_text(
        '[telegram]\nbot_token_env = "X"\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match=r"missing key 'allowed_chats_env' in \[telegram\]"):
        load_config(p)


def test_missing_state_section_raises(tmp_path: Path):
    p = tmp_path / "c.toml"
    p.write_text(
        '[telegram]\nbot_token_env = "X"\nallowed_chats_env = "Y"\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match=r"missing section \[state\]"):
        load_config(p)


def test_location_clause_requires_city_or_country(tmp_path: Path):
    p = tmp_path / "c.toml"
    p.write_text(
        "[telegram]\n"
        'bot_token_env = "X"\n'
        'allowed_chats_env = "Y"\n'
        "[state]\n"
        'seen_file = "s"\n'
        'subscriptions_file = "u"\n'
        'offset_file = "o"\n'
        "max_seen_ids = 10\n"
        "[defaults]\n"
        'seniority = ["junior"]\n'
        'locations = [ { modes = ["remote"] } ]\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match=r"locations\[0\] must define 'city' or 'country'"):
        load_config(p)


def test_missing_file_raises(tmp_path: Path):
    p = tmp_path / "does_not_exist.toml"
    with pytest.raises(FileNotFoundError, match="file not found"):
        load_config(p)
