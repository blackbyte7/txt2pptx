import json
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.documents import Document

from app.tools import (
    BulletPointInput,
    QualityCheckInput,
    PresentationStructureOutput,
    QualityAnalysisOutput,CodeQualityCheckInput, CodeQualityAnalysisOutput,
    TextElement, TableElement, create_bullet_points_tool, create_code_quality_check_tool, create_quality_check_tool
)
from tests.conftest import (
    mock_llm, mock_retriever, sample_raw_text_content,
    sample_detailed_presentation_json, sample_style, sample_template_name
)


@patch('app.tools.PydanticOutputParser')
@patch('app.tools.EnhancedRAG._format_docs')
def test_create_bullet_points_tool_success_no_rag(mock_format_docs, mock_Parser, mock_llm, sample_raw_text_content,
                                                  sample_style, sample_template_name,
                                                  sample_detailed_presentation_json):
    mock_parser_instance = MagicMock()
    mock_parser_instance.get_format_instructions.return_value = "mock_format_instructions"
    mock_output_object = PresentationStructureOutput(**sample_detailed_presentation_json)
    mock_parser_instance.invoke.return_value = mock_output_object
    mock_Parser.return_value = mock_parser_instance
    mock_format_docs.return_value = "Formatted Docs"

    mock_chain = MagicMock()
    mock_chain.invoke.return_value = mock_output_object

    mock_llm.invoke.return_value = MagicMock()

    input_data = BulletPointInput(
        content=sample_raw_text_content,
        style=sample_style,
        template_name=sample_template_name
    )

    with patch('langchain_core.runnables.base.RunnableSequence.invoke',
               return_value=mock_output_object) as mock_chain_invoke:
        result_json_str = create_bullet_points_tool(input_data, mock_llm, retriever=None)

    mock_chain_invoke.assert_called_once()
    call_args, call_kwargs = mock_chain_invoke.call_args
    assert "content" in call_args[0]
    assert call_args[0]["content"] == sample_raw_text_content

    expected_json = mock_output_object.json(indent=2)
    assert result_json_str == expected_json

    mock_format_docs.assert_not_called()


@patch('app.tools.PydanticOutputParser')
@patch('app.tools.EnhancedRAG._format_docs')
def test_create_bullet_points_tool_success_with_rag(mock_format_docs, mock_Parser, mock_llm, mock_retriever,
                                                    sample_raw_text_content, sample_style, sample_template_name,
                                                    sample_detailed_presentation_json):
    mock_parser_instance = MagicMock()
    mock_parser_instance.get_format_instructions.return_value = "mock_format_instructions"
    mock_output_object = PresentationStructureOutput(**sample_detailed_presentation_json)
    mock_parser_instance.invoke.return_value = mock_output_object
    mock_Parser.return_value = mock_parser_instance

    mock_retrieved_docs = [Document(page_content="doc1 content"), Document(page_content="doc2 content")]
    mock_retriever.invoke.return_value = mock_retrieved_docs
    mock_format_docs.return_value = "Formatted RAG Context"

    input_data = BulletPointInput(
        content=sample_raw_text_content,
        style=sample_style,
        template_name=sample_template_name
    )

    with patch('langchain_core.runnables.base.RunnableSequence.invoke',
               return_value=mock_output_object) as mock_chain_invoke:
        result_json_str = create_bullet_points_tool(input_data, mock_llm, retriever=mock_retriever)

    mock_chain_invoke.assert_called_once()
    mock_retriever.invoke.assert_called_once()
    mock_format_docs.assert_called_once_with(mock_retrieved_docs)

    expected_json = mock_output_object.json(indent=2)
    assert result_json_str == expected_json


@patch('app.tools.PydanticOutputParser')
def test_create_bullet_points_tool_llm_error(mock_Parser, mock_llm, sample_raw_text_content, sample_style,
                                             sample_template_name):
    mock_parser_instance = MagicMock()
    mock_parser_instance.get_format_instructions.return_value = "mock_format_instructions"
    mock_Parser.return_value = mock_parser_instance

    mock_chain_invoke = MagicMock(side_effect=ValueError("LLM communication failed"))

    input_data = BulletPointInput(
        content=sample_raw_text_content,
        style=sample_style,
        template_name=sample_template_name
    )

    with patch('langchain_core.runnables.base.RunnableSequence.invoke', mock_chain_invoke):
        with pytest.raises(ValueError, match="Failed to generate presentation structure: LLM communication failed"):
            create_bullet_points_tool(input_data, mock_llm, retriever=None)



@patch('app.tools.PydanticOutputParser')
def test_create_quality_check_tool_success(mock_Parser, mock_llm, sample_detailed_presentation_json):
    mock_parser_instance = MagicMock()
    mock_parser_instance.get_format_instructions.return_value = "mock_format_instructions"
    mock_analysis_output = QualityAnalysisOutput(
        overall_score=85,
        clarity_flow_feedback="Good flow, clear points.",
        engagement_feedback="Mix of elements should be engaging.",
        visual_suggestions=["Consider adding a diagram on slide 1."],
        timing_feedback="Seems appropriate for ~5 minutes.",
        strengths=["Clear structure", "Good use of table/chart"],
        areas_for_improvement=["Make conclusion slide more impactful."]
    )
    mock_parser_instance.invoke.return_value = mock_analysis_output
    mock_Parser.return_value = mock_parser_instance

    input_structure = sample_detailed_presentation_json
    input_data = QualityCheckInput(
        presentation_structure=input_structure,
        target_audience="Engineers",
        time_limit_minutes=10
    )

    with patch('langchain_core.runnables.base.RunnableSequence.invoke',
               return_value=mock_analysis_output) as mock_chain_invoke:
        result_json_str = create_quality_check_tool(input_data, mock_llm)

    mock_chain_invoke.assert_called_once()
    call_args, call_kwargs = mock_chain_invoke.call_args
    assert "structure" in call_args[0]
    assert json.loads(call_args[0]["structure"]) == input_structure

    expected_json = mock_analysis_output.json(indent=2)
    assert result_json_str == expected_json


@patch('app.tools.PydanticOutputParser')
def test_create_quality_check_tool_error(mock_Parser, mock_llm, sample_detailed_presentation_json):
    mock_parser_instance = MagicMock()
    mock_parser_instance.get_format_instructions.return_value = "mock_format_instructions"
    mock_Parser.return_value = mock_parser_instance

    mock_chain_invoke = MagicMock(side_effect=TypeError("Analysis module error"))
    input_data = QualityCheckInput(presentation_structure=sample_detailed_presentation_json)

    with patch('langchain_core.runnables.base.RunnableSequence.invoke', mock_chain_invoke):
        with pytest.raises(ValueError, match="Failed to perform quality analysis: Analysis module error"):
            create_quality_check_tool(input_data, mock_llm)


def test_quality_check_input_validation(mock_llm):
    """ Test that non-serializable structure raises error early """
    input_data = QualityCheckInput(presentation_structure={"data": lambda x: x})

    with pytest.raises(ValueError, match="Invalid presentation structure received for quality check"):
        create_quality_check_tool(input_data, mock_llm)


def test_bullet_point_input_schema():
    inp = BulletPointInput(content="text", style="Creative", template_name="creative")
    assert inp.content == "text"
    assert inp.style == "Creative"
    assert inp.max_slides == 15


def test_quality_check_input_schema():
    inp = QualityCheckInput(presentation_structure={"slides": []})
    assert inp.presentation_structure == {"slides": []}
    assert inp.target_audience == "General Audience"


def test_presentation_structure_output_schema():
    input_slides_data = [
        {
            "slide_number": 1,
            "title": "Slide 1",
            "slide_type": "content",
            "content_elements": [
                {
                    "element_type": "text",
                    "bullet_points": ["p1"]
                },
                {
                    "element_type": "table",
                    "headers": ["H1"],
                    "rows": [["R1C1"]]
                }
            ]
            # "design_elements": {"layout": "title_content"},
            # "speaker_notes": "Optional note"
        }
    ]

    out = PresentationStructureOutput(
        metadata={"presentation_style": "Test", "template_name": "test"},
        slides=input_slides_data
    )

    assert out.metadata.presentation_style == "Test"
    assert len(out.slides) == 1
    assert isinstance(out.slides[0].content_elements[0], TextElement)
    assert isinstance(out.slides[0].content_elements[1], TableElement)
    assert out.slides[0].content_elements[0].element_type == "text"
    assert out.slides[0].content_elements[1].element_type == "table"


def test_quality_analysis_output_schema():
    out = QualityAnalysisOutput(
        overall_score=50,
        clarity_flow_feedback="ok",
        engagement_feedback="needs work",
        strengths=["s1"],
        areas_for_improvement=["a1"]
    )
    assert out.overall_score == 50
    assert out.visual_suggestions is None


def test_code_quality_check_input_schema():
    inp = CodeQualityCheckInput(python_code="print('hello')")
    assert inp.python_code == "print('hello')"


def test_code_quality_analysis_output_schema():
    out_safe = CodeQualityAnalysisOutput(is_safe=True, assessment="Looks good.")
    assert out_safe.is_safe is True
    assert not out_safe.warnings

    out_unsafe = CodeQualityAnalysisOutput(is_safe=False, warnings=["Bad import"], assessment="Unsafe.")
    assert out_unsafe.is_safe is False
    assert out_unsafe.warnings == ["Bad import"]

    out_unsafe_no_warn = CodeQualityAnalysisOutput(is_safe=False, assessment="Unsafe.")
    assert out_unsafe_no_warn.warnings is not None
    assert len(out_unsafe_no_warn.warnings) == 1
    assert "Code marked as unsafe" in out_unsafe_no_warn.warnings[0]


@patch('app.tools.PydanticOutputParser')
def test_create_code_quality_check_tool_safe(mock_Parser, mock_llm, sample_safe_code):
    mock_parser_instance = MagicMock()
    mock_parser_instance.get_format_instructions.return_value = "mock_format_instructions"
    mock_analysis_output = CodeQualityAnalysisOutput(
        is_safe=True,
        warnings=[],
        assessment="Code appears safe and relevant for pptx generation."
    )
    mock_parser_instance.invoke.return_value = mock_analysis_output
    mock_Parser.return_value = mock_parser_instance

    input_data = CodeQualityCheckInput(python_code=sample_safe_code)

    with patch('langchain_core.runnables.base.RunnableSequence.invoke',
               return_value=mock_analysis_output) as mock_chain_invoke:
        result_json_str = create_code_quality_check_tool(input_data, mock_llm)

    mock_chain_invoke.assert_called_once()
    call_args, call_kwargs = mock_chain_invoke.call_args
    assert "python_code" in call_args[0]
    assert call_args[0]["python_code"] == sample_safe_code

    expected_json = mock_analysis_output.json(indent=2)
    assert result_json_str == expected_json


@patch('app.tools.PydanticOutputParser')
def test_create_code_quality_check_tool_unsafe(mock_Parser, mock_llm, sample_unsafe_code):
    mock_parser_instance = MagicMock()
    mock_parser_instance.get_format_instructions.return_value = "mock_format_instructions"
    mock_analysis_output = CodeQualityAnalysisOutput(
        is_safe=False,
        warnings=["Imports suspicious library 'requests'"],
        assessment="Code appears unsafe due to suspicious import."
    )
    mock_parser_instance.invoke.return_value = mock_analysis_output
    mock_Parser.return_value = mock_parser_instance

    input_data = CodeQualityCheckInput(python_code=sample_unsafe_code)

    with patch('langchain_core.runnables.base.RunnableSequence.invoke',
               return_value=mock_analysis_output) as mock_chain_invoke:
        result_json_str = create_code_quality_check_tool(input_data, mock_llm)

    expected_json = mock_analysis_output.json(indent=2)
    assert result_json_str == expected_json


@patch('app.tools.PydanticOutputParser')
def test_create_code_quality_check_tool_error(mock_Parser, mock_llm, sample_safe_code):
    mock_chain_invoke = MagicMock(side_effect=Exception("LLM error during quality check"))
    input_data = CodeQualityCheckInput(python_code=sample_safe_code)

    with patch('langchain_core.runnables.base.RunnableSequence.invoke', mock_chain_invoke):
        result_json_str = create_code_quality_check_tool(input_data, mock_llm)

    result_data = json.loads(result_json_str)
    assert result_data["is_safe"] is False
    assert "Failed to perform code quality analysis" in result_data["warnings"][0]