"""#3 图文视频：check_image_rules 规范校验 + 智能体组合（复用 0.1 模板）。

Run: python -m unittest tests.test_imagery
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tradeflow.compose import build_named_agent  # noqa: E402
from tradeflow.tools.imagery import IMAGERY_TOOLS, check_image_rules as _cir  # noqa: E402

check_image_rules = _cir.func


class TestCheckImageRules(unittest.TestCase):
    def test_main_image_flags_watermark_text(self):
        out = check_image_rules("白底，产品居中，右下角加了促销文字 50% OFF", "main")
        self.assertFalse(out["passed"])
        rules = {v["规则"] for v in out["violations"]}
        self.assertIn("无文字水印", rules)

    def test_clean_main_image_passes(self):
        out = check_image_rules("纯白背景，产品居中完整，高清", "main")
        self.assertTrue(out["passed"], msg=f"应通过: {out}")

    def test_checklist_scoped_by_type(self):
        # 主图应含"纯白背景"规则；场景图不应含它，但应含"真实场景"。
        main = check_image_rules("产品图", "main")
        scene = check_image_rules("使用场景图", "scene")
        main_rules = " ".join(main["checklist"])
        scene_rules = " ".join(scene["checklist"])
        self.assertIn("纯白背景", main_rules)
        self.assertNotIn("纯白背景", scene_rules)
        self.assertIn("真实场景", scene_rules)


class TestImageryAgentComposition(unittest.TestCase):
    def test_reuses_template_and_mounts_tools(self):
        agent = build_named_agent("imagery", tools=IMAGERY_TOOLS)
        self.assertIn("check_image_rules", agent.tools)
        self.assertIn("compliance_gate", agent.tools)   # 复用 #1
        self.assertIn("短视频脚本", agent.system_prompt)


if __name__ == "__main__":
    unittest.main()
