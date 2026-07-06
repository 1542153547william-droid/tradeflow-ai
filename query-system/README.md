# Amazon 关键词查询分析系统

输入关键词 → 抓取 Amazon 上该关键词相关的 **TOP N（默认 10）产品** → 结构化返回、可视化展示、可导出报表。

后端基于 **Python + Starlette（异步 ASGI）**，前端为**零构建的单文件 Web 应用**（后端直接托管）。

---

## ✨ 功能

- **关键词查询**：输入关键词，返回 Amazon TOP10 产品。
- **双通道数据获取**（自动回退）：
  1. **官方/第三方 API**（Rainforest 风格，合规、稳定）—— 配置 `API_KEY` 后优先使用；
  2. **浏览器爬虫**（Playwright）—— 无 Key 时回退；
  3. **示例数据（mock）**—— 前两者都不可用时兜底，保证离线可演示。
- **全量字段**：标题 / 品牌 / ASIN / 主图 / 链接 / 价格 / 原价 / 折扣 / 评分 / 评论数 / BSR / Prime。
- **评论分析**：情感打分（正/中/负占比）+ 高频关键词提取。
- **可视化**：价格对比、评分对比、情感占比、关键词。
- **导出报表**：一键导出 **Excel（含两张表）** 或 **CSV**。
- **SQLite 缓存**：相同关键词 24h 内命中缓存，降低抓取频率。

---

## 🏗️ 架构

```
前端 (单文件 HTML/JS)  ──HTTP/JSON──▶  Starlette 后端
                                        └ SearchService（编排 + 回退 + 缓存）
                                            ├ ApiSource     (httpx → 第三方 API)
                                            ├ ScraperSource (Playwright 爬虫)
                                            └ MockSource    (确定性示例数据)
                                        ReviewAnalysis / ExportService / SQLite 缓存
```

数据源统一实现 `DataSource` 抽象接口（`search_top_products` / `fetch_reviews`），可插拔。
回退顺序：`api → scraper → mock`（任一失败自动降级，mock 永远兜底）。

---

## 🚀 快速开始

### 1. 安装依赖

```bash
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 使用爬虫通道时，安装 Playwright 浏览器（首次）
playwright install chromium
```

> 说明：`starlette / uvicorn / pydantic / httpx / openpyxl / playwright / scikit-learn` 为必需；
> `vaderSentiment / jieba / snownlp` 为评论分析增强项，**缺失时代码会自动回退**到基于星级/词频的实现，不会报错。

### 2. 配置（可选）

```bash
cp .env.example .env
# 编辑 .env：填入 API_KEY 走合规 API；留空则用爬虫/示例数据
```

### 3. 启动

```bash
# 在 backend/ 目录下
uvicorn app.main:app --reload --port 8000
```

浏览器打开 **http://127.0.0.1:8000/** 即可使用（前端由后端托管）。

---

## 🔌 API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET  | `/api/health` | 健康检查，返回当前解析到的数据源 |
| GET  | `/api/config` | 返回站点 / TOP_N / 数据源配置 |
| POST | `/api/search` | 查询：`{"keyword","marketplace?","top_n?","include_reviews?","force_refresh?"}` |
| GET  | `/api/export` | 导出：`?keyword=...&fmt=xlsx|csv&top_n=...&marketplace=...` |

示例：

```bash
curl -X POST http://127.0.0.1:8000/api/search \
  -H "Content-Type: application/json" \
  -d '{"keyword":"wireless earbuds","top_n":10,"include_reviews":true}'
```

---

## ⚙️ 配置项（.env）

| 变量 | 默认 | 说明 |
|------|------|------|
| `DATA_SOURCE_MODE` | `auto` | `auto` / `api` / `scraper` / `mock` |
| `API_KEY` | 空 | 第三方 API Key（填入后 auto 优先走 API） |
| `API_BASE_URL` | Rainforest | 第三方 API 地址 |
| `SCRAPER_ENABLED` | `true` | 是否启用爬虫回退 |
| `CHROMIUM_PATH` | 空 | 自定义 Chromium 路径（留空用 Playwright 默认） |
| `SCRAPER_MIN_DELAY`/`MAX_DELAY` | 1.5 / 4.0 | 爬虫随机延时（秒），控频防封 |
| `MARKETPLACE` | `amazon.com` | 默认站点 |
| `TOP_N` | `10` | 返回产品数 |
| `CACHE_TTL_HOURS` | `24` | 缓存有效期 |

---

## 🧪 测试

```bash
cd backend
python tests/smoke_test.py     # 无需 pytest，覆盖数据源/回退/分析/缓存/导出
# 或（若已安装 pytest）
pytest
```

---

## ⚠️ 合规与免责声明

Amazon 的服务条款与 `robots.txt` 限制自动化抓取。**生产环境请优先使用官方或授权的第三方数据 API**（如 Rainforest API / SerpApi / Apify）。
内置的 Playwright 爬虫仅用于**本地开发 / 低频回退**，已加入随机延时、User-Agent 轮换、并发上限，并在遇到验证码/拦截时优雅降级。请自行评估并遵守目标站点条款与当地法律法规。

---

## 📁 目录结构

```
backend/
  app/
    main.py                 # ASGI 入口（Starlette）+ 前端静态托管
    config.py               # 配置（pydantic-settings）
    models.py               # 数据模型（Pydantic）
    api/routes.py           # 路由处理器
    datasources/
      base.py               # DataSource 抽象接口
      api_source.py         # 第三方 API 数据源
      scraper_source.py     # Playwright 爬虫数据源
      mock_source.py        # 示例数据源（确定性）
    services/
      search_service.py     # 编排 + 回退 + 缓存
      review_analysis.py    # 情感 + 关键词
      export_service.py     # Excel / CSV 导出
    cache/store.py          # SQLite 缓存
  tests/smoke_test.py       # 端到端冒烟测试
  requirements.txt
  .env.example
frontend/
  dist/index.html           # 零构建单文件前端（后端托管）
```
