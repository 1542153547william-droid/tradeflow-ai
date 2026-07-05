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


settings = Settings()
