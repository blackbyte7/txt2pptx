import json
from pathlib import Path
from unittest.mock import MagicMock, patch
from langchain_core.agents import AgentAction, AgentFinish
from langchain_core.tools import BaseTool
from langchain_experimental.tools import PythonREPLTool
import pytest
from langchain_core.documents import Document
from app.agents import PresentationAgent, create_agent, get_llm_instance, run_bullet_points_tool_with_llm, \
    run_quality_check_tool_with_llm, run_code_quality_check_tool_with_llm
from app.tools import BulletPointInput, QualityCheckInput, CodeQualityCheckInput
from tests.conftest import (
    mock_llm, mock_retriever, sample_raw_text_content,
    sample_style, sample_template_name, sample_detailed_presentation_json, sample_template_data
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

    with patch('app.agents.PythonREPLTool', return_value=MagicMock(spec=PythonREPLTool, name="MockPythonREPLTool")) as mock_repl:
        agent_instance = create_agent("openai", "key", loaded_docs=None)

    mock_get_llm.assert_called_once_with("openai", "key")
    mock_EnhancedRAG.assert_not_called()

    assert mock_BaseTool.from_function.call_count == 4
    mock_PresentationAgent.assert_called_once()
    init_args, init_kwargs = mock_PresentationAgent.call_args
    assert init_kwargs['llm'] is mock_llm
    assert len(init_kwargs['tools']) == 5
    assert init_kwargs['retriever'] is None
    mock_repl.assert_called_once()


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

    with patch('app.agents.PythonREPLTool', return_value=MagicMock(spec=PythonREPLTool, name="MockPythonREPLTool")) as mock_repl:
        agent_instance = create_agent("anthropic", "key", loaded_docs=sample_docs)

    mock_get_llm.assert_called_once_with("anthropic", "key")
    mock_EnhancedRAG.assert_called_once_with(docs=sample_docs, cache_name="pptx_docs_context")
    mock_rag_instance.get_retriever.assert_called_once_with(k=5)

    mock_PresentationAgent.assert_called_once()
    init_args, init_kwargs = mock_PresentationAgent.call_args
    assert init_kwargs['llm'] is mock_llm
    assert len(init_kwargs['tools']) == 5
    assert init_kwargs['retriever'] is mock_retriever
    mock_repl.assert_called_once()


@patch('app.agents.get_llm_instance')
@patch('app.agents.EnhancedRAG', side_effect=Exception("RAG Init Failed"))
@patch('app.agents.BaseTool')
@patch('app.agents.PresentationAgent')
def test_create_agent_rag_init_failure(mock_PresentationAgent, mock_BaseTool, mock_EnhancedRAG, mock_get_llm, mock_llm):
    mock_get_llm.return_value = mock_llm
    sample_docs = [Document(page_content="doc1")]

    with patch('app.agents.PythonREPLTool', return_value=MagicMock(spec=PythonREPLTool, name="MockPythonREPLTool")) as mock_repl:
        agent_instance = create_agent("openai", "key", loaded_docs=sample_docs)

    mock_get_llm.assert_called_once_with("openai", "key")
    mock_EnhancedRAG.assert_called_once_with(docs=sample_docs, cache_name="pptx_docs_context")

    mock_PresentationAgent.assert_called_once()
    init_args, init_kwargs = mock_PresentationAgent.call_args
    assert init_kwargs['llm'] is mock_llm
    assert len(init_kwargs['tools']) == 5
    assert init_kwargs['retriever'] is None
    mock_repl.assert_called_once()


def test_presentation_agent_run_success(mock_llm, mock_retriever,
                                        sample_detailed_presentation_json, sample_template_data,
                                        sample_raw_text_content, sample_style, sample_template_name):
    agent = PresentationAgent(llm=mock_llm, tools=[], retriever=mock_retriever)

    raw_json_output_str = json.dumps(sample_detailed_presentation_json)
    mock_runnable_instance = MagicMock(name="MockAgentRunnable")
    mock_runnable_instance.invoke.return_value = {"output": raw_json_output_str}

    with patch.object(agent, 'agent_runnable', mock_runnable_instance):
        result_dict = agent.run(
            user_input=sample_raw_text_content,
            style=sample_style,
            template_name=sample_template_name,
            template_data=sample_template_data,
            generation_method='json'
        )

        mock_runnable_instance.invoke.assert_called_once()
        call_args, call_kwargs = mock_runnable_instance.invoke.call_args
        agent_input_dict = call_args[0]
        assert "input" in agent_input_dict
        assert sample_raw_text_content in agent_input_dict["input"]
        assert sample_style in agent_input_dict["input"]
        assert sample_template_name in agent_input_dict["input"]
        assert "json" in agent_input_dict["input"]
        assert "chat_history" in agent_input_dict

    expected_dict = {
        "type": "json",
        "output": raw_json_output_str
    }
    assert result_dict == expected_dict


def test_presentation_agent_run_json_cleaning(mock_llm, sample_template_data): # Added fixture
    agent = PresentationAgent(llm=mock_llm, tools=[])

    core_json_str = json.dumps({"metadata": {}, "slides": [{"title": "Cleaned"}]})
    raw_output_with_fences = f"```json\n{core_json_str}\n```"

    mock_runnable_instance = MagicMock(name="MockAgentRunnable")
    mock_runnable_instance.invoke.return_value = {"output": raw_output_with_fences}

    with patch.object(agent, 'agent_runnable', mock_runnable_instance):
        result_dict = agent.run(
            user_input="content",
            style="style",
            template_name="template",
            template_data=sample_template_data,
            generation_method='json'
        )

    expected_result = {"type": "json", "output": core_json_str}
    assert result_dict == expected_result
    mock_runnable_instance.invoke.assert_called_once()


def test_presentation_agent_run_bad_json_output(mock_llm, sample_template_data): # Added fixture
    agent = PresentationAgent(llm=mock_llm, tools=[])
    bad_json_output = '{"slides": [ BAD JSON ]}'

    mock_runnable_instance = MagicMock(name="MockAgentRunnable")
    mock_runnable_instance.invoke.return_value = {"output": bad_json_output}

    with patch.object(agent, 'agent_runnable', mock_runnable_instance):
        result_dict = agent.run(
            user_input="content",
            style="style",
            template_name="template",
            template_data=sample_template_data,
            generation_method='json'
        )
        assert result_dict["type"] == "error"
        assert "Agent did not return valid JSON structure" in result_dict["output"]

    mock_runnable_instance.invoke.assert_called_once()


def test_presentation_agent_run_invalid_structure_output(mock_llm, sample_template_data): # Added fixture
    agent = PresentationAgent(llm=mock_llm, tools=[])

    invalid_structure_json = '{"metadata": {}}'
    mock_runnable_instance = MagicMock(name="MockAgentRunnable")
    mock_runnable_instance.invoke.return_value = {"output": invalid_structure_json}

    with patch.object(agent, 'agent_runnable', mock_runnable_instance):
        result_dict = agent.run(
            user_input="content",
            style="style",
            template_name="template",
            template_data=sample_template_data,
            generation_method='json'
        )
        assert result_dict["type"] == "error"
        assert "JSON output from agent is missing 'slides' key" in result_dict["output"]

    mock_runnable_instance.invoke.assert_called_once()


def test_presentation_agent_run_agent_exception(mock_llm, sample_template_data):
    agent = PresentationAgent(llm=mock_llm, tools=[])

    mock_runnable_instance = MagicMock(name="MockAgentRunnable")
    mock_runnable_instance.invoke.side_effect = Exception("LLM API Error")

    with patch.object(agent, 'agent_runnable', mock_runnable_instance):
        result_dict = agent.run(
            user_input="content",
            style="style",
            template_name="template",
            template_data=sample_template_data,
            generation_method='json'
        )
        assert result_dict["type"] == "error"
        assert "An unexpected error occurred in the agent: LLM API Error" in result_dict["output"]

    mock_runnable_instance.invoke.assert_called_once()


def test_presentation_agent_run_code_path_success(
    mock_llm, sample_template_data, sample_raw_text_content, sample_style, sample_template_name,
    mock_code_gen_output, mock_safe_quality_check_output, mock_repl_output, tmp_path):

    agent = PresentationAgent(llm=mock_llm, tools=[])

    # Simulate Intermediate Steps
    code_gen_data = json.loads(mock_code_gen_output)
    quality_data = json.loads(mock_safe_quality_check_output)
    expected_filename = code_gen_data['output_filename']

    Path(expected_filename).touch()

    # Provide valid dicts for tool_input
    intermediate_steps_simulation = [
        (AgentAction(tool="Code_Generator", tool_input={"content": "...", "style": "...", "template_name": "..."}, log="..."), mock_code_gen_output),
        (AgentAction(tool="Code_Quality_Checker", tool_input={"python_code": code_gen_data['python_code']}, log="..."), mock_safe_quality_check_output),
        (AgentAction(tool="PythonREPLTool", tool_input={"code": code_gen_data['python_code']}, log="..."), mock_repl_output), # REPL input is often 'code' or '__arg1'
    ]
    mock_runnable_instance = MagicMock(name="MockAgentRunnable")
    mock_runnable_instance.invoke.return_value = {
        "output": mock_repl_output,
        "intermediate_steps": intermediate_steps_simulation
    }

    with patch.object(agent, 'agent_runnable', mock_runnable_instance):
        result_dict = agent.run(
            user_input=sample_raw_text_content,
            style=sample_style,
            template_name=sample_template_name,
            template_data=sample_template_data,
            generation_method='code'
        )

        mock_runnable_instance.invoke.assert_called_once()

    assert result_dict["type"] == "code_execution"
    assert result_dict["output"] == mock_repl_output
    assert Path(result_dict["generated_filename"]).name == Path(expected_filename).name
    assert Path(result_dict["generated_filename"]).exists()


def test_presentation_agent_run_code_path_unsafe_code(
    mock_llm, sample_template_data, sample_raw_text_content, sample_style, sample_template_name,
    mock_code_gen_output, mock_unsafe_quality_check_output):

    agent = PresentationAgent(llm=mock_llm, tools=[])

    code_gen_data = json.loads(mock_code_gen_output)
    quality_data = json.loads(mock_unsafe_quality_check_output)

    intermediate_steps_simulation = [
        (AgentAction(tool="Code_Generator", tool_input={"content": "...", "style": "...", "template_name": "..."}, log="..."), mock_code_gen_output),
        (AgentAction(tool="Code_Quality_Checker", tool_input={"python_code": code_gen_data['python_code']}, log="..."), mock_unsafe_quality_check_output),
    ]
    mock_runnable_instance = MagicMock(name="MockAgentRunnable")

    mock_runnable_instance.invoke.return_value = {
        "output": mock_unsafe_quality_check_output,
        "intermediate_steps": intermediate_steps_simulation
    }

    with patch.object(agent, 'agent_runnable', mock_runnable_instance):
        result_dict = agent.run(
            user_input=sample_raw_text_content,
            style=sample_style,
            template_name=sample_template_name,
            template_data=sample_template_data,
            generation_method='code'
        )

        mock_runnable_instance.invoke.assert_called_once()

    assert result_dict["type"] == "error"
    assert "Generated code deemed unsafe" in result_dict["output"]
    assert quality_data['assessment'] in result_dict["output"]
    assert quality_data['warnings'][0] in result_dict["output"]


def test_presentation_agent_run_code_path_repl_fails_file_not_found(
    mock_llm, sample_template_data, sample_raw_text_content, sample_style, sample_template_name,
    mock_code_gen_output, mock_safe_quality_check_output, mock_repl_output):

    agent = PresentationAgent(llm=mock_llm, tools=[])

    code_gen_data = json.loads(mock_code_gen_output)
    expected_filename = code_gen_data['output_filename']

    intermediate_steps_simulation = [
        (AgentAction(tool="Code_Generator", tool_input={"content": "...", "style": "...", "template_name": "..."}, log="..."), mock_code_gen_output),
        (AgentAction(tool="Code_Quality_Checker", tool_input={"python_code": code_gen_data['python_code']}, log="..."), mock_safe_quality_check_output),
        (AgentAction(tool="PythonREPLTool", tool_input={"code": code_gen_data['python_code']}, log="..."), mock_repl_output),
    ]

    mock_runnable_instance = MagicMock(name="MockAgentRunnable")
    mock_runnable_instance.invoke.return_value = {
        "output": mock_repl_output,
        "intermediate_steps": intermediate_steps_simulation
    }

    with patch.object(agent, 'agent_runnable', mock_runnable_instance):
        result_dict = agent.run(
            user_input=sample_raw_text_content,
            style=sample_style,
            template_name=sample_template_name,
            template_data=sample_template_data,
            generation_method='code'
        )

        mock_runnable_instance.invoke.assert_called_once()

    assert result_dict["type"] == "error"
    assert "expected output file" in result_dict["output"]
    assert "was not found" in result_dict["output"]
    assert Path(expected_filename).name in result_dict["output"]
    assert result_dict["generated_filename"] == expected_filename


@patch('app.agents.get_llm_instance')
@patch('app.agents.EnhancedRAG')
@patch('app.agents.BaseTool')
@patch('app.agents.PresentationAgent')
def test_create_agent_adds_all_tools(mock_PresentationAgent, mock_BaseTool, mock_EnhancedRAG, mock_get_llm, mock_llm):
    mock_get_llm.return_value = mock_llm
    mock_EnhancedRAG.return_value.get_retriever.return_value = None

    created_tools_mocks = []

    def from_function_side_effect(*args, **kwargs):
        tool_mock = MagicMock(spec=BaseTool)
        tool_mock.name = kwargs.get('name', 'UnknownTool')
        created_tools_mocks.append(tool_mock)
        return tool_mock
    mock_BaseTool.from_function.side_effect = from_function_side_effect

    mock_repl_instance = MagicMock(spec=PythonREPLTool, name="MockPythonREPLTool")
    mock_repl_instance.name = "PythonREPLTool"
    with patch('app.agents.PythonREPLTool', return_value=mock_repl_instance) as mock_repl:
        create_agent("openai", "key", loaded_docs=None)

    assert mock_BaseTool.from_function.call_count == 4

    mock_repl.assert_called_once()
    mock_PresentationAgent.assert_called_once()
    init_args, init_kwargs = mock_PresentationAgent.call_args
    agent_tools = init_kwargs['tools']
    assert len(agent_tools) == 5

    tool_names = [t.name for t in agent_tools]
    print(f"Actual tool names found in mock: {tool_names}")

    assert "Bullet_Points_Generator" in tool_names
    assert "Code_Generator" in tool_names
    assert "Code_Quality_Checker" in tool_names
    assert "PythonREPLTool" in tool_names
    assert "Presentation_Quality_Checker" in tool_names


@patch('app.agents.create_code_quality_check_tool')
def test_run_code_quality_check_tool_with_llm_success(mock_core_tool_func, mock_llm):
    tool_input_dict = {"python_code": "print('safe')"}
    expected_output = '{"is_safe": true, "warnings": [], "assessment": "Safe"}'
    mock_core_tool_func.return_value = expected_output

    result = run_code_quality_check_tool_with_llm(tool_input_dict, mock_llm)

    mock_core_tool_func.assert_called_once()
    call_args, call_kwargs = mock_core_tool_func.call_args
    assert isinstance(call_args[0], CodeQualityCheckInput)
    assert call_args[0].python_code == "print('safe')"
    assert call_args[1] is mock_llm
    assert result == expected_output


@patch('app.agents.create_code_quality_check_tool')
def test_run_code_quality_check_tool_with_llm_error(mock_core_tool_func, mock_llm):
    tool_input_dict = {"python_code": "print('test')"}
    mock_core_tool_func.side_effect = Exception("Core tool failed")

    result_json = run_code_quality_check_tool_with_llm(tool_input_dict, mock_llm)
    result_data = json.loads(result_json)

    assert result_data["is_safe"] is False
    assert "Failed to run code quality analysis tool" in result_data["warnings"][0]
    assert "Core tool failed" in result_data["warnings"][0]