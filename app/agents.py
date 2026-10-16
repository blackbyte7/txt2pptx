import json
import os
import subprocess
import sys
import tempfile
from functools import partial
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from langchain_anthropic import ChatAnthropic
from langchain_core.documents import Document
from langchain_core.language_models import BaseChatModel
from langchain_core.retrievers import BaseRetriever
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool
from langchain_openai import ChatOpenAI

from app.rag import EnhancedRAG
from app.tools import (
    BulletPointInput,
    CodeQualityAnalysisOutput,
    CodeQualityCheckInput,
    GenerateCodeInput,
    GeneratedCodeOutput,
    QualityCheckInput,
    create_bullet_points_tool,
    create_code_generation_tool,
    create_code_quality_check_tool,
    create_quality_check_tool,
    validate_python_code_ast,
)
from log_config.logging_config import logger

DEFAULT_OPENAI_MODEL = "gpt-4-turbo"
DEFAULT_ANTHROPIC_MODEL = "claude-3-5-sonnet-20240620"
DEFAULT_LLM_TEMPERATURE = 0.1
DEFAULT_LLM_MAX_TOKENS = 4096


def _execute_code_safely(python_code: str, timeout_seconds: int = 60) -> str:
    """Executes AST-validated python-pptx code in an isolated subprocess with stripped credentials."""
    ast_warnings = validate_python_code_ast(python_code)
    if ast_warnings:
        raise PermissionError(f"Blocked execution due to AST security violations: {'; '.join(ast_warnings)}")

    safe_env = {
        k: v
        for k, v in os.environ.items()
        if k not in {"OPENAI_API_KEY", "ANTHROPIC_API_KEY"}
    }

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False, encoding="utf-8"
    ) as tmp_script:
        tmp_script.write(python_code)
        script_path = Path(tmp_script.name)

    try:
        proc = subprocess.run(
            [sys.executable, "-I", str(script_path)],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            env=safe_env,
            check=False,
        )
        output = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        if proc.returncode != 0:
            logger.error(f"Subprocess execution failed (exit {proc.returncode}): {output.strip()}")
        return output.strip() or "Code execution finished."
    finally:
        script_path.unlink(missing_ok=True)


class PresentationAgent:
    def __init__(
        self,
        llm: BaseChatModel,
        tools: List[BaseTool],
        retriever: Optional[BaseRetriever] = None,
    ):
        self.llm = llm
        self.tools = tools
        self.retriever = retriever
        self.agent_runnable: Optional[Any] = None
        logger.info(
            f"PresentationAgent initialized with LLM: {llm.__class__.__name__} and "
            f"Tools: {[t.name for t in tools]}."
        )

    def run(
        self,
        user_input: str,
        style: str,
        template_name: str,
        template_data: Dict[str, Any],
        generation_method: str,
        config: Optional[RunnableConfig] = None,
    ) -> Dict[str, Any]:
        """Executes the presentation creation pipeline using the selected method ('json' or 'code')."""
        logger.info(
            f"Running PresentationAgent. Method: '{generation_method}', Style: '{style}', Template: '{template_name}'"
        )

        try:
            # Support mocked agent_runnable if injected during unit tests
            if self.agent_runnable is not None:
                return self._run_via_agent_runnable(
                    user_input=user_input,
                    style=style,
                    template_name=template_name,
                    template_data=template_data,
                    generation_method=generation_method,
                    config=config,
                )

            if generation_method == "json":
                logger.info("Executing deterministic JSON generation pipeline...")
                bp_input = BulletPointInput(
                    content=user_input,
                    style=style,
                    template_name=template_name,
                )
                raw_json = create_bullet_points_tool(
                    bp_input, self.llm, self.retriever, config=config
                )
                cleaned_json = self._clean_json_output(raw_json)
                parsed_json = json.loads(cleaned_json)
                if not isinstance(parsed_json, dict) or "slides" not in parsed_json:
                    raise ValueError("JSON output is missing 'slides' key or is not a dictionary.")
                return {"type": "json", "output": cleaned_json}

            elif generation_method == "code":
                logger.info("Executing deterministic Code generation pipeline...")
                code_input = GenerateCodeInput(
                    content=user_input,
                    style=style,
                    template_name=template_name,
                    template_data=template_data or {},
                )
                code_gen_json = create_code_generation_tool(
                    code_input, self.llm, self.retriever, config=config
                )
                code_gen_data = json.loads(code_gen_json)
                validated_code_gen = GeneratedCodeOutput(**code_gen_data)

                qc_input = CodeQualityCheckInput(python_code=validated_code_gen.python_code)
                qc_json = create_code_quality_check_tool(qc_input, self.llm, config=config)
                qc_data = json.loads(qc_json)
                validated_qc = CodeQualityAnalysisOutput(**qc_data)

                if not validated_qc.is_safe:
                    return {
                        "type": "error",
                        "output": (
                            f"Generated code deemed unsafe or irrelevant by Code Quality Check.\n"
                            f"Assessment: {validated_qc.assessment}\n"
                            f"Warnings: {'; '.join(validated_qc.warnings)}"
                        ),
                    }

                repl_output = _execute_code_safely(validated_code_gen.python_code)
                generated_filename_path = Path(validated_code_gen.output_filename)

                if generated_filename_path.exists():
                    return {
                        "type": "code_execution",
                        "output": repl_output,
                        "generated_filename": str(generated_filename_path.absolute()),
                    }
                return {
                    "type": "error",
                    "output": (
                        f"Code execution finished, but the expected output file "
                        f"'{generated_filename_path.name}' was not found in '{generated_filename_path.parent}'.\n\n"
                        f"Execution Output:\n{repl_output}"
                    ),
                    "generated_filename": validated_code_gen.output_filename,
                }

            else:
                return {
                    "type": "error",
                    "output": f"Internal error: Unknown generation method '{generation_method}'.",
                }

        except Exception as e:
            logger.error(f"An unexpected error occurred during PresentationAgent execution: {e}", exc_info=True)
            return {"type": "error", "output": f"An unexpected error occurred in the agent: {e}"}

    def _run_via_agent_runnable(
        self,
        user_input: str,
        style: str,
        template_name: str,
        template_data: Dict[str, Any],
        generation_method: str,
        config: Optional[RunnableConfig] = None,
    ) -> Dict[str, Any]:
        """Handles execution when an external/mocked agent_runnable is attached."""
        agent_input_message = (
            f"Generate a presentation.\nChosen Generation Method: {generation_method}\n"
            f"Presentation Style: {style}\nVisual Template Name: {template_name}\n"
            f"Template Data: {json.dumps(template_data)}\nContent:\n{user_input}"
        )
        effective_config = config or RunnableConfig()
        agent_response = self.agent_runnable.invoke(
            {"input": agent_input_message, "chat_history": []}, config=effective_config
        )

        intermediate_steps = (
            agent_response.get("intermediate_steps", [])
            if isinstance(agent_response, dict)
            else []
        )
        final_output_content = (
            agent_response.get("output")
            if isinstance(agent_response, dict)
            else str(agent_response)
        )

        if generation_method == "json":
            cleaned_json_string = self._clean_json_output(final_output_content or "")
            try:
                parsed_json = json.loads(cleaned_json_string)
                if not isinstance(parsed_json, dict) or "slides" not in parsed_json:
                    raise ValueError("JSON output from agent is missing 'slides' key or is not a dictionary.")
                return {"type": "json", "output": cleaned_json_string}
            except (json.JSONDecodeError, ValueError) as json_err:
                return {"type": "error", "output": f"Agent did not return valid JSON structure: {json_err}"}

        if generation_method == "code":
            if not intermediate_steps:
                return {
                    "type": "error",
                    "output": f"Agent execution incomplete (no intermediate steps found). Final output: {final_output_content}",
                }

            code_generator_output_json = None
            code_quality_output_json = None
            repl_output = None

            for step in intermediate_steps:
                if len(step) == 2 and hasattr(step[0], "tool"):
                    if step[0].tool == "Code_Generator":
                        code_generator_output_json = step[1]
                    elif step[0].tool == "Code_Quality_Checker":
                        code_quality_output_json = step[1]
                    elif step[0].tool == "PythonREPLTool":
                        repl_output = step[1]

            if not code_generator_output_json:
                return {"type": "error", "output": "Agent failed to use the Code_Generator tool."}

            code_gen_data = json.loads(code_generator_output_json)
            GeneratedCodeOutput(**code_gen_data)
            generated_filename = code_gen_data.get("output_filename")

            if not code_quality_output_json:
                return {"type": "error", "output": "Agent failed to use the Code_Quality_Checker tool."}

            quality_check_data = json.loads(code_quality_output_json)
            CodeQualityAnalysisOutput(**quality_check_data)

            if not quality_check_data.get("is_safe"):
                return {
                    "type": "error",
                    "output": (
                        f"Generated code deemed unsafe or irrelevant by Code Quality Check.\n"
                        f"Assessment: {quality_check_data.get('assessment', 'N/A')}\n"
                        f"Warnings: {'; '.join(quality_check_data.get('warnings', []))}"
                    ),
                }

            generated_filename_path = Path(generated_filename)
            if generated_filename_path.exists():
                return {
                    "type": "code_execution",
                    "output": repl_output if repl_output is not None else (final_output_content or ""),
                    "generated_filename": str(generated_filename_path.absolute()),
                }
            return {
                "type": "error",
                "output": (
                    f"Code execution and REPL step finished, but the expected output file "
                    f"'{generated_filename_path.name}' was not found in '{generated_filename_path.parent}'."
                ),
                "generated_filename": generated_filename,
            }

        return {"type": "error", "output": f"Unknown generation method: {generation_method}"}

    def _clean_json_output(self, raw_output: str) -> str:
        """Cleans potential markdown code fences from JSON output."""
        if not isinstance(raw_output, str):
            return ""
        cleaned = raw_output.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3].strip()
        elif cleaned.startswith("```"):
            cleaned = cleaned[3:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3].strip()

        first_brace = cleaned.find("{")
        last_brace = cleaned.rfind("}")
        if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
            potential_json = cleaned[first_brace : last_brace + 1]
            try:
                json.loads(potential_json)
                logger.debug("Successfully extracted JSON content using brace finding.")
                return potential_json
            except json.JSONDecodeError:
                logger.warning("Brace finding resulted in invalid JSON. Returning original cleaned string.")
                return cleaned
        return cleaned


def get_llm_instance(llm_provider: str, api_key: str) -> BaseChatModel:
    """Helper function to get LLM instance using environment variables or defaults."""
    temperature = float(os.getenv("LLM_TEMPERATURE", DEFAULT_LLM_TEMPERATURE))
    max_tokens = int(os.getenv("LLM_MAX_TOKENS", DEFAULT_LLM_MAX_TOKENS))

    if llm_provider.lower() == "openai":
        model_name = os.getenv("OPENAI_MODEL", DEFAULT_OPENAI_MODEL)
        return ChatOpenAI(
            api_key=api_key,
            model=model_name,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    elif llm_provider.lower() == "anthropic":
        model_name = os.getenv("ANTHROPIC_MODEL", DEFAULT_ANTHROPIC_MODEL)
        return ChatAnthropic(
            api_key=api_key,
            model_name=model_name,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    else:
        raise ValueError(f"Unsupported LLM provider: {llm_provider}")


def create_agent(
    llm_provider: str,
    api_key: str,
    loaded_docs: Optional[List[Document]] = None,
    template_data: Optional[Dict] = None,
    retriever: Optional[BaseRetriever] = None,
) -> PresentationAgent:
    """Creates the PresentationAgent with configured LLM, tools, and optional RAG retriever."""
    llm = get_llm_instance(llm_provider, api_key)

    if retriever is None and loaded_docs:
        try:
            openai_key = api_key if llm_provider.lower() == "openai" else os.getenv("OPENAI_API_KEY")
            rag_system = EnhancedRAG(
                docs=loaded_docs,
                cache_name="pptx_docs_context",
                openai_api_key=openai_key,
            )
            retriever = rag_system.get_retriever(k=5)
            if retriever:
                logger.info("RAG retriever successfully created.")
            else:
                logger.warning("RAG system initialized but failed to create a retriever.")
        except Exception as rag_setup_err:
            logger.error(f"Failed to initialize RAG system: {rag_setup_err}", exc_info=True)
            retriever = None
    else:
        logger.info("No documents provided for RAG context.")

    tools: List[BaseTool] = [
        BaseTool.from_function(
            func=partial(run_bullet_points_tool_with_llm, llm=llm, retriever=retriever),
            name="Bullet_Points_Generator",
            description=(
                create_bullet_points_tool.__doc__
                or "Generates a detailed, structured JSON presentation outline."
            ).strip(),
            args_schema=BulletPointInput,
        ),
        BaseTool.from_function(
            func=partial(
                run_code_generation_tool_with_llm,
                llm=llm,
                retriever=retriever,
                template_data=template_data or {},
            ),
            name="Code_Generator",
            description=(
                create_code_generation_tool.__doc__
                or "Generates runnable python-pptx code to create a presentation file."
            ).strip(),
            args_schema=GenerateCodeInput,
        ),
        BaseTool.from_function(
            func=partial(run_code_quality_check_tool_with_llm, llm=llm),
            name="Code_Quality_Checker",
            description=(
                create_code_quality_check_tool.__doc__
                or "Analyzes generated python-pptx code for safety and relevance."
            ).strip(),
            args_schema=CodeQualityCheckInput,
        ),
        BaseTool.from_function(
            func=partial(run_quality_check_tool_with_llm, llm=llm),
            name="Presentation_Quality_Checker",
            description=(
                create_quality_check_tool.__doc__
                or "Analyzes a presentation structure JSON for quality."
            ).strip(),
            args_schema=QualityCheckInput,
        ),
    ]

    return PresentationAgent(llm=llm, tools=tools, retriever=retriever)


def run_code_generation_tool_with_llm(
    tool_input: Dict[str, Any],
    llm: BaseChatModel,
    retriever: Optional[BaseRetriever],
    template_data: Dict,
) -> str:
    """Helper to run the code generation logic with injected dependencies."""
    try:
        merged_input = {**tool_input, "template_data": tool_input.get("template_data") or template_data}
        input_model = GenerateCodeInput(**merged_input)
        return create_code_generation_tool(input_model, llm, retriever)
    except Exception as e:
        logger.error(f"Error running Code_Generator tool logic: {e}", exc_info=True)
        return GeneratedCodeOutput(
            python_code=f"# Error generating code: {e}",
            output_filename="error.pptx",
        ).model_dump_json(indent=2)


def run_bullet_points_tool_with_llm(
    tool_input: Dict[str, Any],
    llm: BaseChatModel,
    retriever: Optional[BaseRetriever],
) -> str:
    """Helper to run the bullet points logic with injected LLM and Retriever."""
    try:
        validated_input = BulletPointInput(**tool_input)
        return create_bullet_points_tool(validated_input, llm, retriever)
    except Exception as e:
        logger.error(f"Error running Bullet_Points_Generator tool logic: {e}", exc_info=True)
        return f"Error executing Bullet_Points_Generator: Failed to generate structure - {e}"


def run_quality_check_tool_with_llm(tool_input: Dict[str, Any], llm: BaseChatModel) -> str:
    """Helper to run the quality check logic with injected LLM."""
    try:
        validated_input = QualityCheckInput(**tool_input)
        return create_quality_check_tool(validated_input, llm)
    except Exception as e:
        logger.error(f"Error running Presentation_Quality_Checker tool logic: {e}", exc_info=True)
        return f"Error executing Presentation_Quality_Checker: Failed to perform analysis - {e}"


def run_code_quality_check_tool_with_llm(tool_input: Dict[str, Any], llm: BaseChatModel) -> str:
    """Helper to run the code quality check logic with injected LLM."""
    try:
        validated_input = CodeQualityCheckInput(**tool_input)
        return create_code_quality_check_tool(validated_input, llm)
    except Exception as e:
        logger.error(f"Error running Code_Quality_Checker tool logic: {e}", exc_info=True)
        return CodeQualityAnalysisOutput(
            is_safe=False,
            warnings=[f"Failed to run code quality analysis tool: {e}"],
            assessment="Error during tool execution.",
        ).model_dump_json(indent=2)