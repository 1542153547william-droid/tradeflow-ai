# AGENTS.md

## 项目是什么
TradeFlow-AI：面向跨境电商（外贸 / Amazon）的 Agent Harness。一套共享引擎 + 九个业务智能体
（合规、Listing 文案、广告优化、选品等）的 prompts/skills/tools。当前是内部工具，非公开产品，
面向单个运营团队使用，不是多租户 SaaS。

## 技术栈
- Python 3，FastAPI + uvicorn（Web 层），SQLite（`web/database.py`，走 raw SQL，无 ORM）
- 前端是原生 HTML/CSS/JS 单文件（`web/static/prototype.html`），无构建步骤，无框架
- LLM Provider 可插拔（`tradeflow/llm/`）：Mock / Anthropic / OpenAI 兼容（阿里百炼 Qwen、DeepSeek）
- 查询系统（`query-system/`）是独立的第二个 FastAPI 服务，端口 8000，提供商品数据（Amazon 抓取/API/mock），
  和主服务用 HTTP 通信，不共享进程也不共享数据库

## 关键目录
```
tradeflow/       共享引擎：llm/（provider 接口）、tools/（@tool 装饰器 + 内置工具）、
                 agent/loop.py（推理循环）、prompts/（各智能体系统提示词）、factory.py（build_agent）
config/          settings.py，纯 @dataclass + os.environ.get(...) 风格读配置（不是 pydantic）
web/             对外 Web 层：app.py（FastAPI 路由）、database.py（SQLite schema + init_db）、
                 store.py / listing_gen.py / opp_suggest.py / import_service.py（各业务模块）、
                 static/prototype.html（唯一的前端页面，新原型页，首页）
query-system/    独立商品数据服务（backend/，自带 .venv，端口 8000），供 web 层的 tools/amazon.py 调用
skills/          按智能体分类的领域知识文档（规则、评分标准等），被 prompts 引用
tests/           unittest，覆盖 harness + web 层
docs/            设计方案文档（先落地成文档、后实现的工作流）
```

## 常用命令
- 起 web 层（端口 8080）：`python -m uvicorn web.app:app --host 127.0.0.1 --port 8080`
- 起查询系统（端口 8000，需在 `query-system/backend/` 用它自带的 `.venv`）：
  `./.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000`
  （#5 拆解/#6 市场/#7 选品取真实商品数据依赖它，不开则相关取数报错）
- 跑测试：`python -m pytest tests/ -v` 或单文件 `python -m pytest tests/test_p0.py -v`
- 无 key 也能跑核心引擎：`python -m examples.run_demo`（MockProvider）

## 故意的设计（不要当 bug 改）
- `config/settings.py` 用纯 dataclass 而不是 pydantic-settings，是有意保持轻量，和 `query-system/backend/app/config.py`
  （用 pydantic-settings）风格不同——两个服务各自独立演进，不追求统一。
- `web/database.py` 里所有表都按 `user_id`+`store_id` 做了隔离设计，登录功能（2026-07-20 实现，见
  `docs/登录功能设计方案.md`）已经把 `x_tradeflow_user` 从"恒为 default 的伪多租户"换成真实的 cookie
  session 登录（`web/auth.py` + `web/app.py` 的 `Depends(auth.current_user)`）。无自助注册，账号由
  `python -m web.manage create-user` 开通；`default` 用户/店铺仍保留在库里作为历史数据的迁移起点
  （第一个新账号会继承它），不是遗留垃圾。
- 机会点持久化已经走 SQLite（`web/store.py` → `database.py` 的 `opportunities` 表），不是文件存储。
  `web/_store/opportunities.json` 是历史遗留文件（无代码引用），不代表当前设计。
- `web/app.py` 里全局共享 Basic Auth 已随登录功能移除；`X-TradeFlow-Token`（`settings.api_token`）是另一套
  独立的、非按用户区分的访问控制，和登录无关，代码库里没有测试/脚本在用，是预留但未启用的功能，故意保留没删。
- 选品建议（`web/opp_suggest.py`）基于查询系统返回的真实商品数据（`search_products`，取决于查询系统的
  api/scraper/mock 配置），不是模型编造；毛利率等在无真实成本数据时由模型标注"数据不足"，是缺数据时的
  诚实兜底，不是伪造数字。
- "一键上传亚马逊"/"同步"按钮是纯前端 stub（`toast('尚未配置 Amazon SP-API...')`，无后端调用）——依赖尚未
  实现的亚马逊 SP-API OAuth 授权流程，不是遗漏。
