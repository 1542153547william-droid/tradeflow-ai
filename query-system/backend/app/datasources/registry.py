"""平台注册表：平台名 → { 数据源名: 工厂 }。

加一个新平台 = 新建 `datasources/<平台>/` 子包(scraper/api/mock) + 在这里加一行。
上层 SearchService 按 platform 取该平台的数据源，按 api→scraper→mock 顺序回退。
"""
from __future__ import annotations

from typing import Callable, Dict, List

from ..config import Settings
from .base import DataSource

SourceFactory = Callable[[Settings], DataSource]


def _amazon_api(s: Settings) -> DataSource:
    from .amazon.api import ApiSource
    return ApiSource(s)


def _amazon_scraper(s: Settings) -> DataSource:
    from .amazon.scraper import ScraperSource
    return ScraperSource(s)


def _amazon_mock(s: Settings) -> DataSource:
    from .amazon.mock import MockSource
    return MockSource()


# platform → {source_name: factory}。source_name 取值：api / scraper / mock。
PLATFORMS: Dict[str, Dict[str, SourceFactory]] = {
    "amazon": {"api": _amazon_api, "scraper": _amazon_scraper, "mock": _amazon_mock},
    # "ebay":   {"scraper": _ebay_scraper, "mock": _ebay_mock},   # 以后加平台照此追加
}


def supported_platforms() -> List[str]:
    return list(PLATFORMS.keys())


def _norm(platform: str) -> str:
    # 平台名大小写/空格不敏感（模型常传 "Amazon"），键统一按小写匹配。
    return (platform or "").strip().lower()


def has_platform(platform: str) -> bool:
    return _norm(platform) in PLATFORMS


def available_sources(platform: str) -> Dict[str, SourceFactory]:
    return PLATFORMS.get(_norm(platform), {})


def make_source(platform: str, name: str, settings: Settings) -> DataSource:
    return PLATFORMS[_norm(platform)][name](settings)
