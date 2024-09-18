import gradio as gr
from app.agents import create_agent
from app.tools import create_bullet_points_tool, create_pptx_code_tool
from app.utils import generate_presentation


def create_interface(style_params, documents):
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

        with gr.Row():
            with gr.Column():
                template = gr.Dropdown(
                    choices=["professional", "creative"],
                    label="Presentation Template",
                    value="professional"
                )

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
                submit_button = gr.Button("Generate Presentation")

            with gr.Column():
                output_file = gr.File(label="Generated Presentation", type="binary", interactive=False)

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

        submit_button.click(
            fn=process_request,
            inputs=[input_file, style, llm_provider, api_key],
            outputs=output_file
        )

    return iface


def launch_interface(style_params, documents):
    try:
        iface = create_interface(style_params, documents)
        iface.launch()
    except Exception as e:
        print(f"Error launching interface: {str(e)}")
        raise
