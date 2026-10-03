"""Source fetchers. Each returns Items (plain dicts) newer than the given time:

    {"key": "<source>:<id>", "source": str, "type": News|Filing|Insider|Transcript|Video|Policy,
     "ctime": unix seconds, "title": str, "text": str (short), "url": str, "detail": optional hint for details()}

`details(item)` fetches the full text (article, PDF, SEC document, transcript) for items that
pass triage. Sources without timestamps report the time they were first seen.
"""
import gzip, html, io, json, os, re, time, urllib.parse, urllib.request, http.cookiejar
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from sign_url import url as cls_url

BJ = timezone(timedelta(hours=8))
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
# SEC asks for a contact name and email in the User-Agent; set SEC_USER_AGENT (repo variable) to your own
SEC_UA = os.environ.get("SEC_USER_AGENT") or "chinascrape research desk sec-contact@chinascrape.dev"
SEC_HEADERS = {"User-Agent": SEC_UA, "Accept-Encoding": "identity", "Host": "www.sec.gov"}
DETAIL_CHARS = 9000   # max characters of full text sent to Claude per item


# ---------- helpers ----------

def http_get(url, headers=None, data=None, opener=None, timeout=25):
    h = {"User-Agent": UA, "Accept": "*/*", "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8", "Accept-Encoding": "gzip"}
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=h)
    for attempt in range(3):
        try:
            r = (opener or urllib.request.build_opener()).open(req, timeout=timeout)
            body = r.read()
            if r.headers.get("Content-Encoding") == "gzip":
                body = gzip.decompress(body)
            return body
        except urllib.error.HTTPError as e:
            if e.code < 500 or attempt == 2:
                raise
        except Exception:
            if attempt == 2:
                raise
        time.sleep(3 * (attempt + 1))


def get_json(url, **kw):
    d = json.loads(http_get(url, **kw))
    return json.loads(d) if isinstance(d, str) else d   # some APIs double-encode


def strip_html(s):
    s = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", s or "")
    s = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>|</h\d>", "\n", s)
    s = html.unescape(re.sub(r"<[^>]+>", " ", s))
    return re.sub(r"[ \t　\xa0]+", " ", re.sub(r"\n\s*\n+", "\n", s)).strip()


def bj_ts(s, fmt):
    return int(datetime.strptime(s, fmt).replace(tzinfo=BJ).timestamp())


def item(source, id_, type_, ctime, title, text="", url="", detail=None):
    return {"key": f"{source}:{id_}", "source": source, "type": type_, "ctime": int(ctime),
            "title": (title or "").strip(), "text": (text or "").strip()[:600], "url": url, "detail": detail}


def page_links(url, pattern, base=None, enc="utf-8", **kw):
    """(href, text) pairs for links matching a regex, deduplicated, keeping the longest text."""
    page = http_get(url, **kw).decode(enc, "replace")
    out = {}
    for href, text in re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', page, re.S):
        if re.search(pattern, href):
            href = urllib.parse.urljoin(base or url, href)
            text = strip_html(text)
            if len(text) > len(out.get(href, "")):
                out[href] = text
    return [(h, t) for h, t in out.items() if t]


def pdf_text(data):
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data))
        return "\n".join((p.extract_text() or "") for p in reader.pages[:12])
    except Exception as e:
        return f"(PDF text could not be extracted: {e.__class__.__name__})"


# ---------- news flashes (timestamped) ----------

def cls(since, until=None, max_pages=30):
    out, cursor = {}, until or int(time.time())
    for _ in range(max_pages):
        rows = get_json(cls_url(cursor, 50), headers={"Referer": "https://www.cls.cn/telegraph"})["data"]["roll_data"]
        for r in rows:
            out[r["id"]] = item("CLS", r["id"], "News", r["ctime"], r.get("title") or "", r.get("content") or r.get("brief") or "",
                                r.get("shareurl") or f"https://www.cls.cn/detail/{r['id']}", {"full": r.get("content") or ""})
        oldest = min((r["ctime"] for r in rows), default=cursor)
        if not rows or oldest >= cursor or oldest < since:
            break
        cursor = oldest
        time.sleep(1)
    return [i for i in out.values() if until is None or i["ctime"] < until]


def eastmoney_flash(since):
    rows = get_json("https://np-weblist.eastmoney.com/comm/web/getFastNewsList?client=web&biz=web_724&fastColumn=102&sortEnd=&pageSize=200&req_trace=1")["data"]["fastNewsList"]
    return [item("EastMoney", r["code"], "News", bj_ts(r["showTime"], "%Y-%m-%d %H:%M:%S"), r["title"], r["summary"],
                 f"https://finance.eastmoney.com/a/{r['code']}.html", {"full": r["summary"]}) for r in rows]


def ths_flash(since):
    rows = get_json("https://news.10jqka.com.cn/tapp/news/push/stock/?page=1&tag=&track=website&pagesize=100")["data"]["list"]
    return [item("Tonghuashun", r["id"], "News", int(r["ctime"]), r["title"], r.get("digest", ""), r.get("url", ""), {"full": r.get("digest", "")})
            for r in rows]


def wallstreetcn(since):
    rows = get_json("https://api-one-wscn.awtmt.com/apiv1/content/lives?channel=global-channel&limit=100")["data"]["items"]
    return [item("Wallstreetcn", r["id"], "News", r["display_time"], r.get("title") or "", r.get("content_text", ""), r.get("uri", ""),
                 {"full": r.get("content_text", "")}) for r in rows]


def sina_flash(since):
    rows = get_json("https://zhibo.sina.com.cn/api/zhibo/feed?page=1&page_size=100&zhibo_id=152")["result"]["data"]["feed"]["list"]
    return [item("Sina", r["id"], "News", bj_ts(r["create_time"], "%Y-%m-%d %H:%M:%S"), "", r["rich_text"], r.get("docurl", ""),
                 {"full": r["rich_text"]}) for r in rows]


def yicai_flash(since):
    rows = get_json("https://www.yicai.com/api/ajax/getbrieflist?page=1&pagesize=60",
                    headers={"Referer": "https://www.yicai.com/brief/", "Accept-Encoding": "identity", "X-Requested-With": "XMLHttpRequest"})
    if isinstance(rows, dict):
        rows = next((v for v in rows.values() if isinstance(v, list)), [])
    rows = [r for r in rows if isinstance(r, dict)]
    return [item("Yicai", r["id"], "News", bj_ts(r["CreateDate"][:19], "%Y-%m-%dT%H:%M:%S"), r.get("LiveTitle", ""), r.get("LiveContent", ""),
                 "https://www.yicai.com" + r.get("url", ""), {"full": r.get("LiveContent", "")}) for r in rows]


def kr36_flash(since):
    body = json.dumps({"partner_id": "web", "timestamp": int(time.time() * 1000),
                       "param": {"pageSize": 50, "pageEvent": 0, "siteId": 1, "platformId": 2}}).encode()
    rows = get_json("https://gateway.36kr.com/api/mis/nav/newsflash/flow", data=body,
                    headers={"Content-Type": "application/json", "Referer": "https://36kr.com/"})["data"]["itemList"]
    out = []
    for r in rows:
        m = r.get("templateMaterial", {})
        out.append(item("36Kr", r["itemId"], "News", m.get("publishTime", 0) // 1000, m.get("widgetTitle", ""), m.get("widgetContent", ""),
                        f"https://36kr.com/newsflashes/{r['itemId']}", {"full": m.get("widgetContent", "")}))
    return out


def xueqiu_flash(since):
    jar = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    http_get("https://xueqiu.com/hq", opener=op)
    d = get_json("https://xueqiu.com/statuses/livenews/list.json?since_id=-1&max_id=-1&count=50", opener=op,
                 headers={"Referer": "https://xueqiu.com/", "X-Requested-With": "XMLHttpRequest"})
    return [item("Xueqiu", r["id"], "News", r["created_at"] // 1000, "", strip_html(r.get("text", "")), r.get("target", "") or "https://xueqiu.com/",
                 {"full": strip_html(r.get("text", ""))}) for r in d["items"]]


# ---------- long-form news (first-seen) ----------

def caixin(since):
    return [item("Caixin", re.search(r"/(\d+)\.html", h).group(1), "News", time.time(), t, "", h, {"page": h})
            for h, t in page_links("https://www.caixin.com/", r"caixin\.com/20\d\d-\d\d-\d\d/\d+\.html") if "photos." not in h]


def caixin_global(since):
    return [item("Caixin Global", re.search(r"(\d+)\.html", h).group(1), "News", time.time(), t, "", h, {"page": h})
            for h, t in page_links("https://www.caixinglobal.com/news/", r"caixinglobal\.com/20\d\d-\d\d-\d\d/.*\d+\.html")]


def caijing(since):
    return [item("Caijing", re.search(r"/(\d+)\.shtml", h).group(1), "News", time.time(), t, "", h, {"page": h})
            for h, t in page_links("https://www.caijing.com.cn/", r"caijing\.com\.cn/20\d{6}/\d+\.shtml")]


# ---------- exchange filings ----------

def a_share_filings(since):
    """Shanghai/Shenzhen/Beijing filings (EastMoney mirror of SSE/SZSE/BSE disclosures), newest first."""
    out = []
    for page in range(1, 31):
        rows = get_json(f"https://np-anotice-stock.eastmoney.com/api/security/ann?sr=-1&page_size=100&page_index={page}"
                        "&ann_type=A&client_source=web&f_node=0&s_node=0")["data"]["list"]
        for r in rows:
            ts = bj_ts(r["display_time"][:19], "%Y-%m-%d %H:%M:%S")
            code = r["codes"][0] if r.get("codes") else {}
            cols = ", ".join(c["column_name"] for c in r.get("columns", []))
            out.append(item("SSE/SZSE filing", r["art_code"], "Filing", ts, r["title"],
                            f"{code.get('stock_code', '')} {code.get('short_name', '')} [{cols}]",
                            f"https://data.eastmoney.com/notices/detail/{code.get('stock_code', '')}/{r['art_code']}.html",
                            {"pdf": f"https://pdf.dfcfw.com/pdf/H2_{r['art_code']}_1.pdf"}))
        if not rows or min(i["ctime"] for i in out[-len(rows):]) < since:
            break
    return out


def hkex_filings(since):
    out = []
    for n in range(1, 4):
        d = get_json(f"https://www1.hkexnews.hk/ncms/json/eds/lcisehk1relsde_{n}.json")
        rows = d.get("newsInfoLst", [])
        for r in rows:
            ts = int(datetime.strptime(r["relTime"], "%d/%m/%Y %H:%M").replace(tzinfo=BJ).timestamp())
            stocks = "; ".join(f"{s['sc']} {s['sn']}" for s in r.get("stock", []))
            link = "https://www1.hkexnews.hk" + r["webPath"]
            out.append(item("HKEX filing", r["newsId"], "Filing", ts, r["title"].replace("\n", " "), f"{stocks} [{r.get('lTxt', '')}]", link,
                            {"pdf": link} if r.get("ext") == "pdf" else {"page": link}))
        if not rows or min(i["ctime"] for i in out) < since:
            break
    return out


# ---------- SEC EDGAR ----------

SEC_FORMS = ["8-K", "6-K", "10-Q", "10-K", "20-F", "S-1", "F-1", "SC 13D", "4"]


def sec_filings(since):
    out = {}
    for form in SEC_FORMS:
        for start in range(0, 400, 100):
            feed = http_get(f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type={urllib.parse.quote(form)}"
                            f"&company=&dateb=&owner=include&start={start}&count=100&output=atom", headers=SEC_HEADERS)
            entries = ET.fromstring(feed).findall("{http://www.w3.org/2005/Atom}entry")
            oldest = None
            for e in entries:
                t = e.findtext("{http://www.w3.org/2005/Atom}title") or ""
                m = re.match(r"(.+?) - (.+) \((\d+)\) \((\w+)\)", t)
                if not m or (form == "4" and m.group(4) != "Issuer") or (form != "4" and m.group(4) not in ("Filer", "Subject")):
                    continue
                link = e.find("{http://www.w3.org/2005/Atom}link").get("href")
                acc = re.search(r"(\d{10}-\d{2}-\d{6})", e.findtext("{http://www.w3.org/2005/Atom}id") or link)
                ts = int(datetime.fromisoformat(e.findtext("{http://www.w3.org/2005/Atom}updated")).timestamp())
                oldest = ts if oldest is None else min(oldest, ts)
                key = acc.group(1) if acc else link
                typ = "Insider" if form == "4" else "Filing"
                summary = strip_html(e.findtext("{http://www.w3.org/2005/Atom}summary") or "")
                out[key] = item("SEC", key, typ, ts, f"{m.group(1)} - {m.group(2)}", summary, link, {"sec_index": link, "form": m.group(1)})
            if not entries or (oldest and oldest < since):
                break
            time.sleep(0.3)
    return list(out.values())


# ---------- government ----------

def gov_cn(since):
    out = []
    for name, url, pat in [("MOFCOM", "https://www.mofcom.gov.cn/", r"/art/20\d\d/art_\w+\.html"),
                           ("MIIT", "https://www.miit.gov.cn/", r"/art/20\d\d/art_\w+\.html"),
                           ("China Customs", "http://english.customs.gov.cn/", r"/Statics/[\w-]+\.html|/news/.*\.html")]:
        try:
            for h, t in page_links(url, pat):
                out.append(item(name, re.sub(r"\W", "", h[-40:]), "Policy", time.time(), t, "", h, {"page": h}))
        except Exception as e:
            print(f"  {name}: {e!r}")
    return out


def federal_register(since):
    out = []
    for agency in ["industry-and-security-bureau", "trade-representative-office-of-united-states", "international-trade-administration",
                   "foreign-assets-control-office"]:
        fields = "".join(f"&fields%5B%5D={f}" for f in ("title", "type", "abstract", "document_number", "html_url", "publication_date", "raw_text_url"))
        d = get_json(f"https://www.federalregister.gov/api/v1/documents.json?conditions%5Bagencies%5D%5B%5D={agency}&order=newest&per_page=20{fields}")
        for r in d.get("results", []):
            ts = int(datetime.strptime(r["publication_date"], "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())
            out.append(item("US Federal Register", r["document_number"], "Policy", max(ts, since), r["title"],
                            f"{r['type']}. {r.get('abstract') or ''}", r["html_url"], {"text_url": r.get("raw_text_url") or r["html_url"]}))
    return out


# ---------- video and transcripts ----------

YOUTUBE_CHANNELS = [  # handles; channel ids are looked up once and cached
    "@CNBC", "@CNBCtelevision", "@markets", "@YahooFinance", "@FoxBusiness", "@WSJNews",
    "@NVIDIA", "@AMD", "@intel", "@MicronTechnology", "@Qualcomm", "@arm", "@ASML",
    "@DwarkeshPatel", "@Bg2Pod", "@AcquiredFM", "@a16z", "@NoPriorsPodcast", "@LexFridman", "@20VC", "@AllInPodcast",
    "@Asianometry", "@TechTechPotato", "@ServeTheHomeVideo", "@MorganStanley", "@GoldmanSachs", "@NikkeiAsia",
]


def youtube(since, cache):
    out = []
    ids = cache.setdefault("youtube_ids", {})
    for handle in YOUTUBE_CHANNELS:
        try:
            if handle not in ids:
                ids[handle] = None
                page = http_get(f"https://www.youtube.com/{handle}", headers={"Accept-Language": "en-US,en;q=0.9"}).decode("utf-8", "replace")
                m = re.search(r'"(?:externalId|channelId)":"(UC[\w-]{22})"', page)
                ids[handle] = m.group(1) if m else None
            if not ids[handle]:
                continue
            feed = ET.fromstring(http_get(f"https://www.youtube.com/feeds/videos.xml?channel_id={ids[handle]}"))
            ns = {"a": "http://www.w3.org/2005/Atom", "m": "http://search.yahoo.com/mrss/", "yt": "http://www.youtube.com/xml/schemas/2015"}
            channel = feed.findtext("a:title", "", ns)
            for e in feed.findall("a:entry", ns):
                vid = e.findtext("yt:videoId", "", ns)
                ts = int(datetime.fromisoformat(e.findtext("a:published", "", ns)).timestamp())
                desc = e.findtext("m:group/m:description", "", ns)
                out.append(item("YouTube", vid, "Video", ts, f"{channel}: {e.findtext('a:title', '', ns)}", desc,
                                f"https://www.youtube.com/watch?v={vid}", {"full": desc}))
        except Exception as e:
            print(f"  YouTube {handle}: {e!r}")
    return out


def earnings_calls(since):
    out = []
    for h, t in page_links("https://www.fool.com/earnings-call-transcripts/", r"/earnings/call-transcripts/20\d\d/\d\d/\d\d/"):
        y, mth, d = re.search(r"/(20\d\d)/(\d\d)/(\d\d)/", h).groups()
        ts = max(int(datetime(int(y), int(mth), int(d), tzinfo=timezone.utc).timestamp()), since)
        out.append(item("Earnings call", h.rstrip("/").split("/")[-1], "Transcript", ts, t[:200], "", h, {"page": h, "long": True}))
    return out


# ---------- registry ----------

SOURCES = {   # name -> (fetcher, timestamped?)
    "CLS": (cls, True), "EastMoney": (eastmoney_flash, True), "Tonghuashun": (ths_flash, True), "Wallstreetcn": (wallstreetcn, True),
    "Sina": (sina_flash, True), "Yicai": (yicai_flash, True), "36Kr": (kr36_flash, True), "Xueqiu": (xueqiu_flash, True),
    "Caixin": (caixin, False), "Caixin Global": (caixin_global, False), "Caijing": (caijing, False),
    "SSE/SZSE filings": (a_share_filings, True), "HKEX filings": (hkex_filings, True), "SEC EDGAR": (sec_filings, True),
    "China ministries": (gov_cn, False), "US Federal Register": (federal_register, False),
    "YouTube": (youtube, True), "Earnings calls": (earnings_calls, False),
}


# ---------- full text for items that pass triage ----------

SEC_KEYWORDS = re.compile(r"China|Chinese|PRC|Taiwan|Hong Kong|export control|Entity List|tariff|sanction|supplier|sole source|single source|"
                          r"supply chain|rare earth|gallium|germanium|foundry|TSMC|SMIC|Huawei|BIS|CHIPS Act|geopolit", re.I)


def sec_document(index_url, form):
    idx = http_get(index_url, headers=SEC_HEADERS).decode("utf-8", "replace")
    docs = re.findall(r'href="(/Archives/edgar/data/[^"]+\.(?:htm|html|xml|txt))"', idx)
    if form == "4":
        xml_doc = next((d for d in docs if d.endswith(".xml") and "/xsl" not in d), None)   # raw XML, not the rendered page
        if not xml_doc:
            return ""
        root = ET.fromstring(http_get("https://www.sec.gov" + xml_doc, headers=SEC_HEADERS))
        owner = root.findtext(".//reportingOwner/reportingOwnerId/rptOwnerName", "")
        title = root.findtext(".//reportingOwnerRelationship/officerTitle", "") or ("Director" if root.findtext(".//isDirector") in ("1", "true") else "")
        lines = [f"Insider: {owner} ({title}) at {root.findtext('.//issuer/issuerName', '')} ({root.findtext('.//issuer/issuerTradingSymbol', '')})"]
        for t in root.findall(".//nonDerivativeTransaction"):
            code = t.findtext(".//transactionCoding/transactionCode", "")
            shares = t.findtext(".//transactionShares/value", "")
            price = t.findtext(".//transactionPricePerShare/value", "")
            ad = t.findtext(".//transactionAcquiredDisposedCode/value", "")
            after = t.findtext(".//sharesOwnedFollowingTransaction/value", "")
            date = t.findtext(".//transactionDate/value", "")
            lines.append(f"{date} code {code} ({'sold/disposed' if ad == 'D' else 'acquired'}) {shares} shares at ${price}; owns {after} after")
        plan = root.findtext(".//aff10b5One", "")
        if plan in ("1", "true"):
            lines.append("Made under a Rule 10b5-1 trading plan.")
        for fn in root.findall(".//footnote")[:4]:
            lines.append("Footnote: " + (fn.text or "").strip())
        return "\n".join(lines)
    main = next((d for d in docs if not d.endswith((".xml", ".txt")) and "index" not in d), None)
    if not main:
        return ""
    text = strip_html(http_get("https://www.sec.gov" + main, headers=SEC_HEADERS).decode("utf-8", "replace"))
    if len(text) <= DETAIL_CHARS:
        return text
    # long reports: keep the opening plus paragraphs about China, export controls and suppliers
    paras = [p for p in text.split("\n") if len(p) > 80]
    picked = [p for p in paras if SEC_KEYWORDS.search(p)]
    return (text[:2500] + "\n...\n" + "\n".join(picked))[:DETAIL_CHARS * 2]


def _long_strings(node, out):
    if isinstance(node, str):
        if len(node) > 300:
            out.append(node)
    elif isinstance(node, dict):
        for v in node.values():
            _long_strings(v, out)
    elif isinstance(node, list):
        for v in node:
            _long_strings(v, out)


def article_text(raw):
    """Main text of an article page: its paragraphs, else text embedded in the page's JSON (sites that
    render with JavaScript), else the meta description. Skips navigation and boilerplate."""
    paras = [strip_html(p) for p in re.findall(r"(?is)<p[^>]*>(.*?)</p>", raw)]
    text = "\n".join(p for p in paras if len(p) >= 25)
    if len(text) >= 400:
        return text
    blobs = []
    for js in re.findall(r'(?is)<script[^>]*type="application/(?:json|ld\+json)"[^>]*>(.*?)</script>', raw):
        try:
            _long_strings(json.loads(js), blobs)
        except ValueError:
            pass
    if blobs:
        return "\n".join(strip_html(b) for b in sorted(blobs, key=len, reverse=True)[:3])
    m = re.search(r'(?is)<div[^>]+(?:TRS_Editor|article-content|article_content|content)[^>]*>(.*?)</div>', raw)
    if m and len(strip_html(m.group(1))) >= 200:
        return strip_html(m.group(1))
    desc = re.search(r'(?is)<meta[^>]+(?:name|property)="(?:og:)?description"[^>]+content="([^"]*)"', raw)
    return (text + "\n" + html.unescape(desc.group(1)) if desc else text).strip()


def details(it):
    d = it.get("detail") or {}
    try:
        if "full" in d:
            return d["full"]
        if "pdf" in d:
            return pdf_text(http_get(d["pdf"], timeout=40))[:DETAIL_CHARS]
        if "sec_index" in d:
            return sec_document(d["sec_index"], d.get("form", ""))[:DETAIL_CHARS * 2]
        if "text_url" in d:
            return strip_html(http_get(d["text_url"]).decode("utf-8", "replace"))[:DETAIL_CHARS]
        if "page" in d:
            text = article_text(http_get(d["page"]).decode("utf-8", "replace"))
            anchor = text.find(it["title"][:12]) if len(it["title"]) >= 12 else -1
            if anchor > 0:   # drop site navigation before the article's own headline
                text = text[anchor:]
            return text[:DETAIL_CHARS * (3 if d.get("long") else 1)]
    except Exception as e:
        return f"(full text unavailable: {e!r})"
    return ""


if __name__ == "__main__":   # health check: python3 sources.py
    import sys
    cache = {}
    since = int(time.time()) - 3 * 3600
    for name, (fn, _) in SOURCES.items():
        t = time.time()
        try:
            items = fn(since, cache) if fn is youtube else fn(since)
            recent = [i for i in items if i["ctime"] >= since]
            print(f"OK   {name:20s} {len(items):4d} items, {len(recent):4d} in last 3h, {time.time()-t:5.1f}s")
            for i in sorted(items, key=lambda i: -i["ctime"])[:2]:
                print(f"       {datetime.fromtimestamp(i['ctime'], BJ):%m-%d %H:%M} | {i['title'][:70]} | {i['text'][:60]!r} | {i['url'][:80]}")
            if items and "--details" in sys.argv:
                d = details(sorted(items, key=lambda i: -i["ctime"])[0])
                print(f"       DETAIL ({len(d)} chars):", d[:300].replace("\n", " "))
        except Exception as e:
            print(f"FAIL {name:20s} {e!r}"[:300])
        sys.stdout.flush()
    print("youtube channels resolved:", sum(1 for v in cache.get("youtube_ids", {}).values() if v), "/", len(YOUTUBE_CHANNELS),
          "missing:", [k for k, v in cache.get("youtube_ids", {}).items() if not v])
