"""VOC 工作台本机服务：打开页面，把「问 Agent」转给本机 Hermes 上的 VOC Agent。

用法：python3 workbench/serve.py            # 然后浏览器打开 http://127.0.0.1:8790
      python3 workbench/serve.py --port 8790

口径与 ID 都读项目根目录 voc.config.json（唯一真相源）：自家 / 竞品 ASIN、飞书表、群、Hermes profile。
环境变量只做覆盖（都可选）：
  VOC_CONFIG         voc.config.json 的路径（默认：从本文件往上找）
  VOC_DATA_DIR       每个 ASIN 的分析目录（默认：仓库根目录/现场分析，公开版 仓库根目录/voc-reports）
  VOC_OWN_ASIN       自家产品 ASIN（默认 voc.config.json 的 own.asin）
  VOC_HERMES_PROFILE Hermes 的 profile 名（默认 voc.config.json 的 hermes.profile）
  VOC_GROUP_CHAT_ID  飞书群 chat_id（默认 voc.config.json 的 feishu.group_chat_id；都没有就不能发群）
  LARK_CLI           lark-cli 路径（默认在 PATH 里找）

页面打开时，serve.py 把下面这些注入到页面的 VOC 常量里（页面本身不写死任何数据）：
  config    voc.config.json 里页面要用的部分（own / competitors / stages / feishu 的链接和表 ID / 群名）
  products  workbench/products.json（「我的产品」列表的展示行）
  dashboard <自家>/dashboard.json（首页看板）
  offsite   <自家>/data.json 的 offsite 块（站外 VOC）
  alexa     <自家>/alexa_compare.json（Alexa 怎么说）
  actions   现场分析/actions.json（飞书「行动项跟踪」的本地镜像，actions.py pull 生成）
  jobcard   导出/VOC Agent 岗位卡.html（「VOC Agent」页内嵌的岗位卡；公开版放 workbench/jobcard.html）
  timeline  现场分析/timeline.json（项目时间线 + 功能价值，timeline.py 生成；没有就现算）
接口：
  /api/health        工作台和 Hermes 是否都在线
  /api/config        注入给页面的 config 部分
  /api/agent         把对话转给 Hermes（127.0.0.1:8642/p/<profile>/v1/chat/completions），原样流式返回
  /api/product?asin= 现场分析/<ASIN> 里有没有分析结果（添加产品后轮询它）
  /api/products      现场分析/ 下所有分析过的 ASIN（页面打开时并进产品列表）
  /api/dashboard     自家产品的 dashboard.json；/api/offsite、/api/alexa 同理
  /api/detail?asin=  产品详情页的全部数据（现场分析/detail.py 从 data.json + 竞品 + actions.json 算；没数据的块返回空，页面显示去哪接）
  /api/status        设置页：数据源接没接、本周体检数、运行记录（现场分析/runs.jsonl）、本周群消息草稿（现场分析/weekly_draft.md）
  /api/timeline      项目时间线 + 功能价值（现场分析/timeline.py 现算）
演示数据开关：voc.config.json 的 workbench.demo（默认 true）或环境变量 VOC_DEMO=0/1。关掉后 products.json 里标了 "demo": true 的展示行不再注入，
  列表里只剩 现场分析/ 下真实分析过的 ASIN；自家产品仍以 own.asin 为准。
  /report/<ASIN>     打开 现场分析/<ASIN>/报告.html
  /api/post-to-group 人在面板里点了「发到群」才调用；只能发到配置里的群，用 VOC Agent 机器人身份发
Hermes 的密钥只在这里从 ~/.hermes/profiles/<profile>/.env 读，不会发到浏览器；只监听本机。
"""
import datetime
import hashlib
import http.server
import json
import os
import pathlib
import shutil
import subprocess
import sys
import urllib.error
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
for _p in (ROOT / "现场分析", ROOT / "skill", HERE):     # voccfg.py：本地在 现场分析/，公开仓在 skill/
    sys.path.insert(0, str(_p))
import voccfg  # noqa: E402
import detail  # noqa: E402  产品详情数据（本地在 现场分析/，公开仓在 skill/）
try:
    import timeline  # noqa: E402  项目时间线 + 功能价值
except ImportError:  # 公开仓旧版本没有
    timeline = None

CFG = voccfg.load(HERE)
_demo_env = os.environ.get("VOC_DEMO")
DEMO = (_demo_env not in ("0", "false", "no")) if _demo_env is not None else bool((CFG.get("workbench") or {}).get("demo", True))
PAGE = next((p for p in (HERE / "index.html", ROOT / "模拟稿" / "VOC工作台模拟稿.html") if p.exists()), None)
LIVE_DIR = voccfg.data_dir(HERE)                                              # VOC_DATA_DIR，否则 现场分析/（本地）或 voc-reports/（公开版）
SS_PULL = next((p for p in (HERE / "ss_pull.py", LIVE_DIR / "_tools" / "ss_pull.py") if p.exists()), LIVE_DIR / "_tools" / "ss_pull.py")
PRODUCTS = HERE / "products.json"
JOBCARD = next((p for p in (HERE / "jobcard.html", ROOT / "导出" / "VOC Agent 岗位卡.html") if p.exists()), HERE / "jobcard.html")
HERMES = "http://127.0.0.1:8642"
PROFILE = os.environ.get("VOC_HERMES_PROFILE") or (CFG.get("hermes") or {}).get("profile", "voc")
ENV = pathlib.Path.home() / ".hermes" / "profiles" / PROFILE / ".env"
FS = CFG.get("feishu") or {}
OWN = (os.environ.get("VOC_OWN_ASIN") or (CFG.get("own") or {}).get("asin", "")).upper()
OWN_NAME = (CFG.get("own") or {}).get("name", "自家产品")
GROUP_ID = os.environ.get("VOC_GROUP_CHAT_ID") or FS.get("group_chat_id", "")
GROUP_NAME = FS.get("group_name", "VOC专项群")
LARK = os.environ.get("LARK_CLI") or shutil.which("lark-cli") or str(pathlib.Path.home() / ".hermes" / "node" / "bin" / "lark-cli")
SENT_LOG = HERE / "sent.log"
PORT = int(sys.argv[sys.argv.index("--port") + 1]) if "--port" in sys.argv else 8790

SYSTEM = (
    "你在 VOC 工作台的「问 Agent」面板里回答。先给结论，再给依据（条数、占比、原话）；"
    f"数据只用本地 {LIVE_DIR}/<ASIN>/data.json 和飞书「VOC工作台」的表，没有的就直说。"
    "标签、旅程环节、阈值的口径在项目根目录 voc.config.json，引用口径时以它为准。"
    "Alexa 回答是平台归纳，引用时注明。回答控制在手机一屏内，用简单的 Markdown（加粗、列表）。"
    "只写本地分析文件；不改飞书表、不动 listing；你自己不发任何消息。"
    "用户要「同步到群里」「发到群」时：先重新核对最新数据，再把要发的群消息完整写在一个代码块里，"
    "代码块第一行写 ```群消息，结尾用 ```；块里只放要发的正文（可用 Markdown 加粗、列表），不放说明。"
    f"代码块外用一句话说明「点下面的按钮才会发到 {GROUP_NAME}」。不要说已经发出。"
    f"格式示例（必须照这个格式，三个反引号紧跟「群消息」三个字）：\n```群消息\n**行动进度**\n- A-001 背胶粘不住：待负责人决定\n```\n点下面的按钮才会发到 {GROUP_NAME}。"
    f"自家产品「{OWN_NAME}」{OWN} 就当工作台的自家产品来比，不用提它的数据来源。"
    "卖家精灵 MCP 不在你的工具列表、或连接报错（500/超时）时，不要停：直接运行 "
    f"python3 {SS_PULL} <ASIN> --pages 10，"
    f"它直连卖家精灵、自带重试，原始数据写到 {LIVE_DIR}/<ASIN>/，调用次数算在用户已确认的预算里。"
    "要花钱调用接口（卖家精灵、Alexa 采集）或写飞书之前，先说清要做什么、调用几次，等用户确认。"
)


def api_key():
    for line in ENV.read_text(encoding="utf-8").splitlines():
        if line.startswith("API_SERVER_KEY="):
            return line.split("=", 1)[1].strip()
    raise RuntimeError(f"{ENV} 里没有 API_SERVER_KEY（按 ai-hub 接线：aihub apply hermes）")


def _json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _text(path):
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def page_config():
    """注入给页面的配置：只给页面要用的，不给密钥。"""
    return {"version": CFG.get("version"), "own": CFG.get("own"), "competitors": CFG.get("competitors", []), "demo": DEMO,
            "stages": CFG["stages"]["order"], "tags": {"neg": list(CFG["tags"]["neg"]), "pos": list(CFG["tags"]["pos"])},
            "feishu": {"wiki_url": FS.get("wiki_url", ""), "tables": FS.get("tables", {}), "table_names": FS.get("table_names", {}),
                       "group_name": GROUP_NAME, "can_post": bool(GROUP_ID)}}


def summary(asin):
    d = LIVE_DIR / asin
    if not (asin.isalnum() and (d / "data.json").exists()):
        return {"asin": asin, "exists": False}
    data = _json(d / "data.json") or {}
    voccfg.canonicalize(data, CFG)
    rv = [r for r in data.get("reviews", []) if not r.get("vine")]
    neg = data.get("tagsNeg", [])
    cnt = {}
    for r in rv:
        for x in r.get("tags", []):
            if x in neg:
                cnt[x] = cnt.get(x, 0) + 1
    top = max(cnt.items(), key=lambda kv: kv[1]) if cnt else None
    pr = data.get("product", {})
    rep = d / "报告.html"
    now = datetime.date.today()
    last_t = max((r.get("t") or 0) for r in rv) if rv else 0
    ref = datetime.date.fromtimestamp(last_t / 1000) if last_t else now     # 「本周」= 数据最新一天往前 7 天；数据停在过去也能看
    new_rev = sum(1 for r in rv if r.get("t") and (ref - datetime.date.fromtimestamp(r["t"] / 1000)).days < 7)
    ev = [e for e in data.get("events", []) if e.get("date")]
    ev_ref = max((datetime.date.fromisoformat(e["date"]) for e in ev), default=None)
    in30 = lambda t: sum(1 for e in ev if e.get("type") == t and (ev_ref - datetime.date.fromisoformat(e["date"])).days < 30) if ev_ref else None
    drill = (data.get("calc") or {}).get("drill") or {}
    kidrows = [[s["sku"], s["n"], s["share"], s["negShare"],
                sum(1 for e in ev if e.get("type") == "退货" and e.get("sku") == s["sku"]) if ev else None,
                sum(1 for e in ev if e.get("type") == "换货" and e.get("sku") == s["sku"]) if ev else None,
                (s.get("top") or [{}])[0].get("name", "—")] for s in drill.get("skus", []) if s.get("sku")][:8]
    return {"asin": asin, "exists": True, "report": rep.exists(), "updated": int(rep.stat().st_mtime) if rep.exists() else 0,
            "name": pr.get("name") or pr.get("title") or asin, "brand": pr.get("brand"), "rating": pr.get("rating"),
            "n": len(rv), "neg": round(sum(1 for r in rv if r.get("star", 5) <= 3) / len(rv) * 100, 1) if rv else None,
            "top": [top[0], top[1]] if top else None, "own": asin == OWN or data.get("role") == "自家",
            "newRev": new_rev, "ret30": in30("退货"), "ex30": in30("换货"), "msg30": in30("买家消息"), "kidrows": kidrows,
            "pulledAt": (data.get("pulled") or {}).get("at")}


def demo_products():
    """「我的产品」列表：products.json 的展示行（名称 / 图片 / 款式数）+ 真实分析过的 ASIN 的数字。
    展示行对应的 ASIN 在数据目录里有 data.json → 评分、新评论、差评占比、退货、最大的问题全部换成算出来的数，"demo" 标记去掉；
    没有 data.json 的展示行（示例用的自家其他产品）只在 workbench.demo=true 时显示。"""
    out = []
    for r in (_json(PRODUCTS) or {}).get("products", []):
        live = summary(r.get("asin", "").upper()) if r.get("asin") else {"exists": False}
        if live.get("exists"):
            r = {k: v for k, v in r.items() if k not in ("demo", "ret", "retT", "negT", "rd", "todo")}
            r.update({"rating": live.get("rating") or r.get("rating"), "newRev": live.get("newRev"), "neg": live.get("neg"), "retN": live.get("ret30"), "ex": live.get("ex30"),
                      "kidrows": live.get("kidrows") or [], "pulledAt": live.get("pulledAt"), "n": live.get("n"),
                      "issue": f"{live['top'][0]}（{live['top'][1]}/{live['n']} 条）" if live.get("top") else "—",
                      "report": f"/report/{live['asin']}" if live.get("report") else r.get("report"), "status": ["good", "已分析"]})
            if len(r["kidrows"]) > 1:
                r["kids"] = len(r["kidrows"])
            out.append(r)
        elif DEMO or not r.get("demo"):
            out.append(r)
    return out


def analyzed_asins():
    return sorted(d.parent.name for d in LIVE_DIR.glob("*/data.json") if d.parent.name.isalnum() and d.parent.name.upper().startswith("B0"))


def status():
    """设置页要的：数据源接没接、本周体检、运行记录。只看文件和配置，不调任何接口。"""
    own = _json(LIVE_DIR / OWN / "data.json") or {}
    asins = analyzed_asins()
    comps = [a for a in CFG.get("competitors", []) if (LIVE_DIR / a / "data.json").exists()]
    ev = own.get("events", [])
    ss_cfg = pathlib.Path.home() / ".hermes" / "profiles" / PROFILE / "config.yaml"
    has_ss = ss_cfg.exists() and "sellersprite" in (_text(ss_cfg) or "")
    runs = []
    rp = LIVE_DIR / "runs.jsonl"
    if rp.exists():
        for line in (_text(rp) or "").splitlines()[-12:]:
            try:
                runs.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    pulled = own.get("pulled") or {}
    return {"demo": DEMO, "ownAsin": OWN, "analyzed": asins, "competitors": comps, "pulled": pulled, "check": (own.get("calc") or {}).get("check"),
            "events": {t: sum(1 for e in ev if e.get("type") == t) for t in ("退货", "换货", "买家消息")},
            "eventsNoted": sum(1 for e in ev if e.get("note")), "eventsRead": sum(1 for e in ev if e.get("real")),
            "alexa": (LIVE_DIR / OWN / "alexa_compare.json").exists(), "offsite": bool(own.get("offsite")),
            "feishu": bool(FS.get("tables", {}).get("events")) and bool(FS.get("base")), "group": bool(GROUP_ID),
            "sellersprite": has_ss, "llm": bool(os.environ.get("VOC_LLM_KEY")), "hermesProfile": PROFILE,
            "actionsAsOf": (_json(LIVE_DIR / "actions.json") or {}).get("asOf"), "runs": list(reversed(runs)),
            "draft": _text(LIVE_DIR / "weekly_draft.md") or "",
            "draftAt": datetime.datetime.fromtimestamp((LIVE_DIR / "weekly_draft.md").stat().st_mtime).strftime("%Y-%m-%d %H:%M") if (LIVE_DIR / "weekly_draft.md").exists() else None,
            "tags": {"neg": len([t for t in CFG["tags"]["neg"] if not t.startswith("_")]), "pos": len([t for t in CFG["tags"]["pos"] if not t.startswith("_")])}}


def timeline_data(fresh=False):
    """时间线：优先读 timeline.py 写的文件（每周运转留痕时更新）；没有或要最新就现算。"""
    if not fresh:
        t = _json(LIVE_DIR / "timeline.json")
        if t:
            return t
    if timeline is None:
        return None
    try:
        return timeline.collect()
    except Exception as e:  # 时间线算不出不拖垮整页
        return {"error": str(e), "events": [], "features": []}


def page_data():
    own = LIVE_DIR / OWN
    d = _json(own / "data.json") or {}
    acts = _json(LIVE_DIR / "actions.json")
    details = {}
    for a in analyzed_asins():
        try:
            details[a] = detail.build(a, acts, OWN)
        except Exception as e:  # 一个产品的数据坏了不拖垮整页
            details[a] = {"asin": a, "exists": False, "error": str(e)}
    return {"config": page_config(), "products": demo_products(),
            "dashboard": _json(own / "dashboard.json"), "offsite": d.get("offsite"), "alexa": _json(own / "alexa_compare.json"),
            "actions": acts, "jobcard": _text(JOBCARD), "details": details, "status": status(), "timeline": timeline_data()}


def render_page(data=None):
    """把数据注入页面的 /*VOC_DATA*/{}/*/VOC_DATA*/ 位置；导出离线版也走这里。"""
    html = PAGE.read_text(encoding="utf-8")
    if "<meta charset" not in html[:500]:
        html = '<meta charset="utf-8">\n' + html
    blob = json.dumps(data if data is not None else page_data(), ensure_ascii=False).replace("</", "<\\/")
    marker = "/*VOC_DATA*/{}/*/VOC_DATA*/"
    if marker not in html:
        raise RuntimeError("页面里没有 /*VOC_DATA*/ 标记")
    return html.replace(marker, blob, 1)


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        sys.stderr.write("[workbench] " + fmt % args + "\n")

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _file(self, path, what):
        if path.exists():
            return self._send(200, path.read_text(encoding="utf-8"))
        return self._send(200, json.dumps({"missing": f"没有 {what}：{path}"}, ensure_ascii=False))   # 页面按「没数据」处理，不在控制台报 404

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            return self._send(200, render_page(), "text/html; charset=utf-8")
        if path == "/api/health":
            try:
                with urllib.request.urlopen(HERMES + "/v1/health", timeout=3) as r:
                    ok = r.status == 200
            except Exception:
                ok = False
            return self._send(200, json.dumps({"workbench": True, "hermes": ok, "profile": PROFILE, "own": OWN, "config": CFG.get("_path")}))
        if path == "/api/config":
            return self._send(200, json.dumps(page_config(), ensure_ascii=False))
        if path == "/api/product":
            return self._product()
        if path == "/api/products":
            out = [s for s in (self._summary(a) for a in analyzed_asins()) if s.get("exists")]
            return self._send(200, json.dumps({"products": out}, ensure_ascii=False))
        if path == "/api/detail":
            from urllib.parse import parse_qs, urlparse
            asin = (parse_qs(urlparse(self.path).query).get("asin") or [""])[0].upper()
            if not asin.isalnum():
                return self._send(400, json.dumps({"error": "asin?"}))
            try:
                return self._send(200, json.dumps(detail.build(asin, _json(LIVE_DIR / "actions.json"), OWN), ensure_ascii=False))
            except Exception as e:
                return self._send(500, json.dumps({"error": f"算不出 {asin} 的详情：{e}"}, ensure_ascii=False))
        if path == "/api/status":
            return self._send(200, json.dumps(status(), ensure_ascii=False))
        if path == "/api/timeline":
            return self._send(200, json.dumps(timeline_data(fresh=True) or {"error": "没有 timeline.py"}, ensure_ascii=False))
        if path == "/api/dashboard":
            return self._file(LIVE_DIR / OWN / "dashboard.json", "看板（先跑 现场分析/dashboard.py）")
        if path == "/api/alexa":
            return self._file(LIVE_DIR / OWN / "alexa_compare.json", "Alexa 对比数据")
        if path == "/api/actions":
            return self._file(LIVE_DIR / "actions.json", "行动项镜像（先跑 现场分析/actions.py pull）")
        if path == "/api/offsite":
            d = _json(LIVE_DIR / OWN / "data.json") or {}
            if d.get("offsite"):
                return self._send(200, json.dumps(d["offsite"], ensure_ascii=False))
            return self._send(404, json.dumps({"error": "没有站外数据（先跑 现场分析/offsite/analyze_offsite.py）"}, ensure_ascii=False))
        if path.startswith("/report/"):
            asin = path.split("/")[2].upper()
            f = LIVE_DIR / asin / "报告.html"
            if asin.isalnum() and f.exists():
                return self._send(200, f.read_text(encoding="utf-8"), "text/html; charset=utf-8")
        self._send(404, json.dumps({"error": "not found"}))

    def _product(self):
        from urllib.parse import parse_qs, urlparse
        asin = (parse_qs(urlparse(self.path).query).get("asin") or [""])[0].upper()
        return self._send(200, json.dumps(self._summary(asin), ensure_ascii=False))

    def _summary(self, asin):
        return summary(asin)

    def _post_to_group(self):
        n = int(self.headers.get("Content-Length", "0"))
        req = json.loads(self.rfile.read(n) or b"{}")
        text = (req.get("text") or "").strip()
        if not GROUP_ID:
            return self._send(400, json.dumps({"error": "没有配置群：在 voc.config.json 填 feishu.group_chat_id，或设环境变量 VOC_GROUP_CHAT_ID"}, ensure_ascii=False))
        if req.get("confirm") is not True:
            return self._send(400, json.dumps({"error": "需要在面板里点按钮确认后才能发"}))
        if not text or len(text) > 4000:
            return self._send(400, json.dumps({"error": "消息为空或超过 4000 字"}))
        key = hashlib.sha1(text.encode()).hexdigest()[:40]
        env = dict(os.environ, HERMES_HOME=str(pathlib.Path.home() / ".hermes" / "profiles" / PROFILE))
        cmd = [str(LARK), "im", "+messages-send", "--as", "bot", "--chat-id", GROUP_ID,
               "--markdown", text, "--idempotency-key", key, "--format", "json"]
        r = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=60)
        try:
            out = json.loads(r.stdout or "{}")
        except json.JSONDecodeError:
            out = {}
        ok = bool(out.get("ok"))
        msg_id = ((out.get("data") or {}).get("message_id")) if ok else None
        with SENT_LOG.open("a", encoding="utf-8") as f:
            f.write(f'{datetime.datetime.now():%Y-%m-%d %H:%M:%S}\t{"ok" if ok else "fail"}\t{GROUP_NAME}\t{len(text)} 字\t{msg_id or (out.get("error") or {}).get("message", r.stderr[-200:])}\n')
        if not ok:
            err = (out.get("error") or {}).get("message") or r.stderr[-300:] or "发送失败"
            return self._send(502, json.dumps({"error": err}, ensure_ascii=False))
        return self._send(200, json.dumps({"ok": True, "group": GROUP_NAME, "message_id": msg_id,
                                           "at": f"{datetime.datetime.now():%H:%M}"}, ensure_ascii=False))

    def do_POST(self):
        if self.path.split("?")[0] == "/api/post-to-group":
            return self._post_to_group()
        if self.path.split("?")[0] != "/api/agent":
            return self._send(404, json.dumps({"error": "not found"}))
        try:
            n = int(self.headers.get("Content-Length", "0"))
            req = json.loads(self.rfile.read(n) or b"{}")
            history = [m for m in req.get("messages", []) if m.get("role") in ("user", "assistant")][-12:]
            ctx = (req.get("context") or "").strip()
            system = SYSTEM + (f"\n用户当前在工作台看的是：{ctx}" if ctx else "")
            body = json.dumps({"model": PROFILE, "stream": True,
                               "messages": [{"role": "system", "content": system}] + history}).encode()
            up = urllib.request.Request(
                f"{HERMES}/p/{PROFILE}/v1/chat/completions", data=body, method="POST",
                headers={"Authorization": f"Bearer {api_key()}", "Content-Type": "application/json"})
            resp = urllib.request.urlopen(up, timeout=600)
        except urllib.error.HTTPError as e:
            return self._send(502, json.dumps({"error": f"Hermes 返回 {e.code}"}))
        except Exception as e:  # Hermes 没开、密钥没接上等
            return self._send(503, json.dumps({"error": f"连不上 Hermes：{e}"}))
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        try:
            while True:
                chunk = resp.readline()
                if not chunk:
                    break
                self.wfile.write(chunk)
                if chunk in (b"\n", b"\r\n"):
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            resp.close()


if __name__ == "__main__":
    if not PAGE:
        sys.exit("找不到页面：工作台/index.html 或 模拟稿/VOC工作台模拟稿.html")
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"VOC 工作台：http://127.0.0.1:{PORT}   自家 {OWN}  配置 {CFG.get('_path')}  （Ctrl+C 停止）")
    srv.serve_forever()
