# xfeeds

Tools for watching the CLS Telegraph (财联社电报) feed for AI, chips, indium phosphide, photonics and lithography news.

- `fetch_cls.py`: the original script. It calls the CLS roll API directly. In sandboxes that block www.cls.cn it fails with a proxy 403.
- `sign_url.py`: builds signed CLS API URLs (`python3 sign_url.py <unix_time|now> [rows]`). The `category` parameter must be left out entirely; sending it empty gives errno 10012 (签名错误). These URLs can be read with a web-fetch tool when direct connections are blocked.
- `merge.py`: merges the per-time-slice results and checks the pages overlap with no gaps.
- `build.py`: renders the report and the `sent_alerts.md` log (expects `entries_*.py` with the written-up posts).
- `instructions/`: the step-by-step instructions given to the collection and verification passes.

Limits: the feed only goes back a few days through this API, and it does not include CLS paid-column content.
