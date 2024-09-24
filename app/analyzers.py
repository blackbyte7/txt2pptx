from typing import Dict, List
import re


class ContentAnalyzer:
    def __init__(self):
        self.max_bullets_per_slide = 7
        self.optimal_words_per_bullet = 15

    def analyze_content(self, presentation_json: Dict) -> Dict:
        """Analyzes presentation content and provides improvement suggestions."""
        analysis = {
            "suggestions": [],
            "warnings": [],
            "slide_specific": {}
        }

        for idx, page in enumerate(presentation_json.get("pages", [])):
            slide_analysis = self._analyze_slide(page, idx + 1)
            if slide_analysis["suggestions"]:
                analysis["slide_specific"][f"Slide {idx + 1}"] = slide_analysis
            analysis["suggestions"].extend(slide_analysis["general_suggestions"])
            analysis["warnings"].extend(slide_analysis["warnings"])

        return analysis

    def _analyze_slide(self, slide: Dict, slide_num: int) -> Dict:
        analysis = {
            "suggestions": [],
            "warnings": [],
            "general_suggestions": []
        }

        # Analyze bullet points
        bullets = slide.get("bullet_points", [])
        if len(bullets) > self.max_bullets_per_slide:
            analysis["warnings"].append(
                f"Slide {slide_num} has too many bullet points ({len(bullets)}). "
                f"Consider splitting into multiple slides."
            )

        # Analyze bullet point length
        for idx, bullet in enumerate(bullets):
            words = len(bullet.split())
            if words > self.optimal_words_per_bullet:
                analysis["suggestions"].append(
                    f"Bullet point {idx + 1} is too long ({words} words). "
                    f"Consider simplifying."
                )

        # Title analysis
        title = slide.get("title", "")
        if len(title.split()) > 10:
            analysis["suggestions"].append("Consider using a shorter title")

        return analysis