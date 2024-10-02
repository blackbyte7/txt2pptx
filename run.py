from app.utils import load_documentation
from view.gradio_ui import launch_interface


def main():
    try:
        # Define the list of style parameters
        style_params = ["Bold Colors", "Minimalistic", "Gradient Backgrounds", "Custom Fonts", "Image Placeholders"]

        # Load the python-pptx library documentation
        documents = load_documentation("data/python-pptx-documentation.pdf")

        # Launch the Gradio interface
        launch_interface(style_params, documents)
    except Exception as e:
        print(f"Error in main function: {str(e)}")
        raise


if __name__ == "__main__":
    main()
