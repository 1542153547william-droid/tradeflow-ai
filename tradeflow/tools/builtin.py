"""A few starter tools.

`calculator` exercises the loop end-to-end. `check_forbidden_words` is a first,
deliberately tiny seed of business agent #1 (合规风控): it will grow into a real
per-site forbidden-word / IP checker backed by the tables the user will provide.
"""

from __future__ import annotations

import ast
import operator
from typing import Dict, List

from .amazon import AMAZON_TOOLS
from .base import Tool, tool

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


# Placeholder list; real tables (禁词表/黑名单) get loaded from data/ later.
_SEED_FORBIDDEN = ["best", "no.1", "100% cure", "fda approved", "cheapest"]


@tool
def check_forbidden_words(text: str) -> Dict[str, object]:
    """Flag likely non-compliant / 极限词 phrases in a listing string.

    Seed implementation over a hard-coded list — will be replaced by the
    per-site forbidden-word tables (合规风控 agent)."""
    lowered = text.lower()
    hits: List[str] = [w for w in _SEED_FORBIDDEN if w in lowered]
    return {"passed": not hits, "violations": hits}


BUILTIN_TOOLS = [calculator, check_forbidden_words, *AMAZON_TOOLS]
