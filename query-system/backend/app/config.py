"""应用配置。

通过环境变量 / .env 文件读取。参见 backend/.env.example。
"""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
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
    # context.close()/browser.close()/pw.stop() 这几个调用没有内置超时保护：正常
    # 情况下是纯本机 IPC（不涉及网络）。实测过两组：15 轮空白页 p50≈60ms/max≈85ms；
    # 5 轮真实 Amazon 列表页/详情页（大图/A+内容/评论区，~5000-8800 DOM 节点）
    # max≈113ms——数据量大确实会变慢，但幅度不大（约 1.5~2 倍），量级还是毫秒级。
    # 一次搜索（top_n 个商品 × 详情/评论/QA 各开一次 context）最多可能触发几十次
    # close，每次都按超时上限等的话会累加，所以没有直接套「60 倍冗余」给 5 秒，
    # 而是收紧到约 15 倍冗余：单次泄漏的影响可控，累计上限也不会失控到几分钟。
    scraper_close_timeout_s: float = Field(default=1.5, gt=0)
    scraper_headless: bool = True
    # 进商品详情页抓准确品牌（更慢、更易触发反爬，可关）
    scraper_fetch_brand: bool = True
    # 是否抓买家问答（Amazon 多已下线，默认关：省一半请求、降封号）
    scraper_fetch_qa: bool = False
    # 出口代理（住宅/机房），换 IP 绕开亚马逊对数据中心 IP 的反爬。
    # 格式：http://user:pass@host:port（或 http://host:port）；空=直连。
    scraper_proxy: str = ""
    # 代理池：逗号分隔的多个代理，抓取时轮换，进一步分散风控。留空则退回单个
    # scraper_proxy；两者都空 = 直连。机房 IP 抓 Amazon 极易被限，强烈建议配住宅代理池。
    scraper_proxies: str = ""
    # 爬虫通道全局并发上限：同一时刻最多几个搜索请求可以同时用 scraper 通道
    # （每个请求会各自起一个 Chromium）。_enrich 里对同一次搜索已做串行+延时，
    # 但不同搜索请求之间原本互不限制，并发一高就会同时起多个浏览器打 Amazon，
    # 违背降封号的设计意图。默认 1 = 全局串行；配了代理池可以调大。
    # ge=1：0 会让 Semaphore 永远拿不到许可（死锁），负数会在创建 Semaphore 时报错。
    scraper_max_concurrency: int = Field(default=1, ge=1)

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

    def proxy_pool(self) -> list:
        """解析代理池：优先用 scraper_proxies（逗号分隔），否则退回单个 scraper_proxy。"""
        pool = [p.strip() for p in self.scraper_proxies.split(",") if p.strip()]
        if not pool and self.scraper_proxy.strip():
            pool = [self.scraper_proxy.strip()]
        return pool


@lru_cache
def get_settings() -> Settings:
    return Settings()
