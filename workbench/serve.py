"""VOC 工作台本机服务：打开页面，把「问 Agent」转给本机 Hermes 上的 VOC Agent。

用法：python3 workbench/serve.py            # 然后浏览器打开 http://127.0.0.1:8790
      python3 workbench/serve.py --port 8790

环境变量（都可选）：
  VOC_DATA_DIR       每个 ASIN 的分析目录（默认：仓库根目录/现场分析）
  VOC_OWN_ASIN       自家产品 ASIN；跑过 dashboard.py 后首页换成它的看板
  VOC_HERMES_PROFILE Hermes 的 profile 名（默认 voc）
  VOC_GROUP_CHAT_ID  飞书群 chat_id，不填就不能发群
  VOC_GROUP_NAME     群名（默认 VOC专项群）
  LARK_CLI           lark-cli 路径（默认在 PATH 里找）

- 页面：workbench/index.html
- /api/health：工作台和 Hermes 是否都在线
- /api/agent：把对话转给 Hermes（127.0.0.1:8642/p/voc/v1/chat/completions），原样流式返回
- /api/product?asin=：现场分析/<ASIN> 里有没有分析结果（添加产品后轮询它，出报告就把真实数字填回列表）
- /api/products：现场分析/ 下所有分析过的 ASIN（页面打开时并进产品列表）
- /api/dashboard：设了 VOC_OWN_ASIN 且跑过 dashboard.py 时，首页换成这个产品的看板
- /report/<ASIN>：打开 现场分析/<ASIN>/报告.html
- /api/post-to-group：人在面板里点了「发到 VOC专项群」才调用；只能发到 VOC专项群，用 VOC Agent 机器人身份发
- Hermes 的密钥只在这里从 ~/.hermes/profiles/voc/.env 读，不会发到浏览器；只监听本机
"""
import datetime
import shutil
import hashlib
import http.server
import os
import subprocess
import json
import pathlib
import sys
import urllib.error
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
PAGE = HERE / "index.html"
LIVE_DIR = pathlib.Path(os.environ.get("VOC_DATA_DIR", ROOT / "现场分析")).expanduser()
SS_PULL = HERE / "ss_pull.py"
HERMES = "http://127.0.0.1:8642"
PROFILE = os.environ.get("VOC_HERMES_PROFILE", "voc")
ENV = pathlib.Path.home() / ".hermes" / "profiles" / PROFILE / ".env"
GROUP_ID = os.environ.get("VOC_GROUP_CHAT_ID", "")   # 只能发到这个群；不填就不能发
GROUP_NAME = os.environ.get("VOC_GROUP_NAME", "VOC专项群")
LARK = os.environ.get("LARK_CLI") or shutil.which("lark-cli") or str(pathlib.Path.home() / ".hermes" / "node" / "bin" / "lark-cli")
SENT_LOG = HERE / "sent.log"
PORT = int(sys.argv[sys.argv.index("--port") + 1]) if "--port" in sys.argv else 8790

SYSTEM = (
    "你在 VOC 工作台的「问 Agent」面板里回答。先给结论，再给依据（条数、占比、原话）；"
    "数据只用本地 现场分析/<ASIN>/data.json 和飞书「VOC工作台」两张表，没有的就直说。"
    "Alexa 回答是平台归纳，引用时注明。回答控制在手机一屏内，用简单的 Markdown（加粗、列表）。"
    "只写本地分析文件（现场分析/ 下）；不改飞书表、不动 listing；你自己不发任何消息。"
    "用户要「同步到群里」「发到群」时：先重新核对最新数据，再把要发的群消息完整写在一个代码块里，"
    "代码块第一行写 ```群消息，结尾用 ```；块里只放要发的正文（可用 Markdown 加粗、列表），不放说明。"
    "代码块外用一句话说明「点下面的按钮才会发到 VOC专项群」。不要说已经发出。"
    "格式示例（必须照这个格式，三个反引号紧跟「群消息」三个字）：\n```群消息\n**行动进度**\n- A-001 背胶粘不住：待负责人决定\n```\n点下面的按钮才会发到 VOC专项群。"
    ""
    "卖家精灵 MCP 不在你的工具列表、或连接报错（500/超时）时，不要停：直接运行 "
    f"python3 {SS_PULL} <ASIN> --pages 10，"
    "它直连卖家精灵、自带重试，原始数据写到 现场分析/<ASIN>/，调用次数算在用户已确认的预算里。"
    "要花钱调用接口（卖家精灵、Alexa 采集）或写飞书之前，先说清要做什么、调用几次，等用户确认。"
)


def api_key():
    for line in ENV.read_text(encoding="utf-8").splitlines():
        if line.startswith("API_SERVER_KEY="):
            return line.split("=", 1)[1].strip()
    raise RuntimeError(f"{ENV} 里没有 API_SERVER_KEY（按 ai-hub 接线：aihub apply hermes）")


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

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            html = PAGE.read_text(encoding="utf-8")
            if "<meta charset" not in html[:500]:
                html = '<meta charset="utf-8">\n' + html
            return self._send(200, html, "text/html; charset=utf-8")
        if path == "/api/health":
            try:
                with urllib.request.urlopen(HERMES + "/v1/health", timeout=3) as r:
                    ok = r.status == 200
            except Exception:
                ok = False
            return self._send(200, json.dumps({"workbench": True, "hermes": ok, "profile": PROFILE}))
        if path == "/api/product":
            return self._product()
        if path == "/api/products":
            out = []
            for d in sorted(LIVE_DIR.glob("*/data.json")):
                if d.parent.name.isalnum() and d.parent.name.upper().startswith("B0"):
                    s = self._summary(d.parent.name)
                    if s.get("exists"):
                        out.append(s)
            return self._send(200, json.dumps({"products": out}, ensure_ascii=False))
        if path == "/api/dashboard":
            own = os.environ.get("VOC_OWN_ASIN", "").upper()
            f = LIVE_DIR / own / "dashboard.json"
            if own and f.exists():
                return self._send(200, f.read_text(encoding="utf-8"))
            return self._send(404, json.dumps({"error": "没设 VOC_OWN_ASIN，或还没跑 dashboard.py"}, ensure_ascii=False))
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
        d = LIVE_DIR / asin
        if not (asin.isalnum() and (d / "data.json").exists()):
            return {"asin": asin, "exists": False}
        data = json.loads((d / "data.json").read_text(encoding="utf-8"))
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
        out = {"asin": asin, "exists": True, "report": rep.exists(), "updated": int(rep.stat().st_mtime) if rep.exists() else 0,
               "name": pr.get("name") or pr.get("title") or asin, "brand": pr.get("brand"), "rating": pr.get("rating"),
               "n": len(rv), "neg": round(sum(1 for r in rv if r.get("star", 5) <= 3) / len(rv) * 100, 1) if rv else None,
               "top": [top[0], top[1]] if top else None, "own": data.get("role") == "自家"}
        return out

    def _post_to_group(self):
        n = int(self.headers.get("Content-Length", "0"))
        req = json.loads(self.rfile.read(n) or b"{}")
        text = (req.get("text") or "").strip()
        if not GROUP_ID:
            return self._send(400, json.dumps({"error": "没有配置群：设置环境变量 VOC_GROUP_CHAT_ID"}, ensure_ascii=False))
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
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"VOC 工作台：http://127.0.0.1:{PORT}   （Ctrl+C 停止）")
    srv.serve_forever()
