# TradeFlow-AI

An agent harness for cross-border e-commerce (外贸 / Amazon) workflows. This repo
holds the shared **engine** plus all prompts, skills, and tools for a family of
nine business agents (compliance, listing copy, ad optimization, product
selection, …). Early on, everything lives here in one project.

## Status — harness framework (step 1)

The engine is in place and runs today with **no API key** via a mock provider:

- **Reasoning + tool-calling + agent loop** — `tradeflow/agent/loop.py`
- **Model-agnostic LLM interface** — `tradeflow/llm/base.py` (swap providers freely)
  - `MockProvider` (runs now), `AnthropicProvider` (interface done; add key to go live)
- **Tools** — `@tool` decorator auto-derives JSON schema from Python signatures
  (`tradeflow/tools/base.py`); starter tools in `builtin.py`
- **Wiring** — `tradeflow/factory.py::build_agent()`

## Quickstart

```bash
python -m examples.run_demo      # runnable loop, no key needed
python -m unittest tests.test_loop -v
```

Minimal usage:

```python
from tradeflow.factory import build_agent
agent = build_agent()
print(agent.run("What is 12 * (3 + 4)?").output)
```

## Going live later

1. `pip install -r requirements.txt`
2. `cp .env.example .env`, set `ANTHROPIC_API_KEY` and `TRADEFLOW_PROVIDER=anthropic`
3. Same code path — `build_agent()` picks the real provider from settings.

## Layout

```
tradeflow/
  llm/       provider interface + mock + anthropic
  tools/     tool decorator, registry, builtin tools
  agent/     the agent loop
  prompts/   base system prompt (per-agent prompts land here)
factory.py   build_provider / build_agent
config/      settings (env / .env)
skills/      per-agent skill content (see ROADMAP.md)
examples/    run_demo.py
tests/       harness tests
```

See [ROADMAP.md](ROADMAP.md) for the nine-agent plan and build order.
