"""Building the import graph from the target's AST.

Parsing a file is reading its bytes, not running its code, so this happens on the host
under ADR 0011 -- `ast.parse` never executes what it parses. Nothing here imports the
target, and nothing here may start doing so.

The graph's value is answering "what breaks if I change this file", and that answer is
only trustworthy if the edges it could not resolve are visible. An import of a
third-party package, a relative import that walks above the repository root, and an
`importlib.import_module(name)` computed at runtime are all unresolvable in different
ways -- and all three are recorded with `resolved=False` and a reason rather than
dropped, because a blast radius that silently omits edges understates itself, and
understating a blast radius is how a change ships believing it is safe (C4).
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import PurePosixPath

import structlog

from app.models.enums import EdgeType

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ImportEdge:
    """One import, resolved to a repository file or explicitly not.

    ``raw_module_name`` always carries what the source actually asked for, so an
    unresolved edge is still informative: it distinguishes a third-party dependency from
    a genuine resolution bug.
    """

    source_path: str
    raw_module_name: str
    edge_type: EdgeType
    target_path: str | None
    resolved: bool
    unresolved_reason: str | None


def module_name_for(path: str) -> str | None:
    """The dotted module a repository path would be imported as.

    ``pkg/sub/mod.py`` -> ``pkg.sub.mod``; ``pkg/__init__.py`` -> ``pkg``. Returns None
    for anything that is not importable Python, so callers do not build a module index
    out of README files.
    """
    pure = PurePosixPath(path)
    if pure.suffix != ".py":
        return None
    parts = list(pure.parts)
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts[-1] = pure.stem
    return ".".join(parts) if parts else None


def build_module_index(paths: list[str]) -> dict[str, str]:
    """Dotted module name -> repository path, for every importable file.

    Where two paths claim the same module -- ``pkg/mod.py`` and ``pkg/mod/__init__.py``,
    or the same package vendored twice -- the shortest path wins, and it is deterministic
    rather than dependent on walk order. Ambiguity resolved arbitrarily but consistently
    beats a graph that changes between scans of the same commit (C5).
    """
    index: dict[str, str] = {}
    for path in sorted(paths):
        module = module_name_for(path)
        if module is None:
            continue
        existing = index.get(module)
        if existing is None or len(path) < len(existing):
            index[module] = path
    return index


def _resolve_relative(source_path: str, module: str | None, level: int) -> tuple[str | None, str]:
    """Turn a relative import into an absolute dotted name.

    Returns the name and a reason if it could not be formed. A relative import that walks
    above the repository root is a real thing to find -- it means the file is imported as
    part of a package rooted outside what we cloned -- so it is reported rather than
    clamped to the root, which would invent an edge.
    """
    # The containing directory, for both a module and a package's __init__.py: inside
    # pkg/mod.py and inside pkg/__init__.py alike, `.` means pkg.
    package_parts = list(PurePosixPath(source_path).parts[:-1])

    # `from . import x` inside pkg/mod.py is relative to pkg; level 2 goes one higher.
    ascend = level - 1
    if ascend > len(package_parts):
        return None, (
            f"relative import walks {level} levels up from {source_path}, above the repository root"
        )
    base = package_parts[: len(package_parts) - ascend] if ascend else package_parts
    absolute = ".".join([*base, *(module.split(".") if module else [])])
    return (absolute or None), ""


def extract_imports(source_path: str, source: str, index: dict[str, str]) -> list[ImportEdge]:
    """Every import in one file, resolved against the repository's own modules.

    A syntax error yields no edges and is logged rather than raised: one unparseable file
    must not cost the whole graph. The file still appears in the inventory, so it is not
    invisible -- it simply has no outgoing edges, which is the honest representation of
    "we could not read its imports".
    """
    try:
        tree = ast.parse(source, filename=source_path)
    except SyntaxError as exc:
        logger.info("graph.unparseable", path=source_path, error=str(exc))
        return []

    edges: list[ImportEdge] = []

    def record(raw: str, edge_type: EdgeType, reason: str | None = None) -> None:
        if reason:
            edges.append(ImportEdge(source_path, raw, edge_type, None, False, reason))
            return
        target = index.get(raw)
        if target is not None and target != source_path:
            edges.append(ImportEdge(source_path, raw, edge_type, target, True, None))
        elif target == source_path:
            # A module importing itself is not an edge worth drawing.
            return
        else:
            edges.append(
                ImportEdge(
                    source_path,
                    raw,
                    edge_type,
                    None,
                    False,
                    "not a module in this repository (third-party or stdlib)",
                )
            )

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                record(alias.name, EdgeType.IMPORT)

        elif isinstance(node, ast.ImportFrom):
            if node.level:
                absolute, reason = _resolve_relative(source_path, node.module, node.level)
                if absolute is None:
                    record(
                        f"{'.' * node.level}{node.module or ''}",
                        EdgeType.RELATIVE_IMPORT,
                        reason,
                    )
                    continue
                # `from .pkg import name` may mean the module pkg.name or an attribute
                # of pkg. Both are tried, and the submodule wins when it exists.
                for alias in node.names:
                    candidate = f"{absolute}.{alias.name}"
                    record(
                        candidate if candidate in index else absolute,
                        EdgeType.RELATIVE_IMPORT,
                    )
            else:
                base = node.module or ""
                for alias in node.names:
                    candidate = f"{base}.{alias.name}"
                    record(candidate if candidate in index else base, EdgeType.IMPORT_FROM)

        elif isinstance(node, ast.Call):
            raw = _dynamic_import_target(node)
            if raw is not None:
                record(
                    raw,
                    EdgeType.DYNAMIC,
                    "dynamic import; the module is chosen at runtime and cannot be "
                    "resolved statically",
                )

    return edges


def _dynamic_import_target(node: ast.Call) -> str | None:
    """The literal argument of an importlib call, or a placeholder when it is computed.

    Recorded either way. A dynamic import is an edge the graph cannot follow, and a blast
    radius that omits it is one that claims more certainty than it has (C4).
    """
    func = node.func
    is_importlib = (
        isinstance(func, ast.Attribute)
        and func.attr == "import_module"
        and isinstance(func.value, ast.Name)
        and func.value.id == "importlib"
    )
    is_dunder = isinstance(func, ast.Name) and func.id == "__import__"
    if not (is_importlib or is_dunder):
        return None

    if node.args:
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            return first.value
    return "<computed at runtime>"


def blast_radius(edges: list[ImportEdge], changed: str, depth: int = 3) -> dict[str, int]:
    """Which files transitively import ``changed``, and how far away each is.

    Reverse edges: the question is "what breaks if I change this", so the traversal runs
    against the direction of the import. Depth is bounded because an unbounded answer on
    a large repository is every file, which tells a reviewer nothing.
    """
    importers: dict[str, list[str]] = {}
    for edge in edges:
        if edge.resolved and edge.target_path is not None:
            importers.setdefault(edge.target_path, []).append(edge.source_path)

    distances: dict[str, int] = {}
    frontier = [changed]
    for hop in range(1, depth + 1):
        nxt: list[str] = []
        for node in frontier:
            for importer in importers.get(node, []):
                if importer != changed and importer not in distances:
                    distances[importer] = hop
                    nxt.append(importer)
        if not nxt:
            break
        frontier = nxt
    return distances
