# txt2pptx

[![CI](https://github.com/blackbyte7/txt2pptx/actions/workflows/ci.yml/badge.svg)](https://github.com/blackbyte7/txt2pptx/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.11%E2%80%933.14-blue.svg)](pyproject.toml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![MCP](https://img.shields.io/badge/MCP-server-8A2BE2.svg)](#mcp-server)

Turn text and documents into polished, editable PowerPoint decks. Use it from a **web UI**, the
**command line**, or any AI assistant through its **MCP server**.

An LLM (OpenAI or Anthropic) structures your content into a *slide outline*: titles, bullets, tables,
charts, image placeholders, and speaker notes. A deterministic renderer then turns that outline into a
native `.pptx`, with real bullets, native charts, styled tables, 16:9 geometry, and template colors and fonts.
You can export the result to PDF, PNG slide images, or an HTML handout.

## Features

- **Inputs:** `.txt`, `.md`, `.pdf`, `.docx`, `.pptx`, `.html`, or pasted text
- **Native PowerPoint output.** Charts are editable chart objects (bar, column, stacked, line, area, pie,
  doughnut), tables are real tables, and speaker notes and document properties are filled in
- **Templates:** `professional`, `creative`, `minimal`, `dark`, or your own JSON templates. Any value can be
  overridden per request
- **Edit, then rebuild.** Tweak the generated outline JSON and re-render without another LLM call
- **Quality checks:** heuristic content analysis, plus an optional AI review
- **MCP server.** The assistant writes the outline itself, so **no API key is needed** on the server
- **Exports:** PDF via LibreOffice or Microsoft PowerPoint, PNG via pypdfium2 (no Poppler), and HTML
- **Production-minded:** typed config, stderr logging, upload and input limits, export retention,
  authentication for the UI, a non-root Docker image, CI

## Quick start

Requires Python 3.11+. [uv](https://docs.astral.sh/uv/) is recommended.

```bash
git clone https://github.com/blackbyte7/txt2pptx.git
cd txt2pptx
uv sync --all-extras          # or: pip install -e ".[all]"
cp .env.example .env          # add OPENAI_API_KEY and/or ANTHROPIC_API_KEY
uv run txt2pptx ui            # http://127.0.0.1:7860
```

Extras: `ui` (Gradio web UI), `mcp` (MCP server), `all` (both). The core library and CLI need neither.

For **PDF/PNG export**, install [LibreOffice](https://www.libreoffice.org/) (`soffice` on your PATH), or have
Microsoft PowerPoint installed on Windows. HTML export always works.

## Command line

```bash
txt2pptx generate report.pdf -t dark -e pdf --max-slides 10     # LLM: document -> deck (+ PDF)
cat notes.md | txt2pptx generate - -p anthropic --review          # from stdin, with AI review
txt2pptx generate report.docx --save-outline outline.json         # keep the outline for later edits
txt2pptx build outline.json -t minimal -e html                    # outline -> deck, no LLM
txt2pptx templates                                                # list templates
txt2pptx ui --host 0.0.0.0 --port 7860                            # web UI
txt2pptx mcp                                                      # MCP server (stdio)
```

Add `--json` to `generate` or `build` for machine-readable output. `python run.py` still starts the UI for
backward compatibility.

## MCP server

The MCP server exposes txt2pptx to Claude Desktop, Claude Code, IDE assistants, and any other MCP client.

| Tool | What it does |
|---|---|
| `create_presentation` | Renders a `PresentationOutline` (written by the assistant) to `.pptx`, with optional PDF/PNG/HTML exports. No LLM call on the server. |
| `list_templates` | Lists the visual templates with their colors |
| `analyze_outline` | Runs heuristic checks on an outline before rendering |
| `export_presentation` | Exports a previously generated deck |
| `generate_presentation` | Server-side LLM: raw text in, deck out. **Only registered when the server has an API key.** |

Resources: `txt2pptx://schema/outline` (JSON schema), `txt2pptx://templates/{name}`, and
`txt2pptx://exports/{filename}` (the `.pptx` bytes). Prompt: `create_deck`.

**Claude Desktop / Claude Code (stdio).** Add to your MCP config (`claude_desktop_config.json`, or `.mcp.json` for Claude Code):

```json
{
  "mcpServers": {
    "txt2pptx": {
      "command": "uvx",
      "args": ["--from", "txt2pptx[mcp] @ git+https://github.com/blackbyte7/txt2pptx", "txt2pptx-mcp"]
    }
  }
}
```

From a local checkout, use `"command": "uv", "args": ["--directory", "/path/to/txt2pptx", "run", "txt2pptx-mcp"]`.
For Claude Code you can also run `claude mcp add txt2pptx -- uv --directory /path/to/txt2pptx run txt2pptx-mcp`.

Decks are written to `~/txt2pptx/exports` unless you set `TXT2PPTX_HOME` or `TXT2PPTX_OUTPUT_DIR`.

**Remote / shared (Streamable HTTP):**

```bash
txt2pptx-mcp --transport streamable-http --host 127.0.0.1 --port 8000   # endpoint: http://127.0.0.1:8000/mcp
```

DNS-rebinding protection is always on. When binding to a public interface, list your public host names in
`TXT2PPTX_MCP_ALLOWED_HOSTS` and put the server behind a TLS-terminating, authenticating reverse proxy.

## Docker

```bash
docker build -t txt2pptx .
docker run --rm -p 127.0.0.1:7860:7860 --env-file .env -v txt2pptx-data:/data txt2pptx           # web UI
docker run --rm -p 127.0.0.1:8000:8000 -v txt2pptx-data:/data txt2pptx mcp --transport streamable-http
docker compose up ui        # or: docker compose up mcp
```

The image runs as a non-root user and includes LibreOffice and Calibri-compatible fonts for PDF/PNG export.
Generated files live in the `/data` volume.

## Configuration

All settings are environment variables, optionally in a `.env` file. See [`.env.example`](.env.example) for
the full list. The most important ones:

| Variable | Default | Purpose |
|---|---|---|
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` | – | LLM access (not needed for `build` or MCP `create_presentation`) |
| `OPENAI_MODEL` / `ANTHROPIC_MODEL` | `gpt-6-astra` / `claude-sonnet-5-5` | Model names |
| `TXT2PPTX_HOME` | `.` (MCP: `~/txt2pptx`) | Base for relative paths (`exports/`, `cache/`, `logs/`) |
| `TXT2PPTX_SERVER_NAME` | `127.0.0.1` | Web UI bind address. Set `TXT2PPTX_UI_AUTH=user:pass` when exposing it |
| `TXT2PPTX_EXPORT_RETENTION_HOURS` | `72` | Deletes old generated files automatically (`0` = keep forever) |
| `TXT2PPTX_ENABLE_CODE_EXECUTION` | `false` | Experimental mode that executes LLM-written python-pptx code |
| `DOCS_PATH` | `data/python-pptx-documentation.pdf` | Optional reference docs for retrieval (needs an OpenAI key for embeddings) |

### Templates

Templates are JSON files: a name, description, `aspect_ratio` (`16:9`/`4:3`), `colors`
(`background`, `text`, `title`, `accent1`–`accent4`, `text_light`, `surface`, `surface_alt`, `on_accent`),
and `font.heading` / `font.body` (`name`, `size`, `bold`, `italic`). Put your own in a directory and point
`TXT2PPTX_TEMPLATES_DIR` at it. A file whose name matches a built-in template overrides that template.
See [`src/txt2pptx/builtin_templates`](src/txt2pptx/builtin_templates) for examples.

### Outline format

The renderer accepts a `PresentationOutline`. Print its JSON schema with:
`python -c "from txt2pptx.schemas import PresentationOutline as P; import json; print(json.dumps(P.model_json_schema(), indent=2))"`

```json
{
  "metadata": {"title": "Q1 Review"},
  "slides": [
    {"slide_type": "title", "title": "Q1 Review", "subtitle": "Sales & Operations"},
    {"title": "Revenue grew 18%", "content_elements": [
      {"element_type": "text", "bullet_points": ["EMEA led growth", "Churn down to 2.1%"]},
      {"element_type": "chart", "chart_type": "column", "categories": ["Jan", "Feb", "Mar"],
       "series": [{"name": "Revenue (k$)", "values": [120, 135, 142]}]}
    ], "speaker_notes": "Mention the EMEA campaign."},
    {"slide_type": "closing", "title": "Next steps", "content_elements": [
      {"element_type": "text", "bullet_points": ["Hire 2 AEs", "Launch partner program"]}]}
  ]
}
```

## Security notes

- The experimental **code-generation mode** runs LLM-written Python. It is **off by default**. When enabled,
  the code must pass a strict AST allow-list (no file, network, or OS access, no dunder access), then runs in
  an isolated interpreter (`-I`) in an empty temp directory, with a stripped environment and a timeout. That
  is defense in depth, not a sandbox. Only enable it inside a container.
- The web UI binds to localhost by default. Before exposing it, set `TXT2PPTX_UI_AUTH`, because the UI can spend the
  server's API key.
- MCP file access is limited to the output directory, and path traversal is rejected.

## Development

```bash
uv sync --all-extras
uv run pytest --cov          # tests (no API keys or network needed)
uv run ruff check . && uv run ruff format --check .
```

Project layout:

```
src/txt2pptx/
  config.py          typed settings (pydantic-settings)
  schemas.py         PresentationOutline & friends (the LLM <-> renderer contract)
  chains.py          LLM calls with native structured output
  pptx_generator.py  deterministic outline -> .pptx renderer
  pipeline.py        PresentationService used by UI, CLI and MCP
  exporters.py       PDF / PNG / HTML export
  loaders.py         text extraction for input documents
  rag.py             optional retrieval over reference docs
  sandbox.py         validation + isolated execution for code mode
  templates.py       template loading/customization (+ builtin_templates/*.json)
  ui.py · cli.py · mcp_server.py
```

See [docs/AUDIT_REPORT.md](docs/AUDIT_REPORT.md) for the 2026 audit and modernization notes.

## License

[MIT](LICENSE)
