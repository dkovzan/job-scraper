"""Orchestrator: load config, fetch from each scraper, filter, print matches.

Phase 1 scope: dry-run only — no state, no Telegram. Real-run delivery is
wired up in later phases.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from config import load_config
from filters import match_job
from models import Job, Profile
from scrapers import SCRAPERS

log = logging.getLogger("main")

# Hardcoded test profile — replaced by per-user subscriptions in Phase 2.
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
        "--dry-run",
        action="store_true",
        default=True,
        help="print matches to stdout (default; only mode in Phase 1)",
    )
    parser.add_argument(
        "--from-fixtures",
        action="store_true",
        help="parse fixtures under tests/fixtures/ instead of hitting the network",
    )
    return parser.parse_args(argv)


def _load_from_fixtures() -> list[Job]:
    from scrapers.justjoin import _parse as parse_justjoin

    root = Path(__file__).resolve().parent
    fixtures = root / "tests" / "fixtures"
    payload = json.loads((fixtures / "justjoin_listings.json").read_text(encoding="utf-8"))
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


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    cfg = load_config(args.config)
    log.info("loaded config from %s", args.config)

    profile = Profile(name="ui-ux", keywords=_UI_UX_KEYWORDS)

    if args.from_fixtures:
        all_jobs = _load_from_fixtures()
        log.info("loaded %d jobs from fixtures", len(all_jobs))
    else:
        all_jobs = _scrape_all()

    matches = [j for j in all_jobs if match_job(j, profile, cfg.defaults)]
    log.info(
        "filtered %d -> %d matches against profile %r", len(all_jobs), len(matches), profile.name
    )

    for j in matches:
        print(f"- {j.title} @ {j.company}  ({j.location})  [{j.seniority or '—'}]  {j.url}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
