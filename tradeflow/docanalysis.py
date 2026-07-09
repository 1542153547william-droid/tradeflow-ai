"""LLM analysis of parsed documents / business data.

Uses the project's **existing** `LLMProvider` (`build_provider`) — no ContextGem,
no litellm. Two prompt templates, chosen by `ParsedDoc.kind`:

- `"document"` → extract risk points, each with 原文出处 / 判断理由 / 严重度
- `"table"`    → business insights (异常/机会/风险/建议) + metrics

This replicates ContextGem's `references`+`justifications` via prompt design and
a single structured-JSON pass (verified to be just prompt engineering — see the
plan's research notes). Returns a dict the web layer / tools can render.

`build_provider` is imported lazily inside `analyze()` to avoid an import cycle
(builtin tools → this module → factory → builtin tools).
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from config.settings import settings

from .docparse import ParsedDoc
from .llm.base import Message, Role

_DOC_MAX_CHARS_DEFAULT = 150000

_SYSTEM = (
    "你是 TradeFlow-AI 的文件分析助手。基于用户上传、已解析成文本的文件内容做专业分析。"
    "严格基于给定文本，不要编造文本中没有的信息；引用数字/日期/金额时直接取自原文。"
    "输出必须是合法 JSON，不要包裹在代码块里，不要输出 JSON 以外的解释文字。"
)

_DOC_PROMPT = """\
下面是从一份【文档】（合同/规范/说明书/报告等）解析出的文本。请找出其中的【潜在问题与风险点】，
例如：异常条款、前后矛盾、关键信息缺失、合规问题、对己方不利的条款、模糊或易歧义的表述等。

每条风险输出一个对象，字段：
- risk：风险点（一句话）
- severity：严重度，取值 高 / 中 / 低
- quote：原文出处（尽量直接引用原文原句；确实无法定位时写"（概括）"）
- reason：判断理由（为什么判定为风险）

只输出如下结构的 JSON，不要任何其它文字：
{{"risks": [{{"risk": "...", "severity": "...", "quote": "...", "reason": "..."}}]}}

若确实无可识别风险，返回 {{\"risks\": []}}，并在 summary 里说明原因。

文件元信息：{meta}
用户补充关注点（可空）：{focus}

文档内容：
\"\"\"
{text}
\"\"\"
"""

_TABLE_PROMPT = """\
下面是从一份【业务表格数据】（亚马逊广告/订单/库存/竞品 ASIN 报表等）解析出的内容（已转成
Markdown 表格，超大表已截断）。请基于数据给出【业务洞察】：数据概览、异常项、机会/选品信号、
利润或销量观察、可执行的优化建议。

只输出如下结构的 JSON：
{{
  "summary": "一句话数据概览（行数/关键指标）",
  "insights": [
    {{"type": "异常|机会|风险|建议", "finding": "...", "evidence": "引用数据中的字段或数值", "action": "建议动作"}}
  ],
  "metrics": {{"指标名": "值"}}
}}

文件元信息：{meta}
用户补充关注点（可空）：{focus}

表格数据：
\"\"\"
{text}
\"\"\"
"""


def _max_chars() -> int:
    try:
        return int(getattr(settings, "doc_max_chars", _DOC_MAX_CHARS_DEFAULT) or _DOC_MAX_CHARS_DEFAULT)
    except (TypeError, ValueError):
        return _DOC_MAX_CHARS_DEFAULT


def _truncate(text: str) -> str:
    lim = _max_chars()
    if len(text) <= lim:
        return text
    return text[:lim] + f"\n\n[…已截断：原文共 {len(text)} 字符，仅分析前 {lim} 字符…]"


def _build_prompt(parsed: ParsedDoc, focus: str) -> str:
    text = _truncate(parsed.text)
    meta = json.dumps(parsed.meta, ensure_ascii=False)
    tmpl = _TABLE_PROMPT if parsed.kind == "table" else _DOC_PROMPT
    return tmpl.format(meta=meta, focus=focus or "（无）", text=text)


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    """Pull the first balanced {...} object out of a model response that may be
    wrapped in ```json fences or surrounded by stray prose."""
    if not text:
        return None
    s = text.strip()
    # strip a leading ```json / ``` fence if present
    if s.startswith("```"):
        s = s.split("```", 2)
        # ['' , '<inner>', maybe tail]  or  ['', 'json\n<inner>', ...]
        inner = s[1] if len(s) > 1 else ""
        if inner.startswith("json"):
            inner = inner[4:]
        s = inner.strip()
    # brace-match the first complete object
    start = s.find("{")
    if start == -1:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(s)):
        ch = s[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                blob = s[start:i + 1]
                try:
                    return json.loads(blob)
                except json.JSONDecodeError:
                    return None
    return None


def analyze(parsed: ParsedDoc, focus: str = "", provider=None) -> Dict[str, Any]:
    """Analyze a parsed doc with the project's LLM provider. Returns a structured
    dict (risks[] for documents, insights[]/metrics for tables). Falls back to
    {error, raw} if the model didn't return parseable JSON (e.g. on MockProvider)."""
    if provider is None:
        # Lazy import to avoid the builtin→factory→builtin cycle.
        from .factory import build_provider
        provider = build_provider()

    prompt = _build_prompt(parsed, focus)
    try:
        resp = provider.complete(messages=[Message(role=Role.USER, content=prompt)],
                                 system=_SYSTEM)
    except Exception as exc:
        # Provider/网络错误（如连不上模型 API、超时）→ 友好返回，不让端点 500。
        return {
            "error": f"调用模型失败：{type(exc).__name__}: {exc}",
            "kind": parsed.kind,
            "meta": parsed.meta,
        }
    raw = (resp.text or "").strip()
    data = _extract_json(raw)
    if data is None:
        return {
            "error": "模型未返回可解析的 JSON（可能未配置真实模型，处于 mock）",
            "raw": raw[:2000],
            "kind": parsed.kind,
            "meta": parsed.meta,
        }
    data.setdefault("kind", parsed.kind)
    data.setdefault("meta", parsed.meta)
    return data


__all__ = ["analyze"]
