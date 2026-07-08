"""HTTP 路由处理器（Starlette）。

说明：本项目基于 Starlette（FastAPI 的底层 ASGI 框架）实现，异步、轻量、
可移植。请求体用 Pydantic 模型校验，响应用 JSON。
"""
from __future__ import annotations

from functools import lru_cache

from pydantic import ValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from ..cache.store import CacheStore
from ..config import get_settings
from ..datasources import registry
from ..models import SearchRequest
from ..services import export_service
from ..services.search_service import SearchService
from ..tasks import store as task_store


@lru_cache
def _service() -> SearchService:
    settings = get_settings()
    cache = CacheStore(settings.cache_db_path, settings.cache_ttl_hours)
    return SearchService(settings, cache)


async def health(request: Request) -> JSONResponse:
    s = get_settings()
    return JSONResponse({"status": "ok", "resolved_source": s.resolved_source})


async def config_info(request: Request) -> JSONResponse:
    s = get_settings()
    return JSONResponse(
        {"platform": s.default_platform, "platforms": registry.supported_platforms(),
         "marketplace": s.marketplace, "top_n": s.top_n, "resolved_source": s.resolved_source}
    )


async def platforms(request: Request) -> JSONResponse:
    """已支持的平台列表（供前端下拉 / TradeFlow list_platforms 用）。"""
    return JSONResponse({"platforms": registry.supported_platforms()})


async def search(request: Request) -> JSONResponse:
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"detail": "请求体必须是合法 JSON"}, status_code=400)

    try:
        req = SearchRequest.model_validate(body)
    except ValidationError as exc:
        return JSONResponse({"detail": exc.errors()}, status_code=422)

    try:
        result = await _service().search(req)
    except RuntimeError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=502)

    return JSONResponse(result.model_dump(mode="json"))


async def search_async(request: Request) -> JSONResponse:
    """异步版 /api/search（对齐 api.md 0.5）：立即返回 taskId，后台抓取，轮询取结果。

    爬虫单次可能几十秒到几分钟；异步化避免阻塞连接、避免请求堆积，调用方可显示进度。
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"detail": "请求体必须是合法 JSON"}, status_code=400)
    try:
        req = SearchRequest.model_validate(body)
    except ValidationError as exc:
        return JSONResponse({"detail": exc.errors()}, status_code=422)

    task = task_store.create("product_search")

    async def _do(t) -> dict:
        t.progress, t.message = 10, "开始抓取…"
        result = await _service().search(req)
        t.progress, t.message = 90, "整理结果…"
        return result.model_dump(mode="json")

    task_store.run(task, _do)
    return JSONResponse({"taskId": task.id, "status": task.status}, status_code=202)


async def task_status(request: Request) -> JSONResponse:
    """轮询异步任务状态/结果：pending | running | success | failed。"""
    t = task_store.get(request.path_params["task_id"])
    if t is None:
        return JSONResponse({"detail": "任务不存在或已过期"}, status_code=404)
    return JSONResponse(t.to_dict())


async def product(request: Request) -> JSONResponse:
    """按 ASIN 抓单个产品全貌（Listing+变体+评价）。供 #5 拆解 / #7 选品用。"""
    asin = request.path_params["asin"]
    params = request.query_params
    platform = params.get("platform") or get_settings().default_platform
    marketplace = params.get("marketplace")
    try:
        result = await _service().get_product(platform, asin, marketplace)
    except RuntimeError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=502)
    return JSONResponse(result.model_dump(mode="json"))


async def export(request: Request) -> Response:
    params = request.query_params
    keyword = params.get("keyword")
    if not keyword:
        return JSONResponse({"detail": "缺少 keyword 参数"}, status_code=400)
    fmt = params.get("fmt", "xlsx")
    if fmt not in ("xlsx", "csv"):
        return JSONResponse({"detail": "fmt 只能是 xlsx 或 csv"}, status_code=422)

    top_n = params.get("top_n")
    req = SearchRequest(
        keyword=keyword,
        platform=params.get("platform") or get_settings().default_platform,
        marketplace=params.get("marketplace"),
        top_n=int(top_n) if top_n else None,
        include_reviews=True,
    )
    try:
        result = await _service().search(req)
    except RuntimeError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=502)

    data, media_type, filename = export_service.export(result, fmt)  # type: ignore[arg-type]
    return Response(
        content=data,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
