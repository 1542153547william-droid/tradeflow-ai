"""Amazon Mock 数据源（分层结构，通用字段名）。

用于在没有 API Key、且不便实时爬取（沙箱/演示/CI）时，生成结构真实、可复现
的样例数据。数据由关键词/product_id 做种子确定性生成 —— 同一输入每次结果一致。
"""
from __future__ import annotations

import hashlib
import random
from typing import List

from ...models import (
    BaseInfo,
    Content,
    Coupon,
    Logistics,
    Pricing,
    Product,
    QA,
    RankNode,
    Review,
    SearchContext,
)
from ..base import DataSource

_BRANDS = [
    "Anker", "Sony", "Logitech", "SAMSUNG", "Bose", "TP-Link",
    "AmazonBasics", "UGREEN", "Baseus", "SoundPeats", "JBL", "Razer",
]
_BADGES = ["Best Seller", "Amazon's Choice", "", "", ""]
_FULFILL = ["Amazon", "FBA", "FBM"]

_POS_SNIPPETS = [
    "works great and the build quality is excellent",
    "great value for the price, highly recommend",
    "battery life is amazing, lasts all day",
    "easy to set up and very reliable so far",
    "sound quality exceeded my expectations",
    "sleek design and feels premium in hand",
]
_NEG_SNIPPETS = [
    "stopped working after two weeks, disappointed",
    "the connection keeps dropping randomly",
    "cheaper materials than i expected, feels flimsy",
    "customer support was slow to respond",
]
_NEU_SNIPPETS = [
    "it is okay, does what it says",
    "average product, nothing special",
    "fine for the price but there are better options",
]


def _seeded_rng(*parts: str) -> random.Random:
    h = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    return random.Random(int(h[:16], 16))


class MockSource(DataSource):
    name = "mock"
    platform = "amazon"

    async def search_top_products(
        self, keyword: str, marketplace: str, limit: int = 10
    ) -> List[Product]:
        rng = _seeded_rng("products", keyword, marketplace)
        products: List[Product] = []
        organic = 0
        sponsored = 0
        for i in range(limit):
            brand = rng.choice(_BRANDS)
            pid = "B0" + "".join(rng.choice("0123456789ABCDEFGHJKLMNPQRSTUVWXYZ") for _ in range(8))
            price = round(rng.uniform(9.99, 199.99), 2)
            has_discount = rng.random() < 0.5
            list_price = round(price * rng.uniform(1.1, 1.6), 2) if has_discount else None
            discount = round((1 - price / list_price) * 100, 1) if list_price else None
            is_sponsored = rng.random() < 0.25
            if is_sponsored:
                sponsored += 1
            else:
                organic += 1
            badge = rng.choice(_BADGES)
            coupon = None
            if rng.random() < 0.3:
                amt = rng.choice([5, 10, 15])
                coupon = Coupon(type="percent", value=float(amt), text=f"Save {amt}%")
            is_prime = rng.random() < 0.8
            products.append(Product(
                search_context=SearchContext(
                    keyword=keyword,
                    organic_rank=None if is_sponsored else organic,
                    sponsored_rank=sponsored if is_sponsored else None,
                ),
                base_info=BaseInfo(
                    product_id=pid,
                    platform="amazon",
                    brand=brand,
                    title=f"{brand} {keyword.title()} "
                    f"{rng.choice(['Pro', 'Max', 'Plus', 'Lite', 'Ultra', ''])} "
                    f"Model {rng.randint(100, 999)}".strip(),
                    image_url=f"https://m.media-amazon.com/images/I/{pid}.jpg",
                    product_url=f"https://www.{marketplace}/dp/{pid}",
                    rating=round(rng.uniform(3.5, 5.0), 1),
                    review_count=rng.randint(20, 45000),
                    badges=[badge] if badge else [],
                    platform_extra={"is_prime": is_prime},
                ),
                pricing=Pricing(
                    price=price,
                    list_price=list_price,
                    currency="USD",
                    discount_pct=discount,
                    coupon=coupon,
                    fast_shipping=is_prime,
                ),
            ))
        return products

    async def fetch_detail(self, product: Product, marketplace: str) -> None:
        rng = _seeded_rng("detail", product.base_info.product_id)
        product.base_info.parent_id = "B0" + "".join(
            rng.choice("0123456789ABCDEFGHJKLMNPQRSTUVWXYZ") for _ in range(8))
        product.base_info.rank = rng.randint(1, 5000)
        product.base_info.rank_category = rng.choice(
            ["Electronics", "Office Products", "Home & Kitchen", "Sports & Outdoors"])
        product.base_info.rank_sub_nodes = [
            RankNode(node=rng.choice(["Headphones", "Chargers", "Yoga Mats", "Keyboards"]),
                     rank=rng.randint(1, 300))
        ]
        product.logistics = Logistics(
            seller=f"{product.base_info.brand} Store",
            fulfillment=rng.choice(_FULFILL),
            dimensions=f"{rng.uniform(3, 20):.1f} x {rng.uniform(3, 15):.1f} x {rng.uniform(1, 10):.1f}",
            weight=round(rng.uniform(0.2, 8.0), 1),
        )
        product.content = Content(
            bullet_points=[f"{product.base_info.brand} 卖点 {j+1}：耐用/易用/高性价比" for j in range(5)],
            description="示例产品描述：适用于多种场景，用料扎实，做工精细。",
            image_count=rng.randint(4, 9),
            has_video=rng.random() < 0.5,
            child_id=product.base_info.product_id,
            variant_attributes={"Color": rng.choice(["Black", "White", "Blue"]),
                                "Size": rng.choice(["S", "M", "L"])},
        )

    async def fetch_reviews(
        self, product_id: str, marketplace: str, limit: int = 40
    ) -> List[Review]:
        rng = _seeded_rng("reviews", product_id)
        reviews: List[Review] = []
        n = min(limit, rng.randint(8, limit))
        for k in range(n):
            roll = rng.random()
            if roll < 0.6:
                body, rating = rng.choice(_POS_SNIPPETS), rng.choice([4.0, 5.0])
            elif roll < 0.8:
                body, rating = rng.choice(_NEU_SNIPPETS), 3.0
            else:
                body, rating = rng.choice(_NEG_SNIPPETS), rng.choice([1.0, 2.0])
            reviews.append(Review(
                product_id=product_id,
                review_id=f"R{rng.randint(10**9, 10**10)}",
                author=f"user{rng.randint(1000, 9999)}",
                rating=rating,
                title=body[:30],
                body=body,
                date=f"2026-{rng.randint(1, 6):02d}-{rng.randint(1, 28):02d}",
                country="United States",
                variant_purchased=rng.choice(["Color: Black", "Color: White | Size: L", None]),
                helpful_votes=rng.randint(0, 120),
                has_buyer_media=rng.random() < 0.2,
            ))
        return reviews

    async def fetch_qa(self, product_id: str, marketplace: str, limit: int = 10) -> List[QA]:
        rng = _seeded_rng("qa", product_id)
        if rng.random() < 0.5:
            return []  # 模拟亚马逊多数商品已无 Q&A
        return [QA(question_id=f"Q{rng.randint(10**6, 10**7)}",
                   question_text="Is it compatible with older models?",
                   answer_text="Yes, it works with most previous generations.")]
