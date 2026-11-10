"""weekly.py：--dry-run 走通八步不碰任何接口；留痕步写周报 + 时间线，并在临时 git 仓里只 add 本次改动的路径自动 commit（落款可配、--no-commit / 非 git 仓跳过）。

整套脚本拷进临时目录跑（数据 = 样例 B0FMJCMKY1），真仓一个字节不动。
"""
import datetime as dt
import json
import re
import shutil
import unittest

import voctest as T

OWN = "B0FMJCMKY1"


def copy_scripts(src, dst):
    """只拷脚本和模板，不拷任何数据目录。"""
    dst.mkdir(parents=True, exist_ok=True)
    for p in src.iterdir():
        if p.is_file() and (p.suffix == ".py" or p.name in ("template.html", "data.schema.json", "voc")):
            shutil.copy(p, dst / p.name)
        elif p.is_dir() and p.name in ("_tools", "offsite"):
            copy_scripts(p, dst / p.name)


class WeeklyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = T.tmpdir("weekly")
        self.skill = self.tmp / T.SKILL.name
        self.wb = self.tmp / T.WB.name
        copy_scripts(T.SKILL, self.skill)
        copy_scripts(T.WB, self.wb)
        self.data = self.skill                                              # 本地写法：数据和脚本同目录
        T.copy_example(self.data)
        T.make_config(self.tmp, own=OWN)
        T.git_repo(self.tmp)
        self.env = T.env(self.tmp, self.data)
        self.weekly = self.skill / "weekly.py"

    def tearDown(self):
        T.rm(self.tmp)

    def run_weekly(self, *args, extra_env=None):
        r = T.run([T.PY, self.weekly, *args], env={**self.env, **(extra_env or {})}, cwd=self.tmp)
        runs = [json.loads(l) for l in (self.data / "runs.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
        return r, runs[-1] if runs else None

    def commits(self):
        return T.git(self.tmp, "log", "--format=%s").stdout.strip().splitlines()

    def test_dry_run(self):
        r, rep = self.run_weekly("--dry-run")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(rep["dry"])
        self.assertTrue(rep["ok"], rep)
        self.assertEqual(list(rep["steps"]), ["拉评论", "打标签", "投影", "算数", "行动卡", "入飞书", "群草稿", "留痕"])
        self.assertEqual(rep["steps"]["拉评论"]["byAsin"][OWN], {"new": 0, "calls": 0, "dry": True})
        self.assertEqual(rep["steps"]["投影"]["note"], "自家没开脱敏投影")
        self.assertEqual(rep["steps"]["算数"]["analyzed"], [OWN])
        self.assertTrue(rep["steps"]["算数"]["dashboard"])
        self.assertIn("没接飞书行动表", rep["steps"]["行动卡"]["note"])
        self.assertIn("关了", rep["steps"]["入飞书"]["note"])
        self.assertTrue(rep["steps"]["留痕"]["commit"].startswith("跳过"))
        self.assertTrue(rep["steps"]["留痕"]["timeline"])
        today = dt.date.today().isoformat()
        hp = self.data / "_history" / f"周报-{today}.md"
        self.assertTrue(hp.exists())
        txt = hp.read_text(encoding="utf-8")
        self.assertTrue(txt.startswith(f"# VOC 周报 {today}（演练）"))
        self.assertIn("## 这次运转", txt)
        self.assertIn("看板锚定", txt)
        self.assertTrue((self.data / "timeline.json").exists())
        self.assertTrue((self.data / "weekly_draft.md").exists())
        self.assertIn("VOC 周报草稿", (self.data / "weekly_draft.md").read_text(encoding="utf-8"))
        self.assertTrue((self.data / OWN / "报告.html").exists())
        self.assertTrue((self.data / OWN / "dashboard.json").exists())
        self.assertEqual(len(self.commits()), 1)                            # 演练不提交
        self.assertTrue(rep["note"].startswith("演练，"))
        self.assertTrue(list((self.data / "_runs").glob("weekly-*.log")))

    def test_keep_step_commits_only_touched_paths(self):
        r, rep = self.run_weekly("--no-pull", "--no-tag", "--no-actions", "--no-feishu")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse(rep["dry"])
        keep = rep["steps"]["留痕"]
        self.assertTrue(re.fullmatch(r"[0-9a-f]{7,}", keep["commit"]), keep)
        self.assertGreaterEqual(keep["files"], 2)
        log = self.commits()
        self.assertEqual(len(log), 2)
        today = dt.date.today().isoformat()
        self.assertEqual(log[0], f"VOC分析: 每周运转 {today}——新评论 0、打标 0、入飞书 0 行 @Claude Code")
        files = T.git(self.tmp, "show", "--name-only", "--format=", "HEAD").stdout.split()
        allowed = {f"{self.data.name}/{OWN}/data.json", f"{self.data.name}/{OWN}/报告.html", f"{self.data.name}/{OWN}/dashboard.json",
                   f"{self.data.name}/timeline.json", f"{self.data.name}/_history/周报-{today}.md"}
        self.assertTrue(set(files) <= allowed, files)
        self.assertIn(f"{self.data.name}/{OWN}/dashboard.json", files)
        self.assertIn(f"{self.data.name}/_history/周报-{today}.md", files)
        body = T.git(self.tmp, "log", "-1", "--format=%b").stdout
        self.assertIn("自动留痕：weekly.py 第 7 步", body)
        self.assertIn("- 算数：完成", body)
        status = T.git(self.tmp, "status", "--porcelain").stdout
        self.assertNotIn("runs.jsonl", "".join(l for l in status.splitlines() if not l.startswith("??")))   # 运行记录、草稿不进提交
        self.assertFalse(any("runs.jsonl" in f or "weekly_draft" in f or "_runs/" in f for f in files))
        # 落款可用环境变量改；没有新改动就不提交
        (self.data / "_history" / "周报-2020-01-01.md").write_text("# 旧周报\n", encoding="utf-8")
        r, rep = self.run_weekly("--no-pull", "--no-tag", "--no-actions", "--no-feishu", extra_env={"VOC_COMMIT_SIGN": "@Hermes"})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(len(self.commits()), 3)
        self.assertTrue(self.commits()[0].endswith(" @Hermes"), self.commits()[0])
        r, rep = self.run_weekly("--no-pull", "--no-tag", "--no-actions", "--no-feishu", "--no-commit")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(len(self.commits()), 3)
        self.assertTrue(rep["steps"]["留痕"]["commit"].startswith("跳过"))

    def test_outside_git_repo_skips_commit(self):
        other = T.tmpdir("weekly-nogit")
        try:
            skill = other / T.SKILL.name
            copy_scripts(T.SKILL, skill)
            copy_scripts(T.WB, other / T.WB.name)
            T.copy_example(skill)
            T.make_config(other, own=OWN)
            r = T.run([T.PY, skill / "weekly.py", "--no-pull", "--no-tag", "--no-actions", "--no-feishu"], env=T.env(other, skill), cwd=other)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            rep = json.loads((skill / "runs.jsonl").read_text(encoding="utf-8").splitlines()[-1])
            self.assertEqual(rep["steps"]["留痕"]["commit"], "跳过（不在 git 仓里）")
            self.assertTrue((skill / "_history").exists())
        finally:
            T.rm(other)

    def test_config_commit_off(self):
        T.make_config(self.tmp, own=OWN, weekly={"commit": False})
        r, rep = self.run_weekly("--no-pull", "--no-tag", "--no-actions", "--no-feishu")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(rep["steps"]["留痕"]["commit"].startswith("跳过"))
        self.assertEqual(len(self.commits()), 1)


if __name__ == "__main__":
    unittest.main()
