"""Tests of the documentation the repository writes from its own code: the UML diagrams. No Qt involved."""

import importlib.util
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]


def _uml():
    spec = importlib.util.spec_from_file_location("uml", PROJECT_DIR / "scripts" / "uml.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_uml_diagrams_are_those_of_the_code():
    """docs/reference/uml.md is what scripts/uml.py writes now: run it after changing a class."""
    uml = _uml()
    written = (PROJECT_DIR / "docs" / "reference" / "uml.md").read_text(encoding="utf-8")
    assert written == uml.render(), (
        "docs/reference/uml.md is out of date: run `uv run python scripts/uml.py`"
    )


def test_the_uml_reader_finds_classes_their_bases_and_what_they_keep(tmp_path, monkeypatch):
    """Inheritance, composition, aggregation and the stereotypes are read off the source."""
    uml = _uml()
    package = tmp_path / "well_data_viewer"
    (package / "frontend").mkdir(parents=True)
    (package / "backend").mkdir()
    (package / "backend" / "data.py").write_text(
        "from dataclasses import dataclass\n\n"
        "@dataclass\n"
        "class Info:\n"
        "    name: str\n"
        "    def label(self) -> str:\n"
        "        return self.name\n",
        encoding="utf-8",
    )
    (package / "frontend" / "pages.py").write_text(
        "from PySide6.QtWidgets import QWidget\n"
        "from well_data_viewer.backend.data import Info\n\n"
        "class Base(QWidget):\n"
        "    def show_page(self):\n"
        "        pass\n\n"
        "class Page(Base):\n"
        "    def __init__(self, info: Info):\n"
        "        self.info = info\n"
        "        self._child = Base()\n"
        "    @property\n"
        "    def title(self) -> str:\n"
        "        return ''\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(uml, "PACKAGE", package)
    classes, imports = uml.read_package()
    assert set(classes) == {"Info", "Base", "Page"}
    assert classes["Info"].stereotypes == ["dataclass"]
    assert classes["Info"].attributes == ["name: str"] and classes["Info"].methods == ["label"]
    assert classes["Page"].bases == ["Base"] and classes["Page"].attributes == ["title: str"]
    assert imports["frontend.pages"] == ["backend.data"]
    diagram = uml.module_diagram("frontend.pages", classes)
    assert "<<QWidget>>" in diagram  # a base from outside is a stereotype
    assert "Base <|-- Page" in diagram
    assert "Page *-- Base : _child" in diagram  # created and kept
    assert "Page o-- Info : info" in diagram  # handed and kept
    assert "class Info" in diagram  # a class of another module, as a bare box
    assert "+show_page()" in diagram and "+title str" in diagram
    overview = uml.overview_diagram("frontend", classes)
    assert "Base <|-- Page" in overview and "Info" not in overview  # inside the layer alone
    assert uml.overview_diagram("backend", classes) == ""  # nothing built from anything
