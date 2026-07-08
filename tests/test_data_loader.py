"""数据加载层 (0.3) + #1 合规首个垂直切片的测试。

含一个 golden-set 回归（tests/golden/compliance.jsonl）：换模型/改 prompt/改
禁词表后一键跑，保证"必拦/必放行"不退化（G1）。
Run: python -m pytest tests/test_data_loader.py
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tradeflow.data_loader import DataError, load_data  # noqa: E402
from tradeflow.tools.compliance import check_forbidden_words as _cfw_tool  # noqa: E402

# @tool 把函数包成 Tool 对象；测试里直接调底层函数拿结构化结果。
check_forbidden_words = _cfw_tool.func

GOLDEN = Path(__file__).resolve().parent / "golden" / "compliance.jsonl"


class TestDataLoader(unittest.TestCase):
    def test_reads_forbidden_csv_as_rows(self):
        rows = load_data("compliance", "禁词表_US.csv")
        self.assertIsInstance(rows, list)
        self.assertTrue(rows and isinstance(rows[0], dict))
        # BOM 应被 utf-8-sig 去掉：第一列表头是干净的 "违规词"
        self.assertIn("违规词", rows[0])

    def test_missing_file_returns_empty_not_crash(self):
        self.assertEqual(load_data("compliance", "不存在的表.csv"), [])
        self.assertEqual(load_data("compliance", "缺.md"), "")

    def test_required_columns_missing_raises(self):
        with self.assertRaises(DataError):
            load_data("compliance", "禁词表_US.csv",
                      required_columns=["违规词", "不存在的列"])

    def test_name_without_extension_is_probed(self):
        rows = load_data("compliance", "禁词表_US")  # 无扩展名
        self.assertTrue(rows)


class TestComplianceTool(unittest.TestCase):
    def test_flags_with_position_and_replacement(self):
        out = check_forbidden_words("the best case", site="US")
        self.assertFalse(out["passed"])
        hit = out["violations"][0]
        self.assertEqual(hit["词"], "best")
        self.assertEqual(hit["位置"], 4)          # 'best' 在索引 4
        self.assertTrue(hit["合规替代"])           # 表里给了替代表达

    def test_clean_text_passes(self):
        out = check_forbidden_words("durable silicone phone case", site="US")
        self.assertTrue(out["passed"])
        self.assertEqual(out["violations"], [])


class TestComplianceGolden(unittest.TestCase):
    """逐条跑 golden：必拦的要拦住且命中指定词，必放行的要放行。"""

    def test_golden_set(self):
        cases = [json.loads(l) for l in GOLDEN.read_text(encoding="utf-8").splitlines() if l.strip()]
        self.assertTrue(cases, "golden 集不应为空")
        for c in cases:
            out = check_forbidden_words(c["text"], site=c.get("site", "US"))
            self.assertEqual(
                out["passed"], c["passed"],
                msg=f"passed 不符: {c['text']!r} -> {out}",
            )
            flagged = {v["词"] for v in out["violations"]}
            for term in c.get("must_flag", []):
                self.assertIn(term, flagged,
                              msg=f"应命中 {term!r}: {c['text']!r} -> {sorted(flagged)}")


if __name__ == "__main__":
    unittest.main()
