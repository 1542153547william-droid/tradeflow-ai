"""Wiring helpers: turn config into a ready-to-run Agent.

`build_agent` picks the provider from settings (mock by default, anthropic once
keys are wired), registers the requested tools, and attaches the system prompt.
This is the single place that knows how the pieces snap together.
"""

from __future__ import annotations

from typing import List, Optional

from config.settings import settings

from .agent.loop import Agent
from .llm.base import LLMProvider, ModelConfig
from .prompts import BASE_SYSTEM_PROMPT
from .tools.base import Tool, ToolRegistry
from .tools.builtin import BUILTIN_TOOLS


def build_provider(provider_name: Optional[str] = None) -> LLMProvider:
    name = (provider_name or settings.provider).lower()
    config = ModelConfig(model=settings.default_model, max_tokens=settings.max_tokens)
    if name == "anthropic":
        from .llm.anthropic_provider import AnthropicProvider
        return AnthropicProvider(
            api_key=settings.anthropic_api_key,
            config=config,
            base_url=settings.anthropic_base_url,
            proxy=settings.anthropic_proxy,
        )
    if name in ("bailian", "dashscope", "qwen"):
        from .llm.openai_provider import OpenAICompatProvider
        model = settings.default_model
        if model.startswith("claude"):  # claude default doesn't apply to Qwen
            model = "qwen-plus"
        cfg = ModelConfig(model=model, max_tokens=settings.max_tokens)
        return OpenAICompatProvider(
            api_key=settings.bailian_api_key,
            config=cfg,
            base_url=settings.bailian_base_url,
        )
    if name == "mock":
        from .llm.mock_provider import MockProvider
        return MockProvider(config=config)
    raise ValueError(f"unknown provider: {name!r}")


def build_agent(
    system_prompt: str = BASE_SYSTEM_PROMPT,
    tools: Optional[List[Tool]] = None,
    provider: Optional[LLMProvider] = None,
    max_iterations: int = 10,
    observer=None,
) -> Agent:
    registry = ToolRegistry(tools if tools is not None else list(BUILTIN_TOOLS))
    return Agent(
        provider=provider or build_provider(),
        system_prompt=system_prompt,
        tools=registry,
        max_iterations=max_iterations,
        observer=observer,
    )
