# Task: collect CLS Telegraph (财联社电报) posts for one time range and pick out watchlist-relevant ones

You are one of several workers, each covering a different time range of the CLS Telegraph news feed. Your range (NAME, START, END as unix epoch seconds) is given in your task message. START is inclusive, END is exclusive. Beijing time = UTC+8.

Accuracy and completeness matter more than speed. Never invent, guess, translate, paraphrase, or "fix" post text. Numbers must be exactly as in the source.

## How to fetch a page of posts

1. Get a signed URL with Bash: `python3 /home/claude/sign_url.py <CURSOR> 20`
   It prints the cursor and a URL. The API returns the 20 posts immediately OLDER than CURSOR, newest first.
2. Fetch that exact URL with the **WebFetch** tool. If WebFetch is not in your tool list, load it first with ToolSearch using the query `select:WebFetch`.
   Do NOT fetch with curl, python, or anything else: the sandbox network blocks cls.cn by policy and only WebFetch is permitted. Do not try other sites or mirrors.
   Use exactly this WebFetch prompt:

   > This is a JSON API response. Do not summarize, do not translate. First line: the errno/error value and the number of items in data.roll_data. Then for EVERY item in data.roll_data, in order, output one block: `### id | ctime (raw integer)` followed on the next line by the item's content field copied verbatim and unabridged (full original Chinese text, never cut long items short). Output all items; do not stop early.

3. Start with CURSOR = END. After each page, set the next CURSOR = (smallest ctime on that page) + 1 and fetch again. Stop once the smallest ctime on a page is < START. The "+1" makes the boundary post appear again on the next page; that is expected. De-duplicate by id.
4. If a fetch errors or times out: run `sleep 6` in Bash and retry the same URL. If it fails again, retry with CURSOR+1 (a fresh URL), then CURSOR+2, with a sleep before each. Try up to 6 times before giving up on a page. If you must give up, stop and report exactly which cursor failed.
5. Sanity-check each page: errno should be 0 and there should be 20 `###` blocks (fewer than 20 only if the feed really has fewer). If the output is cut off (fewer blocks than the stated item count), fetch the same URL again with a prompt asking only for the missing items, e.g. "Output items 11 to 20 of data.roll_data as: `### id | ctime` then the full content verbatim."

## Which posts are relevant

Keep only posts with START <= ctime < END that are **substantively** about one of these:

1. AI: 人工智能, AI, 大模型, 算力, AI服务器, 智算中心, model releases, AI capex, AI chips and data centers
2. CHIPS: 芯片, 半导体, 集成电路, 晶圆, 存储芯片, HBM, 先进封装, 国产替代, foundries (台积电, 中芯国际, 华虹), GPU makers (英伟达, AMD, 华为昇腾, 寒武纪), chip export controls
3. InP: 磷化铟, indium phosphide substrates/wafers/lasers, supply and pricing, export controls on indium, gallium, germanium
4. PHOTONICS: 光模块, 光通信, 硅光, 光芯片, CPO/共封装光学, 激光器, EML, VCSEL, 800G/1.6T transceivers, 光纤, optical module makers (中际旭创, 新易盛, 天孚通信, etc.)
5. LITHO: 光刻, 光刻机, EUV, DUV, 光刻胶, ASML, 上海微电子, photomasks

Include: company announcements, earnings, orders, prices, policy, export controls, supply-chain news, capacity expansions, M&A, and notable sector stock moves (板块异动) in these areas.
Exclude: passing keyword mentions, energy storage (储能) as opposed to memory chips, and general market wrap-ups.

If you are unsure whether a post is substantive or only a passing mention, INCLUDE it and explain briefly in its `note`. A later pass makes the final cut, so lean towards including borderline posts. Mark promotional teasers for paid content (posts that talk about "这家公司" without naming it) with `note=teaser`.

## Truncation check (important)

The fetch tool sometimes cuts long posts short (text ends mid-sentence, without closing punctuation). For EVERY post you mark relevant whose text looks cut off, fetch the same page URL again with a prompt like:

> Output the complete content field of the item whose id is <ID>, verbatim and unabridged, original Chinese, nothing else.

and use the complete text. If you cannot get the full text after 2 tries, keep what you have and put `truncated` in the note.

## Output file

Write `/home/claude/slices/<NAME>.txt` (plain UTF-8 text) in exactly this layout:

```
RANGE <NAME> start=<START> end=<END>
@@PAGES
cursor=<cursor used> count=<items returned> max_ctime=<largest ctime on page> min_ctime=<smallest ctime on page>
... one line per fetched page, in the order fetched ...
@@INDEX
<id>|<ctime>|<Y or N>|<first ~20 characters of the post text>
... one line for EVERY post with START <= ctime < END, newest first; Y = relevant, N = not ...
@@POSTS
@@POST id=<id> ctime=<ctime> cat=<AI|CHIPS|InP|PHOTONICS|LITHO, comma-separated if more than one> note=<short note or ->
<complete post text, exactly as fetched, may span several lines>
@@END
... one block per relevant post, newest first ...
```

## Your final reply

Reply with only a few lines: pages fetched, posts in range, posts marked relevant, the smallest and largest ctime you covered, and any problems (failed fetches, possible gaps, posts still truncated). Do not paste the posts into your reply; they are in the file.
