"""VOC 算数脚本：所有数字都从评论标签里算，AI 不手算。

用法：
  python3 analyze.py <ASIN>/data.json                       # 分析一个产品
  python3 analyze.py <ASIN>/data.json --vs <竞品>/data.json ...  # 加上竞品对比

做五件事，结果写回 data.json 的 calc 字段（并同步 problems / praises 的条数和 journey）：
  1. 体检：读入、送测、分析条数；没有标签的评论；没定阶段的标签；AI 写的条数和实际不符的。
  2. 帕累托（二八）：问题按人数排，算累计占比，标出占了八成抱怨的那几件。
  3. 下钻：按款式算评论数、平均星级、差评占比；找出集中在某个款式的问题。
  4. 用户旅程：每个标签按 tagStage 归到阶段，算每段的满意度。
  5. 竞品对比（有 --vs 时）：同一套标签下，我和每个竞品、竞品平均各占多少。

口径：
  - 只算非送测（vine=false）评论；一条评论提到同一个标签只算一次。
  - 差评 = 1–3 星。
  - 旅程满意度 = (这一段说好的人数 − 说不好的人数) ÷ 提到这一段的人数 × 100，范围 −100 到 +100。
  - 款式集中度 = 这个问题在该款式的占比 ÷ 该款式在全部评论里的占比。算「集中」要同时满足：
    集中度 ≥1.5、至少 2 条、这个款式至少 5 条评论、比整体占比高 5 个点以上。
  - problems / praises 的名称和标签不一样时，用 "tag" 字段指明对应哪个标签。
"""
import json
import pathlib
import sys

DEFAULT_STAGES = ["为什么买", "收货", "安装", "日常使用", "用了几个月", "再买或推荐"]
NO_SKU = "款式未标"


def load(path):
    p = pathlib.Path(path).resolve()
    return p, json.loads(p.read_text(encoding="utf-8"))


def base(d):
    U = [r for r in d["reviews"] if not r.get("vine")]
    return U, len(U)


def count(U, tag):
    return sum(1 for r in U if tag in r.get("tags", []))


def avg_star(rows):
    return round(sum(r["star"] for r in rows) / len(rows), 2) if rows else None


def pct(a, b):
    return round(a / b * 100, 1) if b else 0.0


def check(d, U, N):
    neg, pos = d.get("tagsNeg", []), d.get("tagsPos", [])
    known = set(neg) | set(pos)
    used = {t for r in U for t in r.get("tags", [])}
    stage_of = d.get("tagStage", {})
    fixed = []
    for group in ("problems", "praises"):
        for item in d.get(group, []):
            tag = item.get("tag", item["name"])
            if tag not in known:
                fixed.append(f'{item["name"]}：对不上标签，没改（在这一项里加 "tag": "标签名"）')
                continue
            real = count(U, tag)
            if item.get("count") != real:
                fixed.append(f'{item["name"]}：{item.get("count")} → {real}')
                item["count"] = real
            if group == "problems":
                hidden = sum(1 for r in U if tag in r.get("tags", []) and r["star"] >= 4)
                if hidden:
                    item["hidden"] = hidden
                else:
                    item.pop("hidden", None)
    return {
        "read": len(d["reviews"]),
        "vine": len(d["reviews"]) - N,
        "analyzed": N,
        "untagged": sum(1 for r in U if not r.get("tags")),
        "unknownTags": sorted(used - known),
        "noStage": sorted(t for t in used & known if t not in stage_of),
        "countFixed": fixed,
    }


def pareto(d, U, N):
    rows = [{"name": t, "count": count(U, t)} for t in d.get("tagsNeg", [])]
    rows = sorted([r for r in rows if r["count"]], key=lambda r: -r["count"])
    total = sum(r["count"] for r in rows)
    cum, core_done = 0, False
    for r in rows:
        cum += r["count"]
        hit = [x for x in U if r["name"] in x.get("tags", [])]
        r.update(
            ofReviews=pct(r["count"], N),
            ofComplaints=pct(r["count"], total),
            cum=pct(cum, total),
            avgStar=avg_star(hit),
            core=not core_done,
        )
        if r["cum"] >= 80:
            core_done = True
    core = [r for r in rows if r["core"]]
    return {
        "mentions": total,
        "rows": rows,
        "coreCount": len(core),
        "coreShare": core[-1]["cum"] if core else 0,
        "avgStarAll": avg_star(U),
    }


def drill(d, U, N):
    groups = {}
    for r in U:
        groups.setdefault(r.get("sku") or NO_SKU, []).append(r)
    neg = d.get("tagsNeg", [])
    skus = []
    for sku, rows in sorted(groups.items(), key=lambda kv: (kv[0] == NO_SKU, -len(kv[1]))):
        top = sorted(((t, count(rows, t)) for t in neg), key=lambda x: -x[1])
        top = [t for t in top if t[1]][:2]
        skus.append({
            "sku": sku,
            "n": len(rows),
            "share": pct(len(rows), N),
            "avgStar": avg_star(rows),
            "negShare": pct(sum(1 for r in rows if r["star"] <= 3), len(rows)),
            "top": [{"name": t, "count": c, "share": pct(c, len(rows))} for t, c in top],
            "small": len(rows) < 5,
        })
    hot = []
    for t in neg:
        total = count(U, t)
        if total < 2:
            continue
        for sku, rows in groups.items():
            if sku == NO_SKU:
                continue
            c = count(rows, t)
            lift = (c / total) / (len(rows) / N) if c else 0
            if c >= 2 and len(rows) >= 5 and lift >= 1.5 and pct(c, len(rows)) >= pct(total, N) + 5:
                hot.append({
                    "name": t, "sku": sku, "count": c, "total": total,
                    "skuShare": pct(c, len(rows)), "allShare": pct(total, N), "lift": round(lift, 1),
                })
    return {"skus": skus, "hot": sorted(hot, key=lambda h: -h["lift"]), "unlabeled": len(groups.get(NO_SKU, []))}


def journey(d, U):
    stage_of = d.get("tagStage", {})
    order = d.get("stages") or DEFAULT_STAGES
    order = order + [s for s in dict.fromkeys(stage_of.values()) if s not in order]
    neg, pos = set(d.get("tagsNeg", [])), set(d.get("tagsPos", []))
    out = []
    for st in order:
        tags = [t for t, s in stage_of.items() if s == st]
        if not tags:
            continue
        p = sorted([[t, count(U, t)] for t in tags if t in pos and count(U, t)], key=lambda x: -x[1])
        n = sorted([[t, count(U, t)] for t in tags if t in neg and count(U, t)], key=lambda x: -x[1])
        good = sum(1 for r in U if any(t in pos for t in r.get("tags", []) if stage_of.get(t) == st))
        bad = sum(1 for r in U if any(t in neg for t in r.get("tags", []) if stage_of.get(t) == st))
        talked = sum(1 for r in U if any(stage_of.get(t) == st for t in r.get("tags", [])))
        if not talked:
            continue
        out.append({"n": st, "pos": p, "neg": n, "good": good, "bad": bad, "talked": talked,
                    "score": round((good - bad) / talked * 100)})
    return out


def compare(d, U, N, others):
    mine_tags = [(t, "neg") for t in d.get("tagsNeg", [])] + [(t, "pos") for t in d.get("tagsPos", [])]
    comps = []
    for path in others:
        _, c = load(path)
        cu, cn = base(c)
        comps.append({"asin": c["product"]["asin"], "name": c["product"]["name"], "brand": c["product"].get("brand", ""),
                      "n": cn, "avgStar": avg_star(cu), "negShare": pct(sum(1 for r in cu if r["star"] <= 3), cn),
                      "_U": cu, "_tags": set(c.get("tagsNeg", [])) | set(c.get("tagsPos", []))})
    rows = []
    for t, kind in mine_tags:
        mc = count(U, t)
        vals = [pct(count(c["_U"], t), c["n"]) if t in c["_tags"] else None for c in comps]
        have = [v for v in vals if v is not None]
        if not mc and not any(have):
            continue
        avg = round(sum(have) / len(have), 1) if have else None
        mine = pct(mc, N)
        verdict = ""
        if avg is not None:
            if kind == "neg" and mc >= 3 and mine >= max(avg * 1.5, avg + 5):
                verdict = "短板"
            elif kind == "neg" and avg >= 5 and mine <= avg * 0.5:
                verdict = "比竞品好"
            elif kind == "pos" and mc >= 3 and mine >= max(avg * 1.5, avg + 5):
                verdict = "卖点"
            elif kind == "pos" and avg >= 5 and mine <= avg * 0.5:
                verdict = "不如竞品"
        rows.append({"name": t, "kind": kind, "mine": mine, "mineCount": mc, "comps": vals, "avg": avg, "verdict": verdict})
    only = sorted({t for c in comps for t in c["_tags"]} - {t for t, _ in mine_tags})
    for c in comps:
        c.pop("_U"), c.pop("_tags")
    return {"mine": {"n": N, "avgStar": avg_star(U), "negShare": pct(sum(1 for r in U if r["star"] <= 3), N)},
            "comps": comps, "rows": rows, "compOnlyTags": only}


def main():
    args = sys.argv[1:]
    if not args:
        sys.exit(__doc__)
    others = args[args.index("--vs") + 1:] if "--vs" in args else []
    path, d = load(args[0])
    U, N = base(d)
    if not N:
        sys.exit("没有可分析的评论（全部是送测或为空）")
    calc = {"check": check(d, U, N), "pareto": pareto(d, U, N), "drill": drill(d, U, N)}
    if d.get("tagStage"):
        d["journey"] = journey(d, U)
    if others:
        calc["compare"] = compare(d, U, N, others)
    d["calc"] = calc
    path.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")

    c, p, dr = calc["check"], calc["pareto"], calc["drill"]
    print(f"体检：读入 {c['read']}，送测 {c['vine']}，分析 {c['analyzed']}，没打标签 {c['untagged']}")
    for k, label in (("unknownTags", "标签不在 tagsNeg/tagsPos 里"), ("noStage", "标签没定阶段"), ("countFixed", "条数已按标签改正")):
        if c[k]:
            print(f"  ⚠ {label}：{'、'.join(c[k])}")
    print(f"二八：{p['coreCount']} 个问题占了 {p['coreShare']}% 的抱怨 → " + " / ".join(r["name"] for r in p["rows"] if r["core"]))
    for h in dr["hot"]:
        print(f"款式集中：「{h['name']}」在 {h['sku']} 占 {h['skuShare']}%（全部 {h['allShare']}%，{h['lift']} 倍）")
    if d.get("tagStage"):
        print("旅程满意度：" + "  ".join(f"{s['n']} {s['score']:+d}（{s['talked']} 人）" for s in d["journey"]))
    if others:
        bad = [r for r in calc["compare"]["rows"] if r["verdict"]]
        print("竞品对比：" + ("；".join(f"{r['name']} {r['verdict']}（我 {r['mine']}% / 竞品平均 {r['avg']}%）" for r in bad) or "没有明显差距"))
    print(path)


if __name__ == "__main__":
    main()
