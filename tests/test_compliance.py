"""#1 合规风控：IP/品牌匹配、类目风险、白名单、统一入口 compliance_gate 的测试。

Run: python -m unittest tests.test_compliance
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tradeflow.tools import compliance as C  # noqa: E402

# @tool 包成 Tool 对象；测试直接调底层 .func 拿结构化结果。
match_ip = C.match_ip_brand_patent.func
flag_risk = C.flag_category_risk.func
gate = C.compliance_gate.func


class TestIPMatch(unittest.TestCase):
    def test_flags_trademark(self):
        out = match_ip("wireless AirPods case cover")
        self.assertFalse(out["passed"])
        self.assertEqual(out["violations"][0]["词"], "AirPods")

    def test_clean_passes(self):
        self.assertTrue(match_ip("wireless earbuds case cover")["passed"])


class TestCategoryRisk(unittest.TestCase):
    def test_high_risk_category(self):
        out = flag_risk("医疗器械 手持仪")
        self.assertTrue(out["matched"])
        self.assertEqual(out["risk_level"], "高")

    def test_unknown_category_defaults_low(self):
        out = flag_risk("普通桌面摆件")
        self.assertFalse(out["matched"])
        self.assertEqual(out["risk_level"], "低")


class TestComplianceGate(unittest.TestCase):
    def test_combines_forbidden_and_ip(self):
        out = gate(text="the best AirPods clone", category="", site="US")
        self.assertFalse(out["passed"])
        terms = {v["词"] for v in out["violations"]}
        self.assertIn("best", terms)       # 禁词
        self.assertIn("AirPods", terms)    # IP

    def test_whitelist_overrides_brand_word(self):
        # "BestNest" 是自有品牌（白名单），其中的 "best" 应被放行。
        out = gate(text="BestNest durable phone case", site="US")
        self.assertTrue(out["passed"], msg=f"应被白名单放行: {out}")
        self.assertTrue(any(v["词"] == "best" for v in out["overridden"]))

    def test_category_risk_is_informational_not_block(self):
        # 只给高风险类目、文案干净 → passed 仍为 True，但带 category_risk 预警。
        out = gate(text="durable phone case", category="化妆品", site="US")
        self.assertTrue(out["passed"])
        self.assertEqual(out["category_risk"]["risk_level"], "高")


if __name__ == "__main__":
    unittest.main()
