# xfeeds

## Automatic alerts (every 30 minutes)

`watch.py`, run by `.github/workflows/cls-watch.yml`, checks every source below every 30 minutes and emails what matters for the AI trade and its supply chain (AI, semiconductors, photonics and optics, robotics, datacenter power and infrastructure, upstream materials), translated into English. Each check with relevant news opens one GitHub issue labelled `cls-alert` and assigned to the repo owner, so GitHub emails it: China first, then US, then other regions, each grouped by category, with the source and item type (News, Filing, Insider, Transcript, Video, Policy) on every entry.

**Sources** (`sources.py`; run `python3 sources.py --details` or the "Source probe" workflow for a health check):

| Kind | Sources |
|---|---|
| News flashes | CLS Telegraph, EastMoney 7x24, Tonghuashun 7x24, Xueqiu live news, Wallstreetcn, Sina 7x24, Yicai, 36Kr |
| Long-form news | Caixin, Caixin Global, Caijing |
| Exchange filings | Shanghai/Shenzhen/Beijing filings (via EastMoney, PDFs read, incl. investor-meeting records 投资者关系活动记录表), HKEXnews (PDFs read) |
| US filings | SEC EDGAR 8-K, 6-K, 10-Q, 10-K, 20-F, S-1/F-1, 13D, and Form 4 insider trades (parsed: who, buy/sell, shares, price, 10b5-1) |
| Government | MOFCOM, MIIT, China Customs (English), US Federal Register (BIS export controls, USTR, ITA, OFAC) |
| Video and calls | ~27 YouTube channels (business TV, chip companies, AI/semis podcasts; title and description only), Motley Fool earnings-call transcripts |

Not covered: SGX (blocks GitHub's servers), YouTube transcripts (YouTube blocks transcript downloads from GitHub's servers), Xueqiu user posts (only its live news feed).

**How it works:** each check pulls everything new from every source; Claude Haiku 4.5 first reads only the titles (`prompts/triage.md`) and picks what is relevant, dropping duplicates of the same story across sources and of stories already sent in the last 12 hours; the picks' full text is fetched (articles, PDFs, SEC documents, transcripts) and Claude writes the English entries (`prompts/write.md`). The relevance rules shared by both steps are in `prompts/relevance.md`, in plain English; edit them to widen or narrow the filter. A source that fails is skipped for that check and listed at the bottom of the email.

- **Setup:** repository secret `ANTHROPIC_API_KEY`. Optional repository variable `SEC_USER_AGENT` (your name and email, which the SEC asks for), e.g. `Jane Doe jane@example.com`.
- **Keeping it running:** GitHub drops many scheduled runs, so each run stays alive for about 5h40m, checks every 30 minutes, then starts its own next run, with an hourly schedule as a backup. To (re)start it by hand: Actions → CLS Telegraph watch → Run workflow with `watch_loop` ticked.
- **Testing:** run the workflow with `lookback_hours` (e.g. 2) to process everything from the last N hours across all sources, even if already sent.
- **Past dates (CLS only):** fill in `from_date` / `to_date` (Beijing dates, YYYY-MM-DD) to process a past range, one issue per day; tick `dry_run` first to see, at no cost, how far back the feed reaches.
- Positions and recently sent headlines are kept in the Actions cache. If a check fails, the same items are retried at the next check, and GitHub emails about the failed run when it ends.
- GitHub disables schedules after 60 days without repo activity; re-enable it from the Actions tab if that happens.

## Manual tools

Tools for watching the CLS Telegraph (财联社电报) feed for AI, chips, indium phosphide, photonics and lithography news.

- `fetch_cls.py`: the original script. It calls the CLS roll API directly. In sandboxes that block www.cls.cn it fails with a proxy 403.
- `sign_url.py`: builds signed CLS API URLs (`python3 sign_url.py <unix_time|now> [rows]`). The `category` parameter must be left out entirely; sending it empty gives errno 10012 (签名错误). These URLs can be read with a web-fetch tool when direct connections are blocked.
- `merge.py`: merges the per-time-slice results and checks the pages overlap with no gaps.
- `build.py`: renders the report and the `sent_alerts.md` log (expects `entries_*.py` with the written-up posts).
- `instructions/`: the step-by-step instructions given to the collection and verification passes.

Limits: the feed only goes back a few days through this API, and it does not include CLS paid-column content.
