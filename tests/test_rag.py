from langchain_core.documents import Document
from langchain_core.embeddings import DeterministicFakeEmbedding

from txt2pptx.rag import DocumentationIndex


class CountingEmbeddings(DeterministicFakeEmbedding):
    calls: int = 0

    def embed_documents(self, texts):
        self.calls += 1
        return super().embed_documents(texts)


def _docs(extra=""):
    return [
        Document(
            page_content="Use shapes.add_chart(chart_type, x, y, cx, cy, chart_data) to add charts." + extra
        ),
        Document(
            page_content="Tables are created with shapes.add_table(rows, cols, left, top, width, height)."
        ),
    ]


def test_index_builds_caches_as_json_and_reloads(tmp_path):
    embeddings = CountingEmbeddings(size=32)
    index = DocumentationIndex(_docs(), embeddings, tmp_path, model_id="fake")
    hits = index.retriever(k=1).invoke("add_table rows cols")
    assert len(hits) == 1
    assert index.cache_file.exists() and index.cache_file.suffix == ".json"  # JSON, never pickle
    assert embeddings.calls == 1

    reloaded = DocumentationIndex(_docs(), embeddings, tmp_path, model_id="fake")
    reloaded.retriever().invoke("charts")
    assert embeddings.calls == 1  # served from cache, no re-embedding


def test_cache_key_changes_with_content_and_model(tmp_path):
    e = DeterministicFakeEmbedding(size=8)
    base = DocumentationIndex(_docs(), e, tmp_path, model_id="m1").cache_key
    assert DocumentationIndex(_docs("!"), e, tmp_path, model_id="m1").cache_key != base
    assert DocumentationIndex(_docs(), e, tmp_path, model_id="m2").cache_key != base


def test_corrupt_cache_is_rebuilt(tmp_path):
    e = DeterministicFakeEmbedding(size=8)
    index = DocumentationIndex(_docs(), e, tmp_path, model_id="m")
    index.cache_file.parent.mkdir(parents=True, exist_ok=True)
    index.cache_file.write_text("{broken")
    assert index.retriever(k=2).invoke("charts")
