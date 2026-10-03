"""Every 30 minutes: pull everything new from all sources (sources.py), have Claude triage the
titles, fetch full text for the picks, have Claude translate/summarise them, and open one GitHub
issue (= one email) with the results, China first, then US, then other regions.

Run by .github/workflows/cls-watch.yml. State (per-source position, ids already handled, recent
headlines for de-duplication) is kept in STATE_FILE. Prompts are in prompts/.
"""
import json, os, sys, time, urllib.error, urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
import anthropic
import sources
from sources import BJ, SOURCES

HERE = Path(__file__).parent
STATE_FILE = os.environ.get("STATE_FILE", "state/watch_state.json")
FIRST_RUN_LOOKBACK = int(os.environ.get("FIRST_RUN_LOOKBACK_MIN", "60")) * 60
OVERLAP = 15 * 60           # re-read this much before a source's last item, in case items land late
SEEN_TTL = 4 * 24 * 3600    # how long to remember items already handled
RECENT_TTL = 12 * 3600      # headlines already sent, shown to triage to avoid repeats
INTERVAL = 30 * 60          # seconds between checks in loop mode
TRIAGE_BATCH = 150          # items per triage request
WRITE_CHARS = 60000         # characters of item text per write request
BODY_LIMIT = 60000          # GitHub issue bodies max out at 65536 characters

MODEL = "claude-haiku-4-5"  # cheapest Claude model; ~$1/$5 per million input/output tokens
REGIONS = ["China", "US", "Other regions"]   # email order
CATEGORIES = ["AI", "Semiconductors", "Photonics & Optics", "Robotics", "Power & Datacenter Infrastructure",
              "Materials & Supply Chain"]
TRIAGE_SCHEMA = {"type": "object", "properties": {"keep": {"type": "array", "items": {"type": "integer"}}},
                 "required": ["keep"], "additionalProperties": False}
WRITE_SCHEMA = {
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


def fmt_time(ct):
    return datetime.fromtimestamp(ct, BJ).strftime("%Y-%m-%d %H:%M")


def ask(client, prompt_file, content, schema, max_tokens):
    with client.messages.stream(
        model=MODEL, max_tokens=max_tokens,
        system=(HERE / "prompts" / prompt_file).read_text(encoding="utf-8"),
        output_config={"format": {"type": "json_schema", "schema": schema}},
        messages=[{"role": "user", "content": content}],
    ) as stream:
        msg = stream.get_final_message()
    if msg.stop_reason != "end_turn":
        raise RuntimeError(f"Claude stopped with {msg.stop_reason}: {msg.stop_details}")
    return json.loads(next(b.text for b in msg.content if b.type == "text"))


def triage(client, items, recent):
    """Stage 1: titles only. Returns the items worth reading in full."""
    def one(batch):
        lines = [f"{n} | {it['source']} | {it['type']} | {fmt_time(it['ctime'])[5:]} | {it['title'][:200]} | {it['text'][:200]}".replace("\n", " ")
                 for n, it in enumerate(batch)]
        sent = "\n".join(f"- {h}" for h in recent[-150:]) or "(none)"
        out = ask(client, "triage.md", f"Already sent in the last 12 hours:\n{sent}\n\nNew items:\n" + "\n".join(lines),
                  TRIAGE_SCHEMA, 4000)
        return [batch[n] for n in sorted(set(out["keep"])) if 0 <= n < len(batch)]
    batches = [items[i:i + TRIAGE_BATCH] for i in range(0, len(items), TRIAGE_BATCH)]
    with ThreadPoolExecutor(4) as pool:
        return [it for kept in pool.map(one, batches) for it in kept]


def write(client, items):
    """Stage 2: full text. Returns [(item, write-up)]."""
    with ThreadPoolExecutor(8) as pool:
        texts = list(pool.map(sources.details, items))
    payload = [{"id": n, "source": it["source"], "type": it["type"], "time": fmt_time(it["ctime"]), "title": it["title"],
                "snippet": it["text"], "full_text": t if t != it["text"] else ""} for n, (it, t) in enumerate(zip(items, texts))]
    batches, cur, size = [], [], 0
    for p in payload:
        n = len(p["full_text"]) + len(p["snippet"]) + 200
        if cur and size + n > WRITE_CHARS:
            batches.append(cur)
            cur, size = [], 0
        cur.append(p)
        size += n
    batches += [cur] if cur else []
    with ThreadPoolExecutor(4) as pool:
        outs = list(pool.map(lambda b: ask(client, "write.md", json.dumps(b, ensure_ascii=False), WRITE_SCHEMA, 32000), batches))
    results = [(items[r["id"]], r) for out in outs for r in out["posts"] if 0 <= r["id"] < len(items)]
    seen, unique = set(), []
    for it, r in results:   # same item id twice across batches can't happen, but guard against repeated headlines
        if r["headline_en"].strip().lower() not in seen:
            seen.add(r["headline_en"].strip().lower())
            unique.append((it, r))
    return unique


def render(results, footer=""):
    """Issue bodies grouped by region (China first), then category, split to fit GitHub's size limit."""
    blocks = []
    for region in REGIONS:
        in_region = [(it, r) for it, r in results if r["region"] == region]
        if in_region:
            blocks.append(f"# {region} ({len(in_region)})\n")
        for cat in CATEGORIES:
            rows = sorted(((it, r) for it, r in in_region if r["category"] == cat),
                          key=lambda x: ({"High": 0, "Medium": 1, "Low": 2}[x[1]["importance"]], -x[0]["ctime"]))
            if rows:
                blocks.append(f"## {cat} ({len(rows)})\n")
            for it, r in rows:
                meta = " · ".join(x for x in (f"{it['type']} · {it['source']}", f"Importance: {r['importance']}",
                                              r["companies"].strip(), f"[Source]({it['url']})") if x)
                text = r["translation_en"].strip().replace("\n", "  \n")
                blocks.append(f"**[{fmt_time(it['ctime'])[5:]} Beijing] {r['headline_en'].strip()}**  \n{text}  \n_{meta}_\n")
    if footer:
        blocks.append(f"---\n_{footer}_\n")
    bodies, cur = [], ""
    for b in blocks:
        if cur and len(cur) + len(b) > BODY_LIMIT:
            bodies.append(cur)
            cur = ""
        cur += b + "\n"
    return bodies + [cur] if cur else bodies


def summary_title(results, label=None):
    times = sorted(it["ctime"] for it, _ in results)
    lo, hi = fmt_time(times[0]), fmt_time(times[-1])
    n_high = sum(r["importance"] == "High" for _, r in results)
    span = lo[5:] if lo == hi else f"{lo[5:]} – {hi[11:] if lo[:10] == hi[:10] else hi[5:]}"
    return (f"AI/semis watch: {len(results)} update{'s' if len(results) != 1 else ''}"
            + (f", {n_high} high" if n_high else "") + f" ({label or span + ' Beijing'})")


def write_issues(groups):
    """groups: [(title, results, footer)]. Writes issue_NNN.title / issue_NNN.md pairs."""
    for f in [*Path().glob("issue_*.md"), *Path().glob("issue_*.title")]:
        f.unlink()
    n = 0
    for title, results, footer in groups:
        bodies = render(results, footer)
        for i, body in enumerate(bodies, 1):
            n += 1
            part = f" [part {i}/{len(bodies)}]" if len(bodies) > 1 else ""
            open(f"issue_{n:03d}.title", "w", encoding="utf-8").write(title + part)
            open(f"issue_{n:03d}.md", "w", encoding="utf-8").write(body)
    return n


def load_state():
    try:
        return json.load(open(STATE_FILE, encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(state):
    os.makedirs(os.path.dirname(STATE_FILE) or ".", exist_ok=True)
    json.dump(state, open(STATE_FILE, "w", encoding="utf-8"), ensure_ascii=False)


def collect(state, lookback=None):
    """Fetch every source in parallel. Returns (new items, per-source high-water marks, failures)."""
    now = int(time.time())
    pos, seen = state.setdefault("sources", {}), state.setdefault("seen", {})
    cache = state.setdefault("cache", {})

    def run(name):
        fn, timestamped = SOURCES[name]
        since = now - lookback if lookback else (pos[name] - OVERLAP if name in pos else now - FIRST_RUN_LOOKBACK)
        t = time.time()
        items = fn(since, cache) if fn is sources.youtube else fn(since)
        if lookback:
            fresh = [i for i in items if i["ctime"] >= since]
        elif not timestamped and name not in pos:
            fresh = []   # first run of an undated source: remember what is there now, report only later additions
        else:
            fresh = [i for i in items if i["key"] not in seen and (not timestamped or i["ctime"] >= since)]
        mark = max([pos.get(name, 0)] + [i["ctime"] for i in items if timestamped]) or now
        print(f"  {name:20s} {len(items):4d} fetched, {len(fresh):4d} new ({time.time() - t:4.1f}s)")
        return fresh, items, mark

    new, marks, failures = [], {}, {}
    with ThreadPoolExecutor(6) as pool:
        futures = {name: pool.submit(run, name) for name in SOURCES}
        for name, fut in futures.items():
            try:
                fresh, items, mark = fut.result()
                new += fresh
                marks[name] = (mark, [i["key"] for i in items])
            except Exception as e:
                failures[name] = repr(e)[:120]
                print(f"  {name:20s} FAILED: {e!r}"[:200])
    return sorted(new, key=lambda i: i["ctime"]), marks, failures


def watch():
    now = int(time.time())
    state = load_state()
    lookback = int(float(os.environ.get("LOOKBACK_HOURS") or 0) * 3600) or None
    new, marks, failures = collect(state, lookback)
    recent = [h for t, h in state.get("recent", []) if t >= now - RECENT_TTL]

    results = []
    if new:
        client = anthropic.Anthropic()
        picked = triage(client, new, recent)
        results = write(client, picked) if picked else []
        print(f"{len(new)} new items, {len(picked)} passed triage, {len(results)} relevant")
    footer = "Sources unavailable this check: " + "; ".join(f"{k} ({v})" for k, v in failures.items()) if failures else ""
    n = write_issues([(summary_title(results), results, footer)] if results else [])

    # commit state only after everything above succeeded, so failed checks are retried
    for name, (mark, keys) in marks.items():
        state["sources"][name] = mark
        for k in keys:
            state["seen"].setdefault(k, now)
    for it in new:
        state["seen"][it["key"]] = now
    state["seen"] = {k: v for k, v in state["seen"].items() if v >= now - SEEN_TTL}
    state["recent"] = [x for x in state.get("recent", []) if x[0] >= now - RECENT_TTL] + [[now, r["headline_en"]] for _, r in results]
    state["failures"] = failures
    save_state(state)
    return n


def backfill(date_from, date_to, dry_run):
    """CLS only: process a past date range (Beijing dates, inclusive), one issue per day. Leaves the watch state alone."""
    start = int(datetime.strptime(date_from, "%Y-%m-%d").replace(tzinfo=BJ).timestamp())
    end = int(datetime.strptime(date_to, "%Y-%m-%d").replace(tzinfo=BJ).timestamp()) + 86400
    posts = sorted(sources.cls(start, end, max_pages=600), key=lambda p: p["ctime"])
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
    client = anthropic.Anthropic()
    groups = []
    for d in sorted(days):
        rs = write(client, triage(client, days[d], []))
        if rs:
            groups.append((summary_title(rs, f"{d} Beijing"), rs, ""))
        print(f"  {d}: {len(rs)} relevant")
    return write_issues(groups)


def github_api(path, data):
    api = os.environ.get("GITHUB_API_URL", "https://api.github.com")
    req = urllib.request.Request(f"{api}/repos/{os.environ['GITHUB_REPOSITORY']}/{path}", json.dumps(data).encode(), {
        "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}", "Accept": "application/vnd.github+json"})
    body = urllib.request.urlopen(req, timeout=30).read()
    return json.loads(body) if body else {}


def publish():
    """Open a GitHub issue for each issue_NNN.md written by this run (skipped outside Actions)."""
    files = sorted(Path().glob("issue_*.md"))
    if not files or not (os.environ.get("GITHUB_TOKEN") and os.environ.get("GITHUB_REPOSITORY")):
        return
    try:
        github_api("labels", {"name": "cls-alert", "color": "1d76db", "description": "AI/semis watch"})
    except urllib.error.HTTPError:
        pass  # already exists
    owner = os.environ["GITHUB_REPOSITORY"].split("/")[0]
    for f in files:
        title = f.with_suffix(".title").read_text(encoding="utf-8")
        issue = github_api("issues", {"title": title, "body": f.read_text(encoding="utf-8"),
                                      "labels": ["cls-alert"], "assignees": [owner]})
        print("opened", issue["html_url"])
        f.unlink()
        f.with_suffix(".title").unlink()


def loop(minutes):
    """Check every INTERVAL seconds until the time budget runs out. GitHub's scheduler drops many
    runs, so one long job does the 30-minute checks itself and then starts its own next run."""
    deadline, failed = time.time() + minutes * 60, False
    while True:
        started = time.time()
        try:
            watch()
            publish()
        except Exception as e:  # keep looping; the items are retried next check
            failed = True
            print(f"check failed: {e!r}", file=sys.stderr)
        wake = started + INTERVAL
        if wake > deadline:
            break
        time.sleep(max(0, wake - time.time()))
    restart()
    if failed:
        sys.exit("at least one check failed; see the log above")


def restart():
    """Queue the next watcher run (GitHub lets a workflow dispatch itself with its own token)."""
    if not os.environ.get("GITHUB_TOKEN"):
        return
    for attempt in range(3):
        try:
            github_api("actions/workflows/cls-watch.yml/dispatches",
                       {"ref": os.environ.get("GITHUB_REF_NAME", "main"), "inputs": {"watch_loop": "true"}})
            print("queued the next watcher run")
            return
        except Exception as e:
            print(f"could not queue the next watcher run ({e!r}); the hourly schedule is the backup", file=sys.stderr)
            time.sleep(10)


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


if __name__ == "__main__":
    main()
