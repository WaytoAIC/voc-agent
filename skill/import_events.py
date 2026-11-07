"""退货 / 换货 / 买家消息导入：把后台导出的表格（CSV / TSV）并进 data.json 的 events，不用任何 API。

用法：python3 <skill>/import_events.py <退货.csv> --asin B0XXXXXXXX [--type 退货|换货|买家消息]
                                                  [--map 日期=date,备注=note,...] [--out voc-reports/<ASIN>/data.json]
- 认得的表：亚马逊 FBA 退货报告（return-date / sku / reason / customer-comments）、赛狐 / 领星导出的退货表、买家消息导出、自己整理的表。
  列名自动认（中英文都认）：日期 · 款式 / sku / msku · 原因 / reason（平台原因码）· 备注 / customer-comments / 留言 / 消息内容 · 类型 · 数量 · 订单号（只用来去重，不存）。
  认不出的列用 --map 自己指：--map 退款时间=date,买家留言=note
- 一行一条事件，写进 data.json 的 events：type / date / sku / code / note / hasNote / qty / id；平台原因码翻成中文（FBA 常见码内置，其余照抄）。
- 重复跑不会重复写：按「类型 + 日期 + 款式 + 订单号（或备注）」去重。
- 导完的备注还没读：跑 python3 <skill>/tag.py <data.json> --events，让模型把每条备注读成一个一级标签写进 real（「读出来是」），
  dashboard.py / detail.py 都按 real 算「真实原因」。
"""
import csv
import datetime as dt
import hashlib
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import voccfg  # noqa: E402

SYN = {
    "date": ["return-date", "return date", "退货日期", "退款日期", "申请日期", "日期", "date", "创建时间", "时间", "message-date", "消息时间", "发送时间"],
    "sku": ["sku", "msku", "seller-sku", "seller sku", "款式", "variant", "变体", "规格", "子sku", "商品规格"],
    "asin": ["asin", "子asin", "child asin"],
    "code": ["reason", "return-reason", "退货原因", "原因码", "平台原因", "原因", "退款原因"],
    "note": ["customer-comments", "customer comments", "买家备注", "备注", "留言", "买家留言", "comment", "comments", "消息内容", "内容", "message", "正文", "body"],
    "type": ["类型", "type", "事件类型"],
    "qty": ["quantity", "数量", "qty"],
    "order": ["order-id", "order id", "订单号", "订单编号", "amazon-order-id", "order"],
}
CODES = {  # 亚马逊 FBA 退货原因码 → 买家听得懂的话；表里已是中文就照抄
    "NOT_AS_DESCRIBED": "与描述不符", "UNWANTED_ITEM": "不想要了", "DEFECTIVE": "有缺陷", "QUALITY_UNACCEPTABLE": "质量不行",
    "ORDERED_WRONG_ITEM": "买错了", "NO_REASON_GIVEN": "没写原因", "DAMAGED_BY_CARRIER": "运输损坏", "DAMAGED_BY_FC": "仓库损坏",
    "MISSED_ESTIMATED_DELIVERY": "送货太慢", "FOUND_BETTER_PRICE": "找到更便宜的", "UNAUTHORIZED_PURCHASE": "误下单", "NOT_COMPATIBLE": "不兼容",
    "APPAREL_TOO_SMALL": "尺寸不合适", "APPAREL_TOO_LARGE": "尺寸不合适", "POOR_FIT": "尺寸不合适", "APPAREL_STYLE": "款式不喜欢", "MISSING_PARTS": "缺件",
    "EXCESSIVE_INSTALLATION": "太难装", "SWITCHEROO": "收到的不是这件", "UNDELIVERABLE_REFUSED": "拒收", "UNDELIVERABLE_UNKNOWN": "无法投递",
    "UNDELIVERABLE_FAILED_ATTEMPTS": "无法投递", "UNDELIVERABLE_INSUFFICIENT_ADDRESS": "地址不全", "EXTRA_ITEM": "多发了", "DID_NOT_LIKE": "不喜欢",
    "PRODUCT_NOT_AS_EXPECTED": "和想的不一样", "CUSTOMER_NO_LONGER_NEEDED": "不需要了", "ARRIVED_LATE": "到得太晚",
}
TYPES = {"退货": "退货", "return": "退货", "refund": "退货", "换货": "换货", "exchange": "换货", "replacement": "换货", "买家消息": "买家消息", "消息": "买家消息", "message": "买家消息", "咨询": "买家消息"}

args = sys.argv[1:]
if not args or args[0].startswith("--"):
    sys.exit(__doc__)
src = pathlib.Path(args[0])
opt = lambda k, d=None: args[args.index(k) + 1] if k in args else d
asin = (opt("--asin") or "").upper()
if not re.fullmatch(r"B0[A-Z0-9]{8}", asin):
    sys.exit("要 --asin B0XXXXXXXX")
default_type = TYPES.get(opt("--type", "退货").lower(), opt("--type", "退货"))
out = pathlib.Path(opt("--out") or HERE.parent / asin / "data.json")
if not out.exists():
    sys.exit(f"{out} 还不存在：先有这个产品的评论数据（卖家精灵 / import_reviews.py），再导退货")

text = src.read_text(encoding="utf-8-sig", errors="replace")
dialect = csv.excel_tab if src.suffix.lower() in (".tsv", ".txt") or text.count("\t") > text.count(",") else csv.excel
rows = list(csv.DictReader(text.splitlines(), dialect=dialect))
if not rows:
    sys.exit("表里没有数据行")
head = list(rows[0].keys())
norm = lambda s: re.sub(r"[\s_（）()]+", "", (s or "").strip().lower())
col = {}
for k, names in SYN.items():
    for h in head:
        if norm(h) in [norm(x) for x in names]:
            col[k] = h
            break
for pair in (opt("--map") or "").split(","):
    if "=" in pair:
        h, k = pair.split("=", 1)
        col[k.strip()] = h.strip()
missing = [k for k in ("date",) if k not in col]
if missing:
    sys.exit(f"认不出这些列：{missing}。表头是 {head}；用 --map 列名=date 指一下")
if "note" not in col:
    print("⚠ 没认出备注列：导入的退货会全部记成「没写备注」，真实原因就读不出来。退货报告导出时记得带 customer-comments 列")


def parse_date(s):
    s = (s or "").strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M", "%d/%m/%Y", "%b %d, %Y", "%B %d, %Y"):
        try:
            return dt.datetime.strptime(s[:len(dt.datetime.now().strftime(fmt))] if "T" in fmt else s, fmt).date().isoformat()
        except ValueError:
            continue
    m = re.search(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", s)
    if m:
        return dt.date(int(m[1]), int(m[2]), int(m[3])).isoformat()
    return None


d = json.loads(out.read_text(encoding="utf-8"))
events = d.setdefault("events", [])
seen = {e.get("id") for e in events if e.get("id")}
added, dup, bad, noted = 0, 0, 0, 0
for r in rows:
    g = lambda k: (r.get(col[k]) or "").strip() if k in col else ""
    date = parse_date(g("date"))
    if not date:
        bad += 1
        continue
    typ = TYPES.get(g("type").lower(), g("type")) if g("type") else default_type
    if typ not in ("退货", "换货", "买家消息"):
        typ = default_type
    code = g("code")
    code = CODES.get(code.upper().replace(" ", "_"), code)
    note = re.sub(r"\s+", " ", g("note"))
    key = f"{typ}|{date}|{g('sku')}|{g('order') or note}"
    eid = hashlib.sha1(key.encode()).hexdigest()[:12]
    if eid in seen:
        dup += 1
        continue
    seen.add(eid)
    e = {"id": eid, "type": typ, "date": date, "sku": g("sku"), "hasNote": bool(note)}
    if code:
        e["code"] = code
    if note:
        e["note"] = note
        noted += 1
    try:
        q = int(float(g("qty") or 1))
        if q != 1:
            e["qty"] = q
    except ValueError:
        pass
    events.append(e)
    added += 1
events.sort(key=lambda e: e["date"])
out.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"读入 {len(rows)} 行，新增 {added} 条（{default_type if 'type' not in col else '按类型列'}），重复跳过 {dup}，日期认不出 {bad}；新增里带备注 {noted} 条 → {out}")
print(f"事件总数：{len(events)}。下一步：python3 {HERE.parent / 'tag.py'} {out} --events   # 把备注读成「读出来是」(real)，再跑 dashboard.py")
