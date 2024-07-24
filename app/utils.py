import json
from langchain.document_loaders import PyPDFLoader, TextLoader, UnstructuredHTMLLoader, UnstructuredWordDocumentLoader, \
    UnstructuredPowerPointLoader
from langchain.tools import PythonREPLTool


def load_documentation(file_path):
    try:
        loader = PyPDFLoader(file_path)
        documents = loader.load()
        return documents
    except Exception as e:
        print(f"Error loading documentation: {str(e)}")
        raise


def generate_presentation(input_file, style, agent, generate_pptx_code):
    try:
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
            return "Unsupported file format. Please provide a file in one of the supported formats: txt, pdf, html, docx, pptx."

        user_input = loader.load_and_split()[0].page_content

        # Run the agent with the user input and selected style
        output = agent.run(user_input, style)

        # Parse the JSON output from the first tool
        json_output = json.loads(output)

        # Generate the Python code using the second tool
        python_code = generate_pptx_code(json.dumps(json_output))

        # Run the generated Python code using the PythonREPLTool
        python_repl_tool = PythonREPLTool()
        result = python_repl_tool.run(python_code)

        # Save the generated PowerPoint presentation
        output_file = "generated_presentation.pptx"
        with open(output_file, "wb") as file:
            file.write(result)

        return output_file
    except Exception as e:
        print(f"Error generating presentation: {str(e)}")
        raise
