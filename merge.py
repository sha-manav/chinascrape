import re, json, glob
from datetime import datetime, timezone, timedelta
BJ = timezone(timedelta(hours=8))
f = lambda x: datetime.fromtimestamp(x,BJ).strftime("%m-%d %H:%M:%S")
allidx, posts, problems = {}, {}, []
ranges = []
for path in sorted(glob.glob("slices/R*.txt")):
    txt = open(path, encoding="utf-8").read()
    m = re.match(r"RANGE (\S+) start=(\d+) end=(\d+)", txt)
    name, start, end = m.group(1), int(m.group(2)), int(m.group(3))
    pages_part = txt.split("@@PAGES",1)[1].split("@@INDEX",1)[0]
    index_part = txt.split("@@INDEX",1)[1].split("@@POSTS",1)[0]
    posts_part = txt.split("@@POSTS",1)[1]
    pages = [dict(kv.split("=") for kv in l.split()) for l in pages_part.strip().splitlines() if l.strip()]
    pages = [{k:int(v) for k,v in p.items()} for p in pages]
    # continuity
    if pages[0]["cursor"] < end: problems.append(f"{name}: first cursor {pages[0]['cursor']} < end {end}")
    for a,b in zip(pages, pages[1:]):
        if b["cursor"] < a["min_ctime"]: problems.append(f"{name}: gap between pages {a} {b}")
    if pages[-1]["min_ctime"] >= start: problems.append(f"{name}: last page min_ctime {pages[-1]['min_ctime']} >= start {start}")
    idx = []
    for l in index_part.strip().splitlines():
        if not l.strip(): continue
        parts = l.split("|", 3)
        pid, ct, yn = int(parts[0]), int(parts[1]), parts[2].strip()
        idx.append((pid, ct, yn, parts[3] if len(parts)>3 else ""))
        if not (start <= ct < end): problems.append(f"{name}: index {pid} ctime out of range")
        if pid in allidx: problems.append(f"{name}: dup id {pid}")
        allidx[pid] = (ct, yn, parts[3] if len(parts)>3 else "", name)
    blocks = re.findall(r"@@POST id=(\d+) ctime=(\d+) cat=(\S+) note=(.*?)\n(.*?)\n@@END", posts_part, flags=re.S)
    ny = sum(1 for i in idx if i[2]=="Y")
    if ny != len(blocks): problems.append(f"{name}: Y count {ny} != blocks {len(blocks)}")
    for pid, ct, cat, note, body in blocks:
        pid, ct = int(pid), int(ct)
        if pid not in allidx or allidx[pid][0] != ct: problems.append(f"{name}: post {pid} not in index or ctime mismatch")
        posts[pid] = {"id": pid, "ctime": ct, "time": datetime.fromtimestamp(ct,BJ).strftime("%Y-%m-%d %H:%M"), "cat": cat, "note": note.strip(), "text": body.strip(),
                      "link": f"https://api3.cls.cn/share/article/{pid}?os=web&sv=8.4.6&app=CailianpressWeb", "range": name}
    cts = [i[1] for i in idx]
    ranges.append((name, start, end, len(pages), len(idx), len(blocks), min(cts), max(cts)))
    print(name, f(start), "->", f(end), "pages", len(pages), "posts", len(idx), "matched", len(blocks), "covered", f(min(cts)), "..", f(max(cts)))
print("TOTAL posts", len(allidx), "matched", len(posts))
print("PROBLEMS:", *problems, sep="\n  ")
json.dump(sorted(posts.values(), key=lambda p: p["ctime"]), open("matched_posts.json","w",encoding="utf-8"), ensure_ascii=False, indent=1)
json.dump({str(k): v for k,v in allidx.items()}, open("all_index.json","w",encoding="utf-8"), ensure_ascii=False)
