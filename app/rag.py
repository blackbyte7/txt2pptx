from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_openai import OpenAIEmbeddings
from langchain.chains import RetrievalQA
from typing import List
import pickle
from pathlib import Path
from logging.logging_config import logger


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

    def create_vector_store(self, documents: List[str], cache_name: str) -> FAISS:
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

    def create_qa_chain(self, vector_store: FAISS, llm) -> RetrievalQA:
        return RetrievalQA.from_chain_type(
            llm=llm,
            chain_type="stuff",
            retriever=vector_store.as_retriever(search_kwargs={"k": 3})
        )
