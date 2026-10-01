# xfeeds

## Automatic alerts (every 30 minutes)

`.github/workflows/cls-watch.yml` runs `watch_cls.py` on GitHub Actions every 30 minutes. It reads the CLS roll API, keeps posts that are new since the last run and match the keyword lists in `KEYWORDS` (AI, CHIPS, InP, PHOTONICS, LITHO), and opens one GitHub issue per run with the matches. The issue is labelled `cls-alert` and assigned to the repo owner, so GitHub emails it to you. Runs with no new matches open nothing.

- Edit `KEYWORDS` in `watch_cls.py` to change what counts as a match.
- The last-seen position is kept in the Actions cache; if it is lost, the next run looks back 60 minutes.
- Run it by hand from the Actions tab ("CLS Telegraph watch" → Run workflow).
- GitHub may start scheduled runs a few minutes late, and disables schedules after 60 days without repo activity.

## Manual tools

Tools for watching the CLS Telegraph (财联社电报) feed for AI, chips, indium phosphide, photonics and lithography news.

- `fetch_cls.py`: the original script. It calls the CLS roll API directly. In sandboxes that block www.cls.cn it fails with a proxy 403.
- `sign_url.py`: builds signed CLS API URLs (`python3 sign_url.py <unix_time|now> [rows]`). The `category` parameter must be left out entirely; sending it empty gives errno 10012 (签名错误). These URLs can be read with a web-fetch tool when direct connections are blocked.
- `merge.py`: merges the per-time-slice results and checks the pages overlap with no gaps.
- `build.py`: renders the report and the `sent_alerts.md` log (expects `entries_*.py` with the written-up posts).
- `instructions/`: the step-by-step instructions given to the collection and verification passes.

Limits: the feed only goes back a few days through this API, and it does not include CLS paid-column content.
