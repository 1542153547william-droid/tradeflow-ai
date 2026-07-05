"""Tool abstraction.

A tool is a plain Python callable wrapped with a JSON-schema description that the
model can see. The `@tool` decorator derives that schema from the function's type
hints and docstring so defining a new capability stays a one-function affair.
"""

from __future__ import annotations

import inspect
import json
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, get_type_hints


_PY_TO_JSON = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
}


def _json_type(py_type: Any) -> str:
    return _PY_TO_JSON.get(py_type, "string")


@dataclass
class Tool:
    name: str
    description: str
    parameters: Dict[str, Any]      # JSON schema for the input object
    func: Callable[..., Any]

    @property
    def spec(self) -> Dict[str, Any]:
        """Provider-neutral tool spec. Providers adapt this to their wire format."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.parameters,
        }

    def run(self, arguments: Dict[str, Any]) -> str:
        """Execute the tool and coerce the result to a string for the model."""
        result = self.func(**arguments)
        if isinstance(result, str):
            return result
        try:
            return json.dumps(result, ensure_ascii=False, default=str)
        except TypeError:
            return str(result)


def tool(_func: Optional[Callable] = None, *, name: Optional[str] = None,
         description: Optional[str] = None) -> Callable:
    """Turn a function into a Tool. Usage:

        @tool
        def add(a: int, b: int) -> int:
            '''Add two integers.'''
            return a + b
    """

    def decorate(func: Callable) -> Tool:
        hints = get_type_hints(func)
        sig = inspect.signature(func)
        props: Dict[str, Any] = {}
        required: List[str] = []
        for pname, param in sig.parameters.items():
            if pname == "self":
                continue
            props[pname] = {"type": _json_type(hints.get(pname, str))}
            if param.default is inspect.Parameter.empty:
                required.append(pname)
        schema = {"type": "object", "properties": props, "required": required}
        return Tool(
            name=name or func.__name__,
            description=description or (inspect.getdoc(func) or "").strip(),
            parameters=schema,
            func=func,
        )

    if _func is not None:          # bare @tool
        return decorate(_func)
    return decorate                # @tool(...)


class ToolRegistry:
    """Holds the tools available to an agent and dispatches calls to them."""

    def __init__(self, tools: Optional[List[Tool]] = None) -> None:
        self._tools: Dict[str, Tool] = {}
        for t in tools or []:
            self.register(t)

    def register(self, t: Tool) -> None:
        if t.name in self._tools:
            raise ValueError(f"duplicate tool name: {t.name}")
        self._tools[t.name] = t

    def specs(self) -> List[Dict[str, Any]]:
        return [t.spec for t in self._tools.values()]

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def __len__(self) -> int:
        return len(self._tools)
