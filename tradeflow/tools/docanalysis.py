"""Document-analysis tools: parse a file, and (optionally) analyze it.

- `parse_document(file_path)` is **deterministic** — it returns the parsed text
  + meta, and lets the agent reason over it (the idiomatic repo pattern: tools
  do the mechanical work, the model does the analysis).
- `analyze_document(file_path, focus)` is the **one-shot** helper: parse + run
  the LLM analysis in one call. NOTE: this calls the provider from inside a
  tool — the repo's first such tool (every other tool is deterministic). It's
  deliberately opt-in (registered in DOCANALYSIS_TOOLS, not the default
  BUILTIN_TOOLS) so the nested-LLM pattern never surprises the default agent.
"""

from __future__ import annotations

from typing import Any, Dict

from ..docanalysis import analyze as _analyze
from ..docparse import ParseError, parse_file
from .base import tool

# Cap how much parsed text we hand back to the agent from `parse_document`, so a
# huge file doesn't blow the conversation context. Full analysis goes through
# the /api/analyze endpoint or `analyze_document`, which cap by DOC_MAX_CHARS.
_AGENT_TEXT_CAP = 8000


@tool
def parse_document(file_path: str) -> Dict[str, Any]:
    """解析本地文件（txt/md/csv/xlsx/pdf/docx/pptx）为纯文本 + 元信息（不做 LLM 分析）。

    用于让 Agent 读取文件内容后自行推理。返回 {kind, meta, text}：
    - kind：'document'（合同/规范/PDF/Word 等散文）或 'table'（csv/xlsx 业务表）
    - meta：格式/行列/页数等
    - text：解析出的文本（超长已截断到上限）
    不支持的格式或缺解析库时返回 {error}。"""
    try:
        parsed = parse_file(file_path)
    except ParseError as exc:
        return {"error": str(exc)}
    text = parsed.text
    truncated = len(text) > _AGENT_TEXT_CAP
    return {
        "kind": parsed.kind,
        "meta": parsed.meta,
        "text": text[:_AGENT_TEXT_CAP] + ("[…已截断…]" if truncated else ""),
    }


@tool
def analyze_document(file_path: str, focus: str = "") -> Dict[str, Any]:
    """解析并用大模型分析本地文件：文档→潜在问题/风险点（附原文出处+理由+严重度）；
    业务表格→洞察（异常/机会/风险/建议 + 关键指标）。

    一步到位（内部会调用项目配置的 LLM provider）。file_path 为服务器本地路径；
    focus 可选，补充你重点关注的方向。需配置真实模型 provider 才有真实分析结果。"""
    try:
        parsed = parse_file(file_path)
    except ParseError as exc:
        return {"error": str(exc)}
    try:
        return _analyze(parsed, focus=focus)
    except Exception as exc:  # surface to the model, don't crash the loop
        return {"error": f"分析失败: {type(exc).__name__}: {exc}"}


# parse_document is safe/deterministic → ok for the default agent.
# analyze_document calls the provider (nested LLM) → opt-in only.
DOCANALYSIS_TOOLS = [parse_document, analyze_document]

__all__ = ["parse_document", "analyze_document", "DOCANALYSIS_TOOLS"]
