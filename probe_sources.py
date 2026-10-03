"""Source probe: fetches candidate endpoints from a GitHub runner and prints their structure,
so parsers can be written against real payloads. Run via the "Source probe" workflow."""
import json, re, sys, time, urllib.request, urllib.error, http.cookiejar
from datetime import datetime, timedelta, timezone

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
now = datetime.now(timezone(timedelta(hours=8)))
d0, d1 = (now - timedelta(days=1)).strftime("%Y-%m-%d"), now.strftime("%Y-%m-%d")


def get(url, headers=None, body=None, cookie_from=None):
    jar = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    if cookie_from:
        op.open(urllib.request.Request(cookie_from, headers={"User-Agent": UA}), timeout=20).read()
    h = {"User-Agent": UA, "Accept": "*/*", "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"} | (headers or {})
    r = op.open(urllib.request.Request(url, data=body, headers=h), timeout=25)
    return r.status, r.read()


def show(name, fn):
    print(f"\n===== {name}")
    try:
        fn()
    except urllib.error.HTTPError as e:
        print("HTTP", e.code, e.read()[:200])
    except Exception as e:
        print("ERR", repr(e)[:300])
    sys.stdout.flush()


def js(url, path, **kw):
    """Print the first two items of the list at `path` in a JSON response."""
    st, b = get(url, **kw)
    d = json.loads(b)
    for k in path:
        d = d[k] if not isinstance(d, str) else json.loads(d)[k]
    if isinstance(d, str):
        d = json.loads(d)
    print(st, "items:", len(d))
    for it in d[:2]:
        print(json.dumps(it, ensure_ascii=False)[:1500])


def links(url, pat, n=12, enc=None, **kw):
    """Print links matching a regex on an HTML page."""
    st, b = get(url, **kw)
    html = b.decode(enc or "utf-8", "replace")
    found = re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', html, re.S)
    hits = [(h, re.sub(r"<[^>]+>|\s+", " ", t).strip()) for h, t in found if re.search(pat, h)]
    print(st, len(html), "chars;", len(hits), "matching links")
    for h, t in hits[:n]:
        print("  ", h, "|", t[:80])


show("eastmoney_724", lambda: js("https://np-weblist.eastmoney.com/comm/web/getFastNewsList?client=web&biz=web_724&fastColumn=102&sortEnd=&pageSize=50&req_trace=1", ["data", "fastNewsList"]))
show("eastmoney_ann", lambda: js("https://np-anotice-stock.eastmoney.com/api/security/ann?sr=-1&page_size=50&page_index=1&ann_type=A&client_source=web&f_node=0&s_node=0", ["data", "list"]))
show("ths_724", lambda: js("https://news.10jqka.com.cn/tapp/news/push/stock/?page=1&tag=&track=website&pagesize=50", ["data", "list"]))
show("wallstreetcn", lambda: js("https://api-one-wscn.awtmt.com/apiv1/content/lives?channel=global-channel&limit=50", ["data", "items"]))
show("sina_724", lambda: js("https://zhibo.sina.com.cn/api/zhibo/feed?page=1&page_size=50&zhibo_id=152", ["result", "data", "feed", "list"]))
show("yicai", lambda: js("https://www.yicai.com/api/ajax/getbrieflist?page=1&pagesize=30", [], headers={"Referer": "https://www.yicai.com/brief/"}))
show("cninfo", lambda: js("https://www.cninfo.com.cn/new/hisAnnouncement/query", ["announcements"],
     headers={"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8", "Referer": "https://www.cninfo.com.cn/"},
     body=f"pageNum=1&pageSize=30&column=szse&tabName=fulltext&plate=&stock=&searchkey=&secid=&category=&trade=&seDate={d0}~{d1}&sortName=&sortType=&isHLtitle=true".encode()))
show("hkex_e", lambda: js("https://www1.hkexnews.hk/ncms/json/eds/lcisehk1relsde_1.json", ["newsInfoLst"]))
show("fedreg", lambda: js("https://www.federalregister.gov/api/v1/documents.json?conditions%5Bagencies%5D%5B%5D=industry-and-security-bureau&order=newest&per_page=5", ["results"]))
show("caixin_links", lambda: links("https://www.caixin.com/", r"caixin\.com/20\d\d-\d\d-\d\d/\d+\.html"))
show("caixin_global_links", lambda: links("https://www.caixinglobal.com/news/", r"caixinglobal\.com/20\d\d-\d\d-\d\d/"))
show("caijing_links", lambda: links("https://www.caijing.com.cn/", r"caijing\.com\.cn/20\d{6}/\d+\.shtml"))
show("mofcom_links", lambda: links("https://www.mofcom.gov.cn/", r"/(xwfb|zwgk|article)/.*\.html"))
show("miit_links", lambda: links("https://www.miit.gov.cn/", r"/(xwdt|zwgk|jgsj)/.*art_.*\.html"))
show("fool_links", lambda: links("https://www.fool.com/earnings-call-transcripts/", r"/earnings/call-transcripts/20"))
show("youtube_rss", lambda: print(get("https://www.youtube.com/feeds/videos.xml?channel_id=UCvJJ_dzjViJCoLf5uKUTwoA")[1][:1500].decode()))

# blocked-source workarounds
for ua in ["Sample Company Name AdminContact@samplecompany.com", "chinascrape bot@chinascrape.dev",
           "Mozilla/5.0 (compatible; chinascrape/1.0; +https://github.com/sha-manav/chinascrape) bot@chinascrape.dev"]:
    show(f"sec[{ua[:20]}]", lambda ua=ua: print(get("https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=8-K&count=10&output=atom",
                                                     headers={"User-Agent": ua, "Accept-Encoding": "identity", "Host": "www.sec.gov"})[1][:600]))
show("sec_data_api", lambda: print(get("https://data.sec.gov/submissions/CIK0001045810.json", headers={"User-Agent": "Sample Company Name AdminContact@samplecompany.com"})[1][:300]))
show("sec_efts", lambda: print(get("https://efts.sec.gov/LATEST/search-index?q=%22China%22&forms=8-K", headers={"User-Agent": "Sample Company Name AdminContact@samplecompany.com"})[1][:300]))
show("36kr_gateway", lambda: print(get("https://gateway.36kr.com/api/mis/nav/newsflash/flow", headers={"Content-Type": "application/json", "Referer": "https://36kr.com/"},
     body=json.dumps({"partner_id": "web", "timestamp": int(time.time() * 1000), "param": {"pageSize": 20, "pageEvent": 0, "siteId": 1, "platformId": 2}}).encode())[1][:800].decode()))
show("36kr_rsshub", lambda: print(get("https://rsshub.app/36kr/newsflashes")[1][:500]))
show("xueqiu_cookie_live", lambda: print(get("https://xueqiu.com/statuses/livenews/list.json?since_id=-1&max_id=-1&count=10",
     headers={"Referer": "https://xueqiu.com/", "X-Requested-With": "XMLHttpRequest"}, cookie_from="https://xueqiu.com/hq")[1][:500]))
show("customs_en", lambda: print(get("http://english.customs.gov.cn/")[1][:300]))
show("sgx_rss", lambda: print(get("https://links.sgx.com/1.0.0/corporate-announcements/rss")[1][:300]))
show("sgx_api_token", lambda: print(get("https://api2.sgx.com/announcements/v1.1/?periodstart=20261001_160000&periodend=20261003_155959&pagestart=0&pagesize=5")[1][:300]))
