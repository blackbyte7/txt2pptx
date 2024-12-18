import json
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.documents import Document

from app.agents import PresentationAgent, create_agent, get_llm_instance, run_bullet_points_tool_with_llm, \
    run_quality_check_tool_with_llm
from app.tools import BulletPointInput, QualityCheckInput
# Import fixtures
from tests.conftest import (
    mock_llm, mock_retriever, sample_raw_text_content,
    sample_style, sample_template_name, sample_detailed_presentation_json
)


@patch('app.agents.ChatOpenAI')
def test_get_llm_instance_openai(mock_ChatOpenAI, mock_llm):
    mock_ChatOpenAI.return_value = mock_llm
    api_key = "sk-testkey"
    llm = get_llm_instance("openai", api_key)
    mock_ChatOpenAI.assert_called_once_with(
        api_key=api_key,
        model='gpt-4-turbo',
        temperature=0.1,
        max_tokens=4096
    )
    assert llm is mock_llm


@patch('app.agents.ChatAnthropic')
def test_get_llm_instance_anthropic(mock_ChatAnthropic, mock_llm):
    mock_ChatAnthropic.return_value = mock_llm
    api_key = "ak-testkey"
    llm = get_llm_instance("anthropic", api_key)
    expected_model = "claude-3-5-sonnet-20240620"
    mock_ChatAnthropic.assert_called_once_with(
        api_key=api_key,
        model_name=expected_model,
        temperature=0.1,
        max_tokens=4096
    )
    assert llm is mock_llm


def test_get_llm_instance_unsupported():
    with pytest.raises(ValueError, match="Unsupported LLM provider: unsupported"):
        get_llm_instance("unsupported", "key")


@patch('app.agents.create_bullet_points_tool')
def test_run_bullet_points_tool_with_llm_success(mock_core_tool_func, mock_llm, mock_retriever):
    tool_input_dict = {"content": "Test content", "style": "Test Style", "template_name": "test_template"}
    expected_output = '{"slides": []}'
    mock_core_tool_func.return_value = expected_output

    result = run_bullet_points_tool_with_llm(tool_input_dict, mock_llm, mock_retriever)

    mock_core_tool_func.assert_called_once()
    call_args, call_kwargs = mock_core_tool_func.call_args
    assert isinstance(call_args[0], BulletPointInput)
    assert call_args[0].content == "Test content"
    assert call_args[0].style == "Test Style"
    assert call_args[1] is mock_llm
    assert call_args[2] is mock_retriever

    assert result == expected_output


@patch('app.agents.create_bullet_points_tool')
def test_run_bullet_points_tool_with_llm_error(mock_core_tool_func, mock_llm, mock_retriever):
    tool_input_dict = {"content": "Test content", "style": "Test Style", "template_name": "test_template"}
    mock_core_tool_func.side_effect = ValueError("Core tool failed")

    result = run_bullet_points_tool_with_llm(tool_input_dict, mock_llm, mock_retriever)

    assert "Error executing Bullet_Points_Generator:" in result
    assert "Core tool failed" in result


@patch('app.agents.create_quality_check_tool')
def test_run_quality_check_tool_with_llm_success(mock_core_tool_func, mock_llm):
    tool_input_dict = {"presentation_structure": {"slides": [{"title": "S1"}]}, "target_audience": "Experts"}
    expected_output = '{"score": 90}'
    mock_core_tool_func.return_value = expected_output

    result = run_quality_check_tool_with_llm(tool_input_dict, mock_llm)

    mock_core_tool_func.assert_called_once()
    call_args, call_kwargs = mock_core_tool_func.call_args
    assert isinstance(call_args[0], QualityCheckInput)
    assert call_args[0].presentation_structure == {"slides": [{"title": "S1"}]}
    assert call_args[0].target_audience == "Experts"
    assert call_args[1] is mock_llm

    assert result == expected_output


@patch('app.agents.create_quality_check_tool')
def test_run_quality_check_tool_with_llm_error(mock_core_tool_func, mock_llm):
    tool_input_dict = {"presentation_structure": {"slides": []}}
    mock_core_tool_func.side_effect = TypeError("Analysis failed")

    result = run_quality_check_tool_with_llm(tool_input_dict, mock_llm)

    assert "Error executing Presentation_Quality_Checker:" in result
    assert "Analysis failed" in result


@patch('app.agents.get_llm_instance')
@patch('app.agents.EnhancedRAG')
@patch('app.agents.BaseTool')
@patch('app.agents.PresentationAgent')
def test_create_agent_success_no_rag(mock_PresentationAgent, mock_BaseTool, mock_EnhancedRAG, mock_get_llm, mock_llm):
    mock_get_llm.return_value = mock_llm
    mock_EnhancedRAG.return_value.get_retriever.return_value = None

    agent_instance = create_agent("openai", "key", loaded_docs=None)

    mock_get_llm.assert_called_once_with("openai", "key")
    mock_EnhancedRAG.assert_not_called()

    assert mock_BaseTool.from_function.call_count == 2
    mock_PresentationAgent.assert_called_once()
    init_args, init_kwargs = mock_PresentationAgent.call_args
    assert init_kwargs['llm'] is mock_llm
    assert len(init_kwargs['tools']) == 2
    assert init_kwargs['retriever'] is None


@patch('app.agents.get_llm_instance')
@patch('app.agents.EnhancedRAG')
@patch('app.agents.BaseTool')
@patch('app.agents.PresentationAgent')
def test_create_agent_success_with_rag(mock_PresentationAgent, mock_BaseTool, mock_EnhancedRAG, mock_get_llm, mock_llm,
                                       mock_retriever):
    mock_get_llm.return_value = mock_llm
    mock_rag_instance = mock_EnhancedRAG.return_value
    mock_rag_instance.get_retriever.return_value = mock_retriever
    sample_docs = [Document(page_content="doc1")]

    agent_instance = create_agent("anthropic", "key", loaded_docs=sample_docs)

    mock_get_llm.assert_called_once_with("anthropic", "key")
    mock_EnhancedRAG.assert_called_once_with(docs=sample_docs, cache_name="pptx_docs_structure_elements")
    mock_rag_instance.get_retriever.assert_called_once_with(k=4)

    mock_PresentationAgent.assert_called_once()
    init_args, init_kwargs = mock_PresentationAgent.call_args
    assert init_kwargs['llm'] is mock_llm
    assert len(init_kwargs['tools']) == 2
    assert init_kwargs['retriever'] is mock_retriever


@patch('app.agents.get_llm_instance')
@patch('app.agents.EnhancedRAG', side_effect=Exception("RAG Init Failed"))
@patch('app.agents.BaseTool')
@patch('app.agents.PresentationAgent')
def test_create_agent_rag_init_failure(mock_PresentationAgent, mock_BaseTool, mock_EnhancedRAG, mock_get_llm, mock_llm):
    mock_get_llm.return_value = mock_llm
    sample_docs = [Document(page_content="doc1")]

    agent_instance = create_agent("openai", "key", loaded_docs=sample_docs)

    mock_get_llm.assert_called_once_with("openai", "key")
    mock_EnhancedRAG.assert_called_once()

    mock_PresentationAgent.assert_called_once()
    init_args, init_kwargs = mock_PresentationAgent.call_args
    assert init_kwargs['llm'] is mock_llm
    assert len(init_kwargs['tools']) == 2
    assert init_kwargs['retriever'] is None


# --- Test PresentationAgent Run Method ---

def test_presentation_agent_run_success(mock_llm, mock_retriever,
                                        sample_detailed_presentation_json, sample_template_data,
                                        sample_raw_text_content, sample_style, sample_template_name):
    agent = PresentationAgent(llm=mock_llm, tools=[], retriever=mock_retriever)

    raw_json_output = json.dumps(sample_detailed_presentation_json)
    mock_runnable_instance = MagicMock(name="MockAgentRunnable")
    mock_runnable_instance.invoke.return_value = {"output": raw_json_output}

    with patch.object(agent, 'agent_runnable', mock_runnable_instance):
        result_dict = agent.run(sample_raw_text_content, sample_style, sample_template_name)

        mock_runnable_instance.invoke.assert_called_once()
        call_args, call_kwargs = mock_runnable_instance.invoke.call_args
        agent_input_dict = call_args[0]
        assert "input" in agent_input_dict
        assert sample_raw_text_content in agent_input_dict["input"]
        assert sample_raw_text_content in agent_input_dict["input"]
        assert sample_style in agent_input_dict["input"]
        assert sample_template_name in agent_input_dict["input"]
        assert "chat_history" in agent_input_dict

    expected_dict = sample_detailed_presentation_json.copy()
    assert result_dict == expected_dict


def test_presentation_agent_run_json_cleaning(mock_llm):
    agent = PresentationAgent(llm=mock_llm, tools=[])

    core_json = {"metadata": {}, "slides": [{"title": "Cleaned"}]}
    raw_json_output = f"```json\n{json.dumps(core_json)}\n```"

    mock_runnable_instance = MagicMock(name="MockAgentRunnable")
    mock_runnable_instance.invoke.return_value = {"output": raw_json_output}

    with patch.object(agent, 'agent_runnable', mock_runnable_instance):
        result_dict = agent.run("content", "style", "template")

    assert result_dict == core_json
    mock_runnable_instance.invoke.assert_called_once()


def test_presentation_agent_run_bad_json_output(mock_llm):
    agent = PresentationAgent(llm=mock_llm, tools=[])
    bad_json_output = '{"slides": [ BAD JSON ]}'

    mock_runnable_instance = MagicMock(name="MockAgentRunnable")
    mock_runnable_instance.invoke.return_value = {"output": bad_json_output}

    with patch.object(agent, 'agent_runnable', mock_runnable_instance):
        with pytest.raises(ValueError, match="Agent did not return valid JSON"):
            agent.run("content", "style", "template")

    mock_runnable_instance.invoke.assert_called_once()


def test_presentation_agent_run_invalid_structure_output(mock_llm):
    agent = PresentationAgent(llm=mock_llm, tools=[])

    invalid_structure_json = '{"metadata": {}}'
    mock_runnable_instance = MagicMock(name="MockAgentRunnable")
    mock_runnable_instance.invoke.return_value = {"output": invalid_structure_json}

    with patch.object(agent, 'agent_runnable', mock_runnable_instance):
        with pytest.raises(ValueError, match="Agent output JSON is missing the required 'slides' key"):
            agent.run("content", "style", "template")

    mock_runnable_instance.invoke.assert_called_once()


def test_presentation_agent_run_agent_exception(mock_llm):
    agent = PresentationAgent(llm=mock_llm, tools=[])

    mock_runnable_instance = MagicMock(name="MockAgentRunnable")
    mock_runnable_instance.invoke.side_effect = Exception("LLM API Error")

    with patch.object(agent, 'agent_runnable', mock_runnable_instance):
        with pytest.raises(RuntimeError, match="An unexpected error occurred in the agent: LLM API Error"):
            agent.run("content", "style", "template")

    mock_runnable_instance.invoke.assert_called_once()
