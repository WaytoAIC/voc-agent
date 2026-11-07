"""产品详情页的数据：从 <ASIN>/data.json（含 analyze.py 写的 calc / journey）、竞品 data.json、actions.json 算出工作台「产品详情」要的所有数。
页面不再嵌任何演示文字；哪一块没数据，就返回空，页面显示「没数据 + 去哪接」。

用法：python3 <skill>/detail.py <ASIN>        # 打印 JSON；serve.py 直接 import 调 build(asin)
口径：
  - 只算非送测评论；条数、占比全部取 analyze.py 写进 calc / journey 的数，这里不重算（主题下钻按款式、退货窗口除外）。
  - 退货 / 换货 / 买家消息来自 data.json 的 events（import_events.py 导入，tag.py --events 打「读出来是」）；窗口 = 最近 30 天，以最新一条事件的日期为准。
  - 竞品 = voc.config.json competitors 里有 data.json 的；旅程的「竞品平均」= 各竞品该段满意度的平均。
"""
import datetime as dt
import json
import os
import pathlib
import sys
from collections import Counter

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import voccfg  # noqa: E402

CFG = voccfg.load(HERE)
DATA = pathlib.Path(os.environ.get("VOC_DATA_DIR", HERE)).expanduser()
WINDOW_DAYS = 30


def _json(p):
    try:
        return json.loads(pathlib.Path(p).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _load(asin):
    d = _json(DATA / asin / "data.json")
    if d:
        voccfg.canonicalize(d, CFG)
    return d


def _src(r):
    return f"{r.get('star', '?')}★" + (f" · {r['sku']}" if r.get("sku") else "")


def _quotes(U, tag, item, k=2):
    q = [list(x) for x in (item or {}).get("quotes", [])][:k]
    if len(q) < k:
        for r in U:
            if tag in r.get("tags", []) and r.get("en") and all(r["en"] != x[0] for x in q):
                q.append([r["en"], r.get("zh", ""), _src(r)])
                if len(q) >= k:
                    break
    return q


def _trend(monthly, name):
    """最近两个完整月的占比方向；某月评论数 < 5 不下结论。"""
    if not monthly or not monthly.get("rows"):
        return None
    row = next((x for x in monthly["rows"] if x["name"] == name), None)
    n = monthly.get("n") or []
    if not row or len(n) < 2 or n[-1] < 5 or n[-2] < 5:
        return None
    a, b = row["share"][-1], row["share"][-2]
    if a is None or b is None:
        return None
    return "↑" if a > b + 1 else "↓" if a < b - 1 else "→"


def build(asin, actions=None, own_asin=None):
    """own_asin：serve.py 传进来的自家 ASIN（可被 VOC_OWN_ASIN 覆盖）；不传就按 voc.config.json。"""
    asin = asin.upper()
    d = _load(asin)
    if not d:
        return {"asin": asin, "exists": False}
    U = [r for r in d.get("reviews", []) if not r.get("vine")]
    N = len(U)
    calc = d.get("calc") or {}
    pr = d.get("product") or {}
    own_asin = (own_asin or (CFG.get("own") or {}).get("asin") or "").upper()
    own = asin == own_asin or d.get("role") == "自家"
    neg, pos = d.get("tagsNeg", []), d.get("tagsPos", [])
    stage_of = d.get("tagStage", {})
    problems = {p.get("tag", p["name"]): p for p in d.get("problems", [])}
    praises = {p.get("tag", p["name"]): p for p in d.get("praises", [])}
    cnt = Counter(t for r in U for t in r.get("tags", []))
    monthly = calc.get("monthly")

    # 行动卡：这个产品的、按标签对上
    act_by_tag = {}
    for a in (actions or {}).get("actions", []):
        if (a.get("dataAsin") or a.get("asin") or "").upper() == asin:
            t = voccfg.tag(CFG, a.get("tag") or a.get("problem") or "")
            act_by_tag.setdefault(t, a.get("id"))

    # 最该改的 3 件事：按优先级分
    hot = {h["name"]: h for h in (calc.get("drill") or {}).get("hot", [])}
    top_issues = []
    for row in (calc.get("priority") or [])[:3]:
        p = problems.get(row["name"], {})
        h = hot.get(row["name"])
        top_issues.append({"name": row["name"], "count": row["count"], "share": row["ofReviews"], "lowStar": row["lowStar"], "priority": row["priority"],
                           "owner": p.get("owner", ""), "fix": p.get("fix", ""), "stage": stage_of.get(row["name"], ""), "trend": _trend(monthly, row["name"]),
                           "hot": {"sku": h["sku"], "lift": h["lift"], "skuShare": h["skuShare"]} if h else None, "act": act_by_tag.get(row["name"])})

    loves = []
    for t in sorted(pos, key=lambda t: -cnt.get(t, 0))[:3]:
        if cnt.get(t, 0):
            p = praises.get(t, {})
            loves.append({"name": p.get("name", t), "tag": t, "count": cnt[t], "use": p.get("use", ""), "quote": (_quotes(U, t, p, 1) or [None])[0]})

    # 和竞品比
    cmp = calc.get("compare") or {}
    comps = cmp.get("comps", [])
    names = [c.get("brand") or c.get("name") for c in comps]
    pareto = (calc.get("pareto") or {}).get("rows", [])
    top_tag = pareto[0]["name"] if pareto else None
    vs = None
    if comps:
        row = next((r for r in cmp.get("rows", []) if r["name"] == top_tag), None) if top_tag else None
        vs = {"names": names, "topTag": top_tag,
              "ratings": [{"name": n, "v": c.get("avgStar")} for n, c in zip(names, comps)] + [{"name": "你的产品", "v": (cmp.get("mine") or {}).get("avgStar"), "me": True}],
              "shares": ([{"name": n, "v": v} for n, v in zip(names, row["comps"]) if v is not None] + [{"name": "你的产品", "v": row["mine"], "me": True}]) if row else []}

    # 用户在说什么：每个标签的人数、按款式、趋势、原话
    kids = Counter(r.get("sku") or "" for r in U)
    kid_list = [k for k, _ in kids.most_common() if k][:8]
    themes = []
    for t in list(neg) + list(pos):
        c = cnt.get(t, 0)
        if not c:
            continue
        by_kid = Counter(r.get("sku") or "" for r in U if t in r.get("tags", []))
        item = problems.get(t) if t in neg else praises.get(t)
        themes.append({"t": (item or {}).get("name", t), "tag": t, "pol": "neg" if t in neg else "pos", "count": c, "kids": {k: by_kid.get(k, 0) for k in kid_list},
                       "trend": _trend(monthly, t), "q": _quotes(U, t, item, 2), "act": act_by_tag.get(t), "owner": (item or {}).get("owner", ""), "use": (item or {}).get("use", "")})

    # 用户旅程：每段满意度 + 竞品平均 + 该谁改
    comp_journeys = []
    if own:
        for ca in CFG.get("competitors", []):
            cd = _load(ca)
            if cd and cd.get("journey"):
                comp_journeys.append({s["n"]: s["score"] for s in cd["journey"]})
    stages = []
    for s in d.get("journey") or []:
        cs = [j[s["n"]] for j in comp_journeys if s["n"] in j]
        comp = round(sum(cs) / len(cs)) if cs else None
        top_neg = s["neg"][0][0] if s.get("neg") else None
        stages.append({"n": s["n"], "score": s["score"], "talked": s["talked"], "good": s["good"], "bad": s["bad"], "comp": comp,
                       "pos": s.get("pos", [])[:3], "neg": s.get("neg", [])[:3], "owner": problems.get(top_neg, {}).get("owner", "") if top_neg else "",
                       "topNeg": top_neg, "act": act_by_tag.get(top_neg) if top_neg else None})
    gap = None
    cand = [s for s in stages if s["talked"]]
    if cand:
        key = (lambda s: (s["score"] - s["comp"]) if s["comp"] is not None else s["score"])
        worst = min(cand, key=key)
        if (worst["comp"] is not None and worst["score"] < worst["comp"]) or (worst["comp"] is None and worst["score"] < 0):
            gap = worst["n"]
            worst["gap"] = True

    # 退货 / 换货 / 买家消息
    ev = [e for e in d.get("events", []) if e.get("date")]
    returns = {"has": bool(ev), "all": {"退货": 0, "换货": 0, "买家消息": 0}}
    if ev:
        for e in ev:
            returns["all"][e.get("type", "退货")] = returns["all"].get(e.get("type", "退货"), 0) + 1
        last = max(dt.date.fromisoformat(e["date"]) for e in ev)
        lo = last - dt.timedelta(days=WINDOW_DAYS - 1)
        W = [e for e in ev if lo <= dt.date.fromisoformat(e["date"]) <= last]
        rets = [e for e in W if e.get("type") == "退货"]
        exs = [e for e in W if e.get("type") == "换货"]
        msgs = [e for e in W if e.get("type") == "买家消息"]
        real = Counter(e.get("real") or "说不清（没写备注）" for e in rets)
        codes = Counter(e.get("code") or "没写原因" for e in rets)
        top_code = codes.most_common(1)[0][0] if codes else None
        sku_rows = []
        for sku, n in Counter(e.get("sku") or "—" for e in rets + exs).most_common(10):
            rr = [e for e in rets if (e.get("sku") or "—") == sku]
            tr = Counter(e.get("real") for e in rr if e.get("real") and not str(e["real"]).startswith("说不清")).most_common(1)
            sku_rows.append({"sku": sku, "ret": len(rr), "ex": sum(1 for e in exs if (e.get("sku") or "—") == sku), "top": tr[0][0] if tr else "—"})
        recent = sorted([e for e in rets if e.get("note")], key=lambda e: e["date"], reverse=True)[:8]
        returns.update({
            "window": WINDOW_DAYS, "asOf": last.isoformat(), "since": lo.isoformat(), "n": len(rets), "withNote": sum(1 for e in rets if e.get("hasNote")),
            "noNote": sum(1 for e in rets if not e.get("hasNote")), "exchanges": len(exs), "messages": len(msgs),
            "topReal": next(((k, v) for k, v in real.most_common() if not k.startswith("说不清")), None),
            "codes": [[k, v] for k, v in codes.most_common(6)],
            "reals": [[k, v, problems.get(k, {}).get("owner", "") if not k.startswith("说不清") else "不拿来下结论"] for k, v in real.most_common(6)],
            "codeCross": [[k, v] for k, v in Counter(e.get("real") for e in rets if e.get("code") == top_code and e.get("real")).most_common(3)] if top_code else [],
            "topCode": top_code,
            "exList": [{"sku": e.get("sku") or "—", "real": e.get("real") or "", "note": e.get("note") or "", "zh": e.get("zh") or ""} for e in exs[:8]],
            "msgTop": [[k, v] for k, v in Counter(e.get("real") for e in msgs if e.get("real")).most_common(5)],
            "bySku": sku_rows,
            "recent": [{"date": e["date"][5:], "sku": e.get("sku") or "—", "code": e.get("code") or "—", "note": e.get("note", ""), "zh": e.get("zh", ""), "real": e.get("real") or "（还没读）"} for e in recent],
        })

    rows = cmp.get("rows", [])
    return {
        "asin": asin, "exists": True, "own": own, "name": pr.get("name") or pr.get("title") or asin, "brand": pr.get("brand", ""), "parent": pr.get("parent", ""),
        "note": pr.get("note", ""), "projection": d.get("projection"),
        "rating": pr.get("rating"), "ratings": pr.get("ratings"), "price": pr.get("price"), "variants": len(pr.get("variants") or []) or len(kid_list),
        "pulled": d.get("pulled") or {}, "n": N, "negShare": round(sum(1 for r in U if r.get("star", 5) <= 3) / N * 100, 1) if N else None,
        "summary": d.get("summary", ""), "insight": d.get("insight", ""), "check": calc.get("check"),
        "topIssues": top_issues, "loves": loves, "vs": vs, "themes": themes, "kids": kid_list,
        "journey": {"stages": stages, "hasComp": bool(comp_journeys), "gap": gap},
        "returns": returns,
        "compare": {"names": names, "rows": rows, "mine": cmp.get("mine")} if comps else None,
        "report": (DATA / asin / "报告.html").exists(),
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    acts = _json(DATA / "actions.json")
    print(json.dumps(build(sys.argv[1], acts), ensure_ascii=False, indent=1))
