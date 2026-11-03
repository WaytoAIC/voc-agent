"""零付费入口：把评论表格（CSV / TSV，卖家精灵、Helium 10、自己整理的都行）导成 data.json 骨架，不用任何 API key。

用法：python3 <skill>/import_reviews.py <评论.csv> --asin B0XXXXXXXX [--name 产品名] [--brand 品牌] [--role 自家|竞品]
                                                   [--map 星级=rating,内容=body,...] [--out voc-reports/<ASIN>/data.json]
- 列名自动认（中英文都认）：星级 / 评分 / rating · 内容 / 评论内容 / content / body · 标题 / title · 日期 / 评论时间 / date ·
  款式 / 变体 / variant / sku · vine / 送测 · vp / verified / 已验证购买。认不出的列用 --map 自己指。
- 日期认得：2026-10-05、2026/10/05、10/5/2026、"Reviewed in the United States on October 5, 2026"。
- 导完是「原料」：reviews 里 zh 和 tags 是空的，下一步让 AI 按 SKILL.md 第一部分第 3 步打标签（只能用 voc.config.json 的词），再跑 analyze.py。
- Excel 请先另存为 CSV（UTF-8）。
"""
import csv
import datetime as dt
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import voccfg  # noqa: E402

SYN = {
    "star": ["星级", "评分", "评论星级", "rating", "stars", "star", "score"],
    "content": ["评论内容", "内容", "正文", "content", "body", "review", "review text", "text", "评论"],
    "title": ["评论标题", "标题", "title", "review title"],
    "date": ["评论时间", "评论日期", "日期", "时间", "date", "time", "review date", "reviewed on"],
    "sku": ["款式", "变体", "型号", "规格", "variant", "variation", "style", "sku", "skus", "size", "color", "asin 变体"],
    "vine": ["vine", "是否vine", "送测", "vine voice"],
    "verified": ["vp", "是否vp", "verified", "verified purchase", "已验证购买", "认证购买"],
    "id": ["id", "评论id", "review id", "reviewid"],
}
MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"], 1)}


def arg(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def parse_date(s):
    s = (s or "").strip()
    if not s:
        return None
    m = re.search(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", s)
    if m:
        return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", s)
    if m:
        return dt.date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
    m = re.search(r"([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})", s)
    if m and m.group(1).lower() in MONTHS:
        return dt.date(int(m.group(3)), MONTHS[m.group(1).lower()], int(m.group(2)))
    if re.fullmatch(r"\d{10,13}", s):
        v = int(s)
        return dt.date.fromtimestamp(v / 1000 if v > 1e11 else v)
    return None


def truthy(v):
    return str(v).strip().lower() in ("1", "true", "yes", "y", "是", "vine", "vp", "verified", "已验证购买", "✓")


def main():
    if len(sys.argv) < 2 or sys.argv[1].startswith("--"):
        sys.exit(__doc__)
    src = pathlib.Path(sys.argv[1])
    asin = (arg("--asin") or "").upper()
    if not re.fullmatch(r"B0[A-Z0-9]{8}", asin):
        sys.exit("要给 --asin B0XXXXXXXX")
    cfg = voccfg.load(HERE)
    text = src.read_text(encoding="utf-8-sig", errors="replace")
    dialect = csv.excel_tab if src.suffix.lower() == ".tsv" or text.count("\t") > text.count(",") else csv.excel
    rows = list(csv.DictReader(text.splitlines(), dialect=dialect))
    if not rows:
        sys.exit("表格是空的")
    heads = list(rows[0].keys())
    low = {h: h.strip().lower() for h in heads}
    col = {}
    for k, names in SYN.items():
        col[k] = next((h for h in heads if low[h] in names), None)
    for pair in (arg("--map") or "").split(","):
        if "=" in pair:
            a, b = pair.split("=", 1)
            col[b.strip()] = a.strip()
    missing = [k for k in ("star", "content") if not col.get(k)]
    if missing:
        sys.exit(f"认不出这些列：{missing}。表头是 {heads}；用 --map 列名=star 或 列名=content 指一下")
    reviews, skipped = [], 0
    for i, r in enumerate(rows):
        try:
            star = int(round(float(str(r[col["star"]]).strip().split()[0])))
        except (ValueError, IndexError):
            skipped += 1
            continue
        d = parse_date(r.get(col["date"]) if col.get("date") else "") or dt.date.today()
        body = (r.get(col["content"]) or "").strip()
        title = (r.get(col["title"]) or "").strip() if col.get("title") else ""
        if not body and not title:
            skipped += 1
            continue
        rv = {"id": (r.get(col["id"]) or f"csv-{i + 1}") if col.get("id") else f"csv-{i + 1}", "star": max(1, min(5, star)),
              "t": int(dt.datetime(d.year, d.month, d.day).timestamp() * 1000),
              "sku": (r.get(col["sku"]) or "").strip() if col.get("sku") else "",
              "vine": truthy(r.get(col["vine"])) if col.get("vine") else False,
              "verified": truthy(r.get(col["verified"])) if col.get("verified") else True,
              "en": body or title, "zh": "", "tags": []}
        if title:
            rv["title"] = title
        reviews.append(rv)
    reviews.sort(key=lambda r: -r["t"])
    stars = {str(s): sum(1 for r in reviews if r["star"] == s) for s in range(5, 0, -1)}
    neg, pos, stage_of = voccfg.vocab(cfg)
    data = {
        "product": {"asin": asin, "name": arg("--name") or asin, "brand": arg("--brand") or ""},
        "role": arg("--role") or "竞品",
        "pulled": {"source": "csv", "file": src.name, "rows": len(rows), "kept": len(reviews), "skipped": skipped, "at": dt.date.today().isoformat(),
                   "columns": {k: v for k, v in col.items() if v}},
        "stars": stars, "reviews": reviews,
        "tagsNeg": list(cfg["tags"]["neg"]), "tagsPos": list(cfg["tags"]["pos"]),
        "stages": list(cfg["stages"]["order"]), "tagStage": dict(stage_of),
        "problems": [], "praises": [], "summary": "", "insight": "",
    }
    errs = voccfg.validate(data)
    if errs:
        sys.exit("导出的结构不对：" + "；".join(errs))
    out = pathlib.Path(arg("--out") or HERE.parent / asin / "data.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists() and "--force" not in sys.argv:
        sys.exit(f"{out} 已存在，加 --force 覆盖")
    out.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    vine = sum(1 for r in reviews if r["vine"])
    print(f"读入 {len(rows)} 行，导入 {len(reviews)} 条（送测 {vine}，跳过 {skipped}），星级 {stars} → {out}")
    print("下一步：让 AI 给每条写 zh 和 tags（只用 voc.config.json 的词），然后 python3 现场分析/analyze.py " + str(out))


if __name__ == "__main__":
    main()
