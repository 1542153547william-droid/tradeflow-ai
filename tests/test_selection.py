"""#7 智能选品：calc_gross_margin + score_product(加权/门槛) + 编排接线。

Run: python -m unittest tests.test_selection
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config.settings import settings  # noqa: E402
from tradeflow import registry  # noqa: E402
from tradeflow.tools.selection import (  # noqa: E402
    calc_gross_margin as _cgm, score_product as _sp,
)

calc_gross_margin = _cgm.func
score_product = _sp.func


class TestGrossMargin(unittest.TestCase):
    def test_margin_math(self):
        out = calc_gross_margin("手机壳", 25.99)
        self.assertTrue(out["found"])
        # 固定 2.5+0.8+3.2+0.3=6.8; 佣金 25.99*0.15≈3.90; 损耗 25.99*0.03≈0.78
        self.assertAlmostEqual(out["breakdown"]["固定成本(采购+头程+FBA+包装)"], 6.8, places=2)
        self.assertGreater(out["margin_pct"], 0)      # 该售价应盈利
        self.assertLess(out["margin_pct"], 1)

    def test_unknown_category(self):
        self.assertFalse(calc_gross_margin("不存在类目", 10)["found"])


class TestScoreProduct(unittest.TestCase):
    def test_recommend_high_scores(self):
        out = score_product(85, 75, 80, 90, 70, category="手机壳")
        self.assertTrue(out["passed"])
        self.assertEqual(out["verdict"], "推荐")
        self.assertGreaterEqual(out["total_score"], 70)

    def test_veto_low_margin(self):
        out = score_product(85, 75, 30, 90, 70, category="手机壳")  # 毛利分30<50
        self.assertFalse(out["passed"])
        self.assertEqual(out["verdict"], "淘汰")
        self.assertTrue(out["vetoed_by"])

    def test_veto_banned_category(self):
        out = score_product(90, 90, 90, 90, 90, category="医疗器械")
        self.assertFalse(out["passed"])
        self.assertEqual(out["verdict"], "淘汰")


class TestOrchestrationWiring(unittest.TestCase):
    def setUp(self):
        self._saved = settings.provider
        settings.provider = "mock"

    def tearDown(self):
        settings.provider = self._saved

    def test_selection_agent_mounts_subagents(self):
        agent = registry.build("selection")
        # 自己的工具 + 三个子智能体工具
        for name in ("score_product", "calc_gross_margin",
                     "ask_compliance", "ask_teardown", "ask_market"):
            self.assertIn(name, agent.tools)


if __name__ == "__main__":
    unittest.main()
