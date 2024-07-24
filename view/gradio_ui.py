import gradio as gr
from app.utils import generate_presentation


def create_interface(agent, pptx_code_tool):
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
            Upload a text or PDF file, choose a presentation style, and generate a professional PowerPoint presentation based on the content.
            """
        )

        with gr.Row():
            with gr.Column():
                input_file = gr.File(label="Input File", type="file")
                style = gr.Dropdown(
                    choices=["Default", "Professional", "Creative", "Playful"],
                    label="Presentation Style",
                    value="Default"
                )
                submit_button = gr.Button("Generate Presentation")

            with gr.Column():
                output_file = gr.File(label="Generated Presentation", type="file", interactive=False)
                download_button = gr.Button("Download Presentation")

        submit_button.click(
            fn=lambda file, selected_style: generate_presentation(file, selected_style, agent, pptx_code_tool.func),
            inputs=[input_file, style],
            outputs=output_file
        )

        download_button.click(
            fn=lambda file: file.name,
            inputs=output_file,
            outputs=output_file
        )

    return iface


def launch_interface(agent, pptx_code_tool):
    try:
        iface = create_interface(agent, pptx_code_tool)
        iface.launch()
    except Exception as e:
        print(f"Error launching interface: {str(e)}")
        raise
