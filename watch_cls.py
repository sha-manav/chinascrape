"""Check the CLS Telegraph feed for new posts since the last run, have Claude pick out the
ones relevant to the AI trade and its supply chain, and translate them into English.

Run every 30 minutes by .github/workflows/cls-watch.yml. Writes issue_title.txt and
issue_body_N.md when there are relevant posts, and keeps its place in STATE_FILE.
The relevance rules and translation instructions are in filter_prompt.md.
"""
import json, os, re, sys, time, urllib.error, urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from pathlib import Path
import anthropic
from sign_url import url

BJ = timezone(timedelta(hours=8))
HERE = Path(__file__).parent
STATE_FILE = os.environ.get("STATE_FILE", "state/cls_state.json")
FIRST_RUN_LOOKBACK = int(os.environ.get("FIRST_RUN_LOOKBACK_MIN", "60")) * 60
OVERLAP = 15 * 60          # re-read this much before the last run, in case posts land late
SEEN_TTL = 2 * 24 * 3600   # how long to remember ids already handled
MAX_PAGES = 30
INTERVAL = 30 * 60        # seconds between checks in loop mode
BATCH = 60                 # posts per Claude request
BODY_LIMIT = 60000         # GitHub issue bodies max out at 65536 characters

MODEL = "claude-haiku-4-5"   # cheapest Claude model; ~$1/$5 per million input/output tokens
REGIONS = ["China", "US", "Other regions"]   # email order
CATEGORIES = ["AI", "Semiconductors", "Photonics & Optics", "Robotics", "Power & Datacenter Infrastructure",
              "Materials & Supply Chain"]
SCHEMA = {
    "type": "object",
    "properties": {"posts": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "id": {"type": "integer"},
            "region": {"type": "string", "enum": REGIONS},
            "category": {"type": "string", "enum": CATEGORIES},
            "importance": {"type": "string", "enum": ["High", "Medium", "Low"]},
            "headline_en": {"type": "string"},
            "translation_en": {"type": "string"},
            "companies": {"type": "string"},
        },
        "required": ["id", "region", "category", "importance", "headline_en", "translation_en", "companies"],
        "additionalProperties": False,
    }}},
    "required": ["posts"],
    "additionalProperties": False,
}


def fetch_page(cursor, rn=50):
    req = urllib.request.Request(url(cursor, rn), headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0 Safari/537.36",
        "Referer": "https://www.cls.cn/telegraph"})
    for attempt in range(4):
        try:
            data = json.load(urllib.request.urlopen(req, timeout=20))
            if data.get("errno") not in (0, None):
                raise RuntimeError(f"CLS API errno {data.get('errno')}: {data.get('msg') or data.get('error')}")
            return data["data"]["roll_data"]
        except Exception as e:
            if attempt == 3:
                raise
            print(f"fetch failed ({e}), retrying", file=sys.stderr)
            time.sleep(5 * (attempt + 1))


def fetch_since(since, until=None, max_pages=MAX_PAGES):
    """All posts with since <= ctime < until (default: now), paging backwards from until."""
    until = until or int(time.time()) + 1
    posts, cursor = {}, until
    for _ in range(max_pages):
        rows = fetch_page(cursor)
        for r in rows:
            posts[r["id"]] = r
        oldest = min((r["ctime"] for r in rows), default=cursor)
        if not rows or oldest >= cursor or oldest < since:
            break
        cursor = oldest
        time.sleep(1)
    return [p for p in posts.values() if since <= p["ctime"] < until]


def fmt_time(ct):
    return datetime.fromtimestamp(ct, BJ).strftime("%Y-%m-%d %H:%M")


def screen(client, system, batch):
    """Ask Claude which posts in the batch are relevant; returns their English write-ups."""
    payload = [{"id": p["id"], "time": fmt_time(p["ctime"]), "title": (p.get("title") or "").strip(),
                "content": (p.get("content") or p.get("brief") or "").strip()} for p in batch]
    with client.messages.stream(
        model=MODEL,
        max_tokens=32000,
        system=system,
        output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
    ) as stream:
        msg = stream.get_final_message()
    if msg.stop_reason != "end_turn":
        raise RuntimeError(f"Claude stopped with {msg.stop_reason}: {msg.stop_details}")
    text = next(b.text for b in msg.content if b.type == "text")
    ids = {p["id"] for p in batch}
    return [r for r in json.loads(text)["posts"] if r["id"] in ids]


def render(results, posts):
    """Issue bodies grouped by region (China first), then category, split to fit GitHub's size limit."""
    blocks = []
    for region in REGIONS:
        in_region = [r for r in results if r["region"] == region]
        if in_region:
            blocks.append(f"# {region} ({len(in_region)})\n")
        for cat in CATEGORIES:
            items = sorted((r for r in in_region if r["category"] == cat), key=lambda r: posts[r["id"]]["ctime"], reverse=True)
            if items:
                blocks.append(f"## {cat} ({len(items)})\n")
            for r in items:
                p = posts[r["id"]]
                link = p.get("shareurl") or f"https://www.cls.cn/detail/{p['id']}"
                meta = " · ".join(x for x in (f"Importance: {r['importance']}", r["companies"].strip(), f"[Source]({link})") if x)
                text = r["translation_en"].strip().replace("\n", "  \n")
                blocks.append(f"**[{fmt_time(p['ctime'])[5:]} Beijing] {r['headline_en'].strip()}**  \n{text}  \n_{meta}_\n")
    bodies, cur = [], ""
    for b in blocks:
        if cur and len(cur) + len(b) > BODY_LIMIT:
            bodies.append(cur)
            cur = ""
        cur += b + "\n"
    return bodies + [cur] if cur else bodies


def day_start(date):
    """Unix time of 00:00 Beijing on a YYYY-MM-DD date."""
    return int(datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=BJ).timestamp())


def write_issues(groups):
    """groups: [(title, results, posts_by_id)]. Writes issue_NNN.title / issue_NNN.md pairs."""
    for f in [*Path().glob("issue_*.md"), *Path().glob("issue_*.title")]:
        f.unlink()
    n = 0
    for title, results, by_id in groups:
        bodies = render(results, by_id)
        for i, body in enumerate(bodies, 1):
            n += 1
            part = f" [part {i}/{len(bodies)}]" if len(bodies) > 1 else ""
            open(f"issue_{n:03d}.title", "w", encoding="utf-8").write(title + part)
            open(f"issue_{n:03d}.md", "w", encoding="utf-8").write(body)
    return n


def summary_title(results, by_id, label=None):
    times = sorted(by_id[r["id"]]["ctime"] for r in results)
    lo, hi = fmt_time(times[0]), fmt_time(times[-1])
    n_high = sum(r["importance"] == "High" for r in results)
    when = label or f"{lo[5:]} – {hi[11:] if lo[:10] == hi[:10] else hi[5:]} Beijing"
    return (f"CLS: {len(results)} AI/semis/supply-chain update{'s' if len(results) != 1 else ''}"
            + (f", {n_high} high" if n_high else "") + f" ({when})")


def screen_all(posts):
    if not posts:
        return []
    client = anthropic.Anthropic()
    system = (HERE / "filter_prompt.md").read_text(encoding="utf-8")
    batches = [posts[i:i + BATCH] for i in range(0, len(posts), BATCH)]
    with ThreadPoolExecutor(4) as pool:
        return [r for rs in pool.map(lambda b: screen(client, system, b), batches) for r in rs]


def backfill(date_from, date_to, dry_run):
    """Process a past date range (Beijing dates, inclusive), one issue per day. Leaves the watch state alone."""
    start, end = day_start(date_from), day_start(date_to) + 86400
    posts = sorted(fetch_since(start, end, max_pages=600), key=lambda p: p["ctime"])
    days = {}
    for p in posts:
        days.setdefault(fmt_time(p["ctime"])[:10], []).append(p)
    print(f"backfill {date_from} to {date_to}: {len(posts)} posts fetched")
    for d, ps in sorted(days.items()):
        print(f"  {d}: {len(ps)} posts ({fmt_time(ps[0]['ctime'])[11:]}–{fmt_time(ps[-1]['ctime'])[11:]})")
    if posts and posts[0]["ctime"] > start + 3600:
        print(f"WARNING: the feed only reached back to {fmt_time(posts[0]['ctime'])} Beijing")
    if dry_run:
        print("dry run: Claude not called, no issues opened")
        return 0
    by_id = {p["id"]: p for p in posts}
    results = screen_all(posts)
    groups = []
    for d in sorted(days):
        rs = [r for r in results if fmt_time(by_id[r["id"]]["ctime"])[:10] == d]
        if rs:
            groups.append((summary_title(rs, by_id, f"{d} Beijing"), rs, by_id))
    print(f"{len(results)} relevant posts across {len(groups)} days")
    return write_issues(groups)


def publish():
    """Open a GitHub issue for each issue_NNN.md written by this run (skipped outside Actions)."""
    files = sorted(Path().glob("issue_*.md"))
    token, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    if not files or not (token and repo):
        return
    def call(path, data):
        api = os.environ.get("GITHUB_API_URL", "https://api.github.com")
        req = urllib.request.Request(f"{api}/repos/{repo}/{path}", json.dumps(data).encode(), {
            "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"})
        return json.load(urllib.request.urlopen(req, timeout=30))
    try:
        call("labels", {"name": "cls-alert", "color": "1d76db", "description": "CLS Telegraph watch"})
    except urllib.error.HTTPError:
        pass  # already exists
    owner = repo.split("/")[0]
    for f in files:
        title = f.with_suffix(".title").read_text(encoding="utf-8")
        issue = call("issues", {"title": title, "body": f.read_text(encoding="utf-8"),
                                "labels": ["cls-alert"], "assignees": [owner]})
        print("opened", issue["html_url"])
        f.unlink()
        f.with_suffix(".title").unlink()


def loop(minutes):
    """Check every INTERVAL seconds until the time budget runs out. GitHub's scheduler drops many
    runs, so one long job does the 30-minute checks itself and the hourly schedule just restarts it."""
    deadline, failed = time.time() + minutes * 60, False
    while True:
        started = time.time()
        try:
            watch()
            publish()
        except Exception as e:  # keep looping; the posts are retried next check
            failed = True
            print(f"check failed: {e!r}", file=sys.stderr)
        wake = started + INTERVAL
        if wake > deadline:
            break
        time.sleep(max(0, wake - time.time()))
    if failed:
        sys.exit("at least one check failed; see the log above")


def main():
    if os.environ.get("FROM_DATE"):
        backfill(os.environ["FROM_DATE"], os.environ.get("TO_DATE") or os.environ["FROM_DATE"],
                 os.environ.get("DRY_RUN", "").lower() == "true")
        publish()
    elif minutes := float(os.environ.get("LOOP_MINUTES") or 0):
        loop(minutes)
    else:
        watch()
        publish()


def watch():
    now = int(time.time())
    try:
        state = json.load(open(STATE_FILE, encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        state = {}
    seen = {int(k): v for k, v in state.get("seen", {}).items()}
    since = state["last_ctime"] - OVERLAP if "last_ctime" in state else now - FIRST_RUN_LOOKBACK
    if force := float(os.environ.get("LOOKBACK_HOURS") or 0):
        # manual test run: report everything in the last N hours, even if already reported
        since, seen = now - int(force * 3600), {}

    posts = fetch_since(since)
    new = sorted((p for p in posts if p["id"] not in seen), key=lambda p: p["ctime"])
    results = screen_all(new)
    print(f"window from {fmt_time(since)} Beijing: {len(posts)} posts, {len(new)} new, {len(results)} relevant")
    by_id = {p["id"]: p for p in new}
    n = write_issues([(summary_title(results, by_id), results, by_id)] if results else [])

    for p in new:
        seen[p["id"]] = p["ctime"]
    state = {"last_ctime": max([state.get("last_ctime", since)] + [p["ctime"] for p in posts]),
             "seen": {str(k): v for k, v in seen.items() if v >= now - SEEN_TTL}}
    os.makedirs(os.path.dirname(STATE_FILE) or ".", exist_ok=True)
    json.dump(state, open(STATE_FILE, "w", encoding="utf-8"))
    return n


if __name__ == "__main__":
    main()
