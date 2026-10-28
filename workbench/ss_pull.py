"""卖家精灵直连拉数据（Hermes 里卖家精灵 MCP 没加载上、或连接报错时的兜底）。

用法：python3 workbench/ss_pull.py <ASIN> [--pages 10] [--no-detail]
- 直连 https://mcp.sellersprite.com/mcp（tools/call），key 读 Hermes voc 配置，不打印
- 每次调用最多重试 3 次（卖家精灵偶尔 500、单次 15–25 秒）；重试不重复扣费，成功才算一次
- 结果写 <VOC_DATA_DIR>/<ASIN>/detail.raw.json、reviews-<页>.raw.json；评论不足一页就提前停
- 最后打印实际调用次数，算在用户确认的预算里
"""
import json
import pathlib
import re
import sys
import time
import urllib.error
import urllib.request

import os
ROOT = pathlib.Path(os.environ.get("VOC_DATA_DIR", pathlib.Path(__file__).resolve().parent.parent / "现场分析")).expanduser()
CFG = pathlib.Path.home() / ".hermes/profiles" / os.environ.get("VOC_HERMES_PROFILE", "voc") / "config.yaml"
asin = sys.argv[1].upper()
pages = int(sys.argv[sys.argv.index("--pages") + 1]) if "--pages" in sys.argv else 10
out = ROOT / asin
out.mkdir(exist_ok=True)
m = re.search(r"sellersprite:\n\s+url: (\S+)\n\s+headers:\n\s+secret-key: (\S+)", CFG.read_text(encoding="utf-8"))
URL, KEY = m.group(1), m.group(2).strip("'\"")
calls = 0


def call(name, args, fname):
    global calls
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args}}).encode()
    hdr = {"secret-key": KEY, "Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    for attempt in range(3):
        try:
            raw = urllib.request.urlopen(urllib.request.Request(URL, data=body, headers=hdr), timeout=120).read().decode()
            calls += 1
            (out / fname).write_text(raw, encoding="utf-8")
            text = json.loads(raw)["result"]["content"][0]["text"]
            return json.loads(text)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, KeyError, json.JSONDecodeError) as e:
            err = getattr(e, "code", e)
            print(f"  {fname} 第 {attempt + 1} 次失败：{err}", file=sys.stderr)
            time.sleep(5 * (attempt + 1))
    (out / (fname + ".error")).write_text("3 次都失败", encoding="utf-8")
    return None


if "--no-detail" not in sys.argv:
    d = call("asin_detail", {"marketplace": "US", "asin": asin}, "detail.raw.json")
    print("商品详情：", "成功" if d else "失败")
got = 0
for page in range(1, pages + 1):
    d = call("review", {"marketplace": "US", "asin": asin, "page": page, "size": 20,
                        "returnFields": "title,content,date,star,skus,vine,verified,likes"}, f"reviews-{page}.raw.json")
    items = ((d or {}).get("data") or {}).get("items") or ((d or {}).get("data") or {}).get("list") or []
    got += len(items)
    print(f"评论第 {page} 页：{len(items) if d else '失败'}")
    if d and len(items) < 20:
        break
print(f"完成：实际调用卖家精灵 {calls} 次，拿到评论约 {got} 条 → {out}")
