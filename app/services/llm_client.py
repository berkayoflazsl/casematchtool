"""Reused OpenAI-compatible async client (HTTP keep-alive, fewer round trips)."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from openai import AsyncOpenAI

from app.config import get_settings, llm_base_url


@lru_cache
def get_async_openai_client() -> AsyncOpenAI:
    s = get_settings()
    if not s.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")
    base = llm_base_url(s)
    client_kw: dict[str, Any] = {"api_key": s.openai_api_key}
    if base:
        client_kw["base_url"] = base
        if "openrouter.ai" in base:
            client_kw["default_headers"] = {
                "HTTP-Referer": s.openrouter_http_referer,
                "X-Title": s.openrouter_app_title,
            }
    return AsyncOpenAI(**client_kw)
