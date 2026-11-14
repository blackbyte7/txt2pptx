"""Visual templates (colors, fonts, slide geometry).

Built-in templates ship inside the package (``builtin_templates/*.json``). Additional templates can be
dropped into the directory configured via ``TXT2PPTX_TEMPLATES_DIR``; a user template with the same name
overrides the built-in one. Templates are never written to disk implicitly.
"""

from __future__ import annotations

import copy
import json
import logging
import re
from importlib import resources
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

logger = logging.getLogger(__name__)

_HEX = re.compile(r"^#?[0-9A-Fa-f]{6}$")


class FontSpec(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = "Calibri"
    size: float = Field(18, gt=4, le=120)
    bold: bool = False
    italic: bool = False


class TemplateColors(BaseModel):
    model_config = ConfigDict(extra="allow")

    background: str = "#FFFFFF"
    text: str = "#1F2937"
    title: str | None = None
    accent1: str = "#2563EB"
    accent2: str = "#0EA5E9"
    accent3: str = "#10B981"
    accent4: str = "#F59E0B"
    text_light: str = "#6B7280"
    surface: str = "#FFFFFF"
    surface_alt: str = "#F3F4F6"
    on_accent: str = "#FFFFFF"

    @field_validator("*")
    @classmethod
    def _valid_hex(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if not isinstance(value, str) or not _HEX.match(value):
            raise ValueError(f"invalid color {value!r}; expected #RRGGBB")
        return value if value.startswith("#") else f"#{value}"

    def series_palette(self) -> list[str]:
        return [self.accent1, self.accent2, self.accent3, self.accent4]


class TemplateFonts(BaseModel):
    model_config = ConfigDict(extra="ignore")

    heading: FontSpec = Field(default_factory=lambda: FontSpec(size=36, bold=True))
    body: FontSpec = Field(default_factory=lambda: FontSpec(size=18))

    @field_validator("heading", "body", mode="before")
    @classmethod
    def _font_name_shorthand(cls, value: Any) -> Any:
        return {"name": value} if isinstance(value, str) else value


class Template(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    name: str
    description: str = ""
    aspect_ratio: Literal["16:9", "4:3"] = "16:9"
    colors: TemplateColors = Field(default_factory=TemplateColors)
    fonts: TemplateFonts = Field(default_factory=TemplateFonts, alias="font")
    layouts: dict[str, int] = Field(default_factory=dict, description="Layout-name -> slide layout index.")


class TemplateInfo(BaseModel):
    name: str
    description: str
    aspect_ratio: str
    colors: dict[str, str]


class TemplateManager:
    """Loads, lists and customizes templates."""

    def __init__(self, user_templates_dir: Path | None = None):
        self.user_templates_dir = user_templates_dir
        self._templates: dict[str, Template] = {}
        self._load_builtin()
        if user_templates_dir:
            self._load_dir(user_templates_dir)

    # ------------------------------------------------------------------------------------ loading --
    def _load_builtin(self) -> None:
        package_dir = resources.files("txt2pptx") / "builtin_templates"
        for entry in sorted(package_dir.iterdir(), key=lambda p: p.name):
            if entry.name.endswith(".json"):
                self._register(entry.name[:-5], entry.read_text(encoding="utf-8"), source="built-in")

    def _load_dir(self, directory: Path) -> None:
        if not directory.is_dir():
            logger.warning("Templates directory %s does not exist; ignoring.", directory)
            return
        for path in sorted(directory.glob("*.json")):
            try:
                self._register(path.stem, path.read_text(encoding="utf-8"), source=str(path))
            except OSError as exc:
                logger.warning("Could not read template %s: %s", path, exc)

    def _register(self, stem: str, raw: str, *, source: str) -> None:
        try:
            data = json.loads(raw)
            data.setdefault("name", stem)
            template = Template.model_validate(data)
        except (json.JSONDecodeError, ValidationError) as exc:
            logger.warning("Skipping invalid template %s (%s): %s", stem, source, exc)
            return
        self._templates[template.name] = template
        logger.debug("Loaded template %r from %s", template.name, source)

    # ------------------------------------------------------------------------------------- access --
    def names(self) -> list[str]:
        return list(self._templates)

    def list_templates(self) -> list[TemplateInfo]:
        return [
            TemplateInfo(
                name=t.name,
                description=t.description,
                aspect_ratio=t.aspect_ratio,
                colors=t.colors.model_dump(exclude_none=True),
            )
            for t in self._templates.values()
        ]

    def get(self, name: str) -> Template:
        try:
            return self._templates[name].model_copy(deep=True)
        except KeyError:
            raise KeyError(f"Unknown template {name!r}. Available: {', '.join(self.names())}") from None

    def customize(self, name: str, overrides: dict[str, Any] | None) -> Template:
        """Return a validated copy of template *name* with *overrides* deep-merged in."""
        base = self.get(name)
        if not overrides:
            return base
        merged = _deep_merge(base.model_dump(by_alias=False), _normalise_overrides(overrides))
        merged["name"] = f"{base.name}_custom"
        try:
            return Template.model_validate(merged)
        except ValidationError as exc:
            raise ValueError(f"Invalid template customization: {exc}") from exc


def _normalise_overrides(overrides: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(overrides)
    if "font" in result and "fonts" not in result:
        result["fonts"] = result.pop("font")
    fonts = result.get("fonts")
    if isinstance(fonts, dict):
        for role, spec in list(fonts.items()):
            if isinstance(spec, str):
                fonts[role] = {"name": spec}
    return result


def _deep_merge(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out
