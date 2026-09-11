"""The import graph.

The property under test throughout: an edge that could not be resolved is recorded with
its reason, never dropped. A blast radius that silently omits edges understates itself,
and understating a blast radius is how a change ships believing it is safe.
"""

from __future__ import annotations

from app.models.enums import EdgeType
from app.services.graph.imports import (
    blast_radius,
    build_module_index,
    extract_imports,
    module_name_for,
)

INDEX = build_module_index(
    [
        "pkg/__init__.py",
        "pkg/module.py",
        "pkg/helpers.py",
        "pkg/sub/__init__.py",
        "pkg/sub/deep.py",
        "README.md",
    ]
)


def test_module_names_are_derived_from_paths() -> None:
    assert module_name_for("pkg/module.py") == "pkg.module"
    assert module_name_for("pkg/__init__.py") == "pkg"
    assert module_name_for("pkg/sub/deep.py") == "pkg.sub.deep"


def test_non_python_files_are_not_modules() -> None:
    """Otherwise the module index fills with README files and resolution gets noisy."""
    assert module_name_for("README.md") is None


def test_an_absolute_import_of_a_repository_module_resolves() -> None:
    edges = extract_imports("pkg/module.py", "import pkg.helpers\n", INDEX)
    assert len(edges) == 1
    assert edges[0].resolved is True
    assert edges[0].target_path == "pkg/helpers.py"
    assert edges[0].edge_type is EdgeType.IMPORT


def test_a_third_party_import_is_recorded_as_unresolved_with_a_reason() -> None:
    """Not dropped: an unresolved edge still says what the code asked for."""
    edges = extract_imports("pkg/module.py", "import requests\n", INDEX)
    assert edges[0].resolved is False
    assert edges[0].raw_module_name == "requests"
    assert edges[0].unresolved_reason is not None


def test_from_import_prefers_a_submodule_over_the_package() -> None:
    edges = extract_imports("pkg/module.py", "from pkg import helpers\n", INDEX)
    assert edges[0].target_path == "pkg/helpers.py"
    assert edges[0].edge_type is EdgeType.IMPORT_FROM


def test_a_relative_import_resolves_within_the_package() -> None:
    edges = extract_imports("pkg/module.py", "from . import helpers\n", INDEX)
    assert edges[0].resolved is True
    assert edges[0].target_path == "pkg/helpers.py"
    assert edges[0].edge_type is EdgeType.RELATIVE_IMPORT


def test_a_deeper_relative_import_resolves_upward() -> None:
    edges = extract_imports("pkg/sub/deep.py", "from .. import helpers\n", INDEX)
    assert edges[0].resolved is True
    assert edges[0].target_path == "pkg/helpers.py"


def test_a_relative_import_above_the_root_is_reported_not_clamped() -> None:
    """Clamping to the root would invent an edge that the code does not have."""
    edges = extract_imports("pkg/module.py", "from ... import something\n", INDEX)
    assert edges[0].resolved is False
    assert edges[0].unresolved_reason is not None
    assert "above the repository root" in edges[0].unresolved_reason


def test_a_dynamic_import_is_recorded_as_dynamic() -> None:
    """It can never resolve, which is exactly why it must appear (C4)."""
    source = "import importlib\nm = importlib.import_module('pkg.helpers')\n"
    edges = extract_imports("pkg/module.py", source, INDEX)
    dynamic = [e for e in edges if e.edge_type is EdgeType.DYNAMIC]
    assert len(dynamic) == 1
    assert dynamic[0].resolved is False
    assert dynamic[0].raw_module_name == "pkg.helpers"


def test_a_computed_dynamic_import_is_still_recorded() -> None:
    """The module name is unknowable, so the edge says so rather than vanishing."""
    source = "import importlib\nm = importlib.import_module(name)\n"
    edges = extract_imports("pkg/module.py", source, INDEX)
    dynamic = [e for e in edges if e.edge_type is EdgeType.DYNAMIC]
    assert dynamic[0].raw_module_name == "<computed at runtime>"


def test_an_unparseable_file_yields_no_edges_rather_than_breaking_the_graph() -> None:
    """One bad file must not cost the whole repository's graph."""
    assert extract_imports("pkg/module.py", "def broken(:\n", INDEX) == []


def test_a_module_does_not_import_itself() -> None:
    edges = extract_imports("pkg/helpers.py", "import pkg.helpers\n", INDEX)
    assert edges == []


def test_blast_radius_walks_importers_not_imports() -> None:
    """The question is what breaks if this changes, so the traversal runs in reverse."""
    edges = [
        *extract_imports("pkg/module.py", "import pkg.helpers\n", INDEX),
        *extract_imports("pkg/sub/deep.py", "import pkg.module\n", INDEX),
    ]

    radius = blast_radius(edges, "pkg/helpers.py")

    assert radius["pkg/module.py"] == 1
    assert radius["pkg/sub/deep.py"] == 2


def test_blast_radius_is_bounded_by_depth() -> None:
    """An unbounded answer on a large repository is every file, which says nothing."""
    edges = [
        *extract_imports("pkg/module.py", "import pkg.helpers\n", INDEX),
        *extract_imports("pkg/sub/deep.py", "import pkg.module\n", INDEX),
    ]
    assert "pkg/sub/deep.py" not in blast_radius(edges, "pkg/helpers.py", depth=1)


def test_unresolved_edges_do_not_contribute_to_the_radius() -> None:
    """A radius must not claim reach through an edge we could not follow."""
    edges = extract_imports("pkg/module.py", "import requests\n", INDEX)
    assert blast_radius(edges, "requests") == {}


def test_the_index_is_deterministic_when_two_paths_claim_one_module() -> None:
    """A graph that changes between scans of the same commit is not reproducible (C5)."""
    first = build_module_index(["pkg/mod.py", "pkg/mod/__init__.py"])
    second = build_module_index(["pkg/mod/__init__.py", "pkg/mod.py"])
    assert first == second


SRC_INDEX = build_module_index(
    ["src/click/__init__.py", "src/click/core.py", "src/click/termui.py", "setup.py"]
)


def test_a_src_layout_package_resolves_under_its_importable_name() -> None:
    """Found by the first real scan, not by any test written before it.

    A src-layout project keeps `click` at `src/click/`, and its code imports
    `click.core` -- never `src.click.core`. Indexing only the path-derived name left
    495 of 692 edges unresolved in pallets/click, understating every blast radius in the
    large fraction of modern Python that uses this layout.
    """
    edges = extract_imports("src/click/termui.py", "from click.core import Context\n", SRC_INDEX)

    assert edges[0].resolved is True
    assert edges[0].target_path == "src/click/core.py"


def test_the_literal_path_name_still_resolves() -> None:
    """A repository may genuinely contain a package called `src`; both forms are kept."""
    edges = extract_imports("setup.py", "import src.click.core\n", SRC_INDEX)
    assert edges[0].resolved is True


def test_a_lib_layout_resolves_too() -> None:
    index = build_module_index(["lib/pkg/__init__.py", "lib/pkg/util.py", "main.py"])
    edges = extract_imports("main.py", "from pkg import util\n", index)
    assert edges[0].target_path == "lib/pkg/util.py"


def test_a_normal_layout_is_unaffected() -> None:
    """The stripping must not change anything for repositories without a source root."""
    edges = extract_imports("pkg/module.py", "import pkg.helpers\n", INDEX)
    assert edges[0].target_path == "pkg/helpers.py"
