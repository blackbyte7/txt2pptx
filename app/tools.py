from langchain.tools import Tool
from langchain.chains import RetrievalQA
from langchain.vectorstores import FAISS
from langchain.embeddings import OpenAIEmbeddings
from langchain.text_splitter import CharacterTextSplitter
from langchain.llms import OpenAI


def create_bullet_points_tool(llm):
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

    tool = Tool(
        name="Create Bullet Points",
        func=create_bullet_points,
        description="Creates bullet points from the user input, organizes them into pages of a presentation, and decides on the design and effects for each slide."
    )
    return tool


def create_pptx_code_tool(documents, llm):
    # Split the documents into chunks
    text_splitter = CharacterTextSplitter(chunk_size=1000, chunk_overlap=0)
    texts = text_splitter.split_documents(documents)

    # Create a vector store
    embeddings = OpenAIEmbeddings()
    vectorstore = FAISS.from_documents(texts, embeddings)

    # Create a retrieval QA chain
    qa = RetrievalQA.from_chain_type(llm=llm, chain_type="stuff", retriever=vectorstore.as_retriever())

    def generate_pptx_code(json_input):
        prompt = f"Generate Python code using python-pptx to create a PowerPoint presentation based on the following JSON input:\n\n{json_input}"

        # Use the retrieval QA chain to enhance the knowledge about python-pptx
        enhanced_prompt = qa.run(prompt)

        response = llm(enhanced_prompt)
        return response

    tool = Tool(
        name="Generate PPTX Code",
        func=generate_pptx_code,
        description="Generates Python code using python-pptx to create a PowerPoint presentation based on the bullet points."
    )
    return tool