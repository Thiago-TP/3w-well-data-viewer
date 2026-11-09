"""Write the UML diagrams of the package, as Mermaid, from its source code.

Usage
-----
    uv run python scripts/uml.py            # writes docs/reference/uml.md
    uv run python scripts/uml.py --check    # exits 1 if that file is out of date

The diagrams are read off the code with ``ast`` alone (nothing is imported, so
no Qt and no dataset is needed), which keeps them true to it: the test suite
runs ``--check``, and a class added, renamed or rewired without running this
script again fails it.

What is drawn
-------------
- **Packages**: the three layers (``algorithms``, ``backend``, ``frontend``)
  and the entry points, an arrow where a module of one imports a module of
  another, labeled with how many such imports there are.
- **Classes**: per layer, an overview of the classes that take part in a
  relation, by name; then per module, its classes with their public
  attributes (the fields of a dataclass or a named tuple, and the properties)
  and their public methods, and the classes they relate to as bare boxes. The
  relations are

  - *inheritance* (``<|--``) between the package's classes; a base from
    outside (Qt, pyqtgraph, ``NamedTuple``) is written as the class's
    stereotype instead, ``<<QWidget>>``, as is ``<<dataclass>>``;
  - *composition* (``*--``): an instance a class creates and keeps,
    ``self.name = Class(...)``;
  - *aggregation* (``o--``): an instance a class keeps but was handed, an
    attribute or a field annotated with one of the package's classes, or a
    ``self.name = name`` of a parameter annotated so.
"""

import argparse
import ast
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "src" / "well_data_viewer"
OUT = ROOT / "docs" / "reference" / "uml.md"
LAYERS = ("algorithms", "backend", "frontend")
LAYER_TITLES = {
    "algorithms": ("Algorithms", "What is computed, from arrays and frames; no Qt."),
    "backend": ("Backend", "The dataset, the passes over it and their caches; no Qt."),
    "frontend": (
        "Frontend",
        "The windows, the pages and the widgets and plot items they are made of.",
    ),
}


@dataclass
class ClassInfo:
    name: str
    module: str  # dotted, relative to the package: "frontend.window"
    bases: list[str] = field(default_factory=list)  # as written, last dotted part
    stereotypes: list[str] = field(default_factory=list)
    attributes: list[str] = field(default_factory=list)
    methods: list[str] = field(default_factory=list)
    # (kind, target class, label): kind is "composition" or "aggregation"
    links: list[tuple[str, str, str]] = field(default_factory=list)

    @property
    def layer(self) -> str:
        return self.module.split(".")[0] if "." in self.module else "entry"


def _name(node: ast.expr | None) -> str:
    """``QWidget`` of ``QWidget``, ``GraphicsObject`` of ``pg.GraphicsObject``; ``""`` otherwise."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Subscript):
        return _name(node.value)
    return ""


def _annotation_names(node: ast.expr | None) -> list[str]:
    """Every class named in an annotation: ``WellData | None`` gives ``WellData``, ``list[X]`` ``X``."""
    if node is None:
        return []
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        try:
            node = ast.parse(node.value, mode="eval").body
        except SyntaxError:
            return []
    return [_name(n) for n in ast.walk(node) if isinstance(n, ast.Name | ast.Attribute)]


def _annotation_text(node: ast.expr | None) -> str:
    return "" if node is None else ast.unparse(node).replace(" ", "")


def _mermaid_type(text: str) -> str:
    """An annotation as Python writes it, ``list[list[int]]``, its quotes dropped.

    Mermaid's own generics (``list~int~``) cannot nest, and the package's can.
    """
    return text.replace("'", "").replace('"', "").replace(",", ", ").replace("|", " | ")


def read_module(path: Path) -> tuple[str, list[ClassInfo], list[str]]:
    """The module's dotted name, its classes and the package modules it imports."""
    relative = path.relative_to(PACKAGE).with_suffix("")
    module = ".".join(relative.parts)
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module.startswith("well_data_viewer"):
                target = node.module.removeprefix("well_data_viewer").lstrip(".")
                if target:
                    imports.append(target)
                else:  # from well_data_viewer import __version__: the package itself
                    imports.append("__init__")
            elif node.level:  # relative imports, should any appear
                imports.append(node.module)
    classes = [_read_class(node, module) for node in tree.body if isinstance(node, ast.ClassDef)]
    return module, classes, imports


def _read_class(node: ast.ClassDef, module: str) -> ClassInfo:
    info = ClassInfo(node.name, module, [_name(base) for base in node.bases if _name(base)])
    decorators = {_name(d.func if isinstance(d, ast.Call) else d) for d in node.decorator_list}
    if "dataclass" in decorators:
        info.stereotypes.append("dataclass")
    # Fields: the annotated names of the class body, public ones.
    for item in node.body:
        if (
            isinstance(item, ast.AnnAssign)
            and isinstance(item.target, ast.Name)
            and not item.target.id.startswith("_")
        ):
            info.attributes.append(f"{item.target.id}: {_annotation_text(item.annotation)}")
            for target in _annotation_names(item.annotation):
                info.links.append(("aggregation", target, item.target.id))
    # Methods and properties, public ones; and what ``self`` keeps.
    for item in node.body:
        if not isinstance(item, ast.FunctionDef):
            continue
        decorators = {_name(d) for d in item.decorator_list}
        if not item.name.startswith("_"):
            if "property" in decorators:
                returns = _annotation_text(item.returns)
                info.attributes.append(f"{item.name}: {returns}" if returns else item.name)
            elif not decorators & {"setter", "deleter"}:
                info.methods.append(item.name)
        params = {
            arg.arg: _annotation_names(arg.annotation)
            for arg in item.args.args + item.args.kwonlyargs
        }
        for statement in ast.walk(item):
            _read_assignment(statement, params, info)
    return info


def _read_assignment(statement: ast.AST, params: dict[str, list[str]], info: ClassInfo) -> None:
    """A ``self.name = ...`` (annotated or not) and what it says about the class's relations."""
    if isinstance(statement, ast.Assign):
        targets, value, annotation = statement.targets, statement.value, None
    elif isinstance(statement, ast.AnnAssign):
        targets, value, annotation = [statement.target], statement.value, statement.annotation
    else:
        return
    for target in targets:
        if not (
            isinstance(target, ast.Attribute)
            and isinstance(target.value, ast.Name)
            and target.value.id == "self"
        ):
            continue
        label = target.attr
        if isinstance(value, ast.Call) and _name(value.func):
            info.links.append(("composition", _name(value.func), label))
        elif isinstance(value, ast.BoolOp):  # self.frames = frames or FrameCache()
            for operand in value.values:
                if isinstance(operand, ast.Call) and _name(operand.func):
                    info.links.append(("composition", _name(operand.func), label))
        elif isinstance(value, ast.Name) and value.id in params:
            for name in params[value.id]:
                info.links.append(("aggregation", name, label))
        for name in _annotation_names(annotation):
            info.links.append(("aggregation", name, label))


def read_package() -> tuple[dict[str, ClassInfo], dict[str, list[str]]]:
    classes: dict[str, ClassInfo] = {}
    imports: dict[str, list[str]] = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        module, found, imported = read_module(path)
        imports[module] = imported
        for info in found:
            classes.setdefault(info.name, info)
    return classes, imports


# -- writing


def package_diagram(imports: dict[str, list[str]]) -> str:
    """The layers and the entry points, an arrow per direction of import between them."""

    def layer(module: str) -> str:
        head = module.split(".")[0]
        return head if head in LAYERS else module

    counts: Counter = Counter()
    members: dict[str, list[str]] = {name: [] for name in LAYERS}
    for module, targets in sorted(imports.items()):
        source = layer(module)
        if source in members:
            members[source].append(module.split(".", 1)[1] if "." in module else module)
        for target in targets:
            if layer(target) != source:
                counts[(source, layer(target))] += 1
    lines = ["flowchart LR"]
    entries = sorted({name for pair in counts for name in pair} - set(LAYERS))
    for name in entries:
        lines.append(f'  {name.replace(".", "_")}(["{name}"])')
    for name in LAYERS:
        listed = "<br>".join(sorted(m for m in members[name] if m != "__init__"))
        lines.append(f'  {name}["<b>{name}</b><br>{listed}"]')
    for (source, target), count in sorted(counts.items()):
        noun = "import" if count == 1 else "imports"
        lines.append(f"  {source.replace('.', '_')} -->|{count} {noun}| {target.replace('.', '_')}")
    return "\n".join(lines)


def _relations(
    own: list[ClassInfo],
    classes: dict[str, ClassInfo],
    labels: bool,
    within: set[str] | None = None,
    aggregation: bool = True,
) -> list[str]:
    """The relations of ``own`` to the package's classes (to ``within`` alone, if given), each once.

    An attribute that holds an instance the class sometimes creates and
    sometimes is handed is drawn once, as composition.
    """
    targets = set(classes) if within is None else within
    relations: list[str] = []
    for info in own:
        for base in info.bases:
            if base in targets:
                relations.append(f"  {base} <|-- {info.name}")
        kinds: dict[tuple[str, str], str] = {}
        for kind, target, label in info.links:
            if target in targets and target != info.name:
                key = (target, label if labels else "")
                if kinds.get(key) != "composition":
                    kinds[key] = kind
        for (target, label), kind in kinds.items():
            if kind == "aggregation" and not aggregation:
                continue
            arrow = "*--" if kind == "composition" else "o--"
            relations.append(f"  {info.name} {arrow} {target}" + (f" : {label}" if label else ""))
    return list(dict.fromkeys(relations))


def _related(relations: list[str]) -> set[str]:
    names: set[str] = set()
    for line in relations:
        left, _arrow, right = line.split(" : ")[0].split()
        names |= {left, right}
    return names


def _box(info: ClassInfo, classes: dict[str, ClassInfo], members: bool) -> list[str]:
    stereotypes = info.stereotypes + [base for base in info.bases if base not in classes]
    if not members:
        if not stereotypes:
            return [f"  class {info.name}"]
        return [f"  class {info.name} {{", f"    <<{stereotypes[0]}>>", "  }"]
    lines = [f"  class {info.name} {{"]
    lines += [f"    <<{stereotype}>>" for stereotype in stereotypes[:1]]
    for attribute in info.attributes:
        name, _, kind = attribute.partition(": ")
        lines.append(f"    +{name} {_mermaid_type(kind)}".rstrip())
    lines += [f"    +{method}()" for method in info.methods]
    lines.append("  }")
    return lines


# A class built by this many others of its layer (a common widget) is left out
# of the layer's overview: its arrows from everywhere would only cross the rest.
COMMON = 4


def _common(own: list[ClassInfo]) -> set[str]:
    names = {info.name for info in own}
    builders: Counter = Counter()
    for info in own:
        built = {t for kind, t, _ in info.links if kind == "composition" and t in names}
        builders.update(built - {info.name})
    return {name for name, count in builders.items() if count >= COMMON}


def overview_diagram(layer: str, classes: dict[str, ClassInfo]) -> str:
    """How the classes of one layer are built from one another: inheritance and composition.

    Only relations inside the layer are drawn, and a class built by
    ``COMMON`` others or more is left out, its arrows from everywhere would
    only cross the rest; the aggregations, the classes of other layers and the
    members are in the modules' diagrams. ``""`` when nothing in the layer is
    built from anything else in it.
    """
    own = sorted(
        (info for info in classes.values() if info.layer == layer),
        key=lambda info: (info.module, info.name),
    )
    keep = {info.name for info in own} - _common(own)
    relations = _relations(
        [i for i in own if i.name in keep], classes, labels=False, within=keep, aggregation=False
    )
    if not relations:
        return ""
    related = _related(relations)
    lines = ["classDiagram", "  direction LR"]
    for info in own:
        if info.name in related:
            lines += _box(info, classes, members=False)
    return "\n".join(lines + relations)


def module_diagram(module: str, classes: dict[str, ClassInfo]) -> str:
    """The classes of one module with their members, and the classes they relate to as bare boxes."""
    own = [info for info in classes.values() if info.module == module]
    relations = _relations(own, classes, labels=True)
    lines = ["classDiagram"]
    for info in own:
        lines += _box(info, classes, members=True)
    lines += [f"  class {name}" for name in sorted(_related(relations) - {i.name for i in own})]
    return "\n".join(lines + relations)


def render() -> str:
    classes, imports = read_package()
    parts = [
        "# UML diagrams",
        "",
        (
            "<!-- Written by scripts/uml.py from the source code; do not edit by hand. "
            "Run `uv run python scripts/uml.py` after changing a class. -->"
        ),
        "",
        (
            "The structure of the `well_data_viewer` package, read off its source code by "
            "[`scripts/uml.py`](https://github.com/Thiago-TP/3w-well-data-viewer/blob/main/scripts/uml.py) "
            "and checked against it by the test suite. A layer whose classes are built from one "
            "another has an overview of how, by name; every module then has a diagram of its "
            "classes with their public attributes and methods."
        ),
        "",
        (
            "- Inheritance (`<|--`) is drawn between the package's own classes; a base from outside "
            "(Qt, pyqtgraph, `NamedTuple`) is the class's stereotype instead, as is `<<dataclass>>`."
        ),
        (
            "- Composition (`*--`) is an instance a class creates and keeps, aggregation (`o--`) one "
            "it keeps but was handed; in a module's diagram each is labeled with the attribute that "
            "holds it."
        ),
        (
            "- A class of another module appears as a bare box; its own module's diagram has its "
            "members."
        ),
        "",
        "## Packages",
        "",
        (
            "The three layers and the entry points; an arrow is the imports from the modules of one "
            "to the modules of the other."
        ),
        "",
        "```mermaid",
        package_diagram(imports),
        "```",
    ]
    for layer in LAYERS:
        own = [info for info in classes.values() if info.layer == layer]
        modules = sorted({info.module for info in own})
        title, blurb = LAYER_TITLES[layer]
        overview = overview_diagram(layer, classes)
        intro = f"{blurb} {len(own)} classes in {len(modules)} modules."
        if overview:
            common = ", ".join(f"`{name}`" for name in sorted(_common(own)))
            intro += (
                " The overview draws how they are built from one another, inheritance and "
                "composition"
                + (f", leaving out the classes many others build ({common})" if common else "")
                + "; the modules' diagrams have the rest."
            )
        else:
            intro += (
                " None of them is built from another: they hold data, and each module's diagram "
                "shows what they hold."
            )
        parts += ["", f"## {title}", "", intro]
        if overview:
            parts += ["", "```mermaid", overview, "```"]
        for module in modules:
            names = ", ".join(f"`{info.name}`" for info in own if info.module == module)
            parts += [
                "",
                f"### {module}",
                "",
                names + ".",
                "",
                "```mermaid",
                module_diagram(module, classes),
                "```",
            ]
    return "\n".join(parts) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="exit 1 if the file is stale")
    parser.add_argument("--out", type=Path, default=OUT)
    opts = parser.parse_args(argv)
    text = render()
    if opts.check:
        current = opts.out.read_text(encoding="utf-8") if opts.out.exists() else ""
        if current != text:
            print(f"{opts.out} is out of date: run uv run python scripts/uml.py", file=sys.stderr)
            return 1
        return 0
    opts.out.parent.mkdir(parents=True, exist_ok=True)
    opts.out.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {opts.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
