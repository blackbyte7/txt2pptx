import pickle
from unittest.mock import patch, MagicMock, mock_open

import pytest
from langchain_core.documents import Document

from app.rag import EnhancedRAG, FAISS_AVAILABLE

if not FAISS_AVAILABLE:
    class MockFAISS:
        @staticmethod
        def from_documents(docs, embeds):
            store = MockFAISS()
            store._docs = docs
            store._embeds = embeds
            store._retriever = MagicMock()
            store._retriever.invoke.return_value = docs[:1]
            store.similarity_search = MagicMock(return_value=docs[:1])
            return store

        def as_retriever(self, **kwargs):
            retriever = MagicMock()
            retriever.invoke.return_value = self._docs[:kwargs.get("k", 1)]
            retriever.get_relevant_documents.return_value = self._docs[:kwargs.get("k", 1)]
            return retriever


    FAISS_MODULE = MockFAISS
else:
    from langchain_community.vectorstores import FAISS

    FAISS_MODULE = FAISS

from tests.conftest import mock_embeddings, mock_vector_store, mock_llm


@pytest.fixture
def sample_docs_list():
    return [
        Document(page_content="Langchain helps build LLM apps."),
        Document(page_content="FAISS is a vector store."),
        Document(page_content="RAG enhances LLM context."),
        Document(page_content="Embeddings represent text numerically.")
    ]


@pytest.fixture
def sample_docs_str():
    return [
        "Langchain helps build LLM apps.",
        "FAISS is a vector store.",
        "RAG enhances LLM context.",
        "Embeddings represent text numerically."
    ]


@patch('app.rag.FAISS', FAISS_MODULE)
@patch('app.rag.pickle.dump')
@patch('app.rag.pickle.load')
@patch('pathlib.Path.exists')
@patch('builtins.open', new_callable=mock_open)
@patch('pathlib.Path.unlink')
def test_rag_init_loads_from_cache(mock_unlink, mock_open_file, mock_exists, mock_load, mock_dump, mock_embeddings, mock_vector_store, tmp_path):
    cache_dir = tmp_path / "rag_cache"
    cache_name = "test_store"
    cache_file = cache_dir / f"{cache_name}.pkl"

    mock_exists.return_value = True
    mock_loaded_store = MagicMock(spec=FAISS_MODULE)
    mock_load.return_value = mock_loaded_store

    rag = EnhancedRAG(embeddings=mock_embeddings, vector_store_cls=FAISS_MODULE, cache_dir=cache_dir,
                      cache_name=cache_name)

    mock_exists.assert_called_once()
    mock_open_file.assert_called_once_with(cache_file, 'rb')
    mock_load.assert_called_once()
    mock_dump.assert_not_called()
    mock_unlink.assert_not_called()
    assert rag.vector_store is mock_loaded_store
    assert rag.cache_file == cache_file


@patch('app.rag.FAISS', FAISS_MODULE)
@patch('app.rag.pickle.dump')
@patch('app.rag.pickle.load', side_effect=pickle.UnpicklingError("corrupt"))
@patch('pathlib.Path.exists')
@patch('pathlib.Path.unlink')
@patch('builtins.open', new_callable=mock_open)
@patch('langchain_text_splitters.RecursiveCharacterTextSplitter.split_documents')
def test_rag_init_recreates_on_cache_load_error(mock_split_docs, mock_open_file, mock_unlink, mock_exists, mock_load, mock_dump,
                                                mock_embeddings, mock_vector_store, sample_docs_list, tmp_path):
    cache_dir = tmp_path / "rag_cache"
    cache_name = "test_store"
    cache_file = cache_dir / f"{cache_name}.pkl"

    mock_exists.return_value = True
    mock_vector_store.as_retriever = MagicMock()
    mock_vector_store.similarity_search = MagicMock()

    mock_split_docs.return_value = sample_docs_list

    with patch.object(FAISS_MODULE, 'from_documents', return_value=mock_vector_store) as mock_from_docs:
        rag = EnhancedRAG(docs=sample_docs_list, embeddings=mock_embeddings, vector_store_cls=FAISS_MODULE,
                          cache_dir=cache_dir, cache_name=cache_name)

        mock_exists.assert_called_once()
        mock_open_file.assert_any_call(cache_file, 'rb')
        mock_open_file.assert_any_call(cache_file, 'wb')
        # assert mock_open_file.call_count >= 2

        mock_load.assert_called_once()
        mock_unlink.assert_called_once()
        mock_split_docs.assert_called_once_with(sample_docs_list)
        mock_from_docs.assert_called_once_with(sample_docs_list, mock_embeddings)
        mock_dump.assert_called_once_with(mock_vector_store, mock_open_file().__enter__())
        # mock_open_file.assert_called_with(cache_file, 'wb')
        assert rag.vector_store is mock_vector_store


@patch('app.rag.FAISS', FAISS_MODULE)
@patch('app.rag.pickle.dump')
@patch('app.rag.Path.exists', return_value=False)
@patch('langchain_text_splitters.RecursiveCharacterTextSplitter.split_documents')
def test_rag_init_creates_new_store(mock_split_docs, mock_exists, mock_dump, mock_embeddings, mock_vector_store,
                                    sample_docs_list, tmp_path):
    cache_dir = tmp_path / "rag_cache"
    cache_name = "test_store"
    mock_split_docs.return_value = sample_docs_list

    with patch.object(FAISS_MODULE, 'from_documents', return_value=mock_vector_store) as mock_from_docs:
        rag = EnhancedRAG(docs=sample_docs_list, embeddings=mock_embeddings, vector_store_cls=FAISS_MODULE,
                          cache_dir=cache_dir, cache_name=cache_name)

        mock_exists.assert_called_once()
        mock_split_docs.assert_called_once_with(sample_docs_list)
        mock_from_docs.assert_called_once_with(sample_docs_list, mock_embeddings)
        mock_dump.assert_called_once()
        assert rag.vector_store is mock_vector_store


@patch('app.rag.FAISS', FAISS_MODULE)
@patch('app.rag.Path.exists', return_value=False)
def test_rag_init_no_docs_no_cache(mock_exists, mock_embeddings, tmp_path):
    rag = EnhancedRAG(docs=None, embeddings=mock_embeddings, vector_store_cls=FAISS_MODULE, cache_dir=tmp_path)
    mock_exists.assert_called_once()
    assert rag.vector_store is None


@patch('app.rag.FAISS', FAISS_MODULE)
@patch('app.rag.Path.exists', return_value=False)
@patch('langchain_text_splitters.RecursiveCharacterTextSplitter.split_documents')
def test_rag_init_handles_str_docs(mock_split_docs, mock_exists, mock_embeddings, mock_vector_store, sample_docs_str,
                                   tmp_path):
    """ Test if list of strings is correctly converted to Documents """
    mock_split_docs.return_value = [Document(page_content=s) for s in sample_docs_str]
    with patch.object(FAISS_MODULE, 'from_documents', return_value=mock_vector_store) as mock_from_docs:
        rag = EnhancedRAG(docs=sample_docs_str, embeddings=mock_embeddings, vector_store_cls=FAISS_MODULE,
                          cache_dir=tmp_path)

        mock_split_docs.assert_called_once()
        call_args, _ = mock_split_docs.call_args
        input_docs_to_splitter = call_args[0]
        assert isinstance(input_docs_to_splitter, list)
        assert all(isinstance(d, Document) for d in input_docs_to_splitter)
        assert input_docs_to_splitter[0].page_content == sample_docs_str[0]

        mock_from_docs.assert_called_once()


def test_get_retriever(mock_vector_store, mock_embeddings):
    rag = EnhancedRAG(embeddings=mock_embeddings)
    rag.vector_store = mock_vector_store
    mock_retriever_instance = MagicMock()
    mock_vector_store.as_retriever.return_value = mock_retriever_instance

    retriever = rag.get_retriever(k=5, score_threshold=0.8)

    mock_vector_store.as_retriever.assert_called_once_with(search_kwargs={"k": 5, "score_threshold": 0.8})
    assert retriever is mock_retriever_instance


def test_get_retriever_no_store(mock_embeddings):
    rag = EnhancedRAG(docs=None, embeddings=mock_embeddings)
    assert rag.vector_store is None
    retriever = rag.get_retriever()
    assert retriever is None


def test_get_relevant_context(mock_vector_store, sample_docs_list, mock_embeddings):
    rag = EnhancedRAG(embeddings=mock_embeddings)
    rag.vector_store = mock_vector_store
    mock_vector_store.similarity_search.return_value = sample_docs_list[:2]

    context = rag.get_relevant_context("query", k=2)

    mock_vector_store.similarity_search.assert_called_once_with("query", k=2)
    expected_context = "Langchain helps build LLM apps.\n\n---\n\nFAISS is a vector store."
    assert context == expected_context


def test_get_relevant_context_no_store(mock_embeddings):
    rag = EnhancedRAG(docs=None, embeddings=mock_embeddings)
    context = rag.get_relevant_context("query")
    assert context == "Context not available."


def test_get_relevant_context_search_error(mock_vector_store, mock_embeddings):
    rag = EnhancedRAG(embeddings=mock_embeddings)
    rag.vector_store = mock_vector_store
    mock_vector_store.similarity_search.side_effect = Exception("Search failed")

    context = rag.get_relevant_context("query")
    assert context == "Error retrieving context."


@patch('app.rag.ChatPromptTemplate')
@patch('app.rag.StrOutputParser')
@patch('langchain_core.runnables.RunnablePassthrough')
def test_create_rag_chain_success(mock_RunnablePassthrough, mock_StrOutputParser, mock_ChatPromptTemplate, mock_llm,
                                  mock_vector_store, mock_retriever, mock_embeddings): # Add mock_embeddings
    rag = EnhancedRAG(embeddings=mock_embeddings)
    rag.vector_store = mock_vector_store
    mock_vector_store.as_retriever.return_value = mock_retriever
    mock_prompt_instance = MagicMock()
    mock_ChatPromptTemplate.from_template.return_value = mock_prompt_instance
    mock_parser_instance = MagicMock()
    mock_StrOutputParser.return_value = mock_parser_instance
    mock_passthrough_instance = MagicMock()
    mock_RunnablePassthrough.return_value = mock_passthrough_instance

    chain = rag.create_rag_chain(llm=mock_llm, retriever_k=5)

    assert chain is not None
    mock_vector_store.as_retriever.assert_called_once_with(search_kwargs={"k": 5})
    mock_ChatPromptTemplate.from_template.assert_called_once()


@patch('app.rag.ChatPromptTemplate')
def test_create_rag_chain_custom_template(mock_ChatPromptTemplate, mock_llm, mock_vector_store, mock_retriever, mock_embeddings):

    rag = EnhancedRAG(embeddings=mock_embeddings)
    rag.vector_store = mock_vector_store
    mock_vector_store.as_retriever.return_value = mock_retriever
    custom_template = "Context: {context} Question: {question} Answer:"

    chain = rag.create_rag_chain(llm=mock_llm, prompt_template=custom_template)

    assert chain is not None
    mock_ChatPromptTemplate.from_template.assert_called_once_with(custom_template)


def test_create_rag_chain_no_retriever(mock_llm, mock_embeddings):
    rag = EnhancedRAG(docs=None, embeddings=mock_embeddings)
    chain = rag.create_rag_chain(llm=mock_llm)
    assert chain is None


def test_format_docs(sample_docs_list):
    formatted = EnhancedRAG._format_docs(sample_docs_list[:2])
    expected = "Langchain helps build LLM apps.\n\n---\n\nFAISS is a vector store."
    assert formatted == expected


def test_format_docs_empty():
    formatted = EnhancedRAG._format_docs([])
    assert formatted == ""
