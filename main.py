import gradio as gr
from langchain.agents import ZeroShotAgent, Tool
from langchain.llms import OpenAI
from langchain.document_loaders import PyPDFLoader, TextLoader
from langchain.text_splitter import CharacterTextSplitter
from langchain.vectorstores import FAISS
from langchain.embeddings import OpenAIEmbeddings
from langchain.chains import RetrievalQA
from langchain.tools import PythonREPLTool
import json

# Initialize the OpenAI API
llm = OpenAI(api_key="YOUR_API_KEY")

# Load the python-pptx library documentation
loader = PyPDFLoader("path/to/python-pptx-documentation.pdf")
documents = loader.load()

# Split the documents into chunks
text_splitter = CharacterTextSplitter(chunk_size=1000, chunk_overlap=0)
texts = text_splitter.split_documents(documents)

# Create a vector store
embeddings = OpenAIEmbeddings()
vectorstore = FAISS.from_documents(texts, embeddings)

# Create a retrieval QA chain
qa = RetrievalQA.from_chain_type(llm=llm, chain_type="stuff", retriever=vectorstore.as_retriever())


# Define the first custom tool
def create_bullet_points(user_input):
    prompt = f"""
    Create bullet points from the following text and organize them into pages of a presentation.
    Also, decide on the design and effects for each slide.
    Return the output in JSON format, using the following structure:
    {{
        "pages": [
            {{
                "title": "Page 1 Title",
                "bullet_points": [
                    "Bullet point 1",
                    "Bullet point 2",
                    ...
                ],
                "design": "Design description",
                "effects": "Effects description"
            }},
            ...
        ]
    }}

    Text:
    {user_input}
    """
    response = llm(prompt)
    return response


# Define the second custom tool
def generate_pptx_code(json_input):
    prompt = f"Generate Python code using python-pptx to create a PowerPoint presentation based on the following JSON input:\n\n{json_input}"

    # Use the retrieval QA chain to enhance the knowledge about python-pptx
    enhanced_prompt = qa.run(prompt)

    response = llm(enhanced_prompt)
    return response


# Create the custom tools
bullet_points_tool = Tool(
    name="Create Bullet Points",
    func=create_bullet_points,
    description="Creates bullet points from the user input, organizes them into pages of a presentation, and decides on the design and effects for each slide."
)

pptx_code_tool = Tool(
    name="Generate PPTX Code",
    func=generate_pptx_code,
    description="Generates Python code using python-pptx to create a PowerPoint presentation based on the bullet points."
)

python_repl_tool = PythonREPLTool()

# Create the zero-shot agent
tools = [bullet_points_tool, pptx_code_tool, python_repl_tool]
agent = ZeroShotAgent(llm=llm, tools=tools)


# Define the Gradio interface
def generate_presentation(input_file):
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
    result = python_repl_tool.run(python_code)

    # Save the generated PowerPoint presentation
    output_file = "generated_presentation.pptx"
    with open(output_file, "wb") as file:
        file.write(result)

    return output_file


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