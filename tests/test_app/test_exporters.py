import platform
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import app.exporters as exporters
from app.exporters import PresentationExporter


@pytest.fixture
def exporter(tmp_path):
    """ Provides a PresentationExporter instance with a temp output dir. """
    output_dir = tmp_path / "exports_test"
    with patch.object(PresentationExporter, "_check_dependencies") as mock_check:
        instance = PresentationExporter(output_dir=str(output_dir))
        mock_check.assert_called_once()
    return instance


@pytest.fixture
def pptx_file(tmp_path):
    """ Creates a dummy pptx file. """
    p = tmp_path / "my_presentation.pptx"
    p.touch()
    return p


@patch("app.exporters.subprocess.run")
def test_is_tool_installed(mock_subprocess_run):
    exporter_inst = PresentationExporter()

    # Tool Found
    mock_subprocess_run.return_value = MagicMock(returncode=0)
    assert exporter_inst._is_tool_installed("git") is True
    mock_subprocess_run.assert_called_with(
        ["git", "--version"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )

    # Tool Not Found
    mock_subprocess_run.side_effect = FileNotFoundError
    assert exporter_inst._is_tool_installed("nonexistenttool") is False

    # Tool errors on version check
    mock_subprocess_run.side_effect = subprocess.CalledProcessError(1, "cmd")
    assert exporter_inst._is_tool_installed("erroringtool") is False


@patch("app.exporters.PresentationExporter._export_to_pdf")
@patch("app.exporters.PresentationExporter._export_to_html")
@patch("app.exporters.PresentationExporter._export_to_images")
def test_export_presentation_all_formats(
    mock_export_images, mock_export_html, mock_export_pdf, exporter, pptx_file
):
    pdf_path = str(exporter.output_dir / f"{pptx_file.stem}.pdf")
    html_path = str(exporter.output_dir / f"{pptx_file.stem}.html")
    img_paths = [str(exporter.output_dir / f"{pptx_file.stem}_images/slide_001.png")]

    mock_export_pdf.return_value = pdf_path
    mock_export_html.return_value = html_path
    mock_export_images.return_value = img_paths

    results = exporter.export_presentation(pptx_file, formats=["pdf", "html", "images"])

    mock_export_pdf.assert_called_once_with(pptx_file, pptx_file.stem)
    mock_export_images.assert_called_once_with(pdf_path, pptx_file.stem)
    mock_export_html.assert_called_once_with(pptx_file, pptx_file.stem)

    assert results == {
        "original": str(pptx_file),
        "exports": {
            "pdf": pdf_path,
            "html": html_path,
            "images": img_paths,
        },
    }


@patch("app.exporters.PresentationExporter._export_to_pdf")
@patch("app.exporters.PresentationExporter._export_to_images")
def test_export_presentation_images_needs_pdf(
    mock_export_images, mock_export_pdf, exporter, pptx_file
):
    temp_pdf_name_part = "_temp_for_images"
    temp_pdf_path = str(exporter.output_dir / f"{pptx_file.stem}{temp_pdf_name_part}.pdf")
    img_paths = [str(exporter.output_dir / f"{pptx_file.stem}_images/slide_001.png")]

    mock_export_pdf.return_value = temp_pdf_path
    mock_export_images.return_value = img_paths

    with patch("app.exporters.Path.unlink") as mock_unlink:
        results = exporter.export_presentation(pptx_file, formats=["images"])
        mock_export_pdf.assert_called_once_with(
            pptx_file, f"{pptx_file.stem}{temp_pdf_name_part}"
        )
        mock_export_images.assert_called_once_with(temp_pdf_path, pptx_file.stem)
        mock_unlink.assert_called_with(missing_ok=True)

    assert results["exports"].get("images") == img_paths
    assert "pdf" not in results["exports"]


def test_export_presentation_input_not_found(exporter):
    results = exporter.export_presentation("non_existent.pptx")
    assert "error" in results
    assert "not found" in results["error"]


@patch("app.exporters.PresentationExporter._export_to_pdf", side_effect=Exception("PDF Boom!"))
def test_export_presentation_handles_export_error(mock_export_pdf, exporter, pptx_file):
    results = exporter.export_presentation(pptx_file, formats=["pdf", "html"])

    assert "pdf" in results["exports"]
    assert "Export failed: PDF Boom!" in results["exports"]["pdf"]


@patch("app.exporters.HAS_WIN_COM", True)
@patch("app.exporters.platform.system", return_value="Windows")
@patch("app.exporters.PresentationExporter._export_to_pdf_windows")
@patch("app.exporters.PresentationExporter._check_dependencies")
def test_export_to_pdf_calls_windows(
    mock_check_deps, mock_export_win, mock_system, pptx_file, tmp_path
):
    output_dir = tmp_path / "exports_test"
    exporter_instance = PresentationExporter(output_dir=str(output_dir))
    exporter_instance._export_to_pdf(pptx_file, pptx_file.stem)
    mock_export_win.assert_called_once_with(
        pptx_file, exporter_instance.output_dir / f"{pptx_file.stem}.pdf"
    )
    mock_check_deps.assert_called_once()


@patch("app.exporters.HAS_WIN_COM", False)
@patch("app.exporters.platform.system", return_value="Windows")
@patch("app.exporters.PresentationExporter._export_to_pdf_windows")
@patch("app.exporters.PresentationExporter._export_to_pdf_unix")
@patch("app.exporters.PresentationExporter._check_dependencies")
def test_export_to_pdf_skips_windows_if_no_com(
    mock_check_deps, mock_export_unix, mock_export_win, mock_system, pptx_file, tmp_path
):
    output_dir = tmp_path / "exports_test"
    exporter_instance = PresentationExporter(output_dir=str(output_dir))
    with patch("app.exporters.logger.warning") as mock_log_warn:
        result = exporter_instance._export_to_pdf(pptx_file, pptx_file.stem)
        mock_log_warn.assert_any_call(
            "PDF export skipped: Unsupported platform or missing dependencies."
        )
        mock_export_win.assert_not_called()
        mock_export_unix.assert_not_called()
        assert result is None


@patch("app.exporters.platform.system", return_value="Linux")
@patch("app.exporters.PresentationExporter._export_to_pdf_unix")
def test_export_to_pdf_calls_unix(mock_export_unix, mock_system, exporter, pptx_file):
    exporter._export_to_pdf(pptx_file, pptx_file.stem)
    mock_export_unix.assert_called_once()


@pytest.mark.skipif(platform.system() != "Windows", reason="COM tests only run on Windows")
def test_export_to_pdf_windows_comtypes_success(exporter, pptx_file, monkeypatch):
    abs_pptx_path = str(pptx_file.absolute())
    output_path = exporter.output_dir / f"{pptx_file.stem}.pdf"
    abs_output_path = str(output_path.absolute())

    mock_comtypes = MagicMock(name="mock_comtypes_module")
    mock_win32com = MagicMock(name="mock_win32com_module")
    mock_powerpoint_app = MagicMock(name="mock_powerpoint_app")
    mock_deck = MagicMock(name="mock_deck")

    mock_comtypes.client.CreateObject.return_value = mock_powerpoint_app
    mock_powerpoint_app.Presentations.Open.return_value = mock_deck

    monkeypatch.setattr(exporters, "HAS_WIN_COM", True)
    monkeypatch.setattr(exporters, "comtypes", mock_comtypes, raising=False)
    monkeypatch.setattr(exporters, "win32com", mock_win32com, raising=False)

    result = exporter._export_to_pdf_windows(pptx_file, output_path)

    assert result == str(output_path)
    mock_comtypes.client.CreateObject.assert_called_once_with("Powerpoint.Application")
    mock_powerpoint_app.Presentations.Open.assert_called_once_with(
        abs_pptx_path, WithWindow=False
    )
    mock_deck.SaveAs.assert_called_once_with(abs_output_path, 32)
    mock_deck.Close.assert_called_once()
    mock_powerpoint_app.Quit.assert_called_once()
    mock_win32com.client.Dispatch.assert_not_called()


@pytest.mark.skipif(platform.system() != "Windows", reason="COM tests only run on Windows")
def test_export_to_pdf_windows_win32com_fallback(exporter, pptx_file, monkeypatch):
    abs_pptx_path = str(pptx_file.absolute())
    output_path = exporter.output_dir / f"{pptx_file.stem}.pdf"
    abs_output_path = str(output_path.absolute())

    mock_comtypes = MagicMock(name="mock_comtypes_module")
    mock_win32com = MagicMock(name="mock_win32com_module")
    mock_powerpoint_app_win32 = MagicMock(name="mock_powerpoint_app_win32")
    mock_deck_win32 = MagicMock(name="mock_deck_win32")

    mock_comtypes.client.CreateObject.side_effect = Exception("Comtypes failed")
    mock_win32com.client.Dispatch.return_value = mock_powerpoint_app_win32
    mock_powerpoint_app_win32.Presentations.Open.return_value = mock_deck_win32

    monkeypatch.setattr(exporters, "HAS_WIN_COM", True)
    monkeypatch.setattr(exporters, "comtypes", mock_comtypes, raising=False)
    monkeypatch.setattr(exporters, "win32com", mock_win32com, raising=False)

    result = exporter._export_to_pdf_windows(pptx_file, output_path)

    assert result == str(output_path)
    mock_comtypes.client.CreateObject.assert_called_once()
    mock_win32com.client.Dispatch.assert_called_once_with("Powerpoint.Application")
    mock_powerpoint_app_win32.Presentations.Open.assert_called_once_with(
        abs_pptx_path, WithWindow=False
    )
    mock_deck_win32.SaveAs.assert_called_once_with(abs_output_path, 32)
    mock_deck_win32.Close.assert_called_once()
    mock_powerpoint_app_win32.Quit.assert_called_once()


@pytest.mark.skipif(platform.system() != "Windows", reason="COM tests only run on Windows")
def test_export_to_pdf_windows_both_fail(exporter, pptx_file, monkeypatch):
    output_path = exporter.output_dir / f"{pptx_file.stem}.pdf"
    mock_comtypes = MagicMock(name="mock_comtypes_module")
    mock_win32com = MagicMock(name="mock_win32com_module")
    mock_comtypes.client.CreateObject.side_effect = Exception("Comtypes create failed")
    mock_win32com.client.Dispatch.side_effect = Exception("win32com dispatch failed")

    monkeypatch.setattr(exporters, "HAS_WIN_COM", True)
    monkeypatch.setattr(exporters, "comtypes", mock_comtypes, raising=False)
    monkeypatch.setattr(exporters, "win32com", mock_win32com, raising=False)

    result = exporter._export_to_pdf_windows(pptx_file, output_path)
    assert result is None
    mock_comtypes.client.CreateObject.assert_called_once()
    mock_win32com.client.Dispatch.assert_called_once()


@patch("app.exporters.subprocess.run")
@patch("app.exporters.PresentationExporter._is_tool_installed")
@patch("app.exporters.platform.system", return_value="Linux")
def test_export_to_pdf_unix_unoconv_success(
    mock_system, mock_is_tool_installed, mock_subprocess_run, exporter, pptx_file
):
    mock_is_tool_installed.side_effect = lambda tool: tool == "unoconv"
    output_path = exporter.output_dir / f"{pptx_file.stem}.pdf"
    abs_pptx_path = str(pptx_file.absolute())

    mock_subprocess_run.return_value = MagicMock(returncode=0)
    with patch.object(Path, "exists", return_value=True):
        result = exporter._export_to_pdf_unix(pptx_file, output_path)

    assert result == str(output_path)
    expected_cmd = ["unoconv", "-f", "pdf", "-o", str(output_path), abs_pptx_path]
    mock_subprocess_run.assert_called_once_with(
        expected_cmd, check=True, capture_output=True, text=True, timeout=120
    )


@patch("app.exporters.subprocess.run")
@patch("app.exporters.PresentationExporter._is_tool_installed")
@patch("app.exporters.platform.system", return_value="Darwin")
def test_export_to_pdf_unix_soffice_fallback(
    mock_system, mock_is_tool_installed, mock_subprocess_run, exporter, pptx_file
):
    mock_is_tool_installed.side_effect = lambda tool: tool == "soffice"
    output_path = exporter.output_dir / f"{pptx_file.stem}.pdf"
    abs_pptx_path = str(pptx_file.absolute())

    mock_subprocess_run.return_value = MagicMock(returncode=0)

    with patch("app.exporters.tempfile.TemporaryDirectory") as mock_tempdir:
        temp_dir_path = exporter.output_dir / "temp"
        mock_tempdir.return_value.__enter__.return_value = str(temp_dir_path)

        with patch.object(Path, "exists", return_value=True), patch.object(
            Path, "rename"
        ) as mock_rename:
            result = exporter._export_to_pdf_unix(pptx_file, output_path)

            assert result == str(output_path)
            expected_cmd = [
                "soffice",
                "--headless",
                "--convert-to",
                "pdf",
                "--outdir",
                str(temp_dir_path),
                abs_pptx_path,
            ]
            mock_subprocess_run.assert_called_once_with(
                expected_cmd, check=True, capture_output=True, text=True, timeout=120
            )
            mock_rename.assert_called_once_with(output_path)


@patch(
    "app.exporters.subprocess.run",
    side_effect=subprocess.CalledProcessError(1, "cmd", stderr="Conversion failed"),
)
@patch("app.exporters.PresentationExporter._is_tool_installed", return_value=True)
@patch("app.exporters.platform.system", return_value="Linux")
def test_export_to_pdf_unix_subprocess_error(
    mock_system, mock_is_tool_installed, mock_subprocess_run, exporter, pptx_file
):
    output_path = exporter.output_dir / f"{pptx_file.stem}.pdf"
    assert exporter._export_to_pdf_unix(pptx_file, output_path) is None


@patch("app.exporters.PresentationExporter._is_tool_installed", return_value=False)
@patch("app.exporters.platform.system", return_value="Linux")
def test_export_to_pdf_unix_no_tools(mock_system, mock_is_tool_installed, exporter, pptx_file):
    output_path = exporter.output_dir / f"{pptx_file.stem}.pdf"
    assert exporter._export_to_pdf_unix(pptx_file, output_path) is None


@patch("app.exporters.pptx.Presentation")
def test_export_to_html_escapes_xss_and_deduplicates_title(
    mock_PptxPresentation, exporter, pptx_file, mock_pptx_slide
):
    output_path = exporter.output_dir / f"{pptx_file.stem}.html"

    mock_pres = MagicMock()

    mock_slide = mock_pptx_slide
    mock_slide.shapes.title.text = "Slide 1 <script>alert(1)</script>"

    shape1 = MagicMock(
        has_table=False,
        has_text_frame=True,
        text_frame=MagicMock(
            paragraphs=[
                MagicMock(text="Bullet 1 & <bold>", level=0),
                MagicMock(text="Sub-bullet 1.1", level=1),
            ]
        ),
    )
    shape2 = MagicMock(has_table=False, has_text_frame=False)

    mock_slide.shapes.__iter__.return_value = iter([mock_slide.shapes.title, shape1, shape2])
    mock_pres.slides = [mock_slide]
    mock_PptxPresentation.return_value = mock_pres

    result = exporter._export_to_html(pptx_file, pptx_file.stem)

    assert result == str(output_path)
    html_content = output_path.read_text(encoding="utf-8")
    assert "<title>my_presentation</title>" in html_content
    assert "<h3>Slide 1 &lt;script&gt;alert(1)&lt;/script&gt;</h3>" in html_content
    assert "<script>" not in html_content
    assert "<p>Bullet 1 &amp; &lt;bold&gt;</p>" in html_content
    assert "<p>&nbsp;&nbsp;&nbsp;&nbsp;- Sub-bullet 1.1</p>" in html_content


@patch("app.exporters.pdf2image.convert_from_path")
def test_export_to_images_success(mock_convert_from_path, exporter, tmp_path):
    pdf_path = tmp_path / "test.pdf"
    pdf_path.touch()
    output_name = "test_output"
    image_dir = exporter.output_dir / f"{output_name}_images"

    mock_image1 = MagicMock()
    mock_image2 = MagicMock()
    mock_convert_from_path.return_value = [mock_image1, mock_image2]

    result = exporter._export_to_images(pdf_path, output_name)

    mock_convert_from_path.assert_called_once_with(pdf_path, dpi=150)
    expected_paths = [
        str(image_dir / "slide_001.png"),
        str(image_dir / "slide_002.png"),
    ]
    assert result == expected_paths


@patch(
    "app.exporters.pdf2image.convert_from_path",
    side_effect=ImportError("pdf2image not installed"),
)
def test_export_to_images_import_error(mock_convert, exporter, tmp_path):
    pdf_path = tmp_path / "test.pdf"
    assert exporter._export_to_images(pdf_path, "test_output") is None


@patch("app.exporters.pdf2image.convert_from_path")
def test_export_to_images_save_error(mock_convert_from_path, exporter, tmp_path):
    pdf_path = tmp_path / "test.pdf"
    mock_image1 = MagicMock()
    mock_image1.save.side_effect = OSError("Cannot write image")
    mock_convert_from_path.return_value = [mock_image1]

    assert exporter._export_to_images(pdf_path, "test_output") is None