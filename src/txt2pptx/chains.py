"""LLM calls, each returning a validated Pydantic model via native structured output."""

from __future__ import annotations

import json
import logging
from typing import Any, TypeVar

from langchain_core.exceptions import OutputParserException
from langchain_core.language_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.retrievers import BaseRetriever
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, ValidationError

from txt2pptx.prompts import CODE_PROMPT, CODE_REVIEW_PROMPT, OUTLINE_PROMPT, REVIEW_PROMPT
from txt2pptx.schemas import CodeSafetyReview, GeneratedCode, PresentationOutline, QualityReview

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)
_NO_CONTEXT = "(none)"


class GenerationError(RuntimeError):
    """The LLM did not return a usable result."""


def _structured(
    llm: BaseChatModel,
    prompt: ChatPromptTemplate,
    schema: type[T],
    variables: dict[str, Any],
    config: RunnableConfig | None,
) -> T:
    chain = (prompt | llm.with_structured_output(schema, method="function_calling")).with_retry(
        retry_if_exception_type=(OutputParserException, ValidationError), stop_after_attempt=2
    )
    try:
        result = chain.invoke(variables, config=config)
    except (OutputParserException, ValidationError) as exc:
        raise GenerationError(f"The model returned an invalid {schema.__name__}: {exc}") from exc
    if result is None:
        raise GenerationError(f"The model returned no {schema.__name__} (output may have been truncated).")
    if isinstance(result, dict):  # some providers hand back raw dicts
        result = schema.model_validate(result)
    return result  # type: ignore[return-value]


def retrieve_context(retriever: BaseRetriever | None, query: str, max_chars: int = 6000) -> str:
    """Fetch reference snippets; failures degrade gracefully to no context."""
    if retriever is None:
        return _NO_CONTEXT
    try:
        docs = retriever.invoke(query)
    except Exception as exc:
        logger.warning("Context retrieval failed: %s", exc)
        return _NO_CONTEXT
    text = "\n\n---\n\n".join(d.page_content for d in docs)
    return text[:max_chars] or _NO_CONTEXT


def generate_outline(
    llm: BaseChatModel,
    content: str,
    *,
    style: str = "Professional",
    audience: str = "General audience",
    max_slides: int = 12,
    retriever: BaseRetriever | None = None,
    config: RunnableConfig | None = None,
) -> PresentationOutline:
    context = retrieve_context(
        retriever, f"python-pptx slide layouts, tables and charts for: {content[:300]}"
    )
    return _structured(
        llm,
        OUTLINE_PROMPT,
        PresentationOutline,
        {
            "content": content,
            "style": style,
            "audience": audience,
            "min_slides": max(3, max_slides // 2),
            "max_slides": max_slides,
            "context": context,
        },
        config,
    )


def review_outline(
    llm: BaseChatModel,
    outline: PresentationOutline,
    *,
    audience: str = "General audience",
    time_limit_minutes: int | None = None,
    config: RunnableConfig | None = None,
) -> QualityReview:
    return _structured(
        llm,
        REVIEW_PROMPT,
        QualityReview,
        {
            "outline": outline.model_dump_json(indent=2, exclude_none=True),
            "audience": audience,
            "time_limit": f"{time_limit_minutes} minutes" if time_limit_minutes else "not specified",
        },
        config,
    )


def generate_code(
    llm: BaseChatModel,
    content: str,
    *,
    style: str,
    template_data: dict[str, Any],
    retriever: BaseRetriever | None = None,
    config: RunnableConfig | None = None,
) -> GeneratedCode:
    context = retrieve_context(retriever, f"python-pptx code examples: tables, charts, text: {content[:300]}")
    return _structured(
        llm,
        CODE_PROMPT,
        GeneratedCode,
        {
            "content": content,
            "style": style,
            "template_json": json.dumps(template_data),
            "context": context,
        },
        config,
    )


def review_code(llm: BaseChatModel, code: str, *, config: RunnableConfig | None = None) -> CodeSafetyReview:
    try:
        return _structured(llm, CODE_REVIEW_PROMPT, CodeSafetyReview, {"code": code}, config)
    except Exception as exc:  # fail closed
        logger.warning("Code review failed: %s", exc)
        return CodeSafetyReview(is_safe=False, warnings=[f"Code review failed: {exc}"], assessment="error")
