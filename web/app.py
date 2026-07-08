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
from tradeflow import registry  # noqa: E402
from tradeflow.agent.loop import AgentStep  # noqa: E402
from tradeflow.factory import build_agent  # noqa: E402

app = FastAPI(title="TradeFlow-AI")
STATIC = Path(__file__).parent / "static"

# 前端可选项 = "通用助手" + 注册表里的全部业务智能体（单一事实来源，见 0.2 registry）。
_DEFAULT = {"key": "default", "label": "通用助手", "desc": "默认工具集，无专属人设"}


def _agent_list() -> List[Dict[str, str]]:
    return [_DEFAULT] + [{"key": s.name, "label": s.label, "desc": s.description}
                         for s in registry.list_specs()]


def _build_agent(agent_key: str, observer):
    if agent_key in registry.REGISTRY:
        return registry.build(agent_key, observer=observer)
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
    return _agent_list()


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
