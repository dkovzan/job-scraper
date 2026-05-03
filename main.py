"""Orchestrator: load config, fetch from each scraper, filter, deliver matches.

Phase 2 scope: real-run mode reads per-user subscriptions from ``.state/`` and
dedups against per-user seen-sets. ``--dry-run`` keeps the Phase 1 hardcoded
``ui-ux`` profile as a debug escape hatch (no state writes).

Output still goes to stdout — Telegram delivery is Phase 3.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import state
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


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="job-scraper")
    parser.add_argument("--config", default="config.toml", help="path to config.toml")
    parser.add_argument(
        "--state-dir",
        default=".state/",
        help="directory holding subscriptions.json / seen_jobs.json / etc. (default: .state/)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="bypass subscriptions + state; match against the hardcoded ui-ux profile",
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


def _run_with_subscriptions(all_jobs: list[Job], cfg: Config, state_dir: Path) -> int:
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
        seen_list = list(seen.get(chat_id, []))
        seen_set = set(seen_list)
        new_for_user: list[tuple[Job, Profile]] = []
        for job in all_jobs:
            if job.id in seen_set:
                continue
            matched = next((p for p in profiles if match_job(job, p, cfg.defaults)), None)
            if matched is None:
                continue
            new_for_user.append((job, matched))
            seen_list.append(job.id)
            seen_set.add(job.id)

        log.info("user %s: %d new matches", chat_id, len(new_for_user))
        for job, profile in new_for_user:
            print(_format_match_line(chat_id, profile, job))
        sent_total += len(new_for_user)
        seen[chat_id] = seen_list

    state.save_seen_jobs(seen_path, seen, max_per_user=cfg.state.max_seen_ids)
    log.info("done: %d notifications, seen sets saved to %s", sent_total, seen_path)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    _setup_logging()

    cfg = load_config(args.config)
    log.info("loaded config from %s", args.config)

    if args.from_fixtures:
        all_jobs = _load_from_fixtures()
        log.info("loaded %d jobs from fixtures", len(all_jobs))
    else:
        all_jobs = _scrape_all()

    if args.dry_run:
        return _run_dry(all_jobs, cfg)
    return _run_with_subscriptions(all_jobs, cfg, Path(args.state_dir))


if __name__ == "__main__":
    sys.exit(main())
