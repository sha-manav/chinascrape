# Task: independent keyword scan of CLS Telegraph feed pages

You are doing a verification pass. Your task message names a URL list file (`/home/claude/scan/urls_N.txt`) and an output file (`/home/claude/scan/hits_N.txt`). Each line of the URL list is `<cursor> <url>`.

For EACH url in the list, in order:

1. Fetch that exact URL with the **WebFetch** tool (if WebFetch is not in your tool list, load it with ToolSearch using the query `select:WebFetch`). Do NOT fetch with curl, python or anything else: the sandbox network blocks cls.cn by policy and only WebFetch is permitted. Use exactly this WebFetch prompt:

   > This is a JSON API response. Check EVERY item in data.roll_data. First line: `COUNT=<number of items in roll_data>`. Then output one line `id | ctime (raw integer) | matched strings | first 60 characters of content` for every item whose title, content or brief contains ANY of these strings (case-insensitive substring match): 磷化铟, 铟, 镓, 锗, 稀土, 出口管制, 管制, 实体清单, 光刻, EUV, DUV, ASML, 阿斯麦, 光罩, 掩模, 掩膜, 上海微电子, 昇腾, DeepSeek, 海力士, 中芯国际, 华虹, 台积电, 光模块, 光芯片, 硅光, CPO, 激光器, 光纤, 光通信, 旭创, 新易盛, 天孚, 晶圆, 封装, 存储芯片, HBM, 国产替代. If no item matches, output `NONE` after the COUNT line. Do not output items that match none of the strings.

2. If a fetch errors or times out, run `sleep 6` in Bash and retry the same URL, up to 5 times.

Append the results for each page to the output file in this layout (plain UTF-8 text):

```
@@PAGE cursor=<cursor> count=<COUNT>
<id>|<ctime>|<matched strings>|<snippet>
... one line per hit, or the single word NONE ...
```

Copy ids, ctimes and text exactly as returned; never invent or correct anything. Do every URL in the list; do not skip any. If a page cannot be fetched after 5 tries, write `@@PAGE cursor=<cursor> count=FAILED` for it.

Final reply: one or two lines only: pages done, pages failed, total hit lines. Do not paste the hits into your reply.
