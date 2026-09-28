"""3W Real Instances Viewer: a GUI to inspect the real instances of the 3W dataset.

The 3W dataset stores one parquet file per instance, and the real instances of
one well are windows cut from the same continuous recording, so they often
overlap in time, and the shared samples then carry two different labels. This
package started as a viewer of those overlaps and is growing into a viewer of
the real instances at large, one page per question: a timelines page with one
interactive timeline per well, an availability page saying what the sensors
of each fault class or well actually recorded, a faults page and a features
page comparing the instances' signals, and, on click, a window with the time
series of an instance and of every instance it overlaps, on shared axes.

The package is laid out by focus, and the dependencies grow from one layer to
the next:

``backend``
    What the data is: ``config``, ``dataset`` (the catalogue and its caches),
    ``labels``, ``timemap``, ``availability``, and the viewer's own data
    (``theme``, ``palette``, ``help_text``). Pandas, numpy and pyarrow only.
``algorithms``
    What is computed from the data: ``faults`` (onsets, scaling), ``spectral``
    (the signal views) and every analysis derived from the instances. Numpy
    only; anything heavier is an optional extra, declared in ``pyproject.toml``
    and looked up through ``backend.extras`` so that a missing one greys a
    control instead of breaking the viewer.
``frontend``
    How it is shown: the pyqtgraph items, the pages, the instance window and
    the main window. PySide6 and pyqtgraph.

``app`` is the command line and start-up; it is the one module of the top
level that imports from all three.
"""

__version__ = "0.1.0"
