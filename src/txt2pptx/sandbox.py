"""Static validation and isolated execution of LLM-generated python-pptx code.

This is defence in depth, **not** a security boundary: the experimental code-generation mode is disabled by
default (``TXT2PPTX_ENABLE_CODE_EXECUTION``). When enabled, generated code must pass a strict AST allow-list,
then runs in a separate interpreter (``-I`` isolated mode) inside an empty temporary directory, with a
minimal environment (no credentials) and a hard timeout. Run it inside a container for real isolation.
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

ALLOWED_IMPORTS = frozenset({"pptx", "math", "datetime", "json", "typing", "collections", "enum"})
FORBIDDEN_NAMES = frozenset(
    {
        "eval",
        "exec",
        "compile",
        "open",
        "input",
        "breakpoint",
        "help",
        "exit",
        "quit",
        "globals",
        "locals",
        "vars",
        "dir",
        "getattr",
        "setattr",
        "delattr",
        "hasattr",
        "memoryview",
        "classmethod",
        "staticmethod",
        "super",
        "type",
        "object",
        "property",
    }
)
FORBIDDEN_ATTRIBUTES = frozenset(
    {"save", "add_picture", "add_movie", "add_ole_object", "open", "read", "write", "load", "system"}
)

_RUNNER = """\
import sys
from pptx.presentation import Presentation as _Presentation

with open(sys.argv[1], encoding="utf-8") as fh:
    source = fh.read()
namespace = {"__name__": "__main__"}
exec(compile(source, "generated_deck.py", "exec"), namespace)
prs = namespace.get("prs")
if not isinstance(prs, _Presentation):
    prs = next((v for v in namespace.values() if isinstance(v, _Presentation)), None)
if prs is None:
    sys.exit("generated code did not create a Presentation (expected a variable named 'prs')")
prs.save(sys.argv[2])
print(f"saved {len(prs.slides)} slides")
"""


class UnsafeCodeError(ValueError):
    """Generated code violates the static safety policy."""


@dataclass
class ExecutionResult:
    output_path: Path
    stdout: str
    stderr: str


def validate_code(code: str) -> list[str]:
    """Return a list of policy violations (empty when the code is acceptable)."""
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return [f"Syntax error: {exc}"]

    problems: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] not in ALLOWED_IMPORTS:
                    problems.append(f"import of '{alias.name}' is not allowed")
        elif isinstance(node, ast.ImportFrom):
            if node.level or not node.module or node.module.split(".")[0] not in ALLOWED_IMPORTS:
                problems.append(f"import from '{node.module or '.'}' is not allowed")
        elif isinstance(node, ast.Name):
            if node.id in FORBIDDEN_NAMES or node.id.startswith("__"):
                problems.append(f"use of '{node.id}' is not allowed")
        elif isinstance(node, ast.Attribute):
            if node.attr.startswith("_"):
                problems.append(f"access to private attribute '.{node.attr}' is not allowed")
            elif node.attr in FORBIDDEN_ATTRIBUTES:
                problems.append(f"call to '.{node.attr}' is not allowed")
        elif isinstance(node, ast.Global | ast.Nonlocal | ast.AsyncFunctionDef | ast.Await):
            problems.append(f"'{type(node).__name__}' statements are not allowed")
    return sorted(set(problems))


def strip_save_calls(code: str) -> str:
    """Remove ``<expr>.save(...)`` statements; the runner saves the deck itself."""
    tree = ast.parse(code)

    class _Stripper(ast.NodeTransformer):
        def visit_Expr(self, node: ast.Expr) -> ast.AST | None:
            call = node.value
            if (
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
                and call.func.attr == "save"
            ):
                return None
            return node

    tree = _Stripper().visit(tree)
    # Re-fill blocks that became empty.
    for node in ast.walk(tree):
        for attr in ("body", "orelse", "finalbody"):
            block = getattr(node, attr, None)
            if isinstance(block, list) and not block and attr == "body":
                block.append(ast.Pass())
    return ast.unparse(ast.fix_missing_locations(tree))


def _minimal_env() -> dict[str, str]:
    keep = ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "LANG", "LC_ALL")
    env = {k: os.environ[k] for k in keep if k in os.environ}
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def execute_presentation_code(code: str, output_path: Path, *, timeout: int = 60) -> ExecutionResult:
    """Validate *code*, run it in an isolated subprocess and save the resulting deck to *output_path*."""
    code = strip_save_calls(code) if "save" in code else code
    problems = validate_code(code)
    if problems:
        raise UnsafeCodeError("; ".join(problems))

    with tempfile.TemporaryDirectory(prefix="txt2pptx-") as tmp:
        work = Path(tmp)
        (work / "generated_deck.py").write_text(code, encoding="utf-8")
        (work / "runner.py").write_text(_RUNNER, encoding="utf-8")
        target = work / "deck.pptx"
        try:
            proc = subprocess.run(
                [sys.executable, "-I", "runner.py", "generated_deck.py", "deck.pptx"],
                cwd=work,
                env=_minimal_env(),
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"Generated code timed out after {timeout}s") from exc
        if proc.returncode != 0 or not target.exists():
            detail = (proc.stderr or proc.stdout).strip()[-2000:]
            raise RuntimeError(f"Generated code failed (exit {proc.returncode}): {detail}")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(target.read_bytes())
        return ExecutionResult(output_path, proc.stdout, proc.stderr)
