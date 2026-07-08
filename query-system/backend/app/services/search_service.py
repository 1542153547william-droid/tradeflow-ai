"""搜索编排服务：平台路由 + 数据源回退 + 缓存 + 详情/评论富化 + 评论分析。

流程：
    按 request.platform 选平台 → 列表页 search_top_products
      → 对前 N 逐个（串行 + 延时，降低封号）富化：详情页 / 评论 / 问答
      → 记录每日价格快照并回填历史
      → 聚合所有评论做情感/关键词分析

回退顺序（resolved_source 为起点，按平台可用数据源过滤）：
    api →（失败）→ scraper →（失败）→ 报「查询失败」
默认不再用 mock 兜底；allow_mock_fallback=True 时才在末尾追加 mock。
缓存：命中 TTL 内的结果直接返回（key 含 platform）。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List

from ..cache.snapshot import SnapshotStore
from ..cache.store import CacheStore
from ..config import Settings
from ..datasources import registry
from ..datasources.base import DataSource, DataSourceError
from ..models import Product, SearchRequest, SearchResult
from .review_analysis import analyze_reviews


# 国家码 → Amazon 站点域名。上游（TradeFlow 工具/模型）常传 "US"/"UK"/"JP" 这类
# 国家码，而爬虫按 https://www.{marketplace}/ 拼 URL，需要的是域名（amazon.com）。
# 在此统一归一化，未知值回退到默认站点，避免拼出 https://www.us/ 这种坏 URL。
_COUNTRY_TO_DOMAIN = {
    "US": "amazon.com", "USA": "amazon.com",
    "UK": "amazon.co.uk", "GB": "amazon.co.uk",
    "DE": "amazon.de", "FR": "amazon.fr", "ES": "amazon.es", "IT": "amazon.it",
    "NL": "amazon.nl", "JP": "amazon.co.jp", "CA": "amazon.ca",
    "AU": "amazon.com.au", "IN": "amazon.in", "MX": "amazon.com.mx",
    "BR": "amazon.com.br", "SE": "amazon.se", "PL": "amazon.pl",
}


def _normalize_marketplace(value: str, default: str) -> str:
    """把 marketplace 归一化成 Amazon 站点域名。

    - 空 → default；已是域名（含 'amazon.'）→ 原样（小写）；
    - 国家码（US/UK/JP…）→ 映射到对应域名；未知 → default（防坏 URL）。
    """
    if not value:
        return default
    v = value.strip().lower()
    if "amazon." in v:
        return v
    return _COUNTRY_TO_DOMAIN.get(value.strip().upper(), default)


class SearchService:
    def __init__(self, settings: Settings, cache: CacheStore):
        self.settings = settings
        self.cache = cache
        self.snapshots = SnapshotStore(settings.cache_db_path)

    def _build_chain(self, platform: str) -> List[str]:
        """按 resolved_source 决定尝试顺序，并按该平台实际拥有的数据源过滤。

        默认不再用 mock 兜底（避免假数据冒充成功）；allow_mock_fallback=True 时
        才把 mock 追加为最后兜底。
        """
        start = self.settings.resolved_source
        order = {
            "api": ["api", "scraper"],
            "scraper": ["scraper"],
            "mock": ["mock"],
        }.get(start, ["mock"])
        if self.settings.allow_mock_fallback and "mock" not in order:
            order = order + ["mock"]
        avail = registry.available_sources(platform)
        order = [n for n in order if n in avail]
        if not order:  # 该平台没有对应数据源时的兜底
            order = ["mock"] if "mock" in avail else list(avail)[:1]
        return order

    async def search(self, req: SearchRequest) -> SearchResult:
        platform = req.platform or self.settings.default_platform
        if not registry.has_platform(platform):
            raise RuntimeError(f"不支持的平台：{platform}")
        marketplace = _normalize_marketplace(req.marketplace, self.settings.marketplace)
        top_n = req.top_n or self.settings.top_n
        key = CacheStore.make_key(platform, req.keyword, marketplace, top_n)

        if not req.force_refresh:
            cached = self.cache.get(key)
            if cached is not None:
                return cached

        last_err: Exception | None = None
        for name in self._build_chain(platform):
            source: DataSource | None = None
            try:
                source = registry.make_source(platform, name, self.settings)
                products = await source.search_top_products(req.keyword, marketplace, top_n)
                await self._enrich(source, products, marketplace, req)

                all_reviews = [r for p in products for r in p.reviews_sample]
                analysis = analyze_reviews(all_reviews) if all_reviews else None
                result = SearchResult(
                    keyword=req.keyword,
                    platform=platform,
                    marketplace=marketplace,
                    fetched_at=datetime.now(timezone.utc),
                    source=name,  # type: ignore[arg-type]
                    products=products,
                    review_analysis=analysis,
                )
                self.cache.set(key, result)
                return result
            except DataSourceError as exc:
                last_err = exc
                continue
            except Exception as exc:  # 非预期错误也回退，保证健壮
                last_err = exc
                continue
            finally:
                if source is not None:
                    await source.close()

        raise RuntimeError(f"数据抓取失败：{last_err}")

    async def get_product(self, platform: str, product_id: str,
                          marketplace: str | None = None) -> SearchResult:
        """按 ASIN 抓单个产品全貌（0.5）：走同一回退链 + 缓存 + 评论分析。

        返回复用 SearchResult（products 只含这一个产品），便于沿用缓存/导出/前端模型。
        """
        platform = platform or self.settings.default_platform
        if not registry.has_platform(platform):
            raise RuntimeError(f"不支持的平台：{platform}")
        marketplace = marketplace or self.settings.marketplace
        key = CacheStore.make_key(platform, f"asin:{product_id}", marketplace, 1)

        cached = self.cache.get(key)
        if cached is not None:
            return cached

        last_err: Exception | None = None
        for name in self._build_chain(platform):
            source: DataSource | None = None
            try:
                source = registry.make_source(platform, name, self.settings)
                product = await source.fetch_product(product_id, marketplace)
                if product is None:
                    raise DataSourceError("数据源不支持按 ASIN 查询")
                analysis = (analyze_reviews(product.reviews_sample)
                            if product.reviews_sample else None)
                result = SearchResult(
                    keyword=f"asin:{product_id}",
                    platform=platform,
                    marketplace=marketplace,
                    fetched_at=datetime.now(timezone.utc),
                    source=name,  # type: ignore[arg-type]
                    products=[product],
                    review_analysis=analysis,
                )
                self.cache.set(key, result)
                return result
            except DataSourceError as exc:
                last_err = exc
                continue
            except Exception as exc:
                last_err = exc
                continue
            finally:
                if source is not None:
                    await source.close()

        raise RuntimeError(f"按 ASIN 查询失败：{last_err}")

    async def _enrich(self, source: DataSource, products: List[Product],
                      marketplace: str, req: SearchRequest) -> None:
        """对前 N 逐个富化。串行执行 —— 无代理时并发抓取极易触发封禁。"""
        for p in products:
            pid = p.base_info.product_id
            if req.include_detail:
                try:
                    await source.fetch_detail(p, marketplace)
                except Exception:
                    pass
            # 详情页已内嵌抓到评论时就不再单独开评论页（省一次请求、降封号）
            if req.include_reviews and not p.reviews_sample:
                try:
                    p.reviews_sample = await source.fetch_reviews(
                        pid, marketplace, self.settings.review_sample_size)
                except Exception:
                    p.reviews_sample = []
            # 问答默认关（Amazon 多已下线，抓回来基本空却平添请求/封号风险）
            if req.include_detail and self.settings.scraper_fetch_qa:
                try:
                    p.qa_sample = await source.fetch_qa(pid, marketplace)
                except Exception:
                    p.qa_sample = []
            # 每日价格/排名快照 → 回填历史（历史从今往后累积）
            try:
                self.snapshots.record(
                    p.base_info.platform, pid, p.pricing.price,
                    p.pricing.currency, p.base_info.rank)
                p.pricing.price_history = self.snapshots.history(p.base_info.platform, pid)
            except Exception:
                pass
