import json
from langchain.document_loaders import PyPDFLoader, TextLoader
from langchain.tools import PythonREPLTool


def load_documentation(file_path):
    loader = PyPDFLoader(file_path)
    documents = loader.load()
    return documents


def generate_presentation(input_file, agent, generate_pptx_code):
    # Load the input file
    if input_file.name.endswith(".pdf"):
        loader = PyPDFLoader(input_file.name)
    elif input_file.name.endswith(".txt"):
        loader = TextLoader(input_file.name)
    else:
        return "Unsupported file format. Please provide a txt or pdf file."

    user_input = loader.load_and_split()[0].page_content

    # Run the agent with the user input
    output = agent.run(user_input)

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
