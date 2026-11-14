"""Retrieval over reference documentation (optional, OpenAI embeddings).

The index is a ``langchain_core`` :class:`InMemoryVectorStore` persisted as JSON (no pickle), cached under a
key derived from the document contents, chunking parameters and embedding model, so changed docs or models
never reuse a stale index.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from pathlib import Path

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.retrievers import BaseRetriever
from langchain_core.vectorstores import InMemoryVectorStore
from langchain_text_splitters import RecursiveCharacterTextSplitter

logger = logging.getLogger(__name__)

CHUNK_SIZE = 900
CHUNK_OVERLAP = 120


class DocumentationIndex:
    def __init__(self, docs: list[Document], embeddings: Embeddings, cache_dir: Path, *, model_id: str = ""):
        self.docs = docs
        self.embeddings = embeddings
        self.cache_dir = cache_dir
        self.model_id = model_id or type(embeddings).__name__
        self._store: InMemoryVectorStore | None = None
        self._lock = threading.Lock()

    @property
    def cache_key(self) -> str:
        digest = hashlib.sha256()
        digest.update(f"{self.model_id}|{CHUNK_SIZE}|{CHUNK_OVERLAP}".encode())
        for doc in self.docs:
            digest.update(doc.page_content.encode("utf-8", "replace"))
        return digest.hexdigest()[:24]

    @property
    def cache_file(self) -> Path:
        return self.cache_dir / f"docs-{self.cache_key}.json"

    def store(self) -> InMemoryVectorStore:
        with self._lock:
            if self._store is None:
                self._store = self._load_or_build()
            return self._store

    def _load_or_build(self) -> InMemoryVectorStore:
        if self.cache_file.exists():
            try:
                store = InMemoryVectorStore.load(str(self.cache_file), self.embeddings)
                logger.info("Loaded documentation index from %s", self.cache_file)
                return store
            except Exception as exc:
                logger.warning("Ignoring unreadable index cache %s: %s", self.cache_file, exc)

        splitter = RecursiveCharacterTextSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)
        chunks = splitter.split_documents(self.docs)
        logger.info("Embedding %d documentation chunks (one-time)...", len(chunks))
        store = InMemoryVectorStore(self.embeddings)
        store.add_documents(chunks)
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            store.dump(str(self.cache_file))
        except OSError as exc:
            logger.warning("Could not cache documentation index: %s", exc)
        return store

    def retriever(self, k: int = 4) -> BaseRetriever:
        return self.store().as_retriever(search_kwargs={"k": k})


def openai_embeddings(api_key: str, model: str) -> Embeddings:
    from langchain_openai import OpenAIEmbeddings

    return OpenAIEmbeddings(api_key=api_key, model=model)
