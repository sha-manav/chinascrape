"""Every 2 minutes: read new posts from the accounts you follow on X, have Claude Sonnet draft two
reply options for each in your voice, and publish them (encrypted) for the drafts page in docs/.

Run by .github/workflows/x-drafts.yml. Nothing is ever posted to X: the page gives you a "Reply on X"
button that opens X's composer pre-filled, and you post yourself.

The published feed (all posts + drafts from the last day) also feeds the 30-minute news watcher,
so news from the X accounts you follow lands in the email without paying X twice.
"""
import json, os, subprocess, sys, tempfile, time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from pathlib import Path
import anthropic
import vault, xapi

HERE = Path(__file__).parent
STATE_FILE = os.environ.get("X_STATE_FILE", "state/x_state.json")
FEED_BRANCH, FEED_FILE = "x-data", "feed.enc.json"
INTERVAL = int(os.environ.get("X_POLL_SECONDS", "120"))
MAX_POSTS_PER_DAY = int(os.environ.get("X_MAX_POSTS_PER_DAY") or 1500)    # X read cap (~$0.005 each)
MAX_DRAFTS_PER_DAY = int(os.environ.get("X_MAX_DRAFTS_PER_DAY") or 1500)  # Claude draft cap
KEEP_HOURS = 24
KEEP_ITEMS = 1200
BATCH = 8
MODEL = "claude-sonnet-5-5"
SCHEMA = {
    "type": "object",
    "properties": {"drafts": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "id": {"type": "string"},
            "skip": {"type": "boolean"},
            "skip_reason": {"type": "string"},
            "worth": {"type": "integer", "enum": [1, 2, 3, 4, 5]},
            "replies": {"type": "array", "items": {
                "type": "object",
                "properties": {"angle": {"type": "string"}, "text": {"type": "string"}},
                "required": ["angle", "text"], "additionalProperties": False}},
        },
        "required": ["id", "skip", "skip_reason", "worth", "replies"],
        "additionalProperties": False,
    }}},
    "required": ["drafts"],
    "additionalProperties": False,
}


def now():
    return int(time.time())


def ts(created_at):
    return int(datetime.fromisoformat(created_at.replace("Z", "+00:00")).timestamp())


def today():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def load_state():
    try:
        return json.load(open(STATE_FILE, encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(state):
    os.makedirs(os.path.dirname(STATE_FILE) or ".", exist_ok=True)
    json.dump(state, open(STATE_FILE, "w", encoding="utf-8"), ensure_ascii=False)


def system_prompt(state):
    me = state["me"]
    voice = "\n".join(f"- {t}" for t in state.get("voice", [])[:40]) or "(no recent posts)"
    return ((HERE / "prompts" / "reply.md").read_text(encoding="utf-8") +
            f"\n\n# Their profile\n{me['name']} (@{me['username']}): {me.get('description', '')}\n\n# Their recent posts\n{voice}\n")


def draft(client, system, posts):
    """One Sonnet call for a batch of posts. Returns {post id: draft}."""
    payload = [{"id": p["id"], "author": f"{p['author_name']} (@{p['author']}, {p['author_followers']:,} followers)",
                "author_bio": p["author_bio"][:200], "text": p["text"], "context": p["context"]} for p in posts]
    with client.beta.messages.stream(
        model=MODEL, max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"], fallbacks="default",   # retry on another model if declined
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user", "content": "Draft replies to these posts:\n" + json.dumps(payload, ensure_ascii=False)}],
    ) as stream:
        msg = stream.get_final_message()
    if msg.stop_reason == "refusal":
        return {p["id"]: {"skip": True, "skip_reason": "declined by the model", "worth": 1, "replies": []} for p in posts}
    if msg.stop_reason != "end_turn":
        raise RuntimeError(f"Claude stopped with {msg.stop_reason}")
    out = json.loads(next(b.text for b in msg.content if b.type == "text"))
    return {d["id"]: d for d in out["drafts"]}


def publish(state):
    """Force-push the encrypted feed as the only commit on the x-data branch (keeps the repo small)."""
    feed = {"updated": now(), "me": state["me"]["username"], "status": state.get("status", {}),
            "items": state.get("items", [])}
    box = vault.seal(feed, os.environ["DRAFTS_PASSPHRASE"])
    token, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    if not (token and repo):
        Path(FEED_FILE).write_text(json.dumps(box))   # local run: just write the file
        return
    with tempfile.TemporaryDirectory() as d:
        Path(d, FEED_FILE).write_text(json.dumps(box))
        git = lambda *a: subprocess.run(["git", "-C", d, *a], check=True, capture_output=True)
        git("init", "-q")
        git("checkout", "-q", "-b", FEED_BRANCH)
        git("add", FEED_FILE)
        git("-c", "user.name=x-drafts", "-c", "user.email=x-drafts@users.noreply.github.com", "commit", "-q", "-m", "Update drafts feed")
        git("push", "-q", "--force", f"https://x-access-token:{token}@github.com/{repo}.git", f"{FEED_BRANCH}:{FEED_BRANCH}")


def tick(state, client):
    """One poll: fetch new posts, draft replies, return True if anything changed."""
    t0 = now()
    day = state.setdefault("day", {"date": today(), "posts": 0, "drafts": 0})
    if day["date"] != today():
        day.update(date=today(), posts=0, drafts=0)
    status = state.setdefault("status", {})
    status.update(checked=t0, posts_today=day["posts"], drafts_today=day["drafts"],
                  post_cap=MAX_POSTS_PER_DAY, draft_cap=MAX_DRAFTS_PER_DAY, error="")

    if "me" not in state:
        state["me"] = xapi.me()
    if state.get("voice_at", 0) < t0 - 7 * 86400:   # refresh voice samples weekly (~50 reads)
        state["voice"] = [p["text"] for p in xapi.user_tweets(state["me"]["id"], 50)]
        state["voice_at"] = t0
        day["posts"] += len(state["voice"])

    if day["posts"] >= MAX_POSTS_PER_DAY:
        status["error"] = f"Daily X read cap reached ({MAX_POSTS_PER_DAY} posts); polling resumes at 00:00 UTC."
        return False
    start = datetime.fromtimestamp(t0 - 900, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    posts, read = xapi.home_timeline(state["me"]["id"], since_id=state.get("since_id"), start_time=start)
    day["posts"] += read
    known = {i["id"] for i in state.get("items", [])}
    new = [p for p in posts if p["id"] not in known and p["author"].lower() != state["me"]["username"].lower()]
    new.sort(key=lambda p: ts(p["created_at"]))

    drafts = {}
    budget = max(0, MAX_DRAFTS_PER_DAY - day["drafts"])
    to_draft = new[-budget:] if budget else []
    if to_draft:
        system = system_prompt(state)
        batches = [to_draft[i:i + BATCH] for i in range(0, len(to_draft), BATCH)]
        with ThreadPoolExecutor(3) as pool:
            for result in pool.map(lambda b: draft(client, system, b), batches):
                drafts.update(result)
        day["drafts"] += len(to_draft)
    for p in new:
        d = drafts.get(p["id"])
        p["ts"] = ts(p["created_at"])
        p["draft"] = d or {"skip": True, "skip_reason": "daily draft cap reached", "worth": 1, "replies": []}
        p["drafted_at"] = now()
    if posts:   # advance only after drafting succeeded, so a failed tick re-reads the same posts
        state["since_id"] = max(posts, key=lambda p: int(p["id"]))["id"]
    items = sorted(new + state.get("items", []), key=lambda i: -i["ts"])
    state["items"] = [i for i in items if i["ts"] >= t0 - KEEP_HOURS * 3600][:KEEP_ITEMS]
    status.update(posts_today=day["posts"], drafts_today=day["drafts"])
    print(f"{datetime.now(timezone.utc):%H:%M:%S} read {read} posts, {len(new)} new, {len(drafts)} drafted "
          f"(today: {day['posts']} posts, {day['drafts']} drafts)")
    return bool(new)


def loop(minutes):
    if not (xapi.configured() and os.environ.get("DRAFTS_PASSPHRASE")):
        sys.exit("X drafts not configured: set the X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET "
                 "and DRAFTS_PASSPHRASE repository secrets")
    client = anthropic.Anthropic()
    state = load_state()
    deadline, failures, last_publish = time.time() + minutes * 60, 0, 0
    while time.time() < deadline:
        started = time.time()
        try:
            changed = tick(state, client)
            failures = 0
        except Exception as e:   # keep going; the same posts are fetched again next tick
            failures += 1
            changed = True
            state.setdefault("status", {})["error"] = f"{type(e).__name__}: {str(e)[:200]}"
            print(f"tick failed: {e!r}", file=sys.stderr)
            if failures >= 10:
                break
        if changed or time.time() - last_publish > 600:   # heartbeat every 10 minutes so the page shows it's alive
            try:
                publish(state)
                last_publish = time.time()
            except Exception as e:
                print(f"publish failed: {e!r}", file=sys.stderr)
        save_state(state)
        time.sleep(max(0, started + INTERVAL - time.time()))
    restart()
    if failures:
        sys.exit("the drafter stopped after repeated failures; see the log above")


def restart():
    """Queue the next drafter run (a workflow may dispatch itself with its own token)."""
    if not os.environ.get("GITHUB_TOKEN"):
        return
    from watch import github_api
    try:
        github_api("actions/workflows/x-drafts.yml/dispatches", {"ref": os.environ.get("GITHUB_REF_NAME", "main")})
        print("queued the next drafter run")
    except Exception as e:
        print(f"could not queue the next drafter run ({e!r}); the hourly schedule is the backup", file=sys.stderr)


if __name__ == "__main__":
    loop(float(os.environ.get("LOOP_MINUTES") or 340))
