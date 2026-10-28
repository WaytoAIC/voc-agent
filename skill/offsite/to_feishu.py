"""站外 VOC · Reddit → 飞书多维表格，一行一个相关讨论串（可选步骤）。

用法：python3 to_feishu.py voc-reports/<ASIN>/offsite [--dry-run] [--as bot|user]
- 读 config.json 的 feishu.base / feishu.table；没填就不写
- 表字段：讨论串、板块、发帖日期、原帖链接、评论数、抱怨、好评、人群、替代方案、品牌、一句话、原声、采集通道、采集批次、写入方
  （抱怨 / 好评 / 人群 / 替代方案 / 采集通道 是多选，选项要先在表里建好；写入方单选：VOC Agent / 人工 / 其他 Agent）
- 已在表里的原帖链接跳过，重复跑不会重复写
- lark-cli：环境变量 LARK_CLI，否则用 PATH 里的 lark-cli；用哪个身份由 --as 决定（默认 bot）
"""
import datetime as dt
import json
import os
import pathlib
import shutil
import subprocess
import sys

OFF = pathlib.Path(sys.argv[1]).resolve()
cfg = json.loads((OFF / "config.json").read_text(encoding="utf-8"))
fs = cfg.get("feishu") or {}
if not fs.get("base") or not fs.get("table"):
    sys.exit("config.json 的 feishu.base / feishu.table 没填，不写飞书")
LARK = os.environ.get("LARK_CLI") or shutil.which("lark-cli") or sys.exit("找不到 lark-cli")
AS = sys.argv[sys.argv.index("--as") + 1] if "--as" in sys.argv else "bot"


def lark(*a):
    r = subprocess.run([LARK, "base", *a, "--as", AS, "--base-token", fs["base"], "--table-id", fs["table"]],
                       capture_output=True, text=True, cwd=OFF)
    return json.loads(r.stdout or "{}")


raw = json.loads((OFF / "raw.json").read_text(encoding="utf-8"))
tags = json.loads((OFF / "tags.json").read_text(encoding="utf-8"))
have = set()
out = lark("+record-list", "--limit", "500")
for rec in (out.get("data") or {}).get("items", []) or (out.get("data") or {}).get("records", []) or []:
    link = rec.get("fields", rec).get("原帖链接")
    if link:
        have.add(link if isinstance(link, str) else str(link))
batch = raw["runs"][-1]["at"] if raw.get("runs") else dt.date.today().isoformat()
NAMES = {"tikhub": "TikHub", "rss": "RSS", "arctic": "Arctic", "sorftime": "Sorftime", "reddit": "Reddit API", "serpapi": "SerpApi"}
rows = []
for pid, t in tags.items():
    p = raw["posts"].get(pid)
    if not t.get("relevant") or not p or p["permalink"] in have:
        continue
    rows.append({"讨论串": p["title"], "板块": "r/" + str(p["subreddit"]), "发帖日期": (p.get("created") or "")[:10],
                 "原帖链接": p["permalink"], "评论数": len(p.get("comments", [])), "抱怨": t.get("neg", []), "好评": t.get("pos", []),
                 "人群": t.get("persona", []), "替代方案": t.get("alt", []), "品牌": "、".join(t.get("brand", [])),
                 "一句话": t.get("gist", ""), "原声": "\n".join(f"{q['zh']}（{q['en']}）" for q in t.get("quotes", [])),
                 "采集通道": sorted({NAMES.get(v.split(":")[0], v.split(":")[0]) for v in p.get("via", [])}),
                 "采集批次": batch, "写入方": ["VOC Agent"]})
print(f"待写入 {len(rows)} 行（表里已有 {len(have)}）")
if "--dry-run" in sys.argv or not rows:
    sys.exit(0)
for i in range(0, len(rows), 200):                 # 一次最多 200 行
    (OFF / "_feishu_rows.json").write_text(json.dumps({"create_records": rows[i:i + 200]}, ensure_ascii=False), encoding="utf-8")
    res = lark("+record-batch-create", "--json", "@_feishu_rows.json")
    print("ok" if res.get("ok") else res)
