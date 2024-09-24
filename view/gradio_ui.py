import gradio as gr
from langchain_text_splitters import json

from app.agents import create_agent
from app.analyzers import ContentAnalyzer
from app.exporters import PresentationExporter
from app.tools import create_bullet_points_tool, create_pptx_code_tool
from app.utils import generate_presentation
from templates.templates import PresentationTemplates


def create_interface(style_params, documents):
    def process_request(file, selected_style, selected_llm_provider, entered_api_key):
        agent = create_agent(
            [
                create_bullet_points_tool(style_params, selected_llm_provider, entered_api_key),
                create_pptx_code_tool(documents, selected_llm_provider, entered_api_key)
            ],
            selected_llm_provider, entered_api_key
        )
        pptx_code_tool_func = create_pptx_code_tool(documents, selected_llm_provider, entered_api_key).func
        return generate_presentation(file, selected_style, agent, pptx_code_tool_func)

    def enhanced_process_request(file, selected_style, selected_llm_provider,
                               entered_api_key, export_formats, analyze_content,
                               template_customization):
        # Original processing
        pptx_file = process_request(file, selected_style,
                                  selected_llm_provider, entered_api_key)

        results = {"pptx_file": pptx_file}

        # Handle template customization
        if template_customization:
            templates = PresentationTemplates()
            custom_template = templates.customize_template(
                selected_style, template_customization
            )
            results["template"] = custom_template

        # Content analysis
        if analyze_content:
            analyzer = ContentAnalyzer()
            analysis = analyzer.analyze_content(json.loads(pptx_file))
            results["analysis"] = analysis

        # Export handling
        if export_formats:
            exporter = PresentationExporter()
            export_results = exporter.export_presentation(
                pptx_file, formats=export_formats
            )
            results["exports"] = export_results

        return results

    with gr.Blocks(css="""
        .gradio-container {
            background-color: #f4f4f4;
            padding: 20px;
            border-radius: 10px;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        }
        .gradio-button {
            background-color: #007bff;
            color: #fff;
            border: none;
            padding: 10px 20px;
            border-radius: 5px;
            cursor: pointer;
            transition: background-color 0.3s;
        }
        .gradio-button:hover {
            background-color: #0056b3;
        }
    """) as iface:
        gr.Markdown(
            """
            # Text to PowerPoint Converter
            Upload a text or PDF file, choose a presentation style, and generate a professional PowerPoint presentation
             based on the content.
            """
        )

        # Define all input components first
        with gr.Row():
            with gr.Column():
                input_file = gr.File(label="Input File", type="filepath")
                style = gr.Dropdown(
                    choices=["Default", "Professional", "Creative", "Playful"],
                    label="Presentation Style",
                    value="Default"
                )
                llm_provider = gr.Dropdown(
                    choices=["OpenAI", "Anthropic"],
                    label="LLM Provider",
                    value="OpenAI"
                )
                api_key = gr.Textbox(label="API Key", type="password")
                template = gr.Dropdown(
                    choices=["professional", "creative"],
                    label="Presentation Template",
                    value="professional"
                )

        with gr.Tab("Advanced Options"):
            with gr.Row():
                export_formats = gr.CheckboxGroup(
                    choices=["pdf", "html", "images"],
                    label="Export Formats",
                    value=["pdf"]
                )
                analyze_content = gr.Checkbox(
                    label="Analyze Content",
                    value=True
                )
            with gr.Row():
                template_customization = gr.JSON(
                    label="Template Customization",
                    value={"colors": [], "font": "", "transitions": []}
                )

        # Define output components
        with gr.Column():
            output_file = gr.File(label="Generated Presentation", type="binary", interactive=False)

        # Define submit button
        submit_button = gr.Button("Generate Presentation")

        # Set up the click event
        submit_button.click(
            fn=enhanced_process_request,
            inputs=[
                input_file, style, llm_provider, api_key,
                export_formats, analyze_content, template_customization
            ],
            outputs=[output_file]
        )

    return iface


def launch_interface(style_params, documents):
    try:
        iface = create_interface(style_params, documents)
        iface.launch()
    except Exception as e:
        print(f"Error launching interface: {str(e)}")
        raise

