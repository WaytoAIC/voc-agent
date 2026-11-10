"""算 VOC 工作台首页「数据看板」的数字，写成 <ASIN>/dashboard.json。

用法：python3 dashboard.py <自家 ASIN>/data.json --vs <竞品>/data.json ...
口径：
  - 周 = 周一到周日；「最新一周」= 运行日（默认今天，--as-of YYYY-MM-DD 或环境变量 VOC_AS_OF 可改）之前最后一个完整周，往前共 12 周。
    评论少的周就是 0，不拿数据里最后一条评论当「本周」糊弄；评论最新到哪天、退货最新到哪天写在 fresh 里，页面照实说。
  - 月度（monthly）：到最新完整周所在月为止的近 12 个月，每月评论 / 差评占比 / 退货 / 换货 / 买家消息；累计（cumulative）：全部非送测评论和事件的总数与覆盖区间。
    评论少的产品看月度和累计，周环比只看方向。
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
import os
import pathlib
import sys
from collections import Counter

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import voccfg  # noqa: E402

args = sys.argv[1:]
AS_OF = None
if "--as-of" in args:
    i = args.index("--as-of")
    AS_OF = dt.date.fromisoformat(args[i + 1])
    del args[i:i + 2]
elif os.environ.get("VOC_AS_OF"):
    AS_OF = dt.date.fromisoformat(os.environ["VOC_AS_OF"])
if "--vs" in args:                                                            # 竞品路径只是和 analyze.py 命令行对齐，这里不用（compare 读 calc.compare）
    args = args[:args.index("--vs")]
LIVE = pathlib.Path(__file__).resolve().parent
if not args:
    CFG = voccfg.load(LIVE)
    args = [str(LIVE / CFG["own"]["asin"] / "data.json")]       # 不带参数 = 用 voc.config.json 里的自家产品
own_path = pathlib.Path(args[0])
CFG = voccfg.load(own_path)
d = json.loads(own_path.read_text(encoding="utf-8"))
K_PJ = float((d.get("projection") or {}).get("k") or 0)                       # 脱敏投影倍数：有就把本周声音折回真实样本量（realNow），判断看它
voccfg.canonicalize(d, CFG)
DB = CFG["thresholds"]["dashboard"]
HOT = CFG["thresholds"]["sku_hot"]

U = [r for r in d["reviews"] if not r.get("vine")]
day = lambda r: dt.date.fromtimestamp(r["t"] / 1000)
RUN_DAY = AS_OF or dt.date.today()
latest_end = RUN_DAY - dt.timedelta(days=(RUN_DAY.weekday() + 1) % 7)    # 运行日之前最后一个周日 = 最新完整周的结束
last_review = max((day(r) for r in U), default=None)
NW = DB["weeks"]
starts = [latest_end - dt.timedelta(days=6 + 7 * k) for k in range(NW - 1, -1, -1)]
end = lambda i: starts[i] + dt.timedelta(days=6)
md = lambda x: f"{x.month}/{x.day}"
wk = lambda x: next((i for i, s in enumerate(starts) if s <= x <= end(i)), None)
for r in U:
    r["_w"] = wk(day(r))
ev = [e for e in d.get("events", []) if e.get("date")]
for e in ev:
    e["_w"] = wk(dt.date.fromisoformat(e["date"][:10]))
last_event = {t: max((e["date"][:10] for e in ev if e.get("type") == t), default=None) for t in ("退货", "换货", "买家消息")}
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
    lo = i - (DB["window_weeks"] - 1)             # 近 4 周
    R = rv(lo, i)

    def voices(w):
        out = {"评论": len(rv(w, w))}
        for t in ("退货", "换货", "买家消息"):
            out[t] = len(evs(w, w, t))
        return out
    now, prev = voices(i), voices(i - 1)
    cnt = Counter(t for r in R for t in r["tags"] if t in neg)
    top_tag = cnt.most_common(1)[0][0] if cnt else None      # 评论少的产品可能某几周没有抱怨
    top_share = lambda w: pct(sum(1 for r in rv(w, w) if top_tag in r["tags"]), len(rv(w, w))) if top_tag else 0.0
    src = {"评论": len(R)}
    for t in ("退货", "换货", "买家消息"):
        src[t] = len(evs(lo, i, t))
    # 问题排名：累计到 80% 之前的算核心问题
    tot = sum(cnt.values())
    rows, cum = [], 0.0
    for name, c in cnt.most_common():
        sh = pct(c, tot)
        rows.append({"name": name, "count": c, "share": sh, "stage": ts.get(name, ""), "core": cum < CFG["thresholds"]["pareto_core_pct"]})
        cum += sh
    core = [r for r in rows if r["core"]]
    pareto = {"rows": rows, "mentions": tot, "core": [r["name"] for r in core], "cum": round(sum(r["share"] for r in core), 1)}
    # 抱怨怎么变
    B = rv(i - 2 * DB["window_weeks"] + 1, i - DB["window_weeks"])
    change = []
    for t in neg:
        a, b = sum(1 for r in B if t in r["tags"]), sum(1 for r in R if t in r["tags"])
        if a or b:
            kind = "新出现" if a == 0 else "已解决" if b == 0 else "变严重" if b > a else "变轻" if b < a else "持平"
            change.append({"tag": t, "before": a, "recent": b, "delta": b - a, "kind": kind})
    change.sort(key=lambda x: -abs(x["delta"]))
    # 各款式；某个问题在某款的占比是全店的 lift 倍以上、且满足 voc.config.json thresholds.sku_hot，标为热点
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
            if c >= HOT["min_count"] and s["n"] >= HOT["min_sku_reviews"] and cnt.get(t):
                lift = round(pct(c, s["n"]) / pct(cnt[t], len(R)), 1)
                if lift >= HOT["lift"] and pct(c, s["n"]) >= pct(cnt[t], len(R)) + HOT["margin_pct"] and (hot is None or lift > hot["lift"]):
                    others = [x for x in skus if x["sku"] != s["sku"]]
                    hot = {"name": t, "sku": s["sku"], "count": c, "total": cnt[t], "lift": lift, "negShare": s["negShare"],
                           "othersNeg": round(sum(x["negShare"] * x["n"] for x in others) / max(sum(x["n"] for x in others), 1), 1)}
    # 用户旅程：每个环节好评、抱怨的标签提及次数
    journey = []
    for st in CFG["stages"]["order"]:
        b = Counter(t for r in R for t in r["tags"] if t in neg and ts.get(t) == st)
        journey.append({"stage": st, "good": sum(1 for r in R for t in r["tags"] if t in pos and ts.get(t) == st),
                        "bad": sum(b.values()), "neg": b.most_common()})
    # 退货：原因码 × 备注里的真实原因
    rets = [dict(e, real=e.get("real") or "说不清（没写备注）") for e in evs(lo, i, "退货")]
    coded = Counter(e.get("code") for e in rets)
    codes = [c for c, _ in coded.most_common()]
    reals = [x for x, _ in Counter(e["real"] for e in rets).most_common()]
    top_code = codes[0] if codes else None
    returns = {"n": len(rets), "withNote": sum(1 for e in rets if e.get("hasNote")), "noNote": sum(1 for e in rets if not e.get("hasNote")),
               "topCode": top_code, "topCodeN": coded.get(top_code, 0),
               "realInTop": Counter(e["real"] for e in rets if e.get("code") == top_code and e.get("hasNote")).most_common(),
               "codes": codes, "reals": reals,
               "matrix": [[sum(1 for e in rets if e.get("code") == c and e["real"] == x) for x in reals] for c in codes]}
    msgs = Counter(e.get("real") for e in evs(lo, i, "买家消息"))
    return {
        "idx": i, "week": f"{md(starts[i])}–{md(end(i))}", "end": end(i).isoformat(), "window": f"{md(starts[lo])}–{md(end(i))}",
        "kpi": {"voices": {"now": sum(now.values()), "prev": sum(prev.values()), "split": now, **({"realNow": round(sum(now.values()) / K_PJ), "realPrev": round(sum(prev.values()) / K_PJ)} if K_PJ else {})},
                "negShare": {"now": trend[i]["negShare"], "prev": trend[i - 1]["negShare"]},
                "returns": {"now": now["退货"], "prev": prev["退货"], "d4": src["退货"]},
                "top": {"tag": top_tag or "—", "now": top_share(i), "prev": top_share(i - 1)}},
        "sources": src, "pareto": pareto, "change": change, "skus": skus, "hot": hot, "journey": journey, "returns": returns,
        "messages": {"n": sum(msgs.values()), "top": [[k, v] for k, v in msgs.most_common() if k != "其他"][:3]},
        "actions": [{"name": r["name"], "count": r["count"], "owner": problems[r["name"]].get("owner"), "fix": problems[r["name"]].get("fix")}
                    for r in core if r["name"] in problems],
    }


snaps = [snap(i) for i in range(DB["min_weeks_for_snapshot"] - 1, NW)]      # 往前满 8 周的才能选；评论少的产品数字会很小，但不会报错

cmp = (d.get("calc") or {}).get("compare") or {}
rows = [r for r in cmp.get("rows", []) if r.get("avg") is not None]
compare = {"names": [c.get("brand") or c.get("name") for c in cmp.get("comps", [])], "mine": cmp.get("mine"),
           "rows": [{"name": r["name"], "kind": r["kind"], "mine": r["mine"], "comps": r["comps"], "avg": r["avg"], "verdict": r.get("verdict")} for r in rows],
           "weak": [r["name"] for r in rows if r.get("verdict") in ("短板", "不如竞品")],
           "strong": [r["name"] for r in rows if r.get("verdict") in ("卖点", "比竞品好")]}

# 月度：到最新完整周所在月为止的近 12 个月；累计：全部
mkeys = []
y, m = latest_end.year, latest_end.month
for _ in range(12):
    mkeys.append(f"{y}-{m:02d}")
    m -= 1
    if m == 0:
        y, m = y - 1, 12
mkeys.reverse()
mrev = {k: [] for k in mkeys}
for r in U:
    k = day(r).strftime("%Y-%m")
    if k in mrev:
        mrev[k].append(r)
mev = {k: Counter() for k in mkeys}
for e in ev:
    k = e["date"][:7]
    if k in mev:
        mev[k][e.get("type", "退货")] += 1
monthly = []
for k in mkeys:
    rows = mrev[k]
    n_neg = sum(1 for r in rows if r["star"] <= 3)
    row = {"month": k, "label": f"{int(k[5:])}月", "reviews": len(rows), "neg": n_neg, "negShare": pct(n_neg, len(rows)),
           "returns": mev[k]["退货"], "exchanges": mev[k]["换货"], "messages": mev[k]["买家消息"]}
    if K_PJ:
        row["realReviews"] = round(len(rows) / K_PJ)
    monthly.append(row)
first_review = min((day(r) for r in U), default=None)
cumulative = {"reviews": len(U), "vine": sum(1 for r in d["reviews"] if r.get("vine")), "neg": sum(1 for r in U if r["star"] <= 3),
              "negShare": pct(sum(1 for r in U if r["star"] <= 3), len(U)),
              "events": {t: sum(1 for e in ev if e.get("type") == t) for t in ("退货", "换货", "买家消息")},
              "firstReview": first_review.isoformat() if first_review else None, "lastReview": last_review.isoformat() if last_review else None,
              "months": len({day(r).strftime("%Y-%m") for r in U}),
              **({"realReviews": round(len(U) / K_PJ), "realEvents": round(len(ev) / K_PJ)} if K_PJ else {})}
fresh = {"lastReview": last_review.isoformat() if last_review else None, "lastEvent": last_event,
         "reviewGapDays": (latest_end - last_review).days if last_review else None,
         "lastWeekWithReviews": next((f"{md(starts[i])}–{md(end(i))}" for i in range(NW - 1, -1, -1) if trend[i]["reviews"]), None),
         "pulledAt": (d.get("pulled") or {}).get("at")}

out = {"asOf": latest_end.isoformat(), "runDate": RUN_DAY.isoformat(), "anchor": "run",
       "latestWeek": f"{md(starts[-1])}–{md(latest_end)}", "trend": trend, "snaps": snaps, "compare": compare,
       "monthly": monthly, "cumulative": cumulative, "fresh": fresh, "k": K_PJ or None,
       "owners": {k: {"owner": v.get("owner"), "fix": v.get("fix")} for k, v in problems.items()}}
p = own_path.parent / "dashboard.json"
p.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
for s in snaps:
    k = s["kpi"]
    print(f"{s['week']}：声音 {k['voices']['now']}（前周 {k['voices']['prev']}）差评 {k['negShare']['now']}%  最大问题 {k['top']['tag']} {k['top']['now']}%  "
          f"核心 {s['pareto']['core']} 占 {s['pareto']['cum']}%  热点 {s['hot'] and (s['hot']['name'], s['hot']['sku'], s['hot']['count'])}  退货 {s['returns']['n']}")
print(f"锚定运行日 {RUN_DAY}，最新完整周 {out['latestWeek']}；评论最新到 {fresh['lastReview']}（最近有评论的周 {fresh['lastWeekWithReviews'] or '12 周内没有'}），"
      f"退货最新到 {last_event['退货']}；累计评论 {cumulative['reviews']}" + (f"（真实 {cumulative['realReviews']}）" if K_PJ else "") + f"，近 12 个月 {sum(x['reviews'] for x in monthly)} 条")
print(p)
