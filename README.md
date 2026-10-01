# xfeeds

## Automatic alerts (every 30 minutes)

`.github/workflows/cls-watch.yml` runs `watch_cls.py` on GitHub Actions every 30 minutes. GitHub drops many scheduled runs, so each scheduled run stays alive for about 5h40m and does the 30-minute checks itself; the hourly schedule only needs to fire occasionally to start the next one. It pulls every CLS Telegraph post since the last run and sends them to Claude Haiku 4.5 (`claude-haiku-4-5`, the cheapest Claude model, roughly $0.0007 per post or about $0.30 a day), which keeps the ones relevant to the AI trade and its supply chain (AI, semiconductors, photonics and optics, robotics, datacenter power and infrastructure, and upstream materials) and translates them into English. The email lists China news first, then US news, then other regions, each grouped by category. Each run with relevant posts opens one GitHub issue labelled `cls-alert` and assigned to the repo owner, so GitHub emails it. Runs with nothing relevant open nothing.

- **Setup:** add an Anthropic API key as a repository secret named `ANTHROPIC_API_KEY` (Settings → Secrets and variables → Actions).
- **What counts as relevant** is written in plain English in `filter_prompt.md`; edit it to widen or narrow the filter.
- The last-seen position is kept in the Actions cache. If it is lost, the next run looks back 60 minutes. If Claude or CLS fails, the run fails (GitHub emails you) and the same posts are retried next run.
- Run it by hand from the Actions tab ("CLS Telegraph watch" → Run workflow). To test, enter a number in "lookback_hours" (e.g. 24) to process every post from that many hours back, even ones already sent. Very long digests are split into several issues.
- **Past dates:** fill in `from_date` / `to_date` (Beijing dates, YYYY-MM-DD) when running by hand to process a past range, with one issue per day. Tick `dry_run` first to see, at no cost, how far back the CLS feed actually reaches. Backfills don't affect the 30-minute watch.
- GitHub disables schedules after 60 days without repo activity; re-enable it from the Actions tab if that happens.

## Manual tools

Tools for watching the CLS Telegraph (财联社电报) feed for AI, chips, indium phosphide, photonics and lithography news.

- `fetch_cls.py`: the original script. It calls the CLS roll API directly. In sandboxes that block www.cls.cn it fails with a proxy 403.
- `sign_url.py`: builds signed CLS API URLs (`python3 sign_url.py <unix_time|now> [rows]`). The `category` parameter must be left out entirely; sending it empty gives errno 10012 (签名错误). These URLs can be read with a web-fetch tool when direct connections are blocked.
- `merge.py`: merges the per-time-slice results and checks the pages overlap with no gaps.
- `build.py`: renders the report and the `sent_alerts.md` log (expects `entries_*.py` with the written-up posts).
- `instructions/`: the step-by-step instructions given to the collection and verification passes.

Limits: the feed only goes back a few days through this API, and it does not include CLS paid-column content.
