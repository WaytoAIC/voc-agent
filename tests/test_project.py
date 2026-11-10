"""project.py --check：脱敏投影的不变量核对，全走改写缓存，不调模型。

临时目录里自建「真实」种子（假 ASIN、假品牌）+ 改写缓存，核对：条数 = 真实 × k、分布一致、敏感词 / 原话重合 / 变体雷同会被拦下、--dry-run 缺缓存时不写文件。
"""
import json
import re
import unittest

import voctest as T

REAL, ALIAS, K = "B0REAL00001", "B0ALIAS0001", 2


def norm(s):
    return re.sub(r"\s+", " ", re.sub(r"<br\s*/?>", " ", s or "")).strip().lower()


def src_key(r):
    return f"{int(r['t'])}|{int(r['star'])}|{norm(r['en'])[:160]}"


class ProjectTest(unittest.TestCase):
    def setUp(self):
        self.tmp = T.tmpdir("project")
        self.data = self.tmp / "data"
        self.real_dir = self.data / "_real" / REAL
        self.real_dir.mkdir(parents=True)
        self.priv = self.data / "_real" / "projection.json"
        self.priv.write_text(json.dumps({"real": REAL, "alias": ALIAS, "k": K, "dateShiftDays": -7, "seed": "test",
                                         "product": {"brand": "演示品牌", "name": "演示踏板", "title": "Demo stair treads", "parent": ALIAS},
                                         "skuMap": {}, "banned": ["RealBrand", "RealStore"]}, ensure_ascii=False), encoding="utf-8")
        T.make_config(self.tmp, own=ALIAS, projection={"enabled": True, "private": str(self.priv)})
        self.reviews = [
            {"star": 5, "t": T.ms(2026, 10, 6), "sku": "Beige · 15", "vine": False, "verified": True, "title": "Great", "en": "Dog stopped slipping.", "zh": "狗不滑了", "tags": ["宠物不再打滑"]},
            {"star": 2, "t": T.ms(2026, 10, 8), "sku": "Grey · 15", "vine": False, "verified": True, "title": "Peeled", "en": "Corners peeled up fast.", "zh": "边角翘", "tags": ["边角翘、粘不住"]},
            {"star": 4, "t": T.ms(2026, 10, 14), "sku": "Beige · 15", "vine": False, "verified": True, "title": "Nice", "en": "Looks nice on stairs.", "zh": "好看", "tags": ["好看"]},
            {"star": 5, "t": T.ms(2026, 10, 15), "sku": "Beige · 15", "vine": True, "verified": False, "title": "Vine", "en": "Free sample, works.", "zh": "送测", "tags": []},
        ]
        self.events = [{"type": "退货", "date": "2026-10-10", "sku": "Grey · 15", "code": "不想要", "real": "颜色偏差", "hasNote": True, "note": "too dark", "qty": 1, "id": "e1"},
                       {"type": "退货", "date": "2026-10-12", "sku": "Beige · 15", "code": "与描述不符", "real": "尺寸偏小", "hasNote": False, "qty": 1, "id": "e2"}]
        real = {"role": "自家", "product": {"asin": REAL, "brand": "RealBrand", "title": "RealBrand treads", "price": 25.0, "rating": 4.4, "ratings": 60, "launched": "2025-01-10"},
                "pulled": {"at": "2026-11-01 09:00", "source": "卖家精灵", "lastPull": {"new": 1}}, "stars": {}, "reviews": self.reviews, "events": self.events,
                "tagsNeg": ["边角翘、粘不住"], "tagsPos": ["宠物不再打滑", "好看"], "problems": [], "praises": [], "summary": "", "insight": ""}
        (self.real_dir / "data.json").write_text(json.dumps(real, ensure_ascii=False), encoding="utf-8")
        self.cache = {}
        for i, r in enumerate(self.reviews):
            self.cache[src_key(r)] = {"at": "2026-11-01", "variants": [{"title": f"v{i}a", "en": f"variant {i} alpha text", "zh": f"变体{i}a"},
                                                                       {"title": f"v{i}b", "en": f"variant {i} beta words", "zh": f"变体{i}b"}]}
        self.write_cache()
        self.env = T.env(self.tmp, self.data, VOC_PROJECTION=str(self.priv))

    def tearDown(self):
        T.rm(self.tmp)

    def write_cache(self):
        (self.real_dir / "_projection_cache.json").write_text(json.dumps(self.cache, ensure_ascii=False), encoding="utf-8")

    def project(self, *args):
        r = T.run([T.PY, T.PROJECT, "--check", "--json", *args], env=self.env, cwd=self.tmp)
        return r.returncode, T.last_json(r.stdout), r.stderr + r.stdout

    def out(self):
        return json.loads((self.data / ALIAS / "data.json").read_text(encoding="utf-8"))

    def test_projection_passes_check(self):
        rc, j, log = self.project()
        self.assertEqual(rc, 0, log)
        self.assertEqual({k: j[k] for k in ("alias", "k", "realReviews", "variants", "paraphrased", "cached", "events", "leaks", "drift", "errors")},
                         {"alias": ALIAS, "k": K, "realReviews": 4, "variants": 8, "paraphrased": 0, "cached": 4, "events": 4, "leaks": [], "drift": [], "errors": []})
        self.assertIn("核对通过", log)
        d = self.out()
        self.assertEqual(len(d["reviews"]), 8)
        self.assertEqual(len(d["events"]), 4)
        self.assertEqual(d["product"]["asin"], ALIAS)
        self.assertEqual((d["product"]["brand"], d["product"]["name"], d["product"]["ratings"], d["product"]["launched"]), ("演示品牌", "演示踏板", 120, "2025-01-03"))
        self.assertEqual(d["product"]["note"], "真实产品数据，经脱敏与等比扩增至类目中位规模")
        text = json.dumps(d, ensure_ascii=False)
        for bad in (REAL, "RealBrand", "RealStore", "Dog stopped slipping", "Corners peeled"):   # 「too dark」不足 3 词，按规则直传
            self.assertNotIn(bad, text)
        self.assertEqual(sorted(d["stars"].items()), [("2", 2), ("4", 2), ("5", 4)])
        self.assertEqual(sum(1 for r in d["reviews"] if r["vine"]), 2)
        self.assertEqual({r["sku"] for r in d["reviews"]}, {"米色 · 15 片", "灰色 · 15 片"})
        self.assertEqual(set(d["product"]["variants"]), {"灰色 · 15 片", "米色 · 15 片"})
        self.assertEqual(sum(1 for r in d["reviews"] if "边角翘、粘不住" in r["tags"]), 2)
        self.assertTrue(all(r["tagger"].startswith("project.py@") for r in d["reviews"]))
        pj = d["projection"]
        self.assertEqual((pj["k"], pj["realReviews"], pj["realEvents"], sum(pj["realByWeek"].values())), (K, 4, 2, 4))
        self.assertEqual(sorted(e["real"] for e in d["events"]), ["尺寸偏小", "尺寸偏小", "颜色偏差", "颜色偏差"])
        self.assertTrue(all(re.fullmatch(r"[0-9a-f]{12}", e["id"]) for e in d["events"]))
        self.assertEqual(len({e["id"] for e in d["events"]}), 4)
        self.assertEqual(sorted(e.get("note", "") for e in d["events"] if e["type"] == "退货" and e["hasNote"]), ["too dark", "too dark"])   # 不足 3 词的备注直传
        self.assertEqual(d["pulled"]["source"], "真实数据投影（脱敏 + 等比扩增）")
        self.assertTrue((self.real_dir / "_projection_map.json").exists())
        # 同样的种子再投一次：结果一模一样（确定性）
        rc2, j2, _ = self.project()
        self.assertEqual(rc2, 0)
        d2 = self.out()
        self.assertEqual([(r["t"], r["en"]) for r in d2["reviews"]], [(r["t"], r["en"]) for r in d["reviews"]])
        self.assertEqual([e["id"] for e in d2["events"]], [e["id"] for e in d["events"]])

    def test_leak_banned_word(self):
        key = src_key(self.reviews[0])
        self.cache[key]["variants"][0]["en"] = "RealBrand treads are great"
        self.write_cache()
        rc, j, log = self.project()
        self.assertEqual(rc, 2, log)
        self.assertTrue(any("RealBrand" in x for x in j["leaks"]), j)
        self.assertIn("核对不过", log)

    def test_leak_duplicate_variant(self):
        self.cache[src_key(self.reviews[1])]["variants"][1]["en"] = "variant 0 alpha text"
        self.write_cache()
        rc, j, _ = self.project()
        self.assertEqual(rc, 2)
        self.assertTrue(any("一模一样" in x for x in j["leaks"]), j)

    def test_leak_eight_word_overlap(self):
        long_review = dict(self.reviews[2], en="These treads keep my old dog from sliding down the hardwood stairs every single morning.")
        real = json.loads((self.real_dir / "data.json").read_text(encoding="utf-8"))
        real["reviews"][2] = long_review
        (self.real_dir / "data.json").write_text(json.dumps(real, ensure_ascii=False), encoding="utf-8")
        self.cache.pop(src_key(self.reviews[2]))
        self.cache[src_key(long_review)] = {"at": "x", "variants": [{"title": "a", "en": "Keep my old dog from sliding down the hardwood stairs at night.", "zh": "a"},
                                                                     {"title": "b", "en": "Senior pup no longer skids on the steps.", "zh": "b"}]}
        self.write_cache()
        rc, j, _ = self.project()
        self.assertEqual(rc, 2)
        self.assertTrue(any("连续 8 词重合" in x for x in j["leaks"]), j)

    def test_dry_run_without_cache_writes_nothing(self):
        self.cache.pop(src_key(self.reviews[0]))
        self.write_cache()
        rc, j, log = self.project("--dry-run")
        self.assertEqual(rc, 0, log)
        self.assertIn("需要改写", log)
        self.assertFalse((self.data / ALIAS / "data.json").exists())
        self.assertEqual(j["cached"], 3)


if __name__ == "__main__":
    unittest.main()
