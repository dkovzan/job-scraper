# Implementation Plan

Companion to [SPEC.md](SPEC.md). Tasks are decomposed so each can be picked up
without re-reading the full spec — every task lists its goal, files, acceptance
criteria, and the spec sections it implements.

## How to use this plan

- Tasks are grouped into phases. **Phases run in order; tasks within a phase can
  run in order or some can be parallelised** (noted where applicable).
- Each task should fit in one focused session (~1–3 h).
- "Spec refs" point to the section in [SPEC.md](SPEC.md) that defines what
  "correct" looks like — when in doubt, the spec wins; if it's wrong, fix the
  spec first.
- "Acceptance" is the done-criterion. Don't move on until it's met.
- After finishing a task, commit it under a `feat: <task id> <short title>`
  message so the git log mirrors the plan.

## User pre-work (only you can do these)

These don't block code work, but block end-to-end testing.

- [ ] Create a Telegram bot via [@BotFather](https://t.me/BotFather), get the
      token. Save as repo secret `TELEGRAM_BOT_TOKEN`.
- [ ] Send `/start` to your new bot, then send `/whoami` (after Phase 4) — or
      use [@userinfobot](https://t.me/userinfobot) right now to grab your chat ID.
- [ ] Add chat IDs as repo secret `ALLOWED_CHAT_IDS` (comma-separated).
- [ ] Create the orphan `state` branch (one-shot, see Task 5.2).

---

## Phase 0 — Foundations

Skeleton + shared types. Everything after this depends on it.

### Task 0.1 — Project skeleton

**Goal**: empty but valid Python project with linting, deps, and directory layout.

**Files**:
- `pyproject.toml` (or `requirements.txt` + `ruff.toml`) — pick one; pyproject preferred.
- `.gitignore` — must include `.state/`, `__pycache__/`, `.venv/`, `*.pyc`.
- `config.toml` — populated per spec, including the `ui-ux` defaults.
- `scrapers/__init__.py`, `tests/__init__.py` — empty.
- Update `README.md` with one-paragraph project description + how to run locally.

**Acceptance**:
- `pip install -e .` (or `pip install -r requirements.txt`) succeeds.
- `ruff check .` and `ruff format --check .` pass on the empty tree.
- `pytest` runs and reports zero tests collected, no errors.

**Spec refs**: [Architecture](SPEC.md#architecture), [Stack](SPEC.md#stack),
[`config.toml` shape](SPEC.md#configtoml-shape).

---

### Task 0.2 — Models

**Goal**: `Job` and `Profile` dataclasses + trivial tests.

**Files**:
- `models.py` — `Job` (frozen, with the fields from the spec), `Profile`
  (`name: str`, `keywords: list[str]`).
- `tests/test_models.py` — instantiate one of each, verify equality/hashability
  for `Job` (needed for dedup sets later).

**Acceptance**:
- `pytest tests/test_models.py` passes.
- `Job` is hashable by `id` (so `set[Job]` works).

**Spec refs**: [Job model](SPEC.md#job-model).

---

### Task 0.3 — Config loader

**Goal**: load `config.toml` into a typed `Config` object; fail loudly on bad
config.

**Files**:
- `config.py` — `load_config(path) -> Config`. Use stdlib `tomllib` (Py 3.11+).
  Validate required keys exist; raise with a clear message if not.
- `tests/test_config.py` — round-trip a sample, then test missing-key failure.

**Acceptance**:
- Loads the real `config.toml` from Task 0.1.
- Missing-key tests assert helpful error messages.
- `Config` exposes typed attributes for everything the rest of the code needs:
  `telegram.bot_token_env`, `telegram.allowed_chats_env`, `state.*`,
  `defaults.seniority`, `defaults.locations`.

**Spec refs**: [Subscriptions & filtering](SPEC.md#subscriptions--filtering).

**Notes**: don't read env vars in `config.py` — that's a Phase 5 concern. Just
expose the *names* of the env vars from config.

---

## Phase 1 — First vertical slice

Goal of this phase: prove the architecture end-to-end with one scraper, one
filter, and stdout output. No state, no Telegram yet. **This is the most
important phase** — finishing it confirms the design works.

### Task 1.1 — Filter module + tests

**Goal**: pure-function filter that takes a `Job` + `Profile` + defaults and
returns bool; comprehensive unit tests.

**Files**:
- `filters.py` — `match_job(job, profile, defaults) -> bool`. Implements
  keyword (substring, case + diacritics insensitive), seniority (with the
  "missing data → keep" rule and the implicit-reject for senior/lead/etc.),
  location clauses (`city+modes` and `country+modes`).
- `tests/test_filters.py` — at least: keyword positive/negative, diacritics
  case (`Kraków` ≡ `Krakow`), seniority missing kept, seniority senior
  rejected, location city match, location country-remote match.

**Acceptance**:
- All tests pass.
- `match_job` is pure (no I/O, no globals). Easy to fuzz later.

**Spec refs**: [Matching rules](SPEC.md#matching-rules).

**Notes**: use `unicodedata.normalize('NFKD', s)` + filter combining marks for
diacritics insensitivity. ~3 lines.

---

### Task 1.2 — justjoin.it fixture capture

**Goal**: save real API responses as test fixtures so scraper tests are
hermetic.

**Files**:
- `tests/fixtures/justjoin_listings.json` — raw API response captured manually
  (curl + save), or via a one-shot script in `scripts/capture_fixtures.py`.
- `tests/fixtures/README.md` — when this was captured, how to refresh it.

**Acceptance**:
- Fixture file exists, is valid JSON, contains at least 5 design listings.
- A short note in the fixtures README explains how to refresh.

**Spec refs**: [Job sources](SPEC.md#job-sources).

**Notes**: do NOT commit secrets if the API requires any (it shouldn't for
listing pages). Inspect the file before committing.

---

### Task 1.3 — justjoin.it scraper

**Goal**: `scrapers/justjoin.py` exposing `fetch() -> list[Job]`, fully tested
against the fixture.

**Files**:
- `scrapers/justjoin.py` — `fetch()`, internal helpers to map API response to
  `Job`. Stable `id = "justjoin.it:" + slug-or-hash`.
- `scrapers/__init__.py` — register `justjoin.fetch` in a `SCRAPERS` list.
- `tests/test_justjoin.py` — load fixture, parse it, assert N jobs returned
  with expected fields populated.

**Acceptance**:
- `pytest tests/test_justjoin.py` passes against the fixture.
- A live invocation (e.g. `python -c "from scrapers.justjoin import fetch; print(len(fetch()))"`)
  returns >0 jobs against the real site.
- Job IDs are stable (run twice, same IDs).

**Spec refs**: [Job sources](SPEC.md#job-sources), [Job model](SPEC.md#job-model).

**Notes**: send a realistic User-Agent header. Use `httpx.Client` with a 10s
timeout.

---

### Task 1.4 — Minimal `main.py` (dry-run mode)

**Goal**: orchestrator that loads config, runs all registered scrapers,
filters against a hardcoded test profile, and prints matches to stdout. No
state, no Telegram.

**Files**:
- `main.py` — `main()` function. Hardcoded test profile inline (`ui-ux` keywords).
- A CLI flag `--dry-run` that's the default for now.

**Acceptance**:
- `python -m main --dry-run` runs end-to-end, prints a list of matched jobs.
- Logs each step (loaded config, fetching X, filtered N → M).
- Doesn't touch the network if a `--from-fixtures` flag is added (optional but
  helpful).

**Spec refs**: [Architecture](SPEC.md#architecture).

**Milestone**: at this point you have a working pipeline. Everything else is
adding capabilities.

---

## Phase 2 — State

Persist what we've seen and which subscriptions exist. Still no Telegram.

### Task 2.1 — State module

**Goal**: `state.py` reads/writes all four state files with per-user keying
and FIFO trim.

**Files**:
- `state.py` — `load_subscriptions(path) -> dict[str, list[Profile]]`,
  `save_subscriptions(...)`, ditto for `seen_jobs` (with 5000-FIFO trim per
  user), `load_offset / save_offset`, `load_failure_counts / save_failure_counts`.
- `tests/test_state.py` — round-trip each file, verify trim, verify "missing
  user gets empty" behavior.

**Acceptance**:
- All round-trips lossless.
- Trim leaves the *most recent* 5000, not the first 5000.
- Missing files are treated as empty (don't crash on first run).

**Spec refs**: [State storage — the `state` branch](SPEC.md#state-storage--the-state-branch).

---

### Task 2.2 — Wire state into `main.py`

**Goal**: real-run mode that uses subscriptions + dedup. Keep `--dry-run` as a
debugging escape hatch.

**Files**:
- `main.py` — load subscriptions and seen-sets from `.state/` (path from
  config). For each allowed user, filter against their profiles, dedup against
  their seen-set, *would-send* to stdout, append to seen-set, save.
- Add `--state-dir` CLI flag (default `.state/`).

**Acceptance**:
- Run twice with the same fixture: first run prints jobs, second run prints
  nothing (all seen).
- Manually editing `subscriptions.json` and re-running picks up the change.

**Spec refs**: [Subscriptions & filtering](SPEC.md#subscriptions--filtering),
[State storage — the `state` branch](SPEC.md#state-storage--the-state-branch).

---

## Phase 3 — Telegram delivery

### Task 3.1 — Low-level Telegram wrapper

**Goal**: `telegram.py` exposing `send_message(chat_id, text, parse_mode)` with
429/retry handling.

**Files**:
- `telegram.py` — `class TelegramClient` (or module-level functions) wrapping
  `httpx`. Handles 429 with `retry_after`. Sleeps 1–2s between sends.
- `tests/test_telegram.py` — mock `httpx`, verify URL/payload, verify 429
  causes a retry.

**Acceptance**:
- Tests pass with mocked HTTP.
- Manual smoke test: `python -c "from telegram import send_message; send_message(MY_CHAT_ID, 'hi')"`
  delivers a message (requires real token in env).

**Spec refs**: [Telegram delivery](SPEC.md#telegram-delivery).

---

### Task 3.2 — Wire `send_job` into `main.py`

**Goal**: replace stdout prints with real Telegram sends; per-user 30-msg cap.

**Files**:
- `telegram.py` (extend) — `format_job(job, profile) -> str` returning the
  spec'd Markdown.
- `main.py` — when sending, route to the user's chat ID, enforce per-user cap
  (excess gets marked-seen anyway so we don't re-send next tick).

**Acceptance**:
- Real run delivers messages to your own chat.
- Per-user cap honored (test by temporarily lowering to 2).
- Capped messages still added to seen-set.

**Spec refs**: [Telegram delivery](SPEC.md#telegram-delivery).

---

## Phase 4 — Bot interaction

### Task 4.1 — Command parser (pure)

**Goal**: parse a Telegram update payload into `Command(name, args, chat_id)`
or `None`. Pure function, no I/O.

**Files**:
- `bot.py` — `parse_command(update: dict) -> Command | None`. Recognises
  `/start`, `/help`, `/list`, `/subscribe`, `/unsubscribe`, `/whoami`.
- `tests/test_bot_parser.py` — fixtures of real Telegram update JSON; verify
  each command parses, garbage returns None or `Command("unknown", ...)`.

**Acceptance**:
- All commands parse correctly including args with commas/spaces.
- Non-command messages return None.
- Tests cover the edge cases (empty subscribe, multi-word names, etc.).

**Spec refs**: [Bot interaction → Commands](SPEC.md#commands).

---

### Task 4.2 — Bot loop + handlers

**Goal**: `bot.py` exposes `tick(state, allowed_chats)` that polls `getUpdates`,
processes commands, mutates state, replies via `telegram.py`.

**Files**:
- `bot.py` (extend) — `tick()` function. Auth gate (allowlist check). Each
  command's handler. Updates `tg_offset.txt` after processing.
- `tests/test_bot_handlers.py` — mock `getUpdates` + `send_message`, verify
  state mutations and replies for each command, verify auth gate.

**Acceptance**:
- All command handlers tested against mocked Telegram.
- Non-allowlisted user gets the chat-ID hint reply only.
- Offset advances correctly even when no commands are recognised.

**Spec refs**: [Bot interaction](SPEC.md#bot-interaction),
[Auth model](SPEC.md#auth-model).

---

### Task 4.3 — Wire bot tick into `main.py`

**Goal**: `main.py` runs `bot.tick()` before the scrape loop.

**Files**:
- `main.py` — bot tick → scrape → filter → send. Bot tick errors are logged
  and don't stop the scrape (and vice versa).

**Acceptance**:
- Live test: `/subscribe ui-ux UX Designer` from your chat → on next run,
  `subscriptions.json` has your profile and matching jobs are delivered.
- `/list` → bot replies with your profiles.
- `/unsubscribe` → profile removed.

**Spec refs**: [Bot interaction](SPEC.md#bot-interaction).

---

## Phase 5 — GitHub Actions

### Task 5.1 — Scrape workflow

**Goal**: `.github/workflows/scrape.yml` runs end-to-end in Actions, including
the two-checkout state branch dance.

**Files**:
- `.github/workflows/scrape.yml` — exactly the steps from the Scheduling
  section of the spec.

**Acceptance**:
- Manual `workflow_dispatch` run succeeds.
- After running, `state` branch shows a commit (if anything changed) or no new
  commit (if nothing changed).
- A second `workflow_dispatch` immediately after produces no commit
  (everything already seen).

**Spec refs**: [Scheduling — GitHub Actions](SPEC.md#scheduling--github-actions).

**Notes**: don't enable cron until the manual run is green.

---

### Task 5.2 — Repo setup checklist (docs)

**Goal**: a runnable checklist so future-you (or your wife) can recover from a
clean clone.

**Files**:
- `README.md` — append a "Setup" section with:
  1. How to create the orphan `state` branch
     (`git checkout --orphan state && git rm -rf . && touch subscriptions.json seen_jobs.json tg_offset.txt failure_counts.json && echo '{}' > subscriptions.json && ...`).
  2. Required repo secrets and how to add them.
  3. How to onboard a new user (chat-ID dance).

**Acceptance**:
- A fresh clone + following README results in a working bot.

**Spec refs**: [State storage — the `state` branch](SPEC.md#state-storage--the-state-branch),
[Auth model](SPEC.md#auth-model).

---

## Phase 6 — Remaining scrapers (parallelisable)

Each scraper follows the same recipe as Task 1.2/1.3: capture fixture →
implement → register → test. Tasks are independent and can be done in any
order or in parallel sessions.

### Task 6.1 — nofluffjobs.com (JSON API)
**Files**: `scrapers/nofluffjobs.py`, fixture, test.
**Spec refs**: row in [Job sources](SPEC.md#job-sources).

### Task 6.2 — bulldogjob.pl (JSON API)
**Files**: `scrapers/bulldogjob.py`, fixture, test.

### Task 6.3 — theprotocol.it (Next.js `__NEXT_DATA__`)
**Files**: `scrapers/theprotocol.py`, fixture, test.
**Notes**: parse `__NEXT_DATA__` script tag JSON; selectolax for the extraction.

### Task 6.4 — pracuj.pl (HTML)
**Files**: `scrapers/pracuj.py`, fixture, test.
**Notes**: most fragile. Set realistic User-Agent. Acceptable to ship even if
coverage is partial — log warnings on unparseable cards rather than crashing.

**Acceptance (each)**: same shape as Task 1.3 — tests pass against fixture,
live call returns >0 jobs, IDs stable across runs.

---

## Phase 7 — Resilience

### Task 7.1 — Per-source try/except + failure counters

**Goal**: one broken source can never kill the run. Counters tracked in
`failure_counts.json`.

**Files**:
- `main.py` — wrap each scraper call in try/except; success resets that
  source's counter, failure increments.
- `state.py` (extend if needed) — already has counter helpers from Task 2.1.

**Acceptance**:
- Force one scraper to raise; verify other scrapers still run, counter
  increments, `state` branch shows the updated `failure_counts.json`.

**Spec refs**: [Failure modes & mitigations](SPEC.md#failure-modes--mitigations).

---

### Task 7.2 — GitHub Issue alerts

**Goal**: when a source hits 3 consecutive failures, open a GH Issue; close it
on recovery.

**Files**:
- `main.py` (or new `alerts.py`) — uses the `gh` CLI via subprocess. Skips
  silently if `gh` is not on PATH (so local runs don't try).
- Workflow yml gets `issues: write`.

**Acceptance**:
- Force 3 consecutive failures of one source in Actions; an issue appears.
- Recover the source; on the next run the issue is closed with a comment.
- No duplicate issues if one is already open.

**Spec refs**: [Failure alerts (GitHub Issues)](SPEC.md#failure-alerts-github-issues).

---

## Phase 8 — Monthly orphan workflow

### Task 8.1 — `state-orphan.yml`

**Goal**: monthly workflow that re-orphans the `state` branch.

**Files**:
- `.github/workflows/state-orphan.yml` — the steps from the spec.
- Same `state-write` concurrency group as `scrape.yml`.

**Acceptance**:
- Manual `workflow_dispatch` run succeeds.
- After it runs, `git log state` shows exactly one commit.
- File contents are identical before and after.

**Spec refs**: [`state-orphan.yml`](SPEC.md#githubworkflowsstate-orphanyml-monthly).

---

## Recommended order summary

1. **Phase 0** in order (skeleton → models → config).
2. **Phase 1** in order — gives you a working dry-run pipeline.
3. **Phase 2** in order — adds persistence.
4. **Phase 3** then **Phase 4** in order — adds Telegram and the bot.
5. **Phase 5.1** — get Actions green with `workflow_dispatch` (don't enable
   cron yet).
6. **Phase 6** — add the other 4 scrapers in any order. Could be done before
   Phase 5 if you want more coverage in the first deploy.
7. **Phase 7** — resilience hardening.
8. **Enable cron** in `scrape.yml`.
9. **Phase 8** — monthly orphan, last because it's standalone and rarely runs.

After each phase, do an end-to-end smoke test before moving on.
