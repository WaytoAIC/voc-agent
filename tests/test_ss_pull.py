"""ss_pull.py --merge --new-only 的去重：用 VOC_SS_STUB 离线桩（从样例评论拼出的卖家精灵原始页），不联网。

覆盖：首次并入、重复页全是已有评论就停、旧库压缩 / 截断行按实词重合认同一条并换真原话、新评论排最前、--no-detail、缺页报错、演示数据不并。
"""
import json
import re
import unittest

import voctest as T

ASIN = "B0TEST00001"


def wrap(payload):
    return json.dumps({"result": {"content": [{"text": json.dumps(payload, ensure_ascii=False)}]}}, ensure_ascii=False)


def detail_payload():
    return {"code": "OK", "data": {"asin": ASIN, "parent": "B0TESTPAR01", "brand": "TestBrand", "sellerName": "Seller", "title": "Test stair treads",
                                   "price": 29.99, "rating": 4.3, "ratings": 120, "subcategories": [{"label": "Stair Treads", "rank": 12}],
                                   "availableDate": T.ms(2024, 5, 1), "zoomImageUrl": "https://example.invalid/img.jpg"}}


def items_from_example(n, min_words=12):
    rows = [r for r in T.example_data()["reviews"] if not r.get("vine") and len(r["en"].split()) >= min_words]
    out = []
    for r in rows[:n]:
        out.append({"date": r["t"], "skus": [f"Size: {r['sku']}"] if r.get("sku") else [], "star": r["star"], "verified": True,
                    "title": r.get("title") or "Title " + str(len(out)), "vine": False, "content": r["en"], "likes": 0})
    assert len(out) == n, f"样例里够长的评论不够 {n} 条"
    return out


def stub_dir(tmp, items, name="stub"):
    d = tmp / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "detail.raw.json").write_text(wrap(detail_payload()), encoding="utf-8")
    (d / "reviews-1.raw.json").write_text(wrap({"code": "OK", "data": {"pages": 1, "page": 1, "size": 20, "total": len(items), "items": items}}), encoding="utf-8")
    return d


class SsPullTest(unittest.TestCase):
    def setUp(self):
        self.tmp = T.tmpdir("sspull")
        self.data = self.tmp / "data"
        self.data.mkdir()
        T.make_config(self.tmp)
        self.items = items_from_example(12)
        self.stub = stub_dir(self.tmp, self.items)

    def tearDown(self):
        T.rm(self.tmp)

    def pull(self, *args, stub=None):
        r = T.run([T.PY, T.SS_PULL, ASIN, "--merge", "--json", *args], env=T.env(self.tmp, self.data, VOC_SS_STUB=str(stub or self.stub)), cwd=self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        return T.last_json(r.stdout), r.stderr

    def data_json(self):
        return json.loads((self.data / ASIN / "data.json").read_text(encoding="utf-8"))

    def test_first_merge_then_nothing_new(self):
        j, _ = self.pull("--pages", "3")
        self.assertEqual((j["new"], j["calls"], j["pages"], j["detail"], j["errors"], j["upgraded"]), (12, 2, 1, True, [], 0))
        d = self.data_json()
        self.assertEqual(len(d["reviews"]), 12)
        self.assertEqual([r["t"] for r in d["reviews"]], sorted((r["t"] for r in d["reviews"]), reverse=True))
        self.assertTrue(all(r["zh"] == "" and r["tags"] == [] and "title" in r for r in d["reviews"]))
        p = d["product"]
        self.assertEqual((p["asin"], p["parent"], p["brand"], p["price"], p["rating"], p["ratings"]), (ASIN, "B0TESTPAR01", "TestBrand", 29.99, 4.3, 120))
        self.assertEqual(p["bsr"], "Stair Treads 第 12 名")
        self.assertEqual(p["launched"], "2024-05-01")
        self.assertEqual(d["pulled"]["total"], 12)
        self.assertEqual(d["pulled"]["calls"], 2)
        self.assertEqual(d["pulled"]["lastPull"]["stopped"], "拉完")
        self.assertEqual(sum(d["stars"].values()), 12)
        # 第二次：同一页全是已有评论 → 一条不加（不满一页，停止原因仍是「拉完」）
        j, _ = self.pull("--pages", "3", "--new-only")
        self.assertEqual((j["new"], j["upgraded"], j["pages"], j["calls"]), (0, 0, 1, 2))
        d2 = self.data_json()
        self.assertEqual(len(d2["reviews"]), 12)
        self.assertEqual(d2["pulled"]["lastPull"]["stopped"], "拉完")
        self.assertEqual(d2["pulled"]["calls"], 4)
        self.assertEqual([r["en"] for r in d2["reviews"]], [r["en"] for r in d["reviews"]])

    def test_full_page_of_known_reviews_stops(self):
        """整整一页 20 条都是已有评论：--new-only 第一页就停，不翻第二页，停止原因记下来。"""
        stub20 = stub_dir(self.tmp, items_from_example(20, min_words=1), "stub20")
        j, _ = self.pull("--pages", "1", stub=stub20)
        self.assertEqual((j["new"], j["errors"]), (20, []))
        j, _ = self.pull("--pages", "3", "--new-only", stub=stub20)
        self.assertEqual((j["new"], j["pages"], j["calls"], j["errors"]), (0, 1, 2, []))
        self.assertEqual(self.data_json()["pulled"]["lastPull"]["stopped"], "这一页全是已有评论")

    def test_legacy_rows_upgraded_not_duplicated(self):
        """旧库里 Agent 手工压缩过的行：没有 title、原话截断、时间戳差 1 小时跨天 → 认作同一条，换真原话、补 title，tags / id 不动。"""
        self.pull("--pages", "1")
        d = self.data_json()
        legacy_idx = [0, 3, 7]
        for i in legacy_idx:
            r = d["reviews"][i]
            r["en"] = " ".join(r["en"].split()[:8])                        # 短于 160 字，精确键对不上，只能靠实词重合认
            del r["title"]
            r["t"] = r["t"] + 3600 * 1000
            r["tags"] = ["好看"]
            r["zh"] = "旧中文"
            r["id"] = f"R-{ASIN}-{i:03d}"
        (self.data / ASIN / "data.json").write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        j, _ = self.pull("--pages", "2", "--new-only")
        self.assertEqual((j["new"], j["upgraded"]), (0, 3))
        d2 = self.data_json()
        self.assertEqual(len(d2["reviews"]), 12)
        full = {it["content"] for it in self.items}
        for r in d2["reviews"]:
            self.assertIn(r["en"], full)
            self.assertIn("title", r)
        for i in legacy_idx:
            r = d2["reviews"][i]
            self.assertEqual((r["tags"], r["zh"], r["id"]), (["好看"], "旧中文", f"R-{ASIN}-{i:03d}"))
        self.assertEqual(d2["pulled"]["lastPull"]["upgraded"], 3)

    def test_new_review_goes_first(self):
        self.pull("--pages", "1")
        extra = {"date": T.ms(2026, 11, 1), "skus": ["Color: Grey"], "star": 1, "verified": True, "title": "Peeled off", "vine": False,
                 "content": "They peeled right off the stairs after one week and the dog slid down.", "likes": 0}
        stub2 = stub_dir(self.tmp, [extra] + self.items, "stub2")
        j, _ = self.pull("--pages", "2", "--new-only", stub=stub2)
        self.assertEqual((j["new"], j["upgraded"]), (1, 0))
        d = self.data_json()
        self.assertEqual(len(d["reviews"]), 13)
        self.assertEqual(d["reviews"][0]["en"], extra["content"])
        self.assertEqual((d["reviews"][0]["sku"], d["reviews"][0]["star"], d["reviews"][0]["tags"], d["reviews"][0]["zh"]), ("Grey", 1, [], ""))
        self.assertEqual(d["pulled"]["lastPull"]["new"], 1)

    def test_no_detail_and_missing_page(self):
        j, _ = self.pull("--pages", "1", "--no-detail")
        self.assertEqual((j["calls"], j["detail"]), (1, False))
        self.assertNotIn("brand", self.data_json()["product"])
        # 整整 20 条一页且 --pages 2：第二页桩文件不存在 → errors 里记下来，第一页照样并入
        stub20 = stub_dir(self.tmp, items_from_example(20, min_words=1), "stub20")
        j, _ = self.pull("--pages", "2", stub=stub20)
        self.assertEqual(j["errors"], ["reviews-2.raw.json"])
        self.assertEqual(j["pages"], 1)
        self.assertEqual(len(self.data_json()["reviews"]), 20)

    def test_demo_data_untouched(self):
        p = self.data / ASIN / "data.json"
        p.parent.mkdir(parents=True)
        demo = {"demo": True, "product": {"asin": ASIN}, "pulled": {"source": "演示数据"}, "stars": {}, "reviews": [], "events": [], "tagsNeg": [], "tagsPos": [], "problems": [], "praises": []}
        p.write_text(json.dumps(demo, ensure_ascii=False), encoding="utf-8")
        j, err = self.pull("--pages", "1")
        self.assertEqual(j["new"], 0)
        self.assertIn("演示数据", err)
        self.assertEqual(json.loads(p.read_text(encoding="utf-8"))["reviews"], [])

    def test_stub_shape_matches_real_cache(self):
        """桩文件的外形 = 卖家精灵原始返回（result.content[0].text 里再套一层 JSON），真缓存页在本机时顺手比一下键。"""
        raw = json.loads((self.stub / "reviews-1.raw.json").read_text(encoding="utf-8"))
        inner = json.loads(raw["result"]["content"][0]["text"])
        self.assertEqual(set(inner["data"]), {"pages", "page", "size", "total", "items"})
        real = sorted(T.SKILL.glob("*/_raw/reviews-1.raw.json"))
        if real:
            r = json.loads(json.loads(real[0].read_text(encoding="utf-8"))["result"]["content"][0]["text"])
            self.assertTrue(set(inner["data"]) <= set(r["data"]))
            self.assertTrue({"date", "star", "content", "skus", "vine", "verified", "title"} <= set(r["data"]["items"][0]))
            self.assertTrue(re.fullmatch(r"B0[A-Z0-9]{8}", real[0].parent.parent.name))


if __name__ == "__main__":
    unittest.main()
