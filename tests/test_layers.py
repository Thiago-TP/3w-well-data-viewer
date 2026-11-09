"""The layers the READMEs promise: each imports only from itself and the layers before it. No Qt involved."""

import ast
from collections.abc import Iterator
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1] / "src" / "well_data_viewer"
# In the order the READMEs give them: a layer may import from the ones before it.
LAYERS = ("backend", "algorithms", "frontend")


def imported_layers(source: str) -> Iterator[str]:
    """The layer of every module of the package one source file imports, once per import."""
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module]
        elif isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        else:
            continue
        for name in names:
            parts = name.split(".")
            if parts[0] == "well_data_viewer" and len(parts) > 1:
                yield parts[1]


def test_the_layers_import_downward_only():
    """backend imports neither of the others, algorithms imports backend alone, frontend both."""
    rank = {layer: k for k, layer in enumerate(LAYERS)}
    upward = [
        f"{path.relative_to(PACKAGE)} imports from {target}"
        for layer in LAYERS
        for path in sorted((PACKAGE / layer).rglob("*.py"))
        for target in imported_layers(path.read_text(encoding="utf-8"))
        if target in rank and rank[target] > rank[layer]
    ]
    assert not upward, "a layer imports from a layer after it:\n" + "\n".join(upward)


def test_an_upward_import_is_caught():
    """The reader sees both forms of import, inside functions too, and ignores other packages."""
    source = (
        "import numpy\n"
        "from well_data_viewer.backend.config import x\n"
        "def f():\n"
        "    import well_data_viewer.frontend.window\n"
        "    from well_data_viewer.algorithms import profiles\n"
    )
    assert list(imported_layers(source)) == ["backend", "frontend", "algorithms"]
