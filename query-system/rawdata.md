# 亚马逊跨境电商：高级爬虫数据抓取与 AI 核心分析数据规范 (Data Schema Specification)

本规范定义了面向亚马逊（Amazon）平台的自动化数据抓取（爬虫系统）所需的底层字段结构，并详细阐述了各数据维度在 AI 深度分析、大模型（LLM）自然语言处理、以及商业决策中的核心应用价值。本规范旨在对接爬虫技术团队与数据分析/AI算法团队，建立统一的数据交换语言。

---

## 一、 列表页与搜索结果页数据 (Search & Listing Page Data)
该模块主要用于对特定关键词下的市场大盘、竞争烈度、品牌垄断度及流量结构（自然流量 vs 广告流量）进行宏观量化分析。

### 1.1 数据字段定义表

| 字段名称 (Field) | 数据类型 (Type) | 抓取来源 (Source) | 核心定义与说明 | AI 分析与商业价值 |
| :--- | :--- | :--- | :--- | :--- |
| `Search_Keyword` | String | 搜索URL参数 | 用户在搜索框输入的原始关键词 | 建立关键词流量池，分析流量归属与词频变动趋势。 |
| `ASIN` | String (10) | 元素属性/URL | 亚马逊产品唯一识别码（身份证号） | 数据排重、跨表关联（Detail/Review表）的唯一主键。 |
| `Product_Title` | String | 节点文本 | 列表页展示的产品标题（可能被压缩） | 提取高频核心词，分析竞品在列表页的文案权重布控。 |
| `Brand_Name` | String | 节点文本 | 产品的所属品牌名称 | **计算品牌垄断指数 (CR4/CR8)**；识别巨头品牌，规避高壁垒品类。 |
| `Organic_Rank` | Integer | 页面流/位置 | 该ASIN在当前页面的**自然排名**位置 | 评估SEO效果，分析自然流量的分布特征与卡位难度。 |
| `Sponsored_Rank` | Integer | 页面流/位置 | 该ASIN在当前页面的**广告排名**位置 | 计算广告位占比，评估该类目的SP广告竞争激烈度与买家点击惯性。 |
| `Current_Price` | Float | 节点文本 | 当前页面显示的实时售价（美金） | 绘制市场价格区间带，分析价格段销量分布（低端/中端/高端）。 |
| `List_Price` | Float | 节点文本 | 划线价/零售参考价（如存在） | 与当前价对比，计算折扣感知度，识别竞品是否在做虚假打折。 |
| `Review_Count` | Integer | 节点文本 | 列表页显示的评论总数 | 评估竞品信任资产池大小。结合上架时间计算评论护城河深度。 |
| `Rating_Score` | Float | 元素属性 | 产品的综合星级（0.0 - 5.0） | 过滤低分竞品；分析该类目的整体服务质量红线。 |
| `Badges` | List [String] | 图标/徽章节点 | 产品享有的特殊徽章（如 `Best Seller`, `Amazon's Choice`） | 识别类目权重核心节点，监控爆款和黑马产品的徽章转移轨迹。 |

---

## 二、 详情页核心数据 (Listing Detail Page Core Data)
该模块深入Listing内部，抓取文案、视觉资产、类目排名及变体架构。主要用于AI文案反向工程、变体销量拆解和物流/供应链成本精算。

### 2.1 数据字段定义表

| 字段名称 (Field) | 数据类型 (Type) | 抓取来源 (Source) | 核心定义与说明 | AI 分析与商业价值 |
| :--- | :--- | :--- | :--- | :--- |
| `Parent_ASIN` | String (10) | 页面源代码/API | 父体ASIN（用于聚合所有变体） | 识别多变体产品的整体架构，建立父子体映射关系。 |
| `Child_ASIN` | String (10) | 变体选择器 | 当前具体选中的子体ASIN | 精准对齐价格、库存、评论的实际承受载体。 |
| `Variant_Attributes`| JSON / Map | 变体规格面板 | 子体的具体属性，如 `{"Color": "Matte Black", "Size": "Large"}` | **拆解热销变体特征**：让AI分析哪种颜色/尺寸是该类目的真正核心出单款。 |
| `Bullet_Points` | List [String] | 顶部描述节点 | 五点描述（通常为5个卖点短句） | **AI文案反向工程核心**：提取竞品卖点逻辑、核心关键词埋词率。 |
| `Product_Desc` | Text / HTML | 详细描述节点 | 纯文本或带有简单HTML标签的产品详细描述 | 补充提取技术参数、使用场景，用于AI丰富自身的FAQ和知识库。 |
| `APlus_Text` | Text | A+内容区域 | 亚马逊A+图文页面的所有文本提取 | 挖掘隐藏在视觉底部的痛点解答、品牌故事及进阶参数。 |
| `Image_Count` | Integer | 图片缩略图栏 | Listing主图及副图的总数量 | 评估竞品的视觉丰富度。AI可根据数量和类型分析视觉转化门槛。 |
| `Has_Main_Video` | Boolean | 视频/图片栏 | 主图流中是否包含产品宣传视频 | 评估核心视觉壁垒，决定我方入场是否必须配置视频资产。 |
| `BuyBox_Seller` | String | 购物车区块 | 赢得黄金购物车的卖家名称 | 监控购物车是否被跟卖、是否被亚马逊自营霸占。 |
| `Fulfillment_Type` | Enum | 购物车区块 | 发货与销售模式：`Amazon` / `FBA` / `FBM` | **重塑供应链画像**：评估竞品属于官方自营、海外仓发货还是本土仓发货。 |
| `BSR_Main` | Integer | 产品信息区块 | 该产品在亚马逊一级大类目的销售排名 | **推算核心销量的终极依据**：AI通过BSR曲线拟合直接预测月销量。 |
| `BSR_Sub_Nodes` | JSON / List | 产品信息区块 | 所有三级/四级小节点类目的排名及完整路径 | 寻找高转化、低竞争的“冷门小类目”进行错位竞争（类目流浪策略）。 |
| `Dimensions` | String | 产品信息区块 | 产品的包装尺寸（长×宽×高，英寸） | **FBA费用精准核算**：输入公式自动计算体积重，辅助AI利润测算。 |
| `Item_Weight` | Float | 产品信息区块 | 产品的含包装重量（磅/盎司） | 核算头程空运/海运物流成本，评估毛利率死穴。 |

---

## 三、 动态价格与促销数据 (Price & Promotion Dynamics)
该模块专门捕捉页面上的“隐藏折扣”与“短期价格操盘行为”，防止AI被静态标价误导。

### 3.1 数据字段定义表

| 字段名称 (Field) | 数据类型 (Type) | 抓取来源 (Source) | 核心定义与说明 | AI 分析与商业价值 |
| :--- | :--- | :--- | :--- | :--- |
| `Coupon_Text` | String | 绿色优惠券徽章 | 页面展示的Coupon，如 `"Save 15%"`, `"Save $5.00"` | **还原真实到手价 (Net Price)**：Current_Price - Coupon = 真实成交价基准线。 |
| `Promo_Code_Text` | String | 折扣码/多买优惠 | 诸如 "Buy 2, get 10% off" 的促销文本 | 分析竞品的客单价拉升策略（捆绑销售/跨店铺联动）。 |
| `Is_Lightning_Deal`| Boolean | 秒杀标志/倒计时 | 当前是否处于秒杀（LD）或限时抢购状态 | 识别竞品的“强心针”销售期。剔除秒杀带来的短期销量激增异常值。 |
| `Historical_Prices`| TimeSeries / JSON | 历史轨迹（增量累计） | 历史价格、Coupon及BSR的每日/每周变动轨迹 | **AI定价策略模型**：预测竞品在黑五/网一/会员日的降价幅度和价格底线。 |

---

## 四、 买家互动与口碑数据 (Review & Q&A Data)
该模块是**AI文本挖掘、消费者痛点分析、微创新机会发现**的黄金燃料。无此模块，AI将失去灵性。

### 4.1 数据字段定义表（Review 详情表）

| 字段名称 (Field) | 数据类型 (Type) | 抓取来源 (Source) | 核心定义与说明 | AI 分析与商业价值 |
| :--- | :--- | :--- | :--- | :--- |
| `Review_ID` | String | 元素ID属性 | 亚马逊每条Review的全球唯一编码 | 防重、更新状态同步的主键。 |
| `Review_Rating` | Integer (1-5) | 节点星级 | 单个买家给予的评分（1星到5星） | **情感分类器输入**：1-2星归为严重痛点，3星为改良痒点，4-5星为核心卖点。 |
| `Review_Date` | Date / TimeStamp | 节点文本 | 评论撰写并发布的时间戳（含国家） | **时序质量监控**：AI分析差评率是否在近3个月内激增，识别竞品工厂质量事故。 |
| `Review_Country` | String | 节点文本 | 买家所在的国家/站点（如 United States） | 本地化痛点挖掘（如欧洲买家更看重环保，美国买家更看重大尺寸）。 |
| `Review_Variant` | String / JSON | 评论区属性标签 | 该评论买家实际购买的变体属性（颜色/尺寸） | **精准改良排雷**：将差评精确定位到“红色款拉链易坏”或“S码偏小”，避免无差别改版。 |
| `Review_Title` | String | 节点文本 | 评论的标题（通常是核心情绪的总结） | 提取高频情绪词，作为AI分析的权重加成项。 |
| `Review_Body` | Text | 节点文本 | 评论的长文本正文 | **NLP 核心燃料**：进行词频统计（TF-IDF）、实体识别、语义痛点聚类。 |
| `Helpful_Count` | Integer | 节点文本 | 该条评论被其他多少个买家点赞了“有用” | **权重系数**：点赞数越高的差评，说明其痛点具备全网普适性，AI需成倍提高其改良优先级。 |
| `Has_Buyer_Media` | Boolean | 评论区多媒体 | 评论中是否附带了买家拍摄的真实照片或视频 | 识别高风险真实缺陷。买家晒图往往暴露产品最真实的做工粗糙点。 |

### 4.2 数据字段定义表（Q&A 买家问答表）

| 字段名称 (Field) | 数据类型 (Type) | 抓取来源 (Source) | 核心定义与说明 | AI 分析与商业价值 |
| :--- | :--- | :--- | :--- | :--- |
| `Question_ID` | String | 元素属性 | 问题的唯一标识 | 关联管理。 |
| `Question_Text` | Text | 节点文本 | 买家提出的未下订单前的疑问句 | **最直接的“需求盲区”**：买家反复问说明Listing和图片没交代清楚，这是我方文案降维打击的切入点。 |
| `Answer_Text` | Text | 节点文本 | 卖家官方或其他已购买家的核心回答 | 提取技术指标与标准答案，看竞品是否能完美解决买家卡点。 |

---

## 五、 技术架构与爬虫抓取设计规范 (Technical Scrapy Notes)

为了保障抓取到的数据能够直接被 AI 框架（如 LangChain / LlamaIndex / Pandas 情感分析分析链）高效吞噬，技术团队在构建爬虫系统时，必须遵循以下底层架构设计：

### 5.1 统一 JSON 数据结构示例 (Per ASIN Payload)
```json
{
  "search_context": {
    "keyword": "ergonomic office chair",
    "organic_rank": 14,
    "sponsored_rank": null
  },
  "base_info": {
    "asin": "B08LLH656X",
    "parent_asin": "B08LLG9YY7",
    "brand": "Sihoo",
    "title": "Sihoo Ergonomic Office Chair with Adjustable Lumbar Support",
    "bsr_main_rank": 1420,
    "bsr_main_node": "Office Products",
    "bsr_sub_nodes": [
      { "node": "Managerial Chairs & Executive Chairs", "rank": 12 }
    ]
  },
  "pricing": {
    "current_price": 189.99,
    "list_price": 239.99,
    "currency": "USD",
    "coupon": {
      "type": "fixed",
      "value": 30.00,
      "text": "Save $30.00 with coupon"
    }
  },
  "logistics": {
    "buybox_seller": "Sihoo Store",
    "fulfillment": "FBA",
    "dimensions_inch": "28.3 x 27.6 x 13.8",
    "weight_lbs": 41.2
  },
  "content": {
    "bullet_points": [
      "Ergonomic Design: 5 ergonomic adjustments help you find the most comfortable seating position...",
      "Breathable Mesh Back: The premium fabric mesh backrest is flexible..."
    ],
    "has_video": true,
    "image_count": 7
  },
  "reviews_sample_increment": [
    {
      "review_id": "R3A9O1J2V4XXXX",
      "rating": 2,
      "date": "2026-05-14",
      "country": "United States",
      "variant_purchased": "Color: Black Mesh | Size: Standard",
      "helpful_votes": 84,
      "title": "Armrest broke after 2 months",
      "body": "I really wanted to love this chair, but the plastic holding the left armrest completely cracked. I only weigh 180 lbs. Customer service has been unresponsive."
    }
  ]
}