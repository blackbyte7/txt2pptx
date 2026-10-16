import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import gradio as gr
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever

from app.agents import create_agent
from app.analyzers import ContentAnalyzer
from app.exporters import PresentationExporter
from app.rag import EnhancedRAG
from app.utils import ALLOWED_EXTENSIONS, generate_presentation, load_supported_documents
from log_config.logging_config import logger
from templates.templates import PresentationTemplates

JSON_METHOD = "JSON Structure + Generator"
CODE_METHOD = "Direct Code Generation (Isolated Subprocess)"


def create_interface(
    available_templates: List[Dict[str, str]],
    loaded_docs_for_rag: Optional[List[Document]] = None,
    default_openai_key: Optional[str] = None,
    default_anthropic_key: Optional[str] = None,
) -> gr.Blocks:
    """Creates the Gradio interface application."""

    template_manager = PresentationTemplates()
    exporter = PresentationExporter()
    analyzer = ContentAnalyzer()

    # Pre-initialize RAG retriever once at startup if OpenAI key and docs are available
    startup_retriever: Optional[BaseRetriever] = None
    if loaded_docs_for_rag and default_openai_key:
        try:
            rag_system = EnhancedRAG(
                docs=loaded_docs_for_rag,
                cache_name="pptx_docs_context",
                openai_api_key=default_openai_key,
            )
            startup_retriever = rag_system.get_retriever(k=5)
        except Exception as e:
            logger.warning(f"Could not initialize startup RAG retriever: {e}")

    template_choices = [(t.get("description", t["name"]), t["name"]) for t in available_templates]
    default_template_value = template_choices[0][1] if template_choices else None

    llm_provider_choices = ["OpenAI", "Anthropic"]
    default_llm_provider = (
        "OpenAI"
        if default_openai_key
        else ("Anthropic" if default_anthropic_key else "OpenAI")
    )

    def process_request(
        input_file_obj: Optional[Any],
        selected_style_desc: str,
        selected_template_name: str,
        selected_llm_provider: str,
        entered_api_key: Optional[str],
        generation_method_choice: str,
        export_formats: List[str],
        analyze_content_flag: bool,
        enable_rag_flag: bool,
        template_customization_json: Optional[str],
        progress: gr.Progress = gr.Progress(),
    ) -> Tuple[Optional[List[str]], Optional[str]]:
        progress(0, desc="Starting...")
        output_files_list: Optional[List[str]] = None
        analysis_results_str: Optional[str] = None
        generated_pptx_path: Optional[str] = None

        if not input_file_obj:
            gr.Warning("Please upload an input file.")
            return None, None

        input_file_path = (
            input_file_obj if isinstance(input_file_obj, str) else getattr(input_file_obj, "name", None)
        )
        if not isinstance(input_file_path, str):
            gr.Error("Could not read the uploaded file path.")
            return None, None

        if not selected_template_name:
            gr.Warning("Please select a presentation template.")
            return None, None

        clean_entered_key = entered_api_key.strip() if entered_api_key else None
        api_key_to_use = clean_entered_key or (
            default_openai_key if selected_llm_provider == "OpenAI" else default_anthropic_key
        )
        if not api_key_to_use:
            gr.Error(f"API Key for {selected_llm_provider} is required!")
            return None, None

        final_template_data = template_manager.get_template(selected_template_name)
        if not final_template_data:
            gr.Error(f"Selected template '{selected_template_name}' not found.")
            return None, None

        if template_customization_json and template_customization_json.strip():
            try:
                custom_data = json.loads(template_customization_json)
                if isinstance(custom_data, dict) and custom_data:
                    customized_template = template_manager.customize_template(
                        selected_template_name, custom_data
                    )
                    if customized_template:
                        final_template_data = customized_template
            except json.JSONDecodeError as json_err:
                gr.Warning(f"Invalid JSON in Template Customization: {json_err}. Using base template.")

        active_retriever = startup_retriever if enable_rag_flag else None
        docs_for_agent = loaded_docs_for_rag if (enable_rag_flag and not active_retriever) else None

        try:
            progress(0.1, desc="Initializing AI Agent...")
            agent = create_agent(
                selected_llm_provider,
                api_key_to_use,
                loaded_docs=docs_for_agent,
                template_data=final_template_data,
                retriever=active_retriever,
            )
        except Exception as e:
            logger.error(f"Failed to create agent: {e}", exc_info=True)
            gr.Error(f"Failed to initialize AI Agent: {e}")
            return None, None

        try:
            progress(0.2, desc="Loading input file content...")
            docs = load_supported_documents(input_file_path)
            full_content = "\n\n".join(
                doc.page_content for doc in docs if doc.page_content and doc.page_content.strip()
            )
            if not full_content:
                gr.Error("Input file is empty or text could not be extracted.")
                return None, None
        except Exception as e:
            logger.error(f"Error loading input file {input_file_path}: {e}", exc_info=True)
            gr.Error(f"Error loading input file: {e}")
            return None, None

        try:
            progress(0.4, desc="AI Processing & Generating...")
            agent_result = agent.run(
                user_input=full_content,
                style=selected_style_desc,
                template_name=selected_template_name,
                template_data=final_template_data,
                generation_method="code" if generation_method_choice == CODE_METHOD else "json",
            )

            logger.debug(f"Agent run result: {agent_result}")

            if agent_result.get("type") == "error":
                raise RuntimeError(agent_result.get("output", "Unknown agent error"))

            if agent_result.get("type") == "json":
                presentation_structure_json = json.loads(agent_result["output"])
                presentation_structure_json["template_info"] = final_template_data

                if analyze_content_flag:
                    progress(0.6, desc="Analyzing Content Structure...")
                    analysis_results = analyzer.analyze_presentation_structure(
                        presentation_structure_json
                    )
                    if analysis_results["suggestions"] or analysis_results["warnings"]:
                        parts = ["Content Analysis:"]
                        if analysis_results["warnings"]:
                            parts.append("\nWarnings:\n- " + "\n- ".join(analysis_results["warnings"]))
                        if analysis_results["suggestions"]:
                            parts.append(
                                "\nSuggestions:\n- " + "\n- ".join(analysis_results["suggestions"])
                            )
                        analysis_results_str = "\n".join(parts)
                    else:
                        analysis_results_str = "Content Analysis:\nNo major issues or suggestions found."

                progress(0.7, desc="Generating PowerPoint from JSON...")
                generated_pptx_path = generate_presentation(
                    presentation_structure_json=presentation_structure_json,
                    output_filename_base=Path(input_file_path).stem,
                )
                if not generated_pptx_path or not Path(generated_pptx_path).exists():
                    raise RuntimeError("PPTX generation from JSON failed.")

            elif agent_result.get("type") == "code_execution":
                logger.info("Agent completed code generation and REPL execution.")
                generated_pptx_path = agent_result.get("generated_filename")
                if not generated_pptx_path or not Path(generated_pptx_path).exists():
                    raise RuntimeError("Code execution finished, but output PPTX file was not found.")
                analysis_results_str = "Content Analysis:\nN/A for Direct Code Generation method."

        except Exception as e:
            logger.error(f"Error during presentation generation pipeline: {e}", exc_info=True)
            gr.Error(f"Generation Failed: {e}")
            return output_files_list, analysis_results_str

        output_files_list = []
        if generated_pptx_path and Path(generated_pptx_path).exists():
            output_files_list.append(generated_pptx_path)
            if export_formats:
                progress(0.85, desc="Exporting additional formats...")
                export_results = exporter.export_presentation(
                    pptx_path=generated_pptx_path,
                    formats=export_formats,
                    output_name=Path(generated_pptx_path).stem,
                )
                for fmt, result in export_results.get("exports", {}).items():
                    if isinstance(result, str) and Path(result).exists():
                        output_files_list.append(result)
                    elif isinstance(result, list):
                        output_files_list.extend(
                            p for p in result if isinstance(p, str) and Path(p).exists()
                        )
                    else:
                        gr.Warning(f"Export to {fmt} failed: {result}")

        progress(1.0, desc="Done!")
        return output_files_list or None, analysis_results_str

    with gr.Blocks(theme=gr.themes.Soft(), title="txt2pptx AI") as iface:
        gr.Markdown(
            "# txt2pptx: AI Text-to-PowerPoint Converter\n"
            "Upload a document, choose options, and generate a PowerPoint presentation."
        )

        with gr.Row():
            with gr.Column(scale=2):
                input_file = gr.File(
                    label="1. Upload Document",
                    file_types=list(ALLOWED_EXTENSIONS),
                )
                generation_method = gr.Radio(
                    choices=[JSON_METHOD, CODE_METHOD],
                    label="2. Generation Method",
                    value=JSON_METHOD,
                )
                style_desc = gr.Dropdown(
                    choices=[
                        "Default",
                        "Professional",
                        "Creative",
                        "Minimalist",
                        "Academic",
                        "Technical",
                        "Playful",
                    ],
                    label="3. Choose Content Style",
                    value="Default",
                )
                template = gr.Dropdown(
                    choices=template_choices,
                    label="4. Select Visual Template",
                    value=default_template_value,
                )
                llm_provider = gr.Dropdown(
                    choices=llm_provider_choices,
                    label="5. Select AI Provider",
                    value=default_llm_provider,
                )
                api_key_input = gr.Textbox(
                    label=f"6. {default_llm_provider} API Key (Optional)",
                    interactive=True,
                    type="password",
                    placeholder="Enter API Key if not set in environment",
                )
                llm_provider.change(
                    lambda p: gr.update(label=f"6. {p} API Key (Optional)"),
                    inputs=llm_provider,
                    outputs=api_key_input,
                )
                submit_button = gr.Button("Generate Presentation", variant="primary")

            with gr.Column(scale=3):
                output_files = gr.Files(label="Generated Files", interactive=False)
                analysis_output = gr.Textbox(
                    label="Content Analysis Results",
                    lines=8,
                    interactive=False,
                )

                with gr.Accordion("Advanced Options & Settings", open=False):
                    with gr.Row():
                        analyze_content = gr.Checkbox(
                            label="Analyze Content (JSON Method)",
                            value=True,
                        )
                        enable_rag = gr.Checkbox(
                            label="Enhance with RAG Context",
                            value=True,
                        )
                    export_formats = gr.CheckboxGroup(
                        choices=[
                            ("PDF", "pdf"),
                            ("HTML (Basic)", "html"),
                            ("Images (PNG)", "images"),
                        ],
                        label="Additional Export Formats",
                        value=[],
                    )
                    template_customization = gr.Code(
                        label="Template Customization (JSON)",
                        language="json",
                        value="",
                        lines=6,
                        interactive=True,
                    )

        submit_button.click(
            fn=process_request,
            inputs=[
                input_file,
                style_desc,
                template,
                llm_provider,
                api_key_input,
                generation_method,
                export_formats,
                analyze_content,
                enable_rag,
                template_customization,
            ],
            outputs=[output_files, analysis_output],
        )

    return iface


def launch_interface(
    available_templates: List[Dict[str, str]],
    loaded_docs_for_rag: Optional[List[Document]] = None,
    default_openai_key: Optional[str] = None,
    default_anthropic_key: Optional[str] = None,
):
    """Creates and launches the Gradio interface."""
    logger.info("Creating Gradio UI instance.")
    try:
        iface = create_interface(
            available_templates,
            loaded_docs_for_rag,
            default_openai_key,
            default_anthropic_key,
        )
        server_name = os.getenv("GRADIO_SERVER_NAME", "0.0.0.0")
        server_port = int(os.getenv("GRADIO_SERVER_PORT", "7860"))
        iface.launch(server_name=server_name, server_port=server_port)
    except Exception as e:
        logger.critical(f"Failed to launch Gradio interface: {e}", exc_info=True)
        print(f"\nFATAL ERROR launching UI: {e}\n", file=sys.stderr)
        raise
