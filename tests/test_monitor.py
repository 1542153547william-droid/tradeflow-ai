"""竞品监控：快照对比纯函数（离线）+ 清单读取 + 注册。

抓取（snapshot_competitors）依赖查询系统服务，不在单测覆盖；对比逻辑 `_diff`
是纯函数，用合成快照脱网测试。
Run: python -m unittest tests.test_monitor
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tradeflow import registry  # noqa: E402
from tradeflow.tools import monitor  # noqa: E402


def _item(price=29.99, rating=4.5, reviews=1000, rank="#12 Patio"):
    return {"标题": "t", "品牌": "b", "价格": price, "评分": rating,
            "评论数": reviews, "排名": rank}


class TestDiff(unittest.TestCase):
    def test_price_drop_alert(self):
        out = monitor._diff({"A1": _item(price=30.0)}, {"A1": _item(price=27.0)})
        self.assertTrue(any("价格变动" in a for a in out["预警"]))   # -10% ≥ 5%

    def test_small_price_change_no_alert(self):
        out = monitor._diff({"A1": _item(price=30.0)}, {"A1": _item(price=29.7)})
        self.assertEqual(out["预警"], [])                            # -1% < 5%
        self.assertTrue(any("价格" in c for c in out["变动"][0]))    # 但记录变动

    def test_review_surge_and_rating_drop(self):
        out = monitor._diff({"A1": _item(reviews=1000, rating=4.5)},
                            {"A1": _item(reviews=1050, rating=4.3)})
        self.assertTrue(any("评论新增" in a for a in out["预警"]))
        self.assertTrue(any("评分下滑" in a for a in out["预警"]))

    def test_new_and_gone(self):
        out = monitor._diff({"OLD": _item()}, {"NEW": _item()})
        self.assertEqual(out["消失"], ["OLD"])
        self.assertTrue(any("没抓到" in a for a in out["预警"]))
        self.assertEqual(out["变动"][0]["变动"], "新加入监控")

    def test_no_change(self):
        out = monitor._diff({"A1": _item()}, {"A1": _item()})
        self.assertEqual(out["变动"], [])
        self.assertEqual(out["预警"], [])


class TestWatchlist(unittest.TestCase):
    def test_list(self):
        out = monitor.list_watchlist.func()
        self.assertGreaterEqual(out["数量"], 1)
        self.assertIn("ASIN", out["清单"][0])


def _prof(price, rating, reviews, bullets, pains):
    return {"标题": "t", "品牌": "b", "价格": price, "评分": rating,
            "评论数": reviews, "排名": "#1", "卖点数": bullets, "图片数": 6,
            "有视频": True, "变体数": 3, "差评占比": 0.2, "痛点词": pains}


class TestCompareCompetitors(unittest.TestCase):
    def setUp(self):
        self.profiles = {
            "COMP1": _prof(29.99, 4.6, 5000, 5, ["not waterproof", "dim light"]),
            "COMP2": _prof(24.99, 4.2, 800, 4, ["not waterproof", "short battery"]),
            "MINE": _prof(32.99, 4.3, 300, 5, []),
        }

    def test_winners(self):
        out = monitor._build_comparison(self.profiles)
        self.assertEqual(out["各维度赢家"]["最低价"]["ASIN"], "COMP2")
        self.assertEqual(out["各维度赢家"]["最高分"]["ASIN"], "COMP1")
        self.assertEqual(out["各维度赢家"]["评论最多"]["ASIN"], "COMP1")

    def test_shared_pain_is_top_opportunity(self):
        out = monitor._build_comparison(self.profiles, my_asin="MINE")
        # "not waterproof" 两个竞品都被骂 → 排第一，且我方痛点不计入
        self.assertEqual(out["差异化机会"][0]["痛点"], "not waterproof")
        self.assertEqual(out["差异化机会"][0]["出现竞品数"], 2)

    def test_my_gaps(self):
        out = monitor._build_comparison(self.profiles, my_asin="MINE")
        gaps = " ".join(out["我方短板"])
        self.assertIn("评分落后", gaps)      # 4.3 < 4.6
        self.assertIn("评论数落后", gaps)    # 300 < 5000
        self.assertIn("价格偏高", gaps)      # 32.99 > 24.99

    def test_empty(self):
        self.assertIn("error", monitor._build_comparison({}))


class TestRegistered(unittest.TestCase):
    def test_in_registry(self):
        self.assertIn("monitor", registry.REGISTRY)
        names = [t.name for t in monitor.MONITOR_TOOLS]
        self.assertIn("snapshot_competitors", names)
        self.assertIn("compare_snapshots", names)
        self.assertIn("compare_competitors", names)


if __name__ == "__main__":
    unittest.main()
