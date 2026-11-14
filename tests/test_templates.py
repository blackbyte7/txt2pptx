import json

import pytest

from txt2pptx.templates import TemplateManager


def test_builtin_templates_load():
    manager = TemplateManager()
    assert {"professional", "creative", "minimal", "dark"} <= set(manager.names())
    pro = manager.get("professional")
    assert pro.aspect_ratio == "16:9"
    assert pro.fonts.heading.bold is True
    assert pro.colors.background == "#FFFFFF"


def test_get_returns_copy():
    manager = TemplateManager()
    manager.get("professional").colors.accent1 = "#000000"
    assert manager.get("professional").colors.accent1 != "#000000"


def test_unknown_template():
    with pytest.raises(KeyError, match="Available"):
        TemplateManager().get("nope")


def test_user_templates_dir_overrides_and_skips_invalid(tmp_path):
    (tmp_path / "professional.json").write_text(json.dumps({"description": "mine", "aspect_ratio": "4:3"}))
    (tmp_path / "broken.json").write_text("{not json")
    (tmp_path / "badcolor.json").write_text(json.dumps({"colors": {"text": "red"}}))
    manager = TemplateManager(tmp_path)
    assert manager.get("professional").description == "mine"
    assert manager.get("professional").aspect_ratio == "4:3"
    assert "broken" not in manager.names()
    assert "badcolor" not in manager.names()


def test_missing_user_dir_is_ignored(tmp_path):
    assert "professional" in TemplateManager(tmp_path / "missing").names()


def test_customize_deep_merges_and_supports_legacy_font_strings():
    manager = TemplateManager()
    custom = manager.customize(
        "professional", {"colors": {"accent1": "ff5500"}, "font": {"body": "Georgia"}, "aspect_ratio": "4:3"}
    )
    assert custom.name == "professional_custom"
    assert custom.colors.accent1 == "#ff5500"
    assert custom.colors.text == manager.get("professional").colors.text  # untouched
    assert custom.fonts.body.name == "Georgia"
    assert custom.fonts.body.size == manager.get("professional").fonts.body.size
    assert custom.aspect_ratio == "4:3"


def test_customize_rejects_invalid_values():
    with pytest.raises(ValueError, match="Invalid template customization"):
        TemplateManager().customize("professional", {"colors": {"accent1": "blue"}})


def test_list_templates_info():
    info = {t.name: t for t in TemplateManager().list_templates()}
    assert info["dark"].colors["background"] == "#111827"
