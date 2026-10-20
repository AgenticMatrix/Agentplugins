#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MCP server: CAD control — drive cad_harness's `cad` skill + arbitrary build123d/cadgen code.

The MCP surface of cad_harness for external agents (e.g. Coderix). Two capability
groups:

* Structured tools that shell out to the `cad` skill's CLI (``gen`` / ``export`` /
  ``inspect`` / ``snapshot`` / ``artifact``), plus workspace artifact listing and
  a viewer handoff.
* ``execute_cad_code`` — the manipulation escape hatch: run *arbitrary* build123d /
  cadgen Python in-process (the server is launched with the CAD interpreter), and
  return a JSON-serialisable ``result`` (non-JSON values fall back to ``repr``).
  ``get_cad_api_help`` introspects the API (type / docstring / attrs).

Run (default stdio — the agent spawns the process and talks stdio)::

    python server.py

Configuration (env, all optional)::

    CAD_PYTHON       Python with build123d/cadgen (default: this interpreter)
    CAD_SKILL_DIR    cad skill dir (default <repo>/claude_dir/skills/cad)
    CAD_VIEWER_HOST  viewer host (default 127.0.0.1)
    CAD_VIEWER_PORT  viewer port (default 3245)
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import traceback
import urllib.parse
from pathlib import Path

from mcp.server.fastmcp import FastMCP

# Server lives at <repo>/services/cad-control/server.py; the repo root is two parents up.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_SKILL_DIR = str(_REPO_ROOT / "claude_dir" / "skills" / "cad")

CAD_EXTS = (".step.py", ".step", ".stp", ".glb", ".stl", ".3mf")
SKIP_DIRS = {
    "node_modules", "__pycache__", ".git", ".cadgen", "__cadgen__",
    ".cache", "cache", "artifacts", ".claude", ".coderix", "history", "frames",
}

mcp = FastMCP("cad-control")


# ── helpers ────────────────────────────────────────────────────────────────

def _cad_python() -> str:
    """Python with build123d/cadgen — this interpreter, overridable via env."""
    return os.environ.get("CAD_PYTHON") or sys.executable


def _skill_dir() -> Path:
    return Path(os.environ.get("CAD_SKILL_DIR") or _DEFAULT_SKILL_DIR)


def _viewer_base() -> str:
    host = os.environ.get("CAD_VIEWER_HOST", "127.0.0.1")
    port = os.environ.get("CAD_VIEWER_PORT", "3245")
    return f"http://{host}:{port}"


def _viewer_url(workspace_dir: str, file_rel: str) -> str:
    abs_dir = workspace_dir.replace("\\", "/")
    path_part = abs_dir if abs_dir.startswith("/") else f"/{abs_dir}"
    base = f"{_viewer_base()}{path_part}"
    return f"{base}?file={urllib.parse.quote(file_rel)}" if file_rel else base


def _run_script(tool: str, args: list[str], dir: str) -> dict:
    """Run `scripts/<tool>` in the CAD interpreter and return its result."""
    script = _skill_dir() / "scripts" / tool
    if not script.exists():
        return {"ok": False, "error": f"cad skill scripts not found: {script}"}
    try:
        proc = subprocess.run(
            [_cad_python(), str(script), *args],
            cwd=dir,
            capture_output=True,
            text=True,
        )
    except (subprocess.SubprocessError, FileNotFoundError) as e:
        return {"ok": False, "error": str(e)}
    body = "\n".join(x.strip() for x in (proc.stdout, proc.stderr) if x.strip())
    if proc.returncode != 0:
        return {"ok": False, "error": f"scripts/{tool} exited {proc.returncode}", "output": body}
    return {"ok": True, "output": body or "ok"}


# ── tools ──────────────────────────────────────────────────────────────────

@mcp.tool()
def list_artifacts(dir: str) -> dict:
    """List CAD artifacts (.step.py/.step/.stp/.glb/.stl/.3mf) under a workspace directory."""
    root = Path(dir)
    if not root.is_dir():
        return {"ok": False, "error": f"Directory not found: {dir}"}
    out: list[str] = []
    stack = [root]
    while stack:
        cur = stack.pop()
        try:
            entries = list(cur.iterdir())
        except OSError:
            continue
        for entry in entries:
            if entry.name.startswith("."):
                continue
            if entry.is_dir():
                if entry.name not in SKIP_DIRS:
                    stack.append(entry)
            elif entry.is_file() and entry.name.endswith(CAD_EXTS):
                out.append(entry.relative_to(root).as_posix())
    out.sort()
    return {"ok": True, "files": out}


@mcp.tool()
def render(dir: str, target: str, write: bool = False) -> dict:
    """Render a build123d gen_step() source (or re-render a model) into a GLB/topology package. Runs `scripts/gen`. Pass write=true to also emit the sibling .step file."""
    args = [target, "--json"] + (["--write"] if write else [])
    return _run_script("gen", args, dir)


@mcp.tool()
def export(dir: str, target: str, format: str) -> dict:
    """Export a CAD model (gen_step() source or imported STEP/STP) to an STL/3MF/GLB mesh. Runs `scripts/export`. `format` is one of stl/3mf/glb."""
    flag = "--3mf" if format == "3mf" else f"--{format}"
    return _run_script("export", [target, flag, "--json"], dir)


@mcp.tool()
def inspect(dir: str, target: str, command: str = "refs") -> dict:
    """Inspect/validate a CAD model. Runs `scripts/inspect` with a command (refs, validate, measure, align, frame, diff). JSON output."""
    return _run_script("inspect", [command, target], dir)


@mcp.tool()
def snapshot(dir: str, target: str, theme: str = "", display: str = "") -> dict:
    """Render a PNG/GIF visual review snapshot of a model. Runs `scripts/snapshot`."""
    args = [target, "--json"]
    if theme:
        args += ["--theme", theme]
    if display:
        args += ["--display", display]
    return _run_script("snapshot", args, dir)


@mcp.tool()
def artifact_build(dir: str, file: str) -> dict:
    """Build a render package from an imported STEP file on demand. Runs `scripts/artifact`."""
    return _run_script("artifact", [file], dir)


@mcp.tool()
def focus(dir: str, file: str) -> dict:
    """Return the cad-viewer URL for an artifact so the on-screen viewer can navigate to it."""
    abs_path = Path(dir) / file
    if not abs_path.exists():
        return {"ok": False, "error": f"Artifact not found: {abs_path}"}
    return {"ok": True, "url": _viewer_url(dir, file)}


@mcp.tool()
def execute_cad_code(code: str, dir: str = "") -> dict:
    """Execute arbitrary build123d/cadgen Python code in the CAD Python environment (full access to build123d, cadgen, OCP). Assign a JSON-serialisable value to a variable named `result` to return data (non-JSON values fall back to repr). Use to create, modify, measure, or assemble CAD models directly — the general-purpose manipulation escape hatch."""
    ns = {"__name__": "__cad_main__"}
    if dir:
        try:
            os.chdir(dir)
        except OSError:
            pass
    err = None
    try:
        exec(compile(code, "<cad_code>", "exec"), ns)
    except Exception:
        err = traceback.format_exc()
    return {"result": ns.get("result"), "error": err}


@mcp.tool()
def get_cad_api_help(expr: str) -> dict:
    """Introspect the build123d/cadgen Python API: resolve an expression (e.g. "build123d.Box" or "cadgen.assembly.AssemblyHelper") and return its type, docstring, and public attributes. Use to discover classes/functions before writing execute_cad_code."""
    ns: dict = {}
    try:
        import build123d  # noqa: F401
        ns["build123d"] = build123d
    except ImportError:
        pass
    try:
        import cadgen  # noqa: F401
        ns["cadgen"] = cadgen
    except ImportError:
        pass
    try:
        obj = eval(expr, {"__builtins__": __builtins__}, ns)
        return {
            "type": type(obj).__name__,
            "doc": (obj.__doc__ or "")[:2000],
            "attrs": [a for a in dir(obj) if not a.startswith("_")][:200],
        }
    except Exception:
        return {"error": traceback.format_exc()}


def main() -> None:
    ap = argparse.ArgumentParser(description="CAD control MCP server")
    ap.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    ap.add_argument("--port", type=int, default=int(os.environ.get("CAD_CONTROL_MCP_PORT", "8001")))
    args = ap.parse_args()

    if args.transport == "streamable-http":
        os.environ.setdefault("MCP_PORT", str(args.port))
        mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
