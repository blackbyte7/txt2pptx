import json
import sys
import traceback
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Any

import gradio as gr
from langchain_core.documents import Document

from app.agents import create_agent, PresentationAgent
from app.analyzers import ContentAnalyzer
from app.exporters import PresentationExporter
from app.utils import generate_presentation, load_supported_documents, ALLOWED_EXTENSIONS
from log_config.logging_config import logger
from templates.templates import PresentationTemplates

JSON_METHOD = "JSON Structure + Generator"
CODE_METHOD = "Direct Code Generation (REPL)"


def create_interface(
        available_templates: List[Dict[str, str]],
        loaded_docs_for_rag: Optional[List[Document]] = None,
        default_openai_key: Optional[str] = None,
        default_anthropic_key: Optional[str] = None
) -> gr.Blocks:
    """Creates the Gradio interface application."""

    template_manager = PresentationTemplates()
    exporter = PresentationExporter()
    analyzer = ContentAnalyzer()

    template_choices = [(t.get('description', t['name']), t['name']) for t in available_templates]
    default_template_value = template_choices[0][1] if template_choices else None

    llm_provider_choices = ["OpenAI", "Anthropic"]
    default_llm_provider = "OpenAI" if default_openai_key else ("Anthropic" if default_anthropic_key else "OpenAI")

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
            progress: gr.Progress
    ) -> Tuple[Optional[List[str]], Optional[str]]:
        """
        Handles the Gradio button click event for presentation generation.
        """
        progress(0, desc="▶️ Starting...")
        logger.info(f"Received request via Gradio UI. Method: '{generation_method_choice}'")
        output_files_list: Optional[List[str]] = None
        analysis_results_str: Optional[str] = None
        generated_pptx_path: Optional[str] = None

        if not input_file_obj:
            gr.Warning("⚠️ Please upload an input file.")
            return None, None
        try:
            input_file_path = input_file_obj.name
            if not isinstance(input_file_path, str): raise AttributeError("File path not string.")
            logger.info(f"Input file path: {input_file_path}")
        except Exception as e:
            logger.error(f"Failed to get file path: {e}, object: {input_file_obj}")
            gr.Error("🛑 Could not read the uploaded file object.")
            return None, None

        if not selected_template_name:
            gr.Warning("⚠️ Please select a presentation template.")
            return None, None
        api_key_to_use = entered_api_key or (
            default_openai_key if selected_llm_provider == "OpenAI" else default_anthropic_key)
        if not api_key_to_use:
            gr.Error(f"🛑 API Key for {selected_llm_provider} required!")
            return None, None

        final_template_data = template_manager.get_template(selected_template_name)
        if not final_template_data:
            gr.Error(f"🛑 Selected template '{selected_template_name}' not found.")
            return None, None
        if template_customization_json and template_customization_json.strip():
            try:
                custom_data = json.loads(template_customization_json)
                if isinstance(custom_data, dict) and custom_data:
                    logger.info("Applying template customization...")
                    customized_template = template_manager.customize_template(selected_template_name, custom_data)
                    if customized_template:
                        final_template_data = customized_template
                        gr.Info("ℹ️ Applied template customizations.")
                    else:
                        gr.Warning("⚠️ Failed to apply template customization. Using base template.")
                elif custom_data:
                    gr.Warning("⚠️ Template customization JSON is invalid or empty. Ignoring.")
            except json.JSONDecodeError as json_err:
                logger.warning(f"Invalid JSON in Template Customization: {json_err}. Ignoring customization.")
                gr.Warning(f"⚠️ Invalid JSON format in Template Customization: {json_err}. Ignoring customization.")
            except Exception as e:
                logger.error(f"Error applying template customization: {e}", exc_info=True)
                gr.Warning(f"⚠️ Error applying customization: {e}. Using base template.")

        docs_for_agent = loaded_docs_for_rag if enable_rag_flag else None
        if enable_rag_flag and not loaded_docs_for_rag:
            gr.Info("ℹ️ RAG enabled, but no documentation was loaded at startup.")

        agent: Optional[PresentationAgent] = None
        try:
            progress(0.1, desc="🧠 Initializing AI Agent...")
            logger.debug(f"Creating agent for method '{generation_method_choice}'...")
            agent = create_agent(selected_llm_provider, api_key_to_use, loaded_docs=docs_for_agent,
                                 template_data=final_template_data)
            if not agent: raise RuntimeError("create_agent returned None")
        except Exception as e:
            logger.error(f"Failed to create agent: {e}", exc_info=True)
            gr.Error(f"🛑 Failed to initialize AI Agent: {e}")
            return None, None

        full_content: Optional[str] = None
        try:
            progress(0.2, desc="📄 Loading input file content...")
            docs = load_supported_documents(input_file_path)
            if not docs:
                gr.Error(f"⚠️ Could not load or parse content from file: {Path(input_file_path).name}")
                return None, None
            full_content = "\n\n".join(
                [doc.page_content for doc in docs if doc.page_content and doc.page_content.strip()])
            logger.info(f"Loaded content length: {len(full_content)} characters.")
            if not full_content:
                gr.Error("⚠️ Input file seems to be empty or could not extract text.")
                return None, None
        except Exception as e:
            logger.error(f"Unexpected error loading input file {input_file_path}: {e}", exc_info=True)
            gr.Error(f"🛑 Unexpected error loading input file: {e}")
            return None, None

        try:
            progress(0.4, desc="✍️ AI Processing & Generating...")
            logger.info(f"Running agent for method: {generation_method_choice}")

            agent_result = agent.run(
                user_input=full_content,
                style=selected_style_desc,
                template_name=selected_template_name,
                template_data=final_template_data,  # Pass the data
                generation_method='code' if generation_method_choice == CODE_METHOD else 'json'
            )

            logger.debug(f"Agent run result: {agent_result}")

            if agent_result.get("type") == "error":
                raise RuntimeError(f"Agent execution failed: {agent_result.get('output', 'Unknown agent error')}")

            if agent_result.get("type") == "json":
                logger.info("Agent completed JSON structure generation.")
                presentation_structure_json_str = agent_result.get("output")
                if not presentation_structure_json_str:
                    raise ValueError("Agent returned empty JSON output.")

                try:
                    presentation_structure_json = json.loads(presentation_structure_json_str)
                    presentation_structure_json["template_info"] = final_template_data
                except json.JSONDecodeError as json_err:
                    logger.error(
                        f"Failed to parse agent's JSON output: {json_err}\nOutput:\n{presentation_structure_json_str}")
                    raise ValueError(f"Agent returned invalid JSON: {json_err}")

                if analyze_content_flag:
                    try:
                        progress(0.6, desc="🧐 Analyzing Content Structure...")
                        analysis_results = analyzer.analyze_presentation_structure(presentation_structure_json)
                        if analysis_results["suggestions"] or analysis_results["warnings"]:
                            analysis_results_str = "📊 Content Analysis:\n"
                            if analysis_results["warnings"]:
                                analysis_results_str += "\n⚠️ Warnings:\n- " + "\n- ".join(analysis_results["warnings"])
                            if analysis_results["suggestions"]:
                                analysis_results_str += "\n\n💡 Suggestions:\n- " + "\n- ".join(
                                    analysis_results["suggestions"])
                            logger.info("Analysis complete. Found issues/suggestions.")
                            gr.Info("ℹ️ Content analysis complete. See results below.")
                        else:
                            analysis_results_str = "📊 Content Analysis:\n✅ No major issues or suggestions found."
                            logger.info("Analysis complete. No significant issues found.")
                    except Exception as e:
                        logger.error(f"Error during content analysis: {e}", exc_info=True)
                        gr.Warning(f"⚠️ Could not perform content analysis: {e}")
                        analysis_results_str = "📊 Content Analysis:\n🛑 Error occurred during analysis."

                progress(0.7, desc="⚙️ Generating PowerPoint from JSON...")
                output_base_name = Path(input_file_path).stem
                generated_pptx_path = generate_presentation(
                    presentation_structure_json=presentation_structure_json,
                    output_filename_base=output_base_name
                )
                if not generated_pptx_path or not Path(generated_pptx_path).exists():
                    raise RuntimeError("PPTX generation from JSON failed or did not produce a file.")
                logger.info(f"Successfully generated PPTX from JSON: {generated_pptx_path}")

            elif agent_result.get("type") == "code_execution":
                logger.info("Agent completed code generation and REPL execution.")
                generated_pptx_path = agent_result.get("generated_filename")
                repl_output = agent_result.get("output", "")

                if not generated_pptx_path:
                    raise RuntimeError("Code execution finished, but agent did not return the generated filename.")
                if not Path(generated_pptx_path).exists():
                    logger.error(
                        f"REPL execution finished, but file not found at expected path: {generated_pptx_path}. REPL Output: {repl_output}")
                    raise RuntimeError(
                        f"Code execution seems to have failed. Expected file '{Path(generated_pptx_path).name}' not found. Check logs and REPL output.")

                logger.info(f"Successfully generated PPTX via code execution: {generated_pptx_path}")
                gr.Info(f"Code execution successful. File: {Path(generated_pptx_path).name}")
                analysis_results_str = "📊 Content Analysis:\n N/A for Direct Code Generation method."

            else:
                raise RuntimeError(f"Agent returned unexpected result type: {agent_result.get('type')}")

        except Exception as e:
            logger.error(f"Error during presentation generation pipeline: {e}", exc_info=True)
            # tb_str = traceback.format_exc()
            gr.Error("🛑 Generation Failed: An internal error occurred. Please check the application logs for details.")
            return output_files_list, analysis_results_str

        output_files_list = []
        if generated_pptx_path and Path(generated_pptx_path).exists():
            output_files_list = [generated_pptx_path]
            if export_formats:
                try:
                    progress(0.85, desc=f" L exporting...")
                    logger.info(f"Starting export process for formats: {export_formats}")
                    export_results = exporter.export_presentation(
                        pptx_path=generated_pptx_path,
                        formats=export_formats,
                        output_name=Path(generated_pptx_path).stem
                    )
                    logger.debug(f"Export results dict: {export_results}")

                    if "exports" in export_results:
                        for fmt, result in export_results["exports"].items():
                            if isinstance(result, str) and Path(result).exists():
                                output_files_list.append(result)
                                logger.info(f"Successfully exported to {fmt}: {result}")
                            elif isinstance(result, list):
                                valid_images = [p for p in result if isinstance(p, str) and Path(p).exists()]
                                if valid_images:
                                    output_files_list.extend(valid_images)
                                    logger.info(f"Successfully exported {len(valid_images)} images for format {fmt}")
                                else:
                                    logger.warning(f"Export to {fmt} (images) produced no valid files.")
                                    gr.Warning(f"⚠️ Export to {fmt} (images) failed or produced no files.")
                            else:
                                logger.error(f"Export to {fmt} failed or produced invalid result: {result}")
                                gr.Warning(f"⚠️ Export to {fmt} failed: {result}")
                except Exception as e:
                    logger.error(f"Error during file export process: {e}", exc_info=True)
                    gr.Warning(f"⚠️ Error during export: {e}")
        else:
            logger.error("Primary PPTX file was not generated or found. Cannot perform exports.")
            gr.Warning("⚠️ Primary PPTX file generation failed, skipping exports.")

        progress(1.0, desc="✅ Done!")
        logger.info(f"Process completed. Returning files: {output_files_list}")
        gr.Info("✅ Presentation generation complete!")

        output_files_list = [f for f in output_files_list if f is not None]
        return output_files_list if output_files_list else None, analysis_results_str

    with gr.Blocks(theme=gr.themes.Soft(), title="txt2pptx AI") as iface:
        gr.Markdown(
            """
            # txt2pptx: AI Text-to-PowerPoint Converter 📄➡️📊
            Upload a document, choose options, and let AI generate a PowerPoint presentation for you.
            """
        )

        with gr.Row():
            with gr.Column(scale=2):
                input_file = gr.File(
                    label="1. Upload Document",
                    file_types=[ext for ext in ALLOWED_EXTENSIONS],
                )
                generation_method = gr.Radio(
                    choices=[JSON_METHOD, CODE_METHOD],
                    label="2. Generation Method",
                    value=JSON_METHOD,
                    info="Choose how the presentation is created."
                )
                style_desc = gr.Dropdown(
                    choices=["Default", "Professional", "Creative", "Minimalist", "Academic", "Technical", "Playful"],
                    label="3. Choose Content Style",
                    info="Influences AI tone & structure.",
                    value="Default"
                )
                template = gr.Dropdown(
                    choices=template_choices,
                    label="4. Select Visual Template",
                    info="Base look (colors, fonts, layouts).",
                    value=default_template_value
                )
                llm_provider = gr.Dropdown(
                    choices=llm_provider_choices,
                    label="5. Select AI Provider",
                    value=default_llm_provider
                )
                api_key_input = gr.Textbox(
                    label=f"6. {default_llm_provider} API Key (Optional)",
                    interactive=True,
                    info="Leave blank to use environment variable.",
                    type="password",
                    placeholder="Enter API Key if not set in environment"
                )
                llm_provider.change(lambda p: gr.update(label=f"6. {p} API Key (Optional)"), inputs=llm_provider,
                                    outputs=api_key_input)

                submit_button = gr.Button("✨ Generate Presentation", variant="primary", scale=1)

            with gr.Column(scale=3):
                output_files = gr.Files(label="Generated Files", interactive=False)
                analysis_output = gr.Textbox(
                    label="📊 Content Analysis Results",
                    lines=8,
                    interactive=False,
                    placeholder="Analysis suggestions will appear here (JSON method only)..."
                )

                with gr.Accordion("Advanced Options & Settings", open=False):
                    with gr.Row():
                        analyze_content = gr.Checkbox(
                            label="Analyze Content (JSON Method)",
                            info="Check structure for issues (only works with JSON method).",
                            value=True,
                            scale=1
                        )
                        enable_rag = gr.Checkbox(
                            label="Enhance with RAG Context",
                            info="Use documentation context (if loaded).",
                            value=True,
                            scale=1
                        )
                    export_formats = gr.CheckboxGroup(
                        choices=[("PDF", "pdf"), ("HTML (Basic)", "html"), ("Images (PNG)", "images")],
                        label="Additional Export Formats",
                        info="Requires system setup (LibreOffice/Poppler).",
                        value=[]
                    )
                    template_customization = gr.Code(
                        label="Template Customization (JSON)",
                        language="json",
                        value='{\n  "colors": {\n    "accent1": "#FF5733",\n    "text": "#1C1C1C"\n  },\n  "font": {\n    "heading": "Georgia",\n    "body": "Arial"\n  }\n}',
                        lines=6,
                        interactive=True
                    )

        click_inputs = [
            input_file,
            style_desc,
            template,
            llm_provider,
            api_key_input,
            generation_method,
            export_formats,
            analyze_content,
            enable_rag,
            template_customization
        ]
        click_outputs = [output_files, analysis_output]

        submit_button.click(
            fn=process_request,
            inputs=click_inputs,
            outputs=click_outputs,
            # api_name="generate"
        )

    return iface


def launch_interface(
        available_templates: List[Dict[str, str]],
        loaded_docs_for_rag: Optional[List[Document]] = None,
        default_openai_key: Optional[str] = None,
        default_anthropic_key: Optional[str] = None
):
    """Creates and launches the Gradio interface."""
    logger.info("Creating Gradio UI instance.")
    try:
        iface = create_interface(
            available_templates,
            loaded_docs_for_rag,
            default_openai_key,
            default_anthropic_key
        )
        logger.info("Launching Gradio interface...")
        iface.launch()
        logger.info("Gradio interface finished.")
    except Exception as e:
        logger.critical(f"Failed to create or launch Gradio interface: {e}", exc_info=True)
        print(f"\nFATAL ERROR launching UI: {e}\n", file=sys.stderr)
        raise
