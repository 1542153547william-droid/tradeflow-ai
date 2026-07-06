"""数据源抽象接口。

所有数据源（第三方 API、Playwright 爬虫、mock）都实现同一接口，
上层 SearchService 面向该接口编排，做到可插拔与统一回退。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List

from ..models import Product, QA, Review


class DataSourceError(Exception):
    """数据源在获取数据时发生的可恢复错误（触发上层回退）。"""


class DataSource(ABC):
    #: 数据源标识，用于结果里的 source 字段
    name: str = "base"
    #: 所属平台（amazon / ebay / walmart …）
    platform: str = "amazon"

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

    async def close(self) -> None:
        """释放资源（如浏览器）。默认无操作。"""
        return None
