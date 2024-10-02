import json
from langchain_community.document_loaders import (PyPDFLoader, TextLoader, UnstructuredHTMLLoader,
                                                  UnstructuredWordDocumentLoader,
                                                  UnstructuredPowerPointLoader)
from langchain_experimental.tools.python.tool import PythonREPLTool
from typing import Any
import time
from pathlib import Path
from .logging_config import logger


def load_documentation(file_path):
    try:
        loader = PyPDFLoader(file_path)
        documents = loader.load()
        return documents
    except Exception as e:
        print(f"Error loading documentation: {str(e)}")
        raise


def generate_presentation(input_file: Any, style: str, agent: Any, generate_pptx_code: Any) -> str:
    progress = ProgressTracker()

    try:
        if not validate_input_file(input_file.name):
            raise ValueError("Unsupported file format")

        progress.update_progress('loading')
        # Load the input file based on its format
        if input_file.name.endswith(".pdf"):
            loader = PyPDFLoader(input_file.name)
        elif input_file.name.endswith(".txt"):
            loader = TextLoader(input_file.name)
        elif input_file.name.endswith(".html") or input_file.name.endswith(".htm"):
            loader = UnstructuredHTMLLoader(input_file.name)
        elif input_file.name.endswith(".docx"):
            loader = UnstructuredWordDocumentLoader(input_file.name)
        elif input_file.name.endswith(".pptx"):
            loader = UnstructuredPowerPointLoader(input_file.name)
        else:
            return ("Unsupported file format. Please provide a file in one of the supported formats: "
                    "txt, pdf, html, docx, pptx.")

        user_input = loader.load_and_split()[0].page_content

        # Run the agent with the user input and selected style
        progress.update_progress('processing')
        output = agent.run(user_input, style)

        # Generate the Python code using the second tool
        progress.update_progress('generating')
        json_output = json.loads(output)
        python_code = generate_pptx_code(json.dumps(json_output))

        # Run the generated Python code using the PythonREPLTool
        progress.update_progress('saving')
        python_repl_tool = PythonREPLTool()
        result = python_repl_tool.run(python_code)

        # Save the generated PowerPoint presentation
        timestamp = time.strftime("%Y%m%d-%H%M%S")
        output_file = f"generated_presentation_{timestamp}.pptx"

        with open(output_file, "wb") as file:
            file.write(result)

        logger.info(f"Successfully generated presentation: {output_file}")
        return output_file

    except Exception as e:
        logger.error(f"Error in generate_presentation: {str(e)}")
        raise


class ProgressTracker:
    def __init__(self):
        self.steps = {
            'loading': 'Loading input file',
            'processing': 'Processing content',
            'generating': 'Generating presentation',
            'saving': 'Saving presentation'
        }
        self.current_step = None

    def update_progress(self, step: str, message: str = None):
        self.current_step = step
        if message:
            logger.info(f"{self.steps[step]}: {message}")
        else:
            logger.info(self.steps[step])


def validate_input_file(file_path: str) -> bool:
    allowed_extensions = {'.pdf', '.txt', '.html', '.htm', '.docx', '.pptx'}
    return Path(file_path).suffix.lower() in allowed_extensions

