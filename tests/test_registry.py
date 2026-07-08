"""智能体注册表 + 编排 (0.2)：build / agent_as_tool(A调B) / run_sequence 流水线。

用 MockProvider（强制 settings.provider=mock），不打真实模型。
Run: python -m unittest tests.test_registry
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config.settings import settings  # noqa: E402
from tradeflow import registry  # noqa: E402


class MockProviderCase(unittest.TestCase):
    """所有编排测试都在 mock provider 下跑，避免真实网络调用。"""

    def setUp(self):
        self._saved = settings.provider
        settings.provider = "mock"

    def tearDown(self):
        settings.provider = self._saved


class TestRegistry(MockProviderCase):
    def test_specs_registered(self):
        names = {s.name for s in registry.list_specs()}
        self.assertEqual(names, {"compliance", "listing", "imagery"})

    def test_build_attaches_right_tools(self):
        agent = registry.build("compliance")
        self.assertIn("compliance_gate", agent.tools)
        self.assertIn("岗位人设", agent.system_prompt)

    def test_unknown_agent_raises(self):
        with self.assertRaises(KeyError):
            registry.get_spec("does-not-exist")


class TestAgentAsTool(MockProviderCase):
    def test_wraps_agent_into_callable_tool(self):
        t = registry.agent_as_tool("compliance")
        self.assertEqual(t.name, "ask_compliance")
        self.assertIn("task", t.parameters["properties"])
        # 真调一次子智能体（mock 下返回回显字符串）
        out = t.func("审一下：the best case")
        self.assertIsInstance(out, str)
        self.assertTrue(out)

    def test_orchestrator_can_mount_subagent_tool(self):
        # #7 式编排：一个上层智能体把 #1 当工具挂上（A 调 B 的接线）
        from tradeflow.compose import build_named_agent
        supervisor = build_named_agent(
            "compliance", tools=[registry.agent_as_tool("imagery")])
        self.assertIn("ask_imagery", supervisor.tools)


class TestPipeline(MockProviderCase):
    def test_run_sequence_chains_agents(self):
        trace = registry.run_sequence(
            [("listing", "写文案："), ("compliance", "审核上面的文案：")],
            initial="手机壳 新品 美国站",
        )
        self.assertEqual([t["agent"] for t in trace], ["listing", "compliance"])
        # 第二步的输入应包含第一步的输出（链路接上了）
        self.assertIn(trace[0]["output"], trace[1]["input"])
        self.assertTrue(trace[-1]["output"])


if __name__ == "__main__":
    unittest.main()
