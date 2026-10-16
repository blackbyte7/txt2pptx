from unittest.mock import MagicMock, patch

import pytest
from langchain_core.documents import Document

from app.rag import FAISS_AVAILABLE, EnhancedRAG

if not FAISS_AVAILABLE:

    class MockFAISS:
        @staticmethod
        def from_documents(docs, embeds):
            store = MockFAISS()
            store._docs = docs
            store._embeds = embeds
            store.save_local = MagicMock()
            store.similarity_search = MagicMock(return_value=docs[:1])
            return store

        @staticmethod
        def load_local(folder_path, embeddings, allow_dangerous_deserialization=False):
            return MockFAISS()

        def as_retriever(self, **kwargs):
            retriever = MagicMock()
            retriever.invoke.return_value = self._docs[: kwargs.get("k", 1)]
            return retriever

    FAISS_MODULE = MockFAISS
else:
    from langchain_community.vectorstores import FAISS

    FAISS_MODULE = FAISS


@pytest.fixture
def sample_docs_list():
    return [
        Document(page_content="Langchain helps build LLM apps."),
        Document(page_content="FAISS is a vector store."),
        Document(page_content="RAG enhances LLM context."),
        Document(page_content="Embeddings represent text numerically."),
    ]


@pytest.fixture
def sample_docs_str():
    return [
        "Langchain helps build LLM apps.",
        "FAISS is a vector store.",
        "RAG enhances LLM context.",
        "Embeddings represent text numerically.",
    ]


@patch("app.rag.FAISS", FAISS_MODULE)
def test_rag_init_loads_from_local_cache(mock_embeddings, mock_vector_store, tmp_path):
    cache_dir = tmp_path / "rag_cache"
    cache_name = "test_store"
    store_dir = cache_dir / cache_name
    store_dir.mkdir(parents=True)
    (store_dir / "index.faiss").touch()

    with patch.object(
        FAISS_MODULE, "load_local", return_value=mock_vector_store, create=True
    ) as mock_load_local:
        rag = EnhancedRAG(
            embeddings=mock_embeddings,
            vector_store_cls=FAISS_MODULE,
            cache_dir=cache_dir,
            cache_name=cache_name,
        )

        mock_load_local.assert_called_once_with(
            str(store_dir),
            mock_embeddings,
            allow_dangerous_deserialization=True,
        )
        assert rag.vector_store is mock_vector_store


@patch("app.rag.FAISS", FAISS_MODULE)
@patch("langchain_text_splitters.RecursiveCharacterTextSplitter.split_documents")
def test_rag_init_recreates_on_cache_load_error(
    mock_split_docs, mock_embeddings, mock_vector_store, sample_docs_list, tmp_path
):
    cache_dir = tmp_path / "rag_cache"
    cache_name = "test_store"
    store_dir = cache_dir / cache_name
    store_dir.mkdir(parents=True)
    (store_dir / "index.faiss").touch()

    mock_split_docs.return_value = sample_docs_list

    with patch.object(
        FAISS_MODULE, "load_local", side_effect=RuntimeError("Corrupt index"), create=True
    ) as mock_load_local, patch.object(
        FAISS_MODULE, "from_documents", return_value=mock_vector_store
    ) as mock_from_docs:
        rag = EnhancedRAG(
            docs=sample_docs_list,
            embeddings=mock_embeddings,
            vector_store_cls=FAISS_MODULE,
            cache_dir=cache_dir,
            cache_name=cache_name,
        )

        mock_load_local.assert_called_once()
        mock_from_docs.assert_called_once_with(sample_docs_list, mock_embeddings)
        mock_vector_store.save_local.assert_called_once_with(str(store_dir))
        assert rag.vector_store is mock_vector_store


@patch("app.rag.FAISS", FAISS_MODULE)
@patch("langchain_text_splitters.RecursiveCharacterTextSplitter.split_documents")
def test_rag_init_creates_new_store(
    mock_split_docs, mock_embeddings, mock_vector_store, sample_docs_list, tmp_path
):
    cache_dir = tmp_path / "rag_cache"
    cache_name = "test_store"
    mock_split_docs.return_value = sample_docs_list

    with patch.object(
        FAISS_MODULE, "from_documents", return_value=mock_vector_store
    ) as mock_from_docs:
        rag = EnhancedRAG(
            docs=sample_docs_list,
            embeddings=mock_embeddings,
            vector_store_cls=FAISS_MODULE,
            cache_dir=cache_dir,
            cache_name=cache_name,
        )

        mock_split_docs.assert_called_once_with(sample_docs_list)
        mock_from_docs.assert_called_once_with(sample_docs_list, mock_embeddings)
        mock_vector_store.save_local.assert_called_once_with(str(cache_dir / cache_name))
        assert rag.vector_store is mock_vector_store


@patch("app.rag.FAISS", FAISS_MODULE)
def test_rag_init_no_docs_no_cache(mock_embeddings, tmp_path):
    rag = EnhancedRAG(
        docs=None,
        embeddings=mock_embeddings,
        vector_store_cls=FAISS_MODULE,
        cache_dir=tmp_path,
    )
    assert rag.vector_store is None


@patch("app.rag.FAISS", FAISS_MODULE)
@patch("langchain_text_splitters.RecursiveCharacterTextSplitter.split_documents")
def test_rag_init_handles_str_docs(
    mock_split_docs, mock_embeddings, mock_vector_store, sample_docs_str, tmp_path
):
    mock_split_docs.return_value = [Document(page_content=s) for s in sample_docs_str]
    with patch.object(FAISS_MODULE, "from_documents", return_value=mock_vector_store):
        EnhancedRAG(
            docs=sample_docs_str,
            embeddings=mock_embeddings,
            vector_store_cls=FAISS_MODULE,
            cache_dir=tmp_path,
        )
        call_args, _ = mock_split_docs.call_args
        input_docs = call_args[0]
        assert all(isinstance(d, Document) for d in input_docs)


def test_get_retriever(mock_vector_store, mock_embeddings, tmp_path):
    rag = EnhancedRAG(embeddings=mock_embeddings, cache_dir=tmp_path)
    rag.vector_store = mock_vector_store
    mock_retriever_instance = MagicMock()
    mock_vector_store.as_retriever.return_value = mock_retriever_instance

    retriever = rag.get_retriever(k=5, score_threshold=0.8)

    mock_vector_store.as_retriever.assert_called_once_with(
        search_kwargs={"k": 5, "score_threshold": 0.8}
    )
    assert retriever is mock_retriever_instance


def test_get_retriever_no_store(mock_embeddings, tmp_path):
    rag = EnhancedRAG(docs=None, embeddings=mock_embeddings, cache_dir=tmp_path)
    assert rag.vector_store is None
    assert rag.get_retriever() is None


def test_get_relevant_context(mock_vector_store, sample_docs_list, mock_embeddings, tmp_path):
    rag = EnhancedRAG(embeddings=mock_embeddings, cache_dir=tmp_path)
    rag.vector_store = mock_vector_store
    mock_vector_store.similarity_search.return_value = sample_docs_list[:2]

    context = rag.get_relevant_context("query", k=2)

    mock_vector_store.similarity_search.assert_called_once_with("query", k=2)
    assert context == "Langchain helps build LLM apps.\n\n---\n\nFAISS is a vector store."


def test_get_relevant_context_no_store(mock_embeddings, tmp_path):
    rag = EnhancedRAG(docs=None, embeddings=mock_embeddings, cache_dir=tmp_path)
    assert rag.get_relevant_context("query") == "Context not available."


def test_get_relevant_context_search_error(mock_vector_store, mock_embeddings, tmp_path):
    rag = EnhancedRAG(embeddings=mock_embeddings, cache_dir=tmp_path)
    rag.vector_store = mock_vector_store
    mock_vector_store.similarity_search.side_effect = Exception("Search failed")

    assert rag.get_relevant_context("query") == "Error retrieving context."


@patch("app.rag.ChatPromptTemplate")
@patch("app.rag.StrOutputParser")
@patch("langchain_core.runnables.RunnablePassthrough")
def test_create_rag_chain_success(
    mock_RunnablePassthrough,
    mock_StrOutputParser,
    mock_ChatPromptTemplate,
    mock_llm,
    mock_vector_store,
    mock_retriever,
    mock_embeddings,
    tmp_path,
):
    rag = EnhancedRAG(embeddings=mock_embeddings, cache_dir=tmp_path)
    rag.vector_store = mock_vector_store
    mock_vector_store.as_retriever.return_value = mock_retriever

    chain = rag.create_rag_chain(llm=mock_llm, retriever_k=5)

    assert chain is not None
    mock_vector_store.as_retriever.assert_called_once_with(search_kwargs={"k": 5})
    mock_ChatPromptTemplate.from_template.assert_called_once()


@patch("app.rag.ChatPromptTemplate")
def test_create_rag_chain_custom_template(
    mock_ChatPromptTemplate,
    mock_llm,
    mock_vector_store,
    mock_retriever,
    mock_embeddings,
    tmp_path,
):
    rag = EnhancedRAG(embeddings=mock_embeddings, cache_dir=tmp_path)
    rag.vector_store = mock_vector_store
    mock_vector_store.as_retriever.return_value = mock_retriever
    custom_template = "Context: {context} Question: {question} Answer:"

    chain = rag.create_rag_chain(llm=mock_llm, prompt_template=custom_template)

    assert chain is not None
    mock_ChatPromptTemplate.from_template.assert_called_once_with(custom_template)


def test_create_rag_chain_no_retriever(mock_llm, mock_embeddings, tmp_path):
    rag = EnhancedRAG(docs=None, embeddings=mock_embeddings, cache_dir=tmp_path)
    assert rag.create_rag_chain(llm=mock_llm) is None


def test_format_docs(sample_docs_list):
    formatted = EnhancedRAG._format_docs(sample_docs_list[:2])
    assert formatted == "Langchain helps build LLM apps.\n\n---\n\nFAISS is a vector store."


def test_format_docs_empty():
    assert EnhancedRAG._format_docs([]) == ""