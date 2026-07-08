"""#5 爆款拆解：list_hot_asins + classify_operation_mode + 注册/组合。

Run: python -m unittest tests.test_teardown
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tradeflow import registry  # noqa: E402
from tradeflow.tools.teardown import (  # noqa: E402
    TEARDOWN_TOOLS, classify_operation_mode as _com, list_hot_asins as _lha,
)

classify_operation_mode = _com.func
list_hot_asins = _lha.func


class TestHotAsins(unittest.TestCase):
    def test_filters_by_category(self):
        out = list_hot_asins("手机壳")
        asins = [a["asin"] for a in out["asins"]]
        self.assertIn("B0HOT0CASE1", asins)
        self.assertNotIn("B0HOT0BAG01", asins)   # 背包不应混入


class TestOperationMode(unittest.TestCase):
    def test_refined_profile(self):
        out = classify_operation_mode(review_count=1200, image_count=8,
                                      has_video=True, variant_count=3, rating=4.6)
        self.assertEqual(out["mode"], "精品")

    def test_volume_profile(self):
        out = classify_operation_mode(review_count=30, image_count=3,
                                      has_video=False, variant_count=8, rating=4.0)
        self.assertEqual(out["mode"], "铺货")

    def test_standard_middle(self):
        out = classify_operation_mode(review_count=300, image_count=5,
                                      has_video=False, variant_count=3, rating=4.2)
        self.assertEqual(out["mode"], "标品")


class TestTeardownRegistered(unittest.TestCase):
    def test_registered_and_wires_tools(self):
        self.assertIn("teardown", registry.REGISTRY)
        names = [t.name for t in TEARDOWN_TOOLS]
        self.assertIn("get_product_by_asin", names)   # 复用 0.5
        self.assertIn("classify_operation_mode", names)


if __name__ == "__main__":
    unittest.main()
