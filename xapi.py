"""Minimal X (Twitter) API v2 client, signed with OAuth 1.0a user tokens (they don't expire).

Needs X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET (from your app in the X developer
console: Keys and tokens -> Consumer keys, and Access Token and Secret generated for your own account).
X bills per post returned (~$0.005 each), so every call here reports how many posts it read.
"""
import base64, hashlib, hmac, json, os, secrets, time, urllib.parse, urllib.request, urllib.error

API = "https://api.x.com/2"
TWEET_FIELDS = "created_at,author_id,conversation_id,referenced_tweets,public_metrics,note_tweet,entities,lang"
USER_FIELDS = "username,name,description,verified,public_metrics"
EXPANSIONS = "author_id,referenced_tweets.id,referenced_tweets.id.author_id"


def configured():
    return all(os.environ.get(k) for k in ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET"))


def _pct(s):
    return urllib.parse.quote(str(s), safe="~-._")


def _auth_header(method, url, params):
    oauth = {"oauth_consumer_key": os.environ["X_API_KEY"], "oauth_nonce": secrets.token_hex(16),
             "oauth_signature_method": "HMAC-SHA1", "oauth_timestamp": str(int(time.time())),
             "oauth_token": os.environ["X_ACCESS_TOKEN"], "oauth_version": "1.0"}
    allp = {**params, **oauth}
    base = "&".join([method, _pct(url), _pct("&".join(f"{_pct(k)}={_pct(v)}" for k, v in sorted(allp.items())))])
    key = f"{_pct(os.environ['X_API_SECRET'])}&{_pct(os.environ['X_ACCESS_TOKEN_SECRET'])}"
    oauth["oauth_signature"] = base64.b64encode(hmac.new(key.encode(), base.encode(), hashlib.sha1).digest()).decode()
    return "OAuth " + ", ".join(f'{_pct(k)}="{_pct(v)}"' for k, v in sorted(oauth.items()))


def get(path, params):
    url = API + path
    params = {k: v for k, v in params.items() if v is not None}
    req = urllib.request.Request(f"{url}?{urllib.parse.urlencode(params)}",
                                 headers={"Authorization": _auth_header("GET", url, params), "User-Agent": "chinascrape-x"})
    for attempt in range(3):
        try:
            return json.load(urllib.request.urlopen(req, timeout=30))
        except urllib.error.HTTPError as e:
            body = e.read()[:300].decode("utf-8", "replace")
            if e.code == 429:   # rate limited: wait until the window resets (capped)
                reset = int(e.headers.get("x-rate-limit-reset", time.time() + 60))
                time.sleep(min(max(reset - time.time(), 5), 120))
                continue
            if e.code >= 500 and attempt < 2:
                time.sleep(5)
                continue
            raise RuntimeError(f"X API {e.code} on {path}: {body}") from None
    raise RuntimeError(f"X API still rate limited on {path}")


def me():
    return get("/users/me", {"user.fields": USER_FIELDS})["data"]


def _flatten(resp):
    """Turn a v2 tweet list response into dicts with author, text and quoted/replied-to context attached."""
    inc = resp.get("includes", {})
    users = {u["id"]: u for u in inc.get("users", [])}
    refs = {t["id"]: t for t in inc.get("tweets", [])}
    out = []
    for t in resp.get("data", []):
        text = (t.get("note_tweet") or {}).get("text") or t["text"]
        for u in (t.get("entities") or {}).get("urls", []):   # show real links instead of t.co
            if u.get("expanded_url") and u.get("url"):
                text = text.replace(u["url"], u["expanded_url"])
        au = users.get(t["author_id"], {})
        context = []
        for r in t.get("referenced_tweets", []):
            rt = refs.get(r["id"])
            if rt:
                ra = users.get(rt.get("author_id"), {})
                context.append({"type": r["type"], "author": ra.get("username", "?"),
                                "text": (rt.get("note_tweet") or {}).get("text") or rt.get("text", "")})
        out.append({"id": t["id"], "created_at": t["created_at"], "author": au.get("username", "?"),
                    "author_name": au.get("name", ""), "author_bio": au.get("description", ""),
                    "author_followers": (au.get("public_metrics") or {}).get("followers_count", 0),
                    "text": text, "context": context, "conversation_id": t.get("conversation_id"),
                    "metrics": t.get("public_metrics", {}), "lang": t.get("lang", ""),
                    "url": f"https://x.com/{au.get('username', 'i')}/status/{t['id']}"})
    return out


def home_timeline(user_id, since_id=None, start_time=None, max_pages=5):
    """New posts from accounts you follow (newest first), excluding retweets. Returns (posts, posts_read)."""
    posts, token, read = [], None, 0
    for _ in range(max_pages):
        resp = get(f"/users/{user_id}/timelines/reverse_chronological", {
            "max_results": 100, "since_id": since_id, "start_time": None if since_id else start_time,
            "pagination_token": token, "exclude": "retweets", "tweet.fields": TWEET_FIELDS,
            "user.fields": USER_FIELDS, "expansions": EXPANSIONS})
        posts += _flatten(resp)
        read += len(resp.get("data", [])) + len(resp.get("includes", {}).get("tweets", []))   # quoted/replied-to posts are billed too
        token = resp.get("meta", {}).get("next_token")
        if not token:
            break
    return posts, read


def user_tweets(user_id, max_results=50):
    """Someone's own recent posts (used once, to learn your writing voice)."""
    resp = get(f"/users/{user_id}/tweets", {"max_results": max_results, "exclude": "retweets",
                                             "tweet.fields": TWEET_FIELDS, "expansions": EXPANSIONS, "user.fields": USER_FIELDS})
    return _flatten(resp)
