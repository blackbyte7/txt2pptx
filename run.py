from langchain_community.llms.openai import OpenAI
from app.agents import create_agent
from app.tools import create_bullet_points_tool, create_pptx_code_tool
from app.utils import load_documentation, generate_presentation
from view.gradio_ui import launch_interface


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

    # Launch the Gradio interface
    launch_interface(agent, pptx_code_tool)

if __name__ == "__main__":
    main()
