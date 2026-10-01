# Task: look for one specific post in the CLS Telegraph feed

We are checking whether the CLS Telegraph (财联社电报) feed contains a post about 光智科技 (Vital Optics Technology, 300489.SZ) and 6-inch indium phosphide (磷化铟) substrate orders. Accuracy matters more than speed. Never invent or correct text.

Fetch pages ONLY with the **WebFetch** tool (load it with ToolSearch query `select:WebFetch` if it is not in your tool list). Do NOT use curl, python or any other way to fetch: the sandbox network blocks cls.cn by policy. Do not try other sites.

Use exactly this WebFetch prompt for every page:

> This is a JSON API response. Check EVERY item in data.roll_data, reading the full title, content and brief of each. First line: `COUNT=<number of items>` and `MIN_CTIME=<smallest ctime>`. Then, for every item whose title, content or brief contains ANY of these strings: 光智, 磷化铟, 衬底, 300489, InP, 铟, 化合物半导体, 砷化镓, 锗, 镓 — output `### id | ctime (raw integer) | matched strings` and on the next line the item's complete content field, verbatim, unabridged, original Chinese. If no item matches, output `NONE`.

If a fetch errors or times out, run `sleep 6` in Bash and retry the same URL, up to 5 times.

Your task message says which MODE you are in.

## MODE list
You are given a URL list file (each line: `<cursor> <url>`). Fetch every URL in the list, in order.

## MODE backward
You are given START and END (unix epoch seconds). Get a signed URL with Bash: `python3 /home/claude/sign_url.py <CURSOR> 20` (prints the cursor and a URL returning the 20 posts just OLDER than CURSOR). Begin with CURSOR = END. After each page set CURSOR = MIN_CTIME + 1 and fetch again. Stop when MIN_CTIME < START, or after 30 pages, whichever comes first.

## Output
Append to your output file (plain UTF-8 text), one block per page:

```
@@PAGE cursor=<cursor> count=<COUNT> min_ctime=<MIN_CTIME>
### <id> | <ctime> | <matched strings>
<complete content exactly as returned>
... or the single word NONE ...
```

Write `@@PAGE cursor=<cursor> count=FAILED` for a page that cannot be fetched after 5 tries.

Final reply, a few lines only: pages done, pages failed, the smallest ctime reached, and the ids of any hits that mention 光智 or 磷化铟 (or "no such post found").
