"""测试公共件：定位两种目录结构（本地 现场分析/ + 工作台/，公开仓 skill/ + workbench/），生成不碰真实数据的临时口径文件。

所有测试只用标准库 unittest；不调卖家精灵、不调模型、不写飞书、不 commit 真仓。
数据来源：自带样例 data.json（B0FMJCMKY1）+ 测试里手工拼的最小集。跑法：项目根目录 python3 -m unittest discover -s tests -v
"""
import datetime as dt
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
SKILL = next(p for p in (ROOT / "现场分析", ROOT / "skill") if (p / "analyze.py").exists())
TOOLS = SKILL / "_tools" if (SKILL / "_tools").exists() else SKILL
WB = next(p for p in (ROOT / "工作台", ROOT / "workbench") if (p / "serve.py").exists())
LOCAL = SKILL.name == "现场分析"
DASHBOARD = SKILL / "dashboard.py" if (SKILL / "dashboard.py").exists() else WB / "dashboard.py"
SS_PULL = TOOLS / "ss_pull.py" if (TOOLS / "ss_pull.py").exists() else WB / "ss_pull.py"
PROJECT = TOOLS / "project.py"
TIMELINE = SKILL / "timeline.py"
WEEKLY = SKILL / "weekly.py"
EXAMPLE = next(p for p in (SKILL / "B0FMJCMKY1" / "data.json", SKILL / "examples" / "B0FMJCMKY1" / "data.json") if p.exists())
CONFIG_SRC = ROOT / "voc.config.json" if (ROOT / "voc.config.json").exists() else SKILL / "voc.config.example.json"
TEMPLATE_DIR = next((p for p in (WB / "飞书模板", ROOT / "agent" / "feishu") if (p / "VOC工作台.base").exists()), None)
PY = sys.executable
# 任何脚本若意外想调模型，都撞到一个不存在的端口，而不是本机网关
DEAD_LLM = {"VOC_LLM_API": "openai", "VOC_LLM_BASE": "http://127.0.0.1:9", "VOC_LLM_KEY": "test-no-model", "VOC_LLM_MODEL": "none"}


def ms(y, m, d, h=12):
    return int(dt.datetime(y, m, d, h).timestamp() * 1000)


def load_config():
    return json.loads(CONFIG_SRC.read_text(encoding="utf-8"))


def make_config(dst, own="B0FMJCMKY1", competitors=(), projection=None, **over):
    """写一份只用于测试的 voc.config.json：词表照抄，自家 / 竞品 / 飞书 / 投影全部换成空的或测试值。"""
    c = load_config()
    c["own"] = {"asin": own, "name": "测试自家", "brand": "测试", "projection": projection or {"enabled": False, "private": ""}}
    c["competitors"] = list(competitors)
    c["feishu"] = {"wiki_url": "", "base": "", "tables": {"events": "", "actions": "", "reddit": ""},
                   "table_names": c["feishu"]["table_names"], "group_chat_id": "", "group_name": "测试群"}
    c["workbench"] = {"demo": False}
    c["weekly"] = {**{k: v for k, v in (c.get("weekly") or {}).items() if not k.startswith("_")},
                   "feishu": False, "export": False, "commit": True, "commit_sign": "@Claude Code", "readback_write": False}
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(c.get(k), dict):
            c[k].update(v)
        else:
            c[k] = v
    p = pathlib.Path(dst) / "voc.config.json"
    p.write_text(json.dumps(c, ensure_ascii=False, indent=1), encoding="utf-8")
    return p


def env(tmp, data_dir=None, config=None, **extra):
    """子进程环境：口径文件、数据目录、假 HOME（不读本机 ~/.hermes），模型通道指向死端口。"""
    tmp = pathlib.Path(tmp)
    home = tmp / "home"
    home.mkdir(parents=True, exist_ok=True)
    e = {k: v for k, v in os.environ.items() if not k.startswith("VOC_")}
    e.update({"HOME": str(home), "VOC_CONFIG": str(config or tmp / "voc.config.json"), "VOC_DATA_DIR": str(data_dir or tmp),
              "PYTHONDONTWRITEBYTECODE": "1", **DEAD_LLM, **extra})
    return e


def run(cmd, env=None, cwd=None, timeout=600):
    return subprocess.run([str(c) for c in cmd], capture_output=True, text=True, env=env, cwd=str(cwd) if cwd else None, timeout=timeout)


def last_json(out):
    for line in reversed(out.strip().splitlines()):
        if line.startswith("{"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                pass
    return {}


def example_data():
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


def copy_example(dst_dir, asin="B0FMJCMKY1", **patch):
    d = example_data()
    d.update(patch)
    p = pathlib.Path(dst_dir) / asin / "data.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    return p


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), "-c", "user.name=voc-test", "-c", "user.email=voc-test@example.com",
                           "-c", "core.hooksPath=/dev/null", "-c", "core.quotepath=false", *args], capture_output=True, text=True)


def git_repo(path):
    """把目录变成一个干净的临时 git 仓（不碰真仓的 hook）。"""
    git(path, "init", "-q")
    git(path, "config", "user.name", "voc-test")                           # weekly.py 自己跑 git commit，没有身份的机器（CI）会拒绝
    git(path, "config", "user.email", "voc-test@example.com")
    git(path, "config", "commit.gpgsign", "false")
    git(path, "add", "-A")
    r = git(path, "commit", "-q", "-m", "init")
    assert r.returncode == 0, r.stderr
    return path


def tmpdir(prefix):
    return pathlib.Path(tempfile.mkdtemp(prefix=f"voc-{prefix}-")).resolve()   # macOS 的 /var 是 /private/var 的软链，脚本里 resolve 过的路径要能对上


def rm(path):
    shutil.rmtree(path, ignore_errors=True)
