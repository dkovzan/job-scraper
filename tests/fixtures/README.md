# Test fixtures

Captured snapshots of real upstream API responses, used to keep scraper tests
hermetic. Don't edit by hand — re-capture if a site's response shape changes.

## Files

| File                       | Source endpoint                                                                          |
| -------------------------- | ---------------------------------------------------------------------------------------- |
| `justjoin_listings.json`   | `GET https://api.justjoin.it/v2/user-panel/offers?categories[]=14&itemsPerPage=20&page=1` |

`categories[]=14` filters to the design category (UI/UX, product, graphic, etc.).

## Refresh

```sh
python scripts/capture_fixtures.py
```

Inspect the diff before committing. If the JSON shape has shifted (renamed
keys, removed fields), update the matching scraper module to keep tests
passing.

Last captured: 2026-05-03.
