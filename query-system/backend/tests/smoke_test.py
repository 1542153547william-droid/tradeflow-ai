"""端到端冒烟单测（分层模型 + 当前 API）。

覆盖：MockSource TOP-N 可复现且字段分层、评论情感分析、SearchService(mock) 搜索、
缓存写入、Excel/CSV 导出。原扁平模型脚本（p.position/p.asin、mock_source 模块）已
按当前分层结构（base_info/pricing/…）与 registry 化的数据源重写。

Run: python -m unittest tests.smoke_test   （在 backend/ 目录下）
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.cache.store import CacheStore  # noqa: E402
from app.config import Settings  # noqa: E402
from app.datasources.amazon.mock import MockSource  # noqa: E402
from app.models import SearchRequest  # noqa: E402
from app.services import export_service  # noqa: E402
from app.services.review_analysis import analyze_reviews  # noqa: E402
from app.services.search_service import SearchService  # noqa: E402


def _service():
    tmp = os.path.join(tempfile.mkdtemp(), "cache.db")
    settings = Settings(data_source_mode="mock", cache_db_path=tmp)
    svc = SearchService(settings, CacheStore(settings.cache_db_path, settings.cache_ttl_hours))
    return svc, settings


class TestMockSource(unittest.TestCase):
    def test_top_n_deterministic_layered(self):
        src = MockSource()
        p1 = asyncio.run(src.search_top_products("wireless earbuds", "amazon.com", 10))
        p2 = asyncio.run(src.search_top_products("wireless earbuds", "amazon.com", 10))
        self.assertEqual(len(p1), 10)
        self.assertTrue(all(p.base_info.product_id for p in p1))   # 分层：商品ID
        self.assertTrue(all(p.pricing.price is not None for p in p1))  # 分层：价格
        self.assertEqual([p.base_info.product_id for p in p1],
                         [p.base_info.product_id for p in p2])     # 确定性可复现

    def test_reviews_and_analysis(self):
        src = MockSource()
        reviews = asyncio.run(src.fetch_reviews("B0TEST0001", "amazon.com", 40))
        self.assertGreater(len(reviews), 0)
        ra = analyze_reviews(reviews)
        self.assertEqual(ra.total_reviews, len(reviews))
        self.assertTrue(0.0 <= ra.sentiment_score <= 1.0)
        self.assertLess(
            abs(ra.positive_ratio + ra.neutral_ratio + ra.negative_ratio - 1.0), 0.01)
        self.assertTrue(ra.top_keywords)


class TestSearchServiceMock(unittest.TestCase):
    def test_search_returns_products_and_analysis(self):
        svc, _ = _service()
        result = asyncio.run(svc.search(
            SearchRequest(keyword="usb c cable", include_reviews=True)))
        self.assertEqual(result.source, "mock")
        self.assertEqual(len(result.products), 10)
        self.assertIsNotNone(result.review_analysis)

    def test_cache_written(self):
        svc, settings = _service()
        asyncio.run(svc.search(SearchRequest(keyword="mechanical keyboard")))
        key = CacheStore.make_key(
            "amazon", "mechanical keyboard", settings.marketplace, settings.top_n)
        self.assertIsNotNone(svc.cache.get(key))   # 结果已写入缓存


class TestExport(unittest.TestCase):
    def _result(self):
        svc, _ = _service()
        return asyncio.run(svc.search(SearchRequest(keyword="gaming mouse")))

    def test_xlsx(self):
        data, _mt, fn = export_service.export(self._result(), "xlsx")
        self.assertTrue(len(data) > 500 and data[:2] == b"PK")  # xlsx = zip 头
        self.assertTrue(fn.endswith(".xlsx"))

    def test_csv(self):
        data, _mt, fn = export_service.export(self._result(), "csv")
        self.assertIn("商品ID".encode("utf-8"), data)   # 当前中文表头
        self.assertTrue(fn.endswith(".csv"))


if __name__ == "__main__":
    unittest.main()
