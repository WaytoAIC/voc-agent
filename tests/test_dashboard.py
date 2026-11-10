"""dashboard.py：运行日锚定（--as-of / VOC_AS_OF）、12 周趋势、快照、月度 / 累计 / fresh、投影倍数折算。离线，只用样例和手拼数据。"""
import collections
import datetime as dt
import json
import unittest

import voctest as T


def synth_data(cfg, k=None):
    """一份手拼的 data.json：5 条非送测评论 + 1 条送测，4 条事件，日期围绕 2026-11-09 这个运行日摆。"""
    stage = {**cfg["tags"]["neg"], **cfg["tags"]["pos"]}
    rows = [(2026, 11, 3, 2, ["边角翘、粘不住"], "米色 · 15 片"), (2026, 11, 4, 5, ["好看"], "灰色 · 15 片"), (2026, 11, 5, 3, ["仍会打滑"], "米色 · 15 片"),
            (2026, 10, 27, 4, ["好看"], "灰色 · 15 片"), (2026, 9, 10, 1, ["边角翘、粘不住"], "米色 · 15 片")]
    reviews = [{"star": s, "t": T.ms(y, m, d), "sku": sku, "vine": False, "verified": True, "title": "t", "en": f"review {i}", "zh": "", "tags": tags}
               for i, (y, m, d, s, tags, sku) in enumerate(rows)]
    reviews.append({"star": 5, "t": T.ms(2026, 11, 3), "sku": "", "vine": True, "verified": False, "title": "v", "en": "vine review", "zh": "", "tags": []})
    events = [{"type": "退货", "date": "2026-11-04", "sku": "米色 · 15 片", "code": "不想要", "real": "颜色偏差", "hasNote": True, "note": "n", "qty": 1},
              {"type": "退货", "date": "2026-11-04", "sku": "灰色 · 15 片", "code": "不想要", "real": "颜色偏差", "hasNote": True, "note": "n", "qty": 1},
              {"type": "换货", "date": "2026-10-28", "sku": "米色 · 15 片", "code": "换色", "real": "颜色偏差", "hasNote": False, "qty": 1},
              {"type": "买家消息", "date": "2026-11-05", "sku": "", "code": None, "real": "能不能机洗", "hasNote": True, "note": "n", "qty": 1}]
    d = {"role": "自家", "product": {"asin": "B0SYNTH0001", "name": "合成品", "brand": "测试", "variants": ["米色 · 15 片", "灰色 · 15 片"]},
         "pulled": {"at": "2026-11-09 09:00", "source": "测试"}, "stars": {}, "reviews": reviews, "events": events,
         "tagsNeg": ["边角翘、粘不住", "仍会打滑"], "tagsPos": ["好看"], "tagStage": {t: stage[t] for t in ("边角翘、粘不住", "仍会打滑", "好看")},
         "problems": [{"name": "边角翘、粘不住", "owner": "产品", "fix": "换胶"}], "praises": [], "summary": "", "insight": ""}
    if k:
        d["projection"] = {"k": k, "realReviews": 3, "realEvents": 2, "realByWeek": {}, "at": "2026-11-09"}
    return d


class DashboardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = T.tmpdir("dash")
        self.cfgp = T.make_config(self.tmp)
        self.cfg = json.loads(self.cfgp.read_text(encoding="utf-8"))
        self.env = T.env(self.tmp)

    def tearDown(self):
        T.rm(self.tmp)

    def dash(self, data_path, *args, extra_env=None):
        r = T.run([T.PY, T.DASHBOARD, data_path, *args], env={**self.env, **(extra_env or {})}, cwd=self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        return json.loads((data_path.parent / "dashboard.json").read_text(encoding="utf-8")), r.stdout

    def write(self, d, asin):
        p = self.tmp / asin / "data.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        return p

    def test_example_anchored_on_run_day(self):
        p = T.copy_example(self.tmp)
        out, stdout = self.dash(p, "--as-of", "2026-11-09")              # 周一 → 最新完整周 = 11/2–11/8
        db = self.cfg["thresholds"]["dashboard"]
        self.assertEqual(out["anchor"], "run")
        self.assertEqual(out["runDate"], "2026-11-09")
        self.assertEqual(out["asOf"], "2026-11-08")
        self.assertEqual(out["latestWeek"], "11/2–11/8")
        self.assertEqual(len(out["trend"]), db["weeks"])
        self.assertEqual(out["trend"][-1]["week"], "11/2")
        self.assertEqual(len(out["snaps"]), db["weeks"] - db["min_weeks_for_snapshot"] + 1)
        self.assertEqual(out["snaps"][-1]["end"], "2026-11-08")
        self.assertEqual([m["month"] for m in out["monthly"]], [f"{y}-{m:02d}" for y, m in ((2025, 12), (2026, 1), (2026, 2), (2026, 3), (2026, 4), (2026, 5), (2026, 6), (2026, 7), (2026, 8), (2026, 9), (2026, 10), (2026, 11))])
        d = T.example_data()
        U = [r for r in d["reviews"] if not r.get("vine")]
        day = lambda r: dt.date.fromtimestamp(r["t"] / 1000)  # noqa: E731
        self.assertEqual(out["cumulative"]["reviews"], len(U))
        self.assertEqual(out["cumulative"]["vine"], sum(1 for r in d["reviews"] if r.get("vine")))
        self.assertEqual(out["cumulative"]["neg"], sum(1 for r in U if r["star"] <= 3))
        self.assertEqual(out["cumulative"]["lastReview"], max(day(r) for r in U).isoformat())
        self.assertEqual(out["cumulative"]["firstReview"], min(day(r) for r in U).isoformat())
        self.assertEqual(out["cumulative"]["months"], len({day(r).strftime("%Y-%m") for r in U}))
        self.assertEqual(out["fresh"]["lastReview"], out["cumulative"]["lastReview"])
        self.assertEqual(out["fresh"]["pulledAt"], d["pulled"]["at"])
        in12 = [r for r in U if day(r).strftime("%Y-%m") in {m["month"] for m in out["monthly"]}]
        self.assertEqual(sum(m["reviews"] for m in out["monthly"]), len(in12))
        self.assertIsNone(out["k"])
        self.assertNotIn("realReviews", out["cumulative"])
        self.assertIn("锚定运行日 2026-11-09，最新完整周 11/2–11/8", stdout)

    def test_env_and_flag(self):
        p = T.copy_example(self.tmp)
        out, _ = self.dash(p, extra_env={"VOC_AS_OF": "2026-11-09"})
        self.assertEqual(out["asOf"], "2026-11-08")
        out, _ = self.dash(p, "--as-of", "2026-11-02", extra_env={"VOC_AS_OF": "2026-11-09"})   # 命令行优先于环境变量
        self.assertEqual(out["asOf"], "2026-11-01")
        self.assertEqual(out["latestWeek"], "10/26–11/1")

    def test_synthetic_weeks_months_events(self):
        p = self.write(synth_data(self.cfg, k=2), "B0SYNTH0001")
        out, _ = self.dash(p, "--as-of", "2026-11-09")
        s = out["snaps"][-1]
        self.assertEqual(s["week"], "11/2–11/8")
        self.assertEqual(out["trend"][-1], {"week": "11/2", "reviews": 3, "neg": 2, "negShare": 66.7})
        self.assertEqual(out["trend"][-2], {"week": "10/26", "reviews": 1, "neg": 0, "negShare": 0.0})
        v = s["kpi"]["voices"]
        self.assertEqual(v["split"], {"评论": 3, "退货": 2, "换货": 0, "买家消息": 1})
        self.assertEqual((v["now"], v["prev"]), (6, 2))                   # 前一周：1 条评论 + 1 次换货
        self.assertEqual((v["realNow"], v["realPrev"]), (3, 1))           # k=2 折回真实样本量
        self.assertEqual(s["kpi"]["negShare"], {"now": 66.7, "prev": 0.0})
        self.assertEqual(s["kpi"]["returns"], {"now": 2, "prev": 0, "d4": 2})
        self.assertEqual(s["kpi"]["top"], {"tag": "边角翘、粘不住", "now": 33.3, "prev": 0.0})
        self.assertEqual(s["sources"], {"评论": 4, "退货": 2, "换货": 1, "买家消息": 1})   # 近 4 周 10/12–11/8
        self.assertEqual([(r["name"], r["count"], r["core"]) for r in s["pareto"]["rows"]], [("边角翘、粘不住", 1, True), ("仍会打滑", 1, True)])
        self.assertEqual(s["pareto"]["mentions"], 2)
        self.assertEqual([(x["sku"], x["n"], x["negShare"]) for x in s["skus"]], [("米色 · 15 片", 2, 100.0), ("灰色 · 15 片", 2, 0.0)])
        self.assertIsNone(s["hot"])                                        # 样本不到 sku_hot.min_sku_reviews，不标热点
        j = {x["stage"]: x for x in s["journey"]}
        self.assertEqual((j["日常使用"]["good"], j["日常使用"]["bad"]), (2, 2))
        self.assertEqual(s["returns"]["n"], 2)
        self.assertEqual(s["returns"]["topCode"], "不想要")
        self.assertEqual(s["returns"]["realInTop"], [["颜色偏差", 2]])
        self.assertEqual(s["messages"], {"n": 1, "top": [["能不能机洗", 1]]})
        self.assertEqual(s["actions"], [{"name": "边角翘、粘不住", "count": 1, "owner": "产品", "fix": "换胶"}])
        self.assertEqual([x["kind"] for x in s["change"]], ["新出现", "新出现"])
        m = {x["month"]: x for x in out["monthly"]}
        self.assertEqual({k: m["2026-11"][k] for k in ("reviews", "neg", "negShare", "returns", "exchanges", "messages", "realReviews")},
                         {"reviews": 3, "neg": 2, "negShare": 66.7, "returns": 2, "exchanges": 0, "messages": 1, "realReviews": 2})
        self.assertEqual((m["2026-10"]["reviews"], m["2026-10"]["exchanges"]), (1, 1))
        self.assertEqual((m["2026-09"]["reviews"], m["2026-09"]["neg"]), (1, 1))
        c = out["cumulative"]
        self.assertEqual((c["reviews"], c["vine"], c["neg"], c["negShare"]), (5, 1, 3, 60.0))
        self.assertEqual(c["events"], {"退货": 2, "换货": 1, "买家消息": 1})
        self.assertEqual((c["firstReview"], c["lastReview"], c["months"]), ("2026-09-10", "2026-11-05", 3))
        self.assertEqual(c["realEvents"], 2)
        f = out["fresh"]
        self.assertEqual(f["lastEvent"], {"退货": "2026-11-04", "换货": "2026-10-28", "买家消息": "2026-11-05"})
        self.assertEqual(f["reviewGapDays"], 3)
        self.assertEqual(f["lastWeekWithReviews"], "11/2–11/8")
        self.assertEqual(out["k"], 2)
        self.assertEqual(out["owners"], {"边角翘、粘不住": {"owner": "产品", "fix": "换胶"}})

    def test_quiet_latest_week(self):
        """最新周没声音：如实为 0，fresh 指向最近有评论的周，月度照常，近 4 周没再提的问题记「已解决」。"""
        p = self.write(synth_data(self.cfg), "B0SYNTH0001")
        out, _ = self.dash(p, "--as-of", "2026-12-21")                    # 最新完整周 12/14–12/20，近 4 周都没有评论
        self.assertEqual(out["latestWeek"], "12/14–12/20")
        self.assertEqual(out["trend"][-1]["reviews"], 0)
        self.assertEqual(out["snaps"][-1]["kpi"]["voices"]["now"], 0)
        self.assertEqual(out["snaps"][-1]["kpi"]["top"]["tag"], "—")
        self.assertEqual(out["fresh"]["lastWeekWithReviews"], "11/2–11/8")
        self.assertEqual(out["fresh"]["reviewGapDays"], 45)
        self.assertEqual(out["monthly"][-1]["month"], "2026-12")
        self.assertEqual(out["monthly"][-1]["reviews"], 0)
        self.assertEqual({m["month"]: m["reviews"] for m in out["monthly"]}["2026-11"], 3)
        self.assertEqual(out["cumulative"]["reviews"], 5)
        self.assertEqual(collections.Counter(x["kind"] for x in out["snaps"][-1]["change"]), collections.Counter({"已解决": 2}))

if __name__ == "__main__":
    unittest.main()
