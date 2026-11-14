"""Chat-model factory."""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.language_models import BaseChatModel

from txt2pptx.config import LLMProvider, Settings

logger = logging.getLogger(__name__)


class MissingAPIKeyError(ValueError):
    """Raised when no API key is available for the requested provider."""


def resolve_provider(settings: Settings, provider: str | None) -> LLMProvider:
    chosen = (provider or settings.default_provider() or "").lower()
    if chosen not in ("openai", "anthropic"):
        raise MissingAPIKeyError(
            "No LLM provider configured. Set OPENAI_API_KEY or ANTHROPIC_API_KEY, or pass an API key."
        )
    return chosen  # type: ignore[return-value]


def create_chat_model(
    settings: Settings,
    provider: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
) -> BaseChatModel:
    """Build a LangChain chat model for *provider* (``openai`` or ``anthropic``)."""
    chosen = resolve_provider(settings, provider)
    key = (api_key or "").strip() or settings.api_key_for(chosen)
    if not key:
        env = "OPENAI_API_KEY" if chosen == "openai" else "ANTHROPIC_API_KEY"
        raise MissingAPIKeyError(f"No API key for {chosen}. Set {env} or enter a key.")

    common: dict[str, Any] = {
        "api_key": key,
        "max_tokens": settings.llm_max_tokens,
        "max_retries": settings.llm_max_retries,
        "timeout": settings.llm_timeout_seconds,
    }
    if settings.llm_temperature is not None:
        common["temperature"] = settings.llm_temperature

    if chosen == "openai":
        from langchain_openai import ChatOpenAI

        name = model or settings.openai_model
        logger.info("Using OpenAI model %s", name)
        return ChatOpenAI(model=name, **common)

    from langchain_anthropic import ChatAnthropic

    name = model or settings.anthropic_model
    logger.info("Using Anthropic model %s", name)
    return ChatAnthropic(model=name, **common)
