from app.agents import create_agent
from app.tools import create_bullet_points_tool, create_pptx_code_tool
from app.utils import load_documentation, generate_presentation
import gradio as gr


def main():
    # Load the python-pptx library documentation
    documents = load_documentation("data/python-pptx-documentation.pdf")

    # Create the custom tools
    bullet_points_tool = create_bullet_points_tool()
    pptx_code_tool = create_pptx_code_tool(documents)

    # Create the zero-shot agent
    tools = [bullet_points_tool, pptx_code_tool]
    agent = create_agent(tools)

    # Create the Gradio interface
    iface = gr.Interface(
        fn=generate_presentation,
        inputs=gr.File(label="Input File"),
        outputs=gr.File(label="Generated Presentation"),
        title="Text to PowerPoint Converter",
        description="Upload a text or PDF file and generate a PowerPoint presentation based on the content.",
    )

    # Launch the Gradio interface
    iface.launch()


if __name__ == "__main__":
    main()
