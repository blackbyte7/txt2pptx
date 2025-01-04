import json
import os
import re
from functools import partial
from pathlib import Path
from typing import Dict, Any, List, Callable, Optional
from langchain_anthropic import ChatAnthropic
from langchain_core.documents import Document
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import SystemMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.retrievers import BaseRetriever
from langchain_core.runnables import RunnableConfig, Runnable
from langchain_core.tools import BaseTool
from langchain_experimental.tools import PythonREPLTool
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent
from app.rag import EnhancedRAG
from app.tools import (
    create_bullet_points_tool,
    create_quality_check_tool,
    create_code_generation_tool,
    BulletPointInput,
    QualityCheckInput,
    GenerateCodeInput,
    GeneratedCodeOutput, create_code_quality_check_tool, CodeQualityAnalysisOutput, CodeQualityCheckInput
)
from log_config.logging_config import logger

DEFAULT_OPENAI_MODEL = "gpt-4-turbo"
DEFAULT_ANTHROPIC_MODEL = "claude-3-5-sonnet-20240620"
DEFAULT_LLM_TEMPERATURE = 0.1
DEFAULT_LLM_MAX_TOKENS = 4096


class PresentationAgent:
    def __init__(self, llm: BaseChatModel, tools: List[BaseTool], retriever: Optional[BaseRetriever] = None):
        """
        Initializes the PresentationAgent.

        Args:
            llm (BaseChatModel): The language model instance.
            tools (List[BaseTool]): The list of tools available to the agent.
            retriever (Optional[BaseRetriever]): The retriever for RAG context, if available.
        """
        self.llm = llm
        self.tools = tools
        self.retriever = retriever
        self.system_prompt = """You are an expert presentation creation assistant using Python. You have two main ways to generate a presentation:

    1.  **JSON Structure Path (Default):**
        *   Use the `Bullet_Points_Generator` tool to create a detailed JSON outline.
        *   Optionally use `Presentation_Quality_Checker` on the JSON if needed.
        *   This JSON structure will be used by *external code* to generate the actual .pptx file.
        *   Your final output for this path MUST be the raw JSON string produced by `Bullet_Points_Generator`. No extra text or markdown.

    2.  **Direct Code Generation Path (Use if user requests 'code generation' or 'REPL method'):**
        *   **Step 1:** Use the `Code_Generator` tool to generate runnable `python-pptx` code. This tool returns JSON containing the code and the target filename.
        *   **Step 2:** Use the `Code_Quality_Checker` tool to analyze the Python code generated in Step 1. Pass the 'python_code' string to it.
        *   **Step 3:** ONLY IF the `Code_Quality_Checker` output indicates the code is safe (`is_safe: true`), proceed to use the `PythonREPLTool` to execute that *exact* Python code.
        *   The `PythonREPLTool` execution is the final step in this path if the code is safe. It creates the .pptx file as a side effect.
        *   Your final output for this path will be the output of the `PythonREPLTool` (e.g., confirmation or error) if executed, OR the analysis result from `Code_Quality_Checker` if the code was deemed unsafe.

    **Tool Selection:**
    - If the user input mentions generating "code", "python code", "script", or using the "REPL method", use the **Direct Code Generation Path** (`Code_Generator` -> `Code_Quality_Checker` -> conditionally `PythonREPLTool`).
    - Otherwise, use the **JSON Structure Path** (`Bullet_Points_Generator`).

    **Input Format:** The user input will specify the content, style, template name, and potentially the desired generation method.

    **Example Interaction (Code Path - Safe Code):**
    User: Create a presentation using the 'REPL method' from this text... Style: Professional, Template: professional
    Agent: (Thinking: User requested REPL method. Need Code_Generator -> Code_Quality_Checker -> PythonREPLTool.)
    Agent -> Code_Generator (content="...", style="Professional", template_name="professional", template_data={...})
    Tool <- (Returns JSON: {"python_code": "from pptx import Presentation...", "output_filename": "exports/file.pptx"})
    Agent: (Thinking: Got code. Now check its quality.)
    Agent -> Code_Quality_Checker (python_code="from pptx import Presentation...")
    Tool <- (Returns JSON: {"is_safe": true, "warnings": [], "assessment": "Code looks safe."})
    Agent: (Thinking: Code is safe. Now execute it.)
    Agent -> PythonREPLTool (code="from pptx import Presentation...")
    Tool <- (Returns REPL output, e.g., "" or error. File exports/file.pptx is created.)
    Agent: (Thinking: REPL executed. The REPL output is the final answer.)
    Agent -> Final Answer: "" (or the REPL error)

    **Example Interaction (Code Path - Unsafe Code):**
    ...
    Agent -> Code_Quality_Checker (python_code="import requests; requests.get(...)")
    Tool <- (Returns JSON: {"is_safe": false, "warnings": ["Imports suspicious library 'requests'"], "assessment": "Code appears unsafe."})
    Agent: (Thinking: Code is unsafe. Stop here and report the findings.)
    Agent -> Final Answer: {"is_safe": false, "warnings": ["Imports suspicious library 'requests'"], "assessment": "Code appears unsafe."}
    """
        self.prompt = ChatPromptTemplate.from_messages([
            SystemMessage(content=self.system_prompt),
            MessagesPlaceholder(variable_name="chat_history"),
            ("user", "{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad")
        ])

        self.agent_runnable: Runnable = create_react_agent(
            model=self.llm,
            tools=self.tools,
            prompt=self.prompt,
        )
        logger.info(
            f"PresentationAgent initialized with LLM: {llm.__class__.__name__} and Tools: {[t.name for t in tools]}. "
            f"RAG Retriever: {'Provided' if retriever else 'Not Provided'}")

    def run(self,
            user_input: str,
            style: str,
            template_name: str,
            template_data: Dict[str, Any],
            generation_method: str,
            config: Optional[RunnableConfig] = None
            ) -> Dict[str, Any]:
        """
        Executes the presentation creation process using the chosen method.

        Args:
            user_input (str): Raw text content.
            style (str): Conceptual style.
            template_name (str): Specific template name.
            template_data (Dict): The actual template data dictionary.
            generation_method (str): 'json' or 'code'.
            config (Optional[RunnableConfig]): Langchain config.

        Returns:
            Dict[str, Any]: A dictionary containing:
                - 'type': 'json' or 'code_execution' or 'error'
                - 'output': The JSON structure string (for 'json'),
                            the REPL output string or quality check result (for 'code'),
                            or an error message string.
                - 'generated_filename': The path to the created file (for 'code_execution'), if successful.
        """
        logger.info(
            f"Running PresentationAgent. Method: '{generation_method}', Style: '{style}', Template: '{template_name}'")

        agent_input_message = f"""
        Generate a presentation based on the following details.
        Chosen Generation Method: {generation_method} {'(Use Code_Generator -> Code_Quality_Checker -> PythonREPLTool)' if generation_method == 'code' else '(Use Bullet_Points_Generator)'}
        Presentation Style: {style}
        Visual Template Name: {template_name}
        Template Data (use this for styling): {json.dumps(template_data, indent=2)}

        Content:
        ---
        {user_input}
        ---
        Follow the instructions precisely based on the chosen generation method. For the 'code' path, ensure you execute the Code_Quality_Checker step *before* the PythonREPLTool. Only execute the REPL if the code is safe.
        """

        agent_response = None
        try:
            agent_input = {"input": agent_input_message, "chat_history": []}
            effective_config = config or RunnableConfig()
            logger.debug(f"Invoking agent runnable with input: {json.dumps(agent_input, indent=2)[:1000]}...")
            agent_response = self.agent_runnable.invoke(agent_input, config=effective_config)

            final_output_content = None
            intermediate_steps = agent_response.get('intermediate_steps', [])
            if not intermediate_steps and generation_method == 'code':
                logger.warning(
                    "Agent response for 'code' path did not contain 'intermediate_steps'. Cannot verify process.")
                final_output_content = agent_response.get("output", str(agent_response))
                return {"type": "error",
                        "output": f"Agent execution incomplete or failed early (no intermediate steps found). Final output: {final_output_content}"}

            if isinstance(agent_response, dict) and "output" in agent_response:
                final_output_content = agent_response["output"]
            elif isinstance(agent_response, dict) and "messages" in agent_response and isinstance(
                    agent_response["messages"], list) and agent_response["messages"]:
                last_message = agent_response["messages"][-1]
                if hasattr(last_message, 'content'):
                    final_output_content = last_message.content
                elif isinstance(last_message, str):
                    final_output_content = last_message
            elif isinstance(agent_response, str):
                final_output_content = agent_response

            if not final_output_content:
                final_output_content = str(agent_response)

            logger.debug(f"Agent final output content: {final_output_content}")
            log_intermediate = [
                (step[0].tool, step[1][:100] + '...' if isinstance(step[1], str) and len(step[1]) > 100 else step[1])
                for step in intermediate_steps if len(step) == 2 and hasattr(step[0], 'tool')]
            logger.debug(f"Agent intermediate tool calls (summary): {log_intermediate}")

            if generation_method == 'json':
                logger.info("Processing 'json' generation path...")
                cleaned_json_string = self._clean_json_output(final_output_content)
                try:
                    parsed_json = json.loads(cleaned_json_string)
                    if not isinstance(parsed_json, dict) or "slides" not in parsed_json:
                        raise ValueError("JSON output from agent is missing 'slides' key or is not a dictionary.")
                    logger.info("Successfully parsed agent's final output as JSON structure.")
                    return {"type": "json", "output": cleaned_json_string}
                except (json.JSONDecodeError, ValueError) as json_err:
                    logger.error(f"Failed to parse final output as JSON for the 'json' method: {json_err}")
                    logger.error(f"Agent raw output that failed parsing:\n{final_output_content}")
                    return {"type": "error", "output": f"Agent did not return valid JSON structure: {json_err}"}

            elif generation_method == 'code':
                logger.info("Processing 'code' generation path...")
                generated_code: Optional[str] = None
                generated_filename: Optional[str] = None
                quality_check_result: Optional[Dict] = None
                repl_output: Optional[str] = None

                code_generator_output_json = None
                for step in reversed(intermediate_steps):
                    if len(step) == 2 and hasattr(step[0], 'tool') and step[0].tool == 'Code_Generator':
                        code_generator_output_json = step[1]
                        logger.info(f"Found Code_Generator output observation in intermediate steps.")
                        break

                if not code_generator_output_json:
                    logger.error("Code_Generator tool output not found in intermediate steps.")
                    return {"type": "error", "output": "Agent failed to use the Code_Generator tool."}

                try:
                    code_gen_data = json.loads(code_generator_output_json)
                    GeneratedCodeOutput(**code_gen_data)
                    generated_code = code_gen_data.get('python_code')
                    generated_filename = code_gen_data.get('output_filename')
                    if not generated_code or not generated_filename:
                        raise ValueError("Code_Generator output JSON missing 'python_code' or 'output_filename'.")
                    logger.info(f"Successfully parsed Code_Generator output. Expected Filename: {generated_filename}")
                except (json.JSONDecodeError, ValueError, Exception) as parse_err:
                    logger.error(f"Could not parse or validate Code_Generator output JSON: {parse_err}", exc_info=True)
                    logger.debug(f"Code Generator Raw Output: {code_generator_output_json}")
                    return {"type": "error",
                            "output": f"Failed to parse or validate code generator output: {parse_err}"}

                code_quality_output_json = None
                for step in reversed(intermediate_steps):
                    if len(step) == 2 and hasattr(step[0], 'tool') and step[0].tool == 'Code_Quality_Checker':
                        code_quality_output_json = step[1]
                        logger.info(f"Found Code_Quality_Checker output observation in intermediate steps.")
                        break

                if not code_quality_output_json:
                    logger.error(
                        "Code_Quality_Checker tool output not found in intermediate steps after Code_Generator.")
                    return {"type": "error",
                            "output": "Agent failed to use the Code_Quality_Checker tool after generating code."}

                try:
                    quality_check_data = json.loads(code_quality_output_json)
                    CodeQualityAnalysisOutput(**quality_check_data)
                    quality_check_result = quality_check_data
                    logger.info(
                        f"Successfully parsed Code_Quality_Checker output. Safe: {quality_check_result.get('is_safe')}, Assessment: {quality_check_result.get('assessment')}")
                except (json.JSONDecodeError, ValueError, Exception) as parse_err:
                    logger.error(f"Could not parse or validate Code_Quality_Checker output JSON: {parse_err}",
                                 exc_info=True)
                    logger.debug(f"Code Quality Raw Output: {code_quality_output_json}")
                    return {"type": "error",
                            "output": f"Failed to parse or validate code quality checker output: {parse_err}"}

                if not quality_check_result.get('is_safe'):
                    logger.warning(
                        f"Code quality check deemed code unsafe. Warnings: {quality_check_result.get('warnings')}")
                    return {
                        "type": "error",
                        "output": f"Generated code deemed unsafe or irrelevant by Code Quality Check.\nAssessment:"
                                  f" {quality_check_result.get('assessment', 'N/A')}\nWarnings: {'; '.join(quality_check_result.get('warnings', []))}"
                    }

                logger.info("Code quality check passed. Verifying REPL execution and file existence.")

                repl_executed = False
                qc_step_index = -1
                for idx, step in enumerate(intermediate_steps):
                    if len(step) == 2 and hasattr(step[0], 'tool') and step[0].tool == 'Code_Quality_Checker':
                        qc_step_index = idx
                        break

                if qc_step_index != -1:
                    for step in intermediate_steps[qc_step_index + 1:]:
                        if len(step) == 2 and hasattr(step[0], 'tool') and step[0].tool == 'PythonREPLTool':
                            repl_executed = True
                            repl_output = step[1]
                            logger.info("PythonREPLTool execution step found after quality check.")
                            break

                if not repl_executed:
                    logger.warning(
                        "PythonREPLTool execution step not found in intermediate steps after safety check. "
                        "Assuming final agent output might be REPL output.")
                    repl_output = final_output_content

                generated_filename_path = Path(generated_filename)
                if generated_filename_path.exists():
                    logger.info(f"Code execution path successful. Confirmed file exists: '{generated_filename}'")
                    return {
                        "type": "code_execution",
                        "output": repl_output if repl_output is not None else "(REPL Output not captured)",
                        "generated_filename": str(generated_filename_path.absolute())
                    }
                else:
                    logger.error(
                        f"REPL execution seems to have finished (or was attempted), but expected file '{generated_filename}' was not found.")
                    return {
                        "type": "error",
                        "output": f"Code execution and REPL step finished, but the expected output file "
                                  f"'{generated_filename_path.name}' was not found in '{generated_filename_path.parent}'. "
                                  f"Check REPL Output below (if available) and logs for errors during execution."
                                  f"\n\nREPL Output:\n{repl_output if repl_output is not None else '(Not Available)'}",
                        "generated_filename": generated_filename
                    }

            else:
                logger.error(f"Unknown generation method specified: {generation_method}")
                return {"type": "error", "output": f"Internal error: Unknown generation method '{generation_method}'."}

        except Exception as e:
            logger.error(f"An unexpected error occurred during PresentationAgent execution: {e}", exc_info=True)
            return {"type": "error", "output": f"An unexpected error occurred in the agent: {e}"}

    def _clean_json_output(self, raw_output: str) -> str:
        """Cleans potential markdown code fences from JSON output."""
        if not isinstance(raw_output, str):
            logger.warning(f"Received non-string output to clean: {type(raw_output)}. Returning empty string.")
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

        first_brace = cleaned.find('{')
        last_brace = cleaned.rfind('}')

        if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
            potential_json = cleaned[first_brace:last_brace + 1]
            try:
                json.loads(potential_json)
                logger.debug("Successfully extracted JSON content using brace finding.")
                return potential_json
            except json.JSONDecodeError:
                logger.warning("Brace finding resulted in invalid JSON. Returning original cleaned string.")
                return cleaned
        else:
            logger.debug("Could not find surrounding braces, returning original cleaned string.")
            return cleaned


def get_llm_instance(llm_provider: str, api_key: str) -> BaseChatModel:
    """Helper function to get LLM instance using environment variables or defaults."""
    try:
        temperature = float(os.getenv('LLM_TEMPERATURE', DEFAULT_LLM_TEMPERATURE))
        max_tokens = int(os.getenv('LLM_MAX_TOKENS', DEFAULT_LLM_MAX_TOKENS))

        if llm_provider.lower() == "openai":
            model_name = os.getenv('OPENAI_MODEL', DEFAULT_OPENAI_MODEL)
            logger.info(f"Initializing OpenAI LLM: model={model_name}, temp={temperature}, max_tokens={max_tokens}")
            return ChatOpenAI(
                api_key=api_key,
                model=model_name,
                temperature=temperature,
                max_tokens=max_tokens
            )
        elif llm_provider.lower() == "anthropic":
            model_name = os.getenv('ANTHROPIC_MODEL', DEFAULT_ANTHROPIC_MODEL)
            logger.info(f"Initializing Anthropic LLM: model={model_name}, temp={temperature}, max_tokens={max_tokens}")
            return ChatAnthropic(
                api_key=api_key,
                model_name=model_name,
                temperature=temperature,
                max_tokens=max_tokens
            )
        else:
            raise ValueError(f"Unsupported LLM provider: {llm_provider}")
    except Exception as e:
        logger.error(f"Failed to initialize LLM for provider {llm_provider}: {e}")
        raise


def create_agent(llm_provider: str,
                 api_key: str,
                 loaded_docs: Optional[List[Document]] = None,
                 template_data: Optional[Dict] = None,
                 ) -> PresentationAgent:
    """
    Creates the PresentationAgent with configured LLM and tools, optionally setting up RAG.

    Args:
        llm_provider (str): "OpenAI" or "Anthropic".
        api_key (str): The API key for the chosen provider.
        loaded_docs (Optional[List[Document]]): Pre-loaded documents for RAG context.
        template_data (Optional[Dict]): Default template data (used by Code_Generator).

    Returns:
        PresentationAgent: The initialized agent instance.
    """
    llm = get_llm_instance(llm_provider, api_key)

    retriever: Optional[BaseRetriever] = None
    if loaded_docs:
        try:
            logger.info(f"Initializing RAG system with {len(loaded_docs)} documents.")
            rag_system = EnhancedRAG(docs=loaded_docs, cache_name="pptx_docs_context")
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

    tools: List[BaseTool] = []

    # Tool 1: Bullet Points Generator (JSON Structure Path)
    bullet_points_tool_func: Callable[[Dict], str] = partial(
        run_bullet_points_tool_with_llm, llm=llm, retriever=retriever
    )
    bullet_points_tool_description = (create_bullet_points_tool.__doc__ or
                                      "Generates a detailed, structured JSON presentation outline.")
    tools.append(BaseTool.from_function(
        func=bullet_points_tool_func,
        name="Bullet_Points_Generator",
        description=bullet_points_tool_description.strip(),
        args_schema=BulletPointInput
    ))

    # Tool 2: Code Generator (Code Path - Step 1)
    code_generation_tool_func: Callable[[Dict], str] = partial(
        run_code_generation_tool_with_llm, llm=llm, retriever=retriever, template_data=template_data or {}
    )
    code_generation_tool_description = (create_code_generation_tool.__doc__ or
                                        "Generates runnable python-pptx code to create a presentation file.")
    tools.append(BaseTool.from_function(
        func=code_generation_tool_func,
        name="Code_Generator",
        description=code_generation_tool_description.strip(),
        args_schema=GenerateCodeInput
    ))

    # Tool 3: Code Quality Checker (Code Path - Step 2)
    code_quality_tool_func: Callable[[Dict], str] = partial(
        run_code_quality_check_tool_with_llm, llm=llm
    )
    code_quality_tool_description = (create_code_quality_check_tool.__doc__ or
                                     "Analyzes generated python-pptx code for safety and relevance.")
    tools.append(BaseTool.from_function(
        func=code_quality_tool_func,
        name="Code_Quality_Checker",
        description=code_quality_tool_description.strip(),
        args_schema=CodeQualityCheckInput
    ))

    # Tool 4: Python REPL (Code Path - Step 3)
    try:
        python_repl_tool = PythonREPLTool()
        python_repl_tool.description = (
            "Executes Python code. Use this ONLY to run the code generated by Code_Generator and *after* it has been verified by Code_Quality_Checker."
            "Input MUST be a valid Python code string.")
        tools.append(python_repl_tool)
    except Exception as repl_err:
        logger.error(f"Failed to initialize PythonREPLTool: {repl_err}. Code generation path will likely fail.",
                     exc_info=True)

    # Tool 5: Presentation Quality Checker (JSON Path - Optional)
    quality_check_tool_func: Callable[[Dict], str] = partial(
        run_quality_check_tool_with_llm, llm=llm
    )
    quality_check_tool_description = (create_quality_check_tool.__doc__ or
                                      "Analyzes a presentation structure JSON for quality.")
    tools.append(BaseTool.from_function(
        func=quality_check_tool_func,
        name="Presentation_Quality_Checker",
        description=quality_check_tool_description.strip(),
        args_schema=QualityCheckInput
    ))

    return PresentationAgent(llm=llm, tools=tools, retriever=retriever)


def run_code_generation_tool_with_llm(tool_input: Dict[str, Any], llm: BaseChatModel,
                                      retriever: Optional[BaseRetriever], template_data: Dict) -> str:
    """Helper to run the code generation logic with injected dependencies."""
    try:
        input_model = GenerateCodeInput(**tool_input, template_data=template_data)
        return create_code_generation_tool(input_model, llm, retriever)
    except Exception as e:
        logger.error(f"Error running Code_Generator tool logic: {e}", exc_info=True)
        error_output = GeneratedCodeOutput(
            python_code=f"# Error generating code: {e}",
            output_filename="error.pptx"
        ).json(indent=2)
        return error_output


def run_bullet_points_tool_with_llm(tool_input: Dict[str, Any], llm: BaseChatModel,
                                    retriever: Optional[BaseRetriever]) -> str:
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
        if not isinstance(validated_input.presentation_structure, dict):
            return "Error executing Presentation_Quality_Checker: Input 'presentation_structure' must be a valid JSON object/dictionary."
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
        error_output = CodeQualityAnalysisOutput(
            is_safe=False,
            warnings=[f"Failed to run code quality analysis tool: {e}"],
            assessment="Error during tool execution."
        ).json(indent=2)
        return error_output
