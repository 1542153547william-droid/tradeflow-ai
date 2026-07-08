# TradeFlow AI — 后端接口规范 v1.1

对话式跨境电商运营 Agent。前端为「对话优先」：主页是对话框，机会挖掘与 Listing 素材生成都在对话中完成，确认后固化为草稿进入「机会上新」模块编辑上传。本文档定义前端所需的全部后端接口。

> 配套前端原型：对话主页 + 机会上新 / 数据导入 / 优化建议 / 客户跟踪 四个支撑模块。

### 变更记录
**v1.1**
- §C2 新增消息 Block 类型 `image_candidates`（对话内 AI 出图候选）。
- §D 新增 `POST /api/agent/generate-image`（AI 出图）、`PATCH /api/listings/drafts/{id}`（草稿图片 / 关键词部分更新）。
- §E 优化建议扩展 **价格、库存** 两个可回写字段：`analysis` 返回 `price`/`stock` 建议；`PATCH /api/products/{sku}` 支持 `price`/`quantity`，返回分渠道 `submits[]`。
- §E 明确「输入框为唯一事实来源」语义：前端提交的是用户最终编辑值，后端不需区分「是否采纳建议」。
- §F `media/upload` 补充在机会上新编辑器（本地上传主图/详情图）中的用途。

---

## 0. 通用约定

### 0.1 基础
- **Base URL**：`/api`
- **协议**：HTTPS，`Content-Type: application/json`（文件上传用 `multipart/form-data`）
- **鉴权**：除登录外所有请求带 `Authorization: Bearer <jwt>`
- **店铺维度**：几乎所有业务接口需 `storeId`（query 或 body）。前端顶栏切换店铺时带上当前 `storeId`。

### 0.2 统一响应信封
```json
{ "code": 0, "message": "ok", "data": { } }
```
- `code=0` 成功；非 0 为业务错误。HTTP 状态码用于传输层错误（401/403/500 等）。

### 0.3 错误格式
```json
{ "code": 40012, "message": "Excel 缺少必填列 ASIN", "data": null }
```
| code | 含义 |
|---|---|
| 0 | 成功 |
| 401xx | 未登录 / token 失效 |
| 403xx | 无权限 / 店铺未授权 |
| 409xx | 店铺授权过期，需重新授权 |
| 4xx | 参数 / 校验错误 |
| 5xx | 服务端 / 第三方(SP-API) 错误 |

### 0.4 分页
列表请求：`?page=1&pageSize=20`；返回：
```json
{ "list": [], "total": 312, "page": 1, "pageSize": 20 }
```

### 0.5 异步任务模式（重要）
同步数据、生成素材、回写/上架 Listing、发邮件等耗时操作**一律异步**：接口立即返回 `taskId`，前端轮询或订阅 SSE 获取进度与结果。

```
POST /api/... → { "taskId": "task_8f2a" }
GET  /api/tasks/{taskId}
```
```json
{
  "taskId": "task_8f2a",
  "type": "amazon_sync",
  "status": "running",          // pending | running | success | failed
  "progress": 60,                // 0-100
  "message": "拉取订单…",
  "result": null,                // success 时为该任务的结果对象
  "error": null                  // failed 时的错误信息
}
```
> 建议同时提供 `GET /api/tasks/{taskId}/stream`（SSE）推送进度，减少轮询。

### 0.6 枚举
- `marketplace`: `US | UK | DE | FR | JP | CA …`
- `store.status`: `active(有效) | expiring(即将过期) | revoked(需重新授权)`
- `severity`: `good | warn | crit`

---

## A. 认证与店铺授权

### A1. 发起亚马逊授权
`POST /api/auth/amazon/authorize-url`
```json
// req
{ "marketplace": "US", "storeAlias": "Aurora Home US" }
// res.data
{ "authUrl": "https://sellercentral.amazon.com/apps/authorize/consent?...", "state": "xr9..." }
```
前端跳转 `authUrl`；用户在亚马逊授权后回调后端。

### A2. 授权回调（后端接收，前端不直接调）
`GET /api/auth/amazon/callback?spapi_oauth_code=...&state=...&selling_partner_id=...`
- 后端用 `code` 换 `refresh_token`（LWA），加密入库，绑定到当前用户 + 店铺。
- 完成后重定向回前端 `/#/stores?authorized=1`。

### A3. 店铺列表
`GET /api/stores`
```json
{ "list": [
  { "id": 1, "name": "Aurora Home US", "marketplace": "US",
    "status": "active", "lastSyncAt": "2026-07-08T09:14:00Z", "sellerId": "A1B2C3" }
]}
```

### A4. 重新授权 / 解绑
- `POST /api/stores/{id}/reauthorize` → `{ "authUrl": "..." }`
- `DELETE /api/stores/{id}`

---

## B. 数据导入

### B1. 亚马逊后台同步
`POST /api/stores/{id}/sync`
```json
// req — types 可多选
{ "types": ["listing","orders","ads","reviews","inventory","messages"],
  "dateRange": "last_90d" }        // last_30d | last_90d | last_180d | all
// res
{ "taskId": "task_sync_01" }
```
任务完成后 `result`：
```json
{ "imported": { "listing": 312, "orders": 1180, "reviews": 86 },
  "importId": "imp_221" }
```
> SP-API 有严格限流；后端负责限流、重试、报表异步生成轮询。

### B2. Excel/CSV 上传（两步：解析预览 → 确认导入）

**Step 1 — 上传并解析**
`POST /api/import/excel`（`multipart/form-data`, 字段 `file`, `storeId`, `dataType`）
```json
// res.data — 返回探测到的列 + 建议映射 + 样例
{ "uploadId": "upl_77", "fileName": "ads_report_90d.xlsx",
  "rows": 1204, "columns": [
    { "col": "Advertised ASIN", "sample": "B0C1X2Y3Z4", "suggestField": "asin" },
    { "col": "Customer Search Term", "sample": "cool mist humidifier", "suggestField": "search_term" },
    { "col": "Impressions", "sample": "18204", "suggestField": "impressions" },
    { "col": "Spend", "sample": "342.10", "suggestField": "spend" },
    { "col": "ACOS", "sample": "28.4%", "suggestField": "acos" }
  ],
  "targetFields": ["asin","sku","search_term","keyword","impressions","clicks","spend","sales","acos","ignore"] }
```

**Step 2 — 确认字段映射并入库**
`POST /api/import/excel/{uploadId}/confirm`
```json
// req
{ "mapping": { "Advertised ASIN": "asin", "Customer Search Term": "search_term",
               "Impressions": "impressions", "Spend": "spend", "ACOS": "acos" } }
// res
{ "taskId": "task_imp_02" }
```

### B3. 导入历史
`GET /api/imports?storeId=1`
```json
{ "list": [
  { "id":"imp_221","source":"amazon","dataType":"listing+orders","rows":312,
    "status":"success","createdAt":"2026-07-08T09:14:00Z" },
  { "id":"imp_220","source":"excel","dataType":"ads_report","rows":1204,
    "status":"success","createdAt":"2026-07-07T21:03:00Z" }
]}
```

---

## C. 对话（Agent Chat）— 核心

对话是主入口。**关键：`/api/chat` 不能只返回纯文本，必须能返回结构化「卡片」**，前端按类型渲染成机会卡 / 素材卡 / 动作按钮。

### C1. 发送消息（推荐 SSE 流式）
`POST /api/chat`
```json
// req
{ "sessionId": "sess_12",       // 空则新建会话
  "storeId": 1,
  "message": "厨房家居类目下有哪些商品有机会？" }
```

**响应 — SSE 事件流**（`text/event-stream`）。每个事件是一个 message block：
```
event: step
data: {"label":"分析类目搜索体量 / 竞争 / 毛利…"}

event: block
data: {"type":"text","text":"在「厨房家居」类目里，我找到 3 个机会商品："}

event: block
data: {"type":"opportunity_list","items":[ ...见 C3 opportunity 对象... ]}

event: block
data: {"type":"chips","chips":["换一批看看","宠物用品类目有机会吗？"]}

event: done
data: {"sessionId":"sess_12","messageId":"msg_88"}
```

### C2. 消息 Block 类型协议
前端支持以下 `type`，后端按对话意图返回其一或多个：

| type | 渲染为 | payload 关键字段 |
|---|---|---|
| `text` | 文本气泡 | `text` (支持 markdown) |
| `step` | 思考步骤行 | `label` |
| `opportunity_list` | 机会商品卡片 | `items[]`（opportunity 对象） |
| `listing_draft` | Listing 素材卡 | `draftId, images[], title, bullets[], description, keywords[]` |
| `image_candidates` | AI 出图候选卡 | `opportunityId, candidates[], action`（用户挑一张加入商品图片） |
| `action` | 操作按钮 | `label, actionId, payload`（如「放入机会上新」） |
| `chips` | 快捷追问 | `chips[]`（字符串数组） |

**`listing_draft` block 示例**（对话生成素材时返回）：
```json
{ "type": "listing_draft",
  "draftId": "draft_501",
  "opportunityId": "opp_hum",
  "compliancePassed": true,
  "images": [
    { "role":"main",   "url":"https://cdn/.../main.png",  "label":"白底主图" },
    { "role":"detail", "url":"https://cdn/.../scene.png", "label":"使用场景" },
    { "role":"detail", "url":"https://cdn/.../spec.png",  "label":"尺寸对比" }
  ],
  "title": "Cool Mist Humidifier 4L, Ultra Quiet Air Humidifier for Bedroom & Baby Room",
  "bullets": [
    "【4L 大容量】一次加水静音运行 30 小时",
    "【26dB 超静音】卧室 / 婴儿房适用",
    "【360°出雾】均匀加湿，缓解干燥不适",
    "【易清洁广口设计】杜绝水垢滋生",
    "【自动断电】水位过低自动关机"
  ],
  "description": "Breathe easier, sleep deeper. The Aurora 4L cool mist humidifier ...",
  "keywords": [
    { "term":"cool mist humidifier", "tag":"core" },
    { "term":"bedroom humidifier",   "tag":"blue_ocean" },
    { "term":"baby humidifier",      "tag":"long_tail" }
  ]
}
```
> 图片可先返回「图片提示词 + 占位」，真实图异步生成完再回填；`images[].url` 为空时前端显示生成中。

**`image_candidates` block 示例**（在机会上新编辑器点「＋ AI 生成」时，前端会跳回对话触发出图）：
```json
{ "type": "image_candidates",
  "opportunityId": "opp_hum",
  "candidates": [
    { "mediaId":"m_a1", "url":"https://cdn/.../main.png",  "role":"主图" },
    { "mediaId":"m_a2", "url":"https://cdn/.../scene.png", "role":"场景图" },
    { "mediaId":"m_a3", "url":"https://cdn/.../white.png", "role":"白底图" }
  ],
  "action": { "label":"加入图片", "target":"listing_draft" }
}
```
> 用户点某张「加入图片」→ 前端将该 `mediaId/url` 追加到对应商品草稿的 `images[]`（见 D4）。

### C3. 会话管理
- `GET /api/chat/sessions?storeId=1` → 侧边「最近对话」列表 `[{id,title,updatedAt}]`
- `GET /api/chat/sessions/{id}` → 历史消息（block 数组）
- `POST /api/chat/sessions` → 新建；`DELETE /api/chat/sessions/{id}`

---

## D. 机会商品与素材生成

对话与「机会上新」模块共用同一数据源。

### D1. 机会商品列表
`GET /api/opportunities?storeId=1&category=厨房家居`
```json
{ "list": [
  { "id":"opp_hum", "name":"Cool Mist Humidifier 4L", "category":"厨房家居",
    "score":8.7, "margin":"42%", "demand":"高", "competition":"中等",
    "infringeRisk":"low", "coverColor":"#0d8a80" }
]}
```

### D2. 生成 Listing 素材（异步）
`POST /api/agent/generate-listing`
```json
// req
{ "opportunityId":"opp_hum", "storeId":1,
  "parts":["images","title","bullets","description","keywords"] }
// res
{ "taskId":"task_gen_09" }
```
任务 `result` = 一个 `listing_draft` 对象（同 C2）。

### D3. 固化草稿 → 放入机会上新
对话里点「确认并放入机会上新」时调用：
`POST /api/listings/draft`
```json
// req — 可直接传 draftId 引用已生成草稿，或传完整素材
{ "draftId":"draft_501", "storeId":1 }
// res
{ "listingDraftId":"ldraft_88", "status":"draft" }
```
该草稿随后出现在 `GET /api/listings/drafts`（机会上新模块列表）。

### D4. AI 出图（异步）
机会上新编辑器点「＋ AI 生成」时触发，前端会跳回对话，后端生成候选图。
`POST /api/agent/generate-image`
```json
// req
{ "opportunityId":"opp_hum", "listingDraftId":"ldraft_88",
  "imageType":"main", "count":3 }   // imageType: main(主图) | scene(场景) | white(白底) | detail(细节)
// res
{ "taskId":"task_img_12" }
```
任务 `result` = 一个 `image_candidates` 对象（见 §C2）。

### D5. 编辑器部分更新（图片 / 关键词 / 文案）
机会上新编辑器里的**本地上传图、AI 出图加入、关键词增删改**都写回草稿。
`PATCH /api/listings/drafts/{id}`
```json
// req — 只传变化的字段（整份覆盖该字段）
{ "images": [
    { "mediaId":"m_up1", "url":"https://cdn/.../u1.png", "role":"主图", "source":"upload" },
    { "mediaId":"m_a2",  "url":"https://cdn/.../scene.png", "role":"场景图", "source":"ai" }
  ],
  "keywords": ["cool mist humidifier","bedroom humidifier","baby humidifier"],
  "title":"...", "bullets":["..."], "description":"..." }
// res
{ "listingDraftId":"ldraft_88", "updatedAt":"2026-07-08T10:20:00Z" }
```
> `images[].source`: `upload(本地上传) | ai(AI生成) | generated(初次素材生成)`。删除即在数组中去掉该项；顺序即展示顺序（第一张为主图）。

---

## E. 优化建议与回写（在售商品）

### E1. 在售商品列表
`GET /api/stores/{id}/products?page=1`
```json
{ "list":[
  { "sku":"AH-HUM-4L", "asin":"B0C1X2Y3Z4", "name":"Cool Mist Humidifier 4L",
    "healthScore":52, "severity":"crit", "issues":["极限词","关键词缺失","库存偏低"] }
]}
```

### E2. 单品分析结论 + 建议
`GET /api/products/{sku}/analysis?storeId=1`
```json
{ "sku":"AH-HUM-4L", "asin":"B0C1X2Y3Z4", "healthScore":52,
  "conclusions":[
    { "severity":"crit","title":"标题含极限词","detail":"命中「Best」「#1」，需删除" },
    { "severity":"warn","title":"五点缺核心词","detail":"未覆盖高搜索词 cool mist" },
    { "severity":"warn","title":"库存偏低","detail":"按近30天动销约6天售罄，建议补货至300" }
  ],
  "suggestions":{
    "title":{ "current":"Best Humidifier #1 Rated...", "suggested":"Cool Mist Humidifier 4L, Ultra Quiet..." },
    "bullets":{ "current":[...], "suggested":[...] },
    "keywords":{ "current":"humidifier", "suggested":"cool mist humidifier, quiet humidifier, bedroom humidifier" },
    "description":{ "current":"...", "suggested":"..." },
    "price":{ "current":25.99, "suggested":23.99, "currency":"USD", "reason":"高于竞品均价，转化承压" },
    "stock":{ "current":80,   "suggested":300,   "reason":"6天售罄，建议补货" }
  }
}
```
> 前端「修改并提交」区把上述每个 `suggestions.*` 渲染成 `当前 | 建议 + 可编辑输入框`，字段含 **标题 / 关键词 / 价格 / 库存**（可扩展五点、描述）。

### E3. 用户修改并回写亚马逊（异步）

> **语义**：输入框是唯一事实来源。前端提交的是用户**最终编辑后的值**（无论是否点过「采纳建议」），后端只需按传入值回写，不区分来源。只传发生变化的字段。

`PATCH /api/products/{sku}`
```json
// req — 只传要改的字段；价格/库存与文案走不同亚马逊端点
{ "storeId":1,
  "title":"Cool Mist Humidifier 4L, ...",
  "bullets":["...","..."],
  "keywords":"cool mist humidifier, ...",
  "price":23.99,          // → SP-API Product Pricing / Listings PATCH
  "quantity":300 }        // → FBA/FBM Inventory 更新
// res — 每类改动一个提交单，各自异步
{ "taskId":"task_patch_11",
  "submits":[
    { "field":"listing", "submitId":"feed_88213" },
    { "field":"price",   "submitId":"price_5521" },
    { "field":"stock",   "submitId":"inv_7734" }
  ] }
```
`GET /api/submits/{submitId}` 查单个回写结果：
```json
{ "submitId":"feed_88213", "field":"listing",
  "status":"processing",              // processing | done | error
  "amazonFeedStatus":"IN_PROGRESS", "errors":[] }
```

---

## F. 合规预检与上架

### F1. 合规预检（本地，先于上架）
`POST /api/compliance/check`
```json
// req
{ "storeId":1, "marketplace":"US",
  "fields":{ "title":"Best Humidifier #1", "bullets":[...], "keywords":"..." } }
// res
{ "passed":false,
  "violations":[
    { "field":"title","type":"极限词","hit":"best" },
    { "field":"title","type":"极限词","hit":"#1" }
  ] }
```

### F2. 图片上传（本地上传）
机会上新编辑器点「＋ 上传」时调用，返回的 `mediaId/url` 通过 §D5 写回草稿 `images[]`。
`POST /api/media/upload`（`multipart`, 字段 `file`, `storeId`）
```json
{ "mediaId":"m_up1", "url":"https://cdn/.../img.png", "width":1600, "height":1600 }
```
> 后端建议校验图片规格（亚马逊主图白底、≥1000px 可缩放等），不合规在响应里返回 `warnings[]`。

### F3. 一键上架（异步）
`POST /api/listings/{listingDraftId}/publish`
```json
// req
{ "storeId":1 }
// res
{ "taskId":"task_pub_04", "feedId":"feed_90417" }
```
`GET /api/listings/publish/{feedId}`：
```json
{ "feedId":"feed_90417", "status":"processing", "asin":null, "errors":[] }
```

---

## G. 客户跟踪与邮件

> 合规红线：亚马逊仅允许通过 **Buyer-Seller Messaging** 联系买家，禁止营销外链与索取好评式话术。**不可**用普通 SMTP 群发买家邮箱。

### G1. 买家名单
`GET /api/stores/{id}/customers?filter=review`  （`filter`: `all | repeat | review`）
```json
{ "list":[
  { "buyerId":"b_1","name":"James W.","product":"Cool Mist Humidifier 4L",
    "orderId":"112-8834","purchasedAt":"2026-07-02","tag":"review" }
], "counts":{ "all":47,"repeat":9,"review":28 } }
```

### G2. 邮件模板
- `GET /api/email-templates?storeId=1`
```json
{ "list":[
  { "id":"review","name":"关怀式催评","type":"review_request",
    "subject":"How is your {{商品}} working out?",
    "body":"Hi {{客户名}},\n\nIt's been a couple of weeks since your {{商品}} (order {{订单号}}) arrived...",
    "variables":["客户名","商品","订单号"] }
]}
```
- `POST /api/email-templates` / `PUT /api/email-templates/{id}` / `DELETE ...` — 自定义模板 CRUD

### G3. 发送（异步）
`POST /api/emails/send`
```json
// req
{ "storeId":1, "templateId":"review", "buyerIds":["b_1","b_3","b_4"],
  "variables":{ }   // 缺省用系统按订单自动填充 客户名/商品/订单号
}
// res
{ "taskId":"task_mail_07", "batchId":"batch_55" }
```
`GET /api/emails/{batchId}`：
```json
{ "batchId":"batch_55", "sent":3, "delivered":3, "failed":[],
  "channel":"buyer_seller_messaging" }
```

---

## 附录：核心数据表（供后端建模参考）

| 表 | 关键字段 |
|---|---|
| `users` | id, email, ... |
| `stores` | id, user_id, name, marketplace, seller_id, refresh_token(加密), status, last_sync_at |
| `imports` | id, store_id, source(amazon/excel), data_type, rows, status, created_at |
| `products` | id, store_id, sku, asin, title, bullets(json), keywords, price, quantity, health_score, severity |
| `suggestions` | id, product_id, field(title/keywords/price/stock/…), current, suggested, reason, severity |
| `opportunities` | id, store_id, name, category, score, margin, demand, competition, infringe_risk |
| `listing_drafts` | id, store_id, opportunity_id, images(json: [{mediaId,url,role,source}]), title, bullets(json), description, keywords(json), status |
| `media` | id(mediaId), store_id, url, source(upload/ai/generated), width, height |
| `chat_sessions` / `chat_messages` | session: id,store_id,title; message: id,session_id,role,blocks(json) |
| `customers` | id, store_id, buyer_id, order_id, product, purchased_at, tag |
| `email_templates` / `email_logs` | template: id,store_id,type,subject,body; log: id,batch_id,buyer_id,status |
| `tasks` | id, type, status, progress, result(json), error, created_at |

## 落地优先级（与前端模块对应）
1. **地基**：DB / 鉴权 / 异步任务(tasks) / 对象存储 —— 全部接口的前提
2. **A + B**：授权 + 导入（Excel 链路可先跑通，不依赖 SP-API 审核）
3. **C + D**：对话 + 机会/素材生成（`/api/chat` 的 block 协议是重点）
4. **E + F**：优化回写 + 上架（依赖 SP-API Listings，异步 Feed）
5. **G**：客户邮件（Buyer-Seller Messaging，注意合规）

> ⚠️ SP-API / LWA 应用审核周期长，建议**第一天就提交申请**，它阻塞 B/E/F/G 的真实对接。
