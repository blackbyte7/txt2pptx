# txt2pptx – Code Audit & Modernization Report

_Audit date: 2026-11-14 · Baseline commit: `872a4d3` (branch `dev`)_

This report lists every problem found in the codebase as of the baseline commit, grouped by severity,
followed by what was changed to resolve it. Severity scale:

| Level | Meaning |
|---|---|
| 🔴 Critical | The app is broken, or there is a serious security hole |
| 🟠 High | Wrong output, data loss, security weakness, or a blocker for production |
| 🟡 Medium | Quality, maintainability, or robustness problem |
| 🔵 Low | Polish and hygiene |

---

## 1. Executive summary

At baseline the app **could not generate a presentation at all.** Two bugs combined to cause this:

1. `create_agent()` calls `BaseTool.from_function(...)`, which does not exist in LangChain, so every request
   raised `AttributeError` before any LLM call.
2. The Gradio handler reports errors with `gr.Error("...")` but never `raise`s it. The user saw no error
   message, just an empty result.

The test suite did not catch this because the tests mock `BaseTool` itself. Five tests were also failing
against the installed libraries (Pydantic v2 API misuse in the tests).

Other major findings:

* The default Anthropic model (`claude-3-5-sonnet-20240620`) has been **retired**, so Anthropic calls fail.
  The OpenAI default (`gpt-4-turbo`) is three generations old.
* The "code generation" mode runs LLM-written Python on the host. Its AST "sandbox" can be bypassed
  (`from os import system; system(...)`, `import os as o; o.execl(...)`, `pathlib.Path(...).write_text`),
  and the code runs in the project directory with the parent's environment, so secrets such as AWS keys leak.
* `environment.env` is **tracked in git** while also being listed in `.gitignore`. A user who fills in their
  API keys will commit them.
* FAISS cache loading uses `allow_dangerous_deserialization=True`, which means pickle deserialization of files on disk.
* Logging is written to **stdout**. That breaks any stdio-based integration, including MCP.
* The deps target Python 3.10, which reached end-of-life in Oct 2026. They pin `python-pptx==0.6.23` (current is 1.0.x),
  `unstructured<0.15`, and `faiss-cpu<1.9`. They also pull in `langchain`, `langgraph`, and `langchain-community`,
  none of which are needed after the move to a deterministic pipeline.
* There is no packaging (`pyproject.toml`). The top-level packages have generic names (`app`, `view`, `templates`,
  `log_config`) that collide with other packages once installed. `LICENSE` is an **empty file**.

---

## 2. Findings

### 2.1 🔴 Critical

| # | Area | Finding |
|---|---|---|
| C1 | `app/agents.py` | `BaseTool.from_function` does not exist (it's `StructuredTool.from_function`). `create_agent()` always raises, so **no presentation can ever be generated.** |
| C2 | `view/gradio_ui.py` | `gr.Error(...)` is created but never raised (8 places). Failures are silent: the user gets an empty output with no message. |
| C3 | `app/agents.py`, `Dockerfile`, `environment.env` | Default Anthropic model `claude-3-5-sonnet-20240620` is retired, so every Anthropic request fails. |
| C4 | `app/tools.py::validate_python_code_ast` | The sandbox can be bypassed. `from os import system` passes (only `os.<attr>` calls are checked). Aliasing (`import os as o`) skips the `os.` check. `os.execl/execvp/spawnl/kill/environ` are not blocked. `pathlib` allows arbitrary file read and write. `time`, `uuid`, and `json` are fine, but `os` and `pathlib` should never be allowed. |
| C5 | `app/agents.py::_execute_code_safely` | Generated code runs with `cwd` = project root and inherits the whole environment except two keys. All other secrets (cloud creds, tokens) are visible to LLM-written code. |
| C6 | git | `environment.env` is tracked even though it's in `.gitignore`. Filling in your keys and committing will leak them. |

### 2.2 🟠 High

| # | Area | Finding |
|---|---|---|
| H1 | `app/tools.py::create_code_generation_tool` | The `.save()` rewrite always emits `prs.save(...)`. If the LLM named its variable anything else (`presentation`, `deck`), the run fails with `NameError`. The regex `\.save\s*\([^)]+\)` also breaks on nested parentheses. |
| H2 | `app/rag.py` | `FAISS.load_local(..., allow_dangerous_deserialization=True)` unpickles files from `cache/`. Anyone who can write there gets code execution. |
| H3 | `app/rag.py` | The vector-store cache is keyed only by a fixed name. If the docs or the embedding model change, the stale index is silently reused. |
| H4 | `app/rag.py`, `view/gradio_ui.py` | RAG requires an OpenAI key. With Anthropic only, `OpenAIEmbeddings()` is created with no key and fails on every request. The failure is logged but wastes time. |
| H5 | `log_config/logging_config.py` | Logs go to **stdout**, and logging is configured as an import side effect, which creates `logs/` in whatever the CWD is. This breaks stdio protocols (MCP) and pollutes library use. |
| H6 | `app/tools.py` | Uses `PydanticOutputParser` with prompt-embedded format instructions instead of native structured output (`with_structured_output`). Malformed or truncated JSON is common, and `LLM_MAX_TOKENS=4096` is too small for a 15-slide deck with tables. |
| H7 | `app/pptx_generator.py` | Data labels are forced to `XL_DATA_LABEL_POSITION.OUTSIDE_END` for every chart type. That's invalid for line, area, stacked, and doughnut charts, and PowerPoint reports that the file "needs repair". `number_format="0"` also truncates decimals (0.25 shows as 0). |
| H8 | `app/pptx_generator.py` | Bullets in free text boxes have **no bullet glyphs**, so they render as plain lines. In placeholders, bullets start at level 1 (indented, smaller) instead of level 0. A leading empty paragraph is left when a text title is added. |
| H9 | `app/pptx_generator.py` | Unused layout placeholders (e.g. the body placeholder when content is placed manually) stay on the slide and show "Click to add text" in PowerPoint. |
| H10 | `app/pptx_generator.py` | The template `background` color is never applied. Table header text uses the dark body color on the default dark-blue header fill, so it's unreadable. |
| H11 | `app/utils.py`, `app/tools.py` | Output files are named with second precision only. Two concurrent requests for the same input in the same second overwrite each other. |
| H12 | `Dockerfile` | No `.dockerignore`, so `.git`, `logs/`, `cache/`, `exports/`, local env files, and a 278 KB repomix dump are baked into the image. Runs as root. No healthcheck. Uses Python 3.10, which is EOL. |
| H13 | `view/gradio_ui.py` | Binds to `0.0.0.0` by default with no auth. Anyone on the network can spend the server's API key. No upload size limit. |
| H14 | `app/exporters.py` | `subprocess.run([tool, "--version"])` has no timeout. `soffice --version` can hang forever, and it runs several times per export. Parallel `soffice` runs share one profile and fail randomly. Windows has no LibreOffice fallback. `unoconv` is unmaintained. |
| H15 | `requirements.txt` | Outdated and partly contradictory pins: `python-pptx==0.6.23`, `unstructured<0.15`, `faiss-cpu<1.9`, `pdf2image<1.18`. It also includes `langchain`, `langgraph`, and `langchain-community`, which are unused or only used for loaders. The README lists different versions again. |
| H16 | `LICENSE` | The file is empty (0 bytes). Legally the code is "all rights reserved", which contradicts the MIT badge in the README. |

### 2.3 🟡 Medium

| # | Area | Finding |
|---|---|---|
| M1 | structure | No `pyproject.toml`, no installable package, no console entry points. Generic top-level package names (`app`, `view`, `templates`, `log_config`) collide with other distributions. |
| M2 | `app/agents.py` | Test-only code lives in production (`agent_runnable` / `_run_via_agent_runnable` exists only so tests can inject a mock). Unused tool wrappers and `_clean_json_output` are left over from the removed ReAct agent. |
| M3 | `view/gradio_ui.py` | All orchestration (load, generate, analyze, build, export) lives inside the Gradio callback, so it can't be reused from a CLI, the MCP server, or tests. |
| M4 | `templates/templates.py` | Default templates are written to a CWD-relative `templates/` dir at runtime, which is an import-time side effect and breaks when installed as a package. No validation of template contents. |
| M5 | `app/pptx_generator.py` | Slide geometry is hard-coded to 10×7.5 in (4:3). Modern decks are 16:9. |
| M6 | `app/pptx_generator.py` | Chart types are unvalidated free text (`"BAR"` is not a valid `XL_CHART_TYPE` and fails). Numeric parsing rejects `"1,500"` and `"1e3"`. Template accent colors are not applied to series. |
| M7 | `app/pptx_generator.py` | Errors are written *into the user's deck* as red text boxes, and nothing is reported back to the caller. |
| M8 | `app/utils.py` | Loaders rely on the heavy `unstructured` stack (hundreds of MB including NLTK models) just to read `.docx`, `.pptx`, and `.html`. `UnstructuredFileLoader` is deprecated. |
| M9 | `app/exporters.py` | Image export requires the Poppler system binaries (`pdf2image`), and the poppler detection hack calls `pdfinfo` on a non-existent file. |
| M10 | app-wide | No input size limit. A huge PDF is sent straight to the LLM (cost, context overflow). |
| M11 | app-wide | `exports/` grows forever because there's no retention or cleanup. |
| M12 | config | Ad-hoc `os.getenv` calls are scattered across modules. Config uses the non-standard `environment.env` file name while the README says `.env`. No typed config. |
| M13 | `ChatAnthropic(model_name=...)` | Uses the legacy alias instead of `model=`. No request timeout or retry configuration. |
| M14 | tests | They over-mock (they mock `BaseTool`, `Presentation`, and python-pptx internals), so they never exercise the real generator or catch C1. 5 tests fail (`.json(indent=…)` on Pydantic v2 models). |
| M15 | `create_quality_check_tool` | The AI quality review is implemented but never reachable from the UI. |

### 2.4 🔵 Low

| # | Area | Finding |
|---|---|---|
| L1 | git | `.idea/` is tracked despite `.gitignore`. |
| L2 | tooling | No linter or formatter config, no CI, no type-checking setup. |
| L3 | README | Wrong Python version (3.9+), wrong config file name, lists `unoconv`, stale dependency list, no Docker/CLI docs. |
| L4 | UI | Can't paste text directly, can't edit or rebuild the generated outline, and no per-request warnings are shown. |
| L5 | `app/exporters.py` | The HTML export loses bullet structure (uses `&nbsp;` indentation) and drops speaker notes. |

---

## 3. Requested feature: MCP server

The project was a good fit for the Model Context Protocol. When an LLM client (Claude Desktop, Claude Code,
IDEs) uses the tool, **the client LLM can write the outline itself**, so the server needs no API key.
The server then does the deterministic part: layout, styling, charts, tables, and export.
See section 4 for what was built.

---

## 4. Resolution

Every finding above was addressed. The codebase was restructured into an installable package
(`src/txt2pptx/`). Git history is preserved through `git mv`.

### 4.1 Finding → fix

| # | Resolution |
|---|---|
| C1, M2 | The ReAct and tool scaffolding is gone. `PresentationService` (`pipeline.py`) calls focused functions in `chains.py` directly, and test-only code paths were removed. |
| C2 | All UI errors are now `raise gr.Error(...)`. Verified in the browser: missing input and a missing API key both show a toast. |
| C3, M13 | Defaults are now `claude-sonnet-5-5` and `gpt-6-astra`, both configurable. Models are built with `model=`, a timeout, retries, and `max_tokens=16000`. Temperature is only sent when configured, because reasoning models reject custom values. |
| C4, C5, H1 | New `sandbox.py`. A strict allow-list blocks `os`, `pathlib`, any `_private` or dunder attribute, `getattr`, `open`, `eval`, file-reading pptx calls, and relative imports. `.save()` calls are stripped via the AST, and a runner saves *any* `Presentation` object, so variable names no longer matter. Code runs with `python -I` in an empty temp dir with a whitelisted environment (no credentials) and a timeout. The whole mode is **off by default** (`TXT2PPTX_ENABLE_CODE_EXECUTION`). 14 known bypasses are covered by tests. |
| C6 | `environment.env` was removed from git and replaced by `.env.example`. `.gitignore` now covers `.env*`, and `.env` is the primary config file (the legacy `environment.env` is still read). |
| H2, H3, H4 | FAISS was replaced by `langchain_core`'s `InMemoryVectorStore`, persisted as **JSON**, so there's no pickle. The cache key is a SHA-256 of the doc contents, chunking parameters, and embedding model. RAG is skipped cleanly when no OpenAI key is available, and loading is lazy and thread-safe. |
| H5 | `setup_logging()` is only called by entry points and always logs to **stderr**, with an optional rotating file. Library modules use `getLogger(__name__)`. Verified with a real stdio MCP session. |
| H6 | All LLM calls use `with_structured_output(..., method="function_calling")` against Pydantic schemas, with one automatic retry on validation errors and an explicit error for empty or truncated results. |
| H7 | Data labels are only enabled where valid: percentages with best fit for pie, outside-end for clustered bar/column with ≤2 series. The number format is derived from the data (`#,##0` vs `#,##0.0#`). |
| H8 | Free text boxes get real bullet glyphs (`a:buChar`, accent color, hanging indent). Placeholder bullets start at level 0, and headings use `a:buNone`. No leading empty paragraph. |
| H9 | Empty, unused placeholders are removed from every slide (covered by tests). |
| H10 | The slide background is applied from the template. Table headers use accent fill with an `on_accent` text color, and rows alternate `surface`/`surface_alt`. Numbers are right-aligned and thousands-separated. |
| H11 | Output names are `<slug>_<timestamp>_<uuid6>.pptx`. |
| H12 | New Dockerfile: multi-stage `uv` build from the lockfile, Python 3.13, non-root user, `/data` volume, healthcheck, Calibri-compatible fonts, and a whitelist `.dockerignore`. Includes `compose.yaml` with `ui` and `mcp` services. |
| H13 | The UI binds to `127.0.0.1` by default, supports optional basic auth (`TXT2PPTX_UI_AUTH`), and warns when exposed without auth. Upload limit (`max_file_size`), concurrency limits, and private API endpoints are set. |
| H14 | `shutil.which` instead of running `--version`. Every `soffice` run gets its own profile, so concurrent conversions are safe. Timeouts everywhere. Windows uses PowerPoint COM with a LibreOffice fallback. **Also fixed:** the old code called `PowerPoint.Quit()` unconditionally, which closed the user's open decks. It now only quits PowerPoint when no other presentations are open. `unoconv` was dropped. |
| H15 | `pyproject.toml` with current minimums (python-pptx 1.0.2, langchain-core 1.7, gradio 6.32, mcp 2.3, pydantic 2.14, ...) and a committed `uv.lock`. Removed `langchain`, `langgraph`, `langchain-community`, `unstructured`, `faiss-cpu`, `pdf2image`, `comtypes`, and `lxml` (now transitive). The UI and MCP are optional extras. |
| H16 | MIT license text added (copyright holder taken from the git history; adjust if needed). |
| M1 | `src/` layout, hatchling build, console scripts `txt2pptx` and `txt2pptx-mcp`, `python -m txt2pptx`. `run.py` kept as a compatibility shim. |
| M3 | `PresentationService` is the single orchestration layer used by the UI, CLI, and MCP. |
| M4 | Built-in templates ship as package data and are validated by Pydantic models. User templates come from `TXT2PPTX_TEMPLATES_DIR` and are never written implicitly. Added `minimal` and `dark` templates. |
| M5 | 16:9 by default (`aspect_ratio` per template). Layout placeholders are rescaled to the slide width. |
| M6 | `chart_type` is now an enum (`bar`, `column`, `stacked_*`, `line`, `pie`, `doughnut`, `area`) with legacy aliases (`BAR_CLUSTERED` …). Robust number parsing handles `"2,500"`, `"5%"`, `"$3"`. Series use the template palette, and gridlines and fonts are themed. |
| M7 | Rendering problems become `warnings` returned to the caller (UI, CLI, MCP). Nothing is drawn into the deck. A failing element never aborts the slide or the deck. |
| M8 | New lightweight loaders: `pypdf`, `python-docx` (headings and tables), `python-pptx` (incl. notes), and a stdlib HTML extractor (scripts and styles removed), plus encoding fallback for text. |
| M9 | PNG export via `pypdfium2` (bundled PDFium, no Poppler). |
| M10, M11 | `TXT2PPTX_MAX_INPUT_CHARS` (truncation with a warning), `TXT2PPTX_MAX_UPLOAD_MB`, and automatic export retention (`TXT2PPTX_EXPORT_RETENTION_HOURS`, default 72h). |
| M12 | `config.Settings` (pydantic-settings): typed, validated, `SecretStr` keys, placeholder-key filtering, legacy variable names still honored. |
| M14 | New test suite (129 tests, about 85% line coverage). It renders and re-opens real `.pptx` files, runs the real sandbox, and drives the MCP server through the SDK's in-process client. No network or API keys needed. |
| M15 | Optional AI review (`--review`, UI checkbox) is wired through the service. |
| L1 | `.idea/` removed from the index. |
| L2 | Ruff (lint and format) config. GitHub Actions CI: lint, a test matrix (Linux/Windows/macOS × Python 3.11/3.13/3.14), and a Docker build. |
| L3 | README rewritten: install, CLI, MCP setup for Claude Desktop/Code, Docker, configuration, security notes. |
| L4 | UI: paste-text input, an outline viewer and editor with "rebuild without AI", rendering notes, and the AI review score. |
| L5 | HTML export: semantic lists with levels, tables, chart placeholders, speaker notes, all escaped. |

### 4.2 MCP server (new)

`txt2pptx-mcp` (or `txt2pptx mcp`) is built on the official MCP Python SDK **v2** (`MCPServer`, the successor
of `FastMCP`).

* **Tools:** `create_presentation` (outline → deck, no LLM), `list_templates`, `analyze_outline`,
  `export_presentation`, and `generate_presentation` (server-side LLM, registered only when a key is configured).
  All tools have annotations (read-only, destructive, open-world hints) and structured output.
* **Resources:** the outline JSON schema, template definitions, and generated decks as binary blobs
  (`txt2pptx://exports/{file}`). **Prompt:** `create_deck`.
* **Transports:** stdio (the default for desktop clients) and Streamable HTTP, with DNS-rebinding protection always on.
  Verified that a forged `Host` header gets HTTP 421.
* **Safety:** file access is confined to the output directory (path traversal tested). Blocking work runs
  in worker threads with progress notifications. The protocol-level logging capability is not used, since it was
  deprecated in the 2026-07-28 spec.
* **Ergonomics:** when launched by a desktop client from an arbitrary CWD, files go to `~/txt2pptx/`.

### 4.3 Verification performed

* `pytest`: 129 passed. `ruff check` and `ruff format --check`: clean.
* Real stdio MCP session: the `txt2pptx-mcp` console script was spawned as a subprocess, tools were listed, a
  9-slide deck was created, and the `.pptx` was read back through the resource URI.
* Streamable HTTP MCP session: tools were listed and called over HTTP, and a forged `Host` header was rejected.
* Web UI in a browser (Gradio 6): it loads, validation and missing-key errors are shown, and the rebuild path
  reports JSON errors.
* Docker image built (350 MB), and all four templates were rendered to PDF and PNG through LibreOffice inside the container. The visual review caught a placeholder-scaling bug in the new renderer (titles collapsed to zero height on 16:9). It was fixed, re-verified, and pinned with a regression test.

### 4.4 Not done / follow-ups

* No live LLM call was made: no API keys were available during the audit. The LLM layer is covered with a fake
  chat model, and the request shape (structured output via tool calling) follows the current LangChain 1.x APIs.
  Run one real generation per provider before release.
* The default model names (`gpt-6-astra`, `claude-sonnet-5-5`) were taken from the current OpenAI and Anthropic
  SDK model lists. Pin whichever models your account has access to via `OPENAI_MODEL` / `ANTHROPIC_MODEL`.
* For a public multi-user deployment, put the UI and MCP behind an authenticating reverse proxy. Built-in basic auth
  is a single shared credential.
