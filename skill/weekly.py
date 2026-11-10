"""每周运转：一条命令把这周的事跑完，结果写 voc-reports/runs.jsonl（工作台设置页「运行记录」读它）。

用法：python3 <skill>/weekly.py [--dry-run] [--no-pull] [--no-tag] [--no-actions] [--no-feishu] [--export] [--asin B0XXXXXXXX] [--pages 3]
六步，任何一步失败都不拦后面的，结尾一起报：
  1 拉评论   自家 + 竞品（voc.config.json 的 own / competitors），卖家精灵按日期倒序只拉到已有评论为止（每个 ASIN 最多 --pages 页）；
             演示数据、还没分析过的 ASIN 不拉；自家开了脱敏投影（own.projection.enabled）时拉的是真实 ASIN，落 voc-reports/_real/（不进仓）
  2 打标签   tag.py 只补新评论；自家 events 里还没读过的备注跑 tag.py --events（模型通道见 tag.py）；投影模式下打的是真实数据
  2.5 投影   own.projection.enabled 时跑 _tools/project.py --check：真实数据 → 别名 data.json（原话改写、等比扩增、日期平移），核对分布与出口扫描
  3 算数     有新东西的竞品各跑 analyze.py；自家 analyze.py --vs 全部竞品；render.py 报告；dashboard.py 看板；--export 顺手重建离线版
  4 行动卡   actions.py pull → readback（只打印；weekly.readback_write=true 才写回飞书的两个 AI 字段）→ check --draft
  5 入飞书   新评论 / 新事件写进「VOC 事件明细」（_tools/events_to_feishu.py）
  6 群草稿   voc-reports/weekly_draft.md：本周新声音、最大问题变化、退货、卡住的行动。不自动发：工作台设置页「发到群」点了才发
  7 留痕     timeline.py 重算项目时间线（工作台「资产库」页）；本周周报存 voc-reports/_history/周报-<日期>.md（进 git）；
             weekly.commit=true 时把这次运转改动的数据、看板、行动卡、时间线、周报 commit 进仓（只 add 这几个路径，落款 weekly.commit_sign，默认 @Hermes；
             环境变量 VOC_COMMIT_SIGN 可改；--no-commit 跳过）。仓库历史就是项目时间线，资产随每周运转自动沉淀。
口径：voc.config.json 的 weekly 段（pages / detail / competitors / feishu / readback_write / export / schedule / commit / commit_sign）。
数据目录：VOC_DATA_DIR（默认 现场分析/；公开版默认 <项目根>/voc-reports，见 voccfg.data_dir）。
--dry-run：不调卖家精灵、不调模型、不写飞书，只走本地算数和草稿，看流程通不通。
每次的完整输出在 voc-reports/_runs/weekly-<时间>.log。
"""
import datetime as dt
import json
import os
import pathlib
import subprocess
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import voccfg  # noqa: E402

ARGS = sys.argv[1:]
CFG = voccfg.load(HERE)
W = {"pages": 3, "detail": True, "competitors": True, "feishu": True, "readback_write": False, "export": False, "commit": True, "commit_sign": "@Hermes",
     **{k: v for k, v in (CFG.get("weekly") or {}).items() if not k.startswith("_")}}
PAGES = int(ARGS[ARGS.index("--pages") + 1]) if "--pages" in ARGS else int(W["pages"])
DRY = "--dry-run" in ARGS
ONLY = ARGS[ARGS.index("--asin") + 1].upper() if "--asin" in ARGS else None
OWN = CFG["own"]["asin"].upper()
COMPS = [a.upper() for a in CFG.get("competitors", [])] if W["competitors"] else []
PJ = (CFG.get("own") or {}).get("projection") or {}
PROJ = bool(PJ.get("enabled"))                                                # 自家 = 真实数据的脱敏投影
PY = sys.executable
TOOLS = HERE / "_tools" if (HERE / "_tools").exists() else HERE            # 本地在 现场分析/_tools，公开仓在 skill/ 平铺
ROOT = HERE.parent
DATA = voccfg.data_dir(HERE)                                                  # VOC_DATA_DIR，否则 现场分析/（本地）或 voc-reports/（公开版）
os.environ["VOC_DATA_DIR"] = str(DATA)                                        # 子脚本（ss_pull / actions / events_to_feishu / serve）用同一个数据目录
WB = next((p for p in (ROOT / "工作台", ROOT / "workbench") if p.exists()), ROOT / "工作台")
SS_PULL = next((p for p in (TOOLS / "ss_pull.py", WB / "ss_pull.py") if p.exists()), TOOLS / "ss_pull.py")
REAL_DATA = DATA / "_real"                                                    # 投影模式：真实自家数据目录
REAL = None
if PROJ:
    _pp = pathlib.Path(os.environ.get("VOC_PROJECTION") or PJ.get("private") or "voc-reports/_real/projection.json")
    _pp = _pp if _pp.is_absolute() else next((q for q in (ROOT / _pp, REAL_DATA / "projection.json") if q.exists()), ROOT / _pp)
    REAL = json.loads(_pp.read_text(encoding="utf-8"))["real"].upper() if _pp.exists() else None
STAMP = dt.datetime.now()
RUNS = DATA / "_runs"
DATA.mkdir(parents=True, exist_ok=True)
RUNS.mkdir(exist_ok=True)
LOG = RUNS / f"weekly-{STAMP:%Y%m%d-%H%M}.log"
LOGF = LOG.open("w", encoding="utf-8")
REPORT = {"at": f"{STAMP:%Y-%m-%d %H:%M}", "dry": DRY, "steps": {}, "calls": 0, "newReviews": 0, "tagged": 0, "feishu": 0, "problems": []}


def log(*a):
    line = " ".join(str(x) for x in a)
    print(line, flush=True)
    LOGF.write(line + "\n")
    LOGF.flush()


def run(cmd, timeout=1800, env=None):
    """跑一个子命令，stdout/stderr 全进日志，返回 (returncode, stdout)。"""
    log(f"$ {' '.join(str(c) for c in cmd)}")
    try:
        r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, timeout=timeout, cwd=ROOT, env=env or os.environ)
    except subprocess.TimeoutExpired:
        log(f"  超时（{timeout}s）")
        return 124, ""
    for line in (r.stdout + ("\n" + r.stderr if r.stderr.strip() else "")).splitlines():
        LOGF.write("  " + line + "\n")
    tail = [l for l in r.stdout.splitlines() if l.strip()][-2:]
    for l in tail:
        log("  " + l[:200])
    if r.returncode:
        log(f"  退出码 {r.returncode}：{(r.stderr or r.stdout).strip().splitlines()[-1][:200] if (r.stderr or r.stdout).strip() else ''}")
    LOGF.flush()
    return r.returncode, r.stdout


def last_json(out):
    for line in reversed(out.strip().splitlines()):
        if line.startswith("{"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                pass
    return {}


def data(asin):
    p = DATA / asin / "data.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def is_demo(d):
    return bool(d and (d.get("demo") or (d.get("pulled") or {}).get("source") == "演示数据"))


def untagged(d):
    return sum(1 for r in d.get("reviews", []) if not r.get("vine") and not r.get("tags") and not r.get("tagger"))


def unread_events(d):
    return sum(1 for e in d.get("events", []) or [] if e.get("note") and not e.get("real"))


def step(name, fn):
    t0 = time.time()
    log(f"\n== {name} ==")
    try:
        res = fn() or {}
        res.setdefault("ok", True)
    except Exception as e:  # 一步坏了不拦后面
        res = {"ok": False, "error": str(e)[:300]}
        log(f"  出错：{e}")
    res["seconds"] = round(time.time() - t0, 1)
    REPORT["steps"][name] = res
    if not res.get("ok"):
        REPORT["problems"].append(f"{name}：{res.get('error') or '有失败'}")
    return res


# ---------- 1 拉评论 ----------
def s_pull():
    res = {"byAsin": {}, "skipped": []}
    if "--no-pull" in ARGS:
        res["note"] = "--no-pull"
        return res
    for asin in [OWN, *COMPS]:
        if ONLY and asin != ONLY:
            continue
        real = PROJ and asin == OWN                                           # 自家投影：拉真实 ASIN，落 _real/
        if real and not REAL:
            res["skipped"].append(f"{asin} 开了投影但找不到私有参数（projection.private）")
            continue
        d = data(asin) if not real else data_json(REAL_DATA / REAL / "data.json")
        if d is None:
            res["skipped"].append(f"{asin} 还没分析过（先用工作台添加产品）" if not real else f"{asin} 投影种子还没拉（先 ss_pull 真实 ASIN 到 _real/）")
            continue
        if is_demo(d):
            res["skipped"].append(f"{asin} 演示数据")
            continue
        if DRY:
            res["byAsin"][asin] = {"new": 0, "calls": 0, "dry": True, **({"real": True} if real else {})}
            continue
        cmd = [PY, SS_PULL, REAL if real else asin, "--pages", PAGES, "--merge", "--new-only", "--json"]
        if not W["detail"]:
            cmd.append("--no-detail")
        rc, out = run(cmd, timeout=1500, env={**os.environ, "VOC_DATA_DIR": str(REAL_DATA)} if real else None)
        j = last_json(out)
        res["byAsin"][asin] = {"new": j.get("new"), "calls": j.get("calls"), "pages": j.get("pages"), "errors": j.get("errors") or [], **({"real": True, "upgraded": j.get("upgraded")} if real else {})}
        REPORT["calls"] += int(j.get("calls") or 0)
        REPORT["newReviews"] += int(j.get("new") or 0)
        if rc or j.get("errors"):
            res["ok"] = False
            res["error"] = f"{asin} 拉取有失败：{j.get('errors') or rc}"
    for s in res["skipped"]:
        log("  跳过：" + s)
    return res


# ---------- 2 打标签 ----------
def s_tag():
    res = {"byAsin": {}}
    if "--no-tag" in ARGS:
        res["note"] = "--no-tag"
        return res
    for asin in [OWN, *COMPS]:
        if ONLY and asin != ONLY:
            continue
        real = PROJ and asin == OWN and REAL
        path = (REAL_DATA / REAL / "data.json") if real else (DATA / asin / "data.json")
        d = data_json(path)
        if d is None or is_demo(d):
            continue
        todo, ev = untagged(d), (unread_events(d) if asin == OWN else 0)
        if not todo and not ev:
            continue
        if DRY:
            res["byAsin"][asin] = {"untagged": todo, "events": ev, "dry": True}
            log(f"  {asin}：{todo} 条没打标、{ev} 条备注没读（--dry-run 不调模型）")
            continue
        if todo:
            rc, _ = run([PY, HERE / "tag.py", path, "--workers", "2"], timeout=2400)
            after = untagged(data_json(path) or {})
            res["byAsin"][asin] = {"tagged": todo - after, "left": after}
            REPORT["tagged"] += todo - after
            if rc:
                res["ok"], res["error"] = False, f"{asin} tag.py 退出码 {rc}"
        if ev:
            rc, _ = run([PY, HERE / "tag.py", path, "--events", "--workers", "2"], timeout=1200)
            res["byAsin"].setdefault(asin, {})["eventsRead"] = ev - unread_events(data_json(path) or {})
            if rc:
                res["ok"], res["error"] = False, f"{asin} tag.py --events 退出码 {rc}"
    return res


# ---------- 2.5 投影 ----------
def s_project():
    res = {}
    if not PROJ:
        res["note"] = "自家没开脱敏投影"
        return res
    tool = next((p for p in (TOOLS / "project.py", HERE / "project.py") if p.exists()), TOOLS / "project.py")
    cmd = [PY, tool, "--check", "--json"] + (["--dry-run"] if DRY else [])
    rc, out = run(cmd, timeout=3600)
    j = last_json(out)
    res.update({k: j.get(k) for k in ("k", "realReviews", "variants", "paraphrased", "cached", "events", "leaks", "drift", "errors") if k in j})
    if rc or j.get("leaks") or j.get("drift") or j.get("errors"):
        res["ok"], res["error"] = False, "投影核对不过：" + "；".join((j.get("leaks") or []) + (j.get("drift") or []) + (j.get("errors") or []))[:200] if j else f"project.py 退出码 {rc}"
    return res


# ---------- 3 算数 ----------
def s_calc():
    res = {"analyzed": [], "rendered": []}
    pulled = (REPORT["steps"].get("拉评论") or {}).get("byAsin") or {}
    tagged = (REPORT["steps"].get("打标签") or {}).get("byAsin") or {}
    comps = [a for a in COMPS if (DATA / a / "data.json").exists()]
    changed = {a for a in comps if (pulled.get(a) or {}).get("new") or (tagged.get(a) or {}).get("tagged")}
    for a in sorted(changed):
        rc, _ = run([PY, HERE / "analyze.py", DATA / a / "data.json"])
        res["analyzed"].append(a)
        if rc == 0:
            run([PY, HERE / "render.py", DATA / a / "data.json"])
            res["rendered"].append(a)
        else:
            res["ok"], res["error"] = False, f"{a} analyze.py 退出码 {rc}"
    if (DATA / OWN / "data.json").exists():
        cmd = [PY, HERE / "analyze.py", DATA / OWN / "data.json"]
        if comps:
            cmd += ["--vs", *[DATA / a / "data.json" for a in comps]]
        rc, _ = run(cmd)
        res["analyzed"].append(OWN)
        if rc:
            res["ok"], res["error"] = False, f"{OWN} analyze.py 退出码 {rc}"
        else:
            run([PY, HERE / "render.py", DATA / OWN / "data.json"])
            res["rendered"].append(OWN)
        dash = next((p for p in (HERE / "dashboard.py", WB / "dashboard.py") if p.exists()), HERE / "dashboard.py")
        rc, _ = run([PY, dash, DATA / OWN / "data.json", *(["--vs", *[DATA / a / "data.json" for a in comps]] if comps else [])])
        res["dashboard"] = rc == 0
        if rc:
            res["ok"], res["error"] = False, f"dashboard.py 退出码 {rc}"
    else:
        res["note"] = f"自家 {OWN} 还没有 data.json"
    if "--export" in ARGS or W["export"]:
        rc, _ = run([PY, WB / "build_export.py"])
        res["export"] = rc == 0
    return res


# ---------- 4 行动卡 ----------
def s_actions():
    res = {}
    if "--no-actions" in ARGS:
        res["note"] = "--no-actions"
        return res
    FS = CFG.get("feishu") or {}
    if not (FS.get("base") and (FS.get("tables") or {}).get("actions")):
        res["note"] = "没接飞书行动表（voc.config.json feishu.tables.actions）"
        return res
    rc, out = run([PY, HERE / "actions.py", "pull"], timeout=300)
    res["pull"] = rc == 0
    if rc:
        res["ok"], res["error"] = False, "actions.py pull 失败"
        return res
    rb = [PY, HERE / "actions.py", "readback"] + (["--write"] if W["readback_write"] and not DRY else [])
    rc, out = run(rb, timeout=300)
    res["readback"] = rc == 0
    res["readbackWrite"] = bool(W["readback_write"] and not DRY)
    rc, out = run([PY, HERE / "actions.py", "check", "--draft"], timeout=300)
    res["check"] = rc == 0
    res["checkText"] = "\n".join(l for l in out.splitlines() if l.startswith("巡检") or l.startswith("- "))
    run([PY, HERE / "actions.py", "timeline"], timeout=300)
    return res


# ---------- 5 入飞书 ----------
def s_feishu():
    res = {}
    FS = CFG.get("feishu") or {}
    if "--no-feishu" in ARGS or not W["feishu"]:
        res["note"] = "关了（--no-feishu 或 weekly.feishu=false）"
        return res
    if not (FS.get("base") and (FS.get("tables") or {}).get("events")):
        res["note"] = "没接飞书事件表（voc.config.json feishu.tables.events）"
        return res
    cmd = [PY, TOOLS / "events_to_feishu.py", "--json"] + ([ONLY] if ONLY else []) + (["--dry-run"] if DRY else [])
    rc, out = run(cmd, timeout=900)
    j = last_json(out)
    res.update({k: j.get(k) for k in ("written", "skipped", "backfilled", "errors", "dry") if k in j})
    REPORT["feishu"] = int(j.get("written") or 0)
    if rc or j.get("errors"):
        res["ok"], res["error"] = False, f"写飞书失败：{(j.get('errors') or [rc])[0]}"
    return res


# ---------- 6 群草稿 ----------
def s_draft():
    sys.path.insert(0, str(HERE))
    import detail  # noqa: E402  产品详情口径和工作台一致
    acts = data_json(DATA / "actions.json")
    own = detail.build(OWN, acts, OWN) if (DATA / OWN / "data.json").exists() else {"exists": False}
    dash = data_json(DATA / OWN / "dashboard.json") or {}
    snap = (dash.get("snaps") or [{}])[-1]
    kpi = snap.get("kpi") or {}
    pulled = (REPORT["steps"].get("拉评论") or {}).get("byAsin") or {}
    n_own = int((pulled.get(OWN) or {}).get("new") or 0)
    n_comp = sum(int((pulled.get(a) or {}).get("new") or 0) for a in COMPS)
    L = [f"**VOC 周报草稿 · {STAMP:%Y-%m-%d}**"]
    pj = (data(OWN) or {}).get("projection") or {}
    if is_demo(data(OWN)):
        L.append(f"- 自家 {OWN} 目前是演示数据，没有拉；换成真实 ASIN（voc.config.json own.asin）后这一行会变成本周新评论数")
    else:
        L.append(f"- 本周新声音：自家评论 +{n_own}" + ("（真实条数；看板按投影倍数展示）" if pj else "") + (f"，竞品 +{n_comp}" if COMPS else "") + (f"；打标 {REPORT['tagged']} 条" if REPORT["tagged"] else ""))
    if kpi:
        v, ns, tp = kpi.get("voices") or {}, kpi.get("negShare") or {}, kpi.get("top") or {}
        real_n = v.get("realNow")
        src = snap.get("sources") or {}
        win_n = sum(int(x or 0) for x in src.values())
        k = float(pj.get("k") or 0)
        if not v.get("now"):                                                 # 这周没声音：报窗口累计和月度，别拿 0 说事
            fr, mo = dash.get("fresh") or {}, dash.get("monthly") or []
            last_mo = next((m for m in reversed(mo) if m.get("reviews")), None)
            L.append(f"- 最新完整周（{snap.get('week', '')}）没有新声音；近 4 周（{snap.get('window', '')}）声音 {win_n} 条"
                     + (f"（真实 {round(win_n / k)} 条）" if k else "")
                     + (f"；评论最新到 {fr['lastReview']}" if fr.get("lastReview") else "")
                     + (f"，最近有评论的月份 {last_mo['label']}：{last_mo['reviews']} 条" + (f"（真实 {last_mo['realReviews']}）" if last_mo.get("realReviews") is not None else "") if last_mo else "")
                     + "；评论少的品看月度和累计，别看周环比")
        else:
            L.append(f"- 最新一周（{snap.get('week', '')}）：声音 {v.get('now', '—')} 条（上周 {v.get('prev', '—')}），差评占比 {ns.get('now', '—')}%（上周 {ns.get('prev', '—')}%）"
                     + (f"；最大问题「{tp.get('tag')}」{tp.get('now')}%（上周 {tp.get('prev')}%）" if tp.get("tag") and tp.get("tag") != "—" else "")
                     + (f"；真实样本 {real_n} 条" + ("，不足 5 条，这周的占比先别下结论" if real_n < 5 else "") if real_n is not None else ""))
    elif own.get("exists"):
        L.append(f"- 自家 {own.get('n', 0)} 条评论，差评占比 {own.get('negShare', '—')}%" + (f"；最大问题「{own['topIssues'][0]['name']}」{own['topIssues'][0]['share']}%" if own.get("topIssues") else ""))
    rt = own.get("returns") or {}
    if rt.get("has"):
        L.append(f"- 退货近 {rt.get('window', 30)} 天：{rt.get('n', 0)} 件，换货 {rt.get('exchanges', 0)}，买家消息 {rt.get('messages', 0)}"
                 + (f"；真实原因最多「{rt['topReal'][0]}」{rt['topReal'][1]} 件" if rt.get("topReal") else ""))
    ck = (REPORT["steps"].get("行动卡") or {}).get("checkText")
    if ck:
        L.append("- 行动卡：" + ck.splitlines()[0].replace("巡检 ", "").split("：", 1)[-1])
        L += ["  " + l for l in ck.splitlines()[1:]]
    if REPORT["problems"]:
        L.append("- 本次运转有失败：" + "；".join(REPORT["problems"]))
    L.append("- 看板、报告已更新：本机工作台 http://127.0.0.1:8790（点「产品」看详情；设置 → 资产库看时间线）")
    text = "\n".join(L)
    (DATA / "weekly_draft.md").write_text(text + "\n", encoding="utf-8")
    log(text)
    return {"draft": str(DATA / "weekly_draft.md"), "lines": len(L)}


# ---------- 7 留痕 ----------
def s_keep():
    res = {}
    # 本周周报：群草稿 + 这次运转每步的数字，进 git（runs.jsonl 不进仓，这份是留给仓库历史的）
    hist = DATA / "_history"
    hist.mkdir(exist_ok=True)
    draft = (DATA / "weekly_draft.md").read_text(encoding="utf-8") if (DATA / "weekly_draft.md").exists() else ""
    lines = [f"# VOC 周报 {STAMP:%Y-%m-%d}" + ("（演练）" if DRY else ""), "", draft.strip(), "", "## 这次运转", ""]
    for name, st in REPORT["steps"].items():
        bits = {k: ("、".join(map(str, v)) if isinstance(v, list) else v) for k, v in st.items() if k not in ("ok", "seconds", "byAsin", "checkText", "draft", "log") and v not in (None, "", [], {})}
        by = st.get("byAsin") or {}
        if by:
            bits["byAsin"] = "；".join(f"{a} " + "、".join(f"{k} {v}" for k, v in x.items() if v not in (None, [], {}, False)) for a, x in by.items())
        lines.append(f"- {name}：{'完成' if st.get('ok') else '失败'}（{st.get('seconds', 0)}s）" + ("　" + "；".join(f"{k} {v}" for k, v in bits.items()) if bits else ""))
    dash = data_json(DATA / OWN / "dashboard.json") or {}
    if dash.get("latestWeek"):
        fr, cu = dash.get("fresh") or {}, dash.get("cumulative") or {}
        lines += ["", f"看板锚定 {dash.get('runDate')}，最新完整周 {dash['latestWeek']}；评论最新到 {fr.get('lastReview')}，退货最新到 {(fr.get('lastEvent') or {}).get('退货')}；"
                  f"累计评论 {cu.get('reviews')}" + (f"（真实 {cu.get('realReviews')}）" if cu.get("realReviews") is not None else "") + f"，退货 {(cu.get('events') or {}).get('退货')}。"]
    hp = hist / f"周报-{STAMP:%Y-%m-%d}.md"
    hp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    res["history"] = str(hp.relative_to(ROOT)) if hp.is_relative_to(ROOT) else str(hp)
    tl = next((p for p in (HERE / "timeline.py", WB / "timeline.py") if p.exists()), None)
    if tl:
        rc, out = run([PY, tl], timeout=120)
        res["timeline"] = rc == 0
    if "--no-commit" in ARGS or not W["commit"] or DRY:
        res["commit"] = "跳过（--no-commit / weekly.commit=false / --dry-run）"
        return res
    if not (ROOT / ".git").exists() or not DATA.is_relative_to(ROOT):
        res["commit"] = "跳过（不在 git 仓里）"
        return res
    paths = [DATA / "actions.json", DATA / "timeline.json", hist]
    for a in [OWN, *COMPS]:
        for f in ("data.json", "报告.html", "dashboard.json", "alexa_compare.json"):
            if (DATA / a / f).exists():
                paths.append(DATA / a / f)
    rel = [str(p.relative_to(ROOT)) for p in paths if p.exists()]
    rc, _ = run(["git", "-C", ROOT, "add", "--", *rel], timeout=60)
    if rc:
        res["ok"], res["error"] = False, "git add 失败"
        return res
    staged = subprocess.run(["git", "-C", str(ROOT), "-c", "core.quotepath=false", "diff", "--cached", "--name-only"], capture_output=True, text=True).stdout.splitlines()
    if not staged:
        res["commit"] = "没有改动，不提交"
        return res
    sign = os.environ.get("VOC_COMMIT_SIGN") or W["commit_sign"]
    title = f"VOC分析: 每周运转 {STAMP:%Y-%m-%d}——新评论 {REPORT['newReviews']}、打标 {REPORT['tagged']}、入飞书 {REPORT['feishu']} 行" + ("，有失败" if REPORT["problems"] else "") + f" {sign}"
    body = "自动留痕：weekly.py 第 7 步。改动 " + "、".join(staged) + "\n" + "\n".join(f"- {n}：{'完成' if st.get('ok') else '失败'}" for n, st in REPORT["steps"].items())
    rc, out = run(["git", "-C", ROOT, "commit", "-q", "-m", title, "-m", body], timeout=60)
    if rc:
        res["ok"], res["error"] = False, "git commit 失败（看日志；落款要在 sops 宪法的七个之内）"
        return res
    res["commit"] = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    res["files"] = len(staged)
    return res


def data_json(p):
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
    except json.JSONDecodeError:
        return None


def main():
    log(f"VOC 每周运转 {REPORT['at']}" + ("（--dry-run）" if DRY else "") + f"：自家 {OWN}，竞品 {len(COMPS)} 个，每个最多 {PAGES} 页")
    step("拉评论", s_pull)
    step("打标签", s_tag)
    step("投影", s_project)
    step("算数", s_calc)
    step("行动卡", s_actions)
    step("入飞书", s_feishu)
    step("群草稿", s_draft)
    step("留痕", s_keep)
    REPORT["ok"] = not REPORT["problems"]
    REPORT["seconds"] = round((dt.datetime.now() - STAMP).total_seconds(), 1)
    REPORT["log"] = str(LOG.relative_to(ROOT) if LOG.is_relative_to(ROOT) else LOG)
    bits = [f"新评论 {REPORT['newReviews']}", f"打标 {REPORT['tagged']}", f"卖家精灵 {REPORT['calls']} 次", f"入飞书 {REPORT['feishu']} 行"]
    if DRY:
        bits.insert(0, "演练")
    REPORT["note"] = "，".join(bits) + ("；失败：" + "；".join(REPORT["problems"]) if REPORT["problems"] else "")
    with (DATA / "runs.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(REPORT, ensure_ascii=False) + "\n")
    log(f"\n完成 {REPORT['seconds']}s：{REPORT['note']}\n记录 → {DATA / 'runs.jsonl'}；日志 → {REPORT['log']}；群草稿 → {DATA / 'weekly_draft.md'}（工作台设置页点「发到群」）")
    LOGF.close()
    sys.exit(0 if REPORT["ok"] else 1)


if __name__ == "__main__":
    main()
