from typing import Dict, Optional, List
from pathlib import Path
import pptx
import pdf2image


class PresentationExporter:
    def __init__(self, output_dir: str = "exports"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)

    def export_presentation(self,
                            pptx_path: str,
                            formats: List[str] = ["pdf", "html", "images"],
                            output_name: Optional[str] = None) -> Dict[str, str]:
        """Exports the presentation to multiple formats."""
        if not output_name:
            output_name = Path(pptx_path).stem

        results = {
            "original": pptx_path,
            "exports": {}
        }

        for format_type in formats:
            try:
                if format_type == "pdf":
                    pdf_path = self._export_to_pdf(pptx_path, output_name)
                    results["exports"]["pdf"] = pdf_path

                elif format_type == "html":
                    html_path = self._export_to_html(pptx_path, output_name)
                    results["exports"]["html"] = html_path

                elif format_type == "images":
                    image_paths = self._export_to_images(pptx_path, output_name)
                    results["exports"]["images"] = image_paths

            except Exception as e:
                results["exports"][format_type] = f"Export failed: {str(e)}"

        return results

    def _export_to_pdf(self, pptx_path: str, output_name: str) -> str:
        output_path = self.output_dir / f"{output_name}.pdf"
        presentation = pptx.Presentation(pptx_path)
        # Implementation would use a PDF conversion library
        # For example: win32com.client for Windows or unoconv for Linux
        return str(output_path)

    def _export_to_html(self, pptx_path: str, output_name: str) -> str:
        output_path = self.output_dir / f"{output_name}.html"
        presentation = pptx.Presentation(pptx_path)

        html_content = ["<html><body>"]
        for slide in presentation.slides:
            html_content.append("<div class='slide'>")
            for shape in slide.shapes:
                if hasattr(shape, "text"):
                    html_content.append(f"<p>{shape.text}</p>")
            html_content.append("</div>")
        html_content.append("</body></html>")

        with open(output_path, "w") as f:
            f.write("\n".join(html_content))

        return str(output_path)

    def _export_to_images(self, pptx_path: str, output_name: str) -> List[str]:
        image_dir = self.output_dir / f"{output_name}_images"
        image_dir.mkdir(exist_ok=True)

        # Convert PDF to images first
        pdf_path = self._export_to_pdf(pptx_path, output_name)
        images = pdf2image.convert_from_path(pdf_path)

        image_paths = []
        for idx, image in enumerate(images):
            image_path = image_dir / f"slide_{idx + 1}.png"
            image.save(image_path)
            image_paths.append(str(image_path))

        return image_paths