"""Check the CLS Telegraph feed for new posts since the last run, have Claude pick out the
ones relevant to the AI trade and its supply chain, and translate them into English.

Run every 30 minutes by .github/workflows/cls-watch.yml. Writes issue_title.txt and
issue_body_N.md when there are relevant posts, and keeps its place in STATE_FILE.
The relevance rules and translation instructions are in filter_prompt.md.
"""
import json, os, re, sys, time, urllib.request
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
BATCH = 60                 # posts per Claude request
BODY_LIMIT = 60000         # GitHub issue bodies max out at 65536 characters

MODEL = "claude-opus-5-5"
CATEGORIES = ["AI", "Semiconductors", "Photonics & Optics", "Robotics", "Power & Datacenter Infrastructure",
              "Materials & Supply Chain"]
SCHEMA = {
    "type": "object",
    "properties": {"posts": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "id": {"type": "integer"},
            "category": {"type": "string", "enum": CATEGORIES},
            "importance": {"type": "string", "enum": ["High", "Medium", "Low"]},
            "headline_en": {"type": "string"},
            "translation_en": {"type": "string"},
            "companies": {"type": "string"},
        },
        "required": ["id", "category", "importance", "headline_en", "translation_en", "companies"],
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


def fetch_since(since):
    """All posts with ctime >= since, paging backwards from now."""
    posts, cursor = {}, int(time.time())
    for _ in range(MAX_PAGES):
        rows = fetch_page(cursor)
        for r in rows:
            posts[r["id"]] = r
        oldest = min((r["ctime"] for r in rows), default=cursor)
        if not rows or oldest >= cursor or oldest < since:
            break
        cursor = oldest
        time.sleep(1)
    return [p for p in posts.values() if p["ctime"] >= since]


def fmt_time(ct):
    return datetime.fromtimestamp(ct, BJ).strftime("%Y-%m-%d %H:%M")


def screen(client, system, batch):
    """Ask Claude which posts in the batch are relevant; returns their English write-ups."""
    payload = [{"id": p["id"], "time": fmt_time(p["ctime"]), "title": (p.get("title") or "").strip(),
                "content": (p.get("content") or p.get("brief") or "").strip()} for p in batch]
    with client.beta.messages.stream(
        model=MODEL,
        max_tokens=64000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        system=system,
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
    ) as stream:
        msg = stream.get_final_message()
    if msg.stop_reason != "end_turn":
        raise RuntimeError(f"Claude stopped with {msg.stop_reason}: {msg.stop_details}")
    text = next(b.text for b in msg.content if b.type == "text")
    ids = {p["id"] for p in batch}
    return [r for r in json.loads(text)["posts"] if r["id"] in ids]


def render(results, posts):
    """Issue bodies grouped by category, split to fit GitHub's size limit."""
    blocks = []
    for cat in CATEGORIES:
        items = sorted((r for r in results if r["category"] == cat), key=lambda r: posts[r["id"]]["ctime"], reverse=True)
        if not items:
            continue
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


def main():
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
    results = []
    if new:
        client = anthropic.Anthropic()
        system = (HERE / "filter_prompt.md").read_text(encoding="utf-8")
        for i in range(0, len(new), BATCH):
            results += screen(client, system, new[i:i + BATCH])
    print(f"window from {fmt_time(since)} Beijing: {len(posts)} posts, {len(new)} new, {len(results)} relevant")

    for f in Path().glob("issue_body_*.md"):
        f.unlink()
    if results:
        by_id = {p["id"]: p for p in new}
        times = sorted(by_id[r["id"]]["ctime"] for r in results)
        lo, hi = fmt_time(times[0]), fmt_time(times[-1])
        n_high = sum(r["importance"] == "High" for r in results)
        open("issue_title.txt", "w", encoding="utf-8").write(
            f"CLS: {len(results)} AI/semis/supply-chain update{'s' if len(results) != 1 else ''}"
            + (f", {n_high} high" if n_high else "")
            + f" ({lo[5:]} – {hi[11:] if lo[:10] == hi[:10] else hi[5:]} Beijing)")
        for n, body in enumerate(render(results, by_id), 1):
            open(f"issue_body_{n}.md", "w", encoding="utf-8").write(body)

    for p in new:
        seen[p["id"]] = p["ctime"]
    state = {"last_ctime": max([state.get("last_ctime", since)] + [p["ctime"] for p in posts]),
             "seen": {str(k): v for k, v in seen.items() if v >= now - SEEN_TTL}}
    os.makedirs(os.path.dirname(STATE_FILE) or ".", exist_ok=True)
    json.dump(state, open(STATE_FILE, "w", encoding="utf-8"))

    if gh_out := os.environ.get("GITHUB_OUTPUT"):
        open(gh_out, "a").write(f"has_matches={'true' if results else 'false'}\n")


if __name__ == "__main__":
    main()
