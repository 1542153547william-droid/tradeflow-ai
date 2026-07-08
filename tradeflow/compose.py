"""智能体组合机制（任务 0.1）—— 把"人设 + 判断规则 + 工具"拼成一个 Agent。

固定套路（新建一个智能体只需加 3 个文件、不改引擎）：
  1. `tradeflow/prompts/<名>.md`  —— 人设 / persona
  2. `skills/<名>/*.md`           —— 判断规则 / SOP（按文件名排序拼接）
  3. `examples/run_<名>.py`       —— 一键运行脚本

系统提示 = BASE_SYSTEM_PROMPT + 人设 + 全部 skills。工具由调用方传入（放
`tradeflow/tools/`）。缺人设或缺 skills 都不报错——允许"先挂工具、后补规则"。
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from .agent.loop import Agent
from .factory import build_agent
from .prompts import BASE_SYSTEM_PROMPT
from .tools.base import Tool

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
SKILLS_DIR = Path(__file__).resolve().parents[1] / "skills"


def load_persona(name: str) -> str:
    """读 `tradeflow/prompts/<名>.md`；不存在返回空串。"""
    path = PROMPTS_DIR / f"{name}.md"
    return path.read_text(encoding="utf-8").strip() if path.exists() else ""


def load_skills(name: str) -> str:
    """按文件名排序拼接 `skills/<名>/*.md`；目录不存在返回空串。"""
    folder = SKILLS_DIR / name
    if not folder.is_dir():
        return ""
    parts = [p.read_text(encoding="utf-8").strip()
             for p in sorted(folder.glob("*.md"))]
    return "\n\n".join(p for p in parts if p)


def compose_system_prompt(name: str) -> str:
    """BASE + 人设 + skills，拼成该智能体的完整系统提示。"""
    sections = [BASE_SYSTEM_PROMPT.strip()]
    if persona := load_persona(name):
        sections.append(f"# 岗位人设\n{persona}")
    if skills := load_skills(name):
        sections.append(f"# 判断规则与 SOP\n{skills}")
    return "\n\n".join(sections)


def build_named_agent(name: str, tools: Optional[List[Tool]] = None,
                      **kwargs) -> Agent:
    """按名字组装一个业务智能体：读人设+skills 拼系统提示，挂上 tools。"""
    return build_agent(system_prompt=compose_system_prompt(name),
                       tools=tools, **kwargs)


__all__ = ["build_named_agent", "compose_system_prompt",
           "load_persona", "load_skills", "PROMPTS_DIR", "SKILLS_DIR"]
