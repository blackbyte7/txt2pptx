import pytest
import json
from pathlib import Path
from app.pptx_generator import DEFAULT_FONT_NAME, DEFAULT_COLOR
from templates.templates import PresentationTemplates

TEMPLATE_DIR_NAME = "test_templates_dir"

@pytest.fixture
def template_manager(tmp_path):
    """Creates a PresentationTemplates instance using a temporary directory."""
    templates_dir = tmp_path / TEMPLATE_DIR_NAME
    manager = PresentationTemplates(templates_dir=str(templates_dir))
    return manager

@pytest.fixture
def populated_template_manager(tmp_path):
    """Creates a PresentationTemplates instance and ensures default files exist."""
    templates_dir = tmp_path / TEMPLATE_DIR_NAME
    templates_dir.mkdir()
    prof_path = templates_dir / "professional.json"
    creative_path = templates_dir / "creative.json"

    if not prof_path.exists():
        with open(prof_path, "w") as f:
            json.dump({
                "name": "professional", "description": "Prof Desc",
                "colors": {"text": "#111111"}, "font": {"body": "Arial"},
                "layouts": {"title_slide": 0}
            }, f)
    if not creative_path.exists():
         with open(creative_path, "w") as f:
            json.dump({
                "name": "creative", "description": "Creative Desc",
                "colors": {"text": "#222222"}, "font": {"body": "Times New Roman"},
                 "layouts": {"title_slide": 0}
            }, f)

    # Init manager *after* files potentially created
    manager = PresentationTemplates(templates_dir=str(templates_dir))
    return manager


def test_init_creates_default_files(tmp_path):
    """Test if __init__ creates default JSON files if they don't exist."""
    templates_dir = tmp_path / TEMPLATE_DIR_NAME
    assert not templates_dir.exists()
    manager = PresentationTemplates(templates_dir=str(templates_dir))
    assert templates_dir.exists()
    assert (templates_dir / "professional.json").exists()
    assert (templates_dir / "creative.json").exists()

    # Check content (basic check)
    with open(templates_dir / "professional.json", 'r') as f:
        data = json.load(f)
        assert data["name"] == "professional"
        assert "colors" in data

def test_init_loads_existing_files(tmp_path):
    """Test if __init__ loads templates from existing files."""
    templates_dir = tmp_path / TEMPLATE_DIR_NAME
    templates_dir.mkdir()
    custom_template_path = templates_dir / "custom.json"
    custom_data = {
        "name": "custom", "description": "My Custom Template",
        "colors": {"text": "#ABCDEF"}, "font": {"heading": "Comic Sans MS"},
        "layouts": {"title_slide": 0}
    }
    with open(custom_template_path, 'w') as f:
        json.dump(custom_data, f)

    manager = PresentationTemplates(templates_dir=str(templates_dir))
    # Should load default AND custom
    loaded_names = [t['name'] for t in manager.list_templates()]
    assert "professional" in loaded_names
    assert "creative" in loaded_names
    assert "custom" in loaded_names

    custom_tpl = manager.get_template("custom")
    assert custom_tpl is not None
    assert custom_tpl["description"] == "My Custom Template"
    assert custom_tpl["colors"]["text"] == "#ABCDEF"

def test_list_templates(populated_template_manager):
    """Test listing available templates."""
    templates = populated_template_manager.list_templates()
    assert isinstance(templates, list)
    assert len(templates) >= 2 # professional and creative
    names = [t['name'] for t in templates]
    assert "professional" in names
    assert "creative" in names
    assert all("name" in t and "description" in t for t in templates)

def test_get_template_found(populated_template_manager):
    """Test getting an existing template."""
    template = populated_template_manager.get_template("professional")
    assert template is not None
    assert isinstance(template, dict)
    assert template["name"] == "professional"
    assert "colors" in template
    assert "font" in template
    # Test it returns a copy
    template["colors"]["text"] = "#MODIFIED"
    original_template = populated_template_manager.get_template("professional")
    assert original_template["colors"]["text"] != "#MODIFIED"


def test_get_template_not_found(populated_template_manager):
    """Test getting a non-existent template."""
    template = populated_template_manager.get_template("non_existent_template")
    assert template is None

def test_add_template_new(template_manager):
    """Test adding a new template."""
    templates_dir = template_manager.templates_dir
    new_template_data = {
        "description": "A brand new template",
        "colors": {"background": "#000000"},
        "font": {"body": "Impact"},
        "layouts": {"default": 6} # Blank layout default
    }
    success = template_manager.add_template("new_one", new_template_data)
    assert success is True

    # Check file saved
    new_file = templates_dir / "new_one.json"
    assert new_file.exists()
    with open(new_file, 'r') as f:
        saved_data = json.load(f)
        assert saved_data["name"] == "new_one" # Name should be added
        assert saved_data["description"] == "A brand new template"
        assert saved_data["layouts"]["default"] == 6

    # Check internal dictionary
    retrieved_template = template_manager.get_template("new_one")
    assert retrieved_template is not None
    assert retrieved_template["name"] == "new_one"

def test_add_template_overwrite_false(populated_template_manager):
    """Test adding a template that exists without overwrite."""
    success = populated_template_manager.add_template("professional", {"description": "Attempt Overwrite"})
    assert success is False
    # Verify original data wasn't overwritten
    template = populated_template_manager.get_template("professional")
    assert template["description"] != "Attempt Overwrite" # Should retain original description

def test_add_template_overwrite_true(populated_template_manager):
    """Test adding a template that exists with overwrite."""
    templates_dir = populated_template_manager.templates_dir
    new_data = {"description": "Successfully Overwritten", "colors": {"text": "#FFFFFF"}}
    success = populated_template_manager.add_template("professional", new_data, overwrite=True)
    assert success is True

    # Check file saved
    prof_file = templates_dir / "professional.json"
    with open(prof_file, 'r') as f:
        saved_data = json.load(f)
        assert saved_data["description"] == "Successfully Overwritten"
        assert saved_data["colors"]["text"] == "#FFFFFF"

    # Check internal dictionary
    retrieved_template = populated_template_manager.get_template("professional")
    assert retrieved_template["description"] == "Successfully Overwritten"

def test_customize_template_found(populated_template_manager):
    """Test customizing an existing template."""
    modifications = {
        "colors": {"accent1": "#FF0000", "new_color": "#00FF00"},
        "font": {"heading": "Impact"},
        "layouts": {"title_slide": 1}, # Change existing layout index
        "new_section": {"info": "test"} # Add new top-level key
    }
    custom_template = populated_template_manager.customize_template("professional", modifications)

    assert custom_template is not None
    assert custom_template["name"] == "professional_custom" # Name reflects customization
    # Check merged/overwritten values
    assert custom_template["colors"]["accent1"] == "#FF0000" # Overwritten
    assert custom_template["colors"]["text"] == "#111111" # Original retained
    assert custom_template["colors"]["new_color"] == "#00FF00" # New added
    assert custom_template["font"]["heading"] == "Impact" # Overwritten
    assert custom_template["font"]["body"] == "Arial" # Original retained
    assert custom_template["layouts"]["title_slide"] == 1 # Overwritten
    assert custom_template["new_section"]["info"] == "test" # New section added

def test_customize_template_not_found(populated_template_manager):
    """Test customizing a non-existent template."""
    custom_template = populated_template_manager.customize_template("non_existent", {"colors": {"text": "#000"}})
    assert custom_template is None

def test_get_template_preview(populated_template_manager):
    """Test getting a template preview."""
    preview = populated_template_manager.get_template_preview("professional")
    assert preview is not None
    assert preview["name"] == "professional"
    assert "description" in preview
    assert "sample_colors" in preview
    assert isinstance(preview["sample_colors"], list)
    assert "fonts" in preview
    assert isinstance(preview["fonts"], dict)
    assert "sample_layout_keys" in preview
    assert isinstance(preview["sample_layout_keys"], list)

def test_get_template_preview_not_found(populated_template_manager):
    """Test preview for a non-existent template."""
    preview = populated_template_manager.get_template_preview("non_existent")
    assert preview is None

