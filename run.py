from langchain_openai import OpenAI
from app.agents import create_agent
from app.tools import create_bullet_points_tool, create_pptx_code_tool
from app.utils import load_documentation, generate_presentation
from view.gradio_ui import launch_interface
import os

os.environ['OPENAI_API_KEY'] = 'value'
api_key = os.environ.get('OPENAI_API_KEY')


def main():
    try:
        # Initialize the OpenAI API
        llm = OpenAI(api_key=api_key)

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
    except Exception as e:
        print(f"Error in main function: {str(e)}")
        raise


if __name__ == "__main__":
    main()
