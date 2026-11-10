"""timeline.py：把运转 / 版本 / 文档 / 数据 / 行动 / 播报 / 评测串成时间线 + 功能价值卡。全部读临时目录里的文件，不读本机 ~/.hermes。"""
import json
import unittest

import voctest as T

RUNS = [
    {"at": "2026-11-03 09:00", "dry": True, "steps": {}, "calls": 0, "newReviews": 0, "tagged": 0, "feishu": 0, "problems": [], "ok": True, "note": "演练"},
    {"at": "2026-11-09 09:00", "dry": False, "calls": 2, "newReviews": 2, "tagged": 2, "feishu": 2, "problems": [], "ok": True, "note": "新评论 2", "log": "x.log", "seconds": 10,
     "steps": {"拉评论": {"byAsin": {"B0FMJCMKY1": {"new": 2, "calls": 2}}, "ok": True},
               "投影": {"variants": 16, "realReviews": 2, "events": 0, "ok": True},
               "入飞书": {"written": 2, "skipped": 100, "ok": True},
               "行动卡": {"checkText": "巡检 2026-11-09：卡住 1 处\n- A-01 采纳了却没填验证日期", "ok": True}}},
]
ACTIONS = {"asOf": "2026-11-09", "actions": [
    {"id": "A-01", "problem": "边角翘、粘不住", "plan": "换胶", "planDate": "2026-10-20", "doneDate": "2026-10-25", "verifyDate": "2099-12-20",
     "metric": "评论里提「边角翘、粘不住」的占比", "start": "10%", "target": "5%", "readbackAt": "2026-11-01", "actual": "8%", "judgement": "看不出来",
     "status": "等验证", "series": {"points": [1, 2]}}]}
EVAL = {"date": "2026-11-07", "model": "test-model", "n": 50, "jaccard": 0.65, "polarity_pct": 92, "exact_pct": 40}


class TimelineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = T.tmpdir("timeline")
        self.data = self.tmp / "data"
        self.data.mkdir()
        T.make_config(self.tmp)
        self.env = T.env(self.tmp, self.data)
        T.copy_example(self.data, events=[{"type": "退货", "date": "2026-10-30", "real": "颜色偏差", "note": "x", "hasNote": True}],
                       projection={"k": 8, "realReviews": 5, "realEvents": 1, "realByWeek": {}, "at": "2026-11-09", "note": ""})
        (self.data / "runs.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in RUNS) + "\n", encoding="utf-8")
        (self.data / "actions.json").write_text(json.dumps(ACTIONS, ensure_ascii=False), encoding="utf-8")
        (self.data / "actions_check.md").write_text("巡检：卡住 1 处\n", encoding="utf-8")
        (self.data / "_eval").mkdir()
        (self.data / "_eval" / "eval-2026-11-07.json").write_text(json.dumps(EVAL), encoding="utf-8")
        (self.data / "_history").mkdir()
        (self.data / "_history" / "周报-2026-11-09.md").write_text("# 周报\n", encoding="utf-8")
        (self.data / "weekly_draft.md").write_text("草稿\n", encoding="utf-8")
        wb = self.tmp / "工作台"
        wb.mkdir()
        (wb / "sent.log").write_text("2026-11-02 10:00\tok\tVOC专项群\t本周周报\n2026-11-09 10:00\tfail\tVOC专项群\t第二条\n", encoding="utf-8")
        (self.tmp / "调研").mkdir()
        (self.tmp / "调研" / "01-测试-20261020.md").write_text("# 测试\n", encoding="utf-8")
        T.git(self.tmp, "init", "-q")
        T.git(self.tmp, "add", "-A")
        r = T.git(self.tmp, "commit", "-q", "-m", "VOC分析: 初始化——测试 @Claude Code")
        self.assertEqual(r.returncode, 0, r.stderr)

    def tearDown(self):
        T.rm(self.tmp)

    def collect(self):
        r = T.run([T.PY, T.TIMELINE, "--json"], env=self.env, cwd=self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        return json.loads(r.stdout.strip().splitlines()[-1])

    def test_events_and_features(self):
        out = self.collect()
        self.assertEqual(out["own"], "B0FMJCMKY1")
        kinds = out["kinds"]
        self.assertEqual(kinds.get("运转"), 2)
        self.assertEqual(kinds.get("版本"), 1)
        self.assertEqual(kinds.get("文档"), 1)
        self.assertEqual(kinds.get("数据"), 3)                              # 评论最新到 / 拉取 / 退货等事件最新到
        self.assertEqual(kinds.get("行动"), 5)                              # 计划 / 上线 / 验证到期 / 读回 / 镜像
        self.assertEqual(kinds.get("播报"), 2)
        self.assertEqual(kinds.get("评测"), 1)
        self.assertNotIn("计划", kinds)                                     # 假 HOME 里没有 Hermes 定时任务
        ev = out["events"]
        self.assertEqual([e["date"] for e in ev], sorted((e["date"] for e in ev), reverse=True))
        by = {}
        for e in ev:
            by.setdefault(e["kind"], []).append(e)
        self.assertEqual(by["版本"][0]["title"], "初始化")                  # 去掉前缀和落款，——后面进 detail
        self.assertEqual(by["版本"][0]["detail"], "测试")
        self.assertEqual((by["文档"][0]["date"], by["文档"][0]["title"]), ("2026-10-20", "01-测试-20261020"))
        run_titles = sorted(e["title"] for e in by["运转"])
        self.assertEqual(run_titles, ["每周运转", "演练"])
        real = next(e for e in by["运转"] if e["title"] == "每周运转")
        self.assertIn("新评论 B0FMJCMKY1 2", real["detail"])
        self.assertIn("投影 2 → 16 条评论", real["detail"])
        self.assertIn("入飞书 2 行", real["detail"])
        self.assertIn("卡住 1 处", real["detail"])
        self.assertTrue(any(e["title"].startswith("验证到期：A-01") and e.get("future") for e in by["行动"]))
        self.assertTrue(any(e["title"].startswith("Agent 读回：A-01") for e in by["行动"]))
        self.assertEqual(sorted(e["ok"] for e in by["播报"]), [False, True])
        self.assertIn("Jaccard 0.65", by["评测"][0]["detail"])
        f = {x["key"]: x for x in out["features"]}
        self.assertEqual(set(f), {"pull", "tag", "project", "analyze", "events", "actions", "feishu", "broadcast", "offsite", "weekly", "history"})
        self.assertEqual(dict(f["weekly"]["value"])["真跑"], "1 次（成功 1）")
        self.assertEqual(dict(f["weekly"]["value"])["演练"], "1 次")
        self.assertEqual(f["weekly"]["status"], "warn")                   # 没读到定时任务
        self.assertEqual(dict(f["history"]["value"])["commit"], "1 次")
        self.assertEqual(dict(f["history"]["value"])["周报留档"], "1 份")
        self.assertEqual(dict(f["broadcast"]["value"])["已发到群"], "1 条")
        self.assertEqual(dict(f["feishu"]["value"])["表里行数（约）"], "102 行")
        self.assertEqual(dict(f["feishu"]["value"])["运转以来写入"], "2 行")
        self.assertEqual(dict(f["actions"]["value"])["行动卡"], "1 张")
        self.assertEqual(f["actions"]["status"], "warn")
        self.assertEqual(f["actions"]["note"], "卡住 1 处（巡检）")
        self.assertEqual(dict(f["project"]["value"])["倍数 k"], "×8")
        self.assertEqual(dict(f["events"]["value"])["退货"], "1 条")
        self.assertEqual(dict(f["pull"]["value"])["运转以来新增"], "2 条")
        self.assertEqual(dict(f["pull"]["value"])["卖家精灵调用"], "2 次")
        self.assertEqual(out["lastRun"]["at"], "2026-11-09 09:00")
        self.assertIsNone(out["next"])

    def test_writes_timeline_json(self):
        r = T.run([T.PY, T.TIMELINE], env=self.env, cwd=self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        p = self.data / "timeline.json"
        self.assertTrue(p.exists())
        out = json.loads(p.read_text(encoding="utf-8"))
        self.assertIn("时间线", r.stdout)
        self.assertEqual(len(out["events"]), sum(out["kinds"].values()))

    def test_empty_workspace(self):
        """什么都没有也不报错：零事件、功能卡全是 plain。"""
        empty = T.tmpdir("timeline-empty")
        try:
            data = empty / "data"
            data.mkdir()
            T.make_config(empty, own="B0NONE00001")
            r = T.run([T.PY, T.TIMELINE, "--json"], env=T.env(empty, data), cwd=empty)
            self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
            out = json.loads(r.stdout.strip().splitlines()[-1])
            self.assertEqual(out["events"], [])
            self.assertTrue(all(x["status"] == "plain" for x in out["features"]), [(x["key"], x["status"]) for x in out["features"]])
            self.assertIsNone(out["lastRun"])
        finally:
            T.rm(empty)


if __name__ == "__main__":
    unittest.main()
