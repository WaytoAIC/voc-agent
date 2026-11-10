"""飞书 .base 模板：仓里的模板能解码、三张表齐全、选项 = voc.config.json 词表、不含真实 ID；从模板再生成一次结果一致；口径变了 check 会报。"""
import copy
import json
import sys
import unittest

import voctest as T

sys.path.insert(0, str(T.WB))
import base_template as bt  # noqa: E402
import voccfg  # noqa: E402


@unittest.skipIf(T.TEMPLATE_DIR is None, "仓里没有飞书模板")
class BaseTemplateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = T.tmpdir("base")
        self.cfg = copy.deepcopy(voccfg.load(T.TEMPLATE_DIR))

    def tearDown(self):
        T.rm(self.tmp)

    def test_shipped_template_is_consistent(self):
        self.assertEqual(bt.check(self.cfg, T.TEMPLATE_DIR), [])
        j, snap = bt.decode(T.TEMPLATE_DIR / bt.FILE)
        self.assertEqual(j["sign"], "")
        rows = bt.field_rows(snap)
        self.assertEqual(set(rows), set(bt.ROLE_IDS.values()))
        names = self.cfg["feishu"]["table_names"]
        self.assertEqual({rows[t]["name"] for t in rows}, set(names.values()))
        ev = {f["name"]: f for f in rows["tbl_events"]["fields"]}
        self.assertEqual(ev["阶段"]["options"], self.cfg["stages"]["order"])
        self.assertEqual(ev["问题分类"]["options"], [t for t in self.cfg["tags"]["neg"] if not t.startswith("_")] + [t for t in self.cfg["tags"]["pos"] if not t.startswith("_")])
        self.assertEqual(ev["该谁改"]["options"], self.cfg["owners"]["list"])
        self.assertTrue(ev["事件ID"]["primary"])
        ac = {f["name"]: f for f in rows["tbl_actions"]["fields"]}
        self.assertEqual(ac["状态"]["options"], self.cfg["actions"]["status"])
        self.assertEqual(ac["AI判断"]["options"], self.cfg["actions"]["judgement"])
        self.assertEqual(ac["责任人"]["type"], "User")
        self.assertEqual(ac["验证日期"]["type"], "DateTime")
        rd = {f["name"]: f for f in rows["tbl_reddit"]["fields"]}
        self.assertEqual(rd["好评"]["options"], [t for t in self.cfg["tags"]["pos"] if not t.startswith("_")])
        for item in snap:
            b = item["schema"]["base"]
            self.assertEqual((b["token"], b["tenantID"], b["id"], item["schema"]["owner"]), ("", 0, 0, "0"))
        schema = json.loads((T.TEMPLATE_DIR / bt.SCHEMA).read_text(encoding="utf-8"))
        self.assertEqual([t["role"] for t in schema["tables"]], ["events", "actions", "reddit"])
        self.assertEqual([len(t["fields"]) for t in schema["tables"]], [len(rows[bt.ROLE_IDS[t["role"]]]["fields"]) for t in schema["tables"]])
        self.assertIn("lark-cli drive +import", schema["import"])

    def test_rebuild_from_template_is_idempotent(self):
        out = bt.build(T.TEMPLATE_DIR / bt.FILE, self.cfg, self.tmp)
        self.assertEqual(bt.check(self.cfg, self.tmp), [])
        _, a = bt.decode(T.TEMPLATE_DIR / bt.FILE)
        _, b = bt.decode(out)
        self.assertEqual(bt.field_rows(a), bt.field_rows(b))
        self.assertEqual(json.loads((self.tmp / bt.SCHEMA).read_text(encoding="utf-8"))["tables"],
                         json.loads((T.TEMPLATE_DIR / bt.SCHEMA).read_text(encoding="utf-8"))["tables"])

    def test_check_catches_vocab_drift(self):
        cfg = copy.deepcopy(self.cfg)
        cfg["tags"]["neg"]["新问题"] = "日常使用"
        errs = bt.check(cfg, T.TEMPLATE_DIR)
        self.assertTrue(any("events.问题分类" in e for e in errs), errs)
        out = bt.build(T.TEMPLATE_DIR / bt.FILE, cfg, self.tmp)             # 用新口径重建就过了
        self.assertEqual(bt.check(cfg, self.tmp), [])
        _, snap = bt.decode(out)
        ev = {f["name"]: f for f in bt.field_rows(snap)["tbl_events"]["fields"]}
        self.assertIn("新问题", ev["问题分类"]["options"])

    def test_check_catches_real_ids(self):
        j, snap = bt.decode(T.TEMPLATE_DIR / bt.FILE)
        snap[0]["schema"]["base"]["token"] = "FAKE_BASE_TOKEN_000"
        (self.tmp / bt.FILE).write_text(bt.encode(j, snap), encoding="utf-8")
        (self.tmp / bt.SCHEMA).write_text((T.TEMPLATE_DIR / bt.SCHEMA).read_text(encoding="utf-8"), encoding="utf-8")
        errs = bt.check(self.cfg, self.tmp)
        self.assertTrue(any("token" in e for e in errs), errs)


if __name__ == "__main__":
    unittest.main()
