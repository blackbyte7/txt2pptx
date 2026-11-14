import os
import time

import pytest
from pptx import Presentation

from txt2pptx import pipeline as pipeline_module
from txt2pptx.chains import GenerationError, generate_outline, review_code
from txt2pptx.exporters import cleanup_old_files
from txt2pptx.pipeline import CodeExecutionDisabledError, GenerationOptions, slugify
from txt2pptx.schemas import CodeSafetyReview, GeneratedCode, PresentationOutline, QualityReview


@pytest.fixture
def outline_model(sample_outline):
    return PresentationOutline.model_validate(sample_outline)


@pytest.fixture
def patch_llm(monkeypatch):
    def _patch(fake):
        monkeypatch.setattr(pipeline_module, "create_chat_model", lambda *a, **k: fake)
        return fake

    return _patch


# ------------------------------------------------------------------------------------------ chains --


def test_generate_outline_prompt_and_result(fake_llm_factory, outline_model):
    llm = fake_llm_factory({PresentationOutline: outline_model})
    result = generate_outline(llm, "Some source text", style="Technical", audience="Engineers", max_slides=8)
    assert result is outline_model
    prompt = llm.prompts[0]
    assert "Some source text" in prompt and "Technical" in prompt and "Engineers" in prompt
    assert "4-8 slides" in prompt


def test_generate_outline_accepts_dict(fake_llm_factory, sample_outline):
    llm = fake_llm_factory({PresentationOutline: sample_outline})
    assert isinstance(generate_outline(llm, "x"), PresentationOutline)


def test_generate_outline_none_raises(fake_llm_factory):
    with pytest.raises(GenerationError, match="truncated"):
        generate_outline(fake_llm_factory({PresentationOutline: None}), "x")


def test_review_code_fails_closed(fake_llm_factory):
    verdict = review_code(fake_llm_factory({CodeSafetyReview: RuntimeError("boom")}), "x=1")
    assert verdict.is_safe is False
    assert "boom" in verdict.warnings[0]


def test_retriever_context_is_injected(fake_llm_factory, outline_model):
    from langchain_core.documents import Document
    from langchain_core.runnables import RunnableLambda

    retriever = RunnableLambda(lambda q: [Document(page_content="use add_chart for charts")])
    llm = fake_llm_factory({PresentationOutline: outline_model})
    generate_outline(llm, "x", retriever=retriever)
    assert "use add_chart for charts" in llm.prompts[0]


# ---------------------------------------------------------------------------------------- service --


def test_build_creates_file_with_analysis_and_html(service, sample_outline):
    result = service.build(
        sample_outline, template="minimal", export_formats=["html"], output_name="My Deck!"
    )
    assert result.pptx_path.is_file()
    assert result.pptx_path.parent == service.output_dir.resolve()
    assert result.pptx_path.name.startswith("my-deck_")
    assert result.slide_count == 5
    assert result.analysis is not None
    html = result.exports["html"][0].read_text(encoding="utf-8")
    assert "Q1 sales by region" in html and "<table>" in html
    assert len(Presentation(str(result.pptx_path)).slides) == 5


def test_build_names_are_unique(service, sample_outline):
    a = service.build(sample_outline).pptx_path
    b = service.build(sample_outline).pptx_path
    assert a != b


def test_build_rejects_bad_outline(service):
    with pytest.raises(ValueError):
        service.build({"slides": []})


def test_generate_end_to_end(service, patch_llm, fake_llm_factory, outline_model):
    review = QualityReview(overall_score=88, strengths=["clear"])
    patch_llm(fake_llm_factory({PresentationOutline: outline_model, QualityReview: review}))
    steps = []
    result = service.generate(
        "Text " * 50,
        GenerationOptions(template="dark", ai_review=True, provider="openai"),
        progress=lambda f, m: steps.append((f, m)),
    )
    assert result.review.overall_score == 88
    assert result.template == "dark"
    assert steps[-1] == (1.0, "Done")
    assert [f for f, _ in steps] == sorted(f for f, _ in steps)


def test_generate_truncates_long_input(service, patch_llm, fake_llm_factory, outline_model):
    service.settings.max_input_chars = 2000
    llm = patch_llm(fake_llm_factory({PresentationOutline: outline_model}))
    result = service.generate("y" * 5000, GenerationOptions(provider="openai"))
    assert any("truncated" in w for w in result.warnings)
    assert "y" * 2001 not in llm.prompts[0]


def test_generate_empty_content(service):
    with pytest.raises(ValueError, match="empty"):
        service.generate("   ")


def test_generate_from_file(service, patch_llm, fake_llm_factory, outline_model, tmp_path):
    patch_llm(fake_llm_factory({PresentationOutline: outline_model}))
    src = tmp_path / "Quarterly Notes.md"
    src.write_text("# Notes\nRevenue up", encoding="utf-8")
    result = service.generate_from_file(src, GenerationOptions(provider="anthropic"))
    assert result.pptx_path.name.startswith("quarterly-notes_")


def test_code_method_disabled_by_default(service, patch_llm, fake_llm_factory):
    patch_llm(fake_llm_factory({}))
    with pytest.raises(CodeExecutionDisabledError):
        service.generate("content", GenerationOptions(method="code", provider="openai"))


def test_code_method_when_enabled(service, patch_llm, fake_llm_factory):
    service.settings.enable_code_execution = True
    code = (
        "from pptx import Presentation\nprs = Presentation()\n"
        "s = prs.slides.add_slide(prs.slide_layouts[1])\ns.shapes.title.text = 'Generated'\nprs.save('x.pptx')"
    )
    patch_llm(
        fake_llm_factory(
            {GeneratedCode: GeneratedCode(python_code=code), CodeSafetyReview: CodeSafetyReview(is_safe=True)}
        )
    )
    result = service.generate("content", GenerationOptions(method="code", provider="openai"))
    assert result.method == "code" and result.slide_count == 1


def test_code_method_rejected_by_reviewer(service, patch_llm, fake_llm_factory):
    service.settings.enable_code_execution = True
    patch_llm(
        fake_llm_factory(
            {
                GeneratedCode: GeneratedCode(python_code="x=1"),
                CodeSafetyReview: CodeSafetyReview(is_safe=False, warnings=["sketchy"]),
            }
        )
    )
    with pytest.raises(PermissionError, match="sketchy"):
        service.generate("content", GenerationOptions(method="code", provider="openai"))


def test_resolve_output_file_blocks_traversal(service, sample_outline, tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("x")
    with pytest.raises(FileNotFoundError):
        service.resolve_output_file("../secret.txt")
    with pytest.raises(FileNotFoundError):
        service.resolve_output_file(secret)
    built = service.build(sample_outline).pptx_path
    assert service.resolve_output_file(built.name) == built
    assert service.resolve_output_file(built) == built


def test_export_existing_deck(service, sample_outline):
    built = service.build(sample_outline)
    result = service.export(built.pptx_path.name, ["html"])
    assert result.exports["html"][0].exists()
    assert result.slide_count == 5


def test_rag_skipped_without_openai_key(service, tmp_path):
    from tests.helpers import write_text_pdf

    service.settings.docs_path = write_text_pdf(tmp_path / "docs.pdf", ["python-pptx docs"])
    assert service._retriever(GenerationOptions(provider="anthropic", api_key="ak")) is None


def test_slugify():
    assert slugify("Ünïcode Déck: 2026/Q1!") == "unicode-deck-2026q1"
    assert slugify("!!!") == "presentation"


def test_cleanup_old_files(tmp_path):
    old, new = tmp_path / "old.pptx", tmp_path / "new.pptx"
    old.write_text("x")
    new.write_text("y")
    past = time.time() - 10 * 3600
    os.utime(old, (past, past))
    assert cleanup_old_files(tmp_path, 5) == 1
    assert not old.exists() and new.exists()
    assert cleanup_old_files(tmp_path, 0) == 0
