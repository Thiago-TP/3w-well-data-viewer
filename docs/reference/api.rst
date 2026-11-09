API reference
=============

Every module of the ``well_data_viewer`` package, generated from its docstrings at each build. The
package is in three layers, drawn in the :doc:`UML diagrams <uml>`: ``algorithms`` (what is
computed, no Qt), ``backend`` (the dataset, the passes over it and their caches, no Qt) and
``frontend`` (the windows, the pages and their widgets). ``src/README.md`` walks through the same
modules in prose.

.. autosummary::
   :toctree: api
   :recursive:

   well_data_viewer
