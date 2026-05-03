"""Tests for bot.handle_command and bot.tick — handler dispatch + auth gate +
the I/O loop with mocked HTTP."""

from pathlib import Path

import pytest

import bot
import state
from bot import Command, handle_command, parse_command, tick
from config import load_config
from models import Profile

ROOT = Path(__file__).resolve().parent.parent

ALLOWED = {"1"}
NOT_ALLOWED = {"999"}


def _cfg():
    return load_config(ROOT / "config.toml")


def _cmd(name: str, args: str = "", chat_id: str = "1", update_id: int = 1) -> Command:
    return Command(name=name, args=args, chat_id=chat_id, update_id=update_id)


def _update(text: str, chat_id: int = 1, update_id: int = 100) -> dict:
    return {
        "update_id": update_id,
        "message": {
            "message_id": 1,
            "chat": {"id": chat_id, "type": "private"},
            "text": text,
            "date": 1714745200,
        },
    }


# ---------- /whoami: allowed for everyone ----------


def test_whoami_works_for_allowlisted():
    reply = handle_command(_cmd("whoami", chat_id="1"), {}, ALLOWED)
    assert "1" in reply.text and "chat ID" in reply.text


def test_whoami_works_for_non_allowlisted():
    reply = handle_command(_cmd("whoami", chat_id="999"), {}, ALLOWED)
    # Non-allowlisted gets their chat ID — that's the onboarding path.
    assert "999" in reply.text


# ---------- auth gate: non-allowlisted gets only the hint ----------


@pytest.mark.parametrize("name", ["start", "help", "list", "subscribe", "unsubscribe"])
def test_non_allowlisted_gets_chat_id_hint(name: str):
    subs: dict[str, list[Profile]] = {}
    reply = handle_command(_cmd(name, args="ui-ux UX Designer", chat_id="999"), subs, ALLOWED)
    assert "999" in reply.text
    assert "ALLOWED_CHAT_IDS" in reply.text
    # And critically — no state mutation.
    assert subs == {}


# ---------- /start, /help ----------


def test_start_allowlisted_returns_help_text():
    reply = handle_command(_cmd("start"), {}, ALLOWED)
    assert "/subscribe" in reply.text


def test_help_lists_commands():
    reply = handle_command(_cmd("help"), {}, ALLOWED)
    for cmd in ["/list", "/subscribe", "/unsubscribe", "/whoami"]:
        assert cmd in reply.text


# ---------- /list ----------


def test_list_empty_explains_subscribe():
    reply = handle_command(_cmd("list"), {}, ALLOWED)
    assert "No active profiles" in reply.text
    assert "/subscribe" in reply.text


def test_list_shows_profiles_for_this_user_only():
    subs = {
        "1": [
            Profile(name="ui-ux", keywords=["UI Designer", "UX Designer"]),
            Profile(name="qa", keywords=["QA Automation"]),
        ],
        "2": [Profile(name="leaked", keywords=["Should not show"])],
    }
    reply = handle_command(_cmd("list", chat_id="1"), subs, ALLOWED)
    assert "ui-ux" in reply.text
    assert "qa" in reply.text
    assert "Should not show" not in reply.text
    assert "leaked" not in reply.text


# ---------- /subscribe ----------


def test_subscribe_creates_new_profile():
    subs: dict[str, list[Profile]] = {}
    reply = handle_command(_cmd("subscribe", args="ui-ux UX Designer, UI Designer"), subs, ALLOWED)
    assert "Subscribed" in reply.text
    assert subs["1"] == [Profile(name="ui-ux", keywords=["UX Designer", "UI Designer"])]


def test_subscribe_replaces_existing_profile_same_name():
    subs = {"1": [Profile(name="ui-ux", keywords=["old"])]}
    reply = handle_command(_cmd("subscribe", args="ui-ux UX Designer, UI Designer"), subs, ALLOWED)
    assert "Updated" in reply.text
    assert subs["1"] == [Profile(name="ui-ux", keywords=["UX Designer", "UI Designer"])]


def test_subscribe_appends_when_name_differs():
    subs = {"1": [Profile(name="ui-ux", keywords=["UX Designer"])]}
    handle_command(_cmd("subscribe", args="qa QA Automation, SDET"), subs, ALLOWED)
    assert len(subs["1"]) == 2
    assert {p.name for p in subs["1"]} == {"ui-ux", "qa"}


def test_subscribe_no_args_returns_usage():
    subs: dict[str, list[Profile]] = {}
    reply = handle_command(_cmd("subscribe", args=""), subs, ALLOWED)
    assert "Usage" in reply.text
    assert subs == {}


def test_subscribe_name_only_no_keywords_returns_usage():
    subs: dict[str, list[Profile]] = {}
    reply = handle_command(_cmd("subscribe", args="ui-ux"), subs, ALLOWED)
    assert "Usage" in reply.text
    assert subs == {}


def test_subscribe_handles_empty_comma_segments():
    subs: dict[str, list[Profile]] = {}
    handle_command(_cmd("subscribe", args="ui-ux UX Designer , , UI Designer ,,"), subs, ALLOWED)
    assert subs["1"][0].keywords == ["UX Designer", "UI Designer"]


# ---------- /unsubscribe ----------


def test_unsubscribe_removes_profile():
    subs = {
        "1": [
            Profile(name="ui-ux", keywords=["x"]),
            Profile(name="qa", keywords=["y"]),
        ]
    }
    reply = handle_command(_cmd("unsubscribe", args="ui-ux"), subs, ALLOWED)
    assert "Removed" in reply.text
    assert [p.name for p in subs["1"]] == ["qa"]


def test_unsubscribe_unknown_profile():
    subs = {"1": [Profile(name="qa", keywords=["x"])]}
    reply = handle_command(_cmd("unsubscribe", args="ui-ux"), subs, ALLOWED)
    assert "No profile" in reply.text
    assert [p.name for p in subs["1"]] == ["qa"]


def test_unsubscribe_no_args_returns_usage():
    subs = {"1": [Profile(name="ui-ux", keywords=["x"])]}
    reply = handle_command(_cmd("unsubscribe", args=""), subs, ALLOWED)
    assert "Usage" in reply.text
    assert subs["1"]  # untouched


# ---------- unknown command ----------


def test_unknown_command_returns_help():
    reply = handle_command(_cmd("unknown"), {}, ALLOWED)
    assert "/subscribe" in reply.text


# ---------- tick: full I/O loop with mocks ----------


def test_tick_persists_subscribe_command(tmp_path: Path):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    sent: list[tuple[str, str]] = []

    rc = tick(
        state_dir=state_dir,
        cfg=_cfg(),
        allowed_chats=ALLOWED,
        fetch_updates=lambda offset: [
            _update("/subscribe ui-ux UX Designer, UI Designer", chat_id=1, update_id=100)
        ],
        send=lambda cid, text: sent.append((cid, text)) or True,
    )
    assert rc == 1
    assert sent and "Subscribed" in sent[0][1]

    subs = state.load_subscriptions(state_dir / "subscriptions.json")
    assert subs == {"1": [Profile(name="ui-ux", keywords=["UX Designer", "UI Designer"])]}


def test_tick_advances_offset_for_non_command_updates(tmp_path: Path):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    sent: list = []

    rc = tick(
        state_dir=state_dir,
        cfg=_cfg(),
        allowed_chats=ALLOWED,
        fetch_updates=lambda offset: [
            _update("hi there", chat_id=1, update_id=100),
            _update("/banana", chat_id=1, update_id=101),  # parses to "unknown"
            _update("👋", chat_id=1, update_id=102),
        ],
        send=lambda cid, text: sent.append((cid, text)) or True,
    )
    assert rc == 3
    # Offset should advance past the highest update_id we saw, even though
    # only one of the three was a recognised command.
    assert state.load_offset(state_dir / "tg_offset.txt") == 103


def test_tick_no_updates_does_nothing(tmp_path: Path):
    state_dir = tmp_path / "state"
    state_dir.mkdir()

    rc = tick(
        state_dir=state_dir,
        cfg=_cfg(),
        allowed_chats=ALLOWED,
        fetch_updates=lambda offset: [],
        send=lambda *a: True,
    )
    assert rc == 0
    assert not (state_dir / "subscriptions.json").exists()
    assert not (state_dir / "tg_offset.txt").exists()


def test_tick_uses_existing_offset(tmp_path: Path):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    state.save_offset(state_dir / "tg_offset.txt", 500)

    seen_offsets: list[int] = []
    tick(
        state_dir=state_dir,
        cfg=_cfg(),
        allowed_chats=ALLOWED,
        fetch_updates=lambda offset: seen_offsets.append(offset) or [],
        send=lambda *a: True,
    )
    assert seen_offsets == [500]


def test_tick_non_allowlisted_subscribe_does_not_mutate_state(tmp_path: Path):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    sent: list[tuple[str, str]] = []

    tick(
        state_dir=state_dir,
        cfg=_cfg(),
        allowed_chats=ALLOWED,
        fetch_updates=lambda offset: [
            _update("/subscribe ui-ux UX Designer", chat_id=999, update_id=200)
        ],
        send=lambda cid, text: sent.append((cid, text)) or True,
    )
    # Replied with the chat-ID hint — but no profile created.
    assert sent and "ALLOWED_CHAT_IDS" in sent[0][1]
    subs = state.load_subscriptions(state_dir / "subscriptions.json")
    assert subs == {}


def test_tick_full_lifecycle_subscribe_list_unsubscribe(tmp_path: Path):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    sent: list[tuple[str, str]] = []

    cfg = _cfg()
    common = dict(
        state_dir=state_dir,
        cfg=cfg,
        allowed_chats=ALLOWED,
        send=lambda cid, text: sent.append((cid, text)) or True,
    )

    # /subscribe → profile created
    tick(
        **common,
        fetch_updates=lambda offset: [
            _update("/subscribe ui-ux UX Designer", chat_id=1, update_id=100)
        ],
    )
    assert state.load_subscriptions(state_dir / "subscriptions.json") == {
        "1": [Profile(name="ui-ux", keywords=["UX Designer"])]
    }
    assert state.load_offset(state_dir / "tg_offset.txt") == 101

    # /list → reply contains the profile
    tick(
        **common,
        fetch_updates=lambda offset: [_update("/list", chat_id=1, update_id=101)],
    )
    list_replies = [t for _, t in sent if t.startswith("Your profiles:")]
    assert list_replies and "ui-ux" in list_replies[0]

    # /unsubscribe → profile gone
    tick(
        **common,
        fetch_updates=lambda offset: [_update("/unsubscribe ui-ux", chat_id=1, update_id=102)],
    )
    subs_after = state.load_subscriptions(state_dir / "subscriptions.json")
    assert subs_after == {"1": []}
    assert state.load_offset(state_dir / "tg_offset.txt") == 103


# ---------- _process_updates pure ----------


def test_process_updates_tracks_max_uid_across_non_commands():
    subs: dict[str, list[Profile]] = {}
    updates = [
        _update("hi", chat_id=1, update_id=10),
        _update("/list", chat_id=1, update_id=20),
        _update("hi again", chat_id=1, update_id=15),
    ]
    replies, max_uid = bot._process_updates(updates, subs, ALLOWED)
    assert len(replies) == 1  # only /list was a command
    assert max_uid == 20  # max across all, not just commands


def test_parse_command_is_imported_module_attr():
    """Smoke check that parse_command is the public surface used by tick."""
    assert callable(parse_command)
