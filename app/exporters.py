from typing import Dict, List
import pptx
import pdf2image
import platform
import subprocess
from pathlib import Path
import tempfile
from typing import Optional
import win32com.client
import comtypes.client
from logging.logging_config import logger


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
        """
        Export PowerPoint presentation to PDF using platform-specific methods.

        Args:
            pptx_path (str): Path to the input PPTX file
            output_name (str): Desired name for the output PDF file

        Returns:
            str: Path to the generated PDF file
        """
        output_path = self.output_dir / f"{output_name}.pdf"

        try:
            if platform.system() == "Windows":
                return self._export_to_pdf_windows(pptx_path, output_path)
            else:
                return self._export_to_pdf_unix(pptx_path, output_path)

        except Exception as e:
            logger.error(f"PDF export failed: {str(e)}")
            raise

    def _export_to_pdf_windows(self, pptx_path: str, output_path: Path) -> str:
        """Windows-specific PDF export using COM automation."""
        try:
            # Try using comtypes first
            powerpoint = comtypes.client.CreateObject("Powerpoint.Application")
            powerpoint.Visible = True

            deck = powerpoint.Presentations.Open(str(Path(pptx_path).absolute()))
            deck.SaveAs(str(output_path.absolute()), 32)  # 32 is the PDF format code
            deck.Close()
            powerpoint.Quit()

            return str(output_path)

        except Exception as first_error:
            logger.warning(f"Comtypes export failed, trying win32com: {str(first_error)}")

            try:
                # Fallback to win32com
                powerpoint = win32com.client.Dispatch("Powerpoint.Application")
                powerpoint.Visible = True

                deck = powerpoint.Presentations.Open(str(Path(pptx_path).absolute()))
                deck.SaveAs(str(output_path.absolute()), 32)
                deck.Close()
                powerpoint.Quit()

                return str(output_path)

            except Exception as second_error:
                logger.error(f"Both PDF export methods failed on Windows: {str(second_error)}")
                raise

    def _export_to_pdf_unix(self, pptx_path: str, output_path: Path) -> str:
        """Unix-specific PDF export using LibreOffice/unoconv."""
        try:
            # Check if unoconv is installed
            if self._check_unoconv_installed():
                # Convert using unoconv
                subprocess.run([
                    'unoconv',
                    '-f', 'pdf',
                    '-o', str(output_path),
                    str(pptx_path)
                ], check=True)

                return str(output_path)

            # Fallback to soffice (LibreOffice) if unoconv is not available
            with tempfile.TemporaryDirectory() as temp_dir:
                subprocess.run([
                    'soffice',
                    '--headless',
                    '--convert-to', 'pdf',
                    '--outdir', temp_dir,
                    str(pptx_path)
                ], check=True)

                # Move the generated PDF to the desired location
                temp_pdf = Path(temp_dir) / f"{Path(pptx_path).stem}.pdf"
                if temp_pdf.exists():
                    temp_pdf.rename(output_path)
                    return str(output_path)
                else:
                    raise FileNotFoundError("PDF conversion failed")

        except Exception as e:
            logger.error(f"Unix PDF export failed: {str(e)}")
            raise

    def _check_unoconv_installed(self) -> bool:
        """Check if unoconv is available on the system."""
        try:
            subprocess.run(['unoconv', '--version'],
                           stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE)
            return True
        except FileNotFoundError:
            return False

    def _ensure_libreoffice_installed(self) -> bool:
        """Check if LibreOffice is available on the system."""
        try:
            subprocess.run(['soffice', '--version'],
                           stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE)
            return True
        except FileNotFoundError:
            return False

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
