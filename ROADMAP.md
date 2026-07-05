# TradeFlow-AI Roadmap

Each business agent = **system prompt + skills + tools** on the shared harness.
The harness (step 1) is done; the agents below are configurations on top of it.

## Architecture pattern for every agent

- **Prompt** → `tradeflow/prompts/` (persona + rules, composed on BASE_SYSTEM_PROMPT)
- **Skills** → `skills/<agent>/` (SOPs, writing logic, judgment rules as markdown/knowledge)
- **Tools** → `tradeflow/tools/` (data lookups, calculators, checkers, report generators)
- **Data** → `data/<agent>/` (the tables/samples the user provides: 禁词表, 词根库, 报表, ASIN…)

## The nine agents (build order)

| # | Agent | Type | Key tools to build | Data user provides |
|---|-------|------|--------------------|--------------------|
| 1 | 合规风控 Compliance | global底层, gates all others | forbidden-word/极限词 checker, IP/brand/patent blacklist match, category risk flag | 各站点禁词表, 品牌+竞品IP黑名单, 类目审核禁描述, 侵权/下架复盘 |
| 2 | Listing 文案 | generator | title/五点/Search Terms/A+/QA gen, keyword-root inject, calls #1 to validate | 产品参数库, 爆款范文, 关键词词根库, 上新SOP, 卖点&差评痛点 |
| 3 | 图文视频提示词 | generator | AI绘图prompt gen (中英), 竞品构图配色拆解, 短视频脚本gen, 图片规范校验 | 参数&拍摄避雷, 竞品图文样例, 官方图文视频规范, 短视频脚本案例 |
| 4 | 广告优化分析 | analyzer | Excel报表解析, 曝光/转化/ACOS统计, 好词/长尾/垃圾词分类, 竞价&预算建议, 否定词批量, 拓词 | 90天SP/SD/SB报表, 人工调词控ACOS规则, 盈亏广告案例, 竞品流量词 |
| 5 | 爆款&精品拆解 | analyzer | ASIN→Listing/变体/定价/配件拆解, 评价QA痛点汇总, 运营模式分类 | 爆款ASIN清单, 竞品Listing+评价, 精品盈利判定, 滞销复盘 |
| 6 | 市场数据分析 | analyzer | 搜索体量测算, 竞争强度, 价格利润区间, 淡旺季识别, 专利/高风险类目标记 | 关键词市场数据, 各价位竞品样本, 淡旺季记录, 蓝海/红海标准 |
| 7 | AI智能选品 | scorer/decision | 多维评分模型(容量/竞争/毛利/侵权/改良), 差评挖改良点, 风险收益报告 | 成本测算表, 选品门槛, 侵权排查规则, 成功&失败复盘, 客群偏好 |
| 8 | 评价&站内客服 | API后期 | 差评归类, 安抚/补偿话术匹配, 催评邮件gen, 申诉模板, FAQ沉淀 | 好/中/差评样本, 客服话术模板, 高频咨询, 站内消息合规限制 |
| 9 | 库存/利润/定价 | API后期 | 真实毛利计算, 断货/滞销预警, 调价建议, ODR/退货率监控 | 成本明细, 备货&清仓规则, 定价SOP, 绩效告警阈值 |

## Immediate next steps

1. **Fill in real model params + key** → flip `TRADEFLOW_PROVIDER=anthropic`.
2. **Agent #1 (合规风控) first** — it's the底层 gate every other agent calls.
   Load the 禁词表/黑名单 into `data/compliance/`, expand `check_forbidden_words`
   into real tools, add IP/patent matching.
3. **Agent registry** — let agents call one another (e.g. Listing → Compliance)
   as a composed pipeline.
4. Data-loading layer for the tables/reports the user supplies (CSV/Excel).
