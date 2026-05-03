# job-scraper

Scrapes Polish job boards (justjoin.it, nofluffjobs.com, bulldogjob.pl,
theprotocol.it, pracuj.pl) and notifies an allowlist of users via a Telegram
bot about new postings matching their subscriptions. Subscriptions are managed
end-to-end through the bot (`/subscribe`, `/unsubscribe`, `/list`); state lives
on a parallel `state` branch; the whole thing runs on a GitHub Actions cron.

See [SPEC.md](SPEC.md) for the full design and [impl_plan.md](impl_plan.md)
for the build plan.

## Run locally

Requires Python 3.11+.

```sh
python -m venv .venv
.venv\Scripts\activate          # PowerShell: .venv\Scripts\Activate.ps1
                                # macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

Lint / format checks:

```sh
ruff check .
ruff format --check .
```

To exercise the full pipeline locally against the live justjoin.it API and
your real chat (Telegram delivery), set `TELEGRAM_BOT_TOKEN` and
`ALLOWED_CHAT_IDS` in your shell, populate `.state/subscriptions.json` with
your chat ID, and run `python -m main`. Without those env vars the same
command exits with a clear error before doing any work.

## Setup (deploy to GitHub Actions)

Run-locally is enough for development. To run the bot on a schedule without
your laptop on, deploy to GitHub Actions:

### 1. Create the Telegram bot

1. In Telegram, message [@BotFather](https://t.me/BotFather), send `/newbot`,
   choose a name + username, save the token.
2. Get your chat ID from [@userinfobot](https://t.me/userinfobot) — send it
   `/start` and copy the number it replies with.

### 2. Create the orphan `state` branch

The bot's mutable state (subscriptions, seen jobs, Telegram offset, scraper
failure counts) lives on a parallel `state` branch — separate history from
`main`, never merged. Create it once after cloning, with a clean working tree:

```sh
git checkout --orphan state
git rm -rf .
cat > README.md <<'EOF'
# state branch

Holds the bot's mutable state: per-user subscriptions, per-user seen-job sets,
the Telegram update_id cursor, and per-source failure counters. Code lives on
`main` and reads/writes this branch via `actions/checkout` into `.state/` at
workflow time. Do not merge into `main`.
EOF
echo '{}' > subscriptions.json
echo '{}' > seen_jobs.json
printf '0\n' > tg_offset.txt
echo '{}' > failure_counts.json
git add README.md subscriptions.json seen_jobs.json tg_offset.txt failure_counts.json
git commit -m "state: initial"
git push -u origin state
git checkout main
```

### 3. Add repo secrets

In **Settings → Secrets and variables → Actions**, add:

| Name | Value |
| ---- | ----- |
| `TELEGRAM_BOT_TOKEN` | the token from @BotFather |
| `ALLOWED_CHAT_IDS`   | comma-separated Telegram chat IDs (your own to start) |

### 4. Trigger the first run

In the GitHub UI: **Actions → scrape → Run workflow** (`workflow_dispatch`).
Watch the log. On a successful run:

- The bot processes any queued `/subscribe` etc. commands and replies.
- The scraper fetches listings and delivers matching jobs to subscribers.
- The `state` branch grows a commit if anything changed (otherwise no-op).

The cron schedule fires twice daily at **06:00 and 14:00 UTC** (≈ 08:00 / 16:00
Polish summer time, 1h earlier in winter — GH Actions cron has no DST).

### Onboarding more users

1. The new user opens the bot in Telegram and sends any message (or
   `/whoami`). On the next tick the bot replies with their chat ID.
2. Append the chat ID to `ALLOWED_CHAT_IDS` (comma-separated) and save.
3. They can now `/subscribe <name> <kw>, <kw>, ...`. Their slot in
   `subscriptions.json` is created lazily on the first `/subscribe`.

