from typing import Dict, List
import json
from pathlib import Path


class PresentationTemplates:
    def __init__(self, templates_dir: str = "templates"):
        self.templates_dir = Path(templates_dir)
        self.templates_dir.mkdir(exist_ok=True)
        self._load_default_templates()

    def _load_default_templates(self):
        default_templates = {
            "professional": {
                "colors": ["#2C3E50", "#E74C3C", "#ECF0F1"],
                "font": "Calibri",
                "slide_layouts": ["title", "two_content", "comparison"],
                "transitions": ["fade", "push", "cover"]
            },
            "creative": {
                "colors": ["#FF6B6B", "#4ECDC4", "#45B7D1"],
                "font": "Helvetica",
                "slide_layouts": ["picture_with_caption", "content_with_picture"],
                "transitions": ["wheel", "zoom", "gallery"]
            }
        }

        for name, template in default_templates.items():
            template_file = self.templates_dir / f"{name}.json"
            if not template_file.exists():
                with open(template_file, 'w') as f:
                    json.dump(template, f, indent=4)

    def get_template(self, name: str) -> Dict:
        template_file = self.templates_dir / f"{name}.json"
        if not template_file.exists():
            raise ValueError(f"Template {name} not found")

        with open(template_file, 'r') as f:
            return json.load(f)

    def add_template(self, name: str, template: Dict):
        template_file = self.templates_dir / f"{name}.json"
        with open(template_file, 'w') as f:
            json.dump(template, f, indent=4)