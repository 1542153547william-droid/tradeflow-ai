# 集成说明：TradeFlow-AI ⇄ 多平台商品查询系统

TradeFlow-AI 通过 HTTP 工具调用独立的 **多平台商品查询系统**（Starlette 服务）
获取市场数据。两者**松耦合**：只通过一份 **API 契约**对接。查询系统按 `platform`
路由到各平台的数据源（目前 amazon；框架可扩 ebay/walmart…）。

## 连接方式

```
TradeFlow-AI                          查询系统
tradeflow/tools/amazon.py  ──HTTP──▶  POST /api/search   (带 platform)
  @tool search_products               GET  /api/platforms
  @tool list_platforms       ▲
                    settings.amazon_api_url (env: AMAZON_API_URL)
```

- 耦合点只有一个文件：[`tradeflow/tools/amazon.py`](tradeflow/tools/amazon.py)
- 服务地址：`config/settings.py::amazon_api_url`（env `AMAZON_API_URL`）

## 契约 = `/api/search`

**请求**：`{"keyword", "platform"?, "marketplace"?, "top_n"?, "include_reviews"?, "include_detail"?, "force_refresh"?}`

**返回**（`SearchResult`）：`keyword / platform / marketplace / fetched_at /
source / products[] / review_analysis / cached`。每个 product 为**平台无关的通用
分层结构**——核心字段跨平台保证有，平台专属字段放 `base_info.platform_extra`：

```
product = {
  search_context: {keyword, organic_rank, sponsored_rank},
  base_info:      {product_id, platform, parent_id, brand, title, rating,
                   review_count, badges[], rank, rank_category, rank_sub_nodes[],
                   platform_extra{}},
  pricing:        {price, list_price, currency, discount_pct, coupon,
                   fast_shipping, is_deal, price_history[]},
  logistics:      {seller, fulfillment, dimensions, weight},
  content:        {bullet_points[], description, rich_content, image_count,
                   has_video, variant_attributes},
  reviews_sample: [{product_id, rating, body, author, date, country, helpful_votes, ...}],
  qa_sample:      [...]
}
```

> **通用核心字段跨平台稳定可依赖**；`platform_extra` 因平台而异（Amazon: is_prime
> 原值等）。TradeFlow 的 Agent 应主要依赖通用核心，需要平台深度时再读 platform_extra。

工具把这份 JSON（去掉 `base_info.image_url`、`content.rich_content`、
`pricing.price_history` 以省 token）原样交给模型。`list_platforms` 工具对应
`GET /api/platforms`。

## 改 Amazon 查询系统时，TradeFlow 要不要跟着改？

| Amazon 侧的改动 | TradeFlow 要改吗 |
|---|---|
| 爬虫抓得更准/更快、修 bug、抗封 | **不用**。数据质量提升在运行时自动流过来 |
| 返回**新增字段**（BSR 细分、广告位标记…） | **基本不用**。新字段自动进入模型；除非想裁剪省 token 或在工具描述里点明含义 |
| **新增接口**（如 `/api/product/{asin}`） | **要**。在 `tools/amazon.py` 加一个新 `@tool` |
| **改请求参数 / 破坏性改返回**（改名、删字段、改语义） | **要**。改工具的 httpx 调用 + docstring |

**一句话**：只有「加新接口」或「破坏性改契约」才动 TradeFlow；单纯把爬虫做好不用。

## 纪律

- 把 `/api/search` 的请求/返回当作**契约**来维护。
- 尽量**加字段而非改字段**，保持向后兼容，TradeFlow 就不用跟着改。
- 契约真变了，同步更新 `tools/amazon.py`（调用 + docstring）。

## 版本管理与部署

- **两个独立仓库**，各自提交、各自部署。不合并、不用 submodule。
- 上线 = 两个服务都部署好 + TradeFlow 的 `AMAZON_API_URL` 指向查询系统（内网地址）。
  爬虫升级只需重启查询系统服务，TradeFlow 通常不必重新发版（除非契约变了）。
