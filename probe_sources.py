"""Reachability probe for candidate sources: prints status, size and a snippet for each URL.
Run on GitHub Actions (probe.yml), since many Chinese sites block other networks."""
import json, sys, time, urllib.request, urllib.error, http.cookiejar
from datetime import datetime, timedelta, timezone

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
SEC_UA = "chinascrape research bot (github.com/sha-manav/chinascrape) chinascrape-bot@users.noreply.github.com"
now = datetime.now(timezone(timedelta(hours=8)))
d0, d1 = (now - timedelta(days=2)).strftime("%Y-%m-%d"), now.strftime("%Y-%m-%d")
y0, y1 = d0.replace("-", ""), d1.replace("-", "")

PROBES = [
    # name, url, extra headers, POST body (bytes) or None
    ("eastmoney_724", "https://np-weblist.eastmoney.com/comm/web/getFastNewsList?client=web&biz=web_724&fastColumn=102&sortEnd=&pageSize=50&req_trace=1", {}, None),
    ("eastmoney_ann", "https://np-anotice-stock.eastmoney.com/api/security/ann?sr=-1&page_size=50&page_index=1&ann_type=A&client_source=web&f_node=0&s_node=0", {}, None),
    ("ths_724", "https://news.10jqka.com.cn/tapp/news/push/stock/?page=1&tag=&track=website&pagesize=50", {}, None),
    ("xueqiu_live", "https://xueqiu.com/statuses/livenews/list.json?since_id=-1&max_id=-1&count=20", {"Referer": "https://xueqiu.com/"}, "COOKIE:https://xueqiu.com/"),
    ("xueqiu_hot", "https://xueqiu.com/statuses/hot/listV2.json?since_id=-1&max_id=-1&size=15", {"Referer": "https://xueqiu.com/"}, "COOKIE:https://xueqiu.com/"),
    ("wallstreetcn_live", "https://api-one-wscn.awtmt.com/apiv1/content/lives?channel=global-channel&limit=50", {}, None),
    ("sina_724", "https://zhibo.sina.com.cn/api/zhibo/feed?page=1&page_size=50&zhibo_id=152", {}, None),
    ("yicai_brief", "https://www.yicai.com/api/ajax/getbrieflist?page=1&pagesize=30", {"Referer": "https://www.yicai.com/brief/"}, None),
    ("caixin_home", "https://www.caixin.com/", {}, None),
    ("caixin_global_rss", "https://www.caixinglobal.com/rss/news.xml", {}, None),
    ("caixin_global_home", "https://www.caixinglobal.com/news/", {}, None),
    ("caijing_home", "https://www.caijing.com.cn/", {}, None),
    ("36kr_feed", "https://36kr.com/feed", {}, None),
    ("36kr_newsflash", "https://36kr.com/feed-newsflash", {}, None),
    ("cninfo_szse", "https://www.cninfo.com.cn/new/hisAnnouncement/query", {"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8", "Referer": "https://www.cninfo.com.cn/"},
        f"pageNum=1&pageSize=30&column=szse&tabName=fulltext&plate=&stock=&searchkey=&secid=&category=&trade=&seDate={d0}~{d1}&sortName=&sortType=&isHLtitle=true".encode()),
    ("szse_ann", "https://www.szse.cn/api/disc/announcement/annList", {"Content-Type": "application/json", "Referer": "https://www.szse.cn/disclosure/listed/notice/"},
        json.dumps({"seDate": [d0, d1], "channelCode": ["listedNotice_disc"], "pageSize": 30, "pageNum": 1}).encode()),
    ("sse_ann", f"https://query.sse.com.cn/security/stock/queryCompanyBulletin.do?isPagination=true&pageHelp.pageSize=25&pageHelp.pageNo=1&beginDate={d0}&endDate={d1}&productId=&securityType=0101,120100,020100,020200,120200&reportType2=&reportType=ALL", {"Referer": "https://www.sse.com.cn/"}, None),
    ("hkex_latest_e", "https://www1.hkexnews.hk/ncms/json/eds/lcisehk1relsde_1.json", {}, None),
    ("hkex_latest_c", "https://www1.hkexnews.hk/ncms/json/eds/lcisehk1relsdc_1.json", {}, None),
    ("hkex_titlesearch", f"https://www1.hkexnews.hk/search/titleSearchServlet.do?sortDir=0&sortByOptions=DateTime&category=0&market=SEHK&stockId=-1&documentType=-1&fromDate={y0}&toDate={y1}&title=&searchType=0&t1code=-2&t2Gcode=-2&t2code=-2&rowRange=100&lang=E", {}, None),
    ("sgx_ann", f"https://api.sgx.com/announcements/v1.1/?periodstart={y0}_160000&periodend={y1}_155959&pagestart=0&pagesize=20", {"Origin": "https://www.sgx.com", "Referer": "https://www.sgx.com/"}, None),
    ("sec_current_8k", "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=8-K&company=&dateb=&owner=include&start=0&count=40&output=atom", {"User-Agent": SEC_UA}, None),
    ("sec_current_form4", "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=4&company=&dateb=&owner=only&start=0&count=40&output=atom", {"User-Agent": SEC_UA}, None),
    ("sec_efts", f"https://efts.sec.gov/LATEST/search-index?q=%22export%20controls%22%20China&dateRange=custom&startdt={d0}&enddt={d1}", {"User-Agent": SEC_UA}, None),
    ("sec_tickers", "https://www.sec.gov/files/company_tickers.json", {"User-Agent": SEC_UA}, None),
    ("fedreg_bis", "https://www.federalregister.gov/api/v1/documents.json?conditions%5Bagencies%5D%5B%5D=industry-and-security-bureau&order=newest&per_page=10", {}, None),
    ("mofcom_home", "https://www.mofcom.gov.cn/", {}, None),
    ("mofcom_en", "https://english.mofcom.gov.cn/", {}, None),
    ("customs_home", "http://www.customs.gov.cn/", {}, None),
    ("miit_home", "https://www.miit.gov.cn/", {}, None),
    ("youtube_rss_cnbc", "https://www.youtube.com/feeds/videos.xml?channel_id=UCvJJ_dzjViJCoLf5uKUTwoA", {}, None),
    ("youtube_watch", "https://www.youtube.com/watch?v=jfKfPfyJRdk", {}, None),
    ("fool_transcripts", "https://www.fool.com/earnings-call-transcripts/", {}, None),
    ("cls_roll", "https://www.cls.cn/telegraph", {}, None),
]


def fetch(url, headers, body):
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    if isinstance(body, str) and body.startswith("COOKIE:"):
        opener.open(urllib.request.Request(body[7:], headers={"User-Agent": UA}), timeout=20).read()
        body = None
    h = {"User-Agent": UA, "Accept": "*/*", "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"} | headers
    return opener.open(urllib.request.Request(url, data=body, headers=h), timeout=25)


ok = 0
for name, url, headers, body in PROBES:
    t = time.time()
    try:
        r = fetch(url, headers, body)
        data = r.read()
        text = data[:400].decode("utf-8", "replace").replace("\n", " ")
        print(f"OK   {name:20s} {r.status} {len(data):>8d}B {time.time()-t:4.1f}s {r.headers.get('Content-Type','')[:30]} | {text}")
        ok += 1
    except urllib.error.HTTPError as e:
        print(f"FAIL {name:20s} HTTP {e.code} | {e.read()[:200].decode('utf-8','replace')}")
    except Exception as e:
        print(f"FAIL {name:20s} {e!r}")
    sys.stdout.flush()
print(f"{ok}/{len(PROBES)} reachable")

try:
    from youtube_transcript_api import YouTubeTranscriptApi
    tr = YouTubeTranscriptApi().fetch("jfKfPfyJRdk")
    print("OK   youtube_transcript", len(tr.snippets), "snippets")
except Exception as e:
    print("FAIL youtube_transcript", repr(e)[:300])
