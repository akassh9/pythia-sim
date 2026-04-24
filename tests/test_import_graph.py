from __future__ import annotations

import ast
import json
from collections import defaultdict
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parent.parent


def _local_module_name(path: Path) -> str:
    return path.stem


def _direct_local_imports(path: Path, local_modules: set[str]) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top_level = alias.name.split(".", 1)[0]
                if top_level in local_modules:
                    imports.add(top_level)
        elif isinstance(node, ast.ImportFrom):
            if node.module is None:
                continue
            top_level = node.module.split(".", 1)[0]
            if top_level in local_modules:
                imports.add(top_level)
    return imports


def _find_cycle(graph: dict[str, set[str]]) -> list[str] | None:
    visiting: set[str] = set()
    visited: set[str] = set()
    stack: list[str] = []

    def visit(node: str) -> list[str] | None:
        visiting.add(node)
        stack.append(node)
        for neighbor in sorted(graph[node]):
            if neighbor in visiting:
                cycle_start = stack.index(neighbor)
                return stack[cycle_start:] + [neighbor]
            if neighbor not in visited:
                cycle = visit(neighbor)
                if cycle is not None:
                    return cycle
        stack.pop()
        visiting.remove(node)
        visited.add(node)
        return None

    for node in sorted(graph):
        if node not in visited:
            cycle = visit(node)
            if cycle is not None:
                return cycle
    return None


def test_local_python_import_graph_is_acyclic() -> None:
    python_files = sorted(PLUGIN_ROOT.rglob("*.py"))
    local_modules = {_local_module_name(path) for path in python_files}

    graph: dict[str, set[str]] = defaultdict(set)
    for path in python_files:
        module_name = _local_module_name(path)
        graph[module_name]  # ensure every node exists
        for imported_module in _direct_local_imports(path, local_modules):
            graph[module_name].add(imported_module)

    cycle = _find_cycle(graph)
    assert cycle is None, f"local import cycle detected: {' -> '.join(cycle)}"


def test_core_and_server_have_one_way_dependency() -> None:
    core_path = PLUGIN_ROOT / "scripts" / "pythia_sim_core.py"
    server_path = PLUGIN_ROOT / "scripts" / "pythia_sim_server.py"
    local_modules = {"pythia_sim_core", "pythia_sim_server"}

    core_imports = _direct_local_imports(core_path, local_modules)
    server_imports = _direct_local_imports(server_path, local_modules)

    assert core_imports == set()
    assert server_imports == {"pythia_sim_core"}


def test_shared_mcp_manifest_uses_plugin_relative_paths() -> None:
    manifest_path = PLUGIN_ROOT / ".mcp.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    server = manifest["mcpServers"]["pythia-sim"]

    assert server["command"] == "python3"
    assert server["args"] == ["scripts/pythia_sim_server.py"]
    assert server["cwd"] == "."
    assert "CLAUDE_PLUGIN_ROOT" not in manifest_path.read_text(encoding="utf-8")
