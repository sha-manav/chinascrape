import hashlib, sys, time, urllib.parse
def url(last_time, rn=20, category=None, extra=None):
    p = {"app": "CailianpressWeb", "last_time": str(last_time), "os": "web",
         "refresh_type": "1", "rn": str(rn), "sv": "8.4.6"}
    if category is not None: p["category"] = category
    if extra: p.update(extra)
    p = dict(sorted(p.items()))
    p["sign"] = hashlib.md5(hashlib.sha1(urllib.parse.urlencode(p).encode()).hexdigest().encode()).hexdigest()
    return "https://www.cls.cn/v1/roll/get_roll_list?" + urllib.parse.urlencode(p)
if __name__ == "__main__":
    rn = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    for t in sys.argv[1].split(","):
        t = int(time.time()) if t == "now" else int(t)
        print(t, url(t, rn))
