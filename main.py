"""Orchestrator: bot tick → scrape → filter → deliver matches.

Default mode runs both halves: first ``bot.tick()`` consumes any pending
``/subscribe`` etc. commands and updates ``subscriptions.json``, then the
scrape loop fetches jobs, filters per-user, and pushes matches via Telegram.
A failure in one half is logged but does not stop the other.

``--dry-run`` keeps the Phase 1 hardcoded ``ui-ux`` profile as a debug escape
hatch — no bot tick, no state writes, no Telegram.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections.abc import Callable
from pathlib import Path

import httpx

import bot
import state
import telegram
from config import Config, load_config
from filters import match_job
from models import Job, Profile
from scrapers import SCRAPERS

log = logging.getLogger("main")

# Hardcoded debug profile used by --dry-run only.
_UI_UX_KEYWORDS: list[str] = [
    "UI Designer",
    "UX Designer",
    "UI/UX",
    "UX/UI",
    "Product Designer",
    "Projektant UX",
    "Projektant UI",
    "Projektant interfejsów",
    "Designer produktu",
]

DEFAULT_MAX_PER_USER = 30

SendFunc = Callable[[str, Job, Profile], bool]


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="job-scraper")
    parser.add_argument("--config", default="config.toml", help="path to config.toml")
    parser.add_argument(
        "--state-dir",
        default=".state/",
        help="directory holding subscriptions.json / seen_jobs.json (default: .state/)",
    )
    parser.add_argument(
        "--max-per-user",
        type=int,
        default=DEFAULT_MAX_PER_USER,
        help=f"cap matches delivered to one user per run (default: {DEFAULT_MAX_PER_USER})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="bypass subscriptions, state, and Telegram; print hardcoded ui-ux matches",
    )
    parser.add_argument(
        "--from-fixtures",
        action="store_true",
        help="parse fixtures under tests/fixtures/ instead of hitting the network",
    )
    return parser.parse_args(argv)


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def _load_from_fixtures() -> list[Job]:
    from scrapers.justjoin import _parse as parse_justjoin

    root = Path(__file__).resolve().parent
    payload = json.loads(
        (root / "tests" / "fixtures" / "justjoin_listings.json").read_text(encoding="utf-8")
    )
    return parse_justjoin(payload)


def _scrape_all() -> list[Job]:
    jobs: list[Job] = []
    for fetch in SCRAPERS:
        module = getattr(fetch, "__module__", "<unknown>")
        try:
            batch = fetch()
        except Exception:
            log.exception("scraper %s failed", module)
            continue
        log.info("fetched %d jobs from %s", len(batch), module)
        jobs.extend(batch)
    return jobs


def _format_match_line(chat_id: str, profile: Profile, job: Job) -> str:
    return (
        f"[{chat_id} via {profile.name}] {job.title} @ {job.company}  "
        f"({job.location})  [{job.seniority or '—'}]  {job.url}"
    )


def _run_dry(all_jobs: list[Job], cfg: Config) -> int:
    profile = Profile(name="ui-ux", keywords=_UI_UX_KEYWORDS)
    matches = [j for j in all_jobs if match_job(j, profile, cfg.defaults)]
    log.info(
        "dry-run: filtered %d -> %d matches against profile %r",
        len(all_jobs),
        len(matches),
        profile.name,
    )
    for job in matches:
        print(_format_match_line("dry-run", profile, job))
    return 0


def _collect_matches_for_user(
    profiles: list[Profile],
    all_jobs: list[Job],
    cfg: Config,
    existing_seen: list[str],
) -> list[tuple[Job, Profile]]:
    """Return ``[(job, matching_profile), ...]`` in scrape order, skipping
    already-seen IDs and stopping at the first profile that matches per job."""
    seen_set = set(existing_seen)
    matches: list[tuple[Job, Profile]] = []
    for job in all_jobs:
        if job.id in seen_set:
            continue
        matched = next((p for p in profiles if match_job(job, p, cfg.defaults)), None)
        if matched is None:
            continue
        matches.append((job, matched))
        seen_set.add(job.id)
    return matches


def _run_with_subscriptions(
    all_jobs: list[Job],
    cfg: Config,
    state_dir: Path,
    max_per_user: int,
    send: SendFunc,
) -> int:
    subs_path = state_dir / cfg.state.subscriptions_file
    seen_path = state_dir / cfg.state.seen_file

    subscriptions = state.load_subscriptions(subs_path)
    seen = state.load_seen_jobs(seen_path)

    log.info("loaded %d users from %s", len(subscriptions), subs_path)
    if not subscriptions:
        log.warning("no subscriptions in %s — nothing to do", subs_path)
        return 0

    sent_total = 0
    for chat_id, profiles in subscriptions.items():
        existing = seen.get(chat_id, [])
        matches = _collect_matches_for_user(profiles, all_jobs, cfg, existing)
        log.info("user %s: %d new matches (cap %d)", chat_id, len(matches), max_per_user)

        seen_list = list(existing)
        for i, (job, profile) in enumerate(matches):
            # All matches are marked seen — even ones beyond the cap, so we
            # don't keep finding them on every subsequent tick.
            seen_list.append(job.id)
            if i >= max_per_user:
                continue
            if send(chat_id, job, profile):
                sent_total += 1
        seen[chat_id] = seen_list

    state.save_seen_jobs(seen_path, seen, max_per_user=cfg.state.max_seen_ids)
    log.info("done: %d notifications sent, seen sets saved to %s", sent_total, seen_path)
    return 0


def _telegram_sender(client: httpx.Client) -> SendFunc:
    def send(chat_id: str, job: Job, profile: Profile) -> bool:
        text = telegram.format_job(job, profile)
        result = telegram.send_message(chat_id, text, client=client)
        if not result.ok:
            log.warning("send failed for chat %s job %s: %s", chat_id, job.id, result.error)
        return result.ok

    return send


def _load_allowed_chats(cfg: Config) -> set[str]:
    raw = os.environ.get(cfg.telegram.allowed_chats_env, "")
    return {s.strip() for s in raw.split(",") if s.strip()}


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    _setup_logging()

    cfg = load_config(args.config)
    log.info("loaded config from %s", args.config)

    if args.dry_run:
        all_jobs = _load_from_fixtures() if args.from_fixtures else _scrape_all()
        if args.from_fixtures:
            log.info("loaded %d jobs from fixtures", len(all_jobs))
        return _run_dry(all_jobs, cfg)

    # Real run — fail fast if the bot token is missing before doing any work.
    telegram.get_bot_token()

    state_dir = Path(args.state_dir)
    allowed_chats = _load_allowed_chats(cfg)
    if not allowed_chats:
        log.warning(
            "%s is empty — bot.tick will only echo chat-ID hints",
            cfg.telegram.allowed_chats_env,
        )

    with telegram.make_client() as client:
        # Bot first: a /subscribe sent before this tick should land before we
        # filter jobs. A bot.tick failure is logged but doesn't kill the scrape.
        try:
            bot.tick(
                state_dir=state_dir,
                cfg=cfg,
                allowed_chats=allowed_chats,
                client=client,
            )
        except Exception:
            log.exception("bot.tick failed — continuing to scrape")

        all_jobs = _load_from_fixtures() if args.from_fixtures else _scrape_all()
        if args.from_fixtures:
            log.info("loaded %d jobs from fixtures", len(all_jobs))

        return _run_with_subscriptions(
            all_jobs,
            cfg,
            state_dir,
            args.max_per_user,
            _telegram_sender(client),
        )


if __name__ == "__main__":
    sys.exit(main())
