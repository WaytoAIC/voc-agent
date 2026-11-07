"""VOC 打标脚本：把评论分批交给模型，写中文意思、打标签（只能用 voc.config.json 的词），严格 JSON、逐条校验、不达线自动补跑、默认只补新评论。

用法：
  python3 <skill>/tag.py <ASIN>/data.json               # 增量：只处理没打过标的非送测评论
  python3 <skill>/tag.py <ASIN>/data.json --all         # 全部重打（覆盖已有 zh / tags）
  python3 <skill>/tag.py <ASIN>/data.json --dry-run     # 只算要处理多少条、调用几次，不调模型、不写文件
  python3 <skill>/tag.py <ASIN>/data.json --events      # 读退货 / 换货 / 买家消息的备注（import_events.py 导入的 events），每条写一个一级标签到 real
  python3 <skill>/tag.py eval [--golden 路径] [--n 50]   # 用金标评测集重新打一遍，和金标比一致率（不碰任何 data.json）
  python3 <skill>/tag.py golden-build [--n 50] [--force] # 从已打标的竞品里抽样建金标集（只建一次；之后人工改金标文件）
  通用选项：--batch 20（每次调用几条）  --workers 4（并行）  --max N（最多处理几条）  --model 名字

模型通道（环境变量，按顺序找）：
  VOC_LLM_API     anthropic | openai（默认按 VOC_LLM_BASE 猜：含 anthropic 就是 anthropic，否则 openai）
  VOC_LLM_BASE    接口根地址，例如 https://api.openai.com/v1 或 https://open.bigmodel.cn/api/anthropic
  VOC_LLM_KEY     密钥（别写进仓库；本地从 ~/.config/ai-hub/secrets.env 之类的地方 source 进来）
  VOC_LLM_MODEL   模型名
  没设 VOC_LLM_KEY 时自动走本机 Hermes 网关（openai 兼容 http://127.0.0.1:8642/p/<profile>/v1，key 读 ~/.hermes/profiles/<profile>/.env），
  profile 名取 voc.config.json 的 hermes.profile。

口径：
  - 只处理非送测（vine=false）评论；一条评论 0–4 个标签，只能是 voc.config.json tags.neg / tags.pos 的一级词；
    模型写了别名会自动换成一级词，词表外的说法不会写进 tags，只在结尾汇总成「建议加进词表」。
  - 泛泛的夸 / 骂（「Awesome」「Not what I thought」）打「总体满意」/「总体不满」，保证覆盖率能算、能达线。
  - 每条写回 reviews[i].zh / tags，并记 reviews[i].tagger = "tag.py/<模型>@<日期>"；已有人工标签、没有 tagger 的评论默认不动。
  - 覆盖率口径和 analyze.py 一样：非送测评论里至少有 1 个标签的占比；低于 acceptance.tag_coverage_pct 时对空标签的评论自动补跑一轮。
  - 所有条数仍由 analyze.py 算；这里只写原料。跑完记得：python3 <skill>/analyze.py <ASIN>/data.json
"""
import datetime as dt
import json
import os
import pathlib
import random
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import voccfg  # noqa: E402

ARGS = sys.argv[1:]


def opt(name, default=None):
    return ARGS[ARGS.index(name) + 1] if name in ARGS else default


CFG = voccfg.load(HERE)
BATCH = int(opt("--batch", 20))
WORKERS = int(opt("--workers", 4))
MAXN = int(opt("--max", 0))
TODAY = dt.date.today().isoformat()
LINE = CFG.get("acceptance", {}).get("tag_coverage_pct", 95)
GENERIC_POS, GENERIC_NEG = "总体满意", "总体不满"
BAD = HERE / "_eval" / "bad"            # 没通过校验的原始回复（不进 git）


# ---------- 模型通道 ----------
def channel():
    api, base, key, model = os.environ.get("VOC_LLM_API"), os.environ.get("VOC_LLM_BASE"), os.environ.get("VOC_LLM_KEY"), opt("--model") or os.environ.get("VOC_LLM_MODEL")
    if not key:  # 走本机 Hermes 网关
        profile = os.environ.get("VOC_HERMES_PROFILE") or (CFG.get("hermes") or {}).get("profile", "voc")
        env = pathlib.Path.home() / ".hermes" / "profiles" / profile / ".env"
        for line in (env.read_text(encoding="utf-8").splitlines() if env.exists() else []):
            if line.startswith("API_SERVER_KEY="):
                key = line.split("=", 1)[1].strip()
        if not key:
            sys.exit("没有模型通道：设 VOC_LLM_BASE / VOC_LLM_KEY / VOC_LLM_MODEL，或把本机 Hermes 网关开起来（~/.hermes/profiles/<profile>/.env 里要有 API_SERVER_KEY）")
        api, base, model = "openai", f"http://127.0.0.1:8642/p/{profile}/v1", model or profile
    if not api:
        api = "anthropic" if "anthropic" in (base or "") else "openai"
    if not base:
        base = "https://api.anthropic.com" if api == "anthropic" else "https://api.openai.com/v1"
    if not model:
        sys.exit("没设模型名：--model 或 VOC_LLM_MODEL")
    return {"api": api, "base": base.rstrip("/"), "key": key, "model": model}


CH = None


def ask(system, user, max_tokens=6000):
    """调一次模型，返回 (文本, 用量 dict)。网络 / 5xx 最多重试 3 次。"""
    for attempt in range(3):
        try:
            if CH["api"] == "anthropic":
                body = {"model": CH["model"], "max_tokens": max_tokens, "temperature": 0, "system": system, "messages": [{"role": "user", "content": user}]}
                req = urllib.request.Request(CH["base"] + "/v1/messages", data=json.dumps(body).encode(), method="POST",
                                             headers={"x-api-key": CH["key"], "anthropic-version": "2023-06-01", "content-type": "application/json"})
                r = json.loads(urllib.request.urlopen(req, timeout=300).read())
                text = "".join(c.get("text", "") for c in r.get("content", []))
                u = r.get("usage", {})
                return text, {"in": u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0) + u.get("cache_creation_input_tokens", 0), "out": u.get("output_tokens", 0)}
            body = {"model": CH["model"], "temperature": 0, "max_tokens": max_tokens,
                    "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
            req = urllib.request.Request(CH["base"] + "/chat/completions", data=json.dumps(body).encode(), method="POST",
                                         headers={"Authorization": "Bearer " + CH["key"], "Content-Type": "application/json"})
            r = json.loads(urllib.request.urlopen(req, timeout=600).read())
            text = r["choices"][0]["message"]["content"] or ""
            u = r.get("usage", {})
            return text, {"in": u.get("prompt_tokens", 0), "out": u.get("completion_tokens", 0)}
        except urllib.error.HTTPError as e:
            msg = e.read()[:300].decode("utf-8", "ignore")
            if e.code < 500 and e.code != 429:
                raise RuntimeError(f"模型接口返回 {e.code}：{msg}")
            err = f"{e.code} {msg}"
        except (urllib.error.URLError, TimeoutError, OSError, KeyError, json.JSONDecodeError) as e:
            err = repr(e)
        sys.stderr.write(f"  调用失败（第 {attempt + 1} 次）：{err}\n")
        time.sleep(5 * (attempt + 1))
    raise RuntimeError("模型连续 3 次没回")


# ---------- 提示词 ----------
def vocab_text():
    alias = {}
    for k, v in CFG["tags"]["alias"].items():
        if not k.startswith("_"):
            alias.setdefault(v, []).append(k)

    def block(tags):
        out = []
        for t, stage in tags.items():
            if t.startswith("_"):
                continue
            a = alias.get(t)
            out.append(f"- {t} — 属于「{stage}」" + (f"；也叫：{' / '.join(a[:4])}" if a else ""))
        return "\n".join(out)
    return block(CFG["tags"]["neg"]), block(CFG["tags"]["pos"])


def system_prompt(product):
    neg, pos = vocab_text()
    name = " ".join(x for x in (product.get("brand"), product.get("name") or product.get("title")) if x)
    return f"""你是亚马逊评论打标员。产品：{name or '（见评论）'}。品类背景：{CFG.get('product', '')}

对每条评论做两件事：
1. zh：用一句中文写清买家的意思（20–60 字，保留具体细节：哪里出问题、怎么用、为什么买）。
2. tags：从下面的词表里挑 0–4 个标签，只能原样用词表里的名字（破折号前面那几个字；不要带阶段、不要带「也叫」）。

问题标签（买家在抱怨）：
{neg}

好评标签（买家在夸、或买的原因）：
{pos}

规则：
- 标题也要读。4–5 星里提到的问题照样打问题标签；1–2 星里顺带夸的也照样打好评标签。
- 买的原因（为了狗、为了老人、比定制便宜…）打成好评标签。
- 只打评论里明确说到的事，不要推测；一条评论里同一件事只打一个标签。
- 泛泛地夸、没说具体哪里好（Awesome / Works great / Love them）：打「{GENERIC_POS}」；泛泛地骂、没说具体哪里差：打「{GENERIC_NEG}」。说了具体内容就不要打这两个。
- 评论里有词表没覆盖、而且对卖家有用的具体说法，写进 other（一个 3–8 字的短语，中文），tags 里不要放词表外的词。没有就省略 other。
- 标题写着「买家消息」的是买家发来的提问，不是评论：只有明确在抱怨时才打问题标签；是提问就 tags 留空、把问的事写进 other（例如「能不能机洗」「要买几片」）。

只输出 JSON，不要任何解释，格式：
{{"items":[{{"i":0,"zh":"…","tags":["标签1","标签2"],"other":"可选"}}, …]}}
items 必须包含输入里的每一个 i。"""


def user_prompt(rows):
    items = [{"i": i, **({"star": r["star"]} if r.get("star") is not None else {}), **({"title": r["title"]} if r.get("title") else {}), "en": (r.get("en") or "")[:1500]} for i, r in rows]
    return "评论（JSON）：\n" + json.dumps(items, ensure_ascii=False)


# ---------- 解析与校验 ----------
def parse_json(text):
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    a, b = t.find("{"), t.rfind("}")
    if a < 0 or b < 0:
        raise ValueError("回复里没有 JSON")
    return json.loads(t[a:b + 1])


def clean_tag(t):
    """模型偶尔把阶段或说明一起抄进来：「边角翘、粘不住［日常使用］」「好看 — 属于「日常使用」」→ 只留标签名。"""
    t = re.split(r"\s*(?:［|\[|（|\(|—|--| - )", t.strip(), 1)[0]
    return t.strip(" 「」")


def validate(items, want, neg, pos):
    """返回 ({i: {zh, tags, other}}, 坏掉的 i 列表, 词表外说法 Counter)。"""
    ok, bad, other = {}, [], {}
    known = neg | pos
    by_i = {}
    for it in items if isinstance(items, list) else []:
        if isinstance(it, dict) and isinstance(it.get("i"), int):
            by_i[it["i"]] = it
    for i in want:
        it = by_i.get(i)
        if not it or not isinstance(it.get("zh"), str) or not it["zh"].strip() or not isinstance(it.get("tags"), list):
            bad.append(i)
            continue
        tags, dropped = [], []
        for t in it["tags"]:
            if not isinstance(t, str):
                continue
            t2 = voccfg.tag(CFG, clean_tag(t))
            if t2 in known and t2 not in tags:
                tags.append(t2)
            elif t2 not in known:
                dropped.append(t.strip())
        for x in dropped:
            other[x] = other.get(x, 0) + 1
        o = it.get("other")
        if isinstance(o, str) and o.strip():
            other[o.strip()] = other.get(o.strip(), 0) + 1
        # 兜底标签只在没有具体标签时保留：有具体的夸就去掉「总体满意」，有具体的骂就去掉「总体不满」
        if GENERIC_POS in tags and any(t in pos and t != GENERIC_POS for t in tags):
            tags.remove(GENERIC_POS)
        if GENERIC_NEG in tags and any(t in neg and t != GENERIC_NEG for t in tags):
            tags.remove(GENERIC_NEG)
        ok[i] = {"zh": it["zh"].strip(), "tags": tags[:4], "other": o.strip() if isinstance(o, str) and o.strip() else ""}
    return ok, bad, other


# ---------- 主流程 ----------
def run_batches(rows, product, label):
    """rows: [(i, review)]。返回 ({i: {zh, tags}}, 统计)。坏掉的条目最多再跑 2 轮。"""
    neg, pos, _ = voccfg.vocab(CFG)
    system = system_prompt(product)
    results, other_all = {}, {}
    stat = {"calls": 0, "in": 0, "out": 0, "retried": 0}
    todo = list(rows)
    for rnd in range(3):
        if not todo:
            break
        batches = [todo[k:k + BATCH] for k in range(0, len(todo), BATCH)]
        if rnd:
            stat["retried"] += len(todo)
            sys.stderr.write(f"  {label}：{len(todo)} 条没通过校验，第 {rnd + 1} 轮重打\n")

        def one(batch):
            text, u = ask(system, user_prompt(batch))
            try:
                data = parse_json(text)
            except (ValueError, json.JSONDecodeError):
                data = {}
            out = validate(data.get("items"), [i for i, _ in batch], neg, pos)
            if out[1]:                                   # 有没通过校验的：留一份原始回复
                BAD.mkdir(parents=True, exist_ok=True)
                f = BAD / f"{label}-{dt.datetime.now():%H%M%S}-{batch[0][0]}.txt"
                f.write_text(f"没通过校验的 i：{out[1]}\n\n{text}", encoding="utf-8")
                sys.stderr.write(f"  {label}：{len(out[1])} 条没通过校验，原始回复在 {f}\n")
            return out, u

        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            outs = list(ex.map(one, batches))
        bad_all = []
        for (ok, bad, other), u in outs:
            results.update(ok)
            bad_all += bad
            for k, v in other.items():
                other_all[k] = other_all.get(k, 0) + v
            stat["calls"] += 1
            stat["in"] += u["in"]
            stat["out"] += u["out"]
        pending = set(bad_all)
        todo = [(i, r) for i, r in todo if i in pending]
    stat["failed"] = [i for i, _ in todo]
    stat["other"] = other_all
    return results, stat


def coverage(reviews):
    U = [r for r in reviews if not r.get("vine")]
    tagged = sum(1 for r in U if r.get("tags"))
    return (round(tagged / len(U) * 100, 1) if U else 0.0), len(U), len(U) - tagged


def cmd_events(p, d):
    """退货 / 换货 / 买家消息的备注 → real（一个一级标签，优先问题标签；只有夸的写「其他」）。"""
    global CH
    ev = d.get("events", [])
    rows = [(i, {"star": None, "title": f"{e.get('type', '退货')}备注" + (f"（平台原因：{e['code']}）" if e.get("code") else ""), "en": e["note"]})
            for i, e in enumerate(ev) if e.get("note") and ("--all" in ARGS or not e.get("real"))]
    if MAXN:
        rows = rows[:MAXN]
    print(f"{p.parent.name}：事件 {len(ev)} 条，带备注 {sum(1 for e in ev if e.get('note'))} 条；本次要读 {len(rows)} 条，约 {-(-len(rows) // BATCH) if rows else 0} 次调用")
    if not rows or "--dry-run" in ARGS:
        return
    CH = channel()
    print(f"模型：{CH['model']}  通道：{CH['api']} {CH['base']}")
    neg, pos, _ = voccfg.vocab(CFG)
    results, stat = run_batches(rows, d.get("product", {}), "读备注")
    tagger = f"tag.py/{CH['model']}@{TODAY}"
    for i, res in results.items():
        tags = res["tags"]
        # 退货 / 换货：优先具体的问题标签；买家消息多是提问，没问题标签时记提问主题（模型的 other 短语），都没有就「其他」
        real = next((t for t in tags if t in neg and t != GENERIC_NEG), None)
        if not real:
            real = (res.get("other") or "其他") if ev[i].get("type") == "买家消息" else (next((t for t in tags if t in neg), None) or "其他")
        ev[i].update({"real": real, "zh": res["zh"], "tagger": tagger})
    p.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    c = {}
    for i in results:
        c[ev[i]["real"]] = c.get(ev[i]["real"], 0) + 1
    print(f"完成：读了 {len(results)} 条，调用 {stat['calls']} 次，tokens 进 {stat['in']} 出 {stat['out']}")
    print("读出来是：" + "、".join(f"{k}×{v}" for k, v in sorted(c.items(), key=lambda kv: -kv[1])[:8]))
    if stat["other"]:
        print("词表外说法：" + "、".join(f"{k}×{v}" for k, v in sorted(stat["other"].items(), key=lambda kv: -kv[1])[:8]))
    print(f"下一步：python3 {HERE / 'dashboard.py'} {p}   # 看板和产品页的退货块按 real 重算")


def cmd_tag(path):
    global CH
    p = pathlib.Path(path).resolve()
    d = json.loads(p.read_text(encoding="utf-8"))
    errs = voccfg.validate(d)
    if errs:
        sys.exit("data.json 结构不对：\n  " + "\n  ".join(errs))
    voccfg.canonicalize(d, CFG)
    if "--events" in ARGS:
        return cmd_events(p, d)
    rv = d["reviews"]
    if "--all" in ARGS:
        rows = [(i, r) for i, r in enumerate(rv) if not r.get("vine")]
    else:
        rows = [(i, r) for i, r in enumerate(rv) if not r.get("vine") and not r.get("tags") and not r.get("tagger")]
    if MAXN:
        rows = rows[:MAXN]
    cov0 = coverage(rv)
    calls = -(-len(rows) // BATCH) if rows else 0
    print(f"{p.parent.name}：非送测 {cov0[1]} 条，现在覆盖 {cov0[0]}%（没标签 {cov0[2]}）；本次要处理 {len(rows)} 条，约 {calls} 次调用（每次 {BATCH} 条）")
    if not rows:
        print("没有要处理的评论（要全部重打加 --all）")
        return
    if "--dry-run" in ARGS:
        return
    CH = channel()
    print(f"模型：{CH['model']}  通道：{CH['api']} {CH['base']}")
    t0 = time.time()
    results, stat = run_batches(rows, d.get("product", {}), "打标")
    tagger = f"tag.py/{CH['model']}@{TODAY}"
    for i, res in results.items():
        rv[i]["zh"], rv[i]["tags"], rv[i]["tagger"] = res["zh"], res["tags"], tagger
    # 不达线：对本次打成空标签的补跑一轮
    cov1 = coverage(rv)
    empties = [(i, rv[i]) for i in results if not rv[i]["tags"]]
    if cov1[0] < LINE and empties:
        sys.stderr.write(f"  覆盖 {cov1[0]}% 低于验收线 {LINE}%，对 {len(empties)} 条空标签补跑一轮\n")
        more, st2 = run_batches(empties, d.get("product", {}), "补跑")
        for i, res in more.items():
            if res["tags"]:
                rv[i]["zh"], rv[i]["tags"], rv[i]["tagger"] = res["zh"], res["tags"], tagger
        for k in ("calls", "in", "out"):
            stat[k] += st2[k]
        for k, v in st2["other"].items():
            stat["other"][k] = stat["other"].get(k, 0) + v
    # tagsNeg / tagsPos：已有的保留，新用到的按词表顺序补上
    neg_order = [t for t in CFG["tags"]["neg"] if not t.startswith("_")]
    pos_order = [t for t in CFG["tags"]["pos"] if not t.startswith("_")]
    used = {t for r in rv for t in r.get("tags", [])}
    d["tagsNeg"] = [t for t in d.get("tagsNeg", []) if t in used] + [t for t in neg_order if t in used and t not in d.get("tagsNeg", [])]
    d["tagsPos"] = [t for t in d.get("tagsPos", []) if t in used] + [t for t in pos_order if t in used and t not in d.get("tagsPos", [])]
    voccfg.canonicalize(d, CFG)
    p.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    cov2 = coverage(rv)
    print(f"完成：打了 {len(results)} 条，调用 {stat['calls']} 次（重打 {stat['retried']} 条），tokens 进 {stat['in']} 出 {stat['out']}，{time.time() - t0:.0f} 秒")
    print(f"覆盖：{cov0[0]}% → {cov2[0]}%（验收线 {LINE}%）" + ("" if cov2[0] >= LINE else "  ⚠ 仍不达线：看下面还没标签的评论是不是真的没内容"))
    if stat["failed"]:
        print(f"  ⚠ {len(stat['failed'])} 条三轮都没通过校验，没写：i = {stat['failed'][:20]}")
    if stat["other"]:
        top = sorted(stat["other"].items(), key=lambda kv: -kv[1])[:10]
        print("词表外说法（出现 ≥ 1 次；要用就先加进 voc.config.json，再 --all 重打或只重打这几条）：\n  " + "、".join(f"{k}×{v}" for k, v in top))
    left = [rv[i]["en"][:50] for i in results if not rv[i]["tags"]][:8]
    if left:
        print("本次仍为空标签的样例：\n  " + "\n  ".join(left))
    print(f"下一步：python3 {HERE / 'analyze.py'} {p}")


# ---------- 金标评测 ----------
def golden_path():
    g = opt("--golden")
    if g:
        return pathlib.Path(g).resolve()
    for c in (HERE / "_eval" / "golden.json", HERE / "examples" / "golden.json"):
        if c.exists():
            return c
    return HERE / "_eval" / "golden.json"


def polarity(tags, neg, pos):
    n, p = any(t in neg for t in tags), any(t in pos for t in tags)
    return "mixed" if n and p else "neg" if n else "pos" if p else "none"


def cmd_golden_build():
    n = int(opt("--n", 50))
    out = golden_path()
    if out.exists() and "--force" not in ARGS:
        sys.exit(f"{out} 已存在：金标集建一次就够，之后人工改它；要重建加 --force")
    asins = list(CFG.get("competitors", []))
    pool = []
    for a in asins:
        f = HERE / a / "data.json"
        if not f.exists():
            continue
        d = json.loads(f.read_text(encoding="utf-8"))
        voccfg.canonicalize(d, CFG)
        for i, r in enumerate(d["reviews"]):
            if not r.get("vine") and r.get("tags") and len(r.get("en") or "") >= 20:
                pool.append({"asin": a, "i": i, "star": r["star"], "title": r.get("title", ""), "en": r["en"], "golden": list(r["tags"])})
    if not pool:
        sys.exit("竞品目录里没有已打标的评论可抽")
    random.seed(20261107)
    by_star = {}
    for x in pool:
        by_star.setdefault(x["star"], []).append(x)
    picks, k = [], 0
    while len(picks) < min(n, len(pool)):           # 按星级轮流抽，让 1–5 星都有
        for s in sorted(by_star):
            if by_star[s] and len(picks) < n:
                picks.append(by_star[s].pop(random.randrange(len(by_star[s]))))
        k += 1
    picks.sort(key=lambda x: (x["asin"], x["i"]))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "_说明": f"打标金标集（{len(picks)} 条，{TODAY} 从已人工复核过的竞品打标里按星级分层抽样）。golden 是「标准答案」：人可以改；改词表后也要同步改这里。"
                 "eval 用它衡量模型 + 提示词 + 词表的一致性，不是衡量某一次分析。",
        "built": TODAY, "source": asins, "items": picks}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"金标集已建：{out}（{len(picks)} 条，星级分布 {dict(sorted((s, sum(1 for x in picks if x['star'] == s)) for s in {x['star'] for x in picks}))}）")


def cmd_eval():
    global CH
    g = golden_path()
    if not g.exists():
        sys.exit(f"没有金标集 {g}：先 python3 tag.py golden-build")
    G = json.loads(g.read_text(encoding="utf-8"))
    items = G["items"][:int(opt("--n", 0)) or None]
    neg, pos, _ = voccfg.vocab(CFG)
    for it in items:
        it["golden"] = [voccfg.tag(CFG, t) for t in it["golden"]]
    CH = channel()
    print(f"评测：{len(items)} 条金标，模型 {CH['model']}（{CH['api']} {CH['base']}）")
    rows = [(k, it) for k, it in enumerate(items)]
    t0 = time.time()
    res, stat = run_batches(rows, {"name": "stair treads"}, "评测")
    jac, exact, pol_ok, tp, fp, fn, rows_out = [], 0, 0, {}, {}, {}, []
    for k, it in rows:
        got = set(res.get(k, {}).get("tags", []))
        gold = set(it["golden"])
        inter, union = got & gold, got | gold
        j = len(inter) / len(union) if union else 1.0
        jac.append(j)
        exact += got == gold
        pol_ok += polarity(got, neg, pos) == polarity(gold, neg, pos)
        for t in inter:
            tp[t] = tp.get(t, 0) + 1
        for t in got - gold:
            fp[t] = fp.get(t, 0) + 1
        for t in gold - got:
            fn[t] = fn.get(t, 0) + 1
        rows_out.append({"asin": it.get("asin"), "i": it.get("i"), "star": it["star"], "en": it["en"][:160], "golden": sorted(gold), "got": sorted(got), "jaccard": round(j, 2), "zh": res.get(k, {}).get("zh")})
    n = len(rows)
    mj, ex, pp = round(sum(jac) / n, 3), round(exact / n * 100, 1), round(pol_ok / n * 100, 1)
    tags = sorted(set(tp) | set(fp) | set(fn), key=lambda t: -(tp.get(t, 0) + fn.get(t, 0)))
    per_tag = []
    for t in tags:
        P = tp.get(t, 0) / (tp.get(t, 0) + fp.get(t, 0)) if tp.get(t, 0) + fp.get(t, 0) else None
        R = tp.get(t, 0) / (tp.get(t, 0) + fn.get(t, 0)) if tp.get(t, 0) + fn.get(t, 0) else None
        per_tag.append({"tag": t, "gold": tp.get(t, 0) + fn.get(t, 0), "tp": tp.get(t, 0), "fp": fp.get(t, 0), "fn": fn.get(t, 0),
                        "precision": None if P is None else round(P * 100), "recall": None if R is None else round(R * 100)})
    acc = CFG.get("acceptance", {})
    line_j, line_p = acc.get("eval_jaccard", 0.6), acc.get("eval_polarity_pct", 90)
    verdict = "通过" if mj >= line_j and pp >= line_p else "不通过"
    out = g.parent / f"eval-{TODAY}.json"
    out.write_text(json.dumps({"date": TODAY, "model": CH["model"], "api": CH["api"], "base": CH["base"], "n": n, "jaccard": mj, "exact_pct": ex, "polarity_pct": pp,
                               "verdict": verdict, "lines": {"jaccard": line_j, "polarity_pct": line_p}, "usage": {k: stat[k] for k in ("calls", "in", "out")},
                               "per_tag": per_tag, "rows": rows_out}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"一致率：Jaccard {mj}（线 {line_j}）  完全一致 {ex}%  好坏方向一致 {pp}%（线 {line_p}%）→ {verdict}；调用 {stat['calls']} 次，tokens 进 {stat['in']} 出 {stat['out']}，{time.time() - t0:.0f} 秒")
    worst = [r for r in per_tag if r["gold"] >= 3 and (r["recall"] or 0) < 60]
    if worst:
        print("召回低的标签（金标 ≥ 3 次、召回 < 60%）：" + "、".join(f"{r['tag']} 召回 {r['recall']}%（漏 {r['fn']}）" for r in worst))
    noisy = [r for r in per_tag if r["fp"] >= 3]
    if noisy:
        print("多打的标签（误打 ≥ 3 次）：" + "、".join(f"{r['tag']} 误打 {r['fp']}" for r in noisy))
    bad = sorted(rows_out, key=lambda r: r["jaccard"])[:6]
    print("差得最远的几条：")
    for r in bad:
        print(f"  [{r['star']}★ J={r['jaccard']}] {r['en'][:70]}…\n      金标 {r['golden']}\n      模型 {r['got']}")
    print(f"明细：{out}")
    if stat["other"]:
        print("词表外说法：" + "、".join(f"{k}×{v}" for k, v in sorted(stat["other"].items(), key=lambda kv: -kv[1])[:8]))


if __name__ == "__main__":
    if not ARGS or ARGS[0].startswith("--"):
        sys.exit(__doc__)
    if ARGS[0] == "eval":
        cmd_eval()
    elif ARGS[0] == "golden-build":
        cmd_golden_build()
    else:
        cmd_tag(ARGS[0])
