import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.agents import AgentAction
from langchain_core.documents import Document
from langchain_core.tools import BaseTool

from app.agents import (
    PresentationAgent,
    _execute_code_safely,
    create_agent,
    get_llm_instance,
    run_bullet_points_tool_with_llm,
    run_code_quality_check_tool_with_llm,
    run_quality_check_tool_with_llm,
)
from app.tools import BulletPointInput, CodeQualityCheckInput, QualityCheckInput


@patch("app.agents.ChatOpenAI")
def test_get_llm_instance_openai(mock_ChatOpenAI, mock_llm):
    mock_ChatOpenAI.return_value = mock_llm
    api_key = "sk-testkey"
    llm = get_llm_instance("openai", api_key)
    mock_ChatOpenAI.assert_called_once_with(
        api_key=api_key,
        model="gpt-4-turbo",
        temperature=0.1,
        max_tokens=4096,
    )
    assert llm is mock_llm


@patch("app.agents.ChatAnthropic")
def test_get_llm_instance_anthropic(mock_ChatAnthropic, mock_llm):
    mock_ChatAnthropic.return_value = mock_llm
    api_key = "ak-testkey"
    llm = get_llm_instance("anthropic", api_key)
    mock_ChatAnthropic.assert_called_once_with(
        api_key=api_key,
        model_name="claude-3-5-sonnet-20240620",
        temperature=0.1,
        max_tokens=4096,
    )
    assert llm is mock_llm


def test_get_llm_instance_unsupported():
    with pytest.raises(ValueError, match="Unsupported LLM provider: unsupported"):
        get_llm_instance("unsupported", "key")


@patch("app.agents.create_bullet_points_tool")
def test_run_bullet_points_tool_with_llm_success(mock_core_tool_func, mock_llm, mock_retriever):
    tool_input_dict = {
        "content": "Test content",
        "style": "Test Style",
        "template_name": "test_template",
    }
    expected_output = '{"slides": []}'
    mock_core_tool_func.return_value = expected_output

    result = run_bullet_points_tool_with_llm(tool_input_dict, mock_llm, mock_retriever)

    mock_core_tool_func.assert_called_once()
    call_args, _ = mock_core_tool_func.call_args
    assert isinstance(call_args[0], BulletPointInput)
    assert call_args[0].content == "Test content"
    assert call_args[1] is mock_llm
    assert call_args[2] is mock_retriever

    assert result == expected_output


@patch("app.agents.create_bullet_points_tool")
def test_run_bullet_points_tool_with_llm_error(mock_core_tool_func, mock_llm, mock_retriever):
    tool_input_dict = {
        "content": "Test content",
        "style": "Test Style",
        "template_name": "test_template",
    }
    mock_core_tool_func.side_effect = ValueError("Core tool failed")

    result = run_bullet_points_tool_with_llm(tool_input_dict, mock_llm, mock_retriever)

    assert "Error executing Bullet_Points_Generator:" in result
    assert "Core tool failed" in result


@patch("app.agents.create_quality_check_tool")
def test_run_quality_check_tool_with_llm_success(mock_core_tool_func, mock_llm):
    tool_input_dict = {
        "presentation_structure": {"slides": [{"title": "S1"}]},
        "target_audience": "Experts",
    }
    expected_output = '{"score": 90}'
    mock_core_tool_func.return_value = expected_output

    result = run_quality_check_tool_with_llm(tool_input_dict, mock_llm)

    mock_core_tool_func.assert_called_once()
    call_args, _ = mock_core_tool_func.call_args
    assert isinstance(call_args[0], QualityCheckInput)
    assert call_args[0].presentation_structure == {"slides": [{"title": "S1"}]}
    assert call_args[0].target_audience == "Experts"
    assert call_args[1] is mock_llm

    assert result == expected_output


@patch("app.agents.create_quality_check_tool")
def test_run_quality_check_tool_with_llm_error(mock_core_tool_func, mock_llm):
    tool_input_dict = {"presentation_structure": {"slides": []}}
    mock_core_tool_func.side_effect = TypeError("Analysis failed")

    result = run_quality_check_tool_with_llm(tool_input_dict, mock_llm)

    assert "Error executing Presentation_Quality_Checker:" in result
    assert "Analysis failed" in result


@patch("app.agents.get_llm_instance")
@patch("app.agents.EnhancedRAG")
@patch("app.agents.BaseTool")
@patch("app.agents.PresentationAgent")
def test_create_agent_success_no_rag(
    mock_PresentationAgent, mock_BaseTool, mock_EnhancedRAG, mock_get_llm, mock_llm
):
    mock_get_llm.return_value = mock_llm

    create_agent("openai", "key", loaded_docs=None)

    mock_get_llm.assert_called_once_with("openai", "key")
    mock_EnhancedRAG.assert_not_called()

    assert mock_BaseTool.from_function.call_count == 4
    mock_PresentationAgent.assert_called_once()
    _, init_kwargs = mock_PresentationAgent.call_args
    assert init_kwargs["llm"] is mock_llm
    assert len(init_kwargs["tools"]) == 4
    assert init_kwargs["retriever"] is None


@patch("app.agents.get_llm_instance")
@patch("app.agents.EnhancedRAG")
@patch("app.agents.BaseTool")
@patch("app.agents.PresentationAgent")
def test_create_agent_success_with_rag(
    mock_PresentationAgent,
    mock_BaseTool,
    mock_EnhancedRAG,
    mock_get_llm,
    mock_llm,
    mock_retriever,
):
    mock_get_llm.return_value = mock_llm
    mock_rag_instance = mock_EnhancedRAG.return_value
    mock_rag_instance.get_retriever.return_value = mock_retriever
    sample_docs = [Document(page_content="doc1")]

    create_agent("openai", "sk-key", loaded_docs=sample_docs)

    mock_get_llm.assert_called_once_with("openai", "sk-key")
    mock_EnhancedRAG.assert_called_once_with(
        docs=sample_docs, cache_name="pptx_docs_context", openai_api_key="sk-key"
    )
    mock_rag_instance.get_retriever.assert_called_once_with(k=5)

    mock_PresentationAgent.assert_called_once()
    _, init_kwargs = mock_PresentationAgent.call_args
    assert init_kwargs["retriever"] is mock_retriever


@patch("app.agents.get_llm_instance")
@patch("app.agents.EnhancedRAG", side_effect=Exception("RAG Init Failed"))
@patch("app.agents.BaseTool")
@patch("app.agents.PresentationAgent")
def test_create_agent_rag_init_failure(
    mock_PresentationAgent, mock_BaseTool, mock_EnhancedRAG, mock_get_llm, mock_llm
):
    mock_get_llm.return_value = mock_llm
    sample_docs = [Document(page_content="doc1")]

    create_agent("openai", "key", loaded_docs=sample_docs)

    mock_PresentationAgent.assert_called_once()
    _, init_kwargs = mock_PresentationAgent.call_args
    assert init_kwargs["retriever"] is None


@patch("app.agents.create_bullet_points_tool")
def test_presentation_agent_deterministic_json_path(
    mock_bp_tool,
    mock_llm,
    mock_retriever,
    sample_detailed_presentation_json,
    sample_template_data,
    sample_raw_text_content,
    sample_style,
    sample_template_name,
):
    raw_json_output_str = json.dumps(sample_detailed_presentation_json)
    mock_bp_tool.return_value = raw_json_output_str

    agent = PresentationAgent(llm=mock_llm, tools=[], retriever=mock_retriever)
    result_dict = agent.run(
        user_input=sample_raw_text_content,
        style=sample_style,
        template_name=sample_template_name,
        template_data=sample_template_data,
        generation_method="json",
    )

    mock_bp_tool.assert_called_once()
    assert result_dict == {"type": "json", "output": raw_json_output_str}


@patch("app.agents._execute_code_safely")
@patch("app.agents.create_code_quality_check_tool")
@patch("app.agents.create_code_generation_tool")
def test_presentation_agent_deterministic_code_path_success(
    mock_code_gen,
    mock_qc,
    mock_exec_safe,
    mock_llm,
    sample_template_data,
    sample_raw_text_content,
    sample_style,
    sample_template_name,
    mock_code_gen_output,
    mock_safe_quality_check_output,
):
    code_gen_data = json.loads(mock_code_gen_output)
    expected_filename = code_gen_data["output_filename"]
    Path(expected_filename).touch()

    mock_code_gen.return_value = mock_code_gen_output
    mock_qc.return_value = mock_safe_quality_check_output
    mock_exec_safe.return_value = "Code execution finished."

    agent = PresentationAgent(llm=mock_llm, tools=[])
    result_dict = agent.run(
        user_input=sample_raw_text_content,
        style=sample_style,
        template_name=sample_template_name,
        template_data=sample_template_data,
        generation_method="code",
    )

    assert result_dict["type"] == "code_execution"
    assert Path(result_dict["generated_filename"]) == Path(expected_filename).absolute()


def test_execute_code_safely_blocks_unsafe_ast():
    unsafe_code = "import subprocess\nsubprocess.run(['ls'])"
    with pytest.raises(PermissionError, match="Blocked execution due to AST security violations"):
        _execute_code_safely(unsafe_code)


def test_execute_code_safely_runs_valid_code():
    safe_code = "import math\nprint(int(math.sqrt(16)))"
    output = _execute_code_safely(safe_code)
    assert "4" in output


def test_presentation_agent_run_json_cleaning(mock_llm, sample_template_data):
    agent = PresentationAgent(llm=mock_llm, tools=[])

    core_json_str = json.dumps({"metadata": {}, "slides": [{"title": "Cleaned"}]})
    raw_output_with_fences = f"```json\n{core_json_str}\n```"

    mock_runnable_instance = MagicMock(name="MockAgentRunnable")
    mock_runnable_instance.invoke.return_value = {"output": raw_output_with_fences}

    with patch.object(agent, "agent_runnable", mock_runnable_instance):
        result_dict = agent.run(
            user_input="content",
            style="style",
            template_name="template",
            template_data=sample_template_data,
            generation_method="json",
        )

    assert result_dict == {"type": "json", "output": core_json_str}


def test_presentation_agent_run_bad_json_output(mock_llm, sample_template_data):
    agent = PresentationAgent(llm=mock_llm, tools=[])
    mock_runnable_instance = MagicMock(name="MockAgentRunnable")
    mock_runnable_instance.invoke.return_value = {"output": '{"slides": [ BAD JSON ]}'}

    with patch.object(agent, "agent_runnable", mock_runnable_instance):
        result_dict = agent.run(
            user_input="content",
            style="style",
            template_name="template",
            template_data=sample_template_data,
            generation_method="json",
        )
        assert result_dict["type"] == "error"
        assert "Agent did not return valid JSON structure" in result_dict["output"]


def test_presentation_agent_run_invalid_structure_output(mock_llm, sample_template_data):
    agent = PresentationAgent(llm=mock_llm, tools=[])
    mock_runnable_instance = MagicMock(name="MockAgentRunnable")
    mock_runnable_instance.invoke.return_value = {"output": '{"metadata": {}}'}

    with patch.object(agent, "agent_runnable", mock_runnable_instance):
        result_dict = agent.run(
            user_input="content",
            style="style",
            template_name="template",
            template_data=sample_template_data,
            generation_method="json",
        )
        assert result_dict["type"] == "error"
        assert "JSON output from agent is missing 'slides' key" in result_dict["output"]


def test_presentation_agent_run_code_path_unsafe_code(
    mock_llm,
    sample_template_data,
    sample_raw_text_content,
    sample_style,
    sample_template_name,
    mock_code_gen_output,
    mock_unsafe_quality_check_output,
):
    agent = PresentationAgent(llm=mock_llm, tools=[])

    code_gen_data = json.loads(mock_code_gen_output)
    quality_data = json.loads(mock_unsafe_quality_check_output)

    intermediate_steps_simulation = [
        (
            AgentAction(
                tool="Code_Generator",
                tool_input={"content": "...", "style": "...", "template_name": "..."},
                log="...",
            ),
            mock_code_gen_output,
        ),
        (
            AgentAction(
                tool="Code_Quality_Checker",
                tool_input={"python_code": code_gen_data["python_code"]},
                log="...",
            ),
            mock_unsafe_quality_check_output,
        ),
    ]
    mock_runnable_instance = MagicMock(name="MockAgentRunnable")

    mock_runnable_instance.invoke.return_value = {
        "output": mock_unsafe_quality_check_output,
        "intermediate_steps": intermediate_steps_simulation,
    }

    with patch.object(agent, "agent_runnable", mock_runnable_instance):
        result_dict = agent.run(
            user_input=sample_raw_text_content,
            style=sample_style,
            template_name=sample_template_name,
            template_data=sample_template_data,
            generation_method="code",
        )

    assert result_dict["type"] == "error"
    assert "Generated code deemed unsafe" in result_dict["output"]
    assert quality_data["assessment"] in result_dict["output"]
    assert quality_data["warnings"][0] in result_dict["output"]


@patch("app.agents.create_code_quality_check_tool")
def test_run_code_quality_check_tool_with_llm_success(mock_core_tool_func, mock_llm):
    tool_input_dict = {"python_code": "print('safe')"}
    expected_output = '{"is_safe": true, "warnings": [], "assessment": "Safe"}'
    mock_core_tool_func.return_value = expected_output

    result = run_code_quality_check_tool_with_llm(tool_input_dict, mock_llm)

    mock_core_tool_func.assert_called_once()
    call_args, _ = mock_core_tool_func.call_args
    assert isinstance(call_args[0], CodeQualityCheckInput)
    assert call_args[0].python_code == "print('safe')"
    assert result == expected_output