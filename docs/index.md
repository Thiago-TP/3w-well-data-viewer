# 3W Well Data Viewer

A desktop GUI to inspect the real instances of the [3W dataset](https://github.com/petrobras/3W):
how the instances of a well are laid out in time, what their sensors recorded, what each fault does
to them, and where every instance stands among the others. The
[README](https://github.com/Thiago-TP/3w-well-data-viewer#readme) covers installing and running it.

- The **user guide** walks through the pages and windows of the viewer, one page each.
- The **UML diagrams** draw the package: its three layers and the classes of each.
- The **API reference** documents every module, class and function from its docstrings.

```{toctree}
:caption: User guide
:maxdepth: 1

gui/Timelines
gui/Availability
gui/Faults
gui/Features
gui/Dispersions
gui/Windows
gui/Instances
gui/InstanceWindow
gui/ColorCode
```

```{toctree}
:caption: Reference
:maxdepth: 1

reference/uml
reference/api
```
