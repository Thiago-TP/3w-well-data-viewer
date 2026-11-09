"""Sphinx configuration of the documentation site: the user guide, the UML diagrams, the API reference.

Build it from the root of the repository with

    uv run --group docs sphinx-build -M html docs docs/_build

and open ``docs/_build/html/index.html``. The pages of the user guide are the
Markdown files of ``docs/gui`` as GitHub shows them (MyST reads them); the UML
diagrams are ``docs/reference/uml.md``, written by ``scripts/uml.py``; the API
reference is generated from the docstrings at every build (``autosummary``
writes it to ``docs/reference/api``, which is not versioned).
"""

import os
import re
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
# The frontend modules import Qt; nothing here opens a window, but a platform
# that needs no display keeps the import quiet on a machine without one.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from well_data_viewer import __version__

# ``python -m well_data_viewer`` runs the viewer, and so would importing
# ``well_data_viewer.__main__``, which the recursive API reference does to list the
# package: an empty module stands in for it, and the reference leaves it out.
sys.modules["well_data_viewer.__main__"] = types.ModuleType("well_data_viewer.__main__")

project = "3W Well Data Viewer"
author = "Thiago-TP"
copyright = "2026, Thiago-TP"
release = version = __version__

extensions = [
    "myst_parser",
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinx.ext.intersphinx",
    "sphinxcontrib.mermaid",
]
source_suffix = {".rst": "restructuredtext", ".md": "markdown"}
exclude_patterns = ["_build", "presentation", "papers", "**/README.md", "Thumbs.db", ".DS_Store"]
templates_path = ["_templates"]

# -- Markdown

myst_heading_anchors = 3
# ```mermaid fences, which GitHub draws, are drawn here too.
myst_fence_as_directive = ["mermaid"]

# -- API reference

autosummary_generate = True
autosummary_imported_members = False
autodoc_default_options = {
    "members": True,
    "show-inheritance": True,
    "member-order": "bysource",
}
autodoc_typehints = "description"
autodoc_class_signature = "separated"
# The docstrings are NumPy-style: Parameters, Returns, Attributes, Signals.
napoleon_google_docstring = False
napoleon_numpy_docstring = True
napoleon_custom_sections = [("Signals", "params_style")]
# An Attributes section lists the fields of a dataclass or a named tuple, which
# autodoc documents again as members: as ``:ivar:`` they are not indexed twice.
napoleon_use_ivar = True
intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "numpy": ("https://numpy.org/doc/stable", None),
    "pandas": ("https://pandas.pydata.org/docs", None),
}

# -- HTML

html_theme = "furo"
html_title = f"3W Well Data Viewer {release}"
html_static_path: list[str] = []
# The diagrams are drawn in the browser, light or dark as the page is. The
# largest (the frontend's overview) is past Mermaid's default size limit.
mermaid_init_config = {"startOnLoad": False, "maxTextSize": 200_000}
# ELK lays the class diagrams out with orthogonal lines and few crossings,
# where Mermaid's own layout tangles the larger ones.
mermaid_include_elk = True
mermaid_config = {"layout": "elk"}
mermaid_light_theme = "neutral"
mermaid_dark_theme = "dark"

# -- Links the Markdown pages make for GitHub, made for this site

# The pages of the user guide link to the source of a module as GitHub shows
# it (``../../src/well_data_viewer/backend/config.py``); here that module has a
# page of its own in the API reference, which is where the link goes.
SOURCE_LINK = re.compile(r"\]\((?:\.\./)+src/well_data_viewer/([\w/]+)\.py\)")


def _link_modules_to_reference(app, docname, source) -> None:
    depth = docname.count("/")
    prefix = "../" * depth
    source[0] = SOURCE_LINK.sub(
        lambda m: f"]({prefix}reference/api/well_data_viewer.{m.group(1).replace('/', '.')}.rst)",
        source[0],
    )


def setup(app) -> None:
    app.connect("source-read", _link_modules_to_reference)
