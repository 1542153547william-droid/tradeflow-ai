"""Amazon 第三方 API 数据源（默认按 Rainforest API 字段映射，产出通用分层 Product）。

Rainforest / SerpApi / Apify 等提供合规的 Amazon 数据接口。
这里以 Rainforest 的响应结构为默认映射，换供应商时改 `_map_*` 即可。
（API 通道为预留：填了 API_KEY 才启用，否则走爬虫。）
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

import httpx

from ...config import Settings
from ...models import (
    BaseInfo,
    Content,
    Logistics,
    Pricing,
    Product,
    RankNode,
    Review,
    SearchContext,
)
from ..base import VALID_STATUSES, DataSource, DataSourceError


_REDACT_API_KEY = re.compile(r"(api_key=)[^&\s'\"]*")


class ApiSource(DataSource):
    name = "api"
    platform = "amazon"
    supports_qa = False  # Rainforest 等第三方 API 不提供问答，走这里从没真正请求过

    def __init__(self, settings: Settings):
        self.settings = settings
        if not settings.api_key:
            raise DataSourceError("未配置 API_KEY，无法使用 ApiSource")

    async def search_top_products(
        self, keyword: str, marketplace: str, limit: int = 10
    ) -> List[Product]:
        params = {
            "api_key": self.settings.api_key,
            "type": "search",
            "amazon_domain": marketplace,
            "search_term": keyword,
        }
        data = await self._request(params)
        results = data.get("search_results", [])[:limit]
        if not results:
            raise DataSourceError("API 未返回搜索结果")
        products: List[Product] = []
        organic = sponsored = 0
        for r in results:
            is_sp = bool(r.get("sponsored"))
            if is_sp:
                sponsored += 1
            else:
                organic += 1
            products.append(self._map_product(
                keyword,
                None if is_sp else organic,
                sponsored if is_sp else None,
                r,
            ))
        return products

    async def fetch_detail(self, product: Product, marketplace: str) -> None:
        params = {
            "api_key": self.settings.api_key,
            "type": "product",
            "amazon_domain": marketplace,
            "asin": product.base_info.product_id,
        }
        try:
            data = await self._request(params)
        except DataSourceError as exc:
            # 跟 ScraperSource.fetch_detail 对齐：失败也要写状态，不能让详情失败
            # 在换成 API 通道时又变回"静默不完整"；沿用 _request 分好的 status
            # （比如 timeout），不能笼统写死成 error 把这个分类信息丢掉。
            product.detail_status = exc.status if exc.status in VALID_STATUSES else "error"
            return
        p = data.get("product") or {}
        if not p:
            # HTTP 200 但业务报错/无此商品（供应商常见做法：额度耗尽、无结果等也回 200）。
            # 不能因为字段都是空的就当成"抓取成功、这商品本来就没这些信息"。
            product.detail_status = "error"
            return
        ranks = p.get("bestsellers_rank", []) or []
        if ranks:
            product.base_info.rank = _to_int(ranks[0].get("rank"))
            product.base_info.rank_category = ranks[0].get("category")
            product.base_info.rank_sub_nodes = [
                RankNode(node=n.get("category", ""), rank=_to_int(n.get("rank")) or 0)
                for n in ranks[1:] if n.get("rank") is not None
            ]
        product.base_info.parent_id = p.get("parent_asin")
        bb = p.get("buybox_winner", {}) or {}
        product.logistics = Logistics(
            seller=(bb.get("seller") or {}).get("name") if isinstance(bb.get("seller"), dict) else bb.get("seller"),
            fulfillment=bb.get("fulfillment", {}).get("type") if isinstance(bb.get("fulfillment"), dict) else None,
            dimensions=p.get("dimensions"),
            weight=_to_float(p.get("weight")),
        )
        product.content = Content(
            bullet_points=p.get("feature_bullets", []) or [],
            description=p.get("description"),
            image_count=len(p.get("images", []) or []) or None,
            has_video=bool(p.get("videos")),
            child_id=p.get("asin"),
        )
        product.detail_status = "ok"

    async def fetch_reviews(
        self, product_id: str, marketplace: str, limit: int = 40
    ) -> List[Review]:
        params = {
            "api_key": self.settings.api_key,
            "type": "reviews",
            "amazon_domain": marketplace,
            "asin": product_id,
        }
        # 不再吞掉 DataSourceError：让它冒泡给 _enrich，写进 Product.reviews_status，
        # 而不是让"API 请求失败"和"这个商品确实没有评论"看起来一样。
        data = await self._request(params)
        if "reviews" not in data:
            # HTTP 200 但响应体里压根没有 reviews 字段：多半是业务错误/额度耗尽，
            # 不是"这个商品确实没有评论"（那种情况供应商通常返回 reviews: []）。
            raise DataSourceError(f"API 响应缺少 reviews 字段 id={product_id}")
        out: List[Review] = []
        for r in data.get("reviews", [])[:limit]:
            date = r.get("date")
            out.append(Review(
                product_id=product_id,
                review_id=r.get("id"),
                author=(r.get("profile", {}) or {}).get("name"),
                rating=_to_float(r.get("rating")),
                title=r.get("title"),
                body=r.get("body", ""),
                date=date.get("raw") if isinstance(date, dict) else date,
                country=r.get("country") or None,
                variant_purchased=r.get("attributes") if isinstance(r.get("attributes"), str) else None,
                helpful_votes=_to_int(r.get("helpful_votes")),
                has_buyer_media=bool(r.get("images") or r.get("videos")),
            ))
        return out

    # ---- 内部 ----
    async def _request(self, params: Dict[str, Any]) -> Dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=self.settings.request_timeout) as client:
                resp = await client.get(self.settings.api_base_url, params=params)
                resp.raise_for_status()
                return resp.json()
        except httpx.TimeoutException as exc:
            raise DataSourceError(f"API 请求超时: {type(exc).__name__}", status="timeout") from exc
        except (httpx.HTTPError, ValueError) as exc:  # 网络/解析错误
            # httpx 的异常文本（尤其 HTTPStatusError）常把完整请求 URL 拼进去，而
            # params 里带着 api_key 查询参数——脱敏后再往外抛/记日志，避免把密钥写进日志。
            raise DataSourceError(
                f"API 请求失败: {_REDACT_API_KEY.sub(r'\1***', str(exc))}") from exc

    @staticmethod
    def _map_product(keyword: str, organic_rank, sponsored_rank, r: Dict[str, Any]) -> Product:
        price = r.get("price", {}) or {}
        value = _to_float(price.get("value"))
        list_price = _to_float((r.get("rrp") or {}).get("value"))
        discount_pct = (
            round((1 - value / list_price) * 100, 1)
            if value and list_price and list_price > value
            else None
        )
        is_prime = bool(r.get("is_prime", False))
        return Product(
            search_context=SearchContext(
                keyword=keyword, organic_rank=organic_rank, sponsored_rank=sponsored_rank,
            ),
            base_info=BaseInfo(
                product_id=r.get("asin", ""),
                platform="amazon",
                brand=r.get("brand"),
                title=r.get("title", ""),
                image_url=r.get("image"),
                product_url=r.get("link"),
                rating=_to_float(r.get("rating")),
                review_count=_to_int(r.get("ratings_total")),
                platform_extra={"is_prime": is_prime},
            ),
            pricing=Pricing(
                price=value,
                list_price=list_price,
                currency=price.get("currency", "USD"),
                discount_pct=discount_pct,
                fast_shipping=is_prime,
            ),
        )


def _to_float(v: Any) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _to_int(v: Any) -> int | None:
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None
