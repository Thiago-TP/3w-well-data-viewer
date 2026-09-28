"""The timelines page: a grid of well timelines, one interactive per-well plot each.

Every plot is one well. Each real instance recorded on it is a bar from its
first to its last timestamp, stacked on the instances it overlaps in time, so a
well recorded twice shows at a glance. Hovering a bar highlights the instances
it overlaps and hatches the stretch they share, and a tooltip gives its span;
clicking it asks the main
window for an ``InstanceWindow`` with their time series. The bars are colored
by their fault folder, or, at the user's choice, by how much of one sensor
each instance recorded, which turns the grid into the history of that sensor
on every well.
"""

from functools import partial

import numpy as np
import pandas as pd
import pyqtgraph as pg
from PySide6.QtCore import QEvent, QPointF, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QFontMetrics
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGridLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QToolBar,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from overlap_viewer.algorithms.interpolation import format_spacing
from overlap_viewer.backend import theme
from overlap_viewer.backend.availability import ABSENT, FROZEN, LIVE, Availability
from overlap_viewer.backend.config import (
    BAR_HEIGHT,
    DEFAULT_COLUMNS,
    DEFAULT_GAP_HOURS,
    GRID_SPACING,
    MAX_LANE_SLOTS,
    MIN_LANE_SLOTS,
    REACH_LABELS,
)
from overlap_viewer.backend.dataset import (
    DatasetInfo,
    WellData,
    instance_title,
    lane_slots,
)
from overlap_viewer.backend.labels import format_duration
from overlap_viewer.backend.palette import (
    bar_color,
    fault_color,
    legend_entries,
    legend_key,
    legend_label,
)
from overlap_viewer.backend.profiles import (
    DESCRIPTOR_CHOICES,
    DESCRIPTOR_MODES,
    GRID_CAVEAT,
    DescriptorChoice,
    descriptor_column,
)
from overlap_viewer.backend.timemap import TimeMap
from overlap_viewer.frontend.heatmap import StateKey, ramp_color
from overlap_viewer.frontend.items import (
    IMPLAUSIBLE_MARK,
    ORDER_MARK,
    InstanceBarsItem,
    ScrollFriendlyViewBox,
    SeamsItem,
    SegmentsItem,
    TimeAxisItem,
    WheelToParent,
)
from overlap_viewer.frontend.legend import LegendBar
from overlap_viewer.frontend.passes import Passes
from overlap_viewer.frontend.styling import TOOLTIP_FOREVER_MS

HINT = (
    "Hover a bar to see the instance and the instances it overlaps | click a bar to open their "
    "time series | click a color in the key to show only that fault's wells | drag to pan | "
    "Ctrl + wheel to zoom | F1 for help"
)

LANE_PX = 26  # height of one stack level on screen
PLOT_CHROME_PX = 26 + 12  # time axis, margins

SORT_KEYS = {
    "Well number": lambda w: (w.well,),
    "Overlapping instances": lambda w: (-w.n_overlapping, w.well),
    "Instances": lambda w: (-w.n_instances, w.well),
    "Deepest pile-up": lambda w: (-w.n_lanes, -w.n_overlapping, w.well),
}

# What a bar's fill can say: the fault; how much of a sensor was recorded, or
# how much of what was recorded was actually measured rather than filled in by
# the historian (these two name a sensor and take the ramp key); and what the
# Instances map made of the instance, its cluster or its typicality, once that
# page has computed them.
COLORINGS = (
    "Fault folder",
    "Availability of a sensor",
    "Measurements of a sensor",
    "Descriptor of a sensor",
    "Sensors the Toolkit's CleanSignals keeps",
    "Cluster of the Instances map",
    "Typicality of the Instances map",
    "Agreement with the model outputs",
)
COLORING_KINDS = (
    "fault",
    "availability",
    "measured",
    "descriptor",
    "cleaned",
    "cluster",
    "typicality",
    "model",
)
SENSOR_KINDS = ("availability", "measured", "descriptor")
MAP_KINDS = ("cluster", "typicality")
DESCRIPTOR_TIP = (
    "Which figure of the sensor's series tints the bars: how long its autocorrelation takes to "
    "halve (a slow, smooth series against a busy one); its signal-to-noise ratio, the variance of "
    "the series over the variance of its sample-to-sample differences; the slope of Zhang's "
    "Gaussianity regression, 1 for a Gaussian series, more for heavier tails; its skewness; or "
    "its excess kurtosis. Melo's characterisation of a variable (thesis, section 4.1). Every bar "
    "is ranked among the bars on show, faint for the smallest and full for the largest; hover a "
    "bar for the value."
)
DESCRIPTOR_MODE_TIP = (
    "What the figure is taken over. Interpolated: the whole 1 Hz grid, most of whose samples the "
    "historian drew between the readings it archived, which is what a pipeline reads. "
    f"Measurements: the readings alone. {GRID_CAVEAT.capitalize()}."
)


def faults_of(data: WellData, index: int, info: DatasetInfo) -> str:
    """The fault behind one bar, or every fault, ``+``-joined, when a joined bar mixes folders."""
    return " + ".join(
        info.fault_name(fault_class)
        for fault_class in sorted({fault_class for fault_class, _ in data.colors[index]})
    )


def bar_rows(availability: Availability, data: WellData, index: int) -> list[int]:
    """The rows of ``availability`` behind one bar: the instances it stands for."""
    return [availability.index_of(data.well, member) for member in data.members[index]]


def implausible_of(availability: Availability | None, data: WellData, index: int) -> list[str]:
    """The sensors with a reading outside the plausible range in any instance behind one bar."""
    if availability is None:
        return []
    rows = bar_rows(availability, data, index)
    flagged = availability.implausible[rows].any(axis=0)
    return [name for name, flag in zip(availability.sensors, flagged) if flag]


def describe_instance(
    data: WellData, index: int, info: DatasetInfo, availability: Availability | None = None
) -> str:
    """One line about a bar: name, fault, reach, span, size, level, partners, implausible readings.

    A bar joined from several instances names them, and every color it
    carries, in place of a single fault and reach.
    """
    row = data.rows.iloc[index]
    members = data.members[index]
    if data.stitched_view:
        pieces = len(data.pieces[index])
        what = (
            f"stitches {len(members)} instances from {pieces} recording"
            f"{'s' if pieces > 1 else ''}, the silences between them left out | "
            + " + ".join(
                legend_label(fault_class, reach, info.fault_names)
                for fault_class, reach in data.colors[index]
            )
        )
    elif len(members) > 1:
        origin = data.origin.rows
        names = [
            f"{instance_title(origin.iloc[m])} ({info.fault_name(int(origin.iloc[m]['fault_class']))})"
            for m in members[:4]
        ]
        if len(members) > 4:
            names.append(f"+{len(members) - 4} more")
        what = f"joins {len(members)} instances: {', '.join(names)} | " + " + ".join(
            legend_label(fault_class, reach, info.fault_names)
            for fault_class, reach in data.colors[index]
        )
    else:
        fault_class = int(row["fault_class"])
        reach = "" if fault_class == 0 else f" | {REACH_LABELS[row['reach']]}"
        what = f"{info.fault_name(fault_class)}{reach}"
    start, end = pd.Timestamp(row["start"]), pd.Timestamp(row["end"])
    end_fmt = "%H:%M:%S" if end.date() == start.date() else "%Y-%m-%d %H:%M:%S"
    noun = "bar" if data.joined_view else "instance"
    partners = data.partners[index]
    if len(partners):
        names = [
            f"{instance_title(data.rows.iloc[j])} ({faults_of(data, j, info)})"
            for j in partners[:4]
        ]
        if len(partners) > 4:
            names.append(f"+{len(partners) - 4} more")
        overlap = (
            f"overlaps {len(partners)} {noun}{'s' if len(partners) > 1 else ''}: "
            + ", ".join(names)
        )
    else:
        overlap = f"overlaps no other {noun}"
    flagged = implausible_of(availability, data, index)
    warning = f" | ⚠ readings outside the plausible range: {', '.join(flagged)}" if flagged else ""
    pairs = (
        availability.out_of_order_pairs(bar_rows(availability, data, index))
        if availability is not None
        else []
    )
    if pairs:
        warning += " | ⚠ pressures out of order: " + ", ".join(f"{a} and {b}" for a, b in pairs)
    return (
        f"{instance_title(row)} | {what} | {start:%Y-%m-%d %H:%M:%S} → {end.strftime(end_fmt)} "
        f"({row['hours']:.1f} h, {int(row['n_samples']):,} samples) | stack level {int(row['lane']) + 1} | {overlap}"
        f"{warning}"
    )


def bar_tooltip(data: WellData, index: int) -> str:
    """The tooltip of one bar: its name, where it starts and ends, and how long it lasts.

    The status bar says this too, but at the other end of the window and in
    the middle of a long line; the tooltip puts the span where the pointer is.
    A joined bar spans from the first sample of its earliest instance to the
    last sample of its latest.
    """
    row = data.rows.iloc[index]
    start, end = pd.Timestamp(row["start"]), pd.Timestamp(row["end"])
    seconds = (end - start).total_seconds()
    members = len(data.members[index])
    joined = f" ({members} instances joined)" if members > 1 else ""
    if data.stitched_view:
        # The span is the calendar's; what the bar holds is its recordings alone.
        recorded = float(row["hours"]) * 3600
        pieces = len(data.pieces[index])
        return (
            f"<nobr><b>{instance_title(row)}</b> ({members} instances stitched from {pieces} "
            f"recording{'s' if pieces > 1 else ''})</nobr>"
            '<table cellspacing="0" cellpadding="1">'
            f"<tr><td>first</td><td>&nbsp;{start:%Y-%m-%d %H:%M:%S}</td></tr>"
            f"<tr><td>last</td><td>&nbsp;{end:%Y-%m-%d %H:%M:%S}</td></tr>"
            f"<tr><td>recorded</td><td>&nbsp;{format_duration(recorded)} ({recorded / 3600:.2f} h)"
            "</td></tr>"
            f"<tr><td>span</td><td>&nbsp;{format_duration(seconds)} ({seconds / 3600:.2f} h)"
            "</td></tr></table>"
        )
    return (
        f"<nobr><b>{instance_title(row)}</b>{joined}</nobr>"
        '<table cellspacing="0" cellpadding="1">'
        f"<tr><td>start</td><td>&nbsp;{start:%Y-%m-%d %H:%M:%S}</td></tr>"
        f"<tr><td>end</td><td>&nbsp;{end:%Y-%m-%d %H:%M:%S}</td></tr>"
        f"<tr><td>duration</td><td>&nbsp;{format_duration(seconds)} ({seconds / 3600:.2f} h)"
        "</td></tr></table>"
    )


def describe_sensor_in_bar(
    availability: Availability, data: WellData, index: int, sensor: str, measured: bool = False
) -> str:
    """How much of one sensor the instances behind a bar recorded: the sentence behind its tint.

    ``measured`` leads with how much of the live signal was measured rather
    than filled in, which is what the bar says under that coloring.
    """
    rows = bar_rows(availability, data, index)
    column = availability.sensors.index(sensor)
    shares, flagged = availability.shares_of(rows, column)
    parts = []
    if measured and availability.measured:
        share, spacing = availability.measured_of(rows, column)
        if np.isfinite(share):
            parts.append(
                f"{sensor}: {share:.0%} of its live samples are measurements, one every "
                f"{format_spacing(spacing)} of signal"
            )
        else:
            parts.append(f"{sensor}: live nowhere, so nothing to measure")
        parts.append(f"live in {shares[LIVE]:.0%} of the samples")
    else:
        parts.append(f"{sensor}: live in {shares[LIVE]:.0%} of the samples")
    if shares[FROZEN] > 0:
        parts.append(f"frozen in {shares[FROZEN]:.0%}")
    if shares[ABSENT] > 0:
        parts.append(f"absent from {shares[ABSENT]:.0%}")
    return ", ".join(parts) + (" | ⚠ readings outside the plausible range" if flagged else "")


class ElidedLabel(QLabel):
    """A single-line label that elides its text instead of growing the window."""

    def __init__(self, text: str = "", parent=None):
        super().__init__(parent)
        self._full = ""
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setText(text)

    def setText(self, text: str) -> None:
        self._full = text
        self.setToolTip(text)
        self._refresh()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._refresh()

    def _refresh(self) -> None:
        metrics = QFontMetrics(self.font())
        super().setText(
            metrics.elidedText(self._full, Qt.TextElideMode.ElideRight, max(self.width() - 8, 50))
        )


class WellTimelinePlot(WheelToParent, pg.PlotWidget):
    """One well: its instances as bars on stack levels, over a gap-compressed time axis.

    Signals
    -------
    hovered(int)
        Row position of the instance under the pointer, ``-1`` when none.
    clicked(int)
        Row position of the instance clicked with the left button.
    """

    hovered = Signal(int)
    clicked = Signal(int)

    def __init__(
        self,
        data: WellData,
        info: DatasetInfo,
        slots: int,
        compressed: bool = True,
        gap_hours: float = DEFAULT_GAP_HOURS,
        parent=None,
    ):
        self._axis = TimeAxisItem(orientation="bottom")
        super().__init__(
            parent=parent, viewBox=ScrollFriendlyViewBox(), axisItems={"bottom": self._axis}
        )
        self.data = data
        self.info = info
        self.slots = max(slots, data.n_lanes)
        self._gap_hours = gap_hours
        self._hover = -1
        self._timemap: TimeMap | None = None
        self._x0 = np.empty(0)
        self._x1 = np.empty(0)
        self._gap_lines: list[pg.InfiniteLine] = []
        # What the bars are filled with and which wear the mark; the fault
        # colors until a page says otherwise.
        self._fills: list[list[str]] | None = None
        self._marks: list[int] | None = None
        # The summary of the title counts bursts, which only the compressed map knows.
        self._bursts = TimeMap.build(*data.spans(), gap_hours=gap_hours, compressed=True)

        plot = self.getPlotItem()
        vb = plot.getViewBox()
        vb.invertY(True)
        vb.setMouseEnabled(x=True, y=False)
        vb.setMouseMode(pg.ViewBox.PanMode)
        plot.hideButtons()
        left = plot.getAxis("left")
        left.setTicks([[(lane, str(lane + 1)) for lane in range(self.slots)]])
        left.setWidth(30)
        left.setStyle(tickLength=3)
        plot.setYRange(-0.7, self.slots - 0.3, padding=0)
        vb.setLimits(yMin=-0.7, yMax=self.slots - 0.3)

        self._blocks = SegmentsItem(z=-20)
        plot.addItem(self._blocks, ignoreBounds=True)
        for lane in range(data.n_lanes):
            line = pg.InfiniteLine(
                pos=lane, angle=0, pen=pg.mkPen(theme.current().grid_line, width=1), movable=False
            )
            line.setZValue(-15)
            plot.addItem(line, ignoreBounds=True)
        self._bars = InstanceBarsItem()
        plot.addItem(self._bars)

        # Until the user pans or zooms, the view follows the widget size (see resizeEvent).
        self._auto_view = True
        vb.sigRangeChangedManually.connect(self._on_manual_range)
        self.set_compressed(compressed)

        self.scene().sigMouseMoved.connect(self._on_mouse_moved)
        self.scene().sigMouseClicked.connect(self._on_mouse_clicked)

    # -- layout

    @property
    def timemap(self) -> TimeMap:
        return self._timemap

    def default_fills(self) -> list[list[str]]:
        """The fault colors of the bars: one color per distinct legend entry behind each."""
        return [
            list(dict.fromkeys(bar_color(fault_class, reach) for fault_class, reach in keys))
            for keys in self.data.colors
        ]

    def set_coloring(self, fills: list[list[str]] | None, marks: list[int] | None) -> None:
        """Fill the bars with ``fills`` (``None`` for the fault colors) and give them the corner ``marks``."""
        self._fills = fills
        self._marks = marks
        self._draw_bars()

    def _draw_bars(self) -> None:
        data = self.data
        rows = data.rows
        edges = [fault_color(int(fc)) for fc in rows["fault_class"]]
        suffixes = [f" +{len(members) - 1}" if len(members) > 1 else "" for members in data.members]
        self._bars.set_bars(
            self._x0,
            self._x1,
            rows["lane"].to_numpy(dtype=float),
            self._fills if self._fills is not None else self.default_fills(),
            edges,
            rows["stamp"],
            suffixes,
            self._marks,
        )

    def set_compressed(self, compressed: bool) -> None:
        """Lay the bars on a gap-compressed axis (``True``) or on the calendar.

        A stitched well has no silence left to compress or to show: its axis
        lays its recordings back to back whatever ``compressed`` says, and a
        solid line over the bar marks each stitch.
        """
        data = self.data
        if data.stitched_view:
            timemap = TimeMap.build(*data.spans(), gap_hours=0.0, gap_share=0.0)
        else:
            timemap = TimeMap.build(
                data.starts, data.ends, gap_hours=self._gap_hours, compressed=compressed
            )
        self._timemap = timemap
        self._x0 = timemap.to_x(data.starts)
        self._x1 = timemap.to_x(data.ends)
        self._draw_bars()

        colors = theme.current()
        spans = timemap.block_spans()
        self._blocks.set_segments(
            [a for a, _ in spans], [b for _, b in spans], [colors.block_fill] * len(spans)
        )
        plot = self.getPlotItem()
        for line in self._gap_lines:
            plot.removeItem(line)
        self._gap_lines = []
        if data.stitched_view:
            stitches = SeamsItem(stitch=True)
            stitches.set_seams(timemap.gap_centers())
            plot.addItem(stitches, ignoreBounds=True)
            self._gap_lines.append(stitches)
        for x in [] if data.stitched_view else timemap.gap_centers():
            line = pg.InfiniteLine(
                pos=x,
                angle=90,
                movable=False,
                pen=pg.mkPen(colors.gap_line, width=1, style=Qt.PenStyle.DashLine),
            )
            line.setZValue(-12)
            plot.addItem(line, ignoreBounds=True)
            self._gap_lines.append(line)

        self._axis.set_timemap(timemap, major_with_time=timemap.calendar_days < 2)
        span = timemap.span
        vb = plot.getViewBox()
        vb.setLimits(
            xMin=-0.25 * span, xMax=1.05 * span, minXRange=min(1 / 60, span), maxXRange=1.3 * span
        )
        self._auto_view = True
        self.reset_view()
        if self._hover >= 0:
            self._set_hover(self._hover)

    def reset_view(self) -> None:
        """Show the whole axis, with room on the left for the date of the first recording block.

        A tick label is drawn only when it fits inside the axis, so the label
        of the first block start, which sits at the very left, needs half its
        width of padding before it; the padding is converted from pixels at
        the current widget width.
        """
        vb = self.getPlotItem().getViewBox()
        span = self._timemap.span
        width = vb.width() if vb.width() > 50 else 700.0
        left = (0.5 * self._axis.major_label_px() + 4.0) / width * span
        vb.setXRange(-left, span + 0.01 * span, padding=0)

    def _on_manual_range(self, *args) -> None:
        self._auto_view = False

    def view_state(self) -> tuple[bool, list]:
        """Whether the view still follows the widget, and the ranges it shows; for a rebuild to keep."""
        return (self._auto_view, self.getPlotItem().getViewBox().viewRange())

    def set_view_state(self, state: tuple[bool, list]) -> None:
        """Take back what ``view_state`` gave: a zoomed view stays zoomed, a fitted one keeps fitting."""
        auto, (x_range, y_range) = state
        if auto:
            return
        self._auto_view = False
        self.getPlotItem().getViewBox().setRange(xRange=x_range, yRange=y_range, padding=0)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # pyqtgraph resizes the view from its own constructor, before this class has set anything.
        if getattr(self, "_auto_view", False) and getattr(self, "_timemap", None) is not None:
            self.reset_view()

    def title_html(self, extra: str = "") -> str:
        """The well's name and a one-line summary of its recording, for the label above the plot.

        ``extra`` is appended to the summary: what the page's coloring adds,
        such as the measurements of the sensor the bars are tinted by.
        """
        data, bursts = self.data, self._bursts
        rows = data.rows
        first, last = pd.Timestamp(rows["start"].min()), pd.Timestamp(rows["end"].max())
        days = bursts.calendar_days
        share = bursts.recorded_hours / max(24 * days, 1e-9)
        n_blocks = len(bursts.blocks)
        n_bars, instances = data.n_instances, data.origin.n_instances
        if data.stitched_view:
            pieces = sum(len(p) for p in data.pieces)
            counts = (
                f"{instances} instances stitched from {pieces} recording"
                f"{'s' if pieces > 1 else ''} into {n_bars} bar{'s' if n_bars > 1 else ''}"
            )
        elif data.joined_view and n_bars < instances:
            still = data.n_overlapping
            counts = (
                f"{instances} instances joined into {n_bars} bar{'s' if n_bars > 1 else ''} | "
                f"{still} still overlap{'s' if still == 1 else ''} another"
                + (" (labels disagree)" if still else "")
            )
        else:  # nothing to join on this well: the plain count says it all
            counts = (
                f"{data.n_instances} instance{'s' if data.n_instances > 1 else ''} | "
                f"{data.n_overlapping} overlap another"
            )
        samples = int(rows["n_samples"].sum())
        summary = (
            f"{counts} | {samples:,} samples | deepest pile-up {data.n_lanes} | "
            f"{bursts.recorded_hours:,.1f} h in {n_blocks} burst{'s' if n_blocks > 1 else ''} over "
            f"{days:,.0f} day{'s' if round(days) != 1 else ''} ({share:.1%}) | {first:%Y-%m-%d} → {last:%Y-%m-%d}"
            + (f" | {extra}" if extra else "")
        )
        return (
            f'<span style="font-size:10pt; font-weight:bold;">{data.label}</span>'
            f'&nbsp;&nbsp;<span style="font-size:8pt; color:{theme.current().muted};">{summary}</span>'
        )

    # -- mouse

    def _hit(self, scene_pos) -> int:
        vb = self.getPlotItem().getViewBox()
        if not vb.sceneBoundingRect().contains(scene_pos):
            return -1
        point = vb.mapSceneToView(scene_pos)
        tolerance = 2.0 * vb.viewPixelSize()[0]  # two pixels, so a sliver can be hit
        lanes = self.data.rows["lane"].to_numpy(dtype=float)
        hits = np.flatnonzero(
            (point.x() >= self._x0 - tolerance)
            & (point.x() <= self._x1 + tolerance)
            & (np.abs(point.y() - lanes) <= BAR_HEIGHT / 2)
        )
        return int(hits[0]) if len(hits) else -1

    def _on_mouse_moved(self, pos) -> None:
        index = self._hit(pos)
        if index != self._hover:
            self._set_hover(index)

    def _set_hover(self, index: int) -> None:
        self._hover = index
        if index < 0:
            self._bars.clear_highlight()
        else:
            partners = self.data.partners[index]
            starts, ends = self.data.starts, self.data.ends
            lanes = self.data.rows["lane"].to_numpy(dtype=float)
            hatches = []
            for j in partners:
                shared_start = max(starts[index], starts[j])
                shared_end = min(ends[index], ends[j])
                hx0, hx1 = self._timemap.to_x([shared_start, shared_end])
                hx1 = max(hx1, hx0 + 1e-6)
                hatches.append((float(hx0), float(hx1), float(lanes[j])))
                hatches.append((float(hx0), float(hx1), float(lanes[index])))
            self._bars.set_highlight(index, partners, hatches)
        self.hovered.emit(index)

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        if self._hover != -1:
            self._set_hover(-1)

    def viewportEvent(self, event) -> bool:
        """Show the span of the bar under the pointer as a tooltip, up until the pointer leaves it."""
        if event.type() != QEvent.Type.ToolTip:
            return super().viewportEvent(event)
        index = self._hit(self.mapToScene(event.pos()))
        if index < 0:
            QToolTip.hideText()
            event.ignore()
            return True
        # Three short lines: not put through ``bounded_tooltip``, whose fixed
        # width would leave most of the box empty.
        QToolTip.showText(
            event.globalPos(),
            bar_tooltip(self.data, index),
            self.viewport(),
            self._bar_rect(index),
            TOOLTIP_FOREVER_MS,
        )
        return True

    def _bar_rect(self, index: int) -> QRect:
        """Where one bar is on the viewport, as wide as ``_hit`` takes it to be."""
        vb = self.getPlotItem().getViewBox()
        lane = float(self.data.rows["lane"].iloc[index])
        tolerance = 2.0 * vb.viewPixelSize()[0]
        corner = vb.mapViewToScene(QPointF(self._x0[index] - tolerance, lane - BAR_HEIGHT / 2))
        opposite = vb.mapViewToScene(QPointF(self._x1[index] + tolerance, lane + BAR_HEIGHT / 2))
        return self.mapFromScene(QRectF(corner, opposite).normalized()).boundingRect()

    def _on_mouse_clicked(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton or event.double():
            return
        index = self._hit(event.scenePos())
        if index >= 0:
            event.accept()
            self.clicked.emit(index)


class WellCell(QWidget):
    """One cell of the grid: the well's title, wrapping as needed, above its timeline."""

    def __init__(self, plot: WellTimelinePlot, extra: str = "", parent=None):
        super().__init__(parent)
        self.plot = plot
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(1)
        self.title = QLabel(plot.title_html(extra))
        self.title.setTextFormat(Qt.TextFormat.RichText)
        self.title.setWordWrap(True)
        self.title.setContentsMargins(6, 0, 6, 0)
        layout.addWidget(self.title)
        layout.addWidget(plot)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)


class TimelinesPage(QWidget):
    """Grid of well timelines with filtering, sorting and the legend of the colors drawn.

    Signals
    -------
    status(str)
        What the main window's status bar should say: the instance under the
        pointer, or the page's hint.
    summary_changed()
        The one-line count of what is on show has changed.
    open_requested(WellData, int)
        A bar was clicked: the well as drawn, and the bar's row position.
    """

    status = Signal(str)
    summary_changed = Signal()
    open_requested = Signal(object, int)

    def hint(self) -> str:
        """What the status bar says when the pointer is over nothing in particular."""
        return HINT

    def __init__(
        self,
        info: DatasetInfo,
        gap_hours: float = DEFAULT_GAP_HOURS,
        columns: int = DEFAULT_COLUMNS,
        passes: Passes | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.info = info
        self._gap_hours = gap_hours
        # Where the profiles of the bars come from, when a coloring asks for
        # them; without it that coloring is not offered.
        self._passes = passes
        self._plots: dict[int, WellTimelinePlot] = {}
        self._cells: dict[int, WellCell] = {}
        self.wells: list[WellData] = []
        self._joined_wells: list[WellData] = []
        self._availability: Availability | None = None
        self._map_results = None  # what the Instances map computed, once it has
        self._model_results = None  # the model outputs loaded, once they are
        # Under the descriptor coloring: every bar's value and its rank among
        # the bars on show, by (well, bar).
        self._descriptor_values: dict[tuple[int, int], float] = {}
        self._descriptor_ranks: dict[tuple[int, int], float] = {}
        self._fault_filter: int | None = None
        self._catalogue = None
        self._summary = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(self._build_toolbar(columns))
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(8, 0, 8, 4)
        body_layout.setSpacing(6)
        # The key of the bars when they say how much of a sensor was recorded;
        # the color key of the faults takes its place otherwise.
        self._state_key = StateKey(("ramp", "frozen", "absent", "implausible", "order"))
        self._state_key.hide()
        body_layout.addWidget(self._state_key, 0, Qt.AlignmentFlag.AlignLeft)
        self._legend = LegendBar()
        self._legend.fault_clicked.connect(self.toggle_fault_filter)
        body_layout.addWidget(self._legend)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._container = QWidget()
        self._grid = QGridLayout(self._container)
        self._grid.setContentsMargins(0, 2, 0, 2)
        self._grid.setHorizontalSpacing(GRID_SPACING[0])
        self._grid.setVerticalSpacing(GRID_SPACING[1])
        self._empty = QLabel("No well matches the current filters.")
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty.hide()
        self._scroll.setWidget(self._container)
        body_layout.addWidget(self._scroll, 1)
        body_layout.addWidget(self._empty)
        layout.addWidget(body, 1)
        self._restyle()

    # -- construction

    def _build_toolbar(self, columns: int) -> QToolBar:
        passes = self._passes
        bar = QToolBar("Timelines")
        bar.setMovable(False)

        bar.addWidget(QLabel(" Columns "))
        self._columns = QSpinBox()
        self._columns.setRange(1, 4)
        self._columns.setValue(columns)
        self._columns.valueChanged.connect(self._relayout)
        bar.addWidget(self._columns)

        bar.addSeparator()
        bar.addWidget(QLabel(" Show "))
        self._filter = QComboBox()
        self._filter.addItems(["All wells", "Wells with overlaps"])
        self._filter.currentIndexChanged.connect(self._relayout)
        bar.addWidget(self._filter)

        bar.addWidget(QLabel(" Sort by "))
        self._sort = QComboBox()
        self._sort.addItems(list(SORT_KEYS))
        self._sort.currentIndexChanged.connect(self._relayout)
        bar.addWidget(self._sort)

        bar.addSeparator()
        self._compress = QCheckBox("Compress silences")  # the name the help and README use
        self._compress.setChecked(True)
        self._compress.setToolTip(
            "Collapse the months of silence between bursts of recording to narrow dashed blanks, "
            "so the instances stay visible; uncheck for a true calendar axis."
        )
        self._compress.toggled.connect(self._set_compressed)
        bar.addWidget(self._compress)
        self._join = QCheckBox("Join overlapping instances")
        self._join.setToolTip(
            "Merge the instances of a well that overlap in time into one bar wherever their labels "
            "agree on the shared stretch (an unlabeled sample agrees with anything). Instances "
            "whose labels disagree there stay apart, so the overlaps that remain are exactly the "
            "labeling conflicts. A bar joined from several fault folders is striped with every "
            "folder's color; clicking it opens the time series of every instance behind it."
        )
        self._join.toggled.connect(self._on_join_toggled)
        bar.addWidget(self._join)
        self._stitch = QCheckBox("Stitch instances")
        self._stitch.setToolTip(
            "Lay the joined bars of every well end to end, the silences between them left out, "
            "so that each well is one bar holding its whole history: clicking it opens every "
            "reading of the well as one recording, to see how its levels moved from one "
            "recording to the next, months apart. The time axis keeps the real timestamps and "
            "jumps at each stitch, which a solid line marks. Ticking it joins the overlapping "
            "instances too, and the join cannot be unticked while the stitch is on."
        )
        self._stitch.toggled.connect(self._on_stitch_toggled)
        bar.addWidget(self._stitch)
        # Whether the join was ticked by hand before the stitch ticked it, to be left as found.
        self._joined_by_hand = False

        bar.addSeparator()
        bar.addWidget(QLabel(" Bar color "))
        self._coloring = QComboBox()
        self._coloring.addItems(list(COLORINGS))
        self._coloring.setToolTip(
            "What fills a bar: the fault folder of its instance, tinted by how far the fault "
            "developed; how much of one sensor the instance recorded, so that the grid shows "
            "the history of that sensor on every well, an era of absence or a scattering of it; "
            "how much of what it recorded was actually measured, the rest being the straight "
            "lines the historian drew between measurements; one descriptor of the sensor's "
            "series (autocorrelation time, signal-to-noise ratio, Gaussianity, skewness, "
            "kurtosis), ranked among the bars on show; how many of its live sensors the 3W "
            "Toolkit's CleanSignals rule would keep, at the Toolkit's default thresholds, full for "
            "all of them and faint for few (hover a bar for which it discards, and why); or what "
            "the Instances map made of it. The sensor and Toolkit colorings read every instance in "
            "full the first time, behind a progress dialog, and keep the result in the cache."
        )
        self._coloring.currentIndexChanged.connect(self._recolor)
        bar.addWidget(self._coloring)
        if passes is None:
            for kind in ("measured", "descriptor", "cleaned"):
                self._coloring.model().item(COLORING_KINDS.index(kind)).setEnabled(False)
        # The map's colorings wait for the map to have computed something, the
        # model's for a set of outputs to be loaded.
        for kind in (*MAP_KINDS, "model"):
            self._coloring.model().item(COLORING_KINDS.index(kind)).setEnabled(False)
        self._sensor = QComboBox()
        self._sensor.setToolTip("The sensor the bars are tinted by")
        self._sensor.currentIndexChanged.connect(self._recolor)
        self._sensor_action = bar.addWidget(self._sensor)
        self._sensor_action.setVisible(False)
        # The descriptor coloring's own boxes: which figure, and on what.
        self._descriptor = QComboBox()
        for choice in DESCRIPTOR_CHOICES:
            self._descriptor.addItem(choice.name, choice.column)
        self._descriptor.setToolTip(DESCRIPTOR_TIP)
        self._descriptor.currentIndexChanged.connect(self._recolor)
        self._descriptor_actions = [bar.addWidget(self._descriptor)]
        self._descriptor_actions.append(bar.addWidget(QLabel(" on ")))
        self._descriptor_mode = QComboBox()
        self._descriptor_mode.addItems(list(DESCRIPTOR_MODES))
        self._descriptor_mode.setToolTip(DESCRIPTOR_MODE_TIP)
        self._descriptor_mode.currentIndexChanged.connect(self._recolor)
        self._descriptor_actions.append(bar.addWidget(self._descriptor_mode))
        for action in self._descriptor_actions:
            action.setVisible(False)

        # No button of its own: the key's own title bar is how it is retracted.
        key_action = QAction("Color key", self)
        key_action.setShortcut("Ctrl+L")
        key_action.triggered.connect(lambda: self._legend.set_collapsed(not self._legend.collapsed))
        self.addAction(key_action)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        bar.addWidget(spacer)
        self._fault_button = QPushButton()
        self._fault_button.setToolTip("Show every well again")
        self._fault_button.clicked.connect(lambda: self.toggle_fault_filter(self._fault_filter))
        # A widget in a toolbar is shown through its action, which overrides hide().
        self._fault_action = bar.addWidget(self._fault_button)
        self._fault_action.setVisible(False)
        return bar

    def set_catalogue(self, catalogue: pd.DataFrame, wells: list[WellData]) -> None:
        """Take a new catalogue and its wells: join each, read what they recorded, rebuild the grid.

        The very same catalogue again is the main window laying the pages out
        in a new theme: the grid is rebuilt for its colors, and every well
        keeps the stretch of time it was zoomed to and the grid its scroll.
        """
        same = catalogue is self._catalogue and bool(self._plots)
        views = {well: plot.view_state() for well, plot in self._plots.items()}
        anchor = self._scroll_anchor() if same else None
        self._catalogue = catalogue
        self.wells = list(wells)
        self._joined_wells = [well.joined() for well in self.wells]
        self._stitched_wells = [well.stitched() for well in self.wells]
        self._availability = self._build_availability()
        wanted = self._sensor.currentText()
        self._sensor.blockSignals(True)
        self._sensor.clear()
        self._sensor.addItems(self._availability.sensors)
        index = self._sensor.findText(wanted)
        self._sensor.setCurrentIndex(max(index, 0))
        self._sensor.blockSignals(False)
        self._build_grid(keep_scroll=same)
        if same:
            for well, state in views.items():
                plot = self._plots.get(well)
                if plot is not None:
                    plot.set_view_state(state)
            self._restore_scroll(anchor)

    def _shown_wells(self) -> list[WellData]:
        """The wells as the grid draws them: instance by instance, joined into bars, or stitched."""
        if self._stitch.isChecked():
            return self._stitched_wells
        return self._joined_wells if self._join.isChecked() else self.wells

    def _on_stitch_toggled(self, checked: bool) -> None:
        """Stitch or unstitch the wells; the join follows, and is left as it was found.

        Ticking the stitch ticks the join and locks it, a stitched well being
        made of joined bars; unticking it unlocks the join and unticks it only
        if the stitch was what ticked it. The silences are gone from a
        stitched well, so the compression box rests meanwhile.
        """
        self._join.blockSignals(True)
        if checked:
            self._joined_by_hand = self._join.isChecked()
            self._join.setChecked(True)
        else:
            self._join.setChecked(self._joined_by_hand)
        self._join.setEnabled(not checked)
        self._join.blockSignals(False)
        self._compress.setEnabled(not checked)
        self._on_join_toggled()

    def _on_join_toggled(self, *args) -> None:
        """Join or unjoin the instances, keeping the well the reader was looking at in view.

        The same wells, in the same order, are drawn either way (only the bars
        inside them change), so throwing the reader back to the first well of a
        long grid loses the very comparison the tick was made to see.
        """
        anchor = self._scroll_anchor()
        self._build_grid(keep_scroll=True)
        self._restore_scroll(anchor)

    def _build_grid(self, *args, keep_scroll: bool = False) -> None:
        """Build every timeline again, from the instances or from their joins."""
        for cell in self._cells.values():
            self._grid.removeWidget(cell)
            cell.hide()  # gone from the screen at once, not only when Qt gets to deleting it
            cell.deleteLater()
        self._plots = {}
        self._cells = {}
        shown = self._shown_wells()
        if self.coloring_kind == "descriptor":
            # The bars on show changed (joined or not), and so did their ranks.
            self._rank_descriptors()
        self.slots = lane_slots(shown, MIN_LANE_SLOTS, MAX_LANE_SLOTS)
        height = PLOT_CHROME_PX + LANE_PX * self.slots
        for well in shown:
            plot = WellTimelinePlot(
                well, self.info, self.slots, self._compress.isChecked(), self._gap_hours
            )
            plot.setFixedHeight(height + LANE_PX * max(0, well.n_lanes - self.slots))
            plot.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            plot.set_coloring(*self._coloring_of(well))
            plot.hovered.connect(partial(self._on_hover, plot))
            plot.clicked.connect(partial(self._on_click, plot))
            self._plots[well.well] = plot
            self._cells[well.well] = WellCell(plot, self._title_extra(well))

        present = set().union(*(well.present_colors() for well in shown))
        self._legend.set_entries(
            legend_entries(present, self.info.fault_names), self.info.fault_names
        )
        n_over = sum(1 for well in shown if well.n_overlapping > 0)
        n_overlapping = sum(well.n_overlapping for well in shown)
        version = f"3W {self.info.version} | " if self.info.version else ""
        instances = f"{version}{len(self._catalogue)} real instances on {len(shown)} wells"
        if self._stitch.isChecked():
            self._summary = f"{instances}, each well stitched into one bar "
        elif self._join.isChecked():
            bars = sum(well.n_instances for well in shown)
            self._summary = (
                f"{instances}, joined into {bars} bars, "
                f"{n_overlapping} still overlapping on {n_over} wells "
            )
        else:
            self._summary = f"{instances}, {n_overlapping} overlapping on {n_over} wells "
        self.summary_changed.emit()
        self._show_key()
        self._relayout(keep_scroll=keep_scroll)

    def summary(self) -> str:
        """One line for the status bar: what the grid is showing."""
        return self._summary

    # -- coloring

    def _build_availability(self) -> Availability:
        """What every instance recorded, with its profile when a page has already paid for the pass."""
        profiles = (
            self._passes.profiles_if_loaded(self.info.sensor_names)
            if self._passes is not None
            else None
        )
        return Availability.from_wells(self.wells, self.info, profiles=profiles)

    def _ensure_profiles(self) -> bool:
        """Have the bars' profiles on hand, reading the data if need be; ``False`` if cancelled."""
        if self._availability is not None and self._availability.measured:
            return True
        if self._passes is None:
            return False
        profiles = self._passes.profiles(self.info.sensor_names, parent=self.window())
        if profiles is None:
            return False
        self._availability = Availability.from_wells(self.wells, self.info, profiles=profiles)
        return True

    @property
    def coloring_kind(self) -> str:
        """``fault``, ``availability``, ``measured``, ``cluster`` or ``typicality``: what the Bar color box asks for."""
        return COLORING_KINDS[self._coloring.currentIndex()]

    @property
    def sensor_coloring(self) -> str | None:
        """The sensor the bars are tinted by, or ``None`` while they are not tinted by one."""
        if self.coloring_kind not in SENSOR_KINDS or self._availability is None:
            return None
        return self._sensor.currentText() or None

    @property
    def descriptor_choice(self) -> DescriptorChoice:
        """The descriptor the bars are tinted by under that coloring."""
        return DESCRIPTOR_CHOICES[max(self._descriptor.currentIndex(), 0)]

    @property
    def descriptor_measured(self) -> bool:
        """Whether the descriptor is taken on the measurements alone rather than on the grid."""
        return self._descriptor_mode.currentIndex() == 1

    def _loaded_profiles(self):
        return (
            self._passes.profiles_if_loaded(self.info.sensor_names)
            if self._passes is not None
            else None
        )

    def _title_extra(self, data: WellData) -> str:
        """What a well's header adds under a sensor coloring: that sensor's measurements on the well.

        Read from the profiles, and only when some page has already paid for
        them, so a header never starts a pass. Counted over the bars on show,
        as the samples of the header are: a sample two instances share is
        counted in each, and once in the joined view.
        """
        sensor, profiles = self.sensor_coloring, self._loaded_profiles()
        if sensor is None or profiles is None or self.info.is_enumerated(sensor):
            return ""
        keys = [self._bar_key(data, index) for index in range(data.n_instances)]
        if data.stitched_view:
            # A stitched bar has no profile of its own; its recordings are the joined bars.
            keys = [(data.well, p) for pieces in data.pieces for p in pieces]
        genuine = float(np.nansum(profiles.matrix(keys, data.joined_view, "n_genuine", [sensor])))
        valid = float(np.nansum(profiles.matrix(keys, data.joined_view, "n_valid", [sensor])))
        if valid <= 0:
            return f"{sensor}: no readings"
        return f"{sensor}: {genuine:,.0f} measurements of {valid:,.0f} readings ({genuine / valid:.1%})"

    def _rank_descriptors(self) -> None:
        """Look up the chosen descriptor of the chosen sensor for every bar on show, and rank them."""
        self._descriptor_values, self._descriptor_ranks = {}, {}
        profiles, sensor = self._loaded_profiles(), self.sensor_coloring
        if profiles is None or sensor is None:
            return
        column = descriptor_column(self.descriptor_choice, self.descriptor_measured)
        keys, values = [], []
        for data in self._shown_wells():
            for index in range(data.n_instances):
                keys.append((data.well, index))
                values.append(
                    profiles.descriptor(
                        self._bar_key(data, index), sensor, column, data.joined_view
                    )
                )
        values = np.asarray(values, dtype=float)
        ranks = np.full(len(values), np.nan)
        known = ~np.isnan(values)  # an infinite figure ranks largest
        if known.sum() > 1:
            order = values[known].argsort().argsort()
            ranks[known] = order / (known.sum() - 1)
        elif known.sum() == 1:
            ranks[known] = 1.0
        self._descriptor_values = dict(zip(keys, values.tolist()))
        self._descriptor_ranks = dict(zip(keys, ranks.tolist()))

    def describe_descriptor_in_bar(self, data: WellData, index: int) -> str:
        """The descriptor's value in one bar, on the grid and on the measurements, and its rank."""
        profiles, sensor = self._loaded_profiles(), self.sensor_coloring
        choice, measured = self.descriptor_choice, self.descriptor_measured
        if profiles is None or sensor is None:
            return f"{sensor}: the profiles have not been read"
        if data.stitched_view:
            return (
                f"{sensor}: the descriptors are taken over one recording at a time, not over a "
                "stitched well; untick 'Stitch instances' to rank the recordings"
            )
        key = self._bar_key(data, index)
        grid = profiles.descriptor(key, sensor, choice.column, data.joined_view)
        genuine = profiles.descriptor(key, sensor, f"{choice.column}_g", data.joined_view)
        first, second = (genuine, grid) if measured else (grid, genuine)
        where, elsewhere = (
            ("on the measurements", "on the grid")
            if measured
            else ("on the grid", "on the measurements")
        )
        if np.isnan(first):
            return f"{sensor}: no {choice.name.lower()} {where} (nothing live to describe)"
        parts = [
            (
                f"{sensor}: {choice.name.lower()} {choice.format(first)} {where} "
                f"({choice.format(second)} {elsewhere})"
            )
        ]
        rank = self._descriptor_ranks.get((data.well, index), float("nan"))
        if np.isfinite(rank):
            parts.append(f"rank {rank:.2f} among the {len(self._descriptor_ranks)} bars on show")
        if not measured and choice.inflated:
            parts.append(GRID_CAVEAT)
        return " | ".join(parts)

    def set_map_results(self, results) -> None:
        """Take what the Instances map computed, and offer its colorings."""
        self._map_results = results
        for kind in MAP_KINDS:
            self._coloring.model().item(COLORING_KINDS.index(kind)).setEnabled(results is not None)
        if self.coloring_kind in MAP_KINDS:
            self._recolor()

    def set_model_results(self, results) -> None:
        """Take the model outputs loaded (or none), and offer the coloring by their agreement."""
        self._model_results = results
        self._coloring.model().item(COLORING_KINDS.index("model")).setEnabled(results is not None)
        if self.coloring_kind == "model":
            if results is None:
                self._coloring.setCurrentIndex(0)
            else:
                self._recolor()

    def _member_keys(self, data: WellData, index: int) -> list[tuple[int, str]]:
        """The instances behind one bar as ``(fault_class, file)`` keys."""
        origin = data.origin.rows
        return [
            (int(origin["fault_class"].iloc[m]), str(origin["file"].iloc[m]))
            for m in data.members[index]
        ]

    def _model_fills(self, data: WellData) -> list[list[str]]:
        """The bars of one well tinted by how far the model agrees with their labels."""
        colors = theme.current()
        results = self._model_results
        fills = []
        for index in range(data.n_instances):
            share = results.agreement_of_members(self._member_keys(data, index))
            fills.append([ramp_color(share) if np.isfinite(share) else colors.block_fill])
        return fills

    def describe_model_in_bar(self, data: WellData, index: int) -> str:
        """How far the model agrees with the labels of one bar."""
        results = self._model_results
        if results is None:
            return "no model outputs loaded"
        keys = self._member_keys(data, index)
        if len(keys) == 1:
            return results.describe(*keys[0])
        share = results.agreement_of_members(keys)
        scored = sum(1 for key in keys if key in results.agreements)
        if not np.isfinite(share):
            return f"none of its {len(keys)} instances scored by {results.name}"
        return (
            f"{results.name}: agrees with the labels {share:.0%} of the compared time over "
            f"{scored} of its {len(keys)} instances"
        )

    def _map_key(self, data: WellData, index: int):
        """The key the map knows one bar by, or ``None`` when the map was drawn on the other view."""
        results = self._map_results
        if results is None or data.stitched_view or results.joined != data.joined_view:
            return None
        if data.joined_view:
            return (data.well, index)
        row = data.rows.iloc[index]
        return (int(row["fault_class"]), str(row["file"]))

    def _map_fills(self, data: WellData) -> list[list[str]]:
        """What the map's coloring fills the bars of one well with: the cluster's color, or the typicality ramp."""
        colors = theme.current()
        results = self._map_results
        fills = []
        for index in range(data.n_instances):
            key = self._map_key(data, index)
            fill = None
            if key is not None:
                if self.coloring_kind == "cluster":
                    fill = results.cluster_color(key)
                else:
                    rank = results.typicality_rank(key)
                    fill = ramp_color(rank) if np.isfinite(rank) else None
            fills.append([fill or colors.block_fill])
        return fills

    def _cleaned_for(self, data: WellData):
        """The Toolkit's verdicts on the view one well is drawn in, if the profiles are on hand."""
        if self._passes is None:
            return None
        return self._passes.cleaning_if_loaded(data.joined_view)

    def _bar_key(self, data: WellData, index: int):
        """The key the profile table knows one bar by; ``None`` for a stitched bar, which it does not."""
        if data.stitched_view:
            return None
        if data.joined_view:
            return (data.well, index)
        row = data.rows.iloc[index]
        return (int(row["fault_class"]), str(row["file"]))

    def _cleaned_fills(self, data: WellData) -> list[list[str]]:
        """The bars of one well tinted by the share of their live sensors the Toolkit's rule keeps."""
        colors = theme.current()
        cleaned = self._cleaned_for(data)
        fills = []
        for index in range(data.n_instances):
            share = cleaned.kept_share(self._bar_key(data, index)) if cleaned else float("nan")
            fills.append([ramp_color(share) if np.isfinite(share) else colors.block_fill])
        return fills

    def describe_cleaning_in_bar(self, data: WellData, index: int) -> str:
        """What the Toolkit's rule would discard in one bar, and why."""
        cleaned = self._cleaned_for(data)
        if data.stitched_view:
            return (
                "the Toolkit's rule judges one recording at a time, not a stitched well; untick "
                "'Stitch instances' to see its verdicts"
            )
        if cleaned is None:
            return "the Toolkit's rule has not been fitted yet"
        return cleaned.describe(self._bar_key(data, index))

    def describe_map_in_bar(self, data: WellData, index: int) -> str:
        """What the map said about one bar: its cluster, or its typicality."""
        results = self._map_results
        key = self._map_key(data, index)
        if results is None or key is None:
            view = "joined bars" if results is not None and results.joined else "instances"
            return f"the Instances map was drawn on the {view}, not on these bars"
        if self.coloring_kind == "cluster":
            if results.clusters is None:
                return "no clustering is on in the Instances map"
            label = results.clusters.get(key)
            if label is None:
                return "not on the Instances map"
            return (
                "left out of every cluster"
                if label < 0
                else f"cluster {label + 1} of the Instances map"
            )
        rank = results.typicality_rank(key)
        if not np.isfinite(rank):
            return "not on the Instances map"
        distance = results.typicality[key][0]
        return f"typicality {rank:.2f} in its class on the Instances map (distance {distance:.2f} to the medoid)"

    def _coloring_of(self, data: WellData) -> tuple[list[list[str]] | None, list[int]]:
        """What fills the bars of one well and which marks they wear, under the current choice.

        In the fault coloring a bar is marked when any sensor of any instance
        behind it reads outside its plausible range (top-right) or any of its
        pressures reads out of order (bottom-right, once the profiles are on
        hand); tinted by one sensor, it is marked for that sensor alone, the
        bar being about that sensor.
        Tinted by the measurements of a sensor, the ramp is the share of the
        sensor's live samples that were measured rather than filled in.
        """
        availability = self._availability
        if availability is None:
            return None, [0] * data.n_instances
        sensor = self.sensor_coloring
        if sensor is None:
            marks = []
            for index in range(data.n_instances):
                rows = bar_rows(availability, data, index)
                marks.append(
                    (IMPLAUSIBLE_MARK if availability.implausible_any(rows) else 0)
                    | (ORDER_MARK if availability.order_any(rows) else 0)
                )
            if self.coloring_kind in MAP_KINDS and self._map_results is not None:
                return self._map_fills(data), marks
            if self.coloring_kind == "cleaned" and self._cleaned_for(data) is not None:
                return self._cleaned_fills(data), marks
            if self.coloring_kind == "model" and self._model_results is not None:
                return self._model_fills(data), marks
            return None, marks
        colors = theme.current()
        column = availability.sensors.index(sensor)
        measured = self.coloring_kind == "measured" and availability.measured
        descriptor = self.coloring_kind == "descriptor"
        fills, marks = [], []
        for index in range(data.n_instances):
            rows = bar_rows(availability, data, index)
            shares, flagged = availability.shares_of(rows, column)
            if descriptor:
                rank = self._descriptor_ranks.get((data.well, index), float("nan"))
                fills.append([ramp_color(rank) if np.isfinite(rank) else colors.block_fill])
            elif shares[LIVE] > 0:
                strength = shares[LIVE]
                if measured:
                    share, _spacing = availability.measured_of(rows, column)
                    strength = share if np.isfinite(share) else 0.0
                fills.append([ramp_color(strength)])
            elif shares[FROZEN] > 0:
                fills.append([colors.frozen])
            else:
                fills.append([colors.block_fill])
            marks.append(
                (IMPLAUSIBLE_MARK if flagged else 0)
                | (ORDER_MARK if availability.order_any(rows, column) else 0)
            )
        return fills, marks

    def _ensure_cleaning(self) -> bool:
        """Have the Toolkit's verdicts for both views on hand; ``False`` if the pass is declined."""
        if self._passes is None:
            return False
        for joined in (False, True):
            if self._passes.cleaning(joined, parent=self.window()) is None:
                return False
        return True

    def _recolor(self, *args) -> None:
        """Fill the bars again under the choice of the Bar color box, without rebuilding the grid."""
        kind = self.coloring_kind
        declined = (kind in ("measured", "descriptor") and not self._ensure_profiles()) or (
            kind == "cleaned" and not self._ensure_cleaning()
        )
        if declined:
            # The pass was declined: back to the coloring that needs none.
            self._coloring.blockSignals(True)
            self._coloring.setCurrentIndex(0)
            self._coloring.blockSignals(False)
        if self.coloring_kind == "descriptor":
            self._rank_descriptors()
        else:
            self._descriptor_values, self._descriptor_ranks = {}, {}
        for plot in self._plots.values():
            plot.set_coloring(*self._coloring_of(plot.data))
        for cell in self._cells.values():
            cell.title.setText(cell.plot.title_html(self._title_extra(cell.plot.data)))
        self._show_key()
        self.status.emit(HINT)

    def _show_key(self) -> None:
        """Show the key that names the bars' fills: the faults', the sensor's, or the map's."""
        sensor = self.sensor_coloring
        kind = self.coloring_kind
        self._sensor_action.setVisible(kind in SENSOR_KINDS)
        for action in self._descriptor_actions:
            action.setVisible(kind == "descriptor")
        self._legend.setVisible(kind == "fault")
        # The map's clusters have no ramp: the map itself is their key, and
        # hovering a bar names its cluster.
        self._state_key.setVisible(sensor is not None or kind in ("typicality", "cleaned", "model"))
        self._state_key.set_visible(
            "order", self._availability is not None and self._availability.out_of_order is not None
        )
        if sensor is not None and kind == "descriptor":
            choice = self.descriptor_choice
            where = (
                "on the measurements" if self.descriptor_measured else "on the interpolated grid"
            )
            caveat = f", {GRID_CAVEAT}" if choice.inflated and not self.descriptor_measured else ""
            self._state_key.set_text(
                "ramp",
                f"{sensor}: {choice.name.lower()} {where}, ranked among the bars on show from "
                f"the smallest to the largest{caveat}",
            )
        elif sensor is not None:
            self._state_key.set_text(
                "ramp",
                f"{sensor}: share of its live samples that are measurements, from a few to all"
                if kind == "measured"
                else f"{sensor}: share of samples live, from a few to all",
            )
        elif kind == "typicality":
            self._state_key.set_text(
                "ramp",
                "typicality on the Instances map, from the farthest instance of its class to "
                "the medoid",
            )
        elif kind == "cleaned":
            self._state_key.set_text(
                "ramp",
                "share of the bar's live sensors the Toolkit's CleanSignals keeps, from none to "
                "all (defaults: 3 IQR, dropped when missing in 60 %)",
            )
        elif kind == "model":
            name = self._model_results.name if self._model_results else "the model"
            self._state_key.set_text(
                "ramp",
                f"share of the compared time {name} agrees with the labels, from none to all; "
                "empty where it scored nothing",
            )

    # -- appearance

    def _restyle(self) -> None:
        """Take the colors of the theme now in force, for the chrome this page owns."""
        self._empty.setStyleSheet(f"color: {theme.current().faint}; padding: 40px;")

    def apply_theme(self) -> None:
        """Take the colors of the theme now in force; the grid itself is rebuilt by ``set_catalogue``."""
        self._restyle()
        self._legend.apply_theme()
        self._state_key.apply_theme()

    # -- behaviour

    def _selected_wells(self) -> list[WellData]:
        wells = self._shown_wells()
        if self._filter.currentIndex() == 1:
            wells = [well for well in wells if well.n_overlapping > 0]
        if self._fault_filter is not None:
            wells = [well for well in wells if self._fault_filter in well.fault_classes()]
        return sorted(wells, key=SORT_KEYS[self._sort.currentText()])

    def _relayout(self, *args, keep_scroll: bool = False) -> None:
        for cell in self._cells.values():
            self._grid.removeWidget(cell)
            cell.hide()
        columns = self._columns.value()
        selected = self._selected_wells()
        for i, well in enumerate(selected):
            cell = self._cells[well.well]
            self._grid.addWidget(cell, i // columns, i % columns)
            cell.show()
        for column in range(4):
            self._grid.setColumnStretch(column, 1 if column < columns else 0)
        # A stretch row below the cells keeps a short grid at the top instead of spread out.
        rows = (len(selected) + columns - 1) // columns
        for row in range(self._grid.rowCount()):
            self._grid.setRowStretch(row, 0)
        self._grid.setRowStretch(rows, 1)
        self._scroll.setVisible(bool(selected))
        self._empty.setVisible(not selected)
        if not keep_scroll:
            # A new set of wells, or a new order for them, is a new page: it
            # starts at the top. What only redraws the same wells says so.
            self._scroll.verticalScrollBar().setValue(0)

    # -- keeping the reader's place

    def _scroll_anchor(self) -> tuple[int, float] | None:
        """The well at the top of the viewport, and how far into its cell the view has scrolled.

        A pixel offset on its own does not survive a rebuild: joining leaves a
        well fewer stack levels, so its cell is shorter, and an offset measured
        against the taller one lands past the end of it, on a well further
        down. The distance is therefore kept as a share of the cell, which
        means the same place whatever height it comes back at.
        """
        tops = sorted((cell.y(), well) for well, cell in self._cells.items() if not cell.isHidden())
        if not tops:
            return None
        y = self._scroll.verticalScrollBar().value()
        top, well = tops[0]
        for other_top, other_well in tops:
            if other_top > y:
                break
            top, well = other_top, other_well
        return well, (y - top) / max(self._cells[well].height(), 1)

    def _restore_scroll(self, anchor: tuple[int, float] | None) -> None:
        """Bring the anchored well back to the top of the viewport.

        The cells are laid out at once so their positions can be read, but the
        scroll range only catches up when Qt gets to the layout request the
        rebuild posted, and a value beyond a stale range would be clamped away;
        hence the second, exact attempt on the next turn of the event loop.
        """
        if anchor is None:
            return
        well, share = anchor
        cell = self._cells.get(well)
        if cell is None or cell.isHidden():
            return
        self._grid.activate()
        bar = self._scroll.verticalScrollBar()
        wanted = max(0, round(cell.y() + share * cell.height()))
        bar.setValue(min(wanted, bar.maximum()))
        QTimer.singleShot(0, lambda: bar.setValue(min(wanted, bar.maximum())))

    def toggle_fault_filter(self, fault_class: int | None) -> None:
        """Show only the wells that recorded ``fault_class``; the same fault again clears it."""
        self._fault_filter = None if fault_class == self._fault_filter else fault_class
        self._legend.set_selected_fault(self._fault_filter)
        if self._fault_filter is not None:
            name = self.info.fault_name(self._fault_filter)
            wells = sum(1 for well in self.wells if self._fault_filter in well.fault_classes())
            self._fault_button.setText(f"✕  {name}")
            self._fault_button.setToolTip(
                f"Showing the {wells} wells that recorded {name}. Click to show every well again."
            )
        self._fault_action.setVisible(self._fault_filter is not None)
        self._relayout()

    def _set_compressed(self, compressed: bool) -> None:
        for plot in self._plots.values():
            plot.set_compressed(compressed)

    def reset_views(self) -> None:
        for plot in self._plots.values():
            plot._auto_view = True
            plot.reset_view()

    def _on_hover(self, plot: WellTimelinePlot, index: int) -> None:
        """Describe the instance under the pointer and key its color in the legend."""
        if index < 0:
            self.status.emit(HINT)
            self._legend.highlight(set())
            return
        text = describe_instance(plot.data, index, self.info, self._availability)
        sensor = self.sensor_coloring
        if sensor is not None and self.coloring_kind == "descriptor":
            text += " | " + self.describe_descriptor_in_bar(plot.data, index)
        elif sensor is not None:
            text += " | " + describe_sensor_in_bar(
                self._availability, plot.data, index, sensor, self.coloring_kind == "measured"
            )
        elif self.coloring_kind in MAP_KINDS:
            text += " | " + self.describe_map_in_bar(plot.data, index)
        elif self.coloring_kind == "cleaned":
            text += " | " + self.describe_cleaning_in_bar(plot.data, index)
        elif self.coloring_kind == "model":
            text += " | " + self.describe_model_in_bar(plot.data, index)
        self.status.emit(text)
        data = plot.data
        self._legend.highlight(
            {
                legend_key(fault_class, reach)
                for i in (index, *data.partners[index])
                for fault_class, reach in data.colors[i]
            }
        )

    def _on_click(self, plot: WellTimelinePlot, index: int) -> None:
        self.open_requested.emit(plot.data, index)

    # -- what leaves the page

    def shown_files(self) -> list[tuple[int, str]]:
        """The instances of the wells on show, for the file list a Toolkit loader takes."""
        files = []
        for well in self._selected_wells():
            rows = well.origin.rows
            files += [
                (int(rows["fault_class"].iloc[i]), str(rows["file"].iloc[i]))
                for i in range(len(rows))
            ]
        return files

    def shown_source(self) -> str:
        """Where the file list came from, for its provenance."""
        parts = [f"the Timelines page | {self._filter.currentText()}"]
        if self._fault_filter is not None:
            parts.append(f"wells that recorded {self.info.fault_name(self._fault_filter)}")
        return " | ".join(parts)
