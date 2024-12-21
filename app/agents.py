import json
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
    GeneratedCodeOutput
)
from log_config.logging_config import logger


class PresentationAgent:
    def __init__(self, llm: BaseChatModel, tools: List[BaseTool], retriever: Optional[BaseRetriever] = None):
        self.llm = llm
        self.tools = tools
        self.retriever = retriever
        self.system_prompt = """You are an expert presentation creation assistant using Python. You have two main ways to generate a presentation:

1.  **JSON Structure Path (Default):**
    *   Use the `Bullet_Points_Generator` tool to create a detailed JSON outline.
    *   This JSON structure will be used by *external code* to generate the actual .pptx file.
    *   Your final output for this path MUST be the raw JSON string produced by the tool. No extra text or markdown.

2.  **Direct Code Generation Path (Use if user requests 'code generation' or 'REPL method'):**
    *   Use the `Code_Generator` tool to generate runnable `python-pptx` code. This tool returns JSON containing the code and the target filename.
    *   Crucially, *after* getting the code from `Code_Generator`, you MUST use the `PythonREPLTool` to execute that Python code.
    *   The `PythonREPLTool` execution is the final step in this path. It will create the .pptx file as a side effect.
    *   Your final output for this path will be the output of the `PythonREPLTool` (e.g., confirmation of execution or an error).

**Tool Selection:**
- If the user input mentions generating "code", "python code", "script", or using the "REPL method", use the **Direct Code Generation Path** (Code_Generator -> PythonREPLTool).
- Otherwise, use the **JSON Structure Path** (Bullet_Points_Generator).

**Input Format:** The user input will specify the content, style, template name, and potentially the desired generation method.

**Example Interaction (Code Path):**
User: Create a presentation using the 'REPL method' from this text... [Text content] Style: Professional, Template: professional
Agent: (Thinking: User requested REPL method. I need Code_Generator, then PythonREPLTool.)
Agent -> Code_Generator (content="...", style="Professional", template_name="professional", template_data={...})
Tool <- (Returns JSON: {"python_code": "from pptx import Presentation\n...", "output_filename": "exports/generated_code_....pptx"})
Agent: (Thinking: Got the code and filename. Now execute it.)
Agent -> PythonREPLTool (code="from pptx import Presentation\n...")
Tool <- (Returns REPL output, e.g., "" or an error traceback. The file exports/generated_code_....pptx is created.)
Agent: (Thinking: REPL executed. The REPL output is the final answer for this path.)
Agent -> Final Answer: "" (or the REPL error)
"""
        self.prompt = ChatPromptTemplate.from_messages([
            SystemMessage(content=self.system_prompt),
            MessagesPlaceholder(variable_name="chat_history"),
            ("user", "{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad")
        ])
        # llm_with_tools = self.llm.bind_tools(self.tools)

        self.agent_runnable: Runnable = create_react_agent(
            model=self.llm,
            tools=self.tools,
            prompt=self.prompt,
        )
        logger.info(
            f"PresentationAgent initialized with LLM: {llm.__class__.__name__} and Tools: {[t.name for t in tools]}. RAG Retriever: {'Provided' if retriever else 'Not Provided'}")

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
                            the REPL output string (for 'code_execution'),
                            or an error message string.
                - 'generated_filename': The path to the created file (for 'code_execution'), if successful.
        """
        logger.info(
            f"Running PresentationAgent. Method: '{generation_method}', Style: '{style}', Template: '{template_name}'")

        agent_input_message = f"""
        Generate a presentation based on the following details.
        Chosen Generation Method: {generation_method} {'(Use Code_Generator -> PythonREPLTool)' if generation_method == 'code' else '(Use Bullet_Points_Generator)'}
        Presentation Style: {style}
        Visual Template Name: {template_name}
        Template Data (use this for styling): {json.dumps(template_data, indent=2)}

        Content:
        ---
        {user_input}
        ---
        """

        agent_response = None
        try:
            agent_input = {"input": agent_input_message, "chat_history": []}
            effective_config = config or RunnableConfig()
            agent_response = self.agent_runnable.invoke(agent_input, config=effective_config)

            final_output_content = None
            intermediate_steps = agent_response.get('intermediate_steps', [])

            if isinstance(agent_response, dict) and "output" in agent_response:
                final_output_content = agent_response["output"]
            elif isinstance(agent_response, dict) and "messages" in agent_response and isinstance(
                    agent_response["messages"], list) and agent_response["messages"]:
                last_message = agent_response["messages"][-1]
                if hasattr(last_message, 'content'):
                    final_output_content = last_message.content
                elif isinstance(last_message, str):
                    final_output_content = last_message

            if not final_output_content:
                final_output_content = str(agent_response)  # Fallback

            logger.debug(f"Agent final output content: {final_output_content}")
            logger.debug(f"Agent intermediate steps: {intermediate_steps}")

            if generation_method == 'json':
                cleaned_json_string = self._clean_json_output(final_output_content)
                try:
                    parsed_json = json.loads(cleaned_json_string)
                    if not isinstance(parsed_json, dict) or "slides" not in parsed_json:
                        raise ValueError("JSON output from agent is missing 'slides' key.")
                    logger.info("Successfully parsed agent's final output as JSON structure.")
                    return {"type": "json", "output": cleaned_json_string}
                except (json.JSONDecodeError, ValueError) as json_err:
                    logger.error(f"Failed to parse final output as JSON for the 'json' method: {json_err}")
                    logger.error(f"Agent raw output that failed parsing:\n{final_output_content}")
                    return {"type": "error", "output": f"Agent did not return valid JSON structure: {json_err}"}

            elif generation_method == 'code':
                generated_filename = None
                code_generator_output_json = None

                for step in reversed(intermediate_steps):
                    # React agent tuple: (AgentAction, observation)
                    if len(step) == 2 and hasattr(step[0], 'tool') and step[0].tool == 'Code_Generator':
                        code_generator_output_json = step[1]
                        logger.info(f"Found Code_Generator output in intermediate steps: {code_generator_output_json}")
                        break

                if code_generator_output_json:
                    try:
                        code_gen_data = json.loads(code_generator_output_json)
                        generated_filename = code_gen_data.get('output_filename')
                    except json.JSONDecodeError:
                        logger.error("Could not parse Code_Generator output JSON from intermediate steps.")
                        # Try regex fallback on the raw output string
                        match = re.search(r'"output_filename":\s*"([^"]+\.pptx)"', code_generator_output_json)
                        if match:
                            generated_filename = match.group(1)
                            logger.warning(f"Parsed filename using regex fallback: {generated_filename}")

                if not generated_filename:
                    logger.error("Could not determine the generated filename from the agent's execution.")
                    return {"type": "error",
                            "output": "Code generation finished, but couldn't determine the output filename."}

                if Path(generated_filename).exists():
                    logger.info(f"Code execution path successful. Confirmed file exists: {generated_filename}")
                    return {
                        "type": "code_execution",
                        "output": final_output_content,  # REPL output
                        "generated_filename": str(Path(generated_filename).absolute())  # Return absolute path
                    }
                else:
                    logger.error(
                        f"Code execution path finished, but expected file '{generated_filename}' was not found.")
                    return {
                        "type": "error",
                        "output": f"Code generation and REPL execution finished, but the expected output file '{generated_filename}' was not found. REPL Output: {final_output_content}",
                        "generated_filename": generated_filename
                    }
            else:
                logger.error(f"Unknown generation method: {generation_method}")
                return {"type": "error", "output": f"Internal error: Unknown generation method '{generation_method}'."}

        except Exception as e:
            logger.error(f"An unexpected error occurred during PresentationAgent execution: {e}", exc_info=True)
            return {"type": "error", "output": f"An unexpected error occurred in the agent: {e}"}

    def _clean_json_output(self, raw_output: str) -> str:
        """Cleans potential markdown code fences from JSON output."""
        if not isinstance(raw_output, str):
            return ""
        cleaned = raw_output.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:].strip()
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3].strip()
        elif cleaned.startswith("```"):
            cleaned = cleaned[3:].strip()
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3].strip()
        match = re.search(r'\{.*\}', cleaned, re.DOTALL)
        if match:
            potential_json = match.group(0)
            try:
                json.loads(potential_json)
                return potential_json
            except json.JSONDecodeError:
                pass
        return cleaned


def get_llm_instance(llm_provider: str, api_key: str) -> BaseChatModel:
    """Helper function to get LLM instance."""
    try:
        if llm_provider.lower() == "openai":
            return ChatOpenAI(api_key=api_key, model="gpt-4-turbo", temperature=0.1,
                              max_tokens=4096)
        elif llm_provider.lower() == "anthropic":
            return ChatAnthropic(api_key=api_key, model_name="claude-3-5-sonnet-20240620", temperature=0.1,
                                 max_tokens=4096)
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

    try:
        python_repl_tool = PythonREPLTool()
        python_repl_tool.description = (
            "Executes Python code. Use this ONLY to run the code generated by Code_Generator."
            "Input MUST be valid Python code string.")
        tools.append(python_repl_tool)
    except Exception as repl_err:
        logger.error(f"Failed to initialize PythonREPLTool: {repl_err}. Code generation path will likely fail.",
                     exc_info=True)

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
