import copy
import json
from pathlib import Path
from typing import Dict, Optional, List

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
                },
                "font": {
                    "heading": "Calibri",
                    "body": "Calibri"
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
                    "picture_with_caption": 8
                }
                # "transitions": ["fade", "push", "cover"]
            },
            "creative": {
                "name": "creative",
                "description": "Bold, vibrant, and expressive style.",
                "colors": {
                    "background": "#FDFEFE",
                    "text": "#5D6D7E",
                    "accent1": "#FF6B6B",
                    "accent2": "#4ECDC4",
                },
                "font": {
                    "heading": "Helvetica Neue",
                    "body": "Helvetica"
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
                    "picture_with_caption": 8
                }
                # "transitions": ["wheel", "zoom", "gallery"]
            }
        }
        self._load_templates()

    def _load_templates(self):
        """Loads templates from JSON files, creating defaults if they don't exist."""
        loaded_templates = {}
        for name, template_data in self._default_templates.items():
            template_file = self.templates_dir / f"{name}.json"
            if not template_file.exists():
                try:
                    with open(template_file, 'w', encoding='utf-8') as f:
                        json.dump(template_data, f, indent=4)
                    logger.info(f"Created default template file: {template_file}")
                except IOError as e:
                    logger.error(f"Failed to write default template {name}: {e}")

        for file_path in self.templates_dir.glob("*.json"):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
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
        """Gets a specific template by name."""
        template = self._default_templates.get(name)
        if not template:
            logger.warning(f"Template '{name}' not found.")
            return None
        return copy.deepcopy(template)

    def add_template(self, name: str, template_data: Dict, overwrite: bool = False) -> bool:
        """Adds or updates a template and saves it to a JSON file."""
        template_file = self.templates_dir / f"{name}.json"
        if template_file.exists() and not overwrite:
            logger.error(f"Template '{name}' already exists. Use overwrite=True to replace.")
            return False

        try:
            template_data["name"] = name
            with open(template_file, 'w', encoding='utf-8') as f:
                json.dump(template_data, f, indent=4)
            self._default_templates[name] = template_data
            logger.info(f"Saved template '{name}' to {template_file}")
            return True
        except IOError as e:
            logger.error(f"Failed to save template '{name}': {e}")
            return False
        except TypeError as e:
            logger.error(f"Invalid data provided for template '{name}': {e}")
            return False

    def customize_template(self, base_template_name: str, modifications: Dict) -> Optional[Dict]:
        """
        Creates a customized copy of an existing template.

        Args:
            base_template_name: Name of the template to base the customization on.
            modifications: Dictionary of changes to apply (e.g., {"colors": {...}}).

        Returns:
            The customized template dictionary, or None if the base template doesn't exist.
            Note: This currently doesn't save the custom template permanently.
        """
        base_template = self.get_template(base_template_name)
        if not base_template:
            logger.error(f"Cannot customize: Base template '{base_template_name}' not found.")
            return None

        custom_template = base_template.copy()
        for key, value in modifications.items():
            if isinstance(custom_template.get(key), dict) and isinstance(value, dict):
                custom_template[key].update(value)
            elif key in custom_template:
                custom_template[key] = value
            else:
                logger.warning(
                    f"Customization key '{key}' not found in base template '{base_template_name}', adding it.")
                custom_template[key] = value

        # timestamp = int(time.time())
        # custom_name = f"{base_template_name}_custom_{timestamp}"
        # self.add_template(custom_name, custom_template)
        # logger.info(f"Created custom template '{custom_name}' based on '{base_template_name}'.")
        # return self.get_template(custom_name)

        logger.info(f"Generated temporary customization based on '{base_template_name}'.")
        custom_template["name"] = f"{base_template_name}_custom"
        return custom_template

    def get_template_preview(self, name: str) -> Optional[Dict]:
        """Returns a simplified preview of a template's settings."""
        template = self.get_template(name)
        if not template:
            return None

        preview = {
            "name": template.get("name", name),
            "description": template.get("description", ""),
            "sample_colors": list(template.get("colors", {}).values())[:4],
            "fonts": template.get("font", {}),
            "sample_layout_keys": list(template.get("layouts", {}).keys())[:3],
        }
        return preview
