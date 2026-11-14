from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
from langchain_core.runnables import RunnableLambda

from txt2pptx.config import Settings, get_settings
from txt2pptx.pipeline import PresentationService

SAMPLE_OUTLINE: dict[str, Any] = {
    "metadata": {"title": "AI Testing 2026", "author": "QA Team", "language": "en"},
    "slides": [
        {"title": "AI Testing in Practice", "subtitle": "Reliability for ML systems", "slide_type": "title"},
        {
            "title": "Why testing AI is different",
            "content_elements": [
                {
                    "element_type": "text",
                    "bullet_points": [
                        "Outputs are non-deterministic",
                        "Huge input space; edge cases dominate",
                        "Models drift as data changes",
                    ],
                }
            ],
            "speaker_notes": "Set the stage.",
        },
        {
            "title": "Q1 sales by region",
            "content_elements": [
                {"element_type": "text", "title": "Highlights", "bullet_points": ["East leads A", "South leads B"]},
                {
                    "element_type": "chart",
                    "chart_type": "column",
                    "title": "Units sold",
                    "categories": ["North", "South", "East", "West"],
                    "series": [
                        {"name": "Product A", "values": [1500, 1200, 1800, 1350]},
                        {"name": "Product B", "values": [800, 950, 700, 880]},
                    ],
                },
            ],
        },
        {
            "title": "Raw numbers",
            "content_elements": [
                {
                    "element_type": "table",
                    "title": "Regional sales",
                    "headers": ["Region", "Product A", "Product B"],
                    "rows": [["North", 1500, 800], ["South", 1200, 950.5]],
                }
            ],
        },
        {"title": "Thank you", "slide_type": "closing", "content_elements": [
            {"element_type": "text", "bullet_points": ["Questions?"]}
        ]},
    ],
}  # fmt: skip


@pytest.fixture
def sample_outline() -> dict[str, Any]:
    return copy.deepcopy(SAMPLE_OUTLINE)


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Never let a developer's real keys or .env leak into tests."""
    for var in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "TXT2PPTX_LLM_PROVIDER", "LLM_TEMPERATURE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.chdir(tmp_path)  # no .env in an empty temp dir
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(home=tmp_path, log_dir=None, docs_path=None, export_retention_hours=0)


@pytest.fixture
def service(settings: Settings) -> PresentationService:
    return PresentationService(settings)


class FakeStructuredLLM:
    """Stands in for a chat model: ``with_structured_output(schema)`` returns canned objects."""

    def __init__(self, responses: dict[type, Any]):
        self.responses = responses
        self.prompts: list[str] = []
        self.schemas: list[type] = []

    def with_structured_output(self, schema: type, **_: Any) -> RunnableLambda:
        self.schemas.append(schema)

        def respond(prompt_value: Any) -> Any:
            self.prompts.append(prompt_value.to_string())
            response = self.responses[schema]
            if isinstance(response, Exception):
                raise response
            return response

        return RunnableLambda(respond)


@pytest.fixture
def fake_llm_factory():
    return FakeStructuredLLM


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
