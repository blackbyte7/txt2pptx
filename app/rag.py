from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_openai import OpenAIEmbeddings
from langchain_core.documents import Document
from langchain_core.runnables import RunnablePassthrough
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from typing import List, Union
import pickle
from pathlib import Path
from log_config.logging_config import logger


class EnhancedRAG:
    def __init__(self, cache_dir: str = "cache/vector_stores"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.embeddings = OpenAIEmbeddings()
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=500,
            chunk_overlap=50,
            separators=["\n\n", "\n", ".", "!", "?", ",", " ", ""],
        )

    def create_vector_store(self, documents: Union[List[str], List[Document]], cache_name: str) -> FAISS:
        cache_file = self.cache_dir / f"{cache_name}.pkl"

        if cache_file.exists():
            logger.info(f"Loading vector store from cache: {cache_name}")
            with open(cache_file, 'rb') as f:
                return pickle.load(f)

        logger.info(f"Creating new vector store: {cache_name}")

        texts = self.text_splitter.split_documents(documents)
        vector_store = FAISS.from_documents(texts, self.embeddings)

        with open(cache_file, 'wb') as f:
            pickle.dump(vector_store, f)

        return vector_store


def get_relevant_context(self, vector_store: FAISS, query: str, k: int = 3) -> str:
    docs = vector_store.similarity_search(query, k=k)
    return "\n".join([doc.page_content for doc in docs])


def create_retrieval_chain(self, vector_store: FAISS, llm):
    """
    Create a retrieval-augmented generation chain using LCEL.

    Args:
        vector_store (FAISS): The vector store to retrieve from
        llm: The language model to use for generation

    Returns:
        A retrieval-augmented generation chain
    """
    # Create a retriever from the vector store
    retriever = vector_store.as_retriever(search_kwargs={"k": 3})

    # Create a prompt template for RAG
    prompt = ChatPromptTemplate.from_template("""
        You are an expert assistant. Answer the question based only on the following context:

        {context}

        Question: {question}
        """)

    # Create the RAG chain using LCEL
    rag_chain = (
            {"context": retriever, "question": RunnablePassthrough()}
            | RunnablePassthrough.assign(context=lambda x: x["context"])
            | prompt
            | llm
            | StrOutputParser()
    )

    return rag_chain
