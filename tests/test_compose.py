"""智能体组合机制 (0.1) 测试：人设 + skills 拼进系统提示，工具挂载。

Run: python -m unittest tests.test_compose
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tradeflow.compose import (  # noqa: E402
    build_named_agent, compose_system_prompt, load_persona, load_skills,
)
from tradeflow.prompts import BASE_SYSTEM_PROMPT  # noqa: E402
from tradeflow.tools.compliance import COMPLIANCE_TOOLS  # noqa: E402


class TestCompose(unittest.TestCase):
    def test_compliance_persona_and_skills_present(self):
        self.assertIn("合规风控", load_persona("compliance"))
        self.assertIn("风险分级", load_skills("compliance"))

    def test_system_prompt_layers_base_persona_skills(self):
        sp = compose_system_prompt("compliance")
        self.assertIn(BASE_SYSTEM_PROMPT.strip()[:20], sp)   # BASE 在
        self.assertIn("岗位人设", sp)                          # 人设段在
        self.assertIn("判断规则与 SOP", sp)                    # skills 段在

    def test_unknown_agent_falls_back_to_base_only(self):
        sp = compose_system_prompt("does-not-exist")
        self.assertIn(BASE_SYSTEM_PROMPT.strip()[:20], sp)
        self.assertNotIn("岗位人设", sp)

    def test_build_named_agent_attaches_tools(self):
        agent = build_named_agent("compliance", tools=COMPLIANCE_TOOLS)
        self.assertIn("compliance_gate", agent.tools)
        self.assertIn("岗位人设", agent.system_prompt)


if __name__ == "__main__":
    unittest.main()
