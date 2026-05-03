# Test fixtures

Captured snapshots of real upstream API responses, used to keep scraper tests
hermetic. Don't edit by hand — re-capture if a site's response shape changes.

## Files

| File                          | Source                                                                                   | Client     |
| ----------------------------- | ---------------------------------------------------------------------------------------- | ---------- |
| `justjoin_listings.json`      | `GET https://api.justjoin.it/v2/user-panel/offers?categories[]=14&itemsPerPage=20&page=1` | `httpx`    |
| `nofluffjobs_design.html`     | `GET https://nofluffjobs.com/pl/design`                                                  | `httpx`    |
| `bulldogjob_design.html`      | `GET https://bulldogjob.pl/companies/jobs/s/specialization,Design`                       | `httpx`    |
| `theprotocol_design.html`     | `GET https://theprotocol.it/filtry/ux-ui;sp/praca`                                       | `curl_cffi` |
| `pracuj_design.html`          | `GET https://it.pracuj.pl/praca/ux%20designer`                                           | `curl_cffi` |

`categories[]=14` on justjoin filters to the design category (UI/UX, product,
graphic, etc.). Bulldogjob's listings endpoint *ignores* the specialization
filter, so the fixture has the parser-shape we need but the actual jobs
inside are dev-heavy. The runtime scraper hits `/s/role,Designer` which
filters correctly but currently returns zero matches.

`theprotocol.it` and `pracuj.pl` are both fronted by Cloudflare's
"Just a moment…" challenge. Plain `httpx` gets a 403; `curl_cffi` sends the
request with a real Chrome's TLS fingerprint and clears the challenge.

## Refresh

```sh
python scripts/capture_fixtures.py            # all live captures
python scripts/capture_fixtures.py justjoin   # one source
```

Inspect the diff before committing. If the upstream shape has shifted
(renamed keys, removed fields), update the matching scraper module to keep
tests passing.

Last captured: 2026-05-03.
