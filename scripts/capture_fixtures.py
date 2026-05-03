"""One-shot fixture capture utility.

Refreshes the per-source fixtures under ``tests/fixtures/`` from the live
sites. Run when a site's API/HTML shape changes.

Usage:

    python scripts/capture_fixtures.py            # all
    python scripts/capture_fixtures.py justjoin   # one source
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 job-scraper/0.1"

# justjoin.it categoryId 14 == design (UI/UX, product, graphic, …).
DESIGN_CATEGORY_ID = 14


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


def capture_nofluffjobs() -> None:
    url = "https://nofluffjobs.com/pl/design"
    headers = {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "pl,en;q=0.9",
    }
    print(f"GET {url}", file=sys.stderr)
    with httpx.Client(timeout=20.0, follow_redirects=True) as client:
        r = client.get(url, headers=headers)
    r.raise_for_status()
    out = FIXTURES / "nofluffjobs_design.html"
    FIXTURES.mkdir(parents=True, exist_ok=True)
    out.write_text(r.text, encoding="utf-8")
    print(f"wrote {out} ({len(r.text)} bytes)", file=sys.stderr)


def capture_bulldogjob() -> None:
    # /s/role,Designer would be the semantically-correct URL but bulldogjob is
    # a dev-focused board and that filter currently returns 0 jobs. Capture
    # /s/specialization,Design instead — it returns 50 jobs (mostly dev,
    # because the specialization filter is silently ignored), giving us a
    # populated fixture to test the parser against. The runtime scraper
    # uses /s/role,Designer for actual matching.
    url = "https://bulldogjob.pl/companies/jobs/s/specialization,Design"
    headers = {
        "User-Agent": UA,
        "Accept": "text/html",
        "Accept-Language": "pl,en;q=0.9",
    }
    print(f"GET {url}", file=sys.stderr)
    with httpx.Client(timeout=20.0, follow_redirects=True) as client:
        r = client.get(url, headers=headers)
    r.raise_for_status()
    out = FIXTURES / "bulldogjob_design.html"
    FIXTURES.mkdir(parents=True, exist_ok=True)
    out.write_text(r.text, encoding="utf-8")
    print(f"wrote {out} ({len(r.text)} bytes)", file=sys.stderr)


def capture_theprotocol() -> None:
    """theprotocol.it is fronted by Cloudflare; needs TLS-fingerprint impersonation."""
    from curl_cffi import requests as cffi

    url = "https://theprotocol.it/filtry/ux-ui;sp/praca"
    print(f"GET {url}", file=sys.stderr)
    r = cffi.get(url, impersonate="chrome120", timeout=20)
    r.raise_for_status()
    out = FIXTURES / "theprotocol_design.html"
    FIXTURES.mkdir(parents=True, exist_ok=True)
    out.write_text(r.text, encoding="utf-8")
    print(f"wrote {out} ({len(r.text)} bytes)", file=sys.stderr)


def capture_pracuj() -> None:
    """pracuj.pl is fronted by Cloudflare; needs TLS-fingerprint impersonation."""
    from curl_cffi import requests as cffi

    url = "https://it.pracuj.pl/praca/ux%20designer"
    print(f"GET {url}", file=sys.stderr)
    r = cffi.get(url, impersonate="chrome120", timeout=20)
    r.raise_for_status()
    out = FIXTURES / "pracuj_design.html"
    FIXTURES.mkdir(parents=True, exist_ok=True)
    out.write_text(r.text, encoding="utf-8")
    print(f"wrote {out} ({len(r.text)} bytes)", file=sys.stderr)


CAPTURES = {
    "justjoin": capture_justjoin,
    "nofluffjobs": capture_nofluffjobs,
    "bulldogjob": capture_bulldogjob,
    "theprotocol": capture_theprotocol,
    "pracuj": capture_pracuj,
}


def main(argv: list[str]) -> None:
    targets = argv[1:] or list(CAPTURES.keys())
    for name in targets:
        if name not in CAPTURES:
            print(f"unknown source: {name}", file=sys.stderr)
            continue
        CAPTURES[name]()


if __name__ == "__main__":
    main(sys.argv)
