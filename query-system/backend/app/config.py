"""应用配置。

通过环境变量 / .env 文件读取。参见 backend/.env.example。
"""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # ---- 数据源选择 ----
    # auto : 有 API_KEY 用 api；否则若 SCRAPER_ENABLED 用 scraper；再否则用 mock
    # api / scraper / mock : 强制使用对应数据源
    data_source_mode: Literal["auto", "api", "scraper", "mock"] = "auto"
    # 真实数据源（api/scraper）失败时，是否回退到示例数据（mock）。
    # 默认 False：直接报「查询失败」，避免用假数据冒充成功（调试爬虫时尤其重要）。
    # 需要离线演示时设 True 恢复旧的兜底行为。
    allow_mock_fallback: bool = False

    # ---- 第三方 API（Rainforest 风格，可换供应商）----
    api_provider: str = "rainforest"
    api_key: str = ""
    api_base_url: str = "https://api.rainforestapi.com/request"

    # ---- 爬虫 ----
    scraper_enabled: bool = True
    # 复用远程环境预装的 Chromium；本地留空则用 Playwright 默认
    chromium_path: str = ""
    scraper_min_delay: float = 1.5  # 每次请求最小随机延时（秒）
    scraper_max_delay: float = 4.0
    scraper_timeout_ms: int = 30000
    scraper_headless: bool = True
    # 进商品详情页抓准确品牌（更慢、更易触发反爬，可关）
    scraper_fetch_brand: bool = True
    # 是否抓买家问答（Amazon 多已下线，默认关：省一半请求、降封号）
    scraper_fetch_qa: bool = False

    # ---- 通用 ----
    default_platform: str = "amazon"     # 未指定 platform 时的默认平台
    marketplace: str = "amazon.com"
    top_n: int = 10
    review_sample_size: int = 40  # 每个 ASIN 抓取评论数上限
    cache_ttl_hours: int = 24
    cache_db_path: str = "cache.db"

    request_timeout: float = 30.0

    @property
    def resolved_source(self) -> str:
        """根据配置解析实际启用的数据源模式。"""
        if self.data_source_mode != "auto":
            return self.data_source_mode
        if self.api_key:
            return "api"
        if self.scraper_enabled:
            return "scraper"
        return "mock"


@lru_cache
def get_settings() -> Settings:
    return Settings()
