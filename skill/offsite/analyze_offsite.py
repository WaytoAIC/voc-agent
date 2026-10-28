"""站外 VOC · Reddit 分析：读 raw.json（采集）+ tags.json（AI 打的标签）+ config.json，算出全部数字。

用法：python3 analyze_offsite.py voc-reports/<ASIN>/data.json
- 站外数据在同目录的 offsite/；结果写 offsite/analysis.json，并写进 data.json 的 offsite 块（报告用）
- 单位 = 一个讨论串（帖子 + 它下面的评论）；relevant=false 的不计
- 站内对照：Reddit 话题按 onsite_map 对到站内评论的标签，算站内占比，看「站外也在说」还是「只有站外在说」
- ⑥ 用户旅程（情绪曲线）：每个环节 情绪 =（好评串 − 抱怨串）÷（好评串 + 抱怨串）× 100，站内评论同口径对照
- ⑦ 需求四象限：每个需求 被提到的讨论串占比（横轴）× 满意度（纵轴，同上公式），中位数切四块
所有数字由脚本算，AI 只能引用，不能改。
"""
import datetime as dt
import json
import pathlib
import sys
from collections import Counter

data_path = pathlib.Path(sys.argv[1]).resolve()
OFF = data_path.parent / "offsite"
own = json.loads(data_path.read_text(encoding="utf-8"))
cfg = json.loads((OFF / "config.json").read_text(encoding="utf-8"))
db = json.loads((OFF / "raw.json").read_text(encoding="utf-8"))
raw, tags = db["posts"], json.loads((OFF / "tags.json").read_text(encoding="utf-8"))

warn = []
tax = cfg["taxonomy"]
for pid, t in tags.items():                          # 体检：只许用词表里的词
    for k in ("neg", "pos", "persona", "alt"):
        bad = [x for x in t.get(k, []) if x not in tax.get(k, [])]
        if bad:
            warn.append(f"{pid} 的 {k} 用了词表外的词：{'、'.join(bad)}")
missing = [pid for pid in raw if pid not in tags]
if missing:
    warn.append(f"{len(missing)} 个帖子还没打标签")
stage_of, stages = cfg.get("stage_of", {}), cfg["stages"]
for x in tax["neg"] + tax["pos"]:
    if x not in stage_of:
        warn.append(f"标签「{x}」没在 stage_of 里定环节")

T = [(pid, t, raw[pid]) for pid, t in tags.items() if t.get("relevant") and pid in raw]
n = len(T)
pct = lambda a, b: round(a / b * 100, 1) if b else 0.0
cnt = lambda key: Counter(x for _, t, _ in T for x in t.get(key, []))
neg, pos, persona, alt, brand = cnt("neg"), cnt("pos"), cnt("persona"), cnt("alt"), cnt("brand")
subs = Counter(p["subreddit"] for _, _, p in T)
months = Counter((p.get("created") or "")[:7] for _, _, p in T if p.get("created"))
comments = sum(len(p.get("comments", [])) for _, _, p in T)

U = [r for r in own["reviews"] if not r.get("vine")]
own_share = lambda tag: pct(sum(1 for r in U if tag in r["tags"]), len(U))
omap = cfg.get("onsite_map", {})
onsite = [{"topic": k, "kind": "neg" if k in neg else "pos", "threads": c, "share": pct(c, n),
           "onsiteTag": omap.get(k), "onsite": own_share(omap[k]) if omap.get(k) else None}
          for k, c in (neg + pos).most_common()]


def score(g, b):
    return round((g - b) / (g + b) * 100) if g + b else None


ostage, demand, compare = cfg.get("onsite_stage", {}), cfg.get("demand_stage"), cfg.get("compare_stage")
journey = []
for st in stages:
    in_st = lambda xs: any(stage_of.get(x) == st for x in xs)
    g = sum(1 for _, t, _ in T if in_st(t.get("pos", [])))
    b = sum(1 for _, t, _ in T if in_st(t.get("neg", [])))
    if st == demand:                                 # 需求触发 = 讨论串里说了为什么需要（人群），不分正负
        g = sum(1 for _, t, _ in T if t.get("persona"))
    og = sum(1 for r in U for x in r["tags"] if x in own["tagsPos"] and ostage.get(own["tagStage"].get(x)) == st)
    ob = sum(1 for r in U for x in r["tags"] if x in own["tagsNeg"] and ostage.get(own["tagStage"].get(x)) == st)
    journey.append({
        "stage": st, "good": g, "bad": b, "score": score(g, b),
        "talked": g if st == demand else sum(1 for _, t, _ in T if in_st(t.get("pos", []) + t.get("neg", []))),
        "alt": sum(1 for _, t, _ in T if t.get("alt")) if st == compare else 0,
        "pains": Counter(x for _, t, _ in T for x in t.get("neg", []) if stage_of.get(x) == st).most_common(3),
        "gains": Counter(x for _, t, _ in T for x in t.get("pos", []) if stage_of.get(x) == st).most_common(3),
        "onsite": score(og, ob) if st in ostage.values() else None, "onsiteN": og + ob,
        "opportunity": (cfg.get("opportunities") or {}).get(st, "")})

needs = []
for nd in cfg.get("needs", []):
    rp, rn, op, on = nd.get("pos", []), nd.get("neg", []), nd.get("onsite_pos", []), nd.get("onsite_neg", [])
    g = sum(1 for _, t, _ in T if set(t.get("pos", [])) & set(rp))
    b = sum(1 for _, t, _ in T if set(t.get("neg", [])) & set(rn))
    m = sum(1 for _, t, _ in T if set(t.get("pos", []) + t.get("neg", [])) & set(rp + rn))
    og = sum(1 for r in U if set(r["tags"]) & set(op))
    ob = sum(1 for r in U if set(r["tags"]) & set(on))
    if m:
        needs.append({"need": nd["name"], "mentions": m, "share": pct(m, n), "good": g, "bad": b, "sat": score(g, b),
                      "onsiteShare": pct(og + ob, len(U)) if op or on else None, "onsiteSat": score(og, ob)})
mid = sorted(s["share"] for s in needs)[len(needs) // 2] if needs else 0   # 取中间位置那个值，和工作台同一口径
for s in needs:                                      # 四象限：横轴按中位数切，纵轴按 0 切
    hi, ok = s["share"] >= mid, (s["sat"] or 0) > 0
    s["quadrant"] = "核心卖点 · 守住" if hi and ok else "最大机会 · 先做" if hi else "加分项" if ok else "潜在痛点 · 盯着"

quotes = [{"topic": q.get("topic"), "en": q["en"], "zh": q["zh"], "sub": p["subreddit"],
           "date": (p.get("created") or "")[:10], "url": q.get("url") or p["permalink"]}
          for _, t, p in T for q in t.get("quotes", [])]
dates = [p.get("created") or "" for _, _, p in T if p.get("created")]
out = {
    "asOf": dt.date.today().isoformat(), "source": "Reddit", "range": [min(dates)[:10], max(dates)[:10]] if dates else ["", ""],
    "pulled": len(raw), "relevant": n, "comments": comments, "subreddits": len(subs), "runs": db.get("runs", []),
    "via": dict(Counter(v.split(":")[0] for _, _, p in T for v in p.get("via", []))),
    "neg": [[k, v, pct(v, n)] for k, v in neg.most_common()], "pos": [[k, v, pct(v, n)] for k, v in pos.most_common()],
    "persona": [[k, v, pct(v, n)] for k, v in persona.most_common()], "alt": [[k, v] for k, v in alt.most_common()],
    "brand": [[k, v] for k, v in brand.most_common(8)], "subs": subs.most_common(8), "months": sorted(months.items())[-12:],
    "journey": journey, "needs": needs, "needMedian": mid, "onsite": onsite, "onsiteN": len(U), "quotes": quotes,
    "threads": [{"id": pid, "title": p["title"], "titleIsSummary": p.get("title_is_summary", False), "sub": p["subreddit"],
                 "date": (p.get("created") or "")[:10], "url": p["permalink"], "comments": len(p.get("comments", [])),
                 "neg": t.get("neg", []), "pos": t.get("pos", []), "persona": t.get("persona", []), "gist": t.get("gist", "")}
                for pid, t, p in sorted(T, key=lambda x: x[2].get("created") or "", reverse=True)],
    "warnings": warn,
}
(OFF / "analysis.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
own["offsite"] = out
data_path.write_text(json.dumps(own, ensure_ascii=False, indent=1), encoding="utf-8")

print(f"相关讨论串 {n}/{len(raw)}，评论 {comments}，板块 {len(subs)}，时间 {out['range'][0]}~{out['range'][1]}")
print("抱怨：" + "、".join(f"{k} {v}" for k, v, _ in out["neg"][:6]))
print("人群：" + "、".join(f"{k} {v}" for k, v, _ in out["persona"][:5]))
low = sorted([s for s in journey if s["score"] is not None and s["stage"] != demand], key=lambda s: s["score"])
if low:
    print(f"⑥ 情绪最低：{low[0]['stage']}（{low[0]['score']}）；站内看不到的环节：" + ("、".join(s["stage"] for s in journey if s["onsite"] is None and s["talked"]) or "无"))
first = [s["need"] for s in needs if s["quadrant"] == "最大机会 · 先做"]
print("⑦ 最大机会 · 先做：" + ("、".join(first) or "无"))
for w in warn:
    print("⚠ " + w)
