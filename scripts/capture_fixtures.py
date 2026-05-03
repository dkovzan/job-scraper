"""One-shot fixture capture utility.

Hits the live justjoin.it API and writes the raw page-1 JSON response to
``tests/fixtures/justjoin_listings.json``. Run when the API shape changes,
or to refresh stale data.

Usage:

    python scripts/capture_fixtures.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"

# justjoin.it categoryId 14 == design (UI/UX, product, graphic, …).
DESIGN_CATEGORY_ID = 14

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 job-scraper/0.1"


def capture_justjoin() -> None:
    url = (
        "https://api.justjoin.it/v2/user-panel/offers"
        f"?categories[]={DESIGN_CATEGORY_ID}&itemsPerPage=20&page=1"
    )
    headers = {
        "User-Agent": UA,
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
        "Origin": "https://justjoin.it",
        "Referer": "https://justjoin.it/",
        "Version": "2",
    }
    print(f"GET {url}", file=sys.stderr)
    with httpx.Client(timeout=15.0, follow_redirects=True) as client:
        r = client.get(url, headers=headers)
    r.raise_for_status()
    payload = r.json()
    out = FIXTURES / "justjoin_listings.json"
    FIXTURES.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    n = len(payload.get("data", [])) if isinstance(payload, dict) else len(payload)
    print(f"wrote {out} ({n} listings)", file=sys.stderr)


if __name__ == "__main__":
    capture_justjoin()
