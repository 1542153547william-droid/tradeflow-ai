"""0.5 /api/product/{asin}：SearchService.get_product 的单测（mock 数据源）。

Run: python -m unittest tests.test_product   （在 backend/ 目录下）
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
from app.services.search_service import SearchService  # noqa: E402


def _service() -> SearchService:
    tmp = os.path.join(tempfile.gettempdir(), "tf_test_cache.db")
    settings = Settings(data_source_mode="mock", cache_db_path=tmp)
    return SearchService(settings, CacheStore(settings.cache_db_path, settings.cache_ttl_hours))


class TestGetProduct(unittest.TestCase):
    def test_returns_full_product_with_variants_and_reviews(self):
        svc = _service()
        result = asyncio.run(svc.get_product("amazon", "B0UNIT0001", "amazon.com"))
        self.assertEqual(len(result.products), 1)
        p = result.products[0]
        self.assertEqual(p.base_info.product_id, "B0UNIT0001")
        self.assertTrue(p.base_info.title)                 # Listing 标题
        self.assertTrue(p.content.variant_attributes)      # 变体维度
        self.assertEqual(len(p.content.bullet_points), 5)  # 五点
        self.assertTrue(p.reviews_sample)                  # 评价
        self.assertIsNotNone(result.review_analysis)       # 评论情感分析
        self.assertGreater(result.review_analysis.total_reviews, 0)

    def test_deterministic_by_asin(self):
        # 同一 ASIN 两次（第二次走缓存）→ 同一产品。
        svc = _service()
        a = asyncio.run(svc.get_product("amazon", "B0UNIT0002", "amazon.com"))
        b = asyncio.run(svc.get_product("amazon", "B0UNIT0002", "amazon.com"))
        self.assertEqual(a.products[0].base_info.brand, b.products[0].base_info.brand)

    def test_unknown_platform_raises(self):
        svc = _service()
        with self.assertRaises(RuntimeError):
            asyncio.run(svc.get_product("nonexistent", "B0X", "x"))


if __name__ == "__main__":
    unittest.main()
