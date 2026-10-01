import hashlib, json, time, urllib.parse, urllib.request
from datetime import datetime, timezone, timedelta
HOURS = 48
BJ = timezone(timedelta(hours=8))
def page(last_time):
    p = {"app": "CailianpressWeb", "category": "", "last_time": str(last_time), "os": "web",
         "refresh_type": "1", "rn": "50", "sv": "8.4.6"}
    p["sign"] = hashlib.md5(hashlib.sha1(urllib.parse.urlencode(p).encode()).hexdigest().encode()).hexdigest()
    req = urllib.request.Request("https://www.cls.cn/v1/roll/get_roll_list?" + urllib.parse.urlencode(p),
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0 Safari/537.36",
                 "Referer": "https://www.cls.cn/telegraph"})
    return json.load(urllib.request.urlopen(req, timeout=20))["data"]["roll_data"]
cutoff, cursor, posts = time.time() - HOURS * 3600, int(time.time()), {}
for _ in range(80):
    rows = page(cursor)
    for r in rows:
        posts[r["id"]] = {"time": datetime.fromtimestamp(r["ctime"], BJ).strftime("%Y-%m-%d %H:%M"),
                          "text": r.get("content") or r.get("title", ""), "link": r.get("shareurl", "")}
    oldest = min((r["ctime"] for r in rows), default=cursor)
    if not rows or oldest >= cursor or oldest < cutoff: break
    cursor = oldest
    time.sleep(1)
keep = sorted((p for p in posts.values() if p["time"] >= datetime.fromtimestamp(cutoff, BJ).strftime("%Y-%m-%d %H:%M")), key=lambda p: p["time"])
json.dump(keep, open("cls_posts.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(len(keep), "posts from", keep[0]["time"] if keep else "-", "to", keep[-1]["time"] if keep else "-")
