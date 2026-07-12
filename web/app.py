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
import base64  # noqa: E402
import hmac  # noqa: E402
import json  # noqa: E402
import threading  # noqa: E402

from fastapi import FastAPI, File, Form, Header, HTTPException, Request, UploadFile  # noqa: E402
from fastapi.responses import FileResponse, StreamingResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from config.settings import settings  # noqa: E402
from tradeflow import registry  # noqa: E402
from tradeflow.agent.loop import AgentStep  # noqa: E402
from tradeflow.factory import build_agent  # noqa: E402
from tradeflow.tools.compliance import compliance_gate  # noqa: E402
from web import store  # noqa: E402
from web.listing_gen import generate_listing  # noqa: E402
from web.opp_suggest import suggest_opportunities  # noqa: E402
from web.database import connect, init_db  # noqa: E402
from web.import_service import (ads_overview, list_imports, parse_upload,
                                save_import, suggest_mapping)  # noqa: E402

app = FastAPI(title="TradeFlow-AI")
STATIC = Path(__file__).parent / "static"

# 前端可选项 = "通用助手" + 注册表里的全部业务智能体（单一事实来源，见 0.2 registry）。
_DEFAULT = {"key": "default", "label": "通用助手", "desc": "默认工具集，无专属人设"}


@app.on_event("startup")
def startup() -> None:
    init_db()


@app.middleware("http")
async def require_api_token(request: Request, call_next):
    if settings.basic_auth_user and settings.basic_auth_password:
        encoded = request.headers.get("Authorization", "").removeprefix("Basic ")
        try:
            supplied = base64.b64decode(encoded).decode("utf-8")
        except Exception:
            supplied = ""
        expected = f"{settings.basic_auth_user}:{settings.basic_auth_password}"
        if not hmac.compare_digest(supplied, expected):
            from fastapi.responses import JSONResponse
            return JSONResponse({"detail": "需要登录"}, status_code=401,
                                headers={"WWW-Authenticate": 'Basic realm="TradeFlow-AI"'})
    if (request.url.path.startswith("/api/") and settings.api_token
            and request.headers.get("X-TradeFlow-Token") != settings.api_token):
        from fastapi.responses import JSONResponse
        return JSONResponse({"detail": "无效的访问令牌"}, status_code=401)
    return await call_next(request)


def _scope(x_tradeflow_token: str | None = Header(default=None),
           x_tradeflow_user: str = Header(default="default"),
           x_tradeflow_store: str = Header(default="default")) -> tuple[str, str]:
    if settings.api_token and x_tradeflow_token != settings.api_token:
        raise HTTPException(status_code=401, detail="无效的访问令牌")
    with connect() as db:
        ok = db.execute("SELECT 1 FROM stores WHERE id=? AND user_id=?",
                        (x_tradeflow_store, x_tradeflow_user)).fetchone()
    if not ok:
        raise HTTPException(status_code=403, detail="无权访问该店铺")
    return x_tradeflow_user, x_tradeflow_store


@app.get("/api/stores")
def stores(x_tradeflow_user: str = Header(default="default")) -> Dict[str, Any]:
    with connect() as db:
        rows = db.execute("SELECT id,name,marketplace,created_at FROM stores WHERE user_id=? ORDER BY created_at",
                          (x_tradeflow_user,)).fetchall()
    return {"items": [dict(r) for r in rows]}


class StoreIn(BaseModel):
    name: str
    marketplace: str = "US"


@app.post("/api/stores")
def create_store(body: StoreIn, x_tradeflow_user: str = Header(default="default")) -> Dict[str, Any]:
    import uuid
    store_id = f"store_{uuid.uuid4().hex[:10]}"
    with connect() as db:
        db.execute("INSERT OR IGNORE INTO users(id,name) VALUES(?,?)", (x_tradeflow_user, x_tradeflow_user))
        db.execute("INSERT INTO stores(id,user_id,name,marketplace) VALUES(?,?,?,?)",
                   (store_id, x_tradeflow_user, body.name, body.marketplace))
    return {"id": store_id, "name": body.name, "marketplace": body.marketplace}


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
    # 新的完整产品原型页（对话已接后端；机会上新等模块仍在接入中）。
    return FileResponse(STATIC / "prototype.html")


@app.get("/classic")
def classic() -> FileResponse:
    # 旧的极简聊天页，保留作为纯净的智能体联调入口。
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


# ---- 机会上新：真实持久化的 CRUD（B1） ----
@app.get("/api/opportunities")
def list_opportunities(x_tradeflow_user: str = Header(default="default"),
                       x_tradeflow_store: str = Header(default="default")) -> Dict[str, Any]:
    return {"items": store.list_opps(x_tradeflow_user, x_tradeflow_store)}


@app.post("/api/opportunities")
def create_opportunity(body: Dict[str, Any], x_tradeflow_user: str = Header(default="default"),
                       x_tradeflow_store: str = Header(default="default")) -> Dict[str, Any]:
    # 入参是前端传的机会对象（name/cat/score/margin/…），存储层负责补 id/时间/去重。
    return store.add_opp(body, x_tradeflow_user, x_tradeflow_store)


@app.delete("/api/opportunities/{opp_id}")
def remove_opportunity(opp_id: str, x_tradeflow_user: str = Header(default="default"),
                       x_tradeflow_store: str = Header(default="default")) -> Dict[str, bool]:
    return {"ok": store.delete_opp(opp_id, x_tradeflow_user, x_tradeflow_store)}


@app.post("/api/imports/preview")
async def import_preview(file: UploadFile = File(...)) -> Dict[str, Any]:
    content = await file.read()
    if len(content) > 20 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="文件不能超过 20MB")
    try:
        columns, rows = parse_upload(file.filename or "upload.xlsx", content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    mapping = suggest_mapping(columns)
    return {"filename": file.filename, "columns": columns, "mapping": mapping,
            "preview": rows[:10], "row_count": len(rows)}


@app.post("/api/imports")
async def import_commit(file: UploadFile = File(...), mapping: str = Form(default="{}"),
                        x_tradeflow_user: str = Header(default="default"),
                        x_tradeflow_store: str = Header(default="default")) -> Dict[str, Any]:
    content = await file.read()
    try:
        columns, rows = parse_upload(file.filename or "upload.xlsx", content)
        selected = json.loads(mapping) if mapping and mapping != "{}" else suggest_mapping(columns)
        return save_import(x_tradeflow_user, x_tradeflow_store, file.filename or "upload.xlsx",
                           columns, rows, selected)
    except (ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/imports")
def imports(x_tradeflow_user: str = Header(default="default"),
            x_tradeflow_store: str = Header(default="default")) -> Dict[str, Any]:
    return {"items": list_imports(x_tradeflow_user, x_tradeflow_store)}


@app.get("/api/optimization/ads")
def optimization_ads(x_tradeflow_user: str = Header(default="default"),
                     x_tradeflow_store: str = Header(default="default")) -> Dict[str, Any]:
    return ads_overview(x_tradeflow_user, x_tradeflow_store)


# ---- 合规预检：直接调 #1 合规的确定性工具，返回结构化结果（B1，无需过模型） ----
class ComplianceIn(BaseModel):
    text: str = ""
    category: str = ""
    site: str = "US"


@app.post("/api/compliance/check")
def compliance_check(body: ComplianceIn) -> Dict[str, Any]:
    return compliance_gate.func(body.text, body.category, body.site)


# ---- 生成 Listing 素材：#2 文案（JSON 契约）+ 词根库 + 合规，结构化返回（B0） ----
class ListingGenIn(BaseModel):
    name: str
    category: str = ""
    site: str = "US"


@app.post("/api/listing/generate")
def listing_generate(body: ListingGenIn) -> Dict[str, Any]:
    return generate_listing(body.name, body.category, body.site)


# ---- 对话选品：结构化机会清单，供前端渲染可「放入机会上新」的卡片（B0） ----
class OppSuggestIn(BaseModel):
    query: str
    top_n: int = 4


@app.post("/api/opportunities/suggest")
def opportunities_suggest(body: OppSuggestIn) -> Dict[str, Any]:
    return suggest_opportunities(body.query, body.top_n)


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
