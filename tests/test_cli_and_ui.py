import json

import pytest

from txt2pptx.cli import main


@pytest.fixture
def cli_home(tmp_path, monkeypatch):
    monkeypatch.setenv("TXT2PPTX_HOME", str(tmp_path))
    monkeypatch.setenv("TXT2PPTX_LOG_DIR", "")
    monkeypatch.setenv("TXT2PPTX_DOCS_PATH", "")
    return tmp_path


def test_templates_command(cli_home, capsys):
    assert main(["templates"]) == 0
    out = capsys.readouterr().out
    assert "professional" in out and "dark" in out


def test_build_command_json(cli_home, sample_outline, capsys):
    outline = cli_home / "outline.json"
    outline.write_text(json.dumps(sample_outline), encoding="utf-8")
    assert main(["build", str(outline), "-t", "minimal", "-e", "html", "-n", "cli deck", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["slide_count"] == 5
    assert data["pptx_path"].endswith(".pptx")
    assert "cli-deck_" in data["pptx_path"]


def test_generate_without_key_fails_cleanly(cli_home, capsys):
    src = cli_home / "in.txt"
    src.write_text("hello world")
    assert main(["generate", str(src)]) == 1
    assert "OPENAI_API_KEY" in capsys.readouterr().err


def test_ui_builds(service):
    gr = pytest.importorskip("gradio")
    from txt2pptx.ui import _parse_overrides, create_app

    app = create_app(service)
    assert isinstance(app, gr.Blocks)
    assert _parse_overrides(' {"colors": {"accent1": "#000000"}} ') == {"colors": {"accent1": "#000000"}}
    assert _parse_overrides("") is None
    with pytest.raises(gr.Error):
        _parse_overrides("[1, 2]")
