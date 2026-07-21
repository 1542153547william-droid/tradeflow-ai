"""Central configuration.

Reads from environment (optionally a .env file if python-dotenv is present).
Real API keys and model params are supplied here later; nothing else in the
codebase reads os.environ directly.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv  # type: ignore
        load_dotenv()
    except ImportError:
        pass  # .env is optional; env vars still work without the package


_load_dotenv()


@dataclass
class Settings:
    anthropic_api_key: Optional[str] = os.environ.get("ANTHROPIC_API_KEY")
    default_model: str = os.environ.get("TRADEFLOW_MODEL", "claude-opus-4-8")
    max_tokens: int = int(os.environ.get("TRADEFLOW_MAX_TOKENS", "4096"))
    # "mock" until keys/params are wired; flip to "anthropic" to go live.
    provider: str = os.environ.get("TRADEFLOW_PROVIDER", "mock")
    api_token: Optional[str] = os.environ.get("TRADEFLOW_API_TOKEN")
    # Cookie session login (web/auth.py).
    session_cookie_name: str = os.environ.get("TRADEFLOW_SESSION_COOKIE", "tf_session")
    session_ttl_days: int = int(os.environ.get("TRADEFLOW_SESSION_TTL_DAYS", "30"))
    secure_cookies: bool = os.environ.get("TRADEFLOW_SECURE_COOKIES", "1") != "0"
    # 商品查询系统（独立 HTTP 服务，不是 amazon.com）的地址，供 tools/amazon.py 调用。
    query_api_url: str = os.environ.get("QUERY_API_URL", "http://127.0.0.1:8000")
    # Alibaba Bailian / DashScope (Qwen) — OpenAI-compatible, works from mainland.
    bailian_api_key: Optional[str] = (
        os.environ.get("DASHSCOPE_API_KEY") or os.environ.get("BAILIAN_API_KEY")
    )
    bailian_base_url: str = os.environ.get(
        "DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
    )
    # DeepSeek — also OpenAI-compatible, reachable from mainland. Set
    # provider=deepseek, TRADEFLOW_MODEL=deepseek-chat, and your key here.
    deepseek_api_key: Optional[str] = os.environ.get("DEEPSEEK_API_KEY")
    deepseek_base_url: str = os.environ.get(
        "DEEPSEEK_BASE_URL", "https://api.deepseek.com"
    )
    # For mainland-China hosts that can't reach api.anthropic.com directly.
    # Set ONE of these to route around the block:
    #   base_url — an overseas relay that forwards to Anthropic (recommended)
    #   proxy    — an http/socks proxy the SDK dials through
    anthropic_base_url: Optional[str] = os.environ.get("ANTHROPIC_BASE_URL")
    anthropic_proxy: Optional[str] = (
        os.environ.get("ANTHROPIC_PROXY")
        or os.environ.get("HTTPS_PROXY")
        or os.environ.get("ALL_PROXY")
    )


settings = Settings()
