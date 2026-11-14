from pathlib import Path

import pytest

from txt2pptx.config import DEFAULT_ANTHROPIC_MODEL, Settings
from txt2pptx.llm import MissingAPIKeyError, create_chat_model, resolve_provider


def test_env_aliases(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("GRADIO_SERVER_PORT", "9999")
    monkeypatch.setenv("LOG_LEVEL", "debug")
    monkeypatch.setenv("TXT2PPTX_ENABLE_CODE_EXECUTION", "true")
    s = Settings()
    assert s.api_key_for("openai") == "sk-test"
    assert s.server_port == 9999
    assert s.log_level == "DEBUG"
    assert s.enable_code_execution is True
    assert s.default_provider() == "openai"


def test_dotenv_and_legacy_environment_env(tmp_path, monkeypatch):
    (tmp_path / "environment.env").write_text("ANTHROPIC_API_KEY=ak-legacy\n")
    monkeypatch.chdir(tmp_path)
    assert Settings().api_key_for("anthropic") == "ak-legacy"
    (tmp_path / ".env").write_text("ANTHROPIC_API_KEY=ak-new\n")
    assert Settings().api_key_for("anthropic") == "ak-new"


@pytest.mark.parametrize("placeholder", ["", "  ", "your_secret_key", "01010101"])
def test_placeholder_keys_are_ignored(monkeypatch, placeholder):
    monkeypatch.setenv("OPENAI_API_KEY", placeholder)
    s = Settings()
    assert s.openai_api_key is None
    assert s.default_provider() is None


def test_secrets_not_in_repr(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-very-secret")
    assert "sk-very-secret" not in repr(Settings())


def test_paths_resolve_against_home(tmp_path):
    s = Settings(home=tmp_path, output_dir=Path("out"), cache_dir=tmp_path / "abs")
    assert s.output_path == tmp_path / "out"
    assert s.cache_path == tmp_path / "abs"


def test_resolve_provider_requires_configuration():
    with pytest.raises(MissingAPIKeyError):
        resolve_provider(Settings(), None)
    assert resolve_provider(Settings(), "Anthropic") == "anthropic"


def test_create_chat_model_needs_key():
    with pytest.raises(MissingAPIKeyError, match="ANTHROPIC_API_KEY"):
        create_chat_model(Settings(), "anthropic")


def test_create_anthropic_model_defaults():
    model = create_chat_model(Settings(), "anthropic", api_key="ak-test")
    assert type(model).__name__ == "ChatAnthropic"
    assert model.model == DEFAULT_ANTHROPIC_MODEL
    assert model.max_tokens == 16_000


def test_create_openai_model_omits_temperature_by_default():
    model = create_chat_model(Settings(), "openai", api_key="sk-test", model="gpt-x")
    assert type(model).__name__ == "ChatOpenAI"
    assert model.model_name == "gpt-x"
    assert model.temperature is None


def test_temperature_passed_when_configured():
    model = create_chat_model(Settings(llm_temperature=0.3), "openai", api_key="sk-test")
    assert model.temperature == 0.3
