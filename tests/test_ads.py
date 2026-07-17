"""#4 广告优化：聚合/盈亏线/三分类/调价建议/否定词导出 + 注册。

golden set 用仓库里的脱敏样例（data/ads/*_样例.csv）；本机若有 *_真实.* 文件，
测试通过覆盖探测顺序强制走样例，保证跨机器确定性。
Run: python -m unittest tests.test_ads
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tradeflow import registry  # noqa: E402
from tradeflow.tools import ads  # noqa: E402

SAMPLE = "搜索词报告_样例.csv"


def setUpModule():
    # 强制样例数据（真实文件只在本机存在且被 gitignore）。
    ads._orig = (ads._AD_REPORTS, ads._SETTLE_REPORTS, ads._MAPPING_FILES)
    ads._AD_REPORTS = (SAMPLE,)
    ads._SETTLE_REPORTS = ("结算报告_样例.csv",)
    ads._MAPPING_FILES = ("广告活动映射.csv",)
    ads.reset_caches()


def tearDownModule():
    ads._AD_REPORTS, ads._SETTLE_REPORTS, ads._MAPPING_FILES = ads._orig
    ads.reset_caches()


class TestNum(unittest.TestCase):
    def test_edge_values(self):
        for raw, want in [("", 0.0), (None, 0.0), ("-", 0.0),
                          ("0.5", 0.5), (3, 3.0)]:
            self.assertEqual(ads._num(raw), want)


class TestAggregation(unittest.TestCase):
    def test_cross_day_merge(self):
        terms = {t["搜索词"]: t for t in ads._aggregated_terms(SAMPLE)}
        good = terms["solar torch lights outdoor"]     # 3 天合并
        self.assertEqual(good["点击"], 30)
        self.assertEqual(good["订单"], 6)
        self.assertAlmostEqual(good["花费"], 24.7, places=2)
        self.assertAlmostEqual(good["ACOS"], 24.7 / 223.93, places=3)

    def test_zero_sales_acos_is_none(self):
        terms = {t["搜索词"]: t for t in ads._aggregated_terms(SAMPLE)}
        self.assertIsNone(terms["christmas lights indoor"]["ACOS"])


class TestBreakeven(unittest.TestCase):
    def test_settlement_orders_only(self):
        stats = ads._sku_stats()["SAMPLE-TORCH-4P"]
        # Refund/Adjustment 行不计：qty=3, sales=95.97, net=57.97
        self.assertEqual(stats["销量"], 3)
        self.assertAlmostEqual(stats["销售额"], 95.97, places=2)
        self.assertAlmostEqual(stats["回款率"], 57.97 / 95.97, places=3)

    def test_true_breakeven_with_cost(self):
        be, basis = ads._breakeven("SAMPLE-TORCH-4P")
        # 回款率 60.4% − 货成本 8.5/31.99=26.6% ≈ 33.8%
        self.assertAlmostEqual(be, 57.97 / 95.97 - 8.5 / 31.99, places=3)
        self.assertIn("真实盈亏线", basis)

    def test_fallback_default(self):
        be, basis = ads._breakeven("NO-SUCH-SKU")
        self.assertAlmostEqual(be, ads._rule("默认盈亏ACOS", 0.30), places=4)
        self.assertIn("默认", basis)


class TestClassification(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        result = ads.classify_search_terms.func(report=SAMPLE)
        cls.by_term = {t["搜索词"]: k
                       for k, rows in result["分类"].items() for t in rows}

    def test_three_way(self):
        self.assertEqual(self.by_term["solar torch lights outdoor"], "好词")
        self.assertEqual(self.by_term["outdoor string lights waterproof"], "好词")
        self.assertEqual(self.by_term["christmas lights indoor"], "垃圾词")   # 零转化
        self.assertEqual(self.by_term["solar string lights"], "垃圾词")       # ACOS 超线
        self.assertEqual(self.by_term["flickering flame torch garden waterproof"],
                         "潜力长尾词")
        self.assertEqual(self.by_term["tiki torch replacement canister"], "观察")


class TestActionsAndExport(unittest.TestCase):
    def test_bid_actions(self):
        acts = {a["搜索词"]: a
                for a in ads.suggest_bid_actions.func(report=SAMPLE)["动作清单"]}
        garbage = acts["christmas lights indoor"]
        self.assertEqual(garbage["动作"], "加否定（精准）")
        good = acts["solar torch lights outdoor"]
        self.assertIn("加价", good["动作"])
        self.assertAlmostEqual(good["建议竞价"],
                               round(good["参考CPC"] * 1.10, 2), places=2)

    def test_export_negatives(self):
        out = ads.export_negative_keywords.func(report=SAMPLE)
        self.assertEqual(out["条数"], 2)
        path = Path(out["文件"])
        try:
            text = path.read_text(encoding="utf-8-sig")
            self.assertIn("Negative Exact", text)
            self.assertIn("christmas lights indoor", text)
        finally:
            path.unlink(missing_ok=True)


class TestRegistered(unittest.TestCase):
    def test_in_registry(self):
        self.assertIn("ads", registry.REGISTRY)
        names = [t.name for t in ads.ADS_TOOLS]
        self.assertIn("classify_search_terms", names)
        self.assertIn("export_negative_keywords", names)


if __name__ == "__main__":
    unittest.main()
