import copy
import json
from pathlib import Path
from typing import Dict, List, Optional

from log_config.logging_config import logger


class PresentationTemplates:
    def __init__(self, templates_dir: str = "templates"):
        self.templates_dir = Path(templates_dir)
        self.templates_dir.mkdir(parents=True, exist_ok=True)
        self._default_templates: Dict[str, Dict] = {
            "professional": {
                "name": "professional",
                "description": "Clean, modern, corporate style.",
                "colors": {
                    "background": "#FFFFFF",
                    "text": "#2C3E50",
                    "accent1": "#3498DB",
                    "accent2": "#2980B9",
                    "text_light": "#7F8C8D",
                },
                "font": {
                    "heading": {"name": "Calibri", "size": 32, "bold": True},
                    "body": {"name": "Calibri", "size": 14, "bold": False},
                },
                "layouts": {
                    "title_slide": 0,
                    "title_content": 1,
                    "section_header": 2,
                    "two_content": 3,
                    "comparison": 4,
                    "title_only": 5,
                    "blank": 6,
                    "content_with_caption": 7,
                    "picture_with_caption": 8,
                },
            },
            "creative": {
                "name": "creative",
                "description": "Bold, vibrant, and expressive style.",
                "colors": {
                    "background": "#FDFEFE",
                    "text": "#5D6D7E",
                    "accent1": "#FF6B6B",
                    "accent2": "#4ECDC4",
                    "text_light": "#95A5A6",
                },
                "font": {
                    "heading": {"name": "Helvetica Neue", "size": 34, "bold": True},
                    "body": {"name": "Helvetica", "size": 14, "bold": False},
                },
                "layouts": {
                    "title_slide": 0,
                    "title_content": 1,
                    "section_header": 2,
                    "two_content": 3,
                    "comparison": 4,
                    "title_only": 5,
                    "blank": 6,
                    "content_with_caption": 7,
                    "picture_with_caption": 8,
                },
            },
        }
        self._load_templates()

    def _load_templates(self):
        """Loads templates from JSON files, creating defaults if they don't exist."""
        loaded_templates = {}
        for name, template_data in self._default_templates.items():
            template_file = self.templates_dir / f"{name}.json"
            if not template_file.exists():
                try:
                    with open(template_file, "w", encoding="utf-8") as f:
                        json.dump(template_data, f, indent=4)
                    logger.info(f"Created default template file: {template_file}")
                except IOError as e:
                    logger.error(f"Failed to write default template {name}: {e}")

        for file_path in self.templates_dir.glob("*.json"):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    template = json.load(f)
                    template_name = file_path.stem
                    if "name" not in template:
                        template["name"] = template_name
                    loaded_templates[template_name] = template
                logger.debug(f"Loaded template '{template_name}' from {file_path}")
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Failed to load or parse template file {file_path}: {e}")

        self._default_templates.update(loaded_templates)

    def list_templates(self) -> List[Dict[str, str]]:
        """Returns a list of available template names and descriptions."""
        return [
            {"name": name, "description": data.get("description", "No description")}
            for name, data in self._default_templates.items()
        ]

    def get_template(self, name: str) -> Optional[Dict]:
        """Gets a deep copy of a specific template by name."""
        template = self._default_templates.get(name)
        if not template:
            logger.warning(f"Template '{name}' not found.")
            return None
        return copy.deepcopy(template)

    def add_template(self, name: str, template_data: Dict, overwrite: bool = False) -> bool:
        """Adds or updates a template and saves it to a JSON file."""
        safe_name = Path(name).stem
        template_file = self.templates_dir / f"{safe_name}.json"
        if template_file.exists() and not overwrite:
            logger.error(f"Template '{safe_name}' already exists. Use overwrite=True to replace.")
            return False

        try:
            data_to_save = copy.deepcopy(template_data)
            data_to_save["name"] = safe_name
            with open(template_file, "w", encoding="utf-8") as f:
                json.dump(data_to_save, f, indent=4)
            self._default_templates[safe_name] = data_to_save
            logger.info(f"Saved template '{safe_name}' to {template_file}")
            return True
        except (IOError, TypeError) as e:
            logger.error(f"Failed to save template '{safe_name}': {e}")
            return False

    def customize_template(self, base_template_name: str, modifications: Dict) -> Optional[Dict]:
        """Creates a customized in-memory copy of an existing template."""
        base_template = self.get_template(base_template_name)
        if not base_template:
            logger.error(f"Cannot customize: Base template '{base_template_name}' not found.")
            return None

        custom_template = copy.deepcopy(base_template)
        for key, value in modifications.items():
            if isinstance(custom_template.get(key), dict) and isinstance(value, dict):
                for sub_key, sub_val in value.items():
                    if (
                        key == "font"
                        and isinstance(custom_template[key].get(sub_key), dict)
                        and isinstance(sub_val, str)
                    ):
                        custom_template[key][sub_key]["name"] = sub_val
                    elif (
                        isinstance(custom_template[key].get(sub_key), dict)
                        and isinstance(sub_val, dict)
                    ):
                        custom_template[key][sub_key].update(sub_val)
                    else:
                        custom_template[key][sub_key] = sub_val
            else:
                logger.warning(
                    f"Customization key '{key}' not found in base template '{base_template_name}', adding it.")
                custom_template[key] = value

        logger.info(f"Generated temporary customization based on '{base_template_name}'.")
        custom_template["name"] = f"{base_template_name}_custom"
        return custom_template

    def get_template_preview(self, name: str) -> Optional[Dict]:
        """Returns a simplified preview of a template's settings."""
        template = self.get_template(name)
        if not template:
            return None

        return {
            "name": template.get("name", name),
            "description": template.get("description", ""),
            "sample_colors": list(template.get("colors", {}).values())[:4],
            "fonts": template.get("font", {}),
            "sample_layout_keys": list(template.get("layouts", {}).keys())[:3],
        }
