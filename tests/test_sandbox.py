import pytest
from pptx import Presentation

from txt2pptx.sandbox import (
    UnsafeCodeError,
    _minimal_env,
    execute_presentation_code,
    strip_save_calls,
    validate_code,
)

SAFE = """
from pptx import Presentation
from pptx.util import Inches, Pt
presentation = Presentation()
slide = presentation.slides.add_slide(presentation.slide_layouts[0])
slide.shapes.title.text = "Hello"
presentation.save("whatever.pptx")
"""


@pytest.mark.parametrize(
    "code",
    [
        "from os import system\nsystem('echo hi')",
        "import os as o\no.execl('/bin/sh', 'sh')",
        "import subprocess",
        "import pathlib\npathlib.Path('x').write_text('y')",
        "().__class__.__bases__[0].__subclasses__()",
        "getattr(object, 'x')",
        "open('/etc/passwd').read()",
        "eval('1+1')",
        "__builtins__['eval']('1')",
        "__import__('os')",
        "from . import x",
        "import importlib",
        "x = [c for c in ().__class__.__mro__]",
        "slide.shapes.add_picture('/etc/passwd', 0, 0)",
    ],
)
def test_validate_blocks_known_bypasses(code):
    assert validate_code(code), code


def test_validate_accepts_typical_pptx_code():
    assert validate_code(strip_save_calls(SAFE)) == []


def test_syntax_error_reported():
    assert "Syntax error" in validate_code("def (:")[0]


def test_strip_save_calls_keeps_blocks_valid():
    code = "try:\n    prs.save('a.pptx')\nexcept Exception:\n    pass\nprs.save('b')"
    stripped = strip_save_calls(code)
    assert "save" not in stripped
    compile(stripped, "x", "exec")


def test_minimal_env_has_no_secrets(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "aws")
    env = _minimal_env()
    assert "OPENAI_API_KEY" not in env and "AWS_SECRET_ACCESS_KEY" not in env


def test_execute_saves_presentation_regardless_of_variable_name(tmp_path):
    out = tmp_path / "out" / "deck.pptx"
    result = execute_presentation_code(SAFE, out, timeout=60)
    assert result.output_path == out
    assert Presentation(str(out)).slides[0].shapes.title.text == "Hello"


def test_execute_rejects_unsafe_code(tmp_path):
    with pytest.raises(UnsafeCodeError, match="not allowed"):
        execute_presentation_code("import socket", tmp_path / "x.pptx")


def test_execute_reports_runtime_errors(tmp_path):
    with pytest.raises(RuntimeError, match="ZeroDivisionError"):
        execute_presentation_code(
            "from pptx import Presentation\nprs = Presentation()\n1/0", tmp_path / "x.pptx"
        )


def test_execute_requires_a_presentation(tmp_path):
    with pytest.raises(RuntimeError, match="did not create a Presentation"):
        execute_presentation_code("x = 1", tmp_path / "x.pptx")


def test_execute_timeout(tmp_path):
    with pytest.raises(RuntimeError, match="timed out"):
        execute_presentation_code("while True:\n    pass", tmp_path / "x.pptx", timeout=2)
