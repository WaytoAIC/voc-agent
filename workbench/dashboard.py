"""算 VOC 工作台首页「数据看板」的数字，写成 <ASIN>/dashboard.json。

用法：python3 dashboard.py <自家 ASIN>/data.json --vs <竞品>/data.json ...
口径：
  - 周 = 周一到周日；数据里最后一个完整周是「最新一周」，往前共 12 周。
  - 时间轴：看板可以切到任意一周，切过去以后所有数都按那一周重算（快照 snaps）。
    只有往前满 8 周数据的周才能选（「抱怨怎么变」要比近 4 周和再往前 4 周）。
  - 每个快照：
      kpi        这一周 vs 前一周
      近 4 周    这一周往前 4 周（含这一周）：声音来源、问题排名、各款式、用户旅程、退货、买家消息
      抱怨怎么变 近 4 周 vs 再往前 4 周，每个问题标签的条数
  - 只算非送测评论；退货、换货、买家消息来自 data.json 的 events。
  - 和竞品比：用 analyze.py --vs 写进 calc.compare 的数（全部评论，不随周变；先跑 analyze.py）。
  所有数字由脚本算，AI 只能引用，不能改。
"""
import datetime as dt
import json
import pathlib
import sys
from collections import Counter

args = sys.argv[1:]
if not args:
    sys.exit(__doc__)
own_path = pathlib.Path(args[0])
d = json.loads(own_path.read_text(encoding="utf-8"))

U = [r for r in d["reviews"] if not r.get("vine")]
day = lambda r: dt.date.fromtimestamp(r["t"] / 1000)
last = max(day(r) for r in U)
latest_end = last - dt.timedelta(days=(last.weekday() + 1) % 7)          # 最后一个周日
NW = 12
starts = [latest_end - dt.timedelta(days=6 + 7 * k) for k in range(NW - 1, -1, -1)]
end = lambda i: starts[i] + dt.timedelta(days=6)
md = lambda x: f"{x.month}/{x.day}"
wk = lambda x: next((i for i, s in enumerate(starts) if s <= x <= end(i)), None)
for r in U:
    r["_w"] = wk(day(r))
ev = d.get("events", [])
for e in ev:
    e["_w"] = wk(dt.date.fromisoformat(e["date"]))
neg, pos = d["tagsNeg"], d["tagsPos"]
ts = d.get("tagStage", {})
problems = {p["name"]: p for p in d.get("problems", [])}


def pct(a, b):
    return round(a / b * 100, 1) if b else 0.0


def rv(lo, hi):            # 第 lo 到 hi 周（含）的评论
    return [r for r in U if r["_w"] is not None and lo <= r["_w"] <= hi]


def evs(lo, hi, t):
    return [e for e in ev if e["_w"] is not None and lo <= e["_w"] <= hi and e["type"] == t]


trend = []
for i in range(NW):
    rows = rv(i, i)
    n_neg = sum(1 for r in rows if r["star"] <= 3)
    trend.append({"week": md(starts[i]), "reviews": len(rows), "neg": n_neg, "negShare": pct(n_neg, len(rows))})


def snap(i):
    lo = i - 3                                   # 近 4 周
    R = rv(lo, i)

    def voices(w):
        out = {"评论": len(rv(w, w))}
        for t in ("退货", "换货", "买家消息"):
            out[t] = len(evs(w, w, t))
        return out
    now, prev = voices(i), voices(i - 1)
    cnt = Counter(t for r in R for t in r["tags"] if t in neg)
    top_tag = cnt.most_common(1)[0][0]
    top_share = lambda w: pct(sum(1 for r in rv(w, w) if top_tag in r["tags"]), len(rv(w, w)))
    src = {"评论": len(R)}
    for t in ("退货", "换货", "买家消息"):
        src[t] = len(evs(lo, i, t))
    # 问题排名：累计到 80% 之前的算核心问题
    tot = sum(cnt.values())
    rows, cum = [], 0.0
    for name, c in cnt.most_common():
        sh = pct(c, tot)
        rows.append({"name": name, "count": c, "share": sh, "stage": ts.get(name, ""), "core": cum < 80})
        cum += sh
    core = [r for r in rows if r["core"]]
    pareto = {"rows": rows, "mentions": tot, "core": [r["name"] for r in core], "cum": round(sum(r["share"] for r in core), 1)}
    # 抱怨怎么变
    B = rv(i - 7, i - 4)
    change = []
    for t in neg:
        a, b = sum(1 for r in B if t in r["tags"]), sum(1 for r in R if t in r["tags"])
        if a or b:
            kind = "新出现" if a == 0 else "已解决" if b == 0 else "变严重" if b > a else "变轻" if b < a else "持平"
            change.append({"tag": t, "before": a, "recent": b, "delta": b - a, "kind": kind})
    change.sort(key=lambda x: -abs(x["delta"]))
    # 各款式；某个问题在某款的占比是全店的 1.8 倍以上、且至少 5 条，标为热点
    skus = []
    for s in d["product"].get("variants", []):
        rs = [r for r in R if r.get("sku") == s]
        if rs:
            skus.append({"sku": s, "n": len(rs), "negShare": pct(sum(1 for r in rs if r["star"] <= 3), len(rs))})
    skus.sort(key=lambda s: -s["n"])
    hot = None
    for t in neg:
        for s in skus:
            c = sum(1 for r in R if r.get("sku") == s["sku"] and t in r["tags"])
            if c >= 5 and cnt.get(t):
                lift = round(pct(c, s["n"]) / pct(cnt[t], len(R)), 1)
                if lift >= 1.8 and (hot is None or lift > hot["lift"]):
                    others = [x for x in skus if x["sku"] != s["sku"]]
                    hot = {"name": t, "sku": s["sku"], "count": c, "total": cnt[t], "lift": lift, "negShare": s["negShare"],
                           "othersNeg": round(sum(x["negShare"] * x["n"] for x in others) / max(sum(x["n"] for x in others), 1), 1)}
    # 用户旅程：每个环节好评、抱怨的标签提及次数
    journey = []
    for st in d.get("stages", []):
        b = Counter(t for r in R for t in r["tags"] if t in neg and ts.get(t) == st)
        journey.append({"stage": st, "good": sum(1 for r in R for t in r["tags"] if t in pos and ts.get(t) == st),
                        "bad": sum(b.values()), "neg": b.most_common()})
    # 退货：原因码 × 备注里的真实原因
    rets = evs(lo, i, "退货")
    coded = Counter(e.get("code") for e in rets)
    codes = [c for c, _ in coded.most_common()]
    reals = [x for x, _ in Counter(e["real"] for e in rets).most_common()]
    top_code = codes[0] if codes else None
    returns = {"n": len(rets), "withNote": sum(1 for e in rets if e.get("hasNote")), "noNote": sum(1 for e in rets if not e.get("hasNote")),
               "topCode": top_code, "topCodeN": coded.get(top_code, 0),
               "realInTop": Counter(e["real"] for e in rets if e.get("code") == top_code and e.get("hasNote")).most_common(),
               "codes": codes, "reals": reals,
               "matrix": [[sum(1 for e in rets if e.get("code") == c and e["real"] == x) for x in reals] for c in codes]}
    msgs = Counter(e["real"] for e in evs(lo, i, "买家消息"))
    return {
        "idx": i, "week": f"{md(starts[i])}–{md(end(i))}", "end": end(i).isoformat(), "window": f"{md(starts[lo])}–{md(end(i))}",
        "kpi": {"voices": {"now": sum(now.values()), "prev": sum(prev.values()), "split": now},
                "negShare": {"now": trend[i]["negShare"], "prev": trend[i - 1]["negShare"]},
                "returns": {"now": now["退货"], "prev": prev["退货"], "d4": src["退货"]},
                "top": {"tag": top_tag, "now": top_share(i), "prev": top_share(i - 1)}},
        "sources": src, "pareto": pareto, "change": change, "skus": skus, "hot": hot, "journey": journey, "returns": returns,
        "messages": {"n": sum(msgs.values()), "top": [[k, v] for k, v in msgs.most_common() if k != "其他"][:3]},
        "actions": [{"name": r["name"], "count": r["count"], "owner": problems[r["name"]].get("owner"), "fix": problems[r["name"]].get("fix")}
                    for r in core if r["name"] in problems],
    }


snaps = [snap(i) for i in range(7, NW)]

cmp = (d.get("calc") or {}).get("compare") or {}
rows = [r for r in cmp.get("rows", []) if r.get("avg") is not None]
compare = {"names": [c.get("brand") or c.get("name") for c in cmp.get("comps", [])], "mine": cmp.get("mine"),
           "rows": [{"name": r["name"], "kind": r["kind"], "mine": r["mine"], "comps": r["comps"], "avg": r["avg"], "verdict": r.get("verdict")} for r in rows],
           "weak": [r["name"] for r in rows if r.get("verdict") in ("短板", "不如竞品")],
           "strong": [r["name"] for r in rows if r.get("verdict") in ("卖点", "比竞品好")]}

out = {"asOf": latest_end.isoformat(), "trend": trend, "snaps": snaps, "compare": compare,
       "owners": {k: {"owner": v.get("owner"), "fix": v.get("fix")} for k, v in problems.items()}}
p = own_path.parent / "dashboard.json"
p.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
for s in snaps:
    k = s["kpi"]
    print(f"{s['week']}：声音 {k['voices']['now']}（前周 {k['voices']['prev']}）差评 {k['negShare']['now']}%  最大问题 {k['top']['tag']} {k['top']['now']}%  "
          f"核心 {s['pareto']['core']} 占 {s['pareto']['cum']}%  热点 {s['hot'] and (s['hot']['name'], s['hot']['sku'], s['hot']['count'])}  退货 {s['returns']['n']}")
print(p)
