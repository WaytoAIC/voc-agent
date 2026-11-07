"""卖家精灵直连拉数据：拉详情和评论，可直接并进 data.json（周度增量用）。

用法：python3 workbench/ss_pull.py <ASIN> [--pages 10] [--no-detail] [--merge] [--new-only] [--json]
- 直连 https://mcp.sellersprite.com/mcp（tools/call），key 读 Hermes voc 配置，不打印
- 每次调用最多重试 3 次（卖家精灵偶尔 500、单次 15–25 秒）；重试不重复扣费，成功才算一次
- 不带 --merge：结果写 <VOC_DATA_DIR>/<ASIN>/detail.raw.json、reviews-<页>.raw.json（给 Agent 按 SKILL.md 建 data.json 用），评论不足一页就提前停
- --merge：拉到的东西直接并进 <VOC_DATA_DIR>/<ASIN>/data.json（没有就按 data.schema.json 建骨架）：
    · 新评论 zh / tags 留空，等 tag.py 打标；已有的评论（同日期 + 星级 + 原话）不重复写；新评论排在最前
    · 旧库里 Agent 手工整理过的评论（原话被压缩 / 截断，没有 title 字段）：同日期 + 同星级、且旧文本的实词一半以上出现在真原话里，就认作同一条，
      顺手把原话换成真原文并补 title（zh / tags / id 不动），pulled.lastPull.upgraded 记条数
    · product（品牌 / 标题 / 价格 / 评分 / 评分数 / 类目排名 / 父体 / 主图）按详情更新，已填的中文 name 不动
    · pulled.calls 累加，pulled.lastPull 记这次拉了几页、新增几条；stars 重算
    · 原始返回留在 <VOC_DATA_DIR>/<ASIN>/_raw/（不进 git）
- --new-only：卖家精灵按日期倒序分页，一页里全是已有评论就停（周度增量通常 1–2 页；配合 --pages 设上限）
- --json：结尾多打一行 JSON {"asin","calls","pages","new","total","detail","errors"} 给 weekly.py 读
- 最后打印实际调用次数，算在用户确认的预算里
- 环境变量：VOC_DATA_DIR 换数据目录（默认 ./voc-reports）；VOC_SS_STUB=<目录> 用已存的 *.raw.json 代替联网（测试）
"""
import datetime as dt
import json
import os
import pathlib
import re
import sys
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(os.environ.get("VOC_DATA_DIR") or pathlib.Path.cwd() / "voc-reports").expanduser()
CFG = pathlib.Path.home() / ".hermes/profiles" / os.environ.get("VOC_HERMES_PROFILE", "voc") / "config.yaml"
STUB = pathlib.Path(os.environ["VOC_SS_STUB"]) if os.environ.get("VOC_SS_STUB") else None   # 测试用：从这个目录读已存的 *.raw.json，不联网
ARGS = sys.argv[1:]
if not ARGS or ARGS[0].startswith("-"):
    sys.exit(__doc__)
asin = ARGS[0].upper()
pages = int(ARGS[ARGS.index("--pages") + 1]) if "--pages" in ARGS else 10
MERGE, NEW_ONLY, AS_JSON, NO_DETAIL = "--merge" in ARGS, "--new-only" in ARGS, "--json" in ARGS, "--no-detail" in ARGS
out = ROOT / asin
raw_dir = out / "_raw" if MERGE else out
raw_dir.mkdir(parents=True, exist_ok=True)
m = re.search(r"sellersprite:\n\s+url: (\S+)\n\s+headers:\n\s+secret-key: (\S+)", CFG.read_text(encoding="utf-8") if CFG.exists() else "")
if not m and not STUB:
    sys.exit("找不到卖家精灵 key：~/.hermes/profiles/voc/config.yaml 的 mcp_servers.sellersprite")
URL, KEY = (m.group(1), m.group(2).strip("'\"")) if m else ("", "")
calls, errors, UPG = 0, [], 0


def say(*a):
    print(*a, file=sys.stderr if AS_JSON else sys.stdout)


def call(name, args, fname):
    global calls
    if STUB:
        f = STUB / fname
        if not f.exists():
            errors.append(fname)
            return None
        calls += 1
        return json.loads(json.loads(f.read_text(encoding="utf-8"))["result"]["content"][0]["text"])
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args}}).encode()
    hdr = {"secret-key": KEY, "Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    for attempt in range(3):
        try:
            raw = urllib.request.urlopen(urllib.request.Request(URL, data=body, headers=hdr), timeout=120).read().decode()
            calls += 1
            (raw_dir / fname).write_text(raw, encoding="utf-8")
            text = json.loads(raw)["result"]["content"][0]["text"]
            return json.loads(text)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, KeyError, json.JSONDecodeError) as e:
            err = getattr(e, "code", e)
            say(f"  {fname} 第 {attempt + 1} 次失败：{err}")
            time.sleep(5 * (attempt + 1))
    (raw_dir / (fname + ".error")).write_text("3 次都失败", encoding="utf-8")
    errors.append(fname)
    return None


# ---------- 原始返回 → data.json 的字段 ----------
def to_review(it):
    sku = " · ".join(re.sub(r"^[A-Za-z ]+:\s*", "", s).strip() for s in (it.get("skus") or []) if s)
    content = re.sub(r"<br\s*/?>", "\n", it.get("content") or "").strip()
    title = (it.get("title") or "").strip()
    return {"star": int(it.get("star") or 0), "t": int(it.get("date") or 0), "sku": sku, "vine": bool(it.get("vine")),
            "verified": bool(it.get("verified")), "title": title, "en": content or title, "zh": "", "tags": []}


def rkey(r):
    """去重键 = 星级 + 原话前 160 字（日期另比：旧库有的按天取整、和原始毫秒差 1 小时跨了天，所以按 tclose 容差比）"""
    en = re.sub(r"<br\s*/?>", " ", r.get("en") or "")
    return (int(r.get("star") or 0), re.sub(r"\s+", " ", en).strip()[:160].lower())


def tclose(a, b):
    return abs(int(a or 0) - int(b or 0)) <= 26 * 3600 * 1000


STOP = set("the and that this with have they were them from your very just also than then into been like will would could about there their what when which more some only even after over down these those onto".split())


def words(s):
    return {w for w in re.findall(r"[a-z']+", (s or "").lower()) if len(w) > 3 and w not in STOP}


def same_legacy(old, r):
    """旧库里手工压缩 / 截断过的评论 vs 真原话：同日期 + 同星级，且旧文本实词 ≥ 50% 出现在原话里（实测：重复的 ≥ 0.67，不同的 = 0）"""
    if not tclose(old.get("t"), r["t"]) or int(old.get("star") or 0) != r["star"]:
        return False
    a = words(old.get("en"))
    return bool(a) and len(a & words(r["en"])) / len(a) >= 0.5


class Matcher:
    """把拉到的评论对到 data.json 里已有的：先精确键，再按旧改写行兜底（一对一消耗）。"""

    def __init__(self, reviews):
        self.keys = {}
        for x in reviews:
            self.add(x)
        self.legacy = [x for x in reviews if "title" not in x]
        self.used = set()

    def add(self, r):
        self.keys.setdefault(rkey(r), []).append(int(r.get("t") or 0))

    def find(self, r, consume=True):
        if any(tclose(t, r["t"]) for t in self.keys.get(rkey(r), [])):
            return "same", None
        for i, old in enumerate(self.legacy):
            if i not in self.used and same_legacy(old, r):
                if consume:
                    self.used.add(i)
                return "legacy", old
        return "new", None


def to_product(dd, old):
    p = dict(old or {})
    sub = (dd.get("subcategories") or [{}])[0]
    got = {"asin": dd.get("asin") or asin, "parent": dd.get("parent"), "brand": dd.get("brand"), "seller": dd.get("sellerName"),
           "title": dd.get("title"), "price": dd.get("price"), "rating": dd.get("rating"), "ratings": dd.get("ratings"),
           "bsr": f"{sub.get('label')} 第 {sub.get('rank')} 名" if sub.get("rank") else None,
           "launched": dt.date.fromtimestamp(dd["availableDate"] / 1000).isoformat() if dd.get("availableDate") else None,
           "image": dd.get("zoomImageUrl") or dd.get("imageUrl")}
    for k, v in got.items():
        if v not in (None, "", -1.0):
            p[k] = v
    p.setdefault("name", (p.get("title") or asin)[:40])
    return p


def merge(detail, items):
    path = out / "data.json"
    d = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {
        "role": "竞品", "product": {"asin": asin}, "pulled": {}, "stars": {}, "reviews": [], "events": [],
        "tagsNeg": [], "tagsPos": [], "problems": [], "praises": [], "summary": "", "insight": ""}
    if d.get("demo") or (d.get("pulled") or {}).get("source") == "演示数据":
        say("这是演示数据，不往里并")
        return 0
    if detail:
        d["product"] = to_product(detail, d.get("product"))
    mt = Matcher(d["reviews"])
    global UPG
    fresh, upgraded = [], 0
    for it in items:
        r = to_review(it)
        kind, old = mt.find(r)
        if kind == "same":
            continue
        if kind == "legacy":   # 旧改写行：换成真原话，补 title；zh / tags / id 不动
            old["en"], old["title"] = r["en"], r["title"]
            mt.add(old)
            upgraded += 1
            continue
        mt.add(r)
        fresh.append(r)
    fresh.sort(key=lambda r: -r["t"])
    d["reviews"] = fresh + d["reviews"]
    vine = sum(1 for r in d["reviews"] if r.get("vine"))
    old = d.get("pulled") or {}
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    d["pulled"] = {**old, "at": now, "source": "卖家精灵", "calls": int(old.get("calls") or 0) + calls, "total": len(d["reviews"]),
                   "vine": vine, "analyzed": len(d["reviews"]) - vine,
                   "lastPull": {"at": now, "new": len(fresh), "upgraded": upgraded, "calls": calls, "pages": got_pages, "stopped": stop_reason}}
    d["stars"] = {}
    for r in d["reviews"]:
        d["stars"][str(r["star"])] = d["stars"].get(str(r["star"]), 0) + 1
    path.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    UPG = upgraded
    return len(fresh)


known = Matcher([])
if MERGE and NEW_ONLY and (out / "data.json").exists():
    known = Matcher(json.loads((out / "data.json").read_text(encoding="utf-8")).get("reviews", []))

detail = None
if not NO_DETAIL:
    detail = ((call("asin_detail", {"marketplace": "US", "asin": asin}, "detail.raw.json") or {}).get("data")) or None
    say("商品详情：", "成功" if detail else "失败")
items, got_pages, stop_reason = [], 0, "拉完"
for page in range(1, pages + 1):
    d = call("review", {"marketplace": "US", "asin": asin, "page": page, "size": 20,
                        "returnFields": "title,content,date,star,skus,vine,verified,likes"}, f"reviews-{page}.raw.json")
    rows = ((d or {}).get("data") or {}).get("items") or ((d or {}).get("data") or {}).get("list") or []
    if d:
        got_pages += 1
    items += rows
    new_here = sum(1 for it in rows if known.find(to_review(it))[0] == "new") if NEW_ONLY else len(rows)
    say(f"评论第 {page} 页：{len(rows) if d else '失败'}" + (f"（新 {new_here}）" if NEW_ONLY and d else ""))
    if d and len(rows) < 20:
        break
    if NEW_ONLY and d and new_here == 0:
        stop_reason = "这一页全是已有评论"
        break
    if page == pages and pages < ((d or {}).get("data") or {}).get("pages", 0):
        stop_reason = f"到了 --pages {pages} 上限"
new = merge(detail, items) if MERGE else None
say(f"完成：实际调用卖家精灵 {calls} 次，拿到评论 {len(items)} 条" + (f"，新增 {new} 条并进 data.json，旧行换真原话 {UPG} 条（{stop_reason}）" if MERGE else "") + f" → {out}")
if AS_JSON:
    print(json.dumps({"asin": asin, "calls": calls, "pages": got_pages, "new": new, "upgraded": UPG, "total": len(items), "detail": bool(detail), "errors": errors}, ensure_ascii=False))
