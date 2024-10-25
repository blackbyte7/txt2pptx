import os
import json
import sys
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Any

import gradio as gr

# Local application imports
from log_config.logging_config import logger
from app.agents import create_agent, PresentationAgent
from app.analyzers import ContentAnalyzer
from app.exporters import PresentationExporter
from app.utils import generate_presentation, load_supported_documents, ProgressTracker, ALLOWED_EXTENSIONS
from templates.templates import PresentationTemplates
from langchain_core.documents import Document


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
            export_formats: List[str],
            analyze_content_flag: bool,
            enable_rag_flag: bool,
            template_customization_json: Optional[str],
            progress: gr.Progress
    ) -> Tuple[Optional[List[str]], Optional[str]]:
        """
        Handles the Gradio button click event for presentation generation.
        Returns a tuple: (list_of_output_file_paths_or_None, analysis_string_or_None)
        """
        progress(0, desc="▶️ Starting...")
        logger.info("Received request from Gradio UI.")
        output_files_list: Optional[List[str]] = None
        analysis_results_str: Optional[str] = None

        if not input_file_obj:
            gr.Warning("⚠️ Please upload an input file.")
            return None, None

        try:
            input_file_path = input_file_obj.name
            if not isinstance(input_file_path, str):
                raise AttributeError("Could not get file path string.")
            logger.info(f"Input file path: {input_file_path}")
        except (AttributeError, TypeError) as e:
            logger.error(f"Failed to get file path from input object: {e}, object: {input_file_obj}")
            gr.Error("🛑 Could not read the uploaded file object.")
            return None, None

        if not selected_template_name:
            gr.Warning("⚠️ Please select a presentation template.")
            return None, None

        api_key_to_use = entered_api_key
        if not api_key_to_use:
            if selected_llm_provider == "OpenAI":
                api_key_to_use = default_openai_key
            elif selected_llm_provider == "Anthropic":
                api_key_to_use = default_anthropic_key

        if not api_key_to_use:
            gr.Error(f"🛑 API Key for {selected_llm_provider} is required! Set it in the UI or environment.")
            return None, None

        docs_for_agent = loaded_docs_for_rag if enable_rag_flag else None
        if enable_rag_flag and not loaded_docs_for_rag:
            gr.Info("ℹ️ RAG enabled, but no documentation was loaded at startup. Context enhancement will be skipped.")

        agent: Optional[PresentationAgent] = None
        try:
            progress(0.1, desc="🧠 Initializing AI Agent...")
            logger.debug(
                f"Creating agent with provider: {selected_llm_provider}, RAG: {'Enabled' if docs_for_agent else 'Disabled'}")
            agent = create_agent(selected_llm_provider, api_key_to_use, loaded_docs=docs_for_agent)
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

        except (FileNotFoundError, ValueError, RuntimeError, ImportError) as e:
            logger.error(f"Error loading input file {input_file_path}: {e}", exc_info=True)
            gr.Error(f"🛑 Error loading input file: {e}")
            return None, None
        except Exception as e:
            logger.error(f"Unexpected error loading input file {input_file_path}: {e}", exc_info=True)
            gr.Error(f"🛑 Unexpected error loading input file: {e}")
            return None, None

        final_template_data = template_manager.get_template(selected_template_name)
        if not final_template_data:
            gr.Error(f"🛑 Selected template '{selected_template_name}' not found internally.")
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

        presentation_structure_json: Optional[Dict] = None
        try:
            progress(0.4, desc="✍️ AI Generating Structure...")
            logger.info(f"Running agent. Style: '{selected_style_desc}', Template: '{final_template_data.get('name')}'")
            presentation_structure_json = agent.run(
                user_input=full_content,
                style=selected_style_desc,
                template_name=final_template_data.get('name', selected_template_name)
            )
            presentation_structure_json["template_info"] = final_template_data
            logger.info("Agent successfully generated presentation structure.")

        except ValueError as ve:
            logger.error(f"Agent failed to produce valid structure: {ve}", exc_info=True)
            gr.Error(f"🛑 AI Agent Error: {ve}")
            return None, None
        except Exception as e:
            logger.error(f"Error during agent execution: {e}", exc_info=True)
            gr.Error(f"🛑 Error during AI generation: {e}")
            return None, None

        if analyze_content_flag and presentation_structure_json:
            try:
                progress(0.6, desc="🧐 Analyzing Content...")
                logger.info("Performing content analysis...")
                analysis_results = analyzer.analyze_presentation_structure(presentation_structure_json)
                if analysis_results["suggestions"] or analysis_results["warnings"]:
                    analysis_results_str = "📊 Content Analysis:\n"
                    if analysis_results["warnings"]:
                        analysis_results_str += "\n⚠️ Warnings:\n- " + "\n- ".join(analysis_results["warnings"])
                    if analysis_results["suggestions"]:
                        analysis_results_str += "\n\n💡 Suggestions:\n- " + "\n- ".join(analysis_results["suggestions"])
                    logger.info("Analysis complete. Found issues/suggestions.")
                    gr.Info("ℹ️ Content analysis complete. See results below.")
                else:
                    analysis_results_str = "📊 Content Analysis:\n✅ No major issues or suggestions found."
                    logger.info("Analysis complete. No significant issues found.")

            except Exception as e:
                logger.error(f"Error during content analysis: {e}", exc_info=True)
                gr.Warning(f"⚠️ Could not perform content analysis: {e}")
                analysis_results_str = "📊 Content Analysis:\n🛑 Error occurred during analysis."

        pptx_file_path: Optional[str] = None
        try:
            progress(0.7, desc="⚙️ Generating PowerPoint File...")
            output_base_name = Path(input_file_path).stem
            pptx_file_path = generate_presentation(
                presentation_structure_json=presentation_structure_json,
                output_filename_base=output_base_name
            )
            if not pptx_file_path or not Path(pptx_file_path).exists():
                raise RuntimeError("PPTX generation failed or did not produce a valid file path.")
            logger.info(f"Successfully generated PPTX file: {pptx_file_path}")
            output_files_list = [pptx_file_path]

        except Exception as e:
            logger.error(f"Error generating PPTX file: {e}", exc_info=True)
            gr.Error(f"🛑 Error generating PowerPoint file: {e}")
            return None, analysis_results_str

        if export_formats and pptx_file_path:
            try:
                progress(0.85, desc=f" L exporting...")
                logger.info(f"Starting export process for formats: {export_formats}")
                export_results = exporter.export_presentation(
                    pptx_path=pptx_file_path,
                    formats=export_formats,
                    output_name=Path(pptx_file_path).stem
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

        progress(1.0, desc="✅ Done!")
        logger.info(f"Process completed. Returning files: {output_files_list}")
        gr.Info("✅ Presentation generation complete!")

        return output_files_list, analysis_results_str

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
                style_desc = gr.Dropdown(
                    choices=["Default", "Professional", "Creative", "Minimalist", "Academic", "Technical", "Playful"],
                    label="2. Choose Content Style",
                    info="Influences AI tone & structure.",
                    value="Default"
                )
                template = gr.Dropdown(
                    choices=template_choices,
                    label="3. Select Visual Template",
                    info="Base look (colors, fonts, layouts).",
                    value=default_template_value
                )
                llm_provider = gr.Dropdown(
                    choices=llm_provider_choices,
                    label="4. Select AI Provider",
                    value=default_llm_provider
                )
                api_key_input = gr.Textbox(
                    label=f"5. {default_llm_provider} API Key (Optional)",
                    interactive=True,
                    info="Leave blank to use environment variable.",
                    type="password",
                    placeholder="Enter API Key if not set in environment"
                )
                llm_provider.change(lambda p: gr.update(label=f"5. {p} API Key (Optional)"), inputs=llm_provider,
                                    outputs=api_key_input)

                submit_button = gr.Button("✨ Generate Presentation", variant="primary", scale=1)

            with gr.Column(scale=3):
                output_files = gr.Files(label="Generated Files", interactive=False)
                analysis_output = gr.Textbox(
                    label="📊 Content Analysis Results",
                    lines=8,
                    interactive=False,
                    placeholder="Analysis suggestions will appear here..."
                )

                with gr.Accordion("Advanced Options & Settings", open=False):
                    with gr.Row():
                        analyze_content = gr.Checkbox(
                            label="Analyze Content Structure",
                            #info="Check structure for potential issues.",
                            value=True,
                            scale=1
                        )
                        enable_rag = gr.Checkbox(
                            label="Enhance with RAG Context",
                            #info="Use documentation context to improve structure (if docs were loaded).",
                            value=True,
                            scale=1
                        )
                    export_formats = gr.CheckboxGroup(
                        choices=[("PDF", "pdf"), ("HTML (Basic)", "html"), ("Images (PNG)", "images")],
                        label="Additional Export Formats",
                        #info="Requires system setup (LibreOffice/Poppler) - see README.",
                        value=[]
                    )
                    template_customization = gr.Code(
                        label="Template Customization (JSON)",
                        language="json",
                        value='{\n  "colors": {\n    "accent1": "#FF5733",\n    "text": "#1C1C1C"\n  },\n  "font": {\n    "heading": "Georgia",\n    "body": "Arial"\n  }\n}',
                        #info="Override parts of the selected visual template. Invalid JSON ignored.",
                        lines=6,
                        interactive=True
                    )

        click_inputs = [
            input_file,
            style_desc,
            template,
            llm_provider,
            api_key_input,
            export_formats,
            analyze_content,
            enable_rag,
            template_customization
        ]
        click_outputs = [output_files, analysis_output]

        submit_button.click(
            fn=process_request,
            inputs=click_inputs,
            outputs=click_outputs
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
