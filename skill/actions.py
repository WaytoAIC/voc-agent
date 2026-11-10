"""行动项闭环：飞书「行动项跟踪」表 ⇄ 本地镜像，到期读回，巡检。总纲 §3「一条差评走一圈」的第 6–8 站。

用法：
  python3 <skill>/actions.py pull                 # 飞书 → voc-reports/actions.json（本地镜像，页面和看板用）
  python3 <skill>/actions.py readback [--write]   # 到期的卡：从 data.json 算「看哪个数」的实际值和 AI 判断；默认只打印，--write 才写回飞书
  python3 <skill>/actions.py check [--draft]      # 巡检四种卡住的情况；--draft 顺手起草一条群消息（不发）
  python3 <skill>/actions.py timeline             # 给每张有「实际完成日」的卡算动作—结果曲线，写进 actions.json

口径：
  - 表和字段都在飞书，这里不建字段；本地 actions.json 只是镜像，每次 pull 覆盖。
  - 读回只算「评论里提「X」的占比」这一类指标（voc.config.json actions.metric_patterns）：
    实际值 = 实际完成日（没有就用验证日期往前 default_verify_weeks 周）到验证日期之间、非送测评论里提到 X 的占比。
    评论少于 min_reviews_for_judgement 条 → 看不出来（数据不够）；≤ 目标 → 有效；≥ 起始 → 无效；中间 → 看不出来（有改善没到目标）。
    退货 / 买家消息类指标本地没数据，只提示要接后台。
  - 写回只写 AI 字段：到期实际值、AI判断。人的字段（采纳、责任人、复盘结论、状态…）永远不碰。
  - 机器人身份（HERMES_HOME = voc profile）。
"""
import datetime as dt
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import voccfg  # noqa: E402

CFG = voccfg.load(HERE)
A = CFG.get("actions") or {}
FS = CFG.get("feishu") or {}
BASE, TABLE = FS.get("base"), (FS.get("tables") or {}).get("actions")
DATA_DIR = voccfg.data_dir(HERE)
OUT = DATA_DIR / "actions.json"          # 本地：voc-reports/actions.json；公开版：voc-reports/actions.json（或 VOC_DATA_DIR）
LARK = os.environ.get("LARK_CLI") or shutil.which("lark-cli") or str(pathlib.Path.home() / ".hermes/node/bin/lark-cli")
ENV = dict(os.environ)
_hh = pathlib.Path.home() / ".hermes/profiles" / (CFG.get("hermes") or {}).get("profile", "voc")
if "HERMES_HOME" not in ENV and _hh.exists():
    ENV["HERMES_HOME"] = str(_hh)
ALIAS = {k: v for k, v in (CFG.get("asin_alias") or {}).items() if not k.startswith("_")}
TODAY = dt.date.today()


def lark(*a, **kw):
    if not BASE or not TABLE:
        sys.exit("voc.config.json 的 feishu.base / feishu.tables.actions 没填")
    r = subprocess.run([LARK, "base", *a, "--as", "bot", "--base-token", BASE, "--table-id", TABLE, *kw.get("extra", [])],
                       capture_output=True, text=True, env=ENV, cwd=HERE)
    try:
        return json.loads(r.stdout or "{}")
    except json.JSONDecodeError:
        return {"ok": False, "error": {"message": (r.stderr or r.stdout)[-400:]}}


def first(v):
    return v[0] if isinstance(v, list) and v else (v if isinstance(v, str) else None)


def day(v):
    return v[:10] if isinstance(v, str) and len(v) >= 10 else None


def num(s):
    m = re.search(r"-?\d+(?:\.\d+)?", s or "")
    return float(m.group()) if m else None


def parse_target(s):
    """目标值 → (方向, 数)。「15% 以下」→ ("max",15)；「不升高」→ ("max",起始)；「0」→ ("max",0)。"""
    if not s:
        return None
    if "不升" in s or "不高" in s:
        return ("max", None)
    v = num(s)
    if v is None:
        return None
    return ("min", v) if ("以上" in s or "不低于" in s) else ("max", v)


def metric_kind(text):
    for kind, pat in (A.get("metric_patterns") or {}).items():
        if kind.startswith("_"):
            continue
        m = re.search(pat, text or "")
        if m:
            return kind, voccfg.tag(CFG, m.group("tag"))
    return None, None


def normalize(rec):
    f = rec
    prod = f.get("产品") or ""
    m = re.search(r"B0[A-Z0-9]{8}", prod)
    asin = m.group() if m else None
    kind, tag = metric_kind(f.get("看哪个数"))
    return {
        "id": f.get("行动编号"), "record_id": f.get("record_id"), "problem": f.get("问题"), "tag": first(f.get("问题类别")) or tag,
        "status": first(f.get("状态")), "adopt": first(f.get("采纳")), "priority": first(f.get("优先级")), "owner": first(f.get("归属部门")),
        "assignee": (f.get("责任人") or [{}])[0].get("name") if isinstance(f.get("责任人"), list) and f.get("责任人") else None,
        "product": prod, "asin": asin, "dataAsin": ALIAS.get(asin, asin), "sku": f.get("涉及款式"), "source": f.get("来源") or [],
        "plan": f.get("AI建议方案"), "altPlan": f.get("改成的方案"), "evidence": f.get("依据原话"), "evidenceN": f.get("依据条数"),
        "impact": f.get("估算影响"), "metric": f.get("看哪个数"), "metricKind": kind, "metricTag": tag,
        "start": f.get("起始值"), "target": f.get("目标值"), "verifyDate": day(f.get("验证日期")), "actual": f.get("到期实际值"),
        "judgement": first(f.get("AI判断")), "planDate": day(f.get("计划完成日")), "doneDate": day(f.get("实际完成日")),
        "review": f.get("复盘结论"), "next": f.get("下一步"), "note": f.get("备注"), "writer": first(f.get("写入方")),
    }


def load_local():
    return json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {"asOf": None, "actions": []}


def pull():
    tmp = DATA_DIR / "_actions_pull.ndjson"
    r = subprocess.run([LARK, "base", "+record-list", "--as", "bot", "--base-token", BASE, "--table-id", TABLE,
                        "--format", "ndjson", "--output", str(tmp), "--overwrite"], capture_output=True, text=True, env=ENV, cwd=HERE)
    if not tmp.exists():
        sys.exit("拉飞书失败：" + (r.stderr or r.stdout)[-400:])
    rows = [json.loads(l) for l in tmp.read_text(encoding="utf-8").splitlines() if l.strip()]
    tmp.unlink()
    for m in DATA_DIR.glob("_actions_pull*.manifest.json"):      # lark-cli 顺手写的清单，不留
        m.unlink()
    acts = sorted((normalize(x) for x in rows), key=lambda a: a["id"] or "")
    old = load_local()
    keep = {a["id"]: a.get("series") for a in old.get("actions", []) if a.get("series")}
    for a in acts:
        if a["id"] in keep:
            a["series"] = keep[a["id"]]
    OUT.write_text(json.dumps({"asOf": TODAY.isoformat(), "table": TABLE, "actions": acts}, ensure_ascii=False, indent=1), encoding="utf-8")
    by = {}
    for a in acts:
        by[a["status"]] = by.get(a["status"], 0) + 1
    print(f"拉到 {len(acts)} 张卡 → {OUT}；" + "，".join(f"{k} {v}" for k, v in by.items()))
    return acts


def reviews_of(asin):
    p = DATA_DIR / (asin or "") / "data.json"
    if not asin or not p.exists():
        return None, p
    d = json.loads(p.read_text(encoding="utf-8"))
    voccfg.canonicalize(d, CFG)
    return [r for r in d["reviews"] if not r.get("vine")], p


def share_between(U, tag, lo, hi):
    rows = [r for r in U if lo <= dt.date.fromtimestamp(r["t"] / 1000) <= hi]
    hit = sum(1 for r in rows if tag in r.get("tags", []))
    return (round(hit / len(rows) * 100, 1) if rows else None), len(rows), hit


def readback(write=False):
    acts = load_local().get("actions") or pull()
    weeks = int(A.get("default_verify_weeks", 6))
    minn = int(A.get("min_reviews_for_judgement", 5))
    updates, lines = {}, []
    for a in acts:
        if not a["verifyDate"] or a["actual"] or a["status"] == "已复盘":
            continue
        vd = dt.date.fromisoformat(a["verifyDate"])
        if vd > TODAY:
            continue
        if a["metricKind"] != "review_share":
            lines.append(f"{a['id']} {a['problem']}：「{a['metric']}」不是评论占比，本地没有退货 / 买家消息数据，要接后台后再算")
            continue
        U, p = reviews_of(a["dataAsin"])
        if U is None:
            lines.append(f"{a['id']}：没有 {p}，先分析 {a['dataAsin']}")
            continue
        lo = dt.date.fromisoformat(a["doneDate"]) if a["doneDate"] else vd - dt.timedelta(weeks=weeks)
        share, n, hit = share_between(U, a["metricTag"], lo, vd)
        start, tgt = num(a["start"]), parse_target(a["target"])
        if n < minn or share is None:
            j, why = "看不出来", f"{lo}~{vd} 只有 {n} 条评论，不够下结论"
        elif tgt and tgt[0] == "max" and share <= (tgt[1] if tgt[1] is not None else start or 0):
            j, why = "有效", f"到目标了（目标 {a['target']}）"
        elif start is not None and share >= start:
            j, why = "无效", f"没降（起始 {a['start']}）"
        else:
            j, why = "看不出来", f"有改善但没到目标（起始 {a['start']}，目标 {a['target']}）"
        actual = f"{share}%（{lo}~{vd} 共 {n} 条评论，{hit} 条提到）"
        lines.append(f"{a['id']} {a['problem']}：{actual} → {j}，{why}")
        updates[a["record_id"]] = {"到期实际值": actual, "AI判断": [j]}
        a["actual"], a["judgement"], a["readbackAt"] = actual, j, TODAY.isoformat()
    print("\n".join(lines) if lines else "没有到期待读回的卡")
    if updates and write:
        res = lark("+record-batch-update", extra=["--json", json.dumps({"update_records": updates}, ensure_ascii=False)])
        print("写回飞书：" + ("ok" if res.get("ok") else json.dumps(res, ensure_ascii=False)[:300]))
        if res.get("ok"):
            OUT.write_text(json.dumps({"asOf": TODAY.isoformat(), "table": TABLE, "actions": acts}, ensure_ascii=False, indent=1), encoding="utf-8")
    elif updates:
        print(f"（{len(updates)} 张卡可写回，加 --write 才写；只写 到期实际值、AI判断 两个 AI 字段）")


def check(draft=False):
    acts = load_local().get("actions") or pull()
    rules = A.get("stuck_rules") or {}
    stuck = {k: [] for k in rules}
    nexts = " ".join((a.get("next") or "") + (a.get("review") or "") for a in acts)
    for a in acts:
        if a["adopt"] in ("采纳", "改方案") and not a["verifyDate"] and a["status"] != "已复盘":
            stuck["adopted_no_verify_date"].append(a)
        if a["verifyDate"] and dt.date.fromisoformat(a["verifyDate"]) < TODAY and a["status"] != "已复盘" and not a["review"]:
            stuck["overdue_no_review"].append(a)
        if a["judgement"] == "看不出来" and a["status"] != "已复盘" and a["verifyDate"] and (TODAY - dt.date.fromisoformat(a["verifyDate"])).days > 14:
            stuck["unclear_too_long"].append(a)
        if a["judgement"] == "无效" and not (a.get("next") or "").strip():
            stuck["invalid_no_next"].append(a)
    total = sum(len(v) for v in stuck.values())
    out = [f"巡检 {TODAY}：{len(acts)} 张卡，卡住 {total} 处"]
    for k, items in stuck.items():
        if items:
            out.append(f"- {rules[k]}：" + "、".join(f"{a['id']} {a['problem']}" for a in items))
    print("\n".join(out))
    if draft:
        msg = "**行动项巡检**\n" + "\n".join(out[1:] or ["- 本周没有卡住的行动"]) + "\n请负责人在飞书「行动项跟踪」里处理。"
        (HERE / "actions_check.md").write_text(msg, encoding="utf-8")
        print(f"群消息草稿 → {HERE / 'actions_check.md'}（不会自动发）")
    return stuck


def timeline():
    data = load_local()
    acts = data.get("actions") or pull()
    n = 0
    for a in acts:
        a.pop("series", None)
        if a["metricKind"] != "review_share" or not (a["doneDate"] or a["verifyDate"]):
            continue
        U, _ = reviews_of(a["dataAsin"])
        if U is None:
            continue
        anchor = dt.date.fromisoformat(a["doneDate"] or a["verifyDate"])
        months, pts = [], []
        for k in range(-6, 3):
            y, m = anchor.year, anchor.month + k
            y, m = y + (m - 1) // 12, (m - 1) % 12 + 1
            lo = dt.date(y, m, 1)
            hi = (dt.date(y + (m == 12), m % 12 + 1, 1) - dt.timedelta(days=1))
            share, cnt, hit = share_between(U, a["metricTag"], lo, hi)
            months.append(f"{y}-{m:02d}")
            pts.append({"month": f"{y}-{m:02d}", "share": share, "n": cnt, "hit": hit})
        a["series"] = {"label": f"评论里提「{a['metricTag']}」的占比（{a['dataAsin']}，按月）", "points": pts,
                       "marks": [x for x in ([{"date": a["doneDate"], "t": "上线"}] if a["doneDate"] else []) + ([{"date": a["verifyDate"], "t": "验证"}] if a["verifyDate"] else [])]}
        n += 1
    OUT.write_text(json.dumps({"asOf": data.get("asOf") or TODAY.isoformat(), "table": TABLE, "actions": acts}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{n} 张卡算了动作—结果曲线 → {OUT}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "pull":
        pull()
    elif cmd == "readback":
        readback(write="--write" in sys.argv)
    elif cmd == "check":
        check(draft="--draft" in sys.argv)
    elif cmd == "timeline":
        timeline()
    else:
        sys.exit(__doc__)
