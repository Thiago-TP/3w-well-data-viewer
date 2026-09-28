"""The Qt pieces of the signal views, shared by the instance window and the faults page.

``TransformControls`` is the toolbar widget holding every parameter a view
takes (the segment length, the overlap, the window function, the number of
bins), so that the two windows offer the same widgets and mean the same thing
by them. ``LogPeriodAxisItem`` labels an axis of log10 seconds in the units a
person says a period in. The rest are the builders both windows draw with: a
histogram as stacked bars or as a filled step outline, a spectrum curve, the
marker over a histogram's fullest bin, and the shading of the periods a
segment cannot resolve or of the readings no instrument could have produced.

Every spectral plot carries its data in log10: the period axis because the
events span seconds to days, the power axis because a line an order of
magnitude above the noise is what a spectrum is read for. The axes are told
so (``AxisItem.setLogMode`` for power, this module's own axis for period) and
print real values; the items themselves are never put in log mode, since a
bar item would not follow.
"""

from collections.abc import Sequence

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPen
from PySide6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QLabel, QSpinBox, QWidget

from overlap_viewer.algorithms.spectral import (
    WINDOWS,
    Histogram,
    Spectrum,
    TransformParams,
    format_period,
)
from overlap_viewer.backend import theme

# The periods an axis may put a tick at, in seconds: from one second to a month.
TICK_PERIODS_S = (
    1,
    2,
    5,
    10,
    15,
    30,
    60,
    120,
    300,
    600,
    900,
    1800,
    3600,
    7200,
    10800,
    21600,
    43200,
    86400,
    172800,
    604800,
    2592000,
)
MIN_TICK_PX = 34  # two ticks of a period axis closer than this collide

DEFAULT_SEGMENT_MIN = 45  # what the box offers once the whole stretch is unticked
DEFAULT_OVERLAP_PCT = 50  # Rabelo's windows overlap by half
DEFAULT_BINS = 40
CLAMP_TIP = (
    "Count only the readings inside the plausible range, which is what a "
    "histogram is normally asked for: one gauge reporting a pressure of 1e12 Pa would otherwise "
    "put every genuine reading into the first bin. Untick to see the garbage itself: the bins "
    "beyond the range sit on an amber ground, and the axis opens to hold them."
)
GENUINE_TIP = (
    "Count and transform the measurements only, leaving out the samples the historian filled in "
    "between them: the straight lines it drew from one reading to the next, and the readings it "
    "carried forward. A histogram then counts what was read; a spectrum becomes the Lomb-Scargle "
    "periodogram of the readings at their own instants, which needs no grid and is the honest "
    "spectrum of a series measured every ten seconds or every two minutes. Most sensors of 3W "
    "were: on the 1 Hz grid, one sample in sixteen is a measurement."
)
GRID_ALPHA = 0.25  # the grid of a spectrum plot, faint enough to stay behind the curve
PEAK_BAR_PX = 14  # how far under the top of a trace plot the bar of one peak period sits
PEAK_FONT_PX = 10
PEAK_MARKER_PX = 9  # the triangle over the fullest bin of a histogram
HIST_FILL_ALPHA = 55  # the wash under a histogram outline, faint enough that several stack


class TransformControls(QWidget):
    """The parameters of the views that transform, as toolbar widgets.

    Signals
    -------
    changed()
        A parameter was edited; the views should be computed again.
    """

    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self._segment_label = QLabel(" Segment ")
        self._whole = QCheckBox("whole stretch")
        self._whole.setChecked(True)
        self._whole.setToolTip(
            "Take the spectrum over the whole stretch shown, in one segment (a periodogram), "
            "which is the only way to see the events: severe slugging cycles every 50 to 90 "
            "minutes, and a segment of a few minutes holds no cycle of it. Untick to set the "
            "segment length yourself."
        )
        self._segment = QSpinBox()
        self._segment.setRange(1, 24 * 60)
        self._segment.setValue(DEFAULT_SEGMENT_MIN)
        self._segment.setSuffix(" min")
        self._segment.setEnabled(False)
        self._segment.setToolTip(
            "Length of the segments the spectrum averages over, in minutes. Nothing longer "
            "than a segment can be resolved, so the axis is greyed beyond it."
        )
        self._overlap_label = QLabel(" Overlap ")
        self._overlap = QSpinBox()
        self._overlap.setRange(0, 90)
        self._overlap.setValue(DEFAULT_OVERLAP_PCT)
        self._overlap.setSuffix(" %")
        self._overlap.setSingleStep(10)
        self._overlap.setToolTip(
            "How much of a segment the next one repeats. More overlap gives the spectrum more "
            "segments to average, from the same stretch."
        )
        self._window_label = QLabel(" Window ")
        self._window = QComboBox()
        self._window.addItems(list(WINDOWS))
        self._window.setToolTip(
            "The taper applied to every segment before it is transformed. Hann is the usual "
            "choice; rectangular is no taper at all, which leaks the strong lines into their "
            "neighbours."
        )
        self._bins_label = QLabel(" Bins ")
        self._bins = QSpinBox()
        self._bins.setRange(5, 200)
        self._bins.setValue(DEFAULT_BINS)
        self._bins.setToolTip("How many bins the histograms count the readings into")
        self._clamp = QCheckBox("Plausible only")
        self._clamp.setChecked(True)
        self._clamp.setToolTip(CLAMP_TIP)
        self._genuine = QCheckBox("Measurements only")
        self._genuine.setToolTip(GENUINE_TIP)
        self._spectral_shown = True
        self._bins_shown = True

        for widget in (
            self._segment_label,
            self._whole,
            self._segment,
            self._overlap_label,
            self._overlap,
            self._window_label,
            self._window,
            self._bins_label,
            self._bins,
            self._clamp,
            self._genuine,
        ):
            layout.addWidget(widget)
        self._whole.toggled.connect(self._on_whole_toggled)
        self._segment.valueChanged.connect(self.changed)
        self._overlap.valueChanged.connect(self.changed)
        self._window.currentIndexChanged.connect(self.changed)
        self._bins.valueChanged.connect(self.changed)
        self._clamp.toggled.connect(self.changed)
        self._genuine.toggled.connect(self.changed)

    def _on_whole_toggled(self, checked: bool) -> None:
        self._segment.setEnabled(not checked)
        self.changed.emit()

    def params(self) -> TransformParams:
        return TransformParams(
            segment_s=0 if self._whole.isChecked() else self._segment.value() * 60,
            overlap=self._overlap.value() / 100.0,
            window=self._window.currentText(),
            bins=self._bins.value(),
            clamp=self._clamp.isChecked(),
            genuine=self._genuine.isChecked(),
        )

    def set_genuine(self, checked: bool) -> None:
        """Tick or untick *Measurements only*, as a script or a test would."""
        self._genuine.setChecked(checked)

    def show_spectral(self, shown: bool) -> None:
        """Show the segment, overlap and window widgets only while a spectral view is on."""
        self._spectral_shown = shown
        for widget in (
            self._segment_label,
            self._whole,
            self._segment,
            self._overlap_label,
            self._overlap,
            self._window_label,
            self._window,
        ):
            widget.setVisible(shown)
        self._sync_genuine()

    def anything_shown(self) -> bool:
        """Whether any widget is on show, so a toolbar row holding only this can hide with it."""
        return self._segment.isVisibleTo(self) or self._bins.isVisibleTo(self)

    def show_bins(self, shown: bool) -> None:
        """Show the bins widget and the plausibility clamp only while a distribution view is on."""
        self._bins_shown = shown
        self._bins_label.setVisible(shown)
        self._bins.setVisible(shown)
        self._clamp.setVisible(shown)
        self._sync_genuine()

    def _sync_genuine(self) -> None:
        """*Measurements only* serves both views, so it stays while either is on."""
        self._genuine.setVisible(self._spectral_shown or self._bins_shown)


class LogPeriodAxisItem(pg.AxisItem):
    """An axis whose values are log10 of a period in seconds, labeled ``30 s``, ``5 min``, ``1.5 h``.

    The ticks sit at the periods a person would name, as many of them as the
    axis has room for at the current zoom.
    """

    def tickValues(self, minVal, maxVal, size):
        if maxVal <= minVal or size <= 0:
            return []
        px_per_unit = size / (maxVal - minVal)
        values = []
        last_px = -np.inf
        for period in TICK_PERIODS_S:
            value = np.log10(period)
            if value < minVal or value > maxVal:
                continue
            px = (value - minVal) * px_per_unit
            if px - last_px >= MIN_TICK_PX:
                values.append(float(value))
                last_px = px
        return [(1.0, values)]

    def tickStrings(self, values, scale, spacing):
        return [format_period(10.0**value) for value in values]


def power_axis(plot: pg.PlotItem, side: str, label: str) -> None:
    """Make one axis of ``plot`` print the powers its log10 data stand for."""
    axis = plot.getAxis(side)
    axis.setLogMode(True)
    axis.enableAutoSIPrefix(False)  # a prefix on a logarithmic axis reads as a stray factor
    plot.setLabel(side, label)


def spectrum_grid(plot: pg.PlotItem) -> None:
    """The faint grid of a spectrum plot: a decade of power and a named period per line."""
    plot.showGrid(x=True, y=True, alpha=GRID_ALPHA)


def add_center_lines(
    plot: pg.PlotItem, mean: float, median: float, horizontal: bool
) -> list[pg.InfiniteLine]:
    """The mean (solid) and the median (dashed) of a distribution, as lines across its plot.

    ``horizontal`` for a marginal histogram, whose values run up the side.
    """
    colors = theme.current()
    items = []
    for value, style in ((mean, Qt.PenStyle.SolidLine), (median, Qt.PenStyle.DashLine)):
        if not np.isfinite(value):
            continue
        line = pg.InfiniteLine(
            pos=value,
            angle=0 if horizontal else 90,
            movable=False,
            pen=pg.mkPen(colors.muted, width=1.2, style=style),
        )
        line.setZValue(12)
        plot.addItem(line, ignoreBounds=True)
        items.append(line)
    return items


def add_peak_marker(
    plot: pg.PlotItem, value: float, height: float, color: str, horizontal: bool
) -> pg.ScatterPlotItem | None:
    """Mark the fullest bin of a histogram with a triangle over its top, in the series color.

    The mean and the median are already lines across the plot, and a third
    grey stroke would be one more to tell apart where what is wanted is the
    single place the readings pile up. A triangle sitting on the tallest bar
    says it without crossing anything, and in the color of the series it
    belongs to, so that a grid or an overlay of several says at a glance
    whether their peaks line up.

    ``horizontal`` for a marginal histogram, whose values run up the side and
    whose bars grow to the right; the marker then points at them from the
    right. ``None`` when there is no peak to mark.
    """
    if not np.isfinite(value) or not np.isfinite(height):
        return None
    x, y = (height, value) if horizontal else (value, height)
    item = pg.ScatterPlotItem(
        [x],
        [y],
        symbol="t3" if horizontal else "t",  # pointing back at the bar
        size=PEAK_MARKER_PX,
        brush=pg.mkBrush(color),
        pen=pg.mkPen(theme.current().plot_background, width=0.8),
    )
    item.setZValue(14)  # over the bars and the center lines
    plot.addItem(item, ignoreBounds=True)
    return item


class PeriodMarker(pg.GraphicsObject):
    """One cycle of the dominant period, drawn as a bar under the top edge of a trace plot.

    The spectrum says the signal repeats every 89 minutes; this puts 89 minutes
    against the trace, so the eye can check the claim against the waves. The
    bar starts a little inside the left edge of the stretch on screen and is
    as long as the period; its label names the period. Drawn in device pixels
    after the ends are mapped, as the other items of the viewer are, so the
    bar keeps its thickness and its text its size at every zoom.
    """

    def __init__(self, z: float = 30.0):
        super().__init__()
        self.setZValue(z)
        # Taken at build time, for a window that keeps a theme of its own.
        self._color = QColor(theme.current().text)
        self._x0 = np.nan
        self._length = 0.0
        self._label = ""

    def set_period(self, x0: float, length: float, label: str) -> None:
        """Put the bar from ``x0`` over ``length`` (both in the plot's x units), named ``label``."""
        self._x0, self._length, self._label = float(x0), float(length), label
        self.prepareGeometryChange()
        self.update()

    def clear(self) -> None:
        self.set_period(np.nan, 0.0, "")

    def dataBounds(self, ax, frac=1.0, orthoRange=None):
        return None

    def pixelPadding(self):
        return 0

    def _view_rect(self) -> QRectF:
        vb = self.getViewBox()
        if vb is None or not hasattr(vb, "viewRange"):
            return QRectF()
        (xmin, xmax), (ymin, ymax) = vb.viewRange()
        return QRectF(QPointF(xmin, ymin), QPointF(xmax, ymax)).normalized()

    def boundingRect(self):
        return QRectF() if not np.isfinite(self._x0) else self._view_rect()

    def viewRangeChanged(self, *args):
        self.prepareGeometryChange()
        self.update()

    def paint(self, p: QPainter, option, widget=None):
        if not np.isfinite(self._x0) or self._length <= 0:
            return
        rect = self._view_rect()
        if rect.isNull():
            return
        transform = p.transform()
        left = transform.map(QPointF(self._x0, rect.top()))
        right = transform.map(QPointF(self._x0 + self._length, rect.top()))
        top = min(transform.map(rect.topLeft()).y(), transform.map(rect.bottomLeft()).y())
        y = top + PEAK_BAR_PX
        p.save()
        p.resetTransform()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(self._color, 1.6)
        p.setPen(pen)
        p.drawLine(QPointF(left.x(), y), QPointF(right.x(), y))
        for end in (left.x(), right.x()):
            p.drawLine(QPointF(end, y - 4), QPointF(end, y + 4))
        font = QFont()
        font.setPixelSize(PEAK_FONT_PX)
        p.setFont(font)
        metrics = QFontMetricsF(font)
        width = metrics.horizontalAdvance(self._label)
        text_x = max(left.x(), min(0.5 * (left.x() + right.x()) - width / 2, right.x() - width))
        p.drawText(QPointF(text_x, y + 4 + metrics.ascent()), self._label)
        p.restore()


def unresolved_brush() -> QColor:
    """The fill of the periods a segment cannot resolve: the shade of an unknown, translucent."""
    color = QColor(theme.current().unknown)
    color.setAlpha(150)
    return color


def add_stacked_bars(
    plot: pg.PlotItem,
    result: Histogram,
    brushes: dict,
    horizontal: bool,
    pen=None,
) -> list[pg.BarGraphItem]:
    """The stacks of a histogram as bars, one item per stack, laid along the value axis.

    ``horizontal`` lays the value axis vertically and the counts to the right,
    the shape of a marginal beside a time series; otherwise the values run
    along x and the counts up. ``brushes`` maps a stack key to what fills it.
    """
    items = []
    base = np.zeros(len(result.edges) - 1, dtype=float)
    lower, upper = result.edges[:-1], result.edges[1:]
    for key, counts in result.stacks.items():
        top = base + counts
        if horizontal:
            item = pg.BarGraphItem(
                x0=base, x1=top, y0=lower, y1=upper, brush=brushes.get(key), pen=pen
            )
        else:
            item = pg.BarGraphItem(
                x0=lower, x1=upper, y0=base, y1=top, brush=brushes.get(key), pen=pen
            )
        plot.addItem(item)
        items.append(item)
        base = top
    return items


def histogram_fill(color: str) -> QColor:
    """The wash under one histogram outline: its own color, faint enough to stack.

    Several of these share a plot, so the fill has to read as an area without
    hiding the ones behind it; at this alpha two overlapping distributions
    still show where they overlap, as a third, deeper shade.
    """
    fill = QColor(color)
    fill.setAlpha(HIST_FILL_ALPHA)
    return fill


def add_step_outline(
    plot: pg.PlotItem,
    edges: np.ndarray,
    heights: np.ndarray,
    pen,
    horizontal: bool = False,
    fill: str | None = None,
) -> pg.PlotDataItem:
    """The outline of a histogram as a step curve: what several of them can share one plot as.

    ``fill`` washes the area under the steps in that color, for the layouts
    where the outline is the whole of the histogram; where it is drawn over
    stacked bars there is nothing to fill, the stacks being the area already.
    """
    if horizontal:
        # A step curve only steps along x, so a sideways outline is drawn as
        # the polygon of its corners.
        ys = np.repeat(edges, 2)
        xs = np.concatenate(([0.0], np.repeat(heights, 2), [0.0]))
        curve = pg.PlotDataItem(xs, ys, pen=pen)
    elif fill is None:
        curve = pg.PlotDataItem(edges, heights, stepMode="center", pen=pen)
    else:
        curve = pg.PlotDataItem(
            edges,
            heights,
            stepMode="center",
            pen=pen,
            fillLevel=0.0,
            fillBrush=pg.mkBrush(histogram_fill(fill)),
        )
    plot.addItem(curve)
    return curve


def spectrum_xy(spectrum: Spectrum, period_axis: str) -> tuple[np.ndarray, np.ndarray]:
    """The log10 coordinates of a spectrum as drawn, binned in log period, the period along ``period_axis``."""
    floor = np.finfo(float).tiny
    periods, power = spectrum.binned()
    log_period = np.log10(periods)
    log_power = np.log10(np.maximum(power, floor))
    return (log_period, log_power) if period_axis == "x" else (log_power, log_period)


def add_spectrum_curve(
    plot: pg.PlotItem, spectrum: Spectrum, pen, period_axis: str
) -> pg.PlotDataItem:
    x, y = spectrum_xy(spectrum, period_axis)
    curve = pg.PlotDataItem(x, y, pen=pen)
    plot.addItem(curve)
    return curve


def shade_unresolved(
    plot: pg.PlotItem, log_segment: float, period_axis: str
) -> pg.LinearRegionItem:
    """Grey the periods beyond the segment length, which the estimate cannot resolve."""
    far = log_segment + 6.0
    region = pg.LinearRegionItem(
        values=(log_segment, far),
        orientation="vertical" if period_axis == "x" else "horizontal",
        brush=pg.mkBrush(unresolved_brush()),
        pen=pg.mkPen(None),
        movable=False,
    )
    region.setZValue(-8)
    plot.addItem(region, ignoreBounds=True)
    return region


def implausible_brush() -> QColor:
    """The ground under the readings no instrument could have produced: the warning amber, faint."""
    color = QColor(theme.current().warning)
    color.setAlpha(45)
    return color


def shade_implausible(
    plot: pg.PlotItem, bounds: tuple[float, float], value_axis: str
) -> list[pg.LinearRegionItem]:
    """Put an amber ground under the stretches of the value axis outside the plausible range.

    Only wanted where a histogram has been told to count the implausible
    readings too: the bins beyond the range are then real counts of real
    samples, and what they need is not to be hidden but to be marked as what
    they are, in the amber this viewer uses for an impossible reading
    everywhere else.
    """
    orientation = "vertical" if value_axis == "x" else "horizontal"
    brush = pg.mkBrush(implausible_brush())
    items = []
    span = max(abs(bounds[1] - bounds[0]), 1.0) * 1e3
    for low, high in ((bounds[0] - span, bounds[0]), (bounds[1], bounds[1] + span)):
        region = pg.LinearRegionItem(
            values=(low, high),
            orientation=orientation,
            brush=brush,
            pen=pg.mkPen(None),
            movable=False,
        )
        region.setZValue(-9)
        plot.addItem(region, ignoreBounds=True)
        items.append(region)
    return items


def period_range(spectrum: Spectrum) -> tuple[float, float]:
    """The log10 period span an axis should show for a spectrum."""
    periods = spectrum.periods
    return (float(np.log10(periods[0])), float(np.log10(periods[-1])))


def caption_for(spectrum: Spectrum, unit: str, compact: bool = False) -> str:
    """What a spectrum plot writes in its corner: the dominant period, its share, the segments.

    ``compact`` breaks it into short lines, for a plot a couple of hundred
    pixels wide. A Lomb-Scargle estimate says how many measurements it was
    taken over, and its share is the variance a sinusoid of the peak period
    explains, which is what that periodogram measures.
    """
    period, share = spectrum.dominant()
    if spectrum.lomb_scargle:
        if np.isfinite(period):
            line = (
                f"peak {format_period(period)}<br>explains {share * 100:.0f} % of the variance"
                if compact
                else (
                    f"dominant period {format_period(period)}, a sinusoid of it explains "
                    f"{share * 100:.0f} % of the variance"
                )
            )
        else:
            line = "no dominant period"
        segments = f"Lomb-Scargle over {spectrum.n_points:,} measurements"
        return f"{line}<br>{segments}" if compact else f"{line}, {segments}"
    if np.isfinite(period):
        line = (
            f"peak {format_period(period)}<br>{share * 100:.0f} % of the power"
            if compact
            else f"dominant period {format_period(period)}, {share * 100:.0f} % of the power"
        )
    else:
        line = "no dominant period"
    segments = (
        f"whole stretch ({format_period(spectrum.segment_s)})"
        if spectrum.n_segments == 1
        else f"{spectrum.n_segments} segments of {format_period(spectrum.segment_s)}"
    )
    return f"{line}<br>{segments}" if compact else f"{line}, {segments}"


def format_width(width: float, unit: str) -> str:
    """The width of a bin with its unit (``0.0311 MPa``), in the unit given and never prefixed."""
    return f"{width:.3g} {unit}".rstrip()


def stack_keys(kinds: Sequence[str]) -> list[str]:
    """The order the stacks of a histogram are laid in: normal, transient, steady, then unknown."""
    order = ("normal", "transient", "steady", "unknown")
    return [kind for kind in order if kind in set(kinds)]


def set_log_period_axis(plot: pg.PlotItem, side: str, label: str = "period") -> LogPeriodAxisItem:
    """Replace one axis of ``plot`` with a period axis and label it."""
    axis = LogPeriodAxisItem(orientation=side)
    plot.setAxisItems({side: axis})
    plot.setLabel(side, label)
    return axis


def power_label(unit: str) -> str:
    """The label of a power axis: the density's unit when the series has one."""
    return f"power [{unit}²/Hz]" if unit and unit != "-" else "power"
