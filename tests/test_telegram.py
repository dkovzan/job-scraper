import json
from datetime import datetime

import httpx
import pytest

import telegram
from models import Job, Profile


@pytest.fixture(autouse=True)
def _bot_token(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake-token-123")


def _client(handler) -> httpx.Client:
    return httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url=telegram.API_BASE,
    )


def _job(**overrides) -> Job:
    base = dict(
        id="src:1",
        source="justjoin.it",
        title="UX Designer",
        company="Acme",
        location="Kraków, hybrid",
        seniority="mid",
        salary="10 000–15 000 PLN B2B",
        url="https://example.com/job/1",
        posted_at=datetime(2026, 1, 1),
    )
    base.update(overrides)
    return Job(**base)


# ---------- send_message: success path ----------


def test_send_message_posts_correct_url_and_payload():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["url"] = str(req.url)
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={"ok": True, "result": {}})

    sleeps: list[float] = []
    res = telegram.send_message(
        "123456789",
        "hello",
        client=_client(handler),
        sleeper=sleeps.append,
        rng=lambda a, b: 1.5,
    )

    assert res.ok
    assert res.chat_id == "123456789"
    assert seen["url"] == "https://api.telegram.org/botfake-token-123/sendMessage"
    assert seen["body"] == {
        "chat_id": "123456789",
        "text": "hello",
        "parse_mode": "Markdown",
    }
    assert sleeps == [1.5]  # throttle after success


def test_send_message_accepts_int_chat_id():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={"ok": True})

    res = telegram.send_message(
        42,
        "hi",
        client=_client(handler),
        sleeper=lambda _: None,
        rng=lambda a, b: 0.0,
    )

    assert res.ok
    assert res.chat_id == "42"
    assert seen["body"]["chat_id"] == "42"


def test_send_message_omits_parse_mode_when_none():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={"ok": True})

    telegram.send_message(
        "1",
        "hi",
        parse_mode=None,
        client=_client(handler),
        sleeper=lambda _: None,
        rng=lambda a, b: 0.0,
    )
    assert "parse_mode" not in seen["body"]


# ---------- 429 retry path ----------


def test_send_message_retries_on_429_honoring_retry_after():
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, json={"ok": False, "parameters": {"retry_after": 5}})
        return httpx.Response(200, json={"ok": True})

    sleeps: list[float] = []
    res = telegram.send_message(
        "1",
        "hi",
        client=_client(handler),
        sleeper=sleeps.append,
        rng=lambda a, b: 1.0,
    )

    assert res.ok
    assert calls["n"] == 2
    # 5s retry-after, then 1s throttle after the eventual success
    assert sleeps == [5.0, 1.0]


def test_send_message_429_default_retry_after_when_missing():
    def handler(req):
        return httpx.Response(429, json={"ok": False})

    sleeps: list[float] = []
    res = telegram.send_message(
        "1",
        "hi",
        client=_client(handler),
        sleeper=sleeps.append,
        rng=lambda a, b: 0.0,
    )
    assert not res.ok
    # 3 retries, each sleeping the default 1s
    assert sleeps == [1.0, 1.0, 1.0]
    assert res.error is not None and "429 retries" in res.error


def test_send_message_gives_up_after_max_retries():
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        return httpx.Response(429, json={"ok": False, "parameters": {"retry_after": 1}})

    res = telegram.send_message(
        "1",
        "hi",
        client=_client(handler),
        sleeper=lambda _: None,
        rng=lambda a, b: 0.0,
    )
    assert not res.ok
    assert calls["n"] == 3


# ---------- error paths ----------


def test_send_message_returns_error_on_4xx():
    def handler(req):
        return httpx.Response(400, text="Bad Request: chat not found")

    res = telegram.send_message(
        "1",
        "hi",
        client=_client(handler),
        sleeper=lambda _: None,
        rng=lambda a, b: 0.0,
    )
    assert not res.ok
    assert res.error is not None and "HTTP 400" in res.error


def test_send_message_handles_transport_error():
    def handler(req):
        raise httpx.ConnectError("boom")

    res = telegram.send_message(
        "1",
        "hi",
        client=_client(handler),
        sleeper=lambda _: None,
        rng=lambda a, b: 0.0,
    )
    assert not res.ok
    assert res.error is not None and "transport" in res.error


def test_send_message_raises_when_token_missing(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)

    def handler(req):  # pragma: no cover (never invoked)
        return httpx.Response(200, json={"ok": True})

    with pytest.raises(RuntimeError, match="TELEGRAM_BOT_TOKEN"):
        telegram.send_message(
            "1",
            "hi",
            client=_client(handler),
            sleeper=lambda _: None,
            rng=lambda a, b: 0.0,
        )


# ---------- format_job ----------


def test_format_job_matches_spec_layout():
    job = _job(
        title="UX Designer",
        company="Acme",
        location="Kraków, hybrid",
        seniority="mid",
        salary="10 000–15 000 PLN B2B",
        source="justjoin.it",
        url="https://example.com/job/1",
    )
    profile = Profile(name="ui-ux", keywords=["UX Designer"])
    out = telegram.format_job(job, profile)
    assert out == (
        "*UX Designer* — Acme\n"
        "📍 Kraków, hybrid  •  mid\n"
        "💰 10 000–15 000 PLN B2B\n"
        "🔗 https://example.com/job/1\n"
        "_via justjoin.it • matched: ui-ux_"
    )


def test_format_job_uses_em_dash_when_seniority_missing():
    job = _job(seniority=None)
    out = telegram.format_job(job, Profile(name="p", keywords=["x"]))
    assert "•  —\n" in out


def test_format_job_uses_em_dash_when_salary_missing():
    job = _job(salary=None)
    out = telegram.format_job(job, Profile(name="p", keywords=["x"]))
    assert "💰 —\n" in out


def test_format_job_escapes_markdown_specials_in_fields():
    job = _job(
        title="UX_Designer (with [tag] *star*)",
        url="https://example.com/foo_bar",
    )
    out = telegram.format_job(job, Profile(name="p", keywords=["x"]))
    # underscore + asterisk + bracket all escaped in fields
    assert r"\_" in out
    assert r"\*" in out
    assert r"\[" in out
    # url's underscore also escaped to avoid breaking V1 formatting
    assert r"foo\_bar" in out
