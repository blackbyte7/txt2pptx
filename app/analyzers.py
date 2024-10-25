from typing import Dict, List, Any
from log_config.logging_config import logger


class ContentAnalyzer:
    def __init__(self, max_bullets: int = 7, optimal_words: int = 20, max_title_words: int = 10):
        self.max_bullets_per_slide = max_bullets
        self.optimal_words_per_bullet = optimal_words
        self.max_title_words = max_title_words
        logger.debug(
            f"ContentAnalyzer initialized with: max_bullets={max_bullets}, optimal_words={optimal_words}, max_title_words={max_title_words}")

    def analyze_presentation_structure(self, presentation_json: Dict[str, Any]) -> Dict[str, List[str]]:
        """
        Analyzes the structured presentation JSON for potential improvements.

        Args:
            presentation_json (Dict[str, Any]): The structured JSON output
                                                  from the bullet point generation tool.

        Returns:
            Dict[str, List[str]]: A dictionary containing lists of suggestions and warnings.
        """
        analysis = {
            "suggestions": [],
            "warnings": [],
        }
        if not isinstance(presentation_json, dict) or "slides" not in presentation_json:
            logger.warning("Invalid presentation structure received for analysis.")
            analysis["warnings"].append("Invalid presentation structure format.")
            return analysis

        logger.info(f"Analyzing presentation structure with {len(presentation_json.get('slides', []))} slides.")

        total_slides = len(presentation_json.get("slides", []))
        if total_slides == 0:
            analysis["warnings"].append("Presentation structure has no slides.")
            return analysis
        elif total_slides == 1:
            analysis["suggestions"].append(
                "Consider adding more slides for better pacing, unless it's a single-point presentation.")
        elif total_slides > 20:
            analysis["warnings"].append(
                f"Presentation has a large number of slides ({total_slides}). Ensure content is concise and engaging per slide.")

        for idx, slide in enumerate(presentation_json.get("slides", [])):
            slide_num = slide.get("slide_number", idx + 1)  # Use provided number or index
            slide_analysis = self._analyze_slide(slide, slide_num)
            analysis["suggestions"].extend(slide_analysis["suggestions"])
            analysis["warnings"].extend(slide_analysis["warnings"])

        logger.info(
            f"Analysis complete: {len(analysis['suggestions'])} suggestions, {len(analysis['warnings'])} warnings.")
        return analysis

    def _analyze_slide(self, slide: Dict[str, Any], slide_num: int) -> Dict[str, List[str]]:
        """Analyzes a single slide dictionary."""
        slide_analysis = {
            "suggestions": [],
            "warnings": [],
        }
        slide_id = f"Slide {slide_num}"
        bullets = slide.get("bullet_points", [])
        if not isinstance(bullets, list):
            slide_analysis["warnings"].append(f"{slide_id}: Invalid format for 'bullet_points'. Expected a list.")
            bullets = []

        if len(bullets) > self.max_bullets_per_slide:
            slide_analysis["warnings"].append(
                f"{slide_id}: Contains {len(bullets)} bullet points (>{self.max_bullets_per_slide}). "
                f"Consider splitting content across multiple slides or summarizing."
            )
        elif len(bullets) == 0 and slide.get("slide_type", "content") == "content":
            slide_analysis["suggestions"].append(
                f"{slide_id}: Has no bullet points. Ensure content is present or consider a different slide type/layout."
            )

        for i, bullet in enumerate(bullets):
            if not isinstance(bullet, str):
                slide_analysis["warnings"].append(f"{slide_id}, Bullet {i + 1}: Invalid format. Expected a string.")
                continue
            words = len(bullet.split())
            if words > self.optimal_words_per_bullet:
                slide_analysis["suggestions"].append(
                    f"{slide_id}, Bullet {i + 1}: Is long ({words} words > {self.optimal_words_per_bullet}). "
                    f"Consider simplifying or breaking it down."
                )
            elif words == 0:
                slide_analysis["warnings"].append(f"{slide_id}, Bullet {i + 1}: Is empty.")

        title = slide.get("title", "")
        if not isinstance(title, str):
            slide_analysis["warnings"].append(f"{slide_id}: Invalid format for 'title'. Expected a string.")
            title = ""  # Treat as empty

        if len(title.split()) > self.max_title_words:
            slide_analysis["suggestions"].append(
                f"{slide_id}: Title is long ({len(title.split())} words > {self.max_title_words}). Consider shortening for impact."
            )
        if not title and slide.get("slide_type", "content") != "opening":  # Allow opening slide without title sometimes
            slide_analysis["warnings"].append(
                f"{slide_id}: Is missing a title. Most slides benefit from a clear title.")

        notes = slide.get("speaker_notes", "")
        if not isinstance(notes, str):
            slide_analysis["warnings"].append(f"{slide_id}: Invalid format for 'speaker_notes'. Expected a string.")

        return slide_analysis
