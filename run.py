from app.utils import load_documentation, generate_presentation
from view.gradio_ui import launch_interface
from app.agents import create_agent
from app.tools import create_pptx_code_tool
from dotenv import load_dotenv
import os


def main():
    try:
        # Load environment variables
        load_dotenv("environment.env")
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY not found in environment.env")

        # Define the list of style parameters
        style_params = ["Bold Colors", "Minimalistic", "Gradient Backgrounds", "Custom Fonts", "Image Placeholders"]

        # Load the python-pptx library documentation
        documents = load_documentation("data/python-pptx-documentation.pdf") #Make sure this file exists

        # Launch the Gradio interface
        launch_interface(style_params, documents, api_key)
    except Exception as e:
        print(f"Error in main function: {str(e)}")
        raise


if __name__ == "__main__":
    main()
