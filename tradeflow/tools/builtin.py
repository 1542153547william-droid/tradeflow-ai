"""A few starter tools.

`calculator` exercises the loop end-to-end. The 合规风控 (#1) tools now live in
`tools/compliance.py` (they grew past a single seed function); they're pulled in
here so the default agent still has the full built-in toolset.
"""

from __future__ import annotations

import ast
import operator

from .amazon import AMAZON_TOOLS
from .base import tool
from .compliance import COMPLIANCE_TOOLS, check_forbidden_words  # noqa: F401  (re-export)
from .docanalysis import parse_document  # deterministic file parser (safe default)

# --- safe arithmetic ------------------------------------------------------
_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.Pow: operator.pow, ast.USub: operator.neg,
    ast.Mod: operator.mod,
}


def _eval(node):
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.BinOp):
        return _OPS[type(node.op)](_eval(node.left), _eval(node.right))
    if isinstance(node, ast.UnaryOp):
        return _OPS[type(node.op)](_eval(node.operand))
    raise ValueError("unsupported expression")


@tool
def calculator(expression: str) -> str:
    """Evaluate a basic arithmetic expression, e.g. '12 * (3 + 4)'."""
    value = _eval(ast.parse(expression, mode="eval").body)
    return str(value)


BUILTIN_TOOLS = [calculator, *COMPLIANCE_TOOLS, *AMAZON_TOOLS, parse_document]
