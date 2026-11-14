"""High-level presentation service shared by the web UI, the CLI and the MCP server."""

from __future__ import annotations

import hashlib
import logging
import re
import threading
import time
import unicodedata
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from langchain_core.documents import Document
from langchain_core.language_models import BaseChatModel
from langchain_core.retrievers import BaseRetriever
from pydantic import BaseModel, Field

from txt2pptx.analyzers import ContentAnalyzer
from txt2pptx.chains import generate_code, generate_outline, review_code, review_outline
from txt2pptx.config import Settings, get_settings
from txt2pptx.exporters import PresentationExporter, cleanup_old_files
from txt2pptx.llm import create_chat_model, resolve_provider
from txt2pptx.loaders import load_documents, load_text
from txt2pptx.pptx_generator import PPTXGenerator
from txt2pptx.rag import DocumentationIndex, openai_embeddings
from txt2pptx.sandbox import execute_presentation_code
from txt2pptx.schemas import AnalysisReport, PresentationOutline, QualityReview
from txt2pptx.templates import TemplateManager

logger = logging.getLogger(__name__)

GenerationMethod = Literal["outline", "code"]
ProgressCallback = Callable[[float, str], None]


def _no_progress(_fraction: float, _message: str) -> None:
    return None


class CodeExecutionDisabledError(PermissionError):
    pass


@dataclass
class GenerationOptions:
    style: str = "Professional"
    audience: str = "General audience"
    template: str = "professional"
    template_overrides: dict[str, Any] | None = None
    provider: str | None = None
    api_key: str | None = field(default=None, repr=False)
    model: str | None = None
    method: GenerationMethod = "outline"
    max_slides: int = 12
    export_formats: Sequence[str] = ()
    analyze: bool = True
    ai_review: bool = False
    use_rag: bool = True
    output_name: str | None = None


class PresentationResult(BaseModel):
    pptx_path: Path = Field(description="Absolute path of the generated .pptx file.")
    slide_count: int
    template: str
    method: str
    exports: dict[str, list[Path]] = Field(default_factory=dict)
    export_errors: dict[str, str] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    analysis: AnalysisReport | None = None
    review: QualityReview | None = None
    outline: PresentationOutline | None = None

    def all_files(self) -> list[Path]:
        return [self.pptx_path, *(p for paths in self.exports.values() for p in paths)]


class PresentationService:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        s = self.settings
        templates_dir = s.resolve(s.templates_dir) if s.templates_dir else None
        self.templates = TemplateManager(templates_dir)
        self.output_dir = s.output_path
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.exporter = PresentationExporter(self.output_dir)
        self.analyzer = ContentAnalyzer()
        self._reference_docs: list[Document] | None = None
        self._indexes: dict[str, DocumentationIndex] = {}
        self._lock = threading.Lock()
        cleanup_old_files(self.output_dir, s.export_retention_hours)

    # ------------------------------------------------------------------------------ deterministic --
    def build(
        self,
        outline: PresentationOutline | dict[str, Any],
        *,
        template: str = "professional",
        template_overrides: dict[str, Any] | None = None,
        export_formats: Sequence[str] = (),
        output_name: str | None = None,
        analyze: bool = True,
        method: str = "outline",
        extra_warnings: Sequence[str] = (),
    ) -> PresentationResult:
        """Render an outline to .pptx (and optional exports). No LLM involved."""
        if not isinstance(outline, PresentationOutline):
            outline = PresentationOutline.model_validate(outline)
        tpl = self.templates.customize(template, template_overrides)
        path = self._new_output_path(output_name or outline.metadata.title or outline.slides[0].title)
        render = PPTXGenerator(tpl).save(outline, path)
        result = PresentationResult(
            pptx_path=path.resolve(),
            slide_count=len(outline.slides),
            template=tpl.name,
            method=method,
            warnings=[*extra_warnings, *render.warnings],
            analysis=self.analyzer.analyze(outline) if analyze else None,
            outline=outline,
        )
        self._export_into(result, export_formats)
        logger.info("Built %s (%d slides)", path.name, result.slide_count)
        return result

    def export(self, pptx_file: str | Path, formats: Sequence[str]) -> PresentationResult:
        """Export a previously generated deck (must live in the output directory)."""
        from pptx import Presentation

        path = self.resolve_output_file(pptx_file)
        slide_count = len(Presentation(str(path)).slides)
        result = PresentationResult(pptx_path=path, slide_count=slide_count, template="", method="export")
        self._export_into(result, formats)
        return result

    def analyze(self, outline: PresentationOutline | dict[str, Any]) -> AnalysisReport:
        if not isinstance(outline, PresentationOutline):
            outline = PresentationOutline.model_validate(outline)
        return self.analyzer.analyze(outline)

    # ------------------------------------------------------------------------------------- LLM --
    def generate(
        self,
        content: str,
        options: GenerationOptions | None = None,
        progress: ProgressCallback = _no_progress,
    ) -> PresentationResult:
        """Create a deck from free text using the configured LLM."""
        options = options or GenerationOptions()
        content, warnings = self._prepare_content(content)
        max_slides = max(1, min(options.max_slides, self.settings.max_slides))

        progress(0.05, "Connecting to the language model")
        llm = self._llm(options)
        retriever = self._retriever(options) if options.use_rag else None

        if options.method == "code":
            return self._generate_via_code(content, options, llm, retriever, warnings, progress)

        progress(0.15, "Drafting the slide outline")
        outline = generate_outline(
            llm,
            content,
            style=options.style,
            audience=options.audience,
            max_slides=max_slides,
            retriever=retriever,
        )
        review = None
        if options.ai_review:
            progress(0.6, "Reviewing the outline")
            try:
                review = review_outline(llm, outline, audience=options.audience)
            except Exception as exc:
                warnings.append(f"AI review skipped: {exc}")

        progress(0.75, "Rendering slides")
        result = self.build(
            outline,
            template=options.template,
            template_overrides=options.template_overrides,
            export_formats=(),
            output_name=options.output_name,
            analyze=options.analyze,
            extra_warnings=warnings,
        )
        result.review = review
        if options.export_formats:
            progress(0.88, "Exporting")
            self._export_into(result, options.export_formats)
        progress(1.0, "Done")
        return result

    def generate_from_file(
        self,
        path: str | Path,
        options: GenerationOptions | None = None,
        progress: ProgressCallback = _no_progress,
    ) -> PresentationResult:
        progress(0.02, "Reading the document")
        text = load_text(path, max_bytes=self.settings.max_upload_mb * 1024 * 1024)
        if not text.strip():
            raise ValueError("No text could be extracted from the document.")
        options = options or GenerationOptions()
        if not options.output_name:
            options.output_name = Path(path).stem
        return self.generate(text, options, progress)

    def _generate_via_code(
        self,
        content: str,
        options: GenerationOptions,
        llm: BaseChatModel,
        retriever: BaseRetriever | None,
        warnings: list[str],
        progress: ProgressCallback,
    ) -> PresentationResult:
        if not self.settings.enable_code_execution:
            raise CodeExecutionDisabledError(
                "Code generation mode is disabled. Set TXT2PPTX_ENABLE_CODE_EXECUTION=true to enable it."
            )
        tpl = self.templates.customize(options.template, options.template_overrides)
        progress(0.15, "Writing python-pptx code")
        generated = generate_code(
            llm, content, style=options.style, template_data=tpl.model_dump(), retriever=retriever
        )
        progress(0.55, "Reviewing generated code")
        verdict = review_code(llm, generated.python_code)
        if not verdict.is_safe:
            raise PermissionError("Generated code rejected: " + "; ".join(verdict.warnings))
        progress(0.7, "Running generated code in an isolated process")
        path = self._new_output_path(options.output_name or "presentation")
        execute_presentation_code(generated.python_code, path, timeout=self.settings.code_execution_timeout)

        from pptx import Presentation

        result = PresentationResult(
            pptx_path=path.resolve(),
            slide_count=len(Presentation(str(path)).slides),
            template=tpl.name,
            method="code",
            warnings=warnings,
        )
        if options.export_formats:
            progress(0.88, "Exporting")
            self._export_into(result, options.export_formats)
        progress(1.0, "Done")
        return result

    # --------------------------------------------------------------------------------- helpers --
    def _prepare_content(self, content: str) -> tuple[str, list[str]]:
        content = (content or "").strip()
        if not content:
            raise ValueError("Content is empty.")
        warnings: list[str] = []
        limit = self.settings.max_input_chars
        if len(content) > limit:
            warnings.append(f"Input truncated from {len(content):,} to {limit:,} characters.")
            content = content[:limit]
        return content, warnings

    def _llm(self, options: GenerationOptions) -> BaseChatModel:
        return create_chat_model(self.settings, options.provider, options.api_key, options.model)

    def _retriever(self, options: GenerationOptions) -> BaseRetriever | None:
        docs_path = self.settings.resolved_docs_path
        if not docs_path or not docs_path.is_file():
            return None
        provider = resolve_provider(self.settings, options.provider)
        key = (options.api_key if provider == "openai" else None) or self.settings.api_key_for("openai")
        if not key:
            logger.info("Reference-doc retrieval needs an OpenAI key for embeddings; skipping.")
            return None
        index_id = hashlib.sha256(f"{key}|{self.settings.embedding_model}".encode()).hexdigest()
        try:
            with self._lock:
                if self._reference_docs is None:
                    self._reference_docs = load_documents(docs_path)
                index = self._indexes.get(index_id)
                if index is None:
                    index = DocumentationIndex(
                        self._reference_docs,
                        openai_embeddings(key, self.settings.embedding_model),
                        self.settings.cache_path / "rag",
                        model_id=self.settings.embedding_model,
                    )
                    self._indexes[index_id] = index
            return index.retriever()
        except Exception as exc:
            logger.warning("Reference-doc retrieval unavailable: %s", exc)
            return None

    def _export_into(self, result: PresentationResult, formats: Sequence[str]) -> None:
        if not formats:
            return
        exported = self.exporter.export(result.pptx_path, list(formats))
        result.exports.update({k: [p.resolve() for p in v] for k, v in exported.files.items()})
        result.export_errors.update(exported.errors)

    def _new_output_path(self, name: str) -> Path:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        return self.output_dir / f"{slugify(name)}_{stamp}_{uuid.uuid4().hex[:6]}.pptx"

    def resolve_output_file(self, name: str | Path) -> Path:
        """Resolve *name* (relative or absolute) inside the output directory, rejecting path traversal."""
        base = self.output_dir.resolve()
        raw = Path(name)
        candidate = (raw if raw.is_absolute() else base / raw).resolve()
        if not candidate.is_relative_to(base) or not candidate.is_file():
            raise FileNotFoundError(f"No generated file {str(name)!r} in the output directory")
        return candidate


def slugify(value: str, max_length: int = 48) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    value = re.sub(r"[^\w\s-]", "", value).strip().lower()
    value = re.sub(r"[-\s]+", "-", value)
    return value[:max_length].strip("-_") or "presentation"
