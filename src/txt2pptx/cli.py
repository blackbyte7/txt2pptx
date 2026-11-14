"""Command-line interface: ``txt2pptx {ui,mcp,generate,build,templates}``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from txt2pptx import __version__
from txt2pptx.config import get_settings
from txt2pptx.logging_config import setup_logging


def _add_render_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-t", "--template", default="professional", help="Visual template (see `templates`).")
    parser.add_argument(
        "-e", "--export", action="append", choices=["pdf", "html", "images"], default=[], help="Extra format."
    )
    parser.add_argument("-n", "--name", help="Output base file name.")
    parser.add_argument("--json", action="store_true", help="Print the result as JSON.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="txt2pptx", description="Turn text into PowerPoint decks.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    ui = sub.add_parser("ui", help="Start the web UI.")
    ui.add_argument("--host")
    ui.add_argument("--port", type=int)

    mcp = sub.add_parser("mcp", help="Start the MCP server.")
    mcp.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    mcp.add_argument("--host")
    mcp.add_argument("--port", type=int)

    gen = sub.add_parser("generate", help="Generate a deck from a document with an LLM.")
    gen.add_argument("input", help="Input file (.txt .md .pdf .docx .pptx .html) or '-' for stdin.")
    gen.add_argument("-s", "--style", default="Professional")
    gen.add_argument("-a", "--audience", default="General audience")
    gen.add_argument("-p", "--provider", choices=["openai", "anthropic"])
    gen.add_argument("-m", "--model", help="Override the model name.")
    gen.add_argument("--max-slides", type=int, default=12)
    gen.add_argument("--review", action="store_true", help="Add an AI quality review.")
    gen.add_argument("--no-rag", action="store_true", help="Do not use reference documentation.")
    gen.add_argument("--save-outline", type=Path, help="Also write the generated outline JSON here.")
    _add_render_args(gen)

    build = sub.add_parser("build", help="Render an outline JSON file (no LLM).")
    build.add_argument("outline", type=Path)
    _add_render_args(build)

    sub.add_parser("templates", help="List available templates.")
    return parser


def _print_result(result, as_json: bool) -> None:
    if as_json:
        print(result.model_dump_json(indent=2, exclude={"outline"}))
        return
    print(f"Created {result.pptx_path} ({result.slide_count} slides, template {result.template})")
    for fmt, paths in result.exports.items():
        print(f"  {fmt}: {paths[0] if len(paths) == 1 else f'{len(paths)} files in {paths[0].parent}'}")
    for fmt, err in result.export_errors.items():
        print(f"  {fmt} export failed: {err}", file=sys.stderr)
    for warning in result.warnings:
        print(f"  note: {warning}", file=sys.stderr)
    if result.analysis and (result.analysis.warnings or result.analysis.suggestions):
        print("\n" + result.analysis.to_markdown())


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "mcp":
        from txt2pptx.mcp_server import main as mcp_main

        forwarded = ["--transport", args.transport]
        forwarded += ["--host", args.host] if args.host else []
        forwarded += ["--port", str(args.port)] if args.port else []
        mcp_main(forwarded)
        return 0

    settings = get_settings()
    setup_logging(settings.log_level, settings.log_path)

    if args.command == "ui":
        try:
            from txt2pptx.ui import launch
        except ImportError:
            print("The web UI needs the 'ui' extra: pip install 'txt2pptx[ui]'", file=sys.stderr)
            return 2
        launch(settings, host=args.host, port=args.port)
        return 0

    from txt2pptx.pipeline import GenerationOptions, PresentationService

    service = PresentationService(settings)
    try:
        if args.command == "templates":
            for info in service.templates.list_templates():
                print(f"{info.name:<14} {info.aspect_ratio:<5} {info.description}")
            return 0
        if args.command == "build":
            outline = json.loads(args.outline.read_text(encoding="utf-8"))
            result = service.build(
                outline, template=args.template, export_formats=args.export, output_name=args.name
            )
        else:
            options = GenerationOptions(
                style=args.style,
                audience=args.audience,
                template=args.template,
                provider=args.provider,
                model=args.model,
                max_slides=args.max_slides,
                export_formats=args.export,
                ai_review=args.review,
                use_rag=not args.no_rag,
                output_name=args.name,
            )
            if args.input == "-":
                result = service.generate(sys.stdin.read(), options)
            else:
                result = service.generate_from_file(args.input, options)
            if args.save_outline and result.outline:
                args.save_outline.write_text(
                    result.outline.model_dump_json(indent=2, exclude_none=True), "utf-8"
                )
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    _print_result(result, args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
