import json, re
from datetime import datetime, timezone, timedelta
from entries_ai import AI
from entries_other import CHIPS, PHOTONICS, LITHO, EXTRA_POSTS, EXTRA_INDEX
BJ = timezone(timedelta(hours=8))
posts = {p["id"]: p for p in json.load(open("matched_posts.json", encoding="utf-8"))}
for p in EXTRA_POSTS:
    p = dict(p); p["time"] = datetime.fromtimestamp(p["ctime"], BJ).strftime("%Y-%m-%d %H:%M")
    p["link"] = f"https://api3.cls.cn/share/article/{p['id']}?os=web&sv=8.4.6&app=CailianpressWeb"
    posts[p["id"]] = p
entries = AI + CHIPS + PHOTONICS + LITHO
ids = [e[0] for e in entries]
assert len(ids) == len(set(ids)), "duplicate ids"
for e in entries:
    assert e[0] in posts, f"missing post {e[0]}"
    assert e[1] in ("AI","CHIPS","InP","PHOTONICS","LITHO") and e[2] in ("High","Medium","Low"), e[0]
    for s in e[3:]: assert s.strip() and "\n" not in s

# ---------- numeric consistency check ----------
def src_values(text):
    vals = set()
    for m in re.finditer(r"(\d[\d,]*(?:\.\d+)?)\s*(万亿|亿|万|千)?", text):
        v = float(m.group(1).replace(",", "")); u = m.group(2)
        vals.add(round(v, 6))
        if u == "亿": vals.update({round(v/10, 6), round(v*100, 6)})
        elif u == "万亿": vals.update({round(v*1000, 6)})
        elif u == "万": vals.update({round(v*10, 6), round(v*10000, 6), round(v/100, 6)})
        elif u == "千": vals.update({round(v*1000, 6)})
    return vals
flags = []
for e in entries:
    sv = src_values(posts[e[0]]["text"])
    for m in re.finditer(r"\d[\d,]*(?:\.\d+)?", e[3] + " " + e[4]):
        v = round(float(m.group(0).replace(",", "")), 6)
        if v not in sv: flags.append((e[0], m.group(0)))
print("numeric flags (need manual review):")
for f in flags: print("  ", f)

# ---------- render ----------
def line(e):
    p = posts[e[0]]
    t = p["time"]
    return (f"**[{t[5:]} Beijing] [{e[1]}] {e[3]}**  \nSummary: {e[4]}  \nCompanies: {e[5]}  \nWhy it matters: {e[6]}  \nImportance: {e[2]}  \nLink: {p['link']}\n")
out = []
for cat, lst in (("AI", AI), ("CHIPS", CHIPS), ("InP", []), ("PHOTONICS", PHOTONICS), ("LITHO", LITHO)):
    lst = sorted(lst, key=lambda e: posts[e[0]]["ctime"], reverse=True)
    out.append(f"## {cat} ({len(lst)} post{chr(115) if len(lst)!=1 else str()})\n")
    if not lst: out.append("No matching posts in the window.\n")
    for e in lst: out.append(line(e))
open("report_body.md", "w", encoding="utf-8").write("\n".join(out))

# ---------- sent_alerts.md ----------
log = ["# fetch method: A",
       "# note: Method A's API was read with the WebFetch tool, because the sandbox proxy blocks www.cls.cn for the script (403). Signed URLs: /home/claude/sign_url.py (same sign as the script, but the empty category parameter must be left out).",
       "# window covered by the first run: 2026-09-29 09:16 to 2026-10-01 10:13 Beijing"]
for e in sorted(entries, key=lambda e: posts[e[0]]["ctime"]):
    log.append(f"[{posts[e[0]]['time']} Beijing] [{e[1]}] {e[3]}")
open("sent_alerts.md", "w", encoding="utf-8").write("\n".join(log) + "\n")

# ---------- cls_posts.json (candidate posts with full text) ----------
keep = sorted(posts.values(), key=lambda p: p["ctime"])
json.dump([{"time": p["time"], "text": p["text"], "link": p["link"], "reported": p["id"] in set(ids)} for p in keep],
          open("cls_posts.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
import collections
print("entries:", len(entries), collections.Counter(e[1] for e in entries), collections.Counter(e[2] for e in entries))
idx = json.load(open("all_index.json", encoding="utf-8"))
print("posts scanned:", len(idx) + len(EXTRA_INDEX))
print("report chars:", sum(len(x) for x in out))
