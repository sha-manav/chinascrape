"""Check the CLS Telegraph feed for new watchlist posts since the last run.

Run every 30 minutes by .github/workflows/cls-watch.yml. Writes issue_title.txt and
issue_body.md when there are new matching posts, and keeps its place in STATE_FILE.
"""
import json, os, re, sys, time, urllib.request
from datetime import datetime, timezone, timedelta
from sign_url import url

BJ = timezone(timedelta(hours=8))
STATE_FILE = os.environ.get("STATE_FILE", "state/cls_state.json")
FIRST_RUN_LOOKBACK = int(os.environ.get("FIRST_RUN_LOOKBACK_MIN", "60")) * 60
OVERLAP = 15 * 60          # re-read this much before the last run, in case posts land late
SEEN_TTL = 2 * 24 * 3600   # how long to remember ids already reported
MAX_PAGES = 30
BODY_LIMIT = 60000         # GitHub issue bodies max out at 65536 characters

# Category -> keywords. ASCII keywords match as whole words, case-insensitively.
KEYWORDS = {
    "AI": ["人工智能", "AI", "大模型", "算力", "智算", "DeepSeek", "OpenAI", "英伟达", "NVIDIA", "寒武纪", "昇腾", "GPU"],
    "CHIPS": ["芯片", "半导体", "集成电路", "晶圆", "存储芯片", "HBM", "先进封装", "国产替代", "台积电", "TSMC",
              "中芯国际", "华虹", "海力士", "三星电子", "美光", "实体清单", "出口管制"],
    "InP": ["磷化铟", "InP", "铟", "镓", "锗", "化合物半导体", "砷化镓", "衬底"],
    "PHOTONICS": ["光模块", "光通信", "硅光", "光芯片", "CPO", "共封装光学", "激光器", "EML", "VCSEL", "800G", "1.6T",
                  "光纤", "中际旭创", "旭创", "新易盛", "天孚通信", "光迅"],
    "LITHO": ["光刻", "EUV", "DUV", "光刻胶", "ASML", "阿斯麦", "上海微电子", "光罩", "掩模", "掩膜"],
}
PATTERNS = {
    cat: re.compile("|".join(
        rf"(?<![A-Za-z0-9]){re.escape(k)}(?![A-Za-z0-9])" if k.isascii() else re.escape(k) for k in words),
        re.IGNORECASE)
    for cat, words in KEYWORDS.items()
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


def categorize(post):
    text = " ".join(str(post.get(k) or "") for k in ("title", "brief", "content"))
    found = {}
    for cat, pat in PATTERNS.items():
        hits = sorted({m.group(0) for m in pat.finditer(text)}, key=str.lower)
        if hits:
            found[cat] = hits
    return found


def fmt_time(ct):
    return datetime.fromtimestamp(ct, BJ).strftime("%Y-%m-%d %H:%M")


def render(matches):
    by_cat = {cat: [] for cat in KEYWORDS}
    for post, cats in matches:
        by_cat[next(iter(cats))].append((post, cats))   # list each post once, under its first category
    out = []
    for cat, items in by_cat.items():
        if not items:
            continue
        out.append(f"## {cat} ({len(items)})\n")
        for post, cats in sorted(items, key=lambda x: x[0]["ctime"], reverse=True):
            title = (post.get("title") or "").strip()
            content = (post.get("content") or post.get("brief") or "").strip()
            link = post.get("shareurl") or f"https://www.cls.cn/detail/{post['id']}"
            tags = "; ".join(f"{c}: {', '.join(h)}" for c, h in cats.items())
            if not title:
                m = re.match(r"【(.+?)】", content)
                title = m.group(1) if m else content[:40]
            out.append(f"**[{fmt_time(post['ctime'])} Beijing] {title}**  ")
            out.append(f"{content}  ")
            out.append(f"_Matched: {tags}_ · [Link]({link})\n")
    body = "\n".join(out)
    if len(body) > BODY_LIMIT:
        body = body[:BODY_LIMIT] + "\n\n…(truncated)"
    return body


def main():
    now = int(time.time())
    try:
        state = json.load(open(STATE_FILE, encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        state = {}
    seen = {int(k): v for k, v in state.get("seen", {}).items()}
    since = state["last_ctime"] - OVERLAP if "last_ctime" in state else now - FIRST_RUN_LOOKBACK

    posts = fetch_since(since)
    new = sorted((p for p in posts if p["id"] not in seen), key=lambda p: p["ctime"])
    matches = [(p, c) for p in new if (c := categorize(p))]
    print(f"window from {fmt_time(since)} Beijing: {len(posts)} posts, {len(new)} new, {len(matches)} matching")

    if matches:
        lo, hi = fmt_time(matches[0][0]["ctime"]), fmt_time(matches[-1][0]["ctime"])
        open("issue_title.txt", "w", encoding="utf-8").write(
            f"CLS Telegraph: {len(matches)} new post{'s' if len(matches) != 1 else ''} ({lo} – {hi[11:] if lo[:10] == hi[:10] else hi} Beijing)")
        open("issue_body.md", "w", encoding="utf-8").write(render(matches))

    for p in new:
        seen[p["id"]] = p["ctime"]
    state = {"last_ctime": max([state.get("last_ctime", since)] + [p["ctime"] for p in posts]),
             "seen": {str(k): v for k, v in seen.items() if v >= now - SEEN_TTL}}
    os.makedirs(os.path.dirname(STATE_FILE) or ".", exist_ok=True)
    json.dump(state, open(STATE_FILE, "w", encoding="utf-8"))

    if gh_out := os.environ.get("GITHUB_OUTPUT"):
        open(gh_out, "a").write(f"has_matches={'true' if matches else 'false'}\n")


if __name__ == "__main__":
    main()
