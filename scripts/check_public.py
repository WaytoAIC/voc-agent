"""公开仓一致性检查（GitHub Actions 里跑，本地 push 前也跑）。

用法：python3 scripts/check_public.py [--repo <公开仓目录>]       # 公开仓里
      python3 scripts/check_public.py --repo ~/dev/voc-agent            # 本地源仓里指向公开仓
查什么（任何一条不过就退出码 1）：
  1 脱敏：git 跟踪的所有文本文件不含 BANNED 里的任何模式（真实飞书链接和 ID、本机绝对路径、内网 IP、密钥样子的串；人名 / 公司 / 真实 ASIN 这类具体字符串由本地源仓的 publish_public.py 在同步时扫，不进公开仓）
  2 两份 voccfg.py（skill/ 和 workbench/）必须一字不差
  3 skill/voc.config.example.json：飞书 ID 全空、脱敏投影关着、JSON 合法
  4 不能跟踪任何 _real/ 目录、*.raw.json、runs.jsonl、.env
  5 CHANGELOG.md 顶部版本号：在 tag 上跑（GITHUB_REF_TYPE=tag）时必须等于 tag 名
  6 飞书 .base 模板和 schema.json 与 voc.config.example.json 一致（agent/feishu/，调 workbench/base_template.py check）
  7 tests/ 和 CI 工作流在
publish_public.py 的脱敏扫描用的是同一份 BANNED（它从这里 import），本地改一处两边生效。
"""
import json
import os
import pathlib
import re
import subprocess
import sys

BANNED = [r"feishu\.cn/(wiki|base|docx|sheets)/[A-Za-z0-9]{10,}",      # 任何真实飞书链接
          r"tbl[A-Za-z0-9]{12}", r"oc_[a-z0-9]{10}", r"ou_[a-z0-9]{10}", r"cli_[a-z0-9]{10}", r"bascn[A-Za-z0-9]{10,}",   # 飞书表 / 群 / 人 / 应用 / Base 的 ID
          r"claude\.ai/artifact", r"/Users/[^/\s\"']+/", r"100\.94\.\d+\.\d+",                                       # 私人链接、本机绝对路径、内网 IP
          r"key=[A-Za-z0-9]{20,}", r"(?i)(secret[_-]?key|api[_-]?key|token)\s*[:=]\s*[\"']?[A-Za-z0-9_-]{24,}"]          # 密钥样子的串
# 本地源仓的 publish_public.py 在这份之上再加私有字符串（人名 / 公司 / 租户 / 真实 ASIN），那些不进公开仓。
TEXT_EXT = {".py", ".md", ".json", ".yaml", ".yml", ".sh", ".html", ".txt", ".base", ".cfg", ".toml", ""}


def tracked(repo):
    r = subprocess.run(["git", "-C", str(repo), "ls-files", "-z"], capture_output=True, text=True)
    if r.returncode:
        sys.exit("不是 git 仓或 git 不可用：" + r.stderr)
    return [repo / p for p in r.stdout.split("\0") if p]


def scan_banned(repo, files):
    errs = []
    for p in files:
        if p.suffix.lower() not in TEXT_EXT or not p.is_file() or p.name == "check_public.py":   # 模式表自己不扫自己
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for pat in BANNED:
            for m in re.finditer(pat, text):
                ctx = text[max(0, m.start() - 25):m.end() + 25]
                errs.append(f"{p.relative_to(repo)}: {pat} → …{ctx.replace(chr(10), ' ')}…")
                break
    return errs


def main():
    args = sys.argv[1:]
    here = pathlib.Path(__file__).resolve().parent
    repo = pathlib.Path(args[args.index("--repo") + 1]).expanduser().resolve() if "--repo" in args else here.parent
    files = tracked(repo)
    rel = {str(p.relative_to(repo)) for p in files}
    errs = scan_banned(repo, files)
    a, b = repo / "skill/voccfg.py", repo / "workbench/voccfg.py"
    if a.exists() and b.exists() and a.read_bytes() != b.read_bytes():
        errs.append("skill/voccfg.py 和 workbench/voccfg.py 不一致")
    ex = repo / "skill/voc.config.example.json"
    if ex.exists():
        try:
            c = json.loads(ex.read_text(encoding="utf-8"))
            fs = c.get("feishu") or {}
            if fs.get("base") or fs.get("wiki_url") or fs.get("group_chat_id") or any((fs.get("tables") or {}).values()):
                errs.append("voc.config.example.json 的 feishu 段带着真实 ID")
            if ((c.get("own") or {}).get("projection") or {}).get("enabled"):
                errs.append("voc.config.example.json 的 own.projection.enabled 应为 false")
        except json.JSONDecodeError as e:
            errs.append(f"voc.config.example.json 不是合法 JSON：{e}")
    else:
        errs.append("缺 skill/voc.config.example.json")
    for p in rel:
        if "/_real/" in p or p.startswith("_real/") or p.endswith(".raw.json") or p.endswith("runs.jsonl") or p.split("/")[-1] in (".env", "secrets.env"):
            errs.append(f"不该进仓的文件：{p}")
    ch = repo / "CHANGELOG.md"
    if ch.exists():
        m = re.search(r"^## (v\d+\.\d+\.\d+)", ch.read_text(encoding="utf-8"), re.M)
        if not m:
            errs.append("CHANGELOG.md 顶部没有 ## vX.Y.Z 标题")
        elif os.environ.get("GITHUB_REF_TYPE") == "tag" and os.environ.get("GITHUB_REF_NAME") and os.environ["GITHUB_REF_NAME"] != m.group(1):
            errs.append(f"CHANGELOG 顶部 {m.group(1)} ≠ tag {os.environ['GITHUB_REF_NAME']}")
    else:
        errs.append("缺 CHANGELOG.md")
    tpl = repo / "agent/feishu"
    bt = repo / "workbench/base_template.py"
    if (tpl / "VOC工作台.base").exists() and bt.exists():
        r = subprocess.run([sys.executable, str(bt), "check", "--dir", str(tpl)], capture_output=True, text=True, cwd=str(repo),
                           env={**os.environ, "VOC_CONFIG": str(ex)})
        if r.returncode:
            errs.append("飞书模板校验不过：" + (r.stdout + r.stderr).strip()[-600:])
    else:
        errs.append("缺 agent/feishu/VOC工作台.base 或 workbench/base_template.py")
    if not any(p.startswith("tests/test_") for p in rel):
        errs.append("缺 tests/test_*.py")
    if not any(p.startswith(".github/workflows/") for p in rel):
        errs.append("缺 .github/workflows/*.yml")
    if errs:
        print(f"公开仓检查不过（{len(errs)} 条）：\n  " + "\n  ".join(errs))
        sys.exit(1)
    print(f"公开仓检查通过：{len(files)} 个跟踪文件无敏感信息，voccfg 一致，样例口径干净，CHANGELOG / 模板 / 测试 / CI 都在")


if __name__ == "__main__":
    main()
