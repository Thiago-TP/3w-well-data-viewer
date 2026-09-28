"""A time series drawn as what it is: the measurements as dots, the historian's lines faint between them.

Most sensors of the dataset were read every ten seconds or every two minutes,
and the 1 Hz samples between two readings are the straight line the historian
drew (``algorithms.interpolation``). A trace drawn as one solid line shows
that line as if it were signal. Here the samples that were measured are drawn
as dots in the full color, and the line through every sample (which, between
two measurements, is exactly the historian's line), in the same color but
faint. Dense dots are a sensor read every second; sparse dots on a faint line
are a sensor read every two minutes and filled in between, and the eye tells
the two apart at any zoom. A sensor measured at every sample keeps the plain
solid line: there is nothing filled to fade.

The dots are a ``PlotDataItem`` with symbols and no pen, downsampled and
clipped to the view like the line, so a merged recording of days with tens of
thousands of measurements costs a few tens of milliseconds a paint.
"""

from dataclasses import dataclass

import numpy as np
import pyqtgraph as pg
from PySide6.QtGui import QColor

from overlap_viewer.algorithms.interpolation import GENUINE

LINE_ALPHA = 115  # the line between measurements, out of 255, where dots carry the measurements
FADE_ALPHA = 70  # a trace that is not the one named while another is
DOT_PX = 3.2
FRONT_WIDTH = 2.2  # how much wider the named trace's line is drawn
STATES = ("normal", "front", "faded")


@dataclass
class Trace:
    """One time series on a plot: its line and, when it has any, its measurement dots."""

    line: pg.PlotDataItem
    dots: pg.PlotDataItem | None
    color: str
    width: float

    @property
    def dotted(self) -> bool:
        return self.dots is not None

    def items(self) -> list[pg.PlotDataItem]:
        return [self.line] + ([self.dots] if self.dots is not None else [])

    def set_state(self, state: str) -> None:
        """Draw the trace as the one named (``front``), as one of the others (``faded``) or plainly."""
        if state not in STATES:
            raise ValueError(f"unknown state {state!r}; expected one of {STATES}")
        line = QColor(self.color)
        dots = QColor(self.color)
        width = self.width
        if state == "faded":
            line.setAlpha(FADE_ALPHA if not self.dotted else FADE_ALPHA // 2)
            dots.setAlpha(FADE_ALPHA)
        elif state == "front":
            line.setAlpha(255 if not self.dotted else min(255, LINE_ALPHA + 60))
            width = self.width * FRONT_WIDTH
        elif self.dotted:
            line.setAlpha(LINE_ALPHA)
        self.line.setPen(pg.mkPen(line, width=width))
        if self.dots is not None:
            self.dots.setSymbolBrush(pg.mkBrush(dots))
            self.dots.setSymbolSize(DOT_PX + (1.0 if state == "front" else 0.0))


def add_trace(
    plot: pg.PlotItem,
    x: np.ndarray,
    y: np.ndarray,
    color: str,
    width: float = 1.0,
    kinds: np.ndarray | None = None,
) -> Trace:
    """Draw one series on ``plot``, its measurements as dots when ``kinds`` says which samples they are.

    ``kinds`` is what ``interpolation.sample_kinds`` returned for the raw
    readings, one code per sample of ``y``; ``None`` draws a plain line (an
    enumerated variable, which is not tested for interpolation). A series
    every sample of which is a measurement is drawn as a plain line too.
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    dotted = False
    if kinds is not None and len(kinds) == len(y):
        genuine = (np.asarray(kinds) == GENUINE) & ~np.isnan(y)
        valid = ~np.isnan(y)
        dotted = bool(genuine.any()) and genuine.sum() < valid.sum()
    line = pg.PlotDataItem(x, y, pen=pg.mkPen(color, width=width), connect="finite")
    # Added before clipping and downsampling are switched on: while an item is
    # being added, pyqtgraph resolves its view to the layout widget, which
    # those options query.
    plot.addItem(line)
    line.setDownsampling(auto=True, method="peak")
    line.setClipToView(True)
    dots = None
    if dotted:
        dots = pg.PlotDataItem(
            x[genuine],
            y[genuine],
            pen=None,
            symbol="o",
            symbolSize=DOT_PX,
            symbolBrush=pg.mkBrush(color),
            symbolPen=None,
        )
        dots.setZValue(line.zValue() + 1)
        plot.addItem(dots)
        dots.setDownsampling(auto=True, method="peak")
        dots.setClipToView(True)
    trace = Trace(line, dots, color, width)
    trace.set_state("normal")
    return trace
