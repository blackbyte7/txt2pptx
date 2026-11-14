"""Model Context Protocol (MCP) server for txt2pptx.

Run it with ``txt2pptx-mcp`` (stdio, for Claude Desktop / Claude Code / IDEs) or
``txt2pptx-mcp --transport streamable-http`` (remote / Docker).

The client's own LLM writes a :class:`~txt2pptx.schemas.PresentationOutline` and calls
``create_presentation``. No API key is needed on the server for that path. ``generate_presentation``
(server-side LLM) is only registered when the server has an OpenAI or Anthropic key configured.
"""

# NOTE: no ``from __future__ import annotations`` here - the MCP SDK inspects real annotations.

import argparse
import logging
import os
from pathlib import Path
from typing import Annotated, Any, Literal

import anyio
import anyio.from_thread
import anyio.to_thread
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from txt2pptx import __version__
from txt2pptx.config import Settings, get_settings
from txt2pptx.llm import MissingAPIKeyError
from txt2pptx.logging_config import setup_logging
from txt2pptx.pipeline import GenerationOptions, PresentationResult, PresentationService
from txt2pptx.prompts import OUTLINE_GUIDELINES
from txt2pptx.schemas import AnalysisReport, PresentationOutline
from txt2pptx.templates import TemplateInfo

logger = logging.getLogger(__name__)

PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
ExportFormat = Literal["pdf", "html", "images"]

INSTRUCTIONS = f"""\
txt2pptx renders professional PowerPoint (.pptx) decks.

Preferred workflow: read/understand the user's material yourself, write a PresentationOutline and call
`create_presentation`. Call `list_templates` to pick a visual style. The result contains the absolute path
of the .pptx file and a `txt2pptx://exports/...` resource URI with the file contents.

{OUTLINE_GUIDELINES}"""


class DeckResult(BaseModel):
    """Outcome of a deck build."""

    pptx_path: str = Field(description="Absolute path of the .pptx on the server's file system.")
    resource_uri: str = Field(description="MCP resource URI that returns the .pptx bytes.")
    slide_count: int
    template: str
    exports: dict[str, list[str]] = Field(default_factory=dict, description="Additional exported files.")
    export_errors: dict[str, str] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list, description="Rendering notes (e.g. truncated tables).")
    analysis: AnalysisReport | None = Field(None, description="Heuristic content feedback.")

    @classmethod
    def from_result(cls, result: PresentationResult) -> "DeckResult":
        return cls(
            pptx_path=str(result.pptx_path),
            resource_uri=f"txt2pptx://exports/{result.pptx_path.name}",
            slide_count=result.slide_count,
            template=result.template,
            exports={k: [str(p) for p in v] for k, v in result.exports.items()},
            export_errors=result.export_errors,
            warnings=result.warnings,
            analysis=result.analysis,
        )


def _progress_reporter(ctx: Context):
    def report(fraction: float, message: str) -> None:
        try:
            anyio.from_thread.run(ctx.report_progress, round(fraction * 100), 100, message)
        except Exception:  # progress is best effort
            logger.debug("Progress notification failed", exc_info=True)

    return report


def create_server(service: PresentationService | None = None) -> MCPServer:
    service = service or PresentationService()
    settings = service.settings
    mcp = MCPServer(
        name="txt2pptx",
        title="txt2pptx - PowerPoint generator",
        description="Create professional PowerPoint decks from outlines or raw text.",
        version=__version__,
        instructions=INSTRUCTIONS,
    )

    def _check_template(name: str) -> None:
        if name not in service.templates.names():
            raise ToolError(f"Unknown template {name!r}. Available: {', '.join(service.templates.names())}")

    # ------------------------------------------------------------------------------------ tools --
    @mcp.tool(
        title="List visual templates",
        annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False),
    )
    def list_templates() -> list[TemplateInfo]:
        """List the available visual templates (name, description, colors)."""
        return service.templates.list_templates()

    @mcp.tool(
        title="Create presentation from outline",
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False),
    )
    async def create_presentation(
        outline: PresentationOutline,
        template: Annotated[str, Field(description="Template name from list_templates.")] = "professional",
        template_overrides: Annotated[
            dict[str, Any] | None,
            Field(description='Optional deep-merged overrides, e.g. {"colors": {"accent1": "#FF5500"}}.'),
        ] = None,
        export_formats: Annotated[
            list[ExportFormat] | None, Field(description="Extra formats (needs LibreOffice for pdf/images).")
        ] = None,
        output_name: Annotated[str | None, Field(description="Base file name (no extension).")] = None,
    ) -> DeckResult:
        """Render a structured outline into a .pptx deck (deterministic, no LLM call).

        Use slide_type 'title' for the first slide and 'closing' for the last. Element types: text
        (bullets), table, chart (bar/column/stacked_bar/stacked_column/line/pie/doughnut/area) and
        image_placeholder. Keep at most two content elements per slide.
        """
        _check_template(template)
        logger.info("MCP create_presentation: %d slides, template %s", len(outline.slides), template)
        try:
            result = await anyio.to_thread.run_sync(
                lambda: service.build(
                    outline,
                    template=template,
                    template_overrides=template_overrides,
                    export_formats=export_formats or (),
                    output_name=output_name,
                )
            )
        except ValueError as exc:
            raise ToolError(str(exc)) from exc
        return DeckResult.from_result(result)

    @mcp.tool(
        title="Analyze outline",
        annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False),
    )
    def analyze_outline(outline: PresentationOutline) -> AnalysisReport:
        """Check an outline for common presentation problems before rendering it."""
        return service.analyze(outline)

    @mcp.tool(
        title="Export presentation",
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False),
    )
    async def export_presentation(
        file: Annotated[
            str, Field(description="File name (or path) of a deck previously created by this server.")
        ],
        formats: list[ExportFormat],
    ) -> DeckResult:
        """Export a previously generated deck to PDF, slide images (PNG) and/or an HTML handout."""
        try:
            result = await anyio.to_thread.run_sync(lambda: service.export(file, formats))
        except FileNotFoundError as exc:
            raise ToolError(str(exc)) from exc
        return DeckResult.from_result(result)

    if settings.default_provider():

        @mcp.tool(
            title="Generate presentation from text (server-side LLM)",
            annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=True),
        )
        async def generate_presentation(
            content: Annotated[str, Field(description="Source text to turn into a deck.")],
            ctx: Context,
            style: str = "Professional",
            audience: str = "General audience",
            template: str = "professional",
            max_slides: Annotated[int, Field(ge=3, le=settings.max_slides)] = 12,
            provider: Literal["openai", "anthropic"] | None = None,
            export_formats: list[ExportFormat] | None = None,
            output_name: str | None = None,
        ) -> DeckResult:
            """Let the server's own LLM draft the outline from raw text, then render it.

            Prefer `create_presentation` when you can write the outline yourself.
            """
            _check_template(template)
            options = GenerationOptions(
                style=style,
                audience=audience,
                template=template,
                provider=provider,
                max_slides=max_slides,
                export_formats=export_formats or (),
                output_name=output_name,
            )
            report = _progress_reporter(ctx)
            try:
                result = await anyio.to_thread.run_sync(lambda: service.generate(content, options, report))
            except (MissingAPIKeyError, ValueError, PermissionError) as exc:
                raise ToolError(str(exc)) from exc
            return DeckResult.from_result(result)

    # -------------------------------------------------------------------------------- resources --
    @mcp.resource(
        "txt2pptx://schema/outline",
        name="outline-schema",
        title="PresentationOutline JSON schema",
        mime_type="application/json",
    )
    def outline_schema() -> str:
        import json

        return json.dumps(PresentationOutline.model_json_schema(), indent=2)

    @mcp.resource("txt2pptx://templates/{name}", title="Template definition", mime_type="application/json")
    def template_resource(name: str) -> str:
        return service.templates.get(name).model_dump_json(indent=2)

    @mcp.resource("txt2pptx://exports/{filename}", title="Generated deck", mime_type=PPTX_MIME)
    def export_resource(filename: str) -> bytes:
        path = service.resolve_output_file(Path(filename).name)
        return path.read_bytes()

    # ---------------------------------------------------------------------------------- prompts --
    @mcp.prompt(title="Create a slide deck")
    def create_deck(topic: str, audience: str = "general audience", slides: str = "10") -> str:
        """Guide the assistant through researching and building a deck with txt2pptx."""
        return (
            f"Create a ~{slides}-slide presentation about: {topic}\nAudience: {audience}\n\n"
            "1. Gather and organize the key points (ask me for source material if needed).\n"
            "2. Call `list_templates` and choose a fitting template.\n"
            "3. Write a PresentationOutline following these rules:\n"
            f"{OUTLINE_GUIDELINES}\n"
            "4. Optionally call `analyze_outline`, fix the issues, then call `create_presentation`.\n"
            "5. Tell me where the file was saved."
        )

    return mcp


def _transport_security(settings: Settings, host: str) -> TransportSecuritySettings | None:
    if host in {"127.0.0.1", "localhost", "::1"} and not settings.mcp_allowed_hosts:
        return None  # SDK auto-enables localhost-only protection
    if settings.mcp_allowed_hosts == ["*"]:
        logger.warning("DNS-rebinding protection disabled (TXT2PPTX_MCP_ALLOWED_HOSTS='[\"*\"]').")
        return TransportSecuritySettings(enable_dns_rebinding_protection=False)
    local_hosts = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
    hosts = local_hosts + settings.mcp_allowed_hosts
    origins = [f"http://{h}" for h in hosts] + [f"https://{h}" for h in settings.mcp_allowed_hosts]
    return TransportSecuritySettings(allowed_hosts=hosts, allowed_origins=origins)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="txt2pptx-mcp", description="txt2pptx MCP server")
    parser.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    parser.add_argument(
        "--host", help="Bind address for streamable-http (default: TXT2PPTX_MCP_HOST or 127.0.0.1)"
    )
    parser.add_argument(
        "--port", type=int, help="Port for streamable-http (default: TXT2PPTX_MCP_PORT or 8000)"
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    if "TXT2PPTX_HOME" not in os.environ:
        # MCP clients start servers from arbitrary working directories; use a stable per-user location.
        settings.home = Path.home() / "txt2pptx"
    setup_logging(settings.log_level, settings.log_path)

    server = create_server(PresentationService(settings))
    logger.info(
        "txt2pptx MCP server %s (%s); output dir %s", __version__, args.transport, settings.output_path
    )
    if args.transport == "stdio":
        server.run("stdio")
    else:
        host = args.host or settings.mcp_host
        server.run(
            "streamable-http",
            host=host,
            port=args.port or settings.mcp_port,
            transport_security=_transport_security(settings, host),
        )


if __name__ == "__main__":
    main()
