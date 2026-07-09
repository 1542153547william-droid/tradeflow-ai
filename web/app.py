"""Minimal public web layer over the agent harness.

Serves a chat page at `/` and a JSON endpoint at `/api/chat`. The page and the
API share an origin, so no CORS setup is needed. This is intentionally thin — the
real logic lives in the harness; here we just expose `agent.run()` over HTTP.

Run locally:  uvicorn web.app:app --reload
In Docker:    see Dockerfile / docker-compose.yml
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import FastAPI, File, Form, HTTPException, UploadFile  # noqa: E402
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


class AnalyzeOut(BaseModel):
    kind: str
    meta: Dict[str, Any]
    analysis: Dict[str, Any]


# Hard upload cap to protect the server from OOM while parsing huge files.
_MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 MB


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


@app.post("/api/analyze", response_model=AnalyzeOut)
async def analyze(file: UploadFile = File(...), focus: str = Form("")):
    """Upload a file (txt/csv/xlsx/pdf/docx/pptx) → parse → LLM analysis.

    Implements the `/api/import/excel`-style upload that `docs/api.md` spec'd but
    never had. Saves the upload to a temp file, parses it (lightweight libs), then
    runs the doc-analysis pipeline (existing provider). Returns parsed `kind`/`meta`
    + the structured analysis (risks[] for documents, insights[]/metrics for tables).
    """
    from tradeflow.docanalysis import analyze as run_analyze
    from tradeflow.docparse import ParseError, parse_file

    suffix = Path(file.filename or "").suffix or ""
    data = await file.read()
    if len(data) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"文件过大（{len(data) // 1024 // 1024}MB），上限 20MB，请拆分或裁剪后重传。",
        )
    fd, tmp_path = tempfile.mkstemp(suffix=suffix)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(data)
        try:
            parsed = parse_file(tmp_path)
        except ParseError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        parsed.meta["uploaded_as"] = file.filename  # show the user's filename, not the temp one
        result = run_analyze(parsed, focus=focus)
        return AnalyzeOut(kind=parsed.kind, meta=parsed.meta, analysis=result)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")
