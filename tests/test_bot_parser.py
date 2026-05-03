"""Tests for bot.parse_command — pure parsing of Telegram update payloads."""

from bot import parse_command


def _update(text: str, chat_id: int = 549849116, update_id: int = 100) -> dict:
    """Build a realistic Telegram update with a private-chat text message."""
    return {
        "update_id": update_id,
        "message": {
            "message_id": 1,
            "from": {"id": chat_id, "is_bot": False, "first_name": "Test"},
            "chat": {"id": chat_id, "type": "private", "first_name": "Test"},
            "date": 1714745200,
            "text": text,
        },
    }


# ---------- happy path ----------


def test_parse_start():
    cmd = parse_command(_update("/start"))
    assert cmd is not None
    assert cmd.name == "start"
    assert cmd.args == ""
    assert cmd.chat_id == "549849116"
    assert cmd.update_id == 100


def test_parse_help():
    cmd = parse_command(_update("/help"))
    assert cmd is not None
    assert cmd.name == "help"


def test_parse_list():
    cmd = parse_command(_update("/list"))
    assert cmd is not None and cmd.name == "list"


def test_parse_whoami():
    cmd = parse_command(_update("/whoami"))
    assert cmd is not None and cmd.name == "whoami"


def test_parse_subscribe_with_one_keyword():
    cmd = parse_command(_update("/subscribe ui-ux UX Designer"))
    assert cmd is not None
    assert cmd.name == "subscribe"
    assert cmd.args == "ui-ux UX Designer"


def test_parse_subscribe_with_comma_separated_keywords():
    cmd = parse_command(_update("/subscribe ui-ux UX Designer, UI Designer, Product Designer"))
    assert cmd is not None
    assert cmd.name == "subscribe"
    assert cmd.args == "ui-ux UX Designer, UI Designer, Product Designer"


def test_parse_unsubscribe():
    cmd = parse_command(_update("/unsubscribe ui-ux"))
    assert cmd is not None
    assert cmd.name == "unsubscribe"
    assert cmd.args == "ui-ux"


# ---------- normalization ----------


def test_parse_command_is_lowercased():
    cmd = parse_command(_update("/SUBSCRIBE ui-ux foo"))
    assert cmd is not None
    assert cmd.name == "subscribe"


def test_parse_strips_bot_username():
    """Group chats append @BotName to the command — strip it before matching."""
    cmd = parse_command(_update("/subscribe@MyJobBot ui-ux UX Designer"))
    assert cmd is not None
    assert cmd.name == "subscribe"
    assert cmd.args == "ui-ux UX Designer"


def test_parse_trims_outer_whitespace():
    cmd = parse_command(_update("  /list  "))
    assert cmd is not None
    assert cmd.name == "list"


def test_parse_normalises_args_whitespace():
    cmd = parse_command(_update("/subscribe   ui-ux   UX Designer"))
    assert cmd is not None
    # We don't squish internal whitespace — handler does it on tokenize. Just
    # confirm leading/trailing trim of the args portion.
    assert cmd.args.startswith("ui-ux")
    assert cmd.args.endswith("UX Designer")


# ---------- unknown / non-command / garbage ----------


def test_parse_unknown_command_returns_unknown():
    cmd = parse_command(_update("/banana"))
    assert cmd is not None
    assert cmd.name == "unknown"
    assert cmd.args == ""


def test_parse_non_command_returns_none():
    assert parse_command(_update("hello")) is None
    assert parse_command(_update("just chatting")) is None


def test_parse_empty_text_returns_none():
    assert parse_command(_update("")) is None


def test_parse_no_message_returns_none():
    assert parse_command({"update_id": 1}) is None


def test_parse_no_text_returns_none():
    assert (
        parse_command({"update_id": 1, "message": {"chat": {"id": 1}, "photo": [{"file_id": "x"}]}})
        is None
    )


def test_parse_no_chat_returns_none():
    assert parse_command({"update_id": 1, "message": {"text": "/start"}}) is None


def test_parse_missing_update_id_returns_none():
    assert parse_command({"message": {"chat": {"id": 1}, "text": "/start"}}) is None


def test_parse_non_dict_returns_none():
    assert parse_command(None) is None
    assert parse_command("garbage") is None
    assert parse_command([]) is None


def test_parse_edited_message_ignored():
    """Telegram delivers edits as ``edited_message`` — we ignore them; we'd
    rather under-react than re-process a command on edit."""
    update = {
        "update_id": 1,
        "edited_message": {"chat": {"id": 1}, "text": "/subscribe ui-ux X"},
    }
    assert parse_command(update) is None


# ---------- /subscribe edge cases ----------


def test_parse_subscribe_no_args():
    cmd = parse_command(_update("/subscribe"))
    assert cmd is not None
    assert cmd.name == "subscribe"
    assert cmd.args == ""  # handler will reject; parser still returns the command


def test_parse_subscribe_only_name_no_keywords():
    cmd = parse_command(_update("/subscribe ui-ux"))
    assert cmd is not None
    assert cmd.args == "ui-ux"  # handler will reject
