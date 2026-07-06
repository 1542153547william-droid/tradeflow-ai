"""端到端冒烟测试（无需 pytest，直接 `python tests/smoke_test.py` 运行）。

覆盖：
- MockSource 生成 TOP10 且可复现
- SearchService 数据源回退（api 失败 → scraper 失败 → mock 成功）
- 评论分析产出情感与关键词
- 缓存命中
- Excel / CSV 导出可生成且非空
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile

# Windows 默认控制台为 GBK，直接 print emoji 会 UnicodeEncodeError；强制 UTF-8 输出。
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.cache.store import CacheStore  # noqa: E402
from app.config import Settings  # noqa: E402
from app.datasources.base import DataSource, DataSourceError  # noqa: E402
from app.datasources.mock_source import MockSource  # noqa: E402
from app.models import SearchRequest  # noqa: E402
from app.services import export_service  # noqa: E402
from app.services.review_analysis import analyze_reviews  # noqa: E402
from app.services.search_service import SearchService  # noqa: E402

_passed = 0
_failed = 0


def check(name: str, cond: bool, extra: str = ""):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  ✅ {name}")
    else:
        _failed += 1
        print(f"  ❌ {name}  {extra}")


class BoomSource(DataSource):
    """总是失败的数据源，用于验证回退。"""

    name = "boom"

    async def search_top_products(self, keyword, marketplace, limit=10):
        raise DataSourceError("boom")

    async def fetch_reviews(self, asin, marketplace, limit=40):
        raise DataSourceError("boom")


async def test_mock_source():
    print("[1] MockSource")
    src = MockSource()
    p1 = await src.search_top_products("wireless earbuds", "amazon.com", 10)
    p2 = await src.search_top_products("wireless earbuds", "amazon.com", 10)
    check("返回 TOP10", len(p1) == 10, f"got {len(p1)}")
    check("排名连续 1..10", [p.position for p in p1] == list(range(1, 11)))
    check("确定性可复现", [p.asin for p in p1] == [p.asin for p in p2])
    check("含价格字段", all(p.price is not None for p in p1))
    reviews = await src.fetch_reviews(p1[0].asin, "amazon.com", 40)
    check("能取到评论", len(reviews) > 0, f"got {len(reviews)}")


async def test_fallback():
    print("[2] SearchService 回退 (boom → mock)")
    settings = Settings(data_source_mode="mock", cache_db_path=_tmpdb())
    svc = SearchService(settings, CacheStore(settings.cache_db_path, 24))

    # 强制链条：先 boom 再 mock
    svc._build_chain = lambda: ["boom", "mock"]  # type: ignore
    orig = svc._make_source

    def make(name):
        return BoomSource() if name == "boom" else MockSource()

    svc._make_source = make  # type: ignore
    result = await svc.search(SearchRequest(keyword="usb c cable", include_reviews=True))
    check("回退到 mock 成功", result.source == "mock", f"source={result.source}")
    check("有 10 个产品", len(result.products) == 10)
    check("有评论分析", result.review_analysis is not None)
    svc._make_source = orig  # type: ignore


async def test_review_analysis():
    print("[3] 评论分析")
    src = MockSource()
    reviews = await src.fetch_reviews("B0TEST0001", "amazon.com", 40)
    ra = analyze_reviews(reviews)
    check("统计到评论数", ra.total_reviews == len(reviews))
    check("情感得分在 0..1", 0.0 <= ra.sentiment_score <= 1.0, f"{ra.sentiment_score}")
    check("占比之和≈1", abs(ra.positive_ratio + ra.neutral_ratio + ra.negative_ratio - 1.0) < 0.01)
    check("提取到关键词", len(ra.top_keywords) > 0)


async def test_cache():
    print("[4] 缓存命中")
    settings = Settings(data_source_mode="mock", cache_db_path=_tmpdb())
    svc = SearchService(settings, CacheStore(settings.cache_db_path, 24))
    r1 = await svc.search(SearchRequest(keyword="mechanical keyboard"))
    r2 = await svc.search(SearchRequest(keyword="mechanical keyboard"))
    check("首次非缓存", r1.cached is False, f"cached={r1.cached}")
    check("二次命中缓存", r2.cached is True and r2.source == "cache", f"source={r2.source}")
    r3 = await svc.search(SearchRequest(keyword="mechanical keyboard", force_refresh=True))
    check("force_refresh 绕过缓存", r3.cached is False)


async def test_export():
    print("[5] 导出")
    settings = Settings(data_source_mode="mock", cache_db_path=_tmpdb())
    svc = SearchService(settings, CacheStore(settings.cache_db_path, 24))
    result = await svc.search(SearchRequest(keyword="gaming mouse"))
    xlsx, mt_x, fn_x = export_service.export(result, "xlsx")
    csv, mt_c, fn_c = export_service.export(result, "csv")
    check("xlsx 非空且是 zip 头", len(xlsx) > 500 and xlsx[:2] == b"PK", f"len={len(xlsx)}")
    check("xlsx 文件名正确", fn_x.endswith(".xlsx"))
    check("csv 非空含表头", b"ASIN" in csv, "")
    check("csv 文件名正确", fn_c.endswith(".csv"))


def _tmpdb() -> str:
    return os.path.join(tempfile.mkdtemp(), "cache.db")


async def main():
    await test_mock_source()
    await test_fallback()
    await test_review_analysis()
    await test_cache()
    await test_export()
    print(f"\n结果：{_passed} 通过 / {_failed} 失败")
    return 0 if _failed == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
