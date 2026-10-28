"""站外 VOC · Reddit 采集：只拉数据、去重、存原始数据，不做任何判断。

用法：python3 collect_reddit.py voc-reports/<ASIN>/offsite [--comments 40]
- 读同目录 config.json（queries / subreddits / subreddit_query / relevance / comments）
- 帖子：reddit-readonly 全站搜索 + 板块内搜索；评论：只给标题/正文命中 relevance 的帖子拉前 N 条
- 后端由 reddit-readonly 按能力路由：设了 SORFTIME_KEY 时全站搜索先走 Sorftime，板块搜索走 Arctic / RSS；
  设了 TIKHUB_API_KEY 再加 REDDIT_RO_BACKEND=tikhub 可全走 TikHub（快、按次计费）
- 结果写同目录 raw.json；按帖子 id 去重，重复跑只追加新帖、补拉评论
- 找 reddit-readonly 的顺序：环境变量 REDDIT_RO → 和本 skill 同一 skills 目录下 → ~/.claude/skills → ~/.agents/skills
"""
import json
import os
import pathlib
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

OUT = pathlib.Path(sys.argv[1]).resolve()
CFG = json.loads((OUT / "config.json").read_text(encoding="utf-8"))
RAW = OUT / "raw.json"
NC = int(sys.argv[sys.argv.index("--comments") + 1]) if "--comments" in sys.argv else int(CFG.get("comments", 40))

REL = "reddit-readonly/scripts/reddit-readonly.mjs"
# 本 skill 在 <skills>/voc-agent/ 或 <skills>/<分类>/voc-agent/ 下，两层都找
HERE = pathlib.Path(__file__).resolve()
near = [p for base in (HERE.parents[2], HERE.parents[3]) for p in (base / REL, *base.glob(f"*/{REL}"))]
candidates = [os.environ.get("REDDIT_RO"), *near,
              pathlib.Path.home() / ".claude/skills" / REL, pathlib.Path.home() / ".agents/skills" / REL]
RO = next((pathlib.Path(c) for c in candidates if c and pathlib.Path(c).exists()), None)
if not RO:
    sys.exit("找不到 reddit-readonly：装 https://github.com/WaytoAIC/reddit-market-monitor 里的 skills/reddit-readonly，或设 REDDIT_RO=<reddit-readonly.mjs 路径>")


def ro(*args):
    for attempt in range(3):
        r = subprocess.run(["node", str(RO), *args], capture_output=True, text=True, timeout=180)
        try:
            d = json.loads(r.stdout)
        except json.JSONDecodeError:
            d = {"ok": False}
        if d.get("ok"):
            return d["data"]
        time.sleep(8 * (attempt + 1))
    return None


db = json.loads(RAW.read_text(encoding="utf-8")) if RAW.exists() else {"posts": {}, "runs": []}
posts = db["posts"]
found = 0
cost = {}


def add(p, via):
    global found
    pid = str(p["id"]).replace("t3_", "")
    tags = p.get("voc_tags") or {}
    if pid not in posts:
        found += 1
        posts[pid] = {"id": pid, "subreddit": p.get("subreddit"),
                      # Sorftime 的搜索结果没有标题，只有 AI 摘要：标题位放摘要，并标出来，打标时不能当原话
                      "title": p.get("title") or (tags.get("summary") or "")[:120],
                      "title_is_summary": not p.get("title") and bool(tags.get("summary")),
                      "author": p.get("author"), "created": p.get("created_iso"), "permalink": p.get("permalink"),
                      "text": p.get("selftext_snippet") or "", "summary": tags.get("summary"),
                      "score": p.get("score"), "via": [], "comments": []}
    if via not in posts[pid]["via"]:
        posts[pid]["via"].append(via)


jobs = [("all", q) for q in CFG["queries"]] + [(s, CFG.get("subreddit_query") or CFG["queries"][0]) for s in CFG.get("subreddits", [])]
with ThreadPoolExecutor(4) as ex:
    for (where, q), d in zip(jobs, ex.map(lambda j: ro("search", j[0], j[1], "--limit", "25"), jobs)):
        d = d or {}
        src = d.get("source", "?")
        for k, v in (d.get("cost") or {}).items():
            cost[k] = cost.get(k, 0) + v
        for p in d.get("posts", []):
            if "/comments/" in (p.get("permalink") or ""):
                add(p, f"{src}:{'全站 ' + q if where == 'all' else 'r/' + where}")
        print(f"{'全站「' + q + '」' if where == 'all' else 'r/' + where}：{len(d.get('posts', []))} 条（{src}）", file=sys.stderr)

rule = CFG.get("relevance") or {}
def relevant(p):
    t = f"{p['title']} {p['text']} {p.get('summary') or ''}".lower()
    return all(k in t for k in rule.get("all", [])) and (not rule.get("any") or any(k in t for k in rule["any"]))


todo = [p for p in posts.values() if relevant(p) and not p["comments"]]
def pull(p):
    d = ro("thread", p["id"], "--commentLimit", str(NC)) or {}
    post = d.get("post") or {}
    if post.get("title"):                       # 拉到全文就换掉摘要标题
        p["title"], p["title_is_summary"] = post["title"], False
    if post.get("selftext_snippet"):
        p["text"] = post["selftext_snippet"]
    p["comments"] = [{"author": c.get("author"), "created": c.get("created_iso"), "text": c.get("body_snippet") or "",
                      "score": c.get("score"), "depth": c.get("depth", 0), "permalink": c.get("permalink")}
                     for c in d.get("comments", [])]
    for k, v in (d.get("cost") or {}).items():
        cost[k] = cost.get(k, 0) + v


with ThreadPoolExecutor(4) as ex:
    list(ex.map(pull, todo))
db["runs"].append({"at": time.strftime("%Y-%m-%d %H:%M"), "new_posts": found, "comment_pulls": len(todo), "cost": cost})
RAW.write_text(json.dumps(db, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"新帖 {found}，共 {len(posts)} 帖；拉评论 {len(todo)} 帖；付费调用 {cost or '无'} → {RAW}")
