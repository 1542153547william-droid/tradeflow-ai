"""Pydantic 数据模型 —— 多平台通用的数据契约（分层结构）。

设计原则（为对接 TradeFlow 跨平台分析）：
  * **通用核心字段**用平台无关的名字（product_id/price/rank/seller/fast_shipping…），
    所有电商平台都保证有 → TradeFlow 的 Agent 跨平台无需改。
  * **平台专属字段**放进 base_info.platform_extra（Amazon: is_prime原值/bsr细分；
    eBay: sold_count/condition…），需要平台深度时再读。

分层：
  search_context  列表页上下文（关键词 / 自然排名 / 广告排名）
  base_info       身份与口碑（product_id/品牌/标题/评分/评论数/徽章/排名 + platform_extra）
  pricing         价格与促销（现价/原价/折扣/优惠券/快速配送）
  logistics       物流与卖家（卖家/发货/尺寸/重量）
  content         Listing 内容（卖点/描述/富文本/图片数/视频/变体）
  reviews_sample  评论抽样
  qa_sample       买家问答抽样
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

# 抓取步骤状态：not_fetched=未请求 / ok=成功(含确实为空) / blocked=被拦截 /
# timeout=超时 / error=其它异常。detail_status/reviews_status/qa_status 共用。
STATUS_LITERAL = Literal["not_fetched", "ok", "blocked", "timeout", "error"]


# ---- 列表页上下文 ----
class SearchContext(BaseModel):
    keyword: str
    organic_rank: Optional[int] = None   # 自然结果中的排名（非广告位）
    sponsored_rank: Optional[int] = None  # 广告结果中的排名


# ---- 排名节点（通用：Amazon=BSR 子类目，其它平台=对应类目排名）----
class RankNode(BaseModel):
    node: str
    rank: int


# ---- 身份与口碑（通用核心）----
class BaseInfo(BaseModel):
    product_id: str                       # 平台商品ID（Amazon=ASIN, eBay=item id…）
    platform: str = "amazon"
    parent_id: Optional[str] = None       # 父体（如有变体架构）
    brand: Optional[str] = None
    title: str = ""
    image_url: Optional[str] = None
    product_url: Optional[str] = None
    rating: Optional[float] = None        # 平均星级 0-5
    review_count: Optional[int] = None
    badges: List[str] = Field(default_factory=list)  # Best Seller / Amazon's Choice ...
    rank: Optional[int] = None            # 通用销量排名（Amazon=BSR 主排名）
    rank_category: Optional[str] = None   # 排名所属类目
    rank_sub_nodes: List[RankNode] = Field(default_factory=list)
    platform_extra: Dict[str, Any] = Field(default_factory=dict)  # 平台专属原始字段


# ---- 价格与促销 ----
class Coupon(BaseModel):
    type: Optional[Literal["fixed", "percent"]] = None
    value: Optional[float] = None
    text: Optional[str] = None


class PricePoint(BaseModel):
    """历史价格/排名的一个每日快照点（历史从接入之日起往后累积）。"""
    date: str
    price: Optional[float] = None
    currency: str = "USD"
    rank: Optional[int] = None


class Pricing(BaseModel):
    price: Optional[float] = None         # 当前售价
    list_price: Optional[float] = None    # 划线价/原价
    currency: str = "USD"
    discount_pct: Optional[float] = None
    coupon: Optional[Coupon] = None
    is_deal: bool = False                 # 是否秒杀/限时特价
    fast_shipping: bool = False           # 快速配送标记（Amazon=Prime）
    price_history: List[PricePoint] = Field(default_factory=list)


# ---- 物流与卖家 ----
class Logistics(BaseModel):
    seller: Optional[str] = None          # 卖家（Amazon=BuyBox 卖家）
    fulfillment: Optional[str] = None     # 发货模式（Amazon: Amazon/FBA/FBM）
    dimensions: Optional[str] = None      # 尺寸（长×宽×高）
    weight: Optional[float] = None        # 重量（磅）


# ---- Listing 内容 ----
class Content(BaseModel):
    bullet_points: List[str] = Field(default_factory=list)  # 卖点短句（Amazon=五点）
    description: Optional[str] = None
    rich_content: Optional[str] = None    # 富文本图文（Amazon=A+）
    image_count: Optional[int] = None
    has_video: bool = False
    child_id: Optional[str] = None
    variant_attributes: Optional[Dict[str, str]] = None  # {"Color": "Black", "Size": "L"}


# ---- 评论 ----
class Review(BaseModel):
    product_id: str
    review_id: Optional[str] = None
    author: Optional[str] = None
    rating: Optional[float] = None        # 1-5
    title: Optional[str] = None
    body: str = ""
    date: Optional[str] = None
    country: Optional[str] = None
    variant_purchased: Optional[str] = None
    helpful_votes: Optional[int] = None
    has_buyer_media: bool = False


# ---- 买家问答 ----
class QA(BaseModel):
    question_id: Optional[str] = None
    question_text: str = ""
    answer_text: Optional[str] = None


# ---- 关键词 / 评论聚合分析（平台无关）----
class KeywordWeight(BaseModel):
    keyword: str
    weight: float


class ReviewAnalysis(BaseModel):
    total_reviews: int = 0
    sentiment_score: float = 0.0
    positive_ratio: float = 0.0
    neutral_ratio: float = 0.0
    negative_ratio: float = 0.0
    top_keywords: List[KeywordWeight] = Field(default_factory=list)
    language: str = "auto"


# ---- 一个商品的完整分层载荷 ----
class Product(BaseModel):
    search_context: SearchContext
    base_info: BaseInfo
    pricing: Pricing = Field(default_factory=Pricing)
    logistics: Logistics = Field(default_factory=Logistics)
    content: Content = Field(default_factory=Content)
    reviews_sample: List[Review] = Field(default_factory=list)
    qa_sample: List[QA] = Field(default_factory=list)
    # 各富化步骤的抓取状态：区分字段/列表为空是因为被拦截/超时，还是确实没有。
    #   not_fetched=未请求该步骤  ok=抓取成功（可能确实是 0 条）
    #   blocked=被平台拦截(验证码/机器人页)  timeout=打开页面超时  error=其它异常
    # 模型/前端应基于这些字段提示用户数据不完整，而不是把抓取失败当成该商品没有评论。
    detail_status: STATUS_LITERAL = "not_fetched"
    reviews_status: STATUS_LITERAL = "not_fetched"
    qa_status: STATUS_LITERAL = "not_fetched"


class SearchResult(BaseModel):
    """一次搜索的完整返回。"""

    keyword: str
    platform: str = "amazon"
    marketplace: str                      # 站点/区域（Amazon: amazon.com 等）
    fetched_at: datetime
    source: Literal["api", "scraper", "mock", "cache"]
    products: List[Product] = Field(default_factory=list)
    review_analysis: Optional[ReviewAnalysis] = None
    cached: bool = False


class SearchRequest(BaseModel):
    keyword: str = Field(..., min_length=1, max_length=200)
    platform: str = "amazon"              # 目标平台（amazon / ebay / walmart …）
    marketplace: Optional[str] = None
    top_n: Optional[int] = Field(default=None, ge=1, le=20)
    # Low-frequency MVP defaults: one search page only. Detail/review enrichment
    # must be explicitly requested because each item otherwise opens more pages.
    include_reviews: bool = False
    include_detail: bool = False
    force_refresh: bool = False
