"""#6 市场分析：竞争强度指标(纯函数) + 市场数据查表 + 注册/组合。

竞争指标用合成数据脱网测试；不依赖运行中的 query-system。
Run: python -m unittest tests.test_market
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tradeflow import registry  # noqa: E402
from tradeflow.tools.market import (  # noqa: E402
    MARKET_TOOLS, _competition_metrics,
    parse_keyword_market_data as _pkmd,
)

parse_keyword_market_data = _pkmd.func


def _p(review, price, rating, brand):
    return {"base_info": {"review_count": review, "rating": rating, "brand": brand},
            "pricing": {"price": price}}


class TestCompetitionMetrics(unittest.TestCase):
    def test_metrics_from_sample(self):
        products = [
            _p(9000, 30, 4.6, "A"), _p(600, 25, 4.4, "B"), _p(400, 20, 4.2, "C"),
            _p(100, 15, 4.0, "D"), _p(50, 12, 3.8, "E"),
        ]
        m = _competition_metrics(products)
        self.assertEqual(m["sample_size"], 5)
        self.assertEqual(m["brand_count"], 5)
        self.assertEqual(m["review_max"], 9000)
        # 头部前3占比应为多数（9000+600+400)/10150 ≈ 0.98
        self.assertGreater(m["head_concentration_top3"], 0.9)
        self.assertEqual(m["price"]["min"], 12)
        self.assertEqual(m["price"]["max"], 30)

    def test_empty_sample_safe(self):
        self.assertEqual(_competition_metrics([])["sample_size"], 0)


class TestKeywordMarketData(unittest.TestCase):
    def test_lookup_hit(self):
        out = parse_keyword_market_data("phone case")
        self.assertTrue(out["found"])
        self.assertEqual(out["竞争度"], "高")

    def test_lookup_miss(self):
        self.assertFalse(parse_keyword_market_data("绝无此词xyz")["found"])


class TestMarketRegistered(unittest.TestCase):
    def test_registered_and_reuses_risk(self):
        self.assertIn("market", registry.REGISTRY)
        names = [t.name for t in MARKET_TOOLS]
        self.assertIn("flag_category_risk", names)   # 复用 #1
        self.assertIn("assess_competition", names)


if __name__ == "__main__":
    unittest.main()
