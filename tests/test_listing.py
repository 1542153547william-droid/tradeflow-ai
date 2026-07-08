"""#2 Listing：inject_keywords 覆盖率检查 + 智能体组合（复用 0.1 模板）。

Run: python -m unittest tests.test_listing
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tradeflow.compose import build_named_agent  # noqa: E402
from tradeflow.tools.listing import LISTING_TOOLS, inject_keywords as _ik  # noqa: E402

inject_keywords = _ik.func


class TestInjectKeywords(unittest.TestCase):
    def test_candidates_sorted_by_volume(self):
        out = inject_keywords(category="手机壳", top_n=3)
        # phone case(50000) > screen protector(20000) > clear(15000)... shockproof(12000)
        self.assertEqual(out["candidates"][0], "phone case")
        self.assertTrue(len(out["candidates"]) <= 3)

    def test_coverage_split(self):
        text = "slim clear phone case with shockproof corners"
        out = inject_keywords(text=text, category="手机壳", top_n=6)
        self.assertIn("phone case", out["covered"])
        self.assertIn("shockproof", out["covered"])
        # 一个没写进去的高优先词应落在 missing
        self.assertIn("screen protector", out["missing"])

    def test_category_filter_isolates_library(self):
        out = inject_keywords(category="背包", top_n=5)
        self.assertIn("travel backpack", out["candidates"])
        self.assertNotIn("phone case", out["candidates"])


class TestListingAgentComposition(unittest.TestCase):
    def test_reuses_template_and_mounts_tools(self):
        agent = build_named_agent("listing", tools=LISTING_TOOLS)
        # 复用 #1 的守门员 + 自己的取词工具
        self.assertIn("compliance_gate", agent.tools)
        self.assertIn("inject_keywords", agent.tools)
        # 人设 + 写作规则拼进了系统提示
        self.assertIn("Listing", agent.system_prompt)
        self.assertIn("三套写作逻辑", agent.system_prompt)


if __name__ == "__main__":
    unittest.main()
