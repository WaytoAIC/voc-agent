"""脱敏投影：把真实自家数据投成可公开的演示数据（别名 + 原话改写 + 等比扩增 + 日期平移），每周重算。

用法：python3 <skill>/project.py [--check] [--dry-run] [--json] [--workers 2]
- 口径在 voc.config.json own.projection（enabled / private），私有参数在 private 指向的文件（不进仓）：
    {"real": "B0XXXXXXXX", "alias": "B0YYYYYYYY", "k": 8, "dateShiftDays": -16, "seed": "…",
     "product": {"brand","name","title","parent"}, "skuMap": {"真实款式": "展示款式"}, "banned": ["品牌", "店名", 子 ASIN…]}
- 种子 = voc-reports/_real/<real>/data.json（ss_pull 拉、tag.py 打标过的真实评论）；输出 = 现场分析/<alias>/data.json
- 规则（全部确定性，同样的种子永远投出同样的结果）：
    · 每条真实评论扩成 k 条变体：星级 / 标签 / 款式 / 送测 / 已验证 全部继承，英文原话、标题、中文意思由模型改写（互不相同、不含品牌型号、意思和事实不变）
    · 日期整体平移 dateShiftDays 天，变体落在平移后的同一周内 → 每周条数 = 真实 × k，趋势形状不变
    · 真实款式按 skuMap（或内置规则：颜色 → 中文、片数 → 「N 片」）换成类目通用叫法
    · 产品信息用 private.product 的别名；评分 = 真实评分，评分数 = 真实 × k；类目排名、主图不投（可识别）
    · 退货 / 换货 / 买家消息：真实 events 每条扩 k 条（原因码 / 真实原因 / 款式继承，备注由模型改写，日期同规则平移）
    · 改写结果缓存在 voc-reports/_real/<real>/_projection_cache.json，每周只改写新评论；变体 ↔ 真实来源的映射在 _projection_map.json（审计用，不进仓）
    · 已写进飞书的事件 ID 从上一版别名文件按原话带回来，不会重编号
- --check：投完核对不变量（星级 / 标签 / 款式 / 送测分布 = 真实分布；每周条数 = 真实 × k）+ 出口扫描（banned 词、连续 8 个词和真原话重合、变体互相雷同），
  任一不过 → 退出码 2，并把问题写进 --json 的 "leaks" / "drift"
- 判断用真实样本量：别名文件带 projection.realByWeek / realReviews，dashboard / weekly 据此标「样本不足」
"""
import datetime as dt
import hashlib
import json
import os
import pathlib
import re
import sys
from concurrent.futures import ThreadPoolExecutor

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import voccfg  # noqa: E402
import llm  # noqa: E402

ARGS = sys.argv[1:]
CHECK, DRY, AS_JSON = "--check" in ARGS, "--dry-run" in ARGS, "--json" in ARGS
WORKERS = int(ARGS[ARGS.index("--workers") + 1]) if "--workers" in ARGS else 2
CFG = voccfg.load()
ROOT = HERE.parent.parent
DATA = voccfg.data_dir(HERE)
PJ = (CFG.get("own") or {}).get("projection") or {}
if not PJ.get("enabled"):
    sys.exit("voc.config.json own.projection.enabled 不是 true，没有投影要做")
PRIV_PATH = pathlib.Path(os.environ.get("VOC_PROJECTION") or PJ.get("private") or "voc-reports/_real/projection.json")   # VOC_PROJECTION：测试时换私有参数文件
if not PRIV_PATH.is_absolute():
    PRIV_PATH = (ROOT / PRIV_PATH) if (ROOT / PRIV_PATH).exists() else (DATA / PRIV_PATH.name if (DATA / PRIV_PATH.name).exists() else DATA / "_real" / "projection.json")
if not PRIV_PATH.exists():
    sys.exit(f"找不到投影私有参数：{PRIV_PATH}")
P = json.loads(PRIV_PATH.read_text(encoding="utf-8"))
REAL, ALIAS, K = P["real"].upper(), P["alias"].upper(), float(P.get("k") or 1)
SHIFT = int(P.get("dateShiftDays") or 0)
SEED = str(P.get("seed") or "voc")
REAL_DIR = DATA / "_real" / REAL
OUT = DATA / ALIAS / "data.json"
CACHE = REAL_DIR / "_projection_cache.json"
MAP = REAL_DIR / "_projection_map.json"
DAY = 86400000
TODAY = dt.date.today().isoformat()
REPORT = {"alias": ALIAS, "k": K, "realReviews": 0, "variants": 0, "paraphrased": 0, "cached": 0, "events": 0, "leaks": [], "drift": [], "errors": []}


def say(*a):
    print(*a, file=sys.stderr if AS_JSON else sys.stdout)


def h(*parts):
    return int(hashlib.sha256(("|".join(str(p) for p in parts) + "|" + SEED).encode()).hexdigest()[:12], 16)


def norm(s):
    return re.sub(r"\s+", " ", re.sub(r"<br\s*/?>", " ", s or "")).strip().lower()


def src_key(r):
    return f"{int(r.get('t') or 0)}|{int(r.get('star') or 0)}|{norm(r.get('en'))[:160]}"


def words(s):
    return re.findall(r"[a-z0-9']+", (s or "").lower())


def ngrams(s, n=8):
    w = words(s)
    return {" ".join(w[i:i + n]) for i in range(len(w) - n + 1)}


# ---------- 款式 ----------
COLORS = {"beige": "米色", "black": "黑色", "brown": "棕色", "grey": "灰色", "gray": "灰色", "white": "白色", "blue": "蓝色", "green": "绿色", "red": "红色", "navy": "藏青", "ivory": "象牙白", "cream": "奶白", "tan": "浅棕", "natural": "原色", "dark grey": "深灰", "dark gray": "深灰", "light grey": "浅灰", "light gray": "浅灰"}


def sku_alias(sku):
    if not sku:
        return ""
    if sku in (P.get("skuMap") or {}):
        return P["skuMap"][sku]
    # 既认卖家精灵的「8" x 30" · Beige · 15」，也认后台 MSKU 的写法（例如「Tread_Beige_7pcs」「76x20_Gray_15PCS」「Landing_Grey」）
    parts = [p.strip() for p in re.split(r"\s*[·,/_\-]\s*|\s+", sku) if p.strip()]
    color, count, glow = None, None, False
    mat = "30×30 落地垫" if (re.search(r'30"?\s*x\s*30', sku.lower()) or "landing" in sku.lower()) else None
    for p in parts:
        pl = p.lower()
        if pl in COLORS or pl.rstrip("e") in ("brwon", "gre"):
            color = COLORS.get(pl) or {"brwon": "棕色", "gre": "灰色"}.get(pl.rstrip("e"), color)
        elif re.fullmatch(r"\d+", pl):
            count = int(pl)
        elif re.fullmatch(r"(\d+)\s*(pcs|pc|pack)", pl):
            count = int(re.match(r"\d+", pl).group())
        elif pl == "fl":
            glow = True
    out = []
    if color:
        out.append(color)
    if mat:
        out.append(mat)
    elif count:
        out.append(f"{count} 片")
    elif any(k in sku.lower() for k in ("tread", "76x20")):
        out.append("15 片")                                                   # 后台不带片数的踏垫 MSKU = 15 片装
    if glow:
        out.append("夜光")
    return " · ".join(out) or "标准款"


# ---------- 日期 ----------
def shift_t(t, key, idx):
    """平移 SHIFT 天后，落在同一周（周一起）内的某一天某一小时；确定性。"""
    base = int(t) + SHIFT * DAY
    d = dt.datetime.fromtimestamp(base / 1000)
    monday = (d - dt.timedelta(days=d.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    x = h(key, idx)
    day, hour = x % 7, (x // 7) % 24
    tt = int((monday + dt.timedelta(days=day, hours=hour)).timestamp() * 1000)
    now = int(dt.datetime.now().timestamp() * 1000)
    return min(tt, now - 3600000)


def week_of(t):
    d = dt.datetime.fromtimestamp(int(t) / 1000)
    return (d - dt.timedelta(days=d.weekday())).strftime("%Y-%m-%d")


# ---------- 改写 ----------
SYSTEM = """You rewrite Amazon customer reviews of a stair-tread / stair-carpet product into several DIFFERENT variants for a demo dataset.
Rules, all mandatory:
1. Keep the meaning, the facts, the complaints and the praise exactly as in the original. Do not add or remove any point. Keep the same overall sentiment and star feeling.
2. Each variant must read as a different real customer: different sentence structure, different vocabulary, different opening. No two variants may share any run of 6 consecutive words with each other or with the original.
3. Length between 60% and 140% of the original. Casual US-English Amazon voice; small natural slips are fine.
4. Never mention any brand, store, seller, model number, ASIN or product name. Say "these treads", "the treads", "they".
5. If the original mentions a color or pack size, keep it consistent with the given variant description; otherwise do not invent one.
6. "zh" is a one-sentence Chinese paraphrase of the meaning (not a translation of the English wording), each variant worded differently.
7. "title" is a short review headline in the same spirit, each different.
Return ONLY a JSON array of exactly N objects: [{"title": "...", "en": "...", "zh": "..."}, ...]"""


def paraphrase(ch, r, n, kind="review"):
    sku = sku_alias(r.get("sku"))
    if kind == "review":
        user = (f"N = {n}\nStar rating: {r.get('star')}\nVariant (color / pack): {sku or 'unknown'}\n"
                f"Original title: {r.get('title') or ''}\nOriginal review:\n{r.get('en') or ''}\n"
                + (f"Original Chinese gist: {r.get('zh')}\n" if r.get("zh") else "") + f"\nReturn exactly {n} variants.")
    else:
        user = (f"N = {n}\nThis is a {r.get('type')} note (return / exchange / buyer message), not a review. Rewrite the note; title may be empty.\n"
                f"Variant (color / pack): {sku or 'unknown'}\nOriginal note:\n{r.get('note') or ''}\n"
                + (f"Original Chinese gist: {r.get('zh')}\n" if r.get("zh") else "") + f"\nReturn exactly {n} variants.")
    orig = ngrams(r.get("en") or r.get("note") or "")
    for attempt in range(3):
        text, _ = llm.ask(ch, SYSTEM, user, max_tokens=4000, temperature=0.7 if attempt else 0.4)
        try:
            items = llm.parse_json(text)
        except Exception:
            continue
        items = [x for x in items if isinstance(x, dict) and x.get("en")]
        good, seen_text, seen_grams = [], set(), []
        for x in items:
            en = en_clean(x.get("en"))
            g = ngrams(en)
            if leak_terms(en) or (g & orig) or norm(en) in seen_text:   # 不许带敏感词、不许和真原话连续 8 词重合、不许一模一样
                continue
            if attempt < 2 and any(g & s for s in seen_grams):           # 前两次还要求变体之间也不重合 8 词；第三次放宽
                continue
            good.append({"title": (x.get("title") or "").strip()[:80], "en": en, "zh": (x.get("zh") or "").strip()})
            seen_text.add(norm(en))
            seen_grams.append(g)
        if len(good) >= n:
            return good[:n]
    return None


def en_clean(s):
    return re.sub(r"[ \t]+", " ", (s or "").replace("\r", "")).strip()


def leak_terms(text):
    t = (text or "").lower()
    return [b for b in BANNED if b and b.lower() in t]


BANNED = list(dict.fromkeys([REAL, *(P.get("banned") or [])]))


# ---------- 主流程 ----------
def allocate(reviews):
    """每条评论分到的变体数：整数部分人人有，小数部分按哈希顺序发给前几条，总数 = round(N×k)。"""
    n = len(reviews)
    target = int(round(n * K))
    base = int(K)
    extra = target - base * n
    order = sorted(range(n), key=lambda i: h("alloc", src_key(reviews[i])))
    alloc = [base] * n
    for i in order[:extra]:
        alloc[i] += 1
    return alloc


def main():
    real = json.loads((REAL_DIR / "data.json").read_text(encoding="utf-8"))
    voccfg.canonicalize(real, CFG)
    reviews = real.get("reviews") or []
    REPORT["realReviews"] = len(reviews)
    if not reviews:
        sys.exit(f"种子没有评论：{REAL_DIR / 'data.json'}")
    untagged = [r for r in reviews if not r.get("tags") and not r.get("vine")]
    if untagged:
        say(f"  注意：{len(untagged)} 条真实评论还没打标（先跑 tag.py），它们的变体标签也会是空的")
    old = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    old_ids = {norm(r.get("en")): r.get("id") for r in (old.get("reviews") or []) if r.get("id") and not old.get("demo")}
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    alloc = allocate(reviews)
    ch = None
    todo = [(i, r, alloc[i]) for i, r in enumerate(reviews) if len((cache.get(src_key(r)) or {}).get("variants") or []) < alloc[i]]
    REPORT["cached"] = len(reviews) - len(todo)
    if todo and not DRY:
        ch = llm.channel()
        say(f"  改写 {len(todo)} 条真实评论 × 最多 {max(a for _, _, a in todo)} 个变体（模型 {ch['model']}，缓存命中 {REPORT['cached']}）")

        def work(item):
            i, r, n = item
            try:
                v = paraphrase(ch, r, n)
            except Exception as e:  # noqa: BLE001
                return i, None, repr(e)
            return i, v, None
        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            for i, v, err in ex.map(work, todo):
                r = reviews[i]
                if v:
                    cache[src_key(r)] = {"at": TODAY, "variants": v}
                    REPORT["paraphrased"] += 1
                else:
                    REPORT["errors"].append(f"评论 {src_key(r)[:40]} 改写失败：{err or '三次都不合规'}")
        CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=0), encoding="utf-8")
    elif todo:
        say(f"  --dry-run：{len(todo)} 条需要改写，没调模型")
        return
    # 组装变体
    out_reviews, mapping, real_by_week = [], {}, {}
    for i, r in enumerate(reviews):
        key = src_key(r)
        vs = (cache.get(key) or {}).get("variants") or []
        if len(vs) < alloc[i]:
            continue
        wk = week_of(int(r["t"]) + SHIFT * DAY)
        real_by_week[wk] = real_by_week.get(wk, 0) + 1
        for j in range(alloc[i]):
            v = vs[j]
            row = {"star": int(r["star"]), "t": shift_t(r["t"], key, j), "sku": sku_alias(r.get("sku")), "vine": bool(r.get("vine")), "verified": bool(r.get("verified", True)),
                   "title": v["title"], "en": v["en"], "zh": v["zh"], "tags": list(r.get("tags") or []),
                   "tagger": f"project.py@{TODAY} ← {r.get('tagger') or '人工'}"}
            if norm(row["en"]) in old_ids:
                row["id"] = old_ids[norm(row["en"])]
            out_reviews.append(row)
            mapping[hashlib.sha1(norm(row["en"]).encode()).hexdigest()[:12]] = {"src": key, "idx": j, "id": row.get("id")}
    out_reviews.sort(key=lambda x: -x["t"])
    REPORT["variants"] = len(out_reviews)
    used = [r for i, r in enumerate(reviews) if len((cache.get(src_key(r)) or {}).get("variants") or []) >= alloc[i]]
    # 事件（有真实的才投）
    out_events = []
    ev_real = [e for e in (real.get("events") or []) if e.get("date")]
    if ev_real:
        ev_alloc = allocate(ev_real) if ev_real else []
        seen_keys = {}
        ev_keys = []
        for e in ev_real:                                                     # 同类型 + 同日 + 同备注开头的事件要能分开，键后面带序号，不然 ID 撞号、飞书只写一份
            base = f"ev|{e.get('type')}|{e.get('date')}|{norm(e.get('note'))[:80]}"
            seen_keys[base] = seen_keys.get(base, 0) + 1
            ev_keys.append(base if seen_keys[base] == 1 else f"{base}#{seen_keys[base]}")
        ev_key = lambda e: ev_keys[ev_real.index(e)]   # noqa: E731
        trivial = lambda e: len(words(e.get("note"))) < 3   # noqa: E731  「xx」这种没内容的备注不改写，原样带过去（没有泄露面）
        ev_todo = [(i, e, ev_alloc[i]) for i, e in enumerate(ev_real) if e.get("note") and not trivial(e) and len((cache.get(ev_keys[i]) or {}).get("variants") or []) < ev_alloc[i]]
        if ev_todo and not DRY:
            ch = ch or llm.channel()
            say(f"  改写 {len(ev_todo)} 条真实备注（并行 {WORKERS}）")

            for i, e, n in list(ev_todo):                                     # 带序号的重复键直接复用第一条的改写
                base = ev_keys[i].split("#")[0]
                if "#" in ev_keys[i] and len((cache.get(base) or {}).get("variants") or []) >= n:
                    cache[ev_keys[i]] = cache[base]
            ev_todo = [(i, e, n) for i, e, n in ev_todo if len((cache.get(ev_keys[i]) or {}).get("variants") or []) < n]

            def work_ev(item):
                i, e, n = item
                try:
                    return i, paraphrase(ch, e, n, kind="event"), None
                except Exception as ex:  # noqa: BLE001
                    return i, None, repr(ex)
            done = 0
            with ThreadPoolExecutor(max_workers=WORKERS) as ex:
                for i, v, err in ex.map(work_ev, ev_todo):
                    if v:
                        cache[ev_key(ev_real[i])] = {"at": TODAY, "variants": v}
                    else:
                        REPORT["errors"].append(f"备注 {ev_key(ev_real[i])[:40]} 改写失败：{err or '三次都不合规'}")
                    done += 1
                    if done % 20 == 0:                                        # 每 20 条落一次缓存，中断不白跑
                        CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=0), encoding="utf-8")
                        say(f"    已改写 {done}/{len(ev_todo)}")
            CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=0), encoding="utf-8")
        for i, e in enumerate(ev_real):
            key = ev_keys[i]
            n = ev_alloc[i]
            vs = (cache.get(key) or {}).get("variants") or []
            if e.get("note") and trivial(e):
                vs = [{"en": e["note"], "zh": e.get("zh", ""), "title": ""}] * n
            if not vs and e.get("note"):                                      # 没改写成功的备注不带原文，只留原因
                e = dict(e, note="")
            t0 = int(dt.datetime.fromisoformat(e["date"]).timestamp() * 1000)
            for j in range(n):
                tt = shift_t(t0, key, j)
                row = {"type": e["type"], "date": dt.datetime.fromtimestamp(tt / 1000).date().isoformat(), "sku": sku_alias(e.get("sku")), "code": e.get("code"), "real": e.get("real"),
                       "hasNote": bool(e.get("note")), "qty": e.get("qty", 1)}
                if e.get("note"):
                    row["note"] = (vs[j]["en"] if j < len(vs) else "")
                    row["zh"] = (vs[j]["zh"] if j < len(vs) else e.get("zh", ""))
                    row["tagger"] = f"project.py@{TODAY}"
                row["id"] = hashlib.sha1(f"{ALIAS}|{key}|{j}".encode()).hexdigest()[:12]   # 事件 ID = 键 + 序号的哈希，确定性，不用从旧文件带
                out_events.append(row)
        CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=0), encoding="utf-8")
    REPORT["events"] = len(out_events)
    # 产品与骨架
    rp = real.get("product") or {}
    pp = P.get("product") or {}
    product = {"asin": ALIAS, "parent": pp.get("parent") or ALIAS, "brand": pp.get("brand") or "自家品牌", "name": pp.get("name") or (CFG.get("own") or {}).get("name") or "自家产品",
               "title": pp.get("title") or "", "price": rp.get("price"), "rating": rp.get("rating"), "ratings": int(round((rp.get("ratings") or 0) * K)) or None,
               "launched": (dt.date.fromisoformat(rp["launched"]) + dt.timedelta(days=SHIFT)).isoformat() if rp.get("launched") else None,
               "variants": sorted({r["sku"] for r in out_reviews if r.get("sku")}),
               "note": "真实产品数据，经脱敏与等比扩增至类目中位规模"}
    product = {k: v for k, v in product.items() if v not in (None, "", [])}
    stars = {}
    for r in out_reviews:
        stars[str(r["star"])] = stars.get(str(r["star"]), 0) + 1
    vine = sum(1 for r in out_reviews if r["vine"])
    keep_groups = {}
    for g in ("problems", "praises"):
        rows = []
        for item in (old.get(g) or []):
            tag = item.get("tag") or item.get("name")
            if tag not in (real.get("tagsNeg") or []) + (real.get("tagsPos") or []) and tag not in {t for r in out_reviews for t in r["tags"]}:
                continue
            hit = sorted([r for r in out_reviews if tag in r["tags"]], key=lambda r: -len(r["en"]))[:3]
            new = {k: v for k, v in item.items() if k not in ("quotes", "count", "hidden")}
            new["quotes"] = [[r["en"], r["zh"], f"{r['star']}★ · {r['sku']}"] for r in hit]
            rows.append(new)
        keep_groups[g] = rows
    d = {"role": "自家", "product": product,
         "pulled": {"at": dt.datetime.now().strftime("%Y-%m-%d %H:%M"), "source": "真实数据投影（脱敏 + 等比扩增）", "calls": 0, "total": len(out_reviews), "vine": vine, "analyzed": len(out_reviews) - vine,
                    "lastPull": {"at": dt.datetime.now().strftime("%Y-%m-%d %H:%M"), "new": 0, "realNew": (real.get("pulled") or {}).get("lastPull", {}).get("new")}},
         "stars": stars, "reviews": out_reviews, "events": out_events,
         "tagsNeg": real.get("tagsNeg") or old.get("tagsNeg") or [], "tagsPos": real.get("tagsPos") or old.get("tagsPos") or [],
         "problems": keep_groups["problems"], "praises": keep_groups["praises"],
         "summary": "", "insight": old.get("insight") or "",
         "projection": {"k": K, "realReviews": len(reviews), "realEvents": len(ev_real), "realByWeek": real_by_week, "at": TODAY,
                        "note": "判断看真实样本量：各页百分比和趋势与真实一致，绝对数 = 真实 × k"}}
    for k in ("journey", "calc", "stages", "tagStage"):
        if old.get(k) is not None and not old.get("demo"):
            d[k] = old[k]
    for k in ("offsite", "alexa"):                                           # 站外 / Alexa 块不是从评论投出来的（Reddit 讨论、平台问答本来就是公开的），重投时原样带上，别冲掉
        if old.get(k) is not None:
            d[k] = old[k]
    voccfg.canonicalize(d, CFG)
    if DRY:
        say(f"  --dry-run：会写 {len(out_reviews)} 条变体、{len(out_events)} 条事件 → {OUT}")
        return
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    MAP.write_text(json.dumps({"alias": ALIAS, "real": REAL, "k": K, "dateShiftDays": SHIFT, "at": TODAY, "variants": mapping}, ensure_ascii=False, indent=0), encoding="utf-8")
    say(f"  投影 → {OUT}：{len(out_reviews)} 条变体（真实 {len(reviews)} × {K:g}），事件 {len(out_events)} 条，改写 {REPORT['paraphrased']} / 缓存 {REPORT['cached']}")
    if CHECK:
        check(real, d, used)


def dist(rows, key):
    c = {}
    for r in rows:
        for v in (key(r) if isinstance(key(r), list) else [key(r)]):
            c[v] = c.get(v, 0) + 1
    n = sum(c.values()) or 1
    return {k: v / n for k, v in c.items()}


def check(real, d, reviews):
    out = d["reviews"]
    for name, key_real, key_out in (("星级", lambda r: int(r["star"]), lambda r: int(r["star"])),
                                    ("款式", lambda r: sku_alias(r.get("sku")), lambda r: r.get("sku")),
                                    ("标签", lambda r: list(r.get("tags") or []), lambda r: list(r.get("tags") or [])),
                                    ("送测", lambda r: bool(r.get("vine")), lambda r: bool(r.get("vine")))):
        a, b = dist(reviews, key_real), dist(out, key_out)
        worst = max(abs(a.get(k, 0) - b.get(k, 0)) for k in set(a) | set(b)) if (a or b) else 0
        if worst > 0.01:
            REPORT["drift"].append(f"{name}分布偏差 {worst:.1%}")
    rw = {}
    for r in out:
        w = week_of(r["t"])
        rw[w] = rw.get(w, 0) + 1
    for w, n in d["projection"]["realByWeek"].items():
        if abs(rw.get(w, 0) - n * K) > 1:
            REPORT["drift"].append(f"周 {w}：真实 {n} × k = {n * K:g}，投影 {rw.get(w, 0)}")
    ev_real = [e for e in (real.get("events") or []) if e.get("date")]
    ev_out = d.get("events") or []
    if ev_real:
        for name, key_real, key_out in (("事件类型", lambda e: e.get("type"), lambda e: e.get("type")), ("原因码", lambda e: e.get("code"), lambda e: e.get("code")),
                                        ("真实原因", lambda e: e.get("real") or "", lambda e: e.get("real") or ""), ("事件款式", lambda e: sku_alias(e.get("sku")), lambda e: e.get("sku"))):
            a, b = dist(ev_real, key_real), dist(ev_out, key_out)
            worst = max(abs(a.get(k, 0) - b.get(k, 0)) for k in set(a) | set(b)) if (a or b) else 0
            if worst > 0.01:
                REPORT["drift"].append(f"{name}分布偏差 {worst:.1%}")
        if abs(len(ev_out) - len(ev_real) * K) > 1:
            REPORT["drift"].append(f"事件条数：真实 {len(ev_real)} × k = {len(ev_real) * K:g}，投影 {len(ev_out)}")
        note_grams = set()
        for e in ev_real:
            note_grams |= ngrams(e.get("note"))
        for e in ev_out:
            if e.get("note") and (ngrams(e["note"]) & note_grams):
                REPORT["leaks"].append(f"事件备注和真备注有连续 8 词重合：{e['note'][:50]}…")
    text = json.dumps(d, ensure_ascii=False).lower()
    for b in BANNED:
        if b and b.lower() in text:
            REPORT["leaks"].append(f"出现敏感词：{b}")
    real_grams = set()
    for r in reviews:
        real_grams |= ngrams(r.get("en"))
    seen = {}
    for r in out:
        g = ngrams(r["en"])
        if g & real_grams:
            REPORT["leaks"].append(f"变体和真原话有连续 8 词重合：{r['en'][:50]}…")
        k = norm(r["en"])
        if k in seen:
            REPORT["leaks"].append(f"两条变体一模一样：{r['en'][:50]}…")
        seen[k] = 1
    if REPORT["leaks"] or REPORT["drift"]:
        say("  核对不过：" + "；".join(REPORT["leaks"][:5] + REPORT["drift"][:5]))
    else:
        say("  核对通过：分布一致、每周条数 = 真实 × k、无敏感词、无原话重合")


try:
    main()
finally:
    if AS_JSON:
        print(json.dumps(REPORT, ensure_ascii=False))
if REPORT["leaks"] or REPORT["drift"] or REPORT["errors"]:
    sys.exit(2)
