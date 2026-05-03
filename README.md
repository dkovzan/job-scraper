# state branch

Holds the bot's mutable state: per-user subscriptions, per-user seen-job sets,
the Telegram update_id cursor, and per-source failure counters. Code lives on
`main` and reads/writes this branch via `actions/checkout` into `.state/` at
workflow time. Do not merge into `main`.
