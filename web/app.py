"""Minimal public web layer over the agent harness.

Serves a chat page at `/` and a JSON endpoint at `/api/chat`. The page and the
API share an origin, so no CORS setup is needed. This is intentionally thin — the
real logic lives in the harness; here we just expose `agent.run()` over HTTP.

Run locally:  uvicorn web.app:app --reload
In Docker:    see Dockerfile / docker-compose.yml
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import FastAPI  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from config.settings import settings  # noqa: E402
from tradeflow.agent.loop import AgentStep  # noqa: E402
from tradeflow.compose import build_named_agent  # noqa: E402
from tradeflow.factory import build_agent  # noqa: E402
from tradeflow.tools.compliance import COMPLIANCE_TOOLS  # noqa: E402
from tradeflow.tools.imagery import IMAGERY_TOOLS  # noqa: E402
from tradeflow.tools.listing import LISTING_TOOLS  # noqa: E402

app = FastAPI(title="TradeFlow-AI")
STATIC = Path(__file__).parent / "static"

# 前端可选的智能体。key → 展示信息 + 挂载的工具（人设由 build_named_agent 按 key 组合）。
AGENTS = {
    "default": {"label": "通用助手", "desc": "默认工具集，无专属人设", "tools": None},
    "compliance": {"label": "#1 合规风控", "desc": "审文案/类目：禁词+IP+类目风险+白名单",
                   "tools": COMPLIANCE_TOOLS},
    "listing": {"label": "#2 Listing 文案", "desc": "产出多站点文案，自动埋词+过合规",
                "tools": LISTING_TOOLS},
    "imagery": {"label": "#3 图文视频提示词", "desc": "绘图prompt+短视频脚本+图片规范校验",
                "tools": IMAGERY_TOOLS},
}


def _build_agent(agent_key: str, observer):
    spec = AGENTS.get(agent_key)
    if spec and spec["tools"] is not None:
        return build_named_agent(agent_key, tools=spec["tools"], observer=observer)
    return build_agent(observer=observer)


class ChatIn(BaseModel):
    message: str
    agent: str = "default"


class ChatOut(BaseModel):
    reply: str
    iterations: int
    stopped_early: bool
    steps: List[Dict[str, Any]]


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/healthz")
def healthz() -> Dict[str, bool]:
    return {"ok": True}


@app.get("/api/info")
def info() -> Dict[str, str]:
    # Lets the page show whether it's on the real model or the mock.
    return {"provider": settings.provider, "model": settings.default_model}


@app.get("/api/agents")
def agents() -> List[Dict[str, str]]:
    # 只暴露展示字段；tools 是 Tool 对象，不可 JSON 序列化，需排除。
    return [{"key": k, "label": v["label"], "desc": v["desc"]} for k, v in AGENTS.items()]


@app.post("/api/chat", response_model=ChatOut)
def chat(body: ChatIn) -> ChatOut:
    steps: List[Dict[str, Any]] = []

    def observe(step: AgentStep) -> None:
        steps.append({
            "iteration": step.iteration,
            "reasoning": step.reasoning,
            "text": step.text,
            "tools": step.tool_calls,
        })

    # Fresh agent per request → clean, single-turn conversations (no shared state).
    agent = _build_agent(body.agent, observe)
    result = agent.run(body.message)
    return ChatOut(
        reply=result.output,
        iterations=result.iterations,
        stopped_early=result.stopped_early,
        steps=steps,
    )


app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")
