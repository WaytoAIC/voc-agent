"""项目时间线 + 功能价值：把这个 VOC 项目里所有带日期的动作串成一条线，写成 voc-reports/timeline.json（工作台「资产库」页读它）。

用法：python3 <skill>/timeline.py            # 写 timeline.json 并打印摘要
      python3 <skill>/timeline.py --json     # 只把结果打到 stdout
来源（都只读文件，不调任何接口）：
  运转   voc-reports/runs.jsonl（weekly.py 每次运转：拉了多少、打了多少标、入飞书多少行、哪步失败）
  版本   git log（每次 commit = 一次能力或口径的变化；落款去掉）
  文档   git 里每个文档第一次入库的日期（调研 / 课程 / 方案总纲 / 架构）
  数据   每个 ASIN 的 data.json：评论最早 / 最新一条、最近一次拉取、退货等事件的区间
  行动   voc-reports/actions.json：每张卡的计划完成 / 实际完成 / 验证到期 / Agent 读回
  播报   工作台/sent.log：发到飞书群的每一条
  评测   现场分析/_eval/eval-*.json：打标金标评测
  计划   Hermes 定时任务（~/.hermes/profiles/<profile>/cron/jobs.json）的下次触发时间（只在本机有）
功能价值（features）：每个功能一张卡——它做什么、累计做了多少、最近一次是什么时候、现在状态；数字全部从上面的文件里算。
脱敏投影的自家数据只用别名侧的日期和条数，真实 ASIN 不出现在这里。
"""
import datetime as dt
import glob
import json
import os
import pathlib
import re
import subprocess
import sys
from collections import Counter

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import voccfg  # noqa: E402

CFG = voccfg.load(HERE)
ROOT = pathlib.Path(CFG.get("_path", HERE.parent / "voc.config.json")).resolve().parent if CFG.get("_path") else HERE.parent
DATA = voccfg.data_dir(HERE)
WB = next((p for p in (ROOT / "工作台", ROOT / "workbench") if p.exists()), ROOT / "工作台")
OWN = (CFG.get("own") or {}).get("asin", "").upper()
COMPS = [a.upper() for a in CFG.get("competitors", [])]
PROFILE = (CFG.get("hermes") or {}).get("profile", "voc")
TODAY = dt.date.today()
OUT = DATA / "timeline.json"


def _json(p):
    try:
        return json.loads(pathlib.Path(p).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _git(*args):
    try:
        r = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, timeout=20)
        return r.stdout if r.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _day(t):
    return dt.date.fromtimestamp(t / 1000)


def _sign_strip(s):
    return re.sub(r"\s*@(Claude Code|Codex|Hermes|OpenClaw|WorkBuddy|Grok|负责人)\s*$", "", s).strip()


def cron_text(expr):
    """简单 cron 翻成人话：'0 9 * * 1' → 每周一 09:00；翻不了就原样。"""
    try:
        mi, h, dom, mon, dow = expr.split()
        wd = "一二三四五六日"
        if dom == "*" and mon == "*" and dow.isdigit():
            return f"每周{wd[(int(dow) - 1) % 7]} {int(h):02d}:{int(mi):02d}"
        if dom == "*" and mon == "*" and dow == "*":
            return f"每天 {int(h):02d}:{int(mi):02d}"
    except (ValueError, AttributeError):
        pass
    return expr


def ev(date, kind, title, detail="", **extra):
    e = {"date": str(date)[:10], "kind": kind, "title": title, "detail": detail}
    e.update({k: v for k, v in extra.items() if v is not None})
    return e


def collect():
    events, features = [], []
    datas = {a: _json(DATA / a / "data.json") for a in [OWN, *COMPS]}
    datas = {a: d for a, d in datas.items() if d}
    runs = []
    rp = DATA / "runs.jsonl"
    if rp.exists():
        for line in rp.read_text(encoding="utf-8").splitlines():
            try:
                runs.append(json.loads(line))
            except json.JSONDecodeError:
                pass

    # ---- 运转 ----
    for r in runs:
        st = r.get("steps") or {}
        bits = []
        pulled = (st.get("拉评论") or {}).get("byAsin") or {}
        new = {a: v.get("new") for a, v in pulled.items() if v.get("new")}
        if new:
            bits.append("新评论 " + "、".join(f"{a} {n}" for a, n in new.items()))
        if r.get("tagged"):
            bits.append(f"打标 {r['tagged']} 条")
        pj = st.get("投影") or {}
        if pj.get("variants"):
            bits.append(f"投影 {pj.get('realReviews')} → {pj.get('variants')} 条评论" + (f"、{pj.get('events')} 条事件" if pj.get("events") else ""))
        if r.get("feishu"):
            bits.append(f"入飞书 {r['feishu']} 行")
        ck = (st.get("行动卡") or {}).get("checkText") or ""
        if ck:
            bits.append(ck.splitlines()[0].split("：", 1)[-1])
        events.append(ev(r.get("at", ""), "运转", ("演练" if r.get("dry") else "每周运转") + ("（有失败）" if r.get("ok") is False else ""),
                        "；".join(bits) or r.get("note", ""), time=(r.get("at") or "")[11:16], ok=r.get("ok"), calls=r.get("calls"),
                        seconds=r.get("seconds"), log=r.get("log")))

    # ---- 版本（git） ----
    commits = [l.split("|", 1) for l in _git("log", "--format=%ad|%s", "--date=short").splitlines() if "|" in l]
    for date, subject in commits:
        title = _sign_strip(subject)
        title = re.sub(r"^VOC分析[:：]\s*", "", title)
        head, _, tail = title.partition("——")
        events.append(ev(date, "版本", head.strip(), tail.strip()))

    # ---- 文档：第一次入库的日期 ----
    docs = []
    for pat in ("调研/*.md", "课程/*.md", "方案总纲-*.md", "架构/*.html", "VOC入口清单-打码版/*", "导出/*.html"):
        docs += [p for p in ROOT.glob(pat) if p.is_file()]
    for p in sorted(docs):
        rel = str(p.relative_to(ROOT))
        first = _git("log", "--diff-filter=A", "--format=%ad", "--date=short", "--follow", "--", rel).strip().splitlines()
        m = re.search(r"(20\d{2})(\d{2})(\d{2})", p.stem)
        date = f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else (first[-1] if first else dt.date.fromtimestamp(p.stat().st_mtime).isoformat())
        events.append(ev(date, "文档", p.stem, rel, path=rel))

    # ---- 数据 ----
    for a, d in datas.items():
        U = [r for r in d.get("reviews", []) if r.get("t")]
        nm = (d.get("product") or {}).get("brand") or (d.get("product") or {}).get("name") or a
        role = "自家" if a == OWN else "竞品"
        pu = d.get("pulled") or {}
        if U:
            lo, hi = min(_day(r["t"]) for r in U), max(_day(r["t"]) for r in U)
            events.append(ev(hi, "数据", f"{role} {nm} 评论最新到 {hi}", f"{a}：{len(U)} 条，{lo} 起", asin=a))
        if pu.get("at"):
            lp = pu.get("lastPull") or {}
            events.append(ev(pu["at"], "数据", f"拉取 {role} {nm} 评论", f"{a}：本次新增 {lp.get('new', 0)}，累计 {pu.get('total', len(U))} 条" + (f"，{pu['source']}" if pu.get("source") else ""),
                            time=pu["at"][11:16], asin=a))
        evs = [e for e in d.get("events", []) if e.get("date")]
        if evs:
            by = Counter(e.get("type", "退货") for e in evs)
            hi = max(e["date"][:10] for e in evs)
            events.append(ev(hi, "数据", f"{role} 退货等事件最新到 {hi}", "、".join(f"{t} {n}" for t, n in by.items()) + f"（{min(e['date'][:10] for e in evs)} 起）", asin=a))

    # ---- 行动 ----
    acts = _json(DATA / "actions.json") or {}
    for c in acts.get("actions", []):
        t = f"{c.get('id')} {c.get('problem') or ''}".strip()
        if c.get("planDate"):
            events.append(ev(c["planDate"], "行动", f"计划完成：{t}", c.get("plan") or "", act=c.get("id")))
        if c.get("doneDate"):
            events.append(ev(c["doneDate"], "行动", f"上线：{t}", c.get("plan") or "", act=c.get("id")))
        if c.get("verifyDate"):
            future = c["verifyDate"] > TODAY.isoformat()
            events.append(ev(c["verifyDate"], "行动", ("验证到期：" if future else "验证日：") + t,
                             (f"看「{c.get('metric')}」{c.get('start') or '—'} → 目标 {c.get('target') or '—'}" if c.get("metric") else "") + (f"；判断：{c['judgement']}" if c.get("judgement") else ""),
                             act=c.get("id"), future=future or None))
        if c.get("readbackAt"):
            events.append(ev(c["readbackAt"], "行动", f"Agent 读回：{t}", f"实际 {c.get('actual') or '—'}，{c.get('judgement') or '待判断'}", act=c.get("id")))
    if acts.get("asOf"):
        events.append(ev(acts["asOf"], "行动", "行动卡镜像", f"从飞书「行动项跟踪」拉回 {len(acts.get('actions', []))} 张卡"))

    # ---- 播报 ----
    sent = []
    sp = WB / "sent.log"
    if sp.exists():
        for line in sp.read_text(encoding="utf-8").splitlines():
            f = line.split("\t")
            if len(f) >= 4:
                sent.append(f)
                events.append(ev(f[0], "播报", f"发到 {f[2]}" + ("" if f[1] == "ok" else "（失败）"), f[3], time=f[0][11:16], ok=f[1] == "ok"))

    # ---- 评测 ----
    evals = sorted(_json(p) for p in glob.glob(str(DATA / "_eval" / "eval-*.json")))
    evals = [e for e in evals if e]
    for e in evals:
        events.append(ev(e.get("date", ""), "评测", f"打标金标评测 {e.get('model', '')}", f"{e.get('n')} 条：Jaccard {e.get('jaccard')}，方向一致 {e.get('polarity_pct')}%，完全一致 {e.get('exact_pct')}%"))

    # ---- 计划（Hermes 定时） ----
    cron = _json(pathlib.Path.home() / ".hermes" / "profiles" / PROFILE / "cron" / "jobs.json") or {}
    job = next((j for j in cron.get("jobs", []) if "VOC" in (j.get("name") or "")), None)
    nxt = None
    if job:
        nxt = {"name": job.get("name"), "next": (job.get("next_run_at") or "")[:16].replace("T", " "), "last": (job.get("last_run_at") or "")[:16].replace("T", " "),
               "lastStatus": job.get("last_status"), "enabled": job.get("enabled"), "state": job.get("state"), "schedule": cron_text(job.get("schedule_display") or ""),
               "cron": job.get("schedule_display"), "completed": (job.get("repeat") or {}).get("completed")}
        if nxt["next"]:
            events.append(ev(nxt["next"], "计划", "下次自动运转", f"Hermes 定时「{job.get('name')}」{nxt['schedule']}", time=nxt["next"][11:16], future=True))

    events.sort(key=lambda e: (e["date"], e.get("time") or ""), reverse=True)

    # ================= 功能价值 =================
    real = [r for r in runs if not r.get("dry")]
    own = datas.get(OWN) or {}
    ownU = [r for r in own.get("reviews", []) if not r.get("vine")]
    pj = own.get("projection") or {}
    k = float(pj.get("k") or 0)
    allU = [r for d in datas.values() for r in d.get("reviews", []) if not r.get("vine")]
    tagged = [r for r in allU if r.get("tags") or r.get("tagger")]
    ownEv = [e for e in own.get("events", []) if e.get("date")]
    last_pull = max((((d.get("pulled") or {}).get("at") or "") for d in datas.values()), default="")
    calls = sum(int(r.get("calls") or 0) for r in runs)
    new_total = sum(int(r.get("newReviews") or 0) for r in real)

    def card(key, name, does, value, last=None, status="good", note="", link=None):
        return {"key": key, "name": name, "does": does, "value": value, "last": last, "status": status, "note": note, "link": link}

    features.append(card("pull", "增量拉评论", "自家 + 竞品按日期倒序只拉到已有评论为止，每周约十几次调用",
                         [["评论在库", f"{len(allU)} 条"], ["产品", f"{len(datas)} 个"], ["运转以来新增", f"{new_total} 条"], ["卖家精灵调用", f"{calls} 次"]],
                         last_pull or None, "good" if last_pull else "plain", "" if last_pull else "还没拉过"))
    ck = (own.get("calc") or {}).get("check") or {}
    ev_last = evals[-1] if evals else {}
    features.append(card("tag", "模型打标", "按 voc.config.json 词表给每条评论和退货备注打一级标签，金标集评测过线才算数",
                         [["已打标", f"{len(tagged)} 条"], ["自家覆盖", f"{ck.get('taggedPct', '—')}%"], ["备注读出", f"{sum(1 for e in ownEv if e.get('real'))} 条"],
                          ["金标 Jaccard", f"{ev_last.get('jaccard', '—')}" + (f"（方向一致 {ev_last.get('polarity_pct')}%）" if ev_last else "")]],
                         ev_last.get("date"), "good" if ck.get("taggedPct", 0) >= 95 else ("warn" if ownU else "plain"), f"模型 {ev_last.get('model')}" if ev_last else "还没跑过 tag.py eval"))
    if pj:
        features.append(card("project", "脱敏投影", "真实自家数据原话改写、等比扩增、日期平移后才进仓和飞书；判断看真实样本量",
                             [["倍数 k", f"×{int(k) if k.is_integer() else k}"], ["真实 → 投影评论", f"{pj.get('realReviews')} → {len(ownU)}"], ["真实 → 投影事件", f"{pj.get('realEvents')} → {len(ownEv)}"], ["真实 ASIN", "不出现在任何对外文件"]],
                             pj.get("at"), "good", pj.get("note", "")))
    reports = [a for a in datas if (DATA / a / "报告.html").exists()]
    dash = _json(DATA / OWN / "dashboard.json") or {}
    features.append(card("analyze", "分析报告与看板", "每个产品一份报告（问题、旅程、款式、优先级分）；首页看板按运行日锚定，12 周 + 12 个月 + 累计",
                         [["报告", f"{len(reports)} 份"], ["看板最新完整周", dash.get("latestWeek") or "—"], ["累计评论", f"{(dash.get('cumulative') or {}).get('reviews', '—')} 条"],
                          ["评论最新到", (dash.get("fresh") or {}).get("lastReview") or "—"]],
                         dash.get("runDate"), "good" if dash else "plain", "评论少的品看月度和累计，周环比只看方向" if dash else "先跑 dashboard.py"))
    if ownEv:
        by = Counter(e.get("type", "退货") for e in ownEv)
        features.append(card("events", "退货 · 换货 · 买家消息", "后台退货报告导入，原因码翻中文、备注读成真实原因，和评论放在同一条时间线上",
                             [[t, f"{by.get(t, 0)} 条"] for t in ("退货", "换货", "买家消息")] + [["备注已读", f"{sum(1 for e in ownEv if e.get('real'))}/{sum(1 for e in ownEv if e.get('note'))}"]],
                             max(e["date"][:10] for e in ownEv), "good" if by.get("退货") else "plain",
                             "换货 / 买家消息还没接" if not by.get("换货") and not by.get("买家消息") else ""))
    else:
        features.append(card("events", "退货 · 换货 · 买家消息", "后台退货报告导入，原因码翻中文、备注读成真实原因", [["退货", "未接"]], None, "plain", "从后台导出表格后 import_events.py"))
    acl = acts.get("actions", [])
    st = Counter(a.get("status") for a in acl)
    jd = Counter(a.get("judgement") for a in acl if a.get("judgement"))
    series = sum(1 for a in acl if (a.get("series") or {}).get("points"))
    stuck = ""
    cm = DATA / "actions_check.md"
    if cm.exists():
        m = re.search(r"卡住 (\d+) 处", cm.read_text(encoding="utf-8"))
        stuck = m.group(1) if m else ""
    last_run_check = next((((r.get("steps") or {}).get("行动卡") or {}).get("checkText", "") for r in reversed(runs) if ((r.get("steps") or {}).get("行动卡") or {}).get("checkText")), "")
    mstuck = re.search(r"卡住 (\d+) 处", last_run_check)
    features.append(card("actions", "行动闭环", "飞书「行动项跟踪」人拍板、Agent 起草和读回；到期自动算动作—结果曲线",
                         [["行动卡", f"{len(acl)} 张"], ["待决定 / 执行中 / 等验证 / 已复盘", f"{st.get('待决定', 0)} / {st.get('执行中', 0)} / {st.get('等验证', 0)} / {st.get('已复盘', 0)}"],
                          ["验证过", f"有效 {jd.get('有效', 0)} · 无效 {jd.get('无效', 0)} · 看不出 {jd.get('看不出来', 0)}"], ["动作—结果曲线", f"{series} 张"]],
                         acts.get("asOf"), "warn" if (mstuck and int(mstuck.group(1))) else ("good" if acl else "plain"),
                         (f"卡住 {mstuck.group(1)} 处（巡检）" if mstuck and int(mstuck.group(1)) else ("" if acl else "先 actions.py pull")),
                         link="行动项跟踪"))
    fs_rows = None
    last_fs = next((((r.get("steps") or {}).get("入飞书") or {}) for r in reversed(runs) if (((r.get("steps") or {}).get("入飞书") or {}).get("written") is not None)), {})
    if last_fs:
        fs_rows = int(last_fs.get("written") or 0) + int(last_fs.get("skipped") or 0)
    fs_total = sum(int(r.get("feishu") or 0) for r in real)
    features.append(card("feishu", "入飞书事件表", "新评论 / 新事件写进「VOC 事件明细」，一行一条，人工意见和关联行动在飞书里填",
                         [["表里行数（约）", f"{fs_rows} 行" if fs_rows is not None else "—"], ["运转以来写入", f"{fs_total} 行"], ["去重键", "事件 ID + 子ASIN + 原话"]],
                         next((r.get("at") for r in reversed(real) if r.get("feishu")), None), "good" if fs_rows else "plain", "" if fs_rows else "还没写过", link="VOC 事件明细"))
    draft = DATA / "weekly_draft.md"
    features.append(card("broadcast", "群播报", "每周运转起草群消息（新声音、最大问题、退货、卡住的行动），人改好点「发到群」才发",
                         [["已发到群", f"{sum(1 for f in sent if f[1] == 'ok')} 条"], ["草稿", "有，待人点发" if draft.exists() else "无"]],
                         (sent[-1][0][:16] if sent else None), "good" if sent else "plain", f"最近草稿 {dt.datetime.fromtimestamp(draft.stat().st_mtime):%Y-%m-%d %H:%M}" if draft.exists() else "", link="群"))
    alexa = _json(DATA / OWN / "alexa_compare.json")
    rd = _json(DATA / "reddit" / "analysis.json") if (DATA / "reddit" / "analysis.json").exists() else None
    off_val = [["Alexa 问答", f"{len(alexa.get('by') or [])} 个产品对比" if alexa else "未采集"], ["Reddit", (f"{rd.get('relevant', len(rd.get('threads', [])))} 个讨论串" if isinstance(rd, dict) else "未分析")]]
    features.append(card("offsite", "站外与平台归纳", "Alexa 问答（平台归纳，只对照不计数）和 Reddit 讨论串（人挑、AI 判相关）",
                         off_val, None, "good" if (alexa or rd) else "plain", ""))
    ok_runs = sum(1 for r in real if r.get("ok"))
    features.append(card("weekly", "每周自动运转", "Hermes 定时周一 09:00 跑 weekly.py：拉 → 打标 → 投影 → 算数 → 行动卡 → 入飞书 → 群草稿 → 留痕",
                         [["真跑", f"{len(real)} 次（成功 {ok_runs}）"], ["演练", f"{len(runs) - len(real)} 次"], ["定时", (nxt or {}).get("schedule") or cron_text((CFG.get("weekly") or {}).get("schedule", "—"))],
                          ["下次", (nxt or {}).get("next") or "—"]],
                         (real[-1].get("at") if real else None), "good" if (nxt or {}).get("enabled") else ("warn" if real else "plain"),
                         "" if (nxt or {}).get("enabled") else "本机没读到 Hermes 定时任务，看命令速查 2.5"))
    hist = sorted((DATA / "_history").glob("*.md")) if (DATA / "_history").exists() else []
    features.append(card("history", "资产沉淀", "每次运转后自动 commit 数据、看板、行动卡和本周周报；仓库历史就是项目时间线",
                         [["commit", f"{len(commits)} 次"], ["周报留档", f"{len(hist)} 份"], ["文档", f"{sum(1 for e in events if e['kind'] == '文档')} 份"], ["时间线条目", f"{len(events)} 条"]],
                         commits[0][0] if commits else None, "good" if commits else "plain", "", link=None))

    kinds = Counter(e["kind"] for e in events)
    return {"builtAt": f"{dt.datetime.now():%Y-%m-%d %H:%M}", "today": TODAY.isoformat(), "own": OWN, "events": events, "kinds": dict(kinds),
            "features": features, "next": nxt, "lastRun": (real[-1] if real else (runs[-1] if runs else None)) and {k: (real[-1] if real else runs[-1]).get(k) for k in ("at", "ok", "note", "newReviews", "tagged", "feishu", "calls")}}


if __name__ == "__main__":
    out = collect()
    if "--json" in sys.argv:
        print(json.dumps(out, ensure_ascii=False))
    else:
        OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"时间线 {len(out['events'])} 条（" + "、".join(f"{k} {v}" for k, v in out["kinds"].items()) + f"），功能 {len(out['features'])} 项 → {OUT}")
        for f in out["features"]:
            print(f"  [{f['status']}] {f['name']}：" + "；".join(f"{a} {b}" for a, b in f["value"]) + (f"（{f['last']}）" if f.get("last") else ""))
        if out.get("next"):
            print(f"  下次自动运转 {out['next'].get('next')}（{out['next'].get('state')}）")
