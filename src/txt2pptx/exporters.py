"""Export generated decks to PDF, PNG images and a simple HTML handout.

PDF conversion uses Microsoft PowerPoint (Windows, via COM) when available and LibreOffice (``soffice``)
everywhere else. Slide images are rendered from the PDF with pypdfium2 (no Poppler needed).
"""

from __future__ import annotations

import html
import logging
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

ExportFormat = Literal["pdf", "html", "images"]
EXPORT_FORMATS: tuple[ExportFormat, ...] = ("pdf", "html", "images")

_SOFFICE_CANDIDATES = (
    r"C:\Program Files\LibreOffice\program\soffice.exe",
    r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    "/Applications/LibreOffice.app/Contents/MacOS/soffice",
)
_COM_LOCK = threading.Lock()


class ExportError(RuntimeError):
    pass


@dataclass
class ExportResult:
    files: dict[str, list[Path]] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)

    def all_files(self) -> list[Path]:
        return [p for paths in self.files.values() for p in paths]


def find_soffice() -> str | None:
    for name in ("soffice", "libreoffice"):
        found = shutil.which(name)
        if found:
            return found
    return next((c for c in _SOFFICE_CANDIDATES if Path(c).exists()), None)


def powerpoint_available() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import win32com.client  # noqa: F401
    except ImportError:
        return False
    import winreg

    try:
        winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "PowerPoint.Application").Close()
        return True
    except OSError:
        return False


class PresentationExporter:
    def __init__(self, output_dir: Path, *, timeout: int = 180):
        self.output_dir = output_dir
        self.timeout = timeout
        self._soffice = find_soffice()
        self._powerpoint = powerpoint_available()

    @property
    def can_export_pdf(self) -> bool:
        return bool(self._soffice or self._powerpoint)

    def capabilities(self) -> dict[str, bool]:
        return {"pdf": self.can_export_pdf, "images": self.can_export_pdf, "html": True}

    def export(self, pptx_path: Path, formats: list[str] | tuple[str, ...]) -> ExportResult:
        result = ExportResult()
        if not pptx_path.is_file():
            raise FileNotFoundError(pptx_path)
        wanted = [f for f in EXPORT_FORMATS if f in set(formats)]
        unknown = set(formats) - set(EXPORT_FORMATS)
        for fmt in sorted(unknown):
            result.errors[fmt] = "unknown format"

        pdf_path: Path | None = None
        if "pdf" in wanted or "images" in wanted:
            try:
                pdf_path = self.to_pdf(pptx_path)
                if "pdf" in wanted:
                    result.files["pdf"] = [pdf_path]
            except Exception as exc:
                logger.warning("PDF export failed: %s", exc)
                for fmt in ("pdf", "images"):
                    if fmt in wanted:
                        result.errors[fmt] = str(exc)
        if "images" in wanted and pdf_path:
            try:
                result.files["images"] = self.to_images(pdf_path, pptx_path.stem)
            except Exception as exc:
                logger.warning("Image export failed: %s", exc)
                result.errors["images"] = str(exc)
            if "pdf" not in wanted:
                pdf_path.unlink(missing_ok=True)
        if "html" in wanted:
            try:
                result.files["html"] = [self.to_html(pptx_path)]
            except Exception as exc:
                logger.warning("HTML export failed: %s", exc)
                result.errors["html"] = str(exc)
        return result

    # --------------------------------------------------------------------------------------- PDF --
    def to_pdf(self, pptx_path: Path) -> Path:
        output = self.output_dir / f"{pptx_path.stem}.pdf"
        errors: list[str] = []
        if self._powerpoint:
            try:
                return self._pdf_via_powerpoint(pptx_path, output)
            except Exception as exc:
                errors.append(f"PowerPoint: {exc}")
        if self._soffice:
            try:
                return self._pdf_via_soffice(pptx_path, output)
            except Exception as exc:
                errors.append(f"LibreOffice: {exc}")
        if not errors:
            raise ExportError("PDF export needs LibreOffice (soffice) or Microsoft PowerPoint (Windows).")
        raise ExportError("; ".join(errors))

    def _pdf_via_soffice(self, pptx_path: Path, output: Path) -> Path:
        assert self._soffice
        with tempfile.TemporaryDirectory(prefix="txt2pptx-soffice-") as tmp:
            tmp_dir = Path(tmp)
            profile = (tmp_dir / "profile").as_uri()  # isolated profile => safe concurrent conversions
            cmd = [
                self._soffice,
                f"-env:UserInstallation={profile}",
                "--headless",
                "--norestore",
                "--convert-to",
                "pdf",
                "--outdir",
                str(tmp_dir),
                str(pptx_path.resolve()),
            ]
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=self.timeout, check=False)
            except subprocess.TimeoutExpired as exc:
                raise ExportError(f"soffice timed out after {self.timeout}s") from exc
            produced = tmp_dir / f"{pptx_path.stem}.pdf"
            if proc.returncode != 0 or not produced.exists():
                raise ExportError(f"soffice failed (exit {proc.returncode}): {proc.stderr.strip()[-500:]}")
            output.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(produced), output)
        return output

    def _pdf_via_powerpoint(self, pptx_path: Path, output: Path) -> Path:
        import pythoncom
        import win32com.client

        pp_save_as_pdf = 32
        with _COM_LOCK:
            pythoncom.CoInitialize()
            app = deck = None
            try:
                app = win32com.client.Dispatch("PowerPoint.Application")
                deck = app.Presentations.Open(str(pptx_path.resolve()), ReadOnly=True, WithWindow=False)
                output.parent.mkdir(parents=True, exist_ok=True)
                deck.SaveAs(str(output.resolve()), pp_save_as_pdf)
            finally:
                if deck is not None:
                    deck.Close()
                # Only quit PowerPoint if we didn't interrupt the user's own open presentations.
                if app is not None and app.Presentations.Count == 0:
                    app.Quit()
                pythoncom.CoUninitialize()
        if not output.exists():
            raise ExportError("PowerPoint did not produce a PDF")
        return output

    # ------------------------------------------------------------------------------------ images --
    def to_images(self, pdf_path: Path, stem: str, *, dpi: int = 150) -> list[Path]:
        import pypdfium2 as pdfium

        image_dir = self.output_dir / f"{stem}_images"
        image_dir.mkdir(parents=True, exist_ok=True)
        paths: list[Path] = []
        pdf = pdfium.PdfDocument(str(pdf_path))
        try:
            for i in range(len(pdf)):
                page = pdf[i]
                image = page.render(scale=dpi / 72).to_pil()
                target = image_dir / f"slide_{i + 1:03d}.png"
                image.save(target, "PNG", optimize=True)
                paths.append(target)
                page.close()
        finally:
            pdf.close()
        if not paths:
            raise ExportError("PDF has no pages")
        return paths

    # -------------------------------------------------------------------------------------- HTML --
    def to_html(self, pptx_path: Path) -> Path:
        from pptx import Presentation

        prs = Presentation(str(pptx_path))
        title = prs.core_properties.title or pptx_path.stem
        out: list[str] = [
            "<!DOCTYPE html>",
            '<html lang="en"><head><meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width, initial-scale=1">',
            f"<title>{html.escape(title)}</title>",
            "<style>",
            "body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;max-width:960px;"
            "margin:2rem auto;padding:0 1rem;color:#1f2937;line-height:1.5}",
            "section{border:1px solid #e5e7eb;border-radius:12px;padding:1.25rem 1.5rem;margin:1.25rem 0}",
            "h1{font-size:1.8rem}h2{margin-top:0}.n{color:#6b7280;font-size:.85rem}",
            "table{border-collapse:collapse;margin:.75rem 0}",
            "td,th{border:1px solid #d1d5db;padding:.35rem .6rem}",
            "th{background:#f3f4f6}.notes{color:#4b5563;font-style:italic;border-top:1px dashed #d1d5db;"
            "margin-top:1rem;padding-top:.5rem}@media print{section{break-inside:avoid}}",
            "</style></head><body>",
            f"<h1>{html.escape(title)}</h1>",
        ]
        for number, slide in enumerate(prs.slides, start=1):
            title_shape = slide.shapes.title
            out.append(f'<section><div class="n">Slide {number}</div>')
            if title_shape is not None and title_shape.text.strip():
                out.append(f"<h2>{html.escape(title_shape.text)}</h2>")
            for shape in slide.shapes:
                if shape == title_shape or shape.name == "Slide Number":
                    continue
                if shape.name == "Title" and title_shape is None and shape.has_text_frame:
                    out.append(f"<h2>{html.escape(shape.text_frame.text)}</h2>")
                    continue
                if getattr(shape, "has_table", False) and shape.has_table:
                    out.append("<table>")
                    for r, row in enumerate(shape.table.rows):
                        tag = "th" if r == 0 else "td"
                        cells = "".join(f"<{tag}>{html.escape(c.text)}</{tag}>" for c in row.cells)
                        out.append(f"<tr>{cells}</tr>")
                    out.append("</table>")
                elif getattr(shape, "has_chart", False) and shape.has_chart:
                    chart = shape.chart
                    name = chart.chart_title.text_frame.text if chart.has_title else "Chart"
                    out.append(f"<p><em>[Chart: {html.escape(name)}]</em></p>")
                elif shape.has_text_frame and shape.text_frame.text.strip():
                    items = [p for p in shape.text_frame.paragraphs if p.text.strip()]
                    out.append("<ul>")
                    out += [
                        f'<li style="margin-left:{p.level * 1.25}rem">{html.escape(p.text)}</li>'
                        for p in items
                    ]
                    out.append("</ul>")
            if slide.has_notes_slide:
                notes = slide.notes_slide.notes_text_frame.text.strip()
                if notes:
                    out.append(f'<div class="notes">{html.escape(notes)}</div>')
            out.append("</section>")
        out.append("</body></html>")
        target = self.output_dir / f"{pptx_path.stem}.html"
        target.write_text("\n".join(out), encoding="utf-8")
        return target


def cleanup_old_files(directory: Path, max_age_hours: float) -> int:
    """Delete generated files older than *max_age_hours* (0 disables). Returns number of files removed."""
    if max_age_hours <= 0 or not directory.is_dir():
        return 0
    cutoff = time.time() - max_age_hours * 3600
    removed = 0
    for path in sorted(directory.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        try:
            if path.is_file() and path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
            elif path.is_dir() and not any(path.iterdir()):
                path.rmdir()
        except OSError:
            continue
    if removed:
        logger.info("Removed %d export file(s) older than %.0fh from %s", removed, max_age_hours, directory)
    return removed
