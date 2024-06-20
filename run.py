from langchain_community.llms.openai import OpenAI
from app.agents import create_agent
from app.tools import create_bullet_points_tool, create_pptx_code_tool
from app.utils import load_documentation, generate_presentation
import gradio as gr


def main():
    # Initialize the OpenAI API
    llm = OpenAI(api_key="YOUR_API_KEY")

    # Define the list of style parameters
    style_params = ["Bold Colors", "Minimalistic", "Gradient Backgrounds", "Custom Fonts", "Image Placeholders"]

    # Load the python-pptx library documentation
    documents = load_documentation("data/python-pptx-documentation.pdf")

    # Create the custom tools
    bullet_points_tool = create_bullet_points_tool(llm, style_params)
    pptx_code_tool = create_pptx_code_tool(documents, llm)

    # Create the zero-shot agent
    tools = [bullet_points_tool, pptx_code_tool]
    agent = create_agent(tools)

    # Create the Gradio interface
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

    # Launch the Gradio interface
    iface.launch()


if __name__ == "__main__":
    main()
