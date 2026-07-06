"""ASGI 应用入口（Starlette）。

- /api/* 路由
- 开发期开放 CORS（供 Vite dev server 调用）
- 生产期：若存在 frontend/dist，则静态托管前端产物（SPA）

运行：uvicorn app.main:app --reload --port 8000
"""
from __future__ import annotations

from pathlib import Path

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from .api import routes

_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"

_routes = [
    Route("/api/health", routes.health, methods=["GET"]),
    Route("/api/config", routes.config_info, methods=["GET"]),
    Route("/api/platforms", routes.platforms, methods=["GET"]),
    Route("/api/search", routes.search, methods=["POST"]),
    Route("/api/export", routes.export, methods=["GET"]),
]

# 生产：托管前端构建产物（须放在 /api 路由之后，作为兜底）
if _DIST.exists():
    _routes.append(Mount("/", app=StaticFiles(directory=str(_DIST), html=True), name="frontend"))

middleware = [
    Middleware(
        CORSMiddleware,
        allow_origins=["*"],  # 生产环境请收紧
        allow_methods=["*"],
        allow_headers=["*"],
    )
]

app = Starlette(routes=_routes, middleware=middleware)
