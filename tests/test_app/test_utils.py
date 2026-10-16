from unittest.mock import MagicMock, patch

import pytest
from langchain_core.documents import Document

from app.utils import (
    ALLOWED_EXTENSIONS,
    generate_presentation,
    load_supported_documents,
    validate_input_file_path,
)


@pytest.fixture(params=list(ALLOWED_EXTENSIONS))
def supported_file_type(request, tmp_path):
    """Provides paths for different supported dummy files."""
    ext = request.param
    p = tmp_path / f"testfile{ext}"
    p.touch()
    return p, ext


@patch("app.utils.PyPDFLoader")
@patch("app.utils.TextLoader")
@patch("app.utils.UnstructuredFileLoader")
def test_load_supported_documents_chooses_correct_loader(
    mock_UnstructuredLoader, mock_TextLoader, mock_PyPDFLoader, supported_file_type
):
    file_path, ext = supported_file_type
    mock_loader_instance = MagicMock()
    mock_loader_instance.load.return_value = [Document(page_content="Loaded content")]

    if ext == ".pdf":
        mock_PyPDFLoader.return_value = mock_loader_instance
    elif ext in [".txt", ".md"]:
        mock_TextLoader.return_value = mock_loader_instance
        mock_loader_instance.load.side_effect = None
        mock_loader_instance.load.return_value = [Document(page_content="Loaded content")]
        mock_TextLoader.reset_mock()
    elif ext in [".docx", ".pptx", ".html", ".htm"]:
        mock_UnstructuredLoader.return_value = mock_loader_instance

    documents = load_supported_documents(file_path)

    assert documents == [Document(page_content="Loaded content")]

    if ext == ".pdf":
        mock_PyPDFLoader.assert_called_once_with(str(file_path))
        mock_TextLoader.assert_not_called()
        mock_UnstructuredLoader.assert_not_called()
    elif ext in [".txt", ".md"]:
        assert mock_TextLoader.call_count >= 1
        assert mock_TextLoader.call_args_list[0][1]["encoding"] == "utf-8"
        mock_PyPDFLoader.assert_not_called()
        mock_UnstructuredLoader.assert_not_called()
    elif ext in [".docx", ".pptx", ".html", ".htm"]:
        mock_UnstructuredLoader.assert_called_once_with(str(file_path), mode="elements")
        mock_PyPDFLoader.assert_not_called()
        mock_TextLoader.assert_not_called()


def test_load_supported_documents_file_not_found(tmp_path):
    non_existent_file = tmp_path / "not_a_real_file.txt"
    with pytest.raises(FileNotFoundError):
        load_supported_documents(non_existent_file)


def test_load_supported_documents_unsupported_extension(tmp_path):
    unsupported_file = tmp_path / "test.unsupported"
    unsupported_file.touch()
    with pytest.raises(ValueError, match="Unsupported file format: .unsupported"):
        load_supported_documents(unsupported_file)


@patch("app.utils.TextLoader")
def test_load_supported_documents_text_encoding_fallback(mock_TextLoader, tmp_path):
    file_path = tmp_path / "encoding_test.txt"
    file_path.touch()

    mock_utf8_loader = MagicMock(name="UTF8LoaderInstance")
    mock_utf8_loader.load.side_effect = UnicodeDecodeError("utf8", b"", 0, 1, "reason")

    mock_latin1_loader = MagicMock(name="Latin1LoaderInstance")
    mock_latin1_loader.load.return_value = [Document(page_content="Latin-1 content")]

    def text_loader_side_effect(*args, **kwargs):
        encoding = kwargs.get("encoding")
        if encoding == "utf-8":
            return mock_utf8_loader
        elif encoding == "latin-1":
            return mock_latin1_loader
        return MagicMock()

    mock_TextLoader.side_effect = text_loader_side_effect

    documents = load_supported_documents(file_path)

    assert mock_utf8_loader.load.call_count == 1
    assert mock_latin1_loader.load.call_count == 1
    assert documents == [Document(page_content="Latin-1 content")]


@patch("app.utils.PyPDFLoader")
def test_load_supported_documents_loader_import_error(mock_PyPDFLoader, tmp_path):
    file_path = tmp_path / "test.pdf"
    file_path.touch()
    mock_PyPDFLoader.side_effect = ImportError("Missing pypdf library")

    with pytest.raises(ImportError, match="Missing library required for .pdf files"):
        load_supported_documents(file_path)


@patch("app.utils.PyPDFLoader")
def test_load_supported_documents_empty_content(mock_PyPDFLoader, tmp_path):
    file_path = tmp_path / "empty.pdf"
    file_path.touch()
    mock_loader_instance = MagicMock()
    mock_loader_instance.load.return_value = [
        Document(page_content=" "),
        Document(page_content="\n\t"),
    ]
    mock_PyPDFLoader.return_value = mock_loader_instance

    documents = load_supported_documents(file_path)
    assert documents == []


@patch("app.utils.PPTXGenerator")
@patch("app.utils.Path.mkdir")
@patch("app.utils.time.strftime")
def test_generate_presentation_success(
    mock_strftime,
    mock_mkdir,
    mock_PPTXGenerator,
    tmp_path,
    sample_detailed_presentation_json,
):
    output_dir = tmp_path / "exports"
    base_name = "test_pres"
    timestamp = "20230101-120000"
    expected_filename = f"{base_name}_{timestamp}.pptx"
    expected_path = output_dir / expected_filename

    mock_strftime.return_value = timestamp

    mock_generator_instance = MagicMock()
    mock_presentation = MagicMock()
    mock_PPTXGenerator.return_value = mock_generator_instance
    mock_generator_instance.create_presentation_from_json.return_value = mock_presentation

    result_path = generate_presentation(
        presentation_structure_json=sample_detailed_presentation_json,
        output_filename_base=base_name,
        output_dir=str(output_dir),
    )

    assert result_path == str(expected_path)
    mock_PPTXGenerator.assert_called_once_with(
        template=sample_detailed_presentation_json["template_info"]
    )
    mock_generator_instance.create_presentation_from_json.assert_called_once_with(
        sample_detailed_presentation_json
    )
    mock_mkdir.assert_called_once_with(parents=True, exist_ok=True)
    mock_presentation.save.assert_called_once_with(str(expected_path))


@patch("app.utils.PPTXGenerator")
def test_generate_presentation_generator_fails(
    mock_PPTXGenerator, sample_detailed_presentation_json, tmp_path
):
    mock_generator_instance = MagicMock()
    mock_PPTXGenerator.return_value = mock_generator_instance
    mock_generator_instance.create_presentation_from_json.return_value = None

    result_path = generate_presentation(sample_detailed_presentation_json, output_dir=tmp_path)
    assert result_path is None


@patch("app.utils.PPTXGenerator")
def test_generate_presentation_save_fails(
    mock_PPTXGenerator, sample_detailed_presentation_json, tmp_path
):
    mock_generator_instance = MagicMock()
    mock_presentation = MagicMock()
    mock_PPTXGenerator.return_value = mock_generator_instance
    mock_generator_instance.create_presentation_from_json.return_value = mock_presentation
    mock_presentation.save.side_effect = OSError("Disk full")

    result_path = generate_presentation(sample_detailed_presentation_json, output_dir=tmp_path)
    assert result_path is None
    mock_presentation.save.assert_called_once()


@pytest.mark.parametrize(
    "path_str, expected",
    [
        ("document.pdf", True),
        ("report.docx", True),
        ("notes.txt", True),
        ("data.pptx", True),
        ("page.html", True),
        ("info.md", True),
        ("/path/to/archive.zip", False),
        ("image.jpg", False),
        ("", False),
        (None, False),
        ("no_extension", False),
        (".gitignore", False),
    ],
)
def test_validate_input_file_path(path_str, expected):
    assert validate_input_file_path(path_str) is expected


def test_validate_input_file_path_with_path_object(tmp_path):
    p_valid = tmp_path / "test.pdf"
    p_invalid = tmp_path / "test.xyz"
    assert validate_input_file_path(p_valid) is True
    assert validate_input_file_path(p_invalid) is False
