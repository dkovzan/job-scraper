"""Telegram bot: command parser, handlers, and the per-tick loop.

``parse_command`` is pure — it turns a raw Telegram update dict into a
``Command`` (or ``None``). ``handle_command`` is pure-ish — it dispatches to
the right handler, mutating the per-user subscriptions dict for
/subscribe and /unsubscribe but doing no I/O. ``tick`` does the I/O:
fetches updates from getUpdates, processes them, persists subscription
changes, sends replies, and advances the offset cursor.

Bot replies are sent with ``parse_mode=None`` (plain text) so we never have
to escape user-supplied profile names or keywords when echoing them back.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

import state
import telegram
from config import Config
from models import Profile

log = logging.getLogger(__name__)

_KNOWN_COMMANDS = frozenset({"start", "help", "list", "subscribe", "unsubscribe", "whoami"})

_START_MSG = (
    "Hi! I send Telegram alerts for new job postings that match your profile.\n\n"
    "Set up your first profile, e.g.:\n"
    "/subscribe ui-ux UI Designer, UX Designer, Product Designer\n\n"
    "Type /help for the full command list."
)

_HELP_MSG = (
    "Commands:\n"
    "/list — show your profiles\n"
    "/subscribe <name> <kw>, <kw>, ... — add or replace a profile\n"
    "/unsubscribe <name> — remove a profile\n"
    "/whoami — show your chat ID\n"
    "/help — this message"
)

_USAGE_SUBSCRIBE = "Usage: /subscribe <name> <keyword>, <keyword>, ..."
_USAGE_UNSUBSCRIBE = "Usage: /unsubscribe <name>"


@dataclass(frozen=True)
class Command:
    name: str
    args: str
    chat_id: str
    update_id: int


@dataclass(frozen=True)
class Reply:
    chat_id: str
    text: str


# ----------- parse_command -----------


def parse_command(update: Any) -> Command | None:
    """Pure: a Telegram update → Command if it's a slash-command from a chat,
    else None. Unknown command names yield ``Command(name="unknown", ...)``
    so callers can reply with /help."""
    if not isinstance(update, dict):
        return None
    update_id = update.get("update_id")
    if not isinstance(update_id, int):
        return None
    message = update.get("message")
    if not isinstance(message, dict):
        return None
    text = message.get("text")
    if not isinstance(text, str):
        return None
    chat = message.get("chat")
    if not isinstance(chat, dict):
        return None
    chat_id = chat.get("id")
    if chat_id is None:
        return None

    text = text.strip()
    if not text.startswith("/"):
        return None

    parts = text.split(maxsplit=1)
    cmd_token = parts[0][1:]
    args = parts[1].strip() if len(parts) > 1 else ""

    # Strip "@BotName" suffix that group chats append.
    if "@" in cmd_token:
        cmd_token = cmd_token.split("@", 1)[0]
    cmd_token = cmd_token.lower()

    name = cmd_token if cmd_token in _KNOWN_COMMANDS else "unknown"
    return Command(name=name, args=args, chat_id=str(chat_id), update_id=update_id)


# ----------- handle_command -----------


def handle_command(
    cmd: Command,
    subscriptions: dict[str, list[Profile]],
    allowed_chats: set[str],
) -> Reply:
    """Dispatch a parsed command. Mutates ``subscriptions`` for /subscribe
    and /unsubscribe. ``/whoami`` works for everyone (it's how new users find
    their chat ID for onboarding); every other command from a non-allowlisted
    chat returns the chat-ID hint and never mutates state."""
    if cmd.name == "whoami":
        return Reply(cmd.chat_id, f"Your chat ID: {cmd.chat_id}")

    if cmd.chat_id not in allowed_chats:
        return Reply(cmd.chat_id, _not_allowed_reply(cmd.chat_id))

    if cmd.name == "start":
        return Reply(cmd.chat_id, _START_MSG)
    if cmd.name == "help":
        return Reply(cmd.chat_id, _HELP_MSG)
    if cmd.name == "list":
        return Reply(cmd.chat_id, _list_reply(cmd.chat_id, subscriptions))
    if cmd.name == "subscribe":
        return _handle_subscribe(cmd, subscriptions)
    if cmd.name == "unsubscribe":
        return _handle_unsubscribe(cmd, subscriptions)
    # unknown
    return Reply(cmd.chat_id, _HELP_MSG)


def _not_allowed_reply(chat_id: str) -> str:
    return (
        "You're not on the allowlist.\n"
        f"Your chat ID is {chat_id}.\n"
        "Ask the bot owner to add you to ALLOWED_CHAT_IDS."
    )


def _list_reply(chat_id: str, subscriptions: dict[str, list[Profile]]) -> str:
    profiles = subscriptions.get(chat_id, [])
    if not profiles:
        return "No active profiles. Use /subscribe <name> <kw>, <kw>, ... to start."
    lines = ["Your profiles:"]
    for p in profiles:
        kws = ", ".join(p.keywords)
        lines.append(f"- {p.name}: {kws}")
    return "\n".join(lines)


def _handle_subscribe(cmd: Command, subscriptions: dict[str, list[Profile]]) -> Reply:
    parsed = _parse_subscribe_args(cmd.args)
    if parsed is None:
        return Reply(cmd.chat_id, _USAGE_SUBSCRIBE)
    name, keywords = parsed
    profiles = subscriptions.setdefault(cmd.chat_id, [])
    for i, existing in enumerate(profiles):
        if existing.name == name:
            profiles[i] = Profile(name=name, keywords=keywords)
            return Reply(
                cmd.chat_id,
                f"Updated {name} ({len(keywords)} keyword{'s' if len(keywords) != 1 else ''}).",
            )
    profiles.append(Profile(name=name, keywords=keywords))
    return Reply(
        cmd.chat_id,
        f"Subscribed to {name} ({len(keywords)} keyword{'s' if len(keywords) != 1 else ''}). "
        "Matches will start arriving on the next tick.",
    )


def _handle_unsubscribe(cmd: Command, subscriptions: dict[str, list[Profile]]) -> Reply:
    name = cmd.args.strip()
    if not name:
        return Reply(cmd.chat_id, _USAGE_UNSUBSCRIBE)
    profiles = subscriptions.get(cmd.chat_id, [])
    for i, p in enumerate(profiles):
        if p.name == name:
            del profiles[i]
            return Reply(cmd.chat_id, f"Removed {name}.")
    return Reply(cmd.chat_id, f"No profile named {name}.")


def _parse_subscribe_args(args: str) -> tuple[str, list[str]] | None:
    """First token = profile name; remainder = comma-separated keywords."""
    args = args.strip()
    if not args:
        return None
    parts = args.split(maxsplit=1)
    if len(parts) < 2:
        return None
    name = parts[0]
    keywords = [k.strip() for k in parts[1].split(",") if k.strip()]
    if not keywords:
        return None
    return name, keywords


# ----------- _process_updates (pure) -----------


def _process_updates(
    updates: list[Any],
    subscriptions: dict[str, list[Profile]],
    allowed_chats: set[str],
) -> tuple[list[Reply], int]:
    """Walk all updates: collect their max update_id (so the offset advances
    even for non-command messages) and dispatch any commands. Mutates
    ``subscriptions`` in place."""
    max_uid = -1
    replies: list[Reply] = []
    for update in updates:
        if isinstance(update, dict):
            uid = update.get("update_id")
            if isinstance(uid, int) and uid > max_uid:
                max_uid = uid
        cmd = parse_command(update)
        if cmd is None:
            continue
        replies.append(handle_command(cmd, subscriptions, allowed_chats))
    return replies, max_uid


# ----------- tick (I/O) -----------

FetchUpdatesFunc = Callable[[int], list[Any]]
SendReplyFunc = Callable[[str, str], bool]


def tick(
    *,
    state_dir: Path,
    cfg: Config,
    allowed_chats: set[str],
    client: httpx.Client | None = None,
    fetch_updates: FetchUpdatesFunc | None = None,
    send: SendReplyFunc | None = None,
) -> int:
    """Fetch new updates, process commands, save state, send replies.

    Pass ``fetch_updates`` and/or ``send`` to mock the HTTP layer in tests.
    Returns the number of updates processed."""
    own_client = client is None and (fetch_updates is None or send is None)
    if own_client:
        client = telegram.make_client()
    try:
        fetch = fetch_updates if fetch_updates is not None else _default_fetcher(client)
        sender = send if send is not None else _default_sender(client)
        return _do_tick(state_dir, cfg, allowed_chats, fetch, sender)
    finally:
        if own_client and client is not None:
            client.close()


def _default_fetcher(client: httpx.Client | None) -> FetchUpdatesFunc:
    assert client is not None

    def fetch(offset: int) -> list[Any]:
        return _get_updates(client, offset)

    return fetch


def _default_sender(client: httpx.Client | None) -> SendReplyFunc:
    assert client is not None

    def send(chat_id: str, text: str) -> bool:
        res = telegram.send_message(chat_id, text, parse_mode=None, client=client)
        if not res.ok:
            log.warning("bot reply failed for %s: %s", chat_id, res.error)
        return res.ok

    return send


def _do_tick(
    state_dir: Path,
    cfg: Config,
    allowed_chats: set[str],
    fetch_updates: FetchUpdatesFunc,
    send: SendReplyFunc,
) -> int:
    offset_path = state_dir / cfg.state.offset_file
    subs_path = state_dir / cfg.state.subscriptions_file

    offset = state.load_offset(offset_path)
    try:
        updates = fetch_updates(offset)
    except (httpx.HTTPError, ValueError) as e:
        log.warning("bot.tick: fetch_updates failed: %s", e)
        return 0

    if not updates:
        log.info("bot.tick: no new updates (offset=%d)", offset)
        return 0

    subscriptions = state.load_subscriptions(subs_path)
    replies, max_uid = _process_updates(updates, subscriptions, allowed_chats)

    state.save_subscriptions(subs_path, subscriptions)

    for reply in replies:
        send(reply.chat_id, reply.text)

    if max_uid >= 0:
        state.save_offset(offset_path, max_uid + 1)

    log.info(
        "bot.tick: processed %d updates, sent %d replies, offset -> %d",
        len(updates),
        len(replies),
        max_uid + 1 if max_uid >= 0 else offset,
    )
    return len(updates)


def _get_updates(client: httpx.Client, offset: int) -> list[Any]:
    token = telegram.get_bot_token()
    r = client.get(
        f"/bot{token}/getUpdates",
        params={"offset": offset, "timeout": 0},
    )
    if r.status_code != 200:
        log.warning("getUpdates HTTP %d: %s", r.status_code, r.text[:200])
        return []
    body = r.json()
    if not isinstance(body, dict) or not body.get("ok"):
        log.warning("getUpdates not-ok: %s", str(body)[:200])
        return []
    result = body.get("result", [])
    return result if isinstance(result, list) else []
