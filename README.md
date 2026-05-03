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
