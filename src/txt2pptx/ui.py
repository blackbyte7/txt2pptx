"""Gradio web interface."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import gradio as gr

from txt2pptx import __version__
from txt2pptx.config import Settings, get_settings
from txt2pptx.exporters import EXPORT_FORMATS
from txt2pptx.llm import MissingAPIKeyError
from txt2pptx.loaders import ALLOWED_EXTENSIONS
from txt2pptx.pipeline import GenerationOptions, PresentationResult, PresentationService

logger = logging.getLogger(__name__)

STYLES = [
    "Professional",
    "Executive summary",
    "Educational",
    "Technical",
    "Sales pitch",
    "Creative",
    "Minimalist",
]
METHOD_OUTLINE = "Structured outline (recommended)"
METHOD_CODE = "Direct python-pptx code (experimental)"
PROVIDERS = {"OpenAI": "openai", "Anthropic": "anthropic"}


def _result_markdown(result: PresentationResult) -> str:
    lines = [f"### ✅ {result.slide_count} slides · template `{result.template}`"]
    if result.export_errors:
        lines.append(
            "**Export problems:** " + "; ".join(f"{k}: {v}" for k, v in result.export_errors.items())
        )
    if result.warnings:
        lines.append("**Rendering notes**\n" + "\n".join(f"- {w}" for w in result.warnings))
    if result.analysis is not None:
        lines.append("#### Content analysis\n" + result.analysis.to_markdown())
    if result.review is not None:
        r = result.review
        parts = [f"#### AI review: {r.overall_score}/100"]
        if r.strengths:
            parts.append("**Strengths**\n" + "\n".join(f"- {s}" for s in r.strengths))
        if r.areas_for_improvement:
            parts.append("**Improve**\n" + "\n".join(f"- {s}" for s in r.areas_for_improvement))
        lines.append("\n\n".join(parts))
    return "\n\n".join(lines)


def _files(result: PresentationResult) -> list[str]:
    return [str(p) for p in result.all_files() if p.exists()]


def _parse_overrides(raw: str | None) -> dict[str, Any] | None:
    if not raw or not raw.strip():
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise gr.Error(f"Template customization is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise gr.Error("Template customization must be a JSON object.")
    return data


def create_app(service: PresentationService | None = None) -> gr.Blocks:
    service = service or PresentationService()
    settings = service.settings
    template_choices = [(f"{t.name} - {t.description}", t.name) for t in service.templates.list_templates()]
    default_template = (
        "professional" if "professional" in service.templates.names() else template_choices[0][1]
    )
    default_provider = {"openai": "OpenAI", "anthropic": "Anthropic"}.get(
        settings.default_provider() or "", "OpenAI"
    )
    caps = service.exporter.capabilities()
    export_choices = [
        (label + ("" if caps[value] else " (unavailable)"), value)
        for label, value in (("PDF", "pdf"), ("Slide images (PNG)", "images"), ("HTML handout", "html"))
    ]
    methods = [METHOD_OUTLINE] + ([METHOD_CODE] if settings.enable_code_execution else [])

    def generate(
        upload: str | None,
        pasted: str,
        style: str,
        audience: str,
        template: str,
        provider_label: str,
        api_key: str,
        method: str,
        max_slides: float,
        exports: list[str],
        analyze: bool,
        ai_review: bool,
        use_rag: bool,
        overrides_raw: str,
        progress: gr.Progress = gr.Progress(),  # noqa: B008 - Gradio injects progress via default
    ) -> tuple[list[str] | None, str, dict[str, Any] | None]:
        if not upload and not (pasted or "").strip():
            raise gr.Error("Upload a document or paste some text first.")
        options = GenerationOptions(
            style=style,
            audience=audience or "General audience",
            template=template,
            template_overrides=_parse_overrides(overrides_raw),
            provider=PROVIDERS.get(provider_label),
            api_key=(api_key or "").strip() or None,
            method="code" if method == METHOD_CODE else "outline",
            max_slides=int(max_slides),
            export_formats=[f for f in exports if f in EXPORT_FORMATS],
            analyze=analyze,
            ai_review=ai_review,
            use_rag=use_rag,
        )

        def report(fraction: float, message: str) -> None:
            progress(fraction, desc=message)

        try:
            if upload:
                result = service.generate_from_file(upload, options, report)
            else:
                result = service.generate(pasted, options, report)
        except gr.Error:
            raise
        except (MissingAPIKeyError, ValueError, PermissionError, FileNotFoundError) as exc:
            raise gr.Error(str(exc)) from exc
        except Exception as exc:
            logger.exception("Generation failed")
            raise gr.Error(f"Generation failed: {exc}") from exc

        for fmt, err in result.export_errors.items():
            gr.Warning(f"{fmt.upper()} export failed: {err}")
        outline = result.outline.model_dump(mode="json", exclude_none=True) if result.outline else None
        return _files(result), _result_markdown(result), outline

    def rebuild(
        outline_json: dict[str, Any] | str | None, template: str, exports: list[str], overrides_raw: str
    ) -> tuple[list[str], str]:
        if not outline_json:
            raise gr.Error("Paste or generate an outline first.")
        try:
            data = json.loads(outline_json) if isinstance(outline_json, str) else outline_json
            result = service.build(
                data,
                template=template,
                template_overrides=_parse_overrides(overrides_raw),
                export_formats=[f for f in exports if f in EXPORT_FORMATS],
            )
        except gr.Error:
            raise
        except Exception as exc:
            raise gr.Error(f"Could not build the deck: {exc}") from exc
        return _files(result), _result_markdown(result)

    with gr.Blocks(title="txt2pptx") as app:
        gr.Markdown(
            f"# txt2pptx <small>v{__version__}</small>\n"
            "Turn documents or notes into a polished PowerPoint deck. "
            "Upload a file (" + ", ".join(ALLOWED_EXTENSIONS) + ") or paste text."
        )
        with gr.Row(equal_height=False):
            with gr.Column(scale=5):
                with gr.Tab("Upload"):
                    upload = gr.File(label="Document", file_types=list(ALLOWED_EXTENSIONS), type="filepath")
                with gr.Tab("Paste text"):
                    pasted = gr.Textbox(
                        label="Content", lines=12, placeholder="Paste notes, an article, a report…"
                    )
                with gr.Row():
                    template = gr.Dropdown(template_choices, value=default_template, label="Visual template")
                    style = gr.Dropdown(STYLES, value="Professional", label="Tone", allow_custom_value=True)
                with gr.Row():
                    audience = gr.Textbox(label="Audience", value="General audience")
                    max_slides = gr.Slider(
                        3, settings.max_slides, value=min(12, settings.max_slides), step=1, label="Max slides"
                    )
                with gr.Row():
                    provider = gr.Dropdown(list(PROVIDERS), value=default_provider, label="AI provider")
                    api_key = gr.Textbox(
                        label="API key (optional if configured on the server)", type="password", max_lines=1
                    )
                exports = gr.CheckboxGroup(export_choices, value=[], label="Also export as")
                with gr.Accordion("Advanced", open=False):
                    method = gr.Radio(methods, value=METHOD_OUTLINE, label="Generation method")
                    with gr.Row():
                        analyze = gr.Checkbox(True, label="Content analysis")
                        ai_review = gr.Checkbox(False, label="AI review (extra LLM call)")
                        use_rag = gr.Checkbox(True, label="Use reference docs (needs OpenAI key)")
                    overrides = gr.Code(
                        label='Template customization (JSON), e.g. {"colors": {"accent1": "#FF5500"}}',
                        language="json",
                        lines=5,
                    )
                go = gr.Button("Generate presentation", variant="primary", size="lg")
            with gr.Column(scale=4):
                files = gr.Files(label="Download", interactive=False)
                summary = gr.Markdown()
                with gr.Accordion("Outline (edit & rebuild without the AI)", open=False):
                    outline = gr.JSON(label="Outline")
                    outline_edit = gr.Code(label="Edit outline JSON", language="json", lines=14)
                    with gr.Row():
                        load_btn = gr.Button("Copy outline into editor")
                        rebuild_btn = gr.Button("Rebuild deck", variant="secondary")

        go.click(
            generate,
            inputs=[
                upload,
                pasted,
                style,
                audience,
                template,
                provider,
                api_key,
                method,
                max_slides,
                exports,
                analyze,
                ai_review,
                use_rag,
                overrides,
            ],
            outputs=[files, summary, outline],
            concurrency_limit=4,
            api_visibility="private",
        )
        load_btn.click(
            lambda o: json.dumps(o, indent=2) if o else "",
            inputs=outline,
            outputs=outline_edit,
            api_visibility="private",
        )
        rebuild_btn.click(
            rebuild,
            inputs=[outline_edit, template, exports, overrides],
            outputs=[files, summary],
            api_visibility="private",
        )
    return app


def launch(settings: Settings | None = None, *, host: str | None = None, port: int | None = None) -> None:
    settings = settings or get_settings()
    service = PresentationService(settings)
    host = host or settings.server_name
    auth = None
    if settings.ui_auth:
        user, _, password = settings.ui_auth.get_secret_value().partition(":")
        if not password:
            raise ValueError("TXT2PPTX_UI_AUTH must look like 'user:password'")
        auth = (user, password)
    elif host not in {"127.0.0.1", "localhost", "::1"}:
        logger.warning("Web UI is exposed on %s without authentication (set TXT2PPTX_UI_AUTH).", host)
    app = create_app(service)
    app.queue(default_concurrency_limit=4)
    app.launch(
        server_name=host,
        server_port=port or settings.server_port,
        auth=auth,
        max_file_size=f"{settings.max_upload_mb}mb",
        allowed_paths=[str(Path(service.output_dir).resolve())],
        theme=gr.themes.Soft(),
        show_error=True,
        footer_links=["gradio"],
    )
