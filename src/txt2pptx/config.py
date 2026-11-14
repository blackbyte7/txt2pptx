"""Typed application configuration (environment variables / `.env`)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LLMProvider = Literal["openai", "anthropic"]

DEFAULT_OPENAI_MODEL = "gpt-6-astra"
DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-5-5"
DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"

# Values commonly left in example env files that must never be sent to a provider.
_PLACEHOLDER_KEYS = {
    "",
    "key",
    "01010101",
    "your_secret_key",
    "your_api_key",
    "your_anthropic_api_key",
    "sk-...",
}


def _alias(*names: str) -> AliasChoices:
    return AliasChoices(*names)


class Settings(BaseSettings):
    """All runtime configuration.

    Well-known variables (``OPENAI_API_KEY``, ``ANTHROPIC_API_KEY``, ``LOG_LEVEL`` ...) are read under their
    usual names; everything app-specific uses the ``TXT2PPTX_`` prefix.
    Values are read from the process environment first, then ``.env`` (and the legacy ``environment.env``).
    """

    model_config = SettingsConfigDict(
        env_prefix="TXT2PPTX_",
        env_file=("environment.env", ".env"),  # later files win
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    # --- LLM providers -------------------------------------------------------------------------------
    openai_api_key: SecretStr | None = Field(None, validation_alias=_alias("OPENAI_API_KEY"))
    anthropic_api_key: SecretStr | None = Field(None, validation_alias=_alias("ANTHROPIC_API_KEY"))
    llm_provider: LLMProvider | None = Field(
        None,
        validation_alias=_alias("TXT2PPTX_LLM_PROVIDER", "LLM_PROVIDER"),
        description="Default provider. If unset, the first provider with an API key is used.",
    )
    openai_model: str = Field(DEFAULT_OPENAI_MODEL, validation_alias=_alias("OPENAI_MODEL"))
    anthropic_model: str = Field(DEFAULT_ANTHROPIC_MODEL, validation_alias=_alias("ANTHROPIC_MODEL"))
    llm_temperature: float | None = Field(
        None,
        ge=0,
        le=2,
        validation_alias=_alias("LLM_TEMPERATURE"),
        description="Leave unset to use the provider default (required by most reasoning models).",
    )
    llm_max_tokens: int = Field(16_000, gt=0, validation_alias=_alias("LLM_MAX_TOKENS"))
    llm_timeout_seconds: float = Field(240.0, gt=0, validation_alias=_alias("LLM_TIMEOUT_SECONDS"))
    llm_max_retries: int = Field(2, ge=0, validation_alias=_alias("LLM_MAX_RETRIES"))
    embedding_model: str = Field(DEFAULT_EMBEDDING_MODEL, validation_alias=_alias("EMBEDDING_MODEL"))

    # --- Paths ---------------------------------------------------------------------------------------
    home: Path = Field(Path(), description="Base directory that relative paths below are resolved against.")
    output_dir: Path = Path("exports")
    cache_dir: Path = Path("cache")
    log_dir: Path | None = Path("logs")
    templates_dir: Path | None = Field(None, description="Optional directory with extra *.json templates.")
    docs_path: Path | None = Field(
        Path("data/python-pptx-documentation.pdf"),
        validation_alias=_alias("TXT2PPTX_DOCS_PATH", "DOCS_PATH"),
        description="Reference documentation used for retrieval-augmented generation.",
    )

    # --- Behaviour / limits --------------------------------------------------------------------------
    log_level: str = Field("INFO", validation_alias=_alias("TXT2PPTX_LOG_LEVEL", "LOG_LEVEL"))
    max_input_chars: int = Field(120_000, gt=1000)
    max_upload_mb: int = Field(25, gt=0)
    max_slides: int = Field(30, ge=1, le=100)
    export_retention_hours: float = Field(72.0, ge=0, description="0 disables automatic cleanup.")
    enable_code_execution: bool = Field(
        False,
        description="Allow the experimental mode that executes LLM-written python-pptx code in a subprocess.",
    )
    code_execution_timeout: int = Field(60, gt=0)

    # --- Web UI --------------------------------------------------------------------------------------
    server_name: str = Field(
        "127.0.0.1", validation_alias=_alias("TXT2PPTX_SERVER_NAME", "GRADIO_SERVER_NAME")
    )
    server_port: int = Field(7860, validation_alias=_alias("TXT2PPTX_SERVER_PORT", "GRADIO_SERVER_PORT"))
    ui_auth: SecretStr | None = Field(None, description="Basic auth for the web UI as 'user:password'.")

    # --- MCP server ----------------------------------------------------------------------------------
    mcp_host: str = "127.0.0.1"
    mcp_port: int = 8000
    mcp_allowed_hosts: list[str] = Field(
        default_factory=list,
        description="Extra Host headers accepted by the HTTP transport (DNS-rebinding protection).",
    )

    @field_validator("openai_api_key", "anthropic_api_key", mode="before")
    @classmethod
    def _drop_placeholder_keys(cls, value: object) -> object:
        if isinstance(value, str) and value.strip() in _PLACEHOLDER_KEYS:
            return None
        return value.strip() if isinstance(value, str) else value

    @field_validator("log_level")
    @classmethod
    def _upper_log_level(cls, value: str) -> str:
        return value.upper()

    # --- Derived helpers -----------------------------------------------------------------------------
    def resolve(self, path: Path) -> Path:
        path = path.expanduser()
        return path if path.is_absolute() else (self.home.expanduser() / path)

    @property
    def output_path(self) -> Path:
        return self.resolve(self.output_dir)

    @property
    def cache_path(self) -> Path:
        return self.resolve(self.cache_dir)

    @property
    def log_path(self) -> Path | None:
        return self.resolve(self.log_dir) if self.log_dir else None

    @property
    def resolved_docs_path(self) -> Path | None:
        return self.resolve(self.docs_path) if self.docs_path else None

    def api_key_for(self, provider: LLMProvider) -> str | None:
        secret = self.openai_api_key if provider == "openai" else self.anthropic_api_key
        return secret.get_secret_value() if secret else None

    def default_provider(self) -> LLMProvider | None:
        if self.llm_provider:
            return self.llm_provider
        if self.openai_api_key:
            return "openai"
        if self.anthropic_api_key:
            return "anthropic"
        return None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings singleton (call ``get_settings.cache_clear()`` in tests)."""
    return Settings()
