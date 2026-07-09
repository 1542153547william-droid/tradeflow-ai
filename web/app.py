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

import asyncio  # noqa: E402
import json  # noqa: E402
import threading  # noqa: E402

from fastapi import FastAPI  # noqa: E402
from fastapi.responses import FileResponse, StreamingResponse  # noqa: E402
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


def _sse(event: Dict[str, Any]) -> str:
    """把一个事件序列化成一帧 SSE。"""
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


@app.post("/api/chat/stream")
async def chat_stream(body: ChatIn) -> StreamingResponse:
    """SSE 流式版对话：边跑边把进度推给前端，避免长任务（抓竞品等）看起来像卡死。

    agent.run_stream 逐事件产出：("tools",…) 本轮要调的工具、("token",…) 最终答案的
    token 增量、("final",…) 结束。整个循环同步阻塞（内部还等爬虫），放线程里跑，
    通过线程安全队列把事件转成 SSE。前端据此：抓取时显示"正在调用…"、答案逐字蹦出。
    """
    loop = asyncio.get_event_loop()
    queue: asyncio.Queue = asyncio.Queue()

    def push(evt: Dict[str, Any]) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, evt)

    def run_agent() -> None:
        try:
            agent = _build_agent(body.agent, lambda _step: None)  # 流式下不用 observer
            for kind, payload in agent.run_stream(body.message):
                if kind == "token":
                    push({"type": "token", "text": payload})
                elif kind == "reset":
                    push({"type": "reset"})
                elif kind == "tools":
                    push({"type": "status", "tools": payload,
                          "message": "正在调用工具：" + "、".join(payload) + " …"})
                elif kind == "final":
                    push({"type": "final", "reply": payload.output,
                          "iterations": payload.iterations,
                          "stopped_early": payload.stopped_early})
        except Exception as exc:  # noqa: BLE001 —— 把错误推给前端而非静默
            push({"type": "error", "error": f"{type(exc).__name__}: {exc}"})
        push({"type": "done"})

    threading.Thread(target=run_agent, daemon=True).start()

    async def event_gen():
        # 先推一个"已收到、开始处理"，让前端立刻有反馈。
        yield _sse({"type": "status", "iteration": 0, "message": "已收到，开始处理 …"})
        while True:
            evt = await queue.get()
            if evt.get("type") == "done":
                break
            yield _sse(evt)

    return StreamingResponse(event_gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")
