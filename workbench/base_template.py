"""飞书多维表格模板：把「VOC工作台」三张表的字段结构做成可一键建库的 .base 文件（配一份人读的 schema.json）。

用法：python3 workbench/base_template.py export [--out agent/feishu]    # 从 voc.config.json feishu.base 导出结构（lark-cli，只导结构不导记录），再生成模板
      python3 workbench/base_template.py build <快照.base> [--out …]         # 用已有的 .base 快照生成模板（不联网）
      python3 workbench/base_template.py check [--dir agent/feishu]        # 校验：模板能解码、三张表都在、选项 = voc.config.json 词表、不含任何真实 ID（CI 跑）
      python3 workbench/base_template.py print [快照.base]                    # 打印一份快照 / 模板的表和字段
一键建库（拿到模板以后）：
      lark-cli drive +import --file VOC工作台.base --type bitable --name "VOC工作台"
  建好把新库的 base token 和三张表的 table id 填进 voc.config.json 的 feishu 段（table-list 能看 id），脚本写入时会自动把缺的选项补进字段。
模板里有什么、没什么：
  - 三张表（voc.config.json feishu.table_names：VOC 事件明细 / 行动项跟踪 / 站外 VOC · Reddit）的全部字段、类型、描述、视图列顺序；
  - 选项字段按 voc.config.json 重写：阶段 = stages.order；问题分类 = 全部一级标签；该谁改 / 归属部门 = owners.list；状态 / AI判断 = actions.status / judgement；
    行动卡的问题类别 = 负面一级标签；Reddit 的抱怨 / 好评 = 负 / 正一级标签，人群 / 替代方案 = 站外配置的 persona / alt；词表外的旧选项不带；
  - 不带任何记录，不带原库的 base token、租户、所有者、表 ID（表 ID 换成 tbl_events / tbl_actions / tbl_reddit，导入时飞书会重新分配）。
.base 的格式：{"gzipSnapshot": base64(gzip(json)), "gzipExtraInfo", "gzipAutomation", "sign"}，snapshot 是按表递增的 3 个 schema 块；sign 是导出端的签名，导入不校验（实测）。
"""
import base64
import datetime as dt
import gzip
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(next((p for p in (ROOT / "现场分析", ROOT / "skill") if (p / "voccfg.py").exists()), HERE)))
import voccfg  # noqa: E402

ARGS = sys.argv[1:]
BASE_NAME = "VOC工作台"
ROLE_IDS = {"events": "tbl_events", "actions": "tbl_actions", "reddit": "tbl_reddit"}
FILE = "VOC工作台.base"
SCHEMA = "schema.json"
STRIP = {"description": "AI 写"}


def opt(x):
    return ARGS[ARGS.index(x) + 1] if x in ARGS else None


def offsite_cfg(cfg):
    """站外 persona / alt 词表：本地 skill/offsite/config.example.json，公开仓 skill/offsite/config.example.json。"""
    root = pathlib.Path(cfg.get("_path", ROOT / "voc.config.json")).resolve().parent
    for p in (root / "skill/offsite/config.example.json", root / "skill/offsite/config.example.json", ROOT / "skill/offsite/config.example.json", ROOT / "skill/offsite/config.example.json"):
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    return {}


def vocab_options(cfg):
    """每张表每个选项字段应有的选项（按 voc.config.json）。没列出的选项字段保留快照里的。"""
    neg, pos = [t for t in cfg["tags"]["neg"] if not t.startswith("_")], [t for t in cfg["tags"]["pos"] if not t.startswith("_")]
    owners = list(cfg["owners"]["list"])
    acts = cfg.get("actions") or {}
    off = offsite_cfg(cfg)
    return {
        "events": {"阶段": list(cfg["stages"]["order"]), "问题分类": neg + pos, "该谁改": owners},
        "actions": {"问题类别": neg, "归属部门": owners, "状态": list(acts.get("status") or []), "AI判断": list(acts.get("judgement") or [])},
        "reddit": {"抱怨": neg, "好评": pos, "人群": list(off.get("persona") or []), "替代方案": list(off.get("alt") or [])},
    }


def decode(path):
    j = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    return j, json.loads(gzip.decompress(base64.b64decode(j["gzipSnapshot"])))


def encode(j, snap):
    gz = base64.b64encode(gzip.compress(json.dumps(snap, ensure_ascii=False, separators=(",", ":")).encode())).decode()
    return json.dumps({"gzipSnapshot": gz, "gzipExtraInfo": j.get("gzipExtraInfo", ""), "gzipAutomation": j.get("gzipAutomation", ""), "sign": ""}, separators=(",", ":"))


def opt_id(table, field, name):
    return "opt" + hashlib.sha1(f"{table}|{field}|{name}".encode()).hexdigest()[:7]


def field_rows(snap):
    """快照 → {table_id: {"name", "fields": [...]}}（按视图列顺序）。"""
    out = {}
    for item in snap:
        sch = item["schema"]
        t = sch["data"]["table"]
        tid = t["meta"]["id"]
        view = t["viewMap"][t["views"][0]] if t.get("views") else {}
        order = (view.get("property") or {}).get("fields") or list(t["fieldMap"])
        rows = []
        for fid in order:
            f = t["fieldMap"].get(fid)
            if not f:
                continue
            desc = "".join(c.get("text", "") for c in (f.get("description") or {}).get("content") or [])
            row = {"name": f["name"], "type": (f.get("fieldUIType") or str(f.get("type"))), "primary": bool(f.get("isPrimary")) or fid == t.get("primaryKey")}
            if f.get("fieldUIType") in ("SingleSelect", "MultiSelect"):
                row["options"] = [o["name"] for o in (f.get("property") or {}).get("options") or []]
            if desc:
                row["description"] = desc
            rows.append(row)
        out[tid] = {"name": sch["tableMap"][tid]["name"], "fields": rows}
    return out


def build(snapshot_path, cfg, out_dir):
    j, snap = decode(snapshot_path)
    fs = cfg.get("feishu") or {}
    live = {v: k for k, v in (fs.get("tables") or {}).items() if v}           # 真实 table id → 角色
    names = fs.get("table_names") or {}
    want = vocab_options(cfg)
    # 表 ID → 角色：先按 voc.config.json 里的 id，对不上再按表名
    roles = {}
    for item in snap:
        for tid, tm in item["schema"]["tableMap"].items():
            role = live.get(tid) or next((r for r, n in names.items() if n == tm["name"]), None) or next((r for r, n in {"events": "VOC 事件明细", "actions": "行动手册", "reddit": "站外 VOC · Reddit"}.items() if n == tm["name"]), None)
            if role:
                roles[tid] = role
    missing = [r for r in ROLE_IDS if r not in roles.values()]
    if missing:
        sys.exit(f"快照里找不到这些表：{missing}（voc.config.json feishu.tables 的 id 或 table_names 对不上）")
    newid = {tid: ROLE_IDS[r] for tid, r in roles.items()}
    added, dropped = {}, {}

    def remap_keys(d):
        return {newid.get(k, k): v for k, v in d.items()} if isinstance(d, dict) else d

    for item in snap:
        sch = item["schema"]
        base = sch["base"]
        base.update({"id": 0, "token": "", "tenantID": 0, "name": BASE_NAME, "rev": 0, "baseRecordsNum": 0})
        base["blocks"] = [newid.get(x, x) for x in base.get("blocks") or []]
        base["blockInfos"] = {newid.get(k, k): {**v, "id": newid.get(k, k), "name": names.get(roles.get(k), v.get("name"))} for k, v in (base.get("blockInfos") or {}).items()}
        base["tables"] = [newid.get(x, x) for x in base.get("tables") or []]
        base["tableInfos"] = remap_keys(base.get("tableInfos") or {})
        lim = base.get("limit") or {}
        for k in ("tableRowsLimitMap", "tableRowsAddOnEnableMap"):
            if k in lim:
                lim[k] = remap_keys(lim[k])
        if "rowsAddOnInfo" in lim and "tableUpgradeRowsMap" in lim["rowsAddOnInfo"]:
            lim["rowsAddOnInfo"]["tableUpgradeRowsMap"] = remap_keys(lim["rowsAddOnInfo"]["tableUpgradeRowsMap"])
        sch["owner"] = "0"
        sch["tableMap"] = {newid.get(k, k): {**v, "id": newid.get(k, k), "name": names.get(roles.get(k), v.get("name"))} for k, v in sch["tableMap"].items()}
        t = sch["data"]["table"]
        old = t["meta"]["id"]
        role = roles.get(old)
        t["meta"].update({"id": newid.get(old, old), "rev": 0, "recordsNum": 0, "archiveRecordsNum": 0})
        for v in t.get("viewMap", {}).values():
            v["owner"] = "0"
            v["privateViewOwner"] = None
        for fid, f in t["fieldMap"].items():
            for c in (f.get("description") or {}).get("content") or []:          # 描述里提到的旧表名也换掉
                for r, n in names.items():
                    for old_name in ("行动手册",):
                        if r == "actions" and old_name in (c.get("text") or ""):
                            c["text"] = c["text"].replace(old_name, n)
            wanted = (want.get(role) or {}).get(f["name"])
            if wanted is None or f.get("fieldUIType") not in ("SingleSelect", "MultiSelect"):
                continue
            have = {o["name"]: o for o in (f.get("property") or {}).get("options") or []}
            opts = []
            for i, name in enumerate(wanted):
                o = have.get(name) or {"id": opt_id(role, f["name"], name), "name": name, "color": i % 11}
                opts.append({"id": o["id"], "name": name, "color": o.get("color", i % 11)})
            f.setdefault("property", {})["options"] = opts
            added[f"{role}.{f['name']}"] = [n for n in wanted if n not in have]
            dropped[f"{role}.{f['name']}"] = [n for n in have if n not in wanted]
    out_dir = pathlib.Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / FILE).write_text(encode(j, snap), encoding="utf-8")
    rows = field_rows(snap)
    schema = {"_说明": "VOC工作台 三张表的字段结构（由 base_template.py 从 .base 模板生成，人读；建库请直接导入同目录的 VOC工作台.base）。选项字段的选项来自 voc.config.json，改口径后重新生成。",
              "base": BASE_NAME, "generated": dt.date.today().isoformat(), "import": f"lark-cli drive +import --file {FILE} --type bitable --name {BASE_NAME}",
              "tables": [{"role": roles_of(tid), "table": v["name"], "fields": v["fields"]} for tid, v in rows.items()]}
    (out_dir / SCHEMA).write_text(json.dumps(schema, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"模板 → {out_dir / FILE}（{(out_dir / FILE).stat().st_size} 字节），结构 → {out_dir / SCHEMA}")
    for tb in schema["tables"]:
        print(f"  {tb['table']}（{tb['role']}）：{len(tb['fields'])} 个字段")
    for k, v in added.items():
        if v:
            print(f"  + {k} 补选项 {len(v)}：{'、'.join(v)}")
    for k, v in dropped.items():
        if v:
            print(f"  - {k} 去掉词表外选项 {len(v)}：{'、'.join(v)}")
    return out_dir / FILE


def roles_of(tid):
    return next((r for r, i in ROLE_IDS.items() if i == tid), tid)


def export_live(cfg):
    """lark-cli 导出 voc.config.json feishu.base 的结构（--only-schema，不导记录）到临时目录，返回 .base 路径。"""
    token = (cfg.get("feishu") or {}).get("base")
    if not token:
        sys.exit("voc.config.json feishu.base 没填，没法从飞书导出；用 build <快照.base> 或先手动导出")
    lark = os.environ.get("LARK_CLI") or shutil.which("lark-cli") or str(pathlib.Path.home() / ".hermes/node/bin/lark-cli")
    env = dict(os.environ)
    hh = pathlib.Path.home() / ".hermes/profiles" / ((cfg.get("hermes") or {}).get("profile") or "voc")
    if "HERMES_HOME" not in env and hh.exists():
        env["HERMES_HOME"] = str(hh)
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="voc-base-"))
    cmd = [lark, "drive", "+export", "--as", "bot", "--token", token, "--doc-type", "bitable", "--file-extension", "base", "--only-schema", "--output-dir", str(tmp), "--overwrite", "--format", "json"]
    r = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=300)
    if r.returncode:
        sys.exit(f"lark-cli 导出失败：{(r.stderr or r.stdout)[-400:]}")
    files = list(tmp.glob("*.base"))
    if not files:
        sys.exit(f"导出没有产生 .base 文件：{r.stdout[-400:]}")
    print(f"已从飞书导出结构快照（只结构，无记录）→ {files[0]}")
    return files[0]


def check(cfg, d):
    d = pathlib.Path(d)
    errs = []
    fp, sp = d / FILE, d / SCHEMA
    if not fp.exists() or not sp.exists():
        return [f"模板文件不全：需要 {fp} 和 {sp}"]
    j, snap = decode(fp)
    schema = json.loads(sp.read_text(encoding="utf-8"))
    rows = field_rows(snap)
    names = (cfg.get("feishu") or {}).get("table_names") or {}
    for role, tid in ROLE_IDS.items():
        if tid not in rows:
            errs.append(f".base 里没有 {tid}（{role}）")
        elif names.get(role) and rows[tid]["name"] != names[role]:
            errs.append(f".base 里 {role} 表名是「{rows[tid]['name']}」，voc.config.json table_names 是「{names[role]}」")
    by_role = {t["role"]: t for t in schema.get("tables", [])}
    for role, tid in ROLE_IDS.items():
        if role in by_role and tid in rows and by_role[role]["fields"] != rows[tid]["fields"]:
            errs.append(f"schema.json 的 {role} 字段和 .base 不一致（重新生成）")
    want = vocab_options(cfg)
    for role, fields in want.items():
        got = {f["name"]: f for f in (by_role.get(role) or {}).get("fields", [])}
        for fname, opts in fields.items():
            if not opts:
                continue
            if fname not in got:
                errs.append(f"{role} 缺字段「{fname}」")
            elif got[fname].get("options") != opts:
                errs.append(f"{role}.{fname} 的选项和 voc.config.json 不一致：模板 {got[fname].get('options')} ≠ 词表 {opts}")
    text = json.dumps(snap, ensure_ascii=False)
    for item in snap:
        b = item["schema"]["base"]
        if b.get("token") or b.get("tenantID") or item["schema"].get("owner") not in (None, "0", ""):
            errs.append("模板里还带着原库的 token / 租户 / 所有者")
    import re
    bad = sorted(set(re.findall(r"tbl[A-Za-z0-9]{12}", text)))
    if bad:
        errs.append(f"模板里还有真实表 ID：{bad}")
    if j.get("sign"):
        errs.append("模板带着导出端签名 sign（应为空）")
    return errs


def main():
    cfg = voccfg.load(ROOT)
    cmd = ARGS[0] if ARGS and not ARGS[0].startswith("-") else "check"
    default_dir = next((p for p in (ROOT / "agent/feishu", ROOT / "agent/feishu") if p.exists()), ROOT / "agent/feishu")
    if cmd == "export":
        build(export_live(cfg), cfg, opt("--out") or default_dir)
    elif cmd == "build":
        build(ARGS[1], cfg, opt("--out") or default_dir)
    elif cmd == "print":
        src = ARGS[1] if len(ARGS) > 1 and not ARGS[1].startswith("-") else default_dir / FILE
        _, snap = decode(src)
        for tid, v in field_rows(snap).items():
            print(f"## {v['name']}（{tid}）{len(v['fields'])} 个字段")
            for f in v["fields"]:
                print(f"  {f['name']} | {f['type']}" + (f" | {len(f['options'])} 选项：{'、'.join(f['options'])}" if f.get("options") else "") + (f" | {f['description']}" if f.get("description") else ""))
    elif cmd == "check":
        errs = check(cfg, opt("--dir") or default_dir)
        if errs:
            print("模板校验不过：\n  " + "\n  ".join(errs))
            sys.exit(1)
        print(f"模板校验通过：{default_dir / FILE} 三张表、选项与 voc.config.json 一致、不含真实 ID")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
