"""评论 / 退货 / 换货 / 买家消息 → 飞书「VOC 事件明细」（一条声音一行）。重复跑不重复写。

用法：python3 <skill>/events_to_feishu.py [B0XXXXXXXX ...] [--dry-run] [--limit 200] [--json]
- 不带 ASIN = voc.config.json 的 own + competitors。演示数据（data.json 的 demo=true 或 pulled.source=演示数据）不写。
- 表的 base / table 读 voc.config.json 的 feishu.base / feishu.tables.events；没填就不写。机器人身份 = hermes.profile 对应的 HERMES_HOME。
- 事件ID：评论 R-<ASIN>-NNN（接着表里已有的序号往下编，并写回 data.json 的 id）；退货 / 换货 / 买家消息 E-<ASIN>-<import_events 的 id>。
- 去重：先按事件ID，再按「子ASIN + 原话」。表里已有、data.json 里还没 id 的评论，会把表里的事件ID 回填进 data.json。
- 评论只写已打标的（tags 或 tagger 有值）和送测的；没打标的等 tag.py 跑完下次再写。
- 写的字段：事件ID 来源 日期 父ASIN 子ASIN 款式 星级 原话 送测 中文意思 问题分类 夸还是骂 该谁改 阶段 平台原因码 写入方。
  人写的字段（人工意见、关联行动、处置结果、履约方式）不碰。阶段用 voc.config.json 的 6 段名，表里的旧名（收货 / 安装 …）读的时候按 stages.alias 认。
- 问题分类 / 阶段 / 该谁改 是选项字段，飞书不会自动建选项：写之前先把这次用到、表里还没有的选项补进字段（+field-update）。
- --json：结尾多打一行 {"written","skipped","backfilled","errors"} 给 weekly.py 读；"dupInData" = data.json 里和已入表评论重复、没回填的条数（有就该查 ss_pull 去重）。
"""
import datetime as dt
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import voccfg  # noqa: E402

ARGS = sys.argv[1:]
CFG = voccfg.load(HERE.parent)
FS = CFG.get("feishu") or {}
BASE, TABLE = FS.get("base"), (FS.get("tables") or {}).get("events")
DATA_DIR = pathlib.Path(os.environ.get("VOC_DATA_DIR") or (HERE.parent if (HERE.parent / CFG["own"]["asin"]).exists() else pathlib.Path.cwd() / "voc-reports")).expanduser()
LARK = os.environ.get("LARK_CLI") or shutil.which("lark-cli") or str(pathlib.Path.home() / ".hermes/node/bin/lark-cli")
ENV = dict(os.environ)
_hh = pathlib.Path.home() / ".hermes/profiles" / (CFG.get("hermes") or {}).get("profile", "voc")
if "HERMES_HOME" not in ENV and _hh.exists():
    ENV["HERMES_HOME"] = str(_hh)
DRY, AS_JSON = "--dry-run" in ARGS, "--json" in ARGS
LIMIT = int(ARGS[ARGS.index("--limit") + 1]) if "--limit" in ARGS else 0
NEG, POS, _ = voccfg.vocab(CFG)
STAGE = {t: s for kind in ("neg", "pos") for t, s in CFG["tags"][kind].items() if not t.startswith("_")}
TMP = DATA_DIR / "_events_rows.json"


def say(*a):
    print(*a, file=sys.stderr if AS_JSON else sys.stdout)


def lark(*a, extra=()):
    r = subprocess.run([LARK, "base", *a, "--as", "bot", "--base-token", BASE, "--table-id", TABLE, *extra],
                       capture_output=True, text=True, env=ENV, cwd=DATA_DIR)
    try:
        return json.loads(r.stdout or "{}")
    except json.JSONDecodeError:
        return {"ok": False, "error": {"message": (r.stderr or r.stdout)[-400:]}}


def norm(s):
    return re.sub(r"\s+", " ", re.sub(r"<br\s*/?>", " ", s or "")).strip()[:160].lower()


def existing():
    """表里已有的：事件ID 集合、（子ASIN, 原话）→ 事件ID、每个 ASIN 的最大评论序号。按 2000 行一页翻完整张表（表超过 2000 行后去重才不会瞎）。"""
    ids, by_text, seq = set(), {}, {}
    offset = 0
    while True:
        tmp = DATA_DIR / "_events_pull.ndjson"
        extra = ["--field-id", "事件ID", "--field-id", "子ASIN", "--field-id", "原话", "--format", "ndjson", "--output", str(tmp), "--overwrite", "--limit", "2000", "--offset", str(offset)]
        r = subprocess.run([LARK, "base", "+record-list", "--as", "bot", "--base-token", BASE, "--table-id", TABLE, *extra],
                           capture_output=True, text=True, env=ENV, cwd=DATA_DIR)
        if not tmp.exists():
            sys.exit("拉飞书事件表失败：" + (r.stderr or r.stdout)[-400:])
        rows = [json.loads(l) for l in tmp.read_text(encoding="utf-8").splitlines() if l.strip()]
        tmp.unlink()
        for mf in DATA_DIR.glob("_events_pull*.manifest.json"):
            mf.unlink()
        for row in rows:
            f = row.get("fields", row)
            eid, sub, text = f.get("事件ID") or "", f.get("子ASIN") or "", f.get("原话") or ""
            if eid:
                ids.add(eid)
                mm = re.fullmatch(r"R-([A-Z0-9]{10})-(\d+)", eid)
                if mm:
                    seq[mm[1]] = max(seq.get(mm[1], 0), int(mm[2]))
            if sub and text:
                by_text[(sub, norm(text))] = eid
        # lark-cli 一次最多 2000 行，按数字 offset 翻页翻到不满一页为止（不能等 stderr 的 next_offset，它不一定打）
        if len(rows) < 2000:
            break
        offset += len(rows)
    return ids, by_text, seq


SELECTS = {"问题分类": True, "阶段": False, "该谁改": False}      # 字段 → 是否多选；写之前把缺的选项补进表


def ensure_options(rows):
    """飞书不会自动建单选 / 多选的选项，写了没有的选项会报 not_found；先把这次要用的补进字段里。"""
    need = {f: set() for f in SELECTS}
    for row in rows:
        for f in SELECTS:
            for v in row.get(f) or []:
                need[f].add(v)
    fl = lark("+field-list", extra=["--format", "json"])
    fields = ((fl.get("data") or {}).get("fields") if isinstance(fl.get("data"), dict) else fl.get("data")) or []
    added = {}
    for f in fields:
        name = f.get("name")
        if name not in need or not need[name]:
            continue
        have = [o.get("name") for o in f.get("options") or []]
        miss = sorted(v for v in need[name] if v not in have)
        if not miss:
            continue
        body = {"name": name, "type": "select", "multiple": bool(f.get("multiple")), "options": [{"name": o} for o in have + miss]}
        res = lark("+field-update", extra=["--field-id", name, "--json", json.dumps(body, ensure_ascii=False), "--yes", "--format", "json"])
        if res.get("ok"):
            added[name] = miss
        else:
            say(f"  给「{name}」加选项失败：{(res.get('error') or {}).get('message') or res}")
    for name, miss in added.items():
        say(f"  「{name}」新加选项：{'、'.join(miss)}")
    return added


def date_of(ms_or_str):
    if isinstance(ms_or_str, (int, float)):
        return dt.datetime.fromtimestamp(ms_or_str / 1000).strftime("%Y-%m-%d 00:00")
    return f"{str(ms_or_str)[:10]} 00:00"


def review_row(asin, parent, r, rid, owners):
    tags = [t for t in r.get("tags") or [] if t in NEG or t in POS]
    neg = [t for t in tags if t in NEG]
    pos = [t for t in tags if t in POS]
    pol = "骂" if neg else ("夸" if pos else "中性")
    first = (neg or pos or [None])[0]
    row = {"事件ID": rid, "来源": ["评论"], "日期": date_of(r.get("t") or 0), "父ASIN": parent or asin, "子ASIN": asin,
           "款式": r.get("sku") or "", "星级": int(r.get("star") or 0), "原话": r.get("en") or "", "送测": bool(r.get("vine")),
           "中文意思": r.get("zh") or "", "夸还是骂": [pol], "写入方": ["VOC Agent"]}
    if tags:
        row["问题分类"] = tags
    if first and STAGE.get(first):
        row["阶段"] = [STAGE[first]]
    if neg and owners.get(neg[0]):
        row["该谁改"] = [owners[neg[0]]]
    return row


def event_row(asin, parent, e, owners):
    eid = e.get("id") or hashlib.sha1(f"{e.get('type')}|{e.get('date')}|{e.get('sku')}|{e.get('note') or ''}".encode()).hexdigest()[:12]
    real = e.get("real") if e.get("real") in NEG or e.get("real") in POS else None
    pol = "骂" if (e.get("type") in ("退货", "换货") or (real and real in NEG)) else "中性"
    row = {"事件ID": f"E-{asin}-{eid}", "来源": [e.get("type") or "退货"], "日期": date_of(e.get("date") or ""), "父ASIN": parent or asin,
           "子ASIN": asin, "款式": e.get("sku") or "", "原话": e.get("note") or "", "送测": False, "夸还是骂": [pol], "写入方": ["VOC Agent"]}
    if e.get("code"):
        row["平台原因码"] = e["code"]
    if real:
        row["问题分类"] = [real]
        if STAGE.get(real):
            row["阶段"] = [STAGE[real]]
        if owners.get(real):
            row["该谁改"] = [owners[real]]
    elif e.get("real"):
        row["中文意思"] = e["real"]                 # 买家消息的提问主题：不在词表里，记在中文意思
    return row


def main():
    if not BASE or not TABLE:
        sys.exit("voc.config.json 的 feishu.base / feishu.tables.events 没填，不写飞书")
    asins = [a.upper() for a in ARGS if re.fullmatch(r"B0[A-Z0-9]{8}", a.upper())] or [CFG["own"]["asin"], *CFG.get("competitors", [])]
    ids, by_text, seq = existing()
    say(f"表里已有 {len(ids)} 行")
    stat = {"written": 0, "skipped": 0, "backfilled": 0, "errors": [], "byAsin": {}}
    rows, touched = [], {}
    for asin in asins:
        p = DATA_DIR / asin / "data.json"
        if not p.exists():
            say(f"{asin}：没有 data.json，跳过")
            continue
        d = json.loads(p.read_text(encoding="utf-8"))
        if d.get("demo") or (d.get("pulled") or {}).get("source") == "演示数据":
            say(f"{asin}：演示数据，不写飞书")
            continue
        voccfg.canonicalize(d, CFG)
        parent = (d.get("product") or {}).get("parent") or asin
        owners = {(pr.get("tag") or pr.get("name")): pr.get("owner") for pr in d.get("problems") or [] if pr.get("owner")}
        n_new, n_skip, changed = 0, 0, False
        used = {r["id"] for r in d.get("reviews", []) if r.get("id")}   # 本文件已占用的事件ID：回填时不许撞号（撞了说明 data.json 里有重复评论，报出来不写）
        for r in d.get("reviews", []):
            k = (asin, norm(r.get("en")))
            if r.get("id") and r["id"] in ids:
                n_skip += 1
                continue
            if k in by_text:
                if not r.get("id"):
                    if by_text[k] in used:
                        stat["dupInData"] = stat.get("dupInData", 0) + 1
                        say(f"  {asin}：评论「{(r.get('en') or '')[:40]}」和 {by_text[k]} 是同一条，data.json 里重复了，没回填")
                        continue
                    r["id"], changed = by_text[k], True
                    used.add(r["id"])
                    stat["backfilled"] += 1
                n_skip += 1
                continue
            if not (r.get("tags") or r.get("tagger") or r.get("vine")):
                continue                                   # 还没打标，下次
            if not r.get("id"):
                seq[asin] = seq.get(asin, 0) + 1
                r["id"], changed = f"R-{asin}-{seq[asin]:03d}", True
            rows.append(review_row(asin, parent, r, r["id"], owners))
            ids.add(r["id"]); by_text[k] = r["id"]
            n_new += 1
        for e in d.get("events", []) or []:
            row = event_row(asin, parent, e, owners)
            if row["事件ID"] in ids:
                n_skip += 1
                continue
            rows.append(row)
            ids.add(row["事件ID"])
            n_new += 1
        stat["byAsin"][asin] = {"new": n_new, "skipped": n_skip}
        stat["skipped"] += n_skip
        if changed:
            touched[asin] = (p, d)
        say(f"{asin}：待写 {n_new}，已有 {n_skip}")
    if LIMIT:
        rows = rows[:LIMIT]
    say(f"待写入 {len(rows)} 行" + ("（--dry-run，不写）" if DRY else ""))
    if DRY:
        if rows:
            say(json.dumps(rows[0], ensure_ascii=False)[:600])
        stat["dry"] = True
        return stat
    if rows:
        stat["options"] = ensure_options(rows)
    for i in range(0, len(rows), 200):
        TMP.write_text(json.dumps({"create_records": rows[i:i + 200]}, ensure_ascii=False), encoding="utf-8")
        res = lark("+record-batch-create", extra=["--json", "@" + TMP.name])
        if res.get("ok"):
            stat["written"] += len(rows[i:i + 200])
        else:
            msg = (res.get("error") or {}).get("message") or str(res)[:300]
            stat["errors"].append(msg)
            say("写入失败：", msg)
            break
    if TMP.exists():
        TMP.unlink()
    if not stat["errors"]:
        for asin, (p, d) in touched.items():       # 写成功了才把 id 落回 data.json
            p.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    say(f"写入 {stat['written']} 行，回填 id {stat['backfilled']} 条")
    return stat


if __name__ == "__main__":
    s = main()
    if AS_JSON:
        print(json.dumps({k: v for k, v in s.items() if k != "byAsin"} | {"byAsin": s["byAsin"]}, ensure_ascii=False))
