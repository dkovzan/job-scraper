# Job Scraper — Spec

Python scraper that pulls job postings from Polish job boards, filters them
against subscriptions you set up via a Telegram bot, and pushes new matches back
to Telegram. Runs on a cron via GitHub Actions.

## Goals

- Notify a small allowlist of users (initially: owner + spouse) about fresh,
  relevant postings — defaults tuned for junior/mid UI/UX in Kraków/PL-remote,
  but driven by user-defined subscriptions.
- Subscriptions managed end-to-end through Telegram (`/subscribe`,
  `/unsubscribe`, `/list`); no editing files in the repo to add a new keyword set.
- Zero infra to maintain — bot and scraper share one GH Actions workflow.
- Easy to add a new board: one file in `scrapers/`.

## Non-goals (POC)

- Public bot — invite-only via chat-ID allowlist.
- Web UI, database, analytics dashboards.
- Auth-walled boards (LinkedIn) — deferred.
- Resume / cover-letter automation.
- Sub-cron-interval reply latency (subscribe acks land on the next tick).

## Job sources

Prefer JSON APIs where they exist; fall back to HTML scraping. Each source is one
module under `scrapers/` exposing `fetch() -> list[Job]`.

| Source            | Method           | Notes                                                                 |
| ----------------- | ---------------- | --------------------------------------------------------------------- |
| `justjoin.it`     | JSON API         | Public-ish API used by their SPA. Filter by category=design.          |
| `nofluffjobs.com` | JSON API         | `/api/search/posting` accepts category + city filters.                |
| `bulldogjob.pl`   | JSON API         | Has a public listings endpoint; verify during implementation.         |
| `theprotocol.it`  | HTML / Next data | Next.js site — may expose `__NEXT_DATA__` JSON in page source.        |
| `pracuj.pl`       | HTML             | Largest board, most useful, also most likely to break / rate-limit.   |

Skipped for POC: `linkedin.com` (auth), `rocketjobs.pl` (same group as JJ/NFJ —
add later if it surfaces unique listings), `jjit.pl` (same site as justjoin.it).

> Endpoint shapes need verification during implementation — site internals change.

## Subscriptions & filtering

Filtering is driven by **profiles**, scoped per user (chat ID). Each profile
has a `name` and a list of `keywords`; seniority and location come from global
defaults. For a given user, a posting is kept if it matches **any** of their
profiles.

Three files cooperate:

| File                 | Edited by | Scope    | Holds                                                |
| -------------------- | --------- | -------- | ---------------------------------------------------- |
| `config.toml`        | you (PR)  | global   | sources, telegram setup, **default** seniority/locations |
| `subscriptions.json` | the bot   | per-user | active profiles, keyed by chat ID                    |
| `seen_jobs.json`     | the bot   | per-user | already-sent job IDs, keyed by chat ID               |

At scrape time, for each allowed user the script reads their profiles, inherits
defaults, filters the global scrape result, and sends new matches to that user
only.

### `config.toml` shape

```toml
[telegram]
bot_token_env     = "TELEGRAM_BOT_TOKEN"
allowed_chats_env = "ALLOWED_CHAT_IDS"   # comma-separated chat IDs

[state]
seen_file          = "seen_jobs.json"
subscriptions_file = "subscriptions.json"
offset_file        = "tg_offset.txt"     # Telegram getUpdates cursor
max_seen_ids       = 5000                # trim oldest per user beyond this

[defaults]
seniority = ["junior", "mid", "regular", "młodszy"]
locations = [
  { city = "Kraków", modes = ["onsite", "hybrid", "remote"] },
  { country = "PL",  modes = ["remote"] },
]
```

### `subscriptions.json` shape

Bot-managed. Top-level keys are Telegram chat IDs (strings). A user with no
entry simply receives nothing until they `/subscribe`.

```json
{
  "123456789": {
    "profiles": [
      {
        "name": "ui-ux",
        "keywords": [
          "UI Designer", "UX Designer", "UI/UX", "UX/UI", "Product Designer",
          "Projektant UX", "Projektant UI", "Projektant interfejsów", "Designer produktu"
        ]
      }
    ]
  },
  "987654321": {
    "profiles": [
      { "name": "test-auto", "keywords": ["Test Automation", "QA Automation", "SDET"] }
    ]
  }
}
```

### `seen_jobs.json` shape

Same chat-ID keying. Per-user dedup means a job that's new to one user isn't
suppressed for another (matters when a second user subscribes later to
overlapping keywords).

```json
{
  "123456789": ["justjoin.it:abc123", "pracuj.pl:def456"],
  "987654321": ["nofluffjobs.com:xyz789"]
}
```

### Matching rules

- **`keywords`** — case-insensitive substring match against title (and category
  field if the source provides one). Diacritics-insensitive (`Kraków` == `Krakow`).
- **`seniority`** (from defaults) — match against the listing's seniority field.
  If the listing has no seniority, **keep it** (don't false-negative on missing
  data). Implicitly rejects anything matching `senior`, `lead`, `principal`,
  `staff`, `head`, `starszy` *unless* defaults explicitly list those terms.
- **`locations`** (from defaults) — a list of clauses, OR-ed together:
  - `{ city = "...", modes = [...] }` — listing's city matches AND its work
    mode is in `modes`, **or**
  - `{ country = "...", modes = [...] }` — listing has no specific city (or
    is country-wide) AND mode is in `modes`. `modes` values: `onsite`,
    `hybrid`, `remote`.
- No filter on employment type or language (intentional).

### Per-profile overrides (future hook)

Profile entries may later grow optional `seniority` / `locations` keys that
override the defaults. POC keeps profiles flat (just `name` + `keywords`), with
defaults applied uniformly per user.

## Bot interaction

The bot runs inside the same GH Actions workflow — no separate process. Each
cron tick it long-polls Telegram (`getUpdates` with a cursor in `tg_offset.txt`),
processes any pending commands, then runs the scraper.

### Commands

All commands operate on the **calling user's** slot in `subscriptions.json`.
You never see, edit, or get notifications from another user's profiles.

| Command                                       | Effect                                                |
| --------------------------------------------- | ----------------------------------------------------- |
| `/start`                                      | If chat ID is allowlisted: short help. Else: replies with the user's chat ID and "ask the owner to add me". |
| `/help`                                       | Lists commands.                                       |
| `/list`                                       | Replies with **your** current profiles.               |
| `/subscribe <name> <keyword>, <keyword>, ...` | Adds (or replaces) a profile in your slot. Names are slug-like (`ui-ux`, `test-auto`). |
| `/unsubscribe <name>`                         | Removes one of your profiles by name.                 |
| `/whoami`                                     | Replies with the chat ID — handy for adding new allowed users. |

Commands from non-allowlisted chats are answered only with the chat-ID hint
(useful for onboarding) and otherwise ignored — they cannot mutate state.

### Auth model

- `ALLOWED_CHAT_IDS` env var = comma-separated list of Telegram chat IDs.
- Each allowed chat has its own slot in `subscriptions.json` and `seen_jobs.json`.
  Subscriptions and notifications are fully isolated between users.
- Onboarding a new user: they send `/start` to the bot, it replies with their
  chat ID, owner adds it to the `ALLOWED_CHAT_IDS` repo secret, done. On the
  next tick the bot accepts their commands; their slot is created lazily on
  first `/subscribe`.

### Latency expectations

Subscribe / unsubscribe acks arrive on the **next cron tick** (worst case
≈ cadence interval). This is acceptable for a personal job-alert tool; users
should be told once and not surprised. If it ever bothers us, swap cron-poll
for a webhook later (architectural impact: a tiny serverless function,
otherwise unchanged).

### Bot state files

- `subscriptions.json` — committed; per-user profiles.
- `seen_jobs.json` — committed; per-user dedup sets.
- `tg_offset.txt` — committed; single integer, the Telegram `update_id` cursor.
  Without this we'd reprocess the same commands every tick. Global, not per-user
  (it's the bot's read position, not a per-user concept).

## Job model

```python
@dataclass(frozen=True)
class Job:
    id: str            # stable ID: f"{source}:{source_native_id_or_url_hash}"
    source: str        # e.g. "justjoin.it"
    title: str
    company: str
    location: str      # human-readable, e.g. "Kraków, hybrid" or "Remote (PL)"
    seniority: str | None
    salary: str | None # raw string, e.g. "12 000 – 18 000 PLN, B2B"
    url: str
    posted_at: datetime | None
```

`id` is the dedup key — must be stable across runs.

## State storage — the `state` branch

All mutable state (`subscriptions.json`, `seen_jobs.json`, `tg_offset.txt`)
lives on a dedicated **orphan branch** called `state`. Code lives on `main`;
state lives on `state`. The two histories are parallel and never merged.

Why: keeps `main`'s `git log` clean (no `[bot] state` commits cluttering
real history) while still giving us git's durability, inspectability, and
revertability for free.

### Branch layout

`state` branch contains only:

```
.
├── README.md             # one-paragraph "this branch holds bot state, do not merge"
├── subscriptions.json    # per-user profiles
├── seen_jobs.json        # per-user dedup sets
├── tg_offset.txt         # global Telegram update_id cursor
└── failure_counts.json   # per-source consecutive-failure counter
```

No code, no `.github/`, nothing else. Created once with `git checkout --orphan state`.

### Workflow integration

The GH Actions job does **two checkouts**:

1. `actions/checkout@v4` — default, gets `main` into the workspace.
2. `actions/checkout@v4` with `ref: state`, `path: .state` — gets the `state`
   branch into a `.state/` subdirectory.

`config.toml` points all state file paths into `.state/`. The script reads and
writes `.state/*` as if they were normal files; git knows they belong to the
`state` branch via the second checkout.

After the script runs, a final step:

- `cd .state && git add -A`
- If `git diff --cached --quiet` returns nonzero (i.e. there are changes):
  commit with a generated message like `state: 3 new jobs, 0 sub changes`
  and `git push origin state`.
- If nothing changed, no commit, no push. Most ticks will be no-ops.

Requires `permissions: contents: write` on the workflow.

### Local-dev safety

Add `.state/` to the root `.gitignore` on `main`. Prevents anyone running the
script locally from accidentally staging state files into a `main` commit.

### Caps & maintenance

- Trim each user's `seen_jobs` list to the most recent ~5 000 IDs (FIFO).
- The `state` branch's git history grows over time; if it ever gets bloated,
  re-orphan it (one-shot manual: `git checkout --orphan state-new`, copy
  files, force-push). Not a near-term concern.

## Telegram delivery

- One message per new job per user (no digest for POC).
- Bot token via repo secret `TELEGRAM_BOT_TOKEN`; allowed chat IDs via
  `ALLOWED_CHAT_IDS` (comma-separated). Both injected as env vars in the workflow.
- Each user receives only jobs that match their own profiles and aren't in
  their own `seen_jobs` set.
- Message format (Markdown):

  ```
  *{title}* — {company}
  📍 {location}  •  {seniority or "—"}
  💰 {salary or "—"}
  🔗 {url}
  _via {source} • matched: {profile.name}_
  ```

- Rate limit: sleep 1–2 s between sends; on HTTP 429 honour `retry_after`.
- Per-run cap: max 30 messages per user, to avoid floods after a long outage.
  Excess gets marked as seen anyway (so we don't re-send next tick).

## Architecture

```
job-scraper/
├── scrapers/
│   ├── __init__.py        # registry: list of fetch() callables
│   ├── justjoin.py
│   ├── nofluffjobs.py
│   ├── bulldogjob.py
│   ├── theprotocol.py
│   └── pracuj.py
├── models.py              # Job + Profile dataclasses
├── config.py              # load + validate config.toml
├── filters.py             # match Job against a Profile
├── state.py               # subscriptions.json + seen_jobs.json I/O (in .state/)
├── bot.py                 # Telegram getUpdates loop, command parser
├── telegram.py            # low-level Telegram API wrapper
├── main.py                # orchestrator: bot tick → scrape → filter → send → save
├── tests/
│   ├── test_filters.py
│   ├── test_bot_commands.py
│   └── fixtures/          # captured API/HTML samples
├── .github/workflows/
│   └── scrape.yml
├── requirements.txt
├── config.toml            # sources, telegram setup, filter defaults
├── .gitignore             # ignores .state/
└── README.md
```

State files (`subscriptions.json`, `seen_jobs.json`, `tg_offset.txt`,
`failure_counts.json`) live on the parallel **`state` branch** — see the
State Storage section. They're checked out into `.state/` at workflow time and
never appear on `main`.

`main.py` runs each scraper in a try/except — one broken source must not kill
the run. Log a warning, continue.

## Stack

- Python 3.12.
- `httpx` for HTTP (sync, simpler for cron; can switch to async if pages > ~50).
- `selectolax` for HTML parsing (faster than BeautifulSoup, lxml-backed).
- Standard library `dataclasses`, `logging`, `re`.
- `pytest` for tests, `ruff` for lint/format.

No `pydantic`, no ORM, no framework — keep deps thin.

## Scheduling — GitHub Actions

Two workflow files: one runs the bot+scraper twice a day, one rewrites the
state branch monthly to keep its history bounded.

### `.github/workflows/scrape.yml` (twice daily)

- `on.schedule`: cron `0 6,14 * * *` (06:00 and 14:00 **UTC**).
  - In CEST (Polish summer): 08:00 and 16:00 local — exact.
  - In CET (Polish winter): 07:00 and 15:00 local — 1h early. GH Actions cron
    has no DST awareness; either pick a season to favour or flip the cron
    twice a year.
- `on.workflow_dispatch` for manual runs.
- `permissions: contents: write` and `issues: write` (state push + failure alerts).
- `concurrency: { group: state-write, cancel-in-progress: false }` — shared with
  the orphan workflow to prevent races on the `state` branch.
- Steps:
  1. `actions/checkout@v4` — code on `main`.
  2. `actions/checkout@v4` with `ref: state`, `path: .state` — state branch.
  3. `actions/setup-python@v5` (3.12).
  4. `pip install -r requirements.txt`.
  5. `python -m main`.
  6. `cd .state && git add -A && (git diff --cached --quiet || (git -c user.name=bot -c user.email=bot@noreply commit -m "state: <generated summary>" && git push origin state))`.
- Secrets: `TELEGRAM_BOT_TOKEN`, `ALLOWED_CHAT_IDS`.

### `.github/workflows/state-orphan.yml` (monthly)

Keeps the `state` branch's git history from growing unbounded by re-orphaning
it. ~60 commits/month otherwise; after 5 years that's 3600 commits we don't
need.

- `on.schedule`: cron `0 4 1 * *` (04:00 UTC on the 1st of each month — chosen
  to avoid colliding with a scrape tick).
- `on.workflow_dispatch` for manual rebuilds.
- `permissions: contents: write` (needs force-push).
- Steps:
  1. Checkout `state` branch.
  2. `git checkout --orphan state-fresh`
  3. `git add -A && git commit -m "state: monthly orphan rebuild"`
  4. `git push origin state-fresh:state --force`
- Concurrency group `state-write` shared with `scrape.yml` so the two cannot
  race. (Add the same group key to `scrape.yml`.)

Force-push is intentional and safe here: the state files themselves are
identical before and after; only the history is reset.

## Failure modes & mitigations

| Risk                              | Mitigation                                                        |
| --------------------------------- | ----------------------------------------------------------------- |
| Source HTML changes, scraper 500s | Per-source try/except; failure-alert mechanism (see below).       |
| Anti-bot block (pracuj.pl etc.)   | Realistic User-Agent, jittered delays, accept reduced coverage.   |
| Telegram 429                      | Honour `retry_after`; per-user cap of 30 messages per run.        |
| Same job on 3 boards              | Dedup by `id` only — duplicates across sources will post 3×.      |
|                                   | Cross-source dedup (by title+company hash) is a v2 feature.       |
| GH Actions cron drift             | Acceptable — job postings are not minute-sensitive.               |
| Garbage / unknown bot commands    | Bot replies with `/help` text; never crashes the run.             |
| Non-allowlisted user spams bot    | Bot replies once with chat-ID hint, then silently drops.          |
| `state` branch push race          | Shared `state-write` concurrency group across both workflows.     |

### Failure alerts (GitHub Issues)

Per-source failure tracking lives in `.state/failure_counts.json`:

```json
{ "pracuj.pl": 2, "justjoin.it": 0, "nofluffjobs.com": 0 }
```

On each tick, per source:

- Scraper success → reset counter to `0`. If an open issue with the
  conventional title `[scraper-down] <source>` exists, close it with a
  recovery comment.
- Scraper failure (exception in `fetch()`) → increment counter.
  - When the counter hits **3** consecutive failures, check via
    `gh issue list --search '[scraper-down] <source> in:title is:open'`
    whether one is already open. If not, `gh issue create` a new one with
    the last error's traceback in the body.
  - Above the threshold, do nothing further (don't spam more issues).

Uses the `gh` CLI which is preinstalled on GH Actions runners. The
`issues: write` permission is granted in the workflow.

## Future (out of POC scope)

- Per-profile overrides for seniority / location (extend `/subscribe` syntax
  or add `/set <profile> <field> <value>`).
- Webhook-based bot for instant command acks (Cloudflare Worker → repo dispatch).
- Cross-source dedup (title + company fuzzy match).
- Salary parsing into a comparable numeric range.
- Add LinkedIn (needs cookie/login flow).
- Daily digest mode as alternative to per-job messages.

## Decisions log

- **Cron**: 06:00 and 14:00 UTC (≈ 08:00 / 16:00 Polish summer time).
- **Per-user `seen_jobs` cap**: 5 000 IDs, FIFO trim.
- **Failure alerts**: open a GitHub Issue after 3 consecutive failures of any
  one source; auto-close on recovery.
- **State branch maintenance**: monthly orphan rebuild via dedicated workflow.
