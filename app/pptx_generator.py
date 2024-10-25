from typing import Dict, Any, Optional
from pptx import Presentation
from pptx.util import Pt
from pptx.enum.text import MSO_AUTO_SIZE  # Keep if used, check usage
from pptx.dml.color import RGBColor
from pptx.exc import PackageNotFoundError
from log_config.logging_config import logger

# Default values
DEFAULT_FONT_NAME = "Calibri"
DEFAULT_FONT_SIZE = Pt(18)
DEFAULT_TITLE_FONT_SIZE = Pt(32)
DEFAULT_COLOR = RGBColor(0, 0, 0)


class PPTXGenerator:
    """Generates a PowerPoint presentation from a structured JSON."""

    def __init__(self, template: Optional[Dict] = None):
        """
        Initializes the generator with optional template data.

        Args:
            template (Optional[Dict]): A template dictionary containing colors, fonts,
                                        and layout mappings (e.g., from PresentationTemplates).
        """
        self.template = template or {}
        self.colors = self.template.get("colors", {})
        self.fonts = self.template.get("font", {})
        self.layout_map = self.template.get("layouts", {
            "title_slide": 0,
            "title_content": 1,
            "section_header": 2,
            "two_content": 3,
            "comparison": 4,
            "title_only": 5,
            "blank": 6,
            "content_with_caption": 7,
            "picture_with_caption": 8,
            "opening": 0,
            "content": 1,
            "closing": 1,
            "default": 1,
        })
        logger.debug(
            f"PPTXGenerator initialized with template: {self.template.get('name', 'Default')}, Layout Map Keys: {list(self.layout_map.keys())}")

    def _get_color(self, role: str, default: RGBColor = DEFAULT_COLOR) -> RGBColor:
        """Gets a color from the template by role, with fallback."""
        hex_color = self.colors.get(role)
        if hex_color and isinstance(hex_color, str) and hex_color.startswith('#'):
            try:
                hex_val = hex_color[1:]
                if len(hex_val) == 6:
                    return RGBColor.from_string(hex_val)
                else:
                    logger.warning(
                        f"Invalid hex color format '{hex_color}' (must be #RRGGBB). Using default for role '{role}'.")
                    return default
            except ValueError as ve:
                logger.warning(f"Invalid hex value in color '{hex_color}' for role '{role}': {ve}. Using default.")
                return default
        return default

    def _get_font_props(self, role: str) -> Dict[str, Any]:
        """Gets font name and size from the template by role."""
        font_info = self.fonts.get(role, {})
        default_size = DEFAULT_TITLE_FONT_SIZE if role == "heading" else DEFAULT_FONT_SIZE
        size_pt = font_info.get("size")
        try:
            font_size = Pt(int(size_pt)) if size_pt is not None else default_size
        except (ValueError, TypeError):
            logger.warning(f"Invalid font size '{size_pt}' for role '{role}'. Using default {default_size.pt}pt.")
            font_size = default_size

        return {
            "name": font_info.get("name", DEFAULT_FONT_NAME),
            "size": font_size,
        }

    def create_presentation_from_json(self, data: Dict[str, Any]) -> Optional[Presentation]:
        """Creates a pptx.Presentation object from the structured JSON data."""
        if not isinstance(data, dict) or "slides" not in data:
            logger.error("Invalid input data: Must be a dict with a 'slides' key.")
            return None

        try:
            # TODO: Allow specifying a base template file path
            # base_template_path = self.template.get("base_file")
            # prs = Presentation(base_template_path)
            prs = Presentation()
            logger.info(f"Starting presentation generation for {len(data['slides'])} slides.")

            if not prs.slide_layouts:
                logger.error("Failed to create presentation: The base presentation has no slide layouts.")
                return None

            for i, slide_data in enumerate(data.get("slides", [])):
                logger.debug(f"Generating Slide {i + 1}...")
                self._add_slide(prs, slide_data, i + 1)

            logger.info("Presentation generation completed.")
            return prs

        except PackageNotFoundError:
            logger.error("Failed to create presentation. Ensure python-pptx is installed correctly.")
            return None
        except FileNotFoundError as fnf:
            logger.error(f"Failed to create presentation. Base template file not found: {fnf}")
            return None
        except Exception as e:
            logger.error(f"An error occurred during presentation generation: {e}", exc_info=True)
            return None

    def _add_slide(self, prs: Presentation, slide_data: Dict[str, Any], slide_number: int):
        """Adds a single slide to the presentation based on slide_data."""
        if not isinstance(slide_data, dict):
            logger.warning(f"Skipping slide {slide_number}: Invalid slide data format (not a dict).")
            return

        slide_type = slide_data.get("slide_type", "content")
        layout_key_suggestion = slide_data.get("design_elements", {}).get("layout", slide_type)

        layout_index = self.layout_map.get(layout_key_suggestion, self.layout_map["default"])
        logger.debug(
            f"Slide {slide_number}: Type '{slide_type}', Layout Suggestion '{layout_key_suggestion}', Mapped Index: {layout_index}")

        try:
            if layout_index >= len(prs.slide_layouts):
                logger.warning(
                    f"Slide {slide_number}: Layout index {layout_index} (for key '{layout_key_suggestion}') is out of range for available layouts ({len(prs.slide_layouts)}). Falling back to layout 0.")
                layout_index = 0
            slide_layout = prs.slide_layouts[layout_index]
        except IndexError:
            logger.error(
                f"Slide {slide_number}: Cannot access any slide layouts (even index 0). Aborting slide creation.")
            return

        slide = prs.slides.add_slide(slide_layout)

        title_text = slide_data.get("title", "")
        if hasattr(slide.shapes, 'title') and slide.shapes.title and title_text:
            try:
                title_shape = slide.shapes.title
                title_shape.text = str(title_text)
                font_props = self._get_font_props("heading")

                if title_shape.has_text_frame and title_shape.text_frame.paragraphs:
                    p = title_shape.text_frame.paragraphs[0]
                    p.font.name = font_props["name"]
                    p.font.size = font_props.get("size", DEFAULT_TITLE_FONT_SIZE)
                    p.font.color.rgb = self._get_color("accent1", self._get_color("text"))
                else:
                    logger.warning(
                        f"Slide {slide_number}: Title shape found but lacks text frame/paragraph for formatting.")
            except Exception as title_err:
                logger.warning(f"Slide {slide_number}: Failed to set or format title: {title_err}")

        body_shape = None
        common_body_indices = [1, 13, 14]
        for idx in common_body_indices:
            try:
                potential_shape = slide.placeholders[idx]

                if potential_shape.has_text_frame:
                    body_shape = potential_shape
                    logger.debug(f"Slide {slide_number}: Found body placeholder at index {idx}.")
                    break
            except (IndexError, KeyError):
                continue

        if not body_shape:
            for shape in slide.placeholders:
                ph_name = shape.name.lower()
                if shape.has_text_frame and shape.placeholder_format.idx != 0 and (
                        'content' in ph_name or 'body' in ph_name or 'text' in ph_name):
                    body_shape = shape
                    logger.debug(
                        f"Slide {slide_number}: Found body placeholder via name/fallback logic at index {shape.placeholder_format.idx}.")
                    break

        if body_shape:
            try:
                tf = body_shape.text_frame
                tf.clear()
                # tf.margin_left = Inches(0.1)
                tf.word_wrap = True
                # tf.auto_size = MSO_AUTO_SIZE.SHAPE_TO_FIT_TEXT

                bullets = slide_data.get("bullet_points", [])
                if not isinstance(bullets, list):
                    logger.warning(f"Slide {slide_number}: 'bullet_points' is not a list. Skipping bullet population.")
                    bullets = []

                body_font_props = self._get_font_props("body")
                body_color = self._get_color("text")

                if bullets:
                    for i, bullet_text in enumerate(bullets):
                        if not isinstance(bullet_text, str):
                            logger.warning(
                                f"Slide {slide_number}, Bullet {i + 1}: Invalid format (not a string). Skipping.")
                            continue

                        if i == 0 and tf.paragraphs:
                            p = tf.paragraphs[0]
                        else:
                            p = tf.add_paragraph()

                        p.text = bullet_text
                        p.level = 0

                        p.font.name = body_font_props["name"]
                        p.font.size = body_font_props.get("size", DEFAULT_FONT_SIZE)
                        p.font.color.rgb = body_color
                else:
                    logger.debug(f"Slide {slide_number}: No bullet points provided for body placeholder.")
            except Exception as body_err:
                logger.warning(f"Slide {slide_number}: Failed to populate body placeholder: {body_err}")

        elif slide_type == "content" and layout_key_suggestion != "title_only" and layout_key_suggestion != "blank":
            logger.warning(
                f"Slide {slide_number}: Could not find a suitable body/content placeholder for layout suggestion '{layout_key_suggestion}' (index {layout_index}). Content may be missing.")

        notes_text = slide_data.get("speaker_notes")
        if notes_text and isinstance(notes_text, str):
            try:
                notes_slide = slide.notes_slide
                text_frame = notes_slide.notes_text_frame
                text_frame.clear()
                if not text_frame.paragraphs:
                    p = text_frame.add_paragraph()
                else:
                    p = text_frame.paragraphs[0]
                p.text = notes_text
                p.font.name = DEFAULT_FONT_NAME
                p.font.size = Pt(12)
                logger.debug(f"Slide {slide_number}: Added speaker notes.")
            except Exception as notes_err:
                logger.warning(f"Slide {slide_number}: Failed to add speaker notes: {notes_err}")
