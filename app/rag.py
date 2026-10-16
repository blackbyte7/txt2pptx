from pathlib import Path
from typing import List, Optional, Union

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseLanguageModel
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableLambda, RunnablePassthrough, RunnableSerializable
from langchain_core.vectorstores import VectorStore
from langchain_openai import OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

from log_config.logging_config import logger

try:
    from langchain_community.vectorstores import FAISS

    FAISS_AVAILABLE = True
except ImportError:
    logger.warning(
        "FAISS not found. RAG will be disabled. Install with 'pip install faiss-cpu' or 'pip install faiss-gpu'."
    )
    FAISS_AVAILABLE = False

    class FAISS:  # type: ignore
        pass


class EnhancedRAG:
    def __init__(
        self,
        docs: Union[List[str], List[Document], None] = None,
        embeddings: Optional[Embeddings] = None,
        vector_store_cls: type[VectorStore] = FAISS,
        cache_dir: Union[str, Path] = "cache/vector_stores",
        cache_name: str = "default_rag_store",
        text_splitter: Optional[RecursiveCharacterTextSplitter] = None,
        openai_api_key: Optional[str] = None,
    ):
        if not FAISS_AVAILABLE and vector_store_cls == FAISS:
            raise ImportError("FAISS is selected as VectorStore but is not installed.")

        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_name = cache_name
        self.cache_path = self.cache_dir / self.cache_name

        if embeddings is not None:
            self.embeddings = embeddings
        elif openai_api_key:
            self.embeddings = OpenAIEmbeddings(api_key=openai_api_key)
        else:
            self.embeddings = OpenAIEmbeddings()

        self.text_splitter = text_splitter or RecursiveCharacterTextSplitter(
            chunk_size=500,
            chunk_overlap=50,
            separators=["\n\n", "\n", ". ", "? ", "! ", ", ", " ", ""],
            length_function=len,
        )
        self.vector_store_cls = vector_store_cls
        self.vector_store: Optional[VectorStore] = self._load_or_create_vector_store(docs)

    def _load_or_create_vector_store(
        self, documents: Union[List[str], List[Document], None]
    ) -> Optional[VectorStore]:
        """Loads vector store from native FAISS local cache or creates it if documents are provided."""
        index_file = self.cache_path / "index.faiss"
        if (
            self.cache_path.exists()
            and index_file.exists()
            and hasattr(self.vector_store_cls, "load_local")
        ):
            try:
                logger.info(f"Loading vector store from cache: {self.cache_path}")
                return self.vector_store_cls.load_local(
                    str(self.cache_path),
                    self.embeddings,
                    allow_dangerous_deserialization=True,
                )
            except Exception as e:
                logger.warning(f"Failed to load vector store from cache ({e}). Recreating.")

        if documents:
            logger.info(f"Creating new vector store: {self.cache_name}")
            if isinstance(documents[0], str):
                docs_to_split = [Document(page_content=doc) for doc in documents]
            else:
                docs_to_split = documents  # type: ignore

            texts = self.text_splitter.split_documents(docs_to_split)
            logger.info(f"Split {len(docs_to_split)} documents into {len(texts)} chunks.")

            if not texts:
                logger.warning("No text chunks generated after splitting. Vector store will be empty.")
                return None

            try:
                vector_store = self.vector_store_cls.from_documents(texts, self.embeddings)
                if hasattr(vector_store, "save_local"):
                    try:
                        vector_store.save_local(str(self.cache_path))
                        logger.info(f"Saved new vector store to cache: {self.cache_path}")
                    except Exception as e:
                        logger.error(f"Failed to save vector store to cache: {e}")
                return vector_store
            except Exception as e:
                logger.error(f"Failed to create vector store: {e}", exc_info=True)
                return None
        else:
            logger.info(
                "No documents provided and no cache found. RAG system initialized without a vector store."
            )
            return None

    def get_retriever(self, k: int = 3, **kwargs):
        """Gets the retriever instance from the vector store."""
        if self.vector_store:
            return self.vector_store.as_retriever(search_kwargs={"k": k, **kwargs})
        else:
            logger.warning("Vector store not available. Cannot create retriever.")
            return None

    def get_relevant_context(self, query: str, k: int = 3) -> str:
        """Performs similarity search and returns concatenated context."""
        if self.vector_store:
            try:
                docs = self.vector_store.similarity_search(query, k=k)
                logger.debug(f"Retrieved {len(docs)} documents for query: '{query[:50]}...'")
                return "\n\n---\n\n".join([doc.page_content for doc in docs])
            except Exception as e:
                logger.error(f"Error during similarity search: {e}", exc_info=True)
                return "Error retrieving context."
        else:
            logger.warning("Vector store not available. Cannot retrieve context.")
            return "Context not available."

    def create_rag_chain(
        self,
        llm: BaseLanguageModel,
        retriever_k: int = 3,
        prompt_template: Optional[str] = None,
    ) -> Optional[RunnableSerializable]:
        """
        Creates a Retrieval-Augmented Generation chain using LCEL.

        Args:
            llm (BaseLanguageModel): The language model for generation.
            retriever_k (int): Number of documents to retrieve.
            prompt_template (Optional[str]): Custom prompt template string. Must include
                                            '{context}' and '{question}' placeholders.

        Returns:
            Optional[RunnableSerializable]: The RAG chain, or None if retriever is unavailable.
        """
        retriever = self.get_retriever(k=retriever_k)
        if not retriever:
            logger.warning("Cannot create RAG chain: Retriever is unavailable.")
            return None

        template = (
            prompt_template
            or """
        You are an expert assistant. Answer the question based *only* on the following context:

        <context>
        {context}
        </context>

        Question: {question}

        Answer:"""
        )
        prompt = ChatPromptTemplate.from_template(template)

        rag_chain = (
            {
                "context": retriever | RunnableLambda(self._format_docs),
                "question": RunnablePassthrough(),
            }
            | prompt
            | llm
            | StrOutputParser()
        )
        logger.info("Created RAG chain.")
        return rag_chain

    @staticmethod
    def _format_docs(docs: List[Document]) -> str:
        """Helper to join document contents."""
        return "\n\n---\n\n".join(doc.page_content for doc in docs)
