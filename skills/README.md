# Skills

Per-agent knowledge and SOPs live here, one folder per business agent, e.g.:

```
skills/
  compliance/     # 合规风控 — 禁词判定逻辑, 侵权排查规则
  listing/        # Listing文案 — 新品/成熟/清仓三套写作逻辑, 上新SOP
  ads/            # 广告优化 — 调词控ACOS人工规则
  ...
```

A skill is written as markdown (rules, checklists, few-shot examples) that gets
composed into an agent's system prompt or loaded as retrievable context. Keep the
raw data (tables, reports, samples) in `data/<agent>/`; keep the *judgment* here.
