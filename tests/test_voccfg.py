"""voccfg：数据目录默认值（VOC_DATA_DIR → 现场分析/ → voc-reports/，样例口径时项目根 = skill/ 上一级）和别名归一。"""
import os
import sys
import unittest

import voctest as T

sys.path.insert(0, str(T.SKILL))
import voccfg  # noqa: E402


class DataDirTest(unittest.TestCase):
    def setUp(self):
        self.tmp = T.tmpdir("voccfg")
        self.saved = {k: os.environ.get(k) for k in ("VOC_DATA_DIR", "VOC_CONFIG")}
        for k in self.saved:
            os.environ.pop(k, None)
        voccfg._cache.clear()

    def tearDown(self):
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        voccfg._cache.clear()
        T.rm(self.tmp)

    def test_env_wins(self):
        os.environ["VOC_DATA_DIR"] = str(self.tmp / "elsewhere")
        self.assertEqual(voccfg.data_dir(self.tmp), self.tmp / "elsewhere")

    def test_local_layout(self):
        T.make_config(self.tmp)
        (self.tmp / "现场分析").mkdir()
        self.assertEqual(voccfg.data_dir(self.tmp / "现场分析"), self.tmp / "现场分析")

    def test_public_layout(self):
        T.make_config(self.tmp)
        (self.tmp / "skill").mkdir()
        self.assertEqual(voccfg.data_dir(self.tmp / "skill"), self.tmp / "voc-reports")

    def test_example_config_root(self):
        skill = self.tmp / "skill"
        skill.mkdir()
        (skill / "voc.config.example.json").write_text(T.CONFIG_SRC.read_text(encoding="utf-8"), encoding="utf-8")
        os.environ["VOC_CONFIG"] = str(skill / "voc.config.example.json")
        self.assertEqual(voccfg.data_dir(skill), self.tmp / "voc-reports")


class CanonTest(unittest.TestCase):
    def test_alias_and_stage(self):
        cfg = T.load_config()
        d = {"tagsNeg": ["边角翘起", "边角翘、粘不住"], "tagsPos": ["贴得牢"], "reviews": [{"tags": ["粘不住、会滑动", "柔软舒适"]}],
             "tagStage": {"边角翘起": "安装"}, "problems": [{"name": "边角翘起"}]}
        notes = voccfg.canonicalize(d, cfg)
        self.assertEqual(d["tagsNeg"], ["边角翘、粘不住"])
        self.assertEqual(d["tagsPos"], ["粘得牢"])
        self.assertEqual(d["reviews"][0]["tags"], ["边角翘、粘不住", "脚感软"])
        self.assertEqual(d["tagStage"]["边角翘、粘不住"], "日常使用")        # 词表定的阶段优先于旧阶段
        self.assertEqual(d["problems"][0]["tag"], "边角翘、粘不住")
        self.assertEqual(d["stages"], cfg["stages"]["order"])
        self.assertEqual(notes["notInVocab"], [])
        self.assertIn("边角翘起", notes["aliased"])


if __name__ == "__main__":
    unittest.main()
