"""数据源抽象接口。

所有数据源（第三方 API、Playwright 爬虫、mock）都实现同一接口，
上层 SearchService 面向该接口编排，做到可插拔与统一回退。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional, get_args

from ..models import STATUS_LITERAL, BaseInfo, Product, QA, Review, SearchContext

VALID_STATUSES = frozenset(get_args(STATUS_LITERAL))


class DataSourceError(Exception):
    """数据源在获取数据时发生的可恢复错误（触发上层回退）。

    status：给上层（SearchService._enrich）分类用，写进 Product 的
    detail_status/reviews_status/qa_status，让"字段为空"和"这一步抓取失败"
    在返回结果里可区分，而不是静默变成一样的空值。
    """

    def __init__(self, message: str, status: str = "error"):
        super().__init__(message)
        self.status = status


class DataSource(ABC):
    #: 数据源标识，用于结果里的 source 字段
    name: str = "base"
    #: 所属平台（amazon / ebay / walmart …）
    platform: str = "amazon"
    #: 该数据源是否真的实现了问答抓取。默认 False（安全默认）：没显式声明 True 的
    #: 数据源，一律当成"没请求过"（qa_status 留在 not_fetched），而不是误标成 ok
    #: ——否则任何忘记声明、或走本类空实现 fetch_qa 的新数据源都会被当成"抓取
    #: 成功、确实没有问答"。真正实现了的数据源（如 ScraperSource）显式覆盖成 True。
    supports_qa: bool = False

    @abstractmethod
    async def search_top_products(
        self, keyword: str, marketplace: str, limit: int = 10
    ) -> List[Product]:
        """返回该关键词下的 TOP N 产品（列表页字段：search_context/base_info/pricing）。"""
        raise NotImplementedError

    @abstractmethod
    async def fetch_reviews(
        self, product_id: str, marketplace: str, limit: int = 40
    ) -> List[Review]:
        """返回某产品的评论样本。"""
        raise NotImplementedError

    async def fetch_detail(self, product: Product, marketplace: str) -> None:
        """进详情页补全 base_info(rank)/logistics/content 等字段，原地修改 product。

        默认无操作（列表页数据源无需实现）。失败不应抛错，静默跳过即可。
        """
        return None

    async def fetch_qa(
        self, product_id: str, marketplace: str, limit: int = 10
    ) -> List[QA]:
        """返回买家问答样本。默认空（亚马逊多已下线；仅爬虫尽力抓）。"""
        return []

    async def fetch_product(
        self, product_id: str, marketplace: str
    ) -> Optional[Product]:
        """按 product_id(ASIN) 抓单个产品全貌（任务 0.5 的 /api/product/{asin} 底座）。

        默认实现：构造骨架（含 dp URL）→ fetch_detail 富化（变体/rank/content）→
        fetch_reviews 补评论。数据源可覆盖以更精确实现；返回 None 表示不支持/未找到。
        """
        product = Product(
            search_context=SearchContext(keyword=f"asin:{product_id}"),
            base_info=BaseInfo(
                product_id=product_id, platform=self.platform,
                product_url=f"https://www.{marketplace}/dp/{product_id}",
            ),
        )
        await self.fetch_detail(product, marketplace)
        if product.reviews_sample:
            # 详情页已内嵌抓到评论（如 ScraperSource），不再单独抓一次；状态跟随
            # 详情页结果，跟 SearchService._enrich 对同一情形的处理保持一致。
            product.reviews_status = (
                product.detail_status if product.detail_status != "not_fetched" else "ok")
        else:
            try:
                product.reviews_sample = await self.fetch_reviews(product_id, marketplace)
                # 列表/详情页已知有评论数却一条没抓到，视为抓取不完整而非"确实没有"；
                # 具体是超时/被拦截/选择器失效说不准，只能诚实标 error，不能断言 timeout。
                if not product.reviews_sample and (product.base_info.review_count or 0) > 0:
                    product.reviews_status = "error"
                else:
                    product.reviews_status = "ok"
            except DataSourceError as exc:
                product.reviews_sample = []
                product.reviews_status = exc.status if exc.status in VALID_STATUSES else "error"
            except Exception:
                product.reviews_sample = []
                product.reviews_status = "error"
        return product

    async def close(self) -> None:
        """释放资源（如浏览器）。默认无操作。"""
        return None
