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

import asyncio
import logging
from datetime import datetime, timezone
from typing import List

from ..cache.snapshot import SnapshotStore
from ..cache.store import CacheStore
from ..config import Settings
from ..datasources import registry
from ..datasources.base import VALID_STATUSES, DataSource, DataSourceError
from ..models import Product, SearchRequest, SearchResult
from .review_analysis import analyze_reviews

logger = logging.getLogger(__name__)


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
        # 爬虫通道全局并发闸门：多个搜索请求同时命中 scraper 时，各自起一个
        # Chromium 并发打 Amazon 会违背 _enrich 里"串行降封号"的设计意图。
        # 只挡 scraper 通道，api/mock 不受影响（见 search()/get_product() 里的用法）。
        self._scraper_sem = asyncio.Semaphore(settings.scraper_max_concurrency)

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
        # 只在对应 include_* 打开时才把这两个配置项带进 key：没开评论/详情时它们
        # 根本不影响返回内容，不带进去能让 key 在不相关配置变化时保持稳定。
        qa_enabled = self.settings.scraper_fetch_qa if req.include_detail else False
        review_sample_size = self.settings.review_sample_size if req.include_reviews else 0
        key = CacheStore.make_key(platform, req.keyword, marketplace, top_n,
                                  req.include_detail, req.include_reviews,
                                  qa_enabled, review_sample_size)

        if not req.force_refresh:
            cached = self.cache.get(key)
            if cached is not None:
                return cached

        last_err: Exception | None = None
        for name in self._build_chain(platform):
            source: DataSource | None = None
            # 手动 acquire/release 而非 `async with contextlib.nullcontext()`：
            # nullcontext 的异步协议支持是 Python 3.10 才加入的，项目声明兼容 3.9。
            sem = self._scraper_sem if name == "scraper" else None
            if sem is not None:
                await sem.acquire()
            try:
                if sem is not None and not req.force_refresh:
                    # 排队等信号量期间，同 key 的另一个请求可能已经爬完并写了缓存；
                    # 拿到执行权后重新查一次，避免相同关键词被重复串行爬取。
                    cached = self.cache.get(key)
                    if cached is not None:
                        return cached
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
                    try:
                        await source.close()
                    except Exception as exc:
                        # release 必须无条件执行：close() 抛异常也不能让信号量卡住。
                        logger.warning("数据源 close() 抛出异常，已忽略：%s", exc)
                if sem is not None:
                    sem.release()

        raise RuntimeError(f"数据抓取失败：{last_err}")

    async def get_product(self, platform: str, product_id: str,
                          marketplace: str | None = None) -> SearchResult:
        """按 ASIN 抓单个产品全貌（0.5）：走同一回退链 + 缓存 + 评论分析。

        返回复用 SearchResult（products 只含这一个产品），便于沿用缓存/导出/前端模型。
        """
        platform = platform or self.settings.default_platform
        if not registry.has_platform(platform):
            raise RuntimeError(f"不支持的平台：{platform}")
        # 与 search() 一致地归一化：上游常传 "US"/"UK" 等国家码，必须映射成站点域名
        # （amazon.com），否则爬虫会拼出 https://www.us/dp/... 这种坏 URL 而超时。
        marketplace = _normalize_marketplace(marketplace, self.settings.marketplace)
        # get_product 走 fetch_product：恒定抓详情+评论（不抓 QA、评论数固定用
        # fetch_reviews 的默认 limit=40，不读 settings.review_sample_size，如实反映
        # 在 key 里）；kind="product" 跟 search() 的关键词搜索分开命名空间，避免
        # 用户搜索词恰好长得像 "asin:XXX" 时撞上这里的 key。
        key = CacheStore.make_key(platform, f"asin:{product_id}", marketplace, 1,
                                  True, True, False, 40, kind="product")

        cached = self.cache.get(key)
        if cached is not None:
            return cached

        last_err: Exception | None = None
        for name in self._build_chain(platform):
            source: DataSource | None = None
            sem = self._scraper_sem if name == "scraper" else None
            if sem is not None:
                await sem.acquire()
            try:
                if sem is not None:
                    cached = self.cache.get(key)
                    if cached is not None:
                        return cached
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
                    try:
                        await source.close()
                    except Exception as exc:
                        logger.warning("数据源 close() 抛出异常，已忽略：%s", exc)
                if sem is not None:
                    sem.release()

        raise RuntimeError(f"按 ASIN 查询失败：{last_err}")

    async def _enrich(self, source: DataSource, products: List[Product],
                      marketplace: str, req: SearchRequest) -> None:
        """对前 N 逐个富化。串行执行 —— 无代理时并发抓取极易触发封禁。

        每一步失败都保持"尽力而为"——不中断其它商品/其它步骤，但会把失败原因
        写进 Product.reviews_status/qa_status（detail_status 由各数据源自己维护）
        并记日志，让调用方能区分"抓取失败"和"这个商品确实没有评论/问答"，而不是
        两者都静默变成空列表。
        """
        for p in products:
            pid = p.base_info.product_id
            if req.include_detail:
                try:
                    await source.fetch_detail(p, marketplace)
                except Exception as exc:
                    # 约定 fetch_detail 自己吞异常、把状态写进 p.detail_status；
                    # 这里兜底防止某个数据源实现打破约定而中断整批富化。
                    p.detail_status = "error"
                    logger.warning("详情抓取意外抛出 id=%s: %s", pid, exc)

            if req.include_reviews:
                if p.reviews_sample:
                    # 详情页已内嵌抓到评论，没有单独调 fetch_reviews；状态跟随详情页结果。
                    p.reviews_status = p.detail_status if p.detail_status != "not_fetched" else "ok"
                else:
                    try:
                        p.reviews_sample = await source.fetch_reviews(
                            pid, marketplace, self.settings.review_sample_size)
                        # 列表/详情页已知这商品有评论数，却一条没抓到：判定为抓取
                        # 不完整（懒加载慢/选择器失效/拦截等，说不准具体哪种），
                        # 诚实标 error 而不是断言一个不确定的 timeout。
                        if not p.reviews_sample and (p.base_info.review_count or 0) > 0:
                            p.reviews_status = "error"
                        else:
                            p.reviews_status = "ok"
                    except DataSourceError as exc:
                        p.reviews_sample = []
                        p.reviews_status = exc.status if exc.status in VALID_STATUSES else "error"
                        logger.warning("评论抓取失败 id=%s status=%s: %s", pid, exc.status, exc)
                    except Exception as exc:
                        p.reviews_sample = []
                        p.reviews_status = "error"
                        logger.warning("评论抓取意外异常 id=%s: %s", pid, exc)

            # 问答默认关（Amazon 多已下线，抓回来基本空却平添请求/封号风险）；
            # supports_qa=False 的数据源（如 ApiSource）压根没请求过，留在 not_fetched，
            # 不要跟"请求过、确实没有"混成同一个 ok。
            if req.include_detail and self.settings.scraper_fetch_qa and getattr(source, "supports_qa", True):
                try:
                    p.qa_sample = await source.fetch_qa(pid, marketplace)
                    p.qa_status = "ok"
                except DataSourceError as exc:
                    p.qa_sample = []
                    p.qa_status = exc.status if exc.status in VALID_STATUSES else "error"
                    logger.warning("问答抓取失败 id=%s status=%s: %s", pid, exc.status, exc)
                except Exception as exc:
                    p.qa_sample = []
                    p.qa_status = "error"
                    logger.warning("问答抓取意外异常 id=%s: %s", pid, exc)
            # 每日价格/排名快照 → 回填历史（历史从今往后累积）
            try:
                self.snapshots.record(
                    p.base_info.platform, pid, p.pricing.price,
                    p.pricing.currency, p.base_info.rank)
                p.pricing.price_history = self.snapshots.history(p.base_info.platform, pid)
            except Exception as exc:
                logger.warning("价格快照记录失败 id=%s: %s", pid, exc)
