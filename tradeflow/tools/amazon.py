"""商品查询工具 —— 把独立的「多平台商品查询系统」HTTP 服务包成 Agent 工具。

查询系统（Starlette 服务，默认 http://127.0.0.1:8000）负责脏活：按平台路由 →
API/爬虫/mock 多源回退、限流、24h SQLite 缓存、评论情感分析。这里只做一层薄
封装。服务地址由 `settings.query_api_url` 配置（env: QUERY_API_URL）。

数据是**平台无关的通用核心**（base_info/pricing/logistics/content），跨平台可统一
分析；平台专属字段在 base_info.platform_extra。赋能业务 Agent：#6 市场分析 /
#5 爆款拆解 / #7 智能选品 / #2 Listing 文案。
"""

from __future__ import annotations

from typing import Any, Dict

from config.settings import settings

from .base import tool

# httpx 惰性导入（见函数内）：保持核心 harness 零必需依赖，未装 httpx 时
# 仍能 import 工具、跑 MockProvider；只有真正调用本工具才需要 httpx。

# 走爬虫通道 + 逐个抓详情/评论时，单次查询可能要几分钟，给足超时。
_SEARCH_TIMEOUT = 300.0
_POLL_INTERVAL = 3.0        # 轮询异步任务的间隔（秒）


def _compact(result: Dict[str, Any]) -> Dict[str, Any]:
    """裁掉对分析无用、又占 token 的字段（主图 URL、富文本、历史价格明细），
    保留通用分层结构（base_info/pricing/logistics/content/reviews_sample）给模型。"""
    for p in result.get("products", []):
        (p.get("base_info") or {}).pop("image_url", None)
        content = p.get("content") or {}
        content.pop("rich_content", None)         # A+/富文本可能很长
        pricing = p.get("pricing") or {}
        pricing.pop("price_history", None)        # 历史明细，模型分析用不到逐日点
    return result


@tool
def search_products(keyword: str, platform: str = "amazon", top_n: int = 10,
                    marketplace: str = "", include_reviews: bool = False) -> Dict[str, Any]:
    """按关键词查询指定电商平台的 TOP N 商品（平台无关的通用分层结构）。

    platform：目标平台（如 'amazon'；用 list_platforms 查可选值）。
    每个商品含通用核心字段：base_info(product_id/品牌/标题/评分/评论数/徽章/rank
    销量排名+类目)、pricing(price/原价/折扣/优惠券/fast_shipping)、logistics(seller/
    发货/尺寸/重量)、content(卖点/图片数/视频/变体)、reviews_sample(评论抽样)，外加
    对全部评论的情感分析(正/中/负占比)与高频关键词。平台专属字段在
    base_info.platform_extra。用于市场分析、竞品拆解、选品判断。top_n 范围 1-20。

    include_reviews：是否逐个抓取每个商品的评论正文做情感分析。默认 False——
    列表页已含 品牌/价格/评分/评论数/排名，足够做「竞品格局/选品」，且**快得多**
    （爬虫模式下开 True 会对每个商品再单独开页，单次查询可能慢到几分钟）。
    只有确实需要评论抽样/情感分析时才设 True。
    """
    try:
        import httpx  # 惰性导入，见文件头说明
    except ImportError:
        return {"error": "未安装 httpx，无法调用查询系统："
                         "请 pip install httpx（或 -r requirements.txt）。"}
    payload: Dict[str, Any] = {
        "keyword": keyword,
        "platform": platform,
        "top_n": top_n,
        "include_reviews": include_reviews,
    }
    if marketplace:
        payload["marketplace"] = marketplace
    # 异步模式：提交任务 → 轮询任务状态，直到 success/failed/超时。查询系统据此
    # 不再阻塞连接、不堆积；爬虫慢也不会把请求拖死，超时后给模型明确反馈。
    import time
    base = settings.query_api_url
    try:
        sub = httpx.post(f"{base}/api/search/async", json=payload, timeout=30.0)
        sub.raise_for_status()
        task_id = sub.json().get("taskId")
        if not task_id:
            return {"error": "商品查询失败：未拿到任务ID。"}
        deadline = time.time() + _SEARCH_TIMEOUT
        while time.time() < deadline:
            time.sleep(_POLL_INTERVAL)
            st = httpx.get(f"{base}/api/tasks/{task_id}", timeout=15.0).json()
            status = st.get("status")
            if status == "success":
                return _compact(st.get("result") or {})
            if status == "failed":
                return {"error": f"商品查询失败: {st.get('error')}"}
        return {"error": "商品查询超时（爬虫较慢或被限流）：可稍后重试，"
                         "或让运维改用 API 数据源 / 配置住宅代理池。"}
    except httpx.HTTPError as exc:
        # 把错误作为文本反馈给模型，让它据此调整或告知用户，而非让引擎崩溃。
        return {"error": f"商品查询失败: {type(exc).__name__}: {exc}"}


@tool
def get_product_by_asin(asin: str, platform: str = "amazon",
                        marketplace: str = "") -> Dict[str, Any]:
    """按 ASIN/商品ID 抓单个产品的完整全貌（Listing+变体+评价+评论情感分析）。

    用于 #5 爆款拆解 / #7 选品：输入单个 ASIN，返回该产品的通用分层结构
    base_info(品牌/标题/评分/评论数/排名)、pricing、logistics、content(卖点/变体)、
    reviews_sample 及整体评论情感/关键词分析。platform 用 list_platforms 查可选值。"""
    try:
        import httpx  # 惰性导入，见文件头说明
    except ImportError:
        return {"error": "未安装 httpx，无法调用查询系统。"}
    params: Dict[str, Any] = {"platform": platform}
    if marketplace:
        params["marketplace"] = marketplace
    try:
        resp = httpx.get(f"{settings.query_api_url}/api/product/{asin}",
                         params=params, timeout=_SEARCH_TIMEOUT)
        resp.raise_for_status()
        return _compact(resp.json())
    except httpx.HTTPError as exc:
        return {"error": f"按 ASIN 查询失败: {type(exc).__name__}: {exc}"}


@tool
def list_platforms() -> Dict[str, Any]:
    """列出查询系统当前支持哪些电商平台（供 search_products 的 platform 取值）。"""
    try:
        import httpx
    except ImportError:
        return {"error": "未安装 httpx。"}
    try:
        resp = httpx.get(f"{settings.query_api_url}/api/platforms", timeout=15.0)
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPError as exc:
        return {"error": f"获取平台列表失败: {type(exc).__name__}: {exc}"}


AMAZON_TOOLS = [search_products, get_product_by_asin, list_platforms]
