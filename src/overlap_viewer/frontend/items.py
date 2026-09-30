"""Custom pyqtgraph pieces shared by the two windows.

``SegmentsItem`` fills full-height colored spans along the time axis (recording
blocks, label shading, label bands), ``InstanceBarsItem`` draws the instance
bars of a well timeline with their hover highlight, ``TimeAxisItem`` labels an
axis laid out by a ``TimeMap`` with real dates, ``ScrollFriendlyViewBox`` keeps
the mouse wheel for scrolling unless Ctrl is held, and ``AnchoredText`` pins a
note to a corner of a plot.

Rectangles and text are painted in device pixels after resetting the painter
transform, as ``pyqtgraph.ScatterPlotItem`` does: the data axes are hours and
stack levels, so a pen or a font left in data coordinates would be stretched
beyond recognition, and a label can only be fitted inside its bar when both are
measured in pixels.
"""

from collections.abc import Iterable, Sequence

import numpy as np
import pandas as pd
import pyqtgraph as pg
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetricsF,
    QPainter,
    QPen,
    QPolygonF,
    QWheelEvent,
)
from PySide6.QtWidgets import QAbstractScrollArea, QApplication, QSizePolicy

from overlap_viewer.backend import theme
from overlap_viewer.backend.config import BAR_HEIGHT
from overlap_viewer.backend.palette import blend, text_color
from overlap_viewer.backend.timemap import TimeMap

# Formats tried, longest first, for the stamp written inside an instance bar.
STAMP_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%m-%d %H:%M", "%H:%M")

# Tick steps of a time axis, in hours, from one second to five years.
TICK_STEPS_HOURS = (
    1 / 3600,
    2 / 3600,
    5 / 3600,
    10 / 3600,
    15 / 3600,
    30 / 3600,
    1 / 60,
    2 / 60,
    5 / 60,
    10 / 60,
    15 / 60,
    30 / 60,
    1.0,
    2.0,
    3.0,
    6.0,
    12.0,
    24.0,
    48.0,
    72.0,
    168.0,
    336.0,
    720.0,
    2160.0,
    4320.0,
    8760.0,
    17520.0,
    43800.0,
)
# Steps of a month or more are aligned to calendar months rather than to multiples
# of a fixed number of hours, which would drift away from the first of the month.
MONTH_STEPS = (1, 2, 3, 6, 12, 24, 60, 120)
HOURS_PER_MONTH = 730.5

# Sentinel "spacings" handed to ``tickStrings`` to tell the levels apart.
MAJOR_SPACING = -1.0  # block starts
MONTH_SPACING = -2.0  # month-aligned ticks
YEAR_SPACING = -3.0  # year-aligned ticks

# The class band of an instance window carries this many pixels of text.
LABEL_FONT_PX = 10

# Two seams of a merged recording closer than this are drawn as one (see ``SeamsItem``).
MIN_SEAM_PX = 8

# The corner mark of a reading outside the plausible range: a small triangle in
# the warning color, on a timeline bar and on a cell of the availability page.
# Pressures out of order along their line take the same triangle in the
# bottom-right corner. A bar's or a cell's marks are these flags or'ed together
# (a plain ``True`` is the implausible mark alone).
MARK_PX = 6
IMPLAUSIBLE_MARK = 1
ORDER_MARK = 2


def draw_mark(p: QPainter, right: float, top: float, color: QColor) -> None:
    """Paint the mark of an implausible reading into the top-right corner ending at ``right``, ``top``."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    p.drawPolygon(
        QPolygonF(
            [QPointF(right, top), QPointF(right - MARK_PX, top), QPointF(right, top + MARK_PX)]
        )
    )
    p.restore()


def draw_order_mark(p: QPainter, right: float, bottom: float, color: QColor) -> None:
    """Paint the mark of pressures out of order into the bottom-right corner ending at ``right``, ``bottom``."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    p.drawPolygon(
        QPolygonF(
            [
                QPointF(right, bottom),
                QPointF(right - MARK_PX, bottom),
                QPointF(right, bottom - MARK_PX),
            ]
        )
    )
    p.restore()


def draw_marks(p: QPainter, rect, marks: int, color: QColor) -> None:
    """Paint the corner marks ``marks`` flags ask for on ``rect``."""
    marks = int(marks)
    if marks & IMPLAUSIBLE_MARK:
        draw_mark(p, rect.right() + 1, rect.top(), color)
    if marks & ORDER_MARK:
        draw_order_mark(p, rect.right() + 1, rect.bottom() + 1, color)


def restyle_axes(plot_item: pg.PlotItem) -> None:
    """Take the theme now in force on the axes of a plot built under the other one.

    pyqtgraph copies the foreground color into an axis's pens when the axis is
    built, so a plot that outlives a theme switch goes on drawing its axis
    lines, its ticks, its tick labels and its grid in the color of the theme it
    was built under, which over the new background is very nearly the
    background, and the grid appears to vanish. Most pages throw their plots
    away and build them again whenever the catalogue is laid out, and need none
    of this; the pages that keep one plot for their whole life (the Instances
    map and the Dispersions cloud) call this from ``apply_theme``. The tick pen
    is left alone: unset, it follows the axis pen.
    """
    foreground = theme.current().plot_foreground
    for name in ("left", "bottom", "right", "top"):
        axis = plot_item.getAxis(name)
        axis.setPen(foreground)
        axis.setTextPen(foreground)


class ScrollFriendlyViewBox(pg.ViewBox):
    """A ViewBox that zooms on Ctrl + wheel only, leaving the plain wheel to scroll.

    Both windows lay their plots in a scroll area; a wheel that zoomed would
    hijack scrolling as soon as the pointer crossed a plot.
    """

    def wheelEvent(self, ev, axis=None):
        if ev.modifiers() & Qt.KeyboardModifier.ControlModifier:
            super().wheelEvent(ev, axis)
        else:
            ev.ignore()


class WheelToParent:
    """Widget mixin handing a plain wheel to the scroll area that holds the plots.

    Declining the event in the view box is not enough: pyqtgraph's
    ``GraphicsView`` accepts every wheel event whether or not the scene used
    it, so the scroll area never saw one and the page stopped scrolling as soon
    as the pointer crossed a plot, over an axis, a title or a margin as much
    as over the plotting area, since those belong to no view box at all.
    Declining alone is not enough either: a scroll area is not the parent
    widget of the plots but their grandparent through its viewport, and Qt only
    walks that chain for events it delivered itself. The event is therefore
    re-sent to the viewport outright. Ctrl + wheel still reaches the plot,
    where it zooms.
    """

    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            super().wheelEvent(event)
            return
        event.ignore()
        area = self._scroll_area()
        if area is None:
            return
        viewport = area.viewport()
        forwarded = QWheelEvent(
            QPointF(viewport.mapFromGlobal(event.globalPosition().toPoint())),
            event.globalPosition(),
            event.pixelDelta(),
            event.angleDelta(),
            event.buttons(),
            event.modifiers(),
            event.phase(),
            event.inverted(),
            event.source(),
        )
        QApplication.sendEvent(viewport, forwarded)
        if forwarded.isAccepted():
            event.accept()

    def _scroll_area(self):
        """The scroll area this widget sits in, if any; never the widget itself.

        A plot widget is a scroll area of its own (every ``QGraphicsView`` is),
        so the search starts at the parent.
        """
        widget = self.parentWidget()
        while widget is not None:
            if isinstance(widget, QAbstractScrollArea):
                return widget
            widget = widget.parentWidget()
        return None


def _device_font(pixel_size: int) -> QFont:
    font = QFont()
    font.setPixelSize(pixel_size)
    return font


def hatch_brush() -> QBrush:
    """The texture drawn over a stretch nothing is known about, in the theme in force.

    Shared with the help window, so that the swatch it shows for *Unknown* is
    the very texture the bands carry.
    """
    return QBrush(QColor(theme.current().hatch), Qt.BrushStyle.FDiagPattern)


class SegmentsItem(pg.GraphicsObject):
    """Full-height colored spans along x, with optional labels centered inside.

    The spans stretch over whatever the view's y range is, like
    ``pyqtgraph.LinearRegionItem`` does, and a label is drawn only when it fits
    inside its span at the current zoom. The item is excluded from auto-range.
    Spans can also be hatched, which is how the unlabeled stretches are told
    apart from the grey of a fault that happens to be grey too: a texture reads
    as "no information here" where one more shade of grey would just read as
    one more class.
    """

    def __init__(
        self, z: float = -10.0, label_px: int = LABEL_FONT_PX, hatch: QBrush | None = None
    ):
        super().__init__()
        self.setZValue(z)
        # Taken when the item is built, not when it is painted, like every
        # color it draws: a window can keep a theme of its own, in force only
        # while that window builds its plots. Another texture than the
        # unlabeled one can be given, for a stretch that means something else
        # (the zero padding of a window).
        self._hatch = hatch if hatch is not None else hatch_brush()
        self._label_px = label_px
        self._x0 = np.empty(0)
        self._x1 = np.empty(0)
        self._colors: list[QColor] = []
        self._labels: list[str] = []
        self._label_colors: list[QColor] = []
        self._hatched: list[bool] = []

    def set_segments(
        self,
        x0,
        x1,
        colors: Sequence[str],
        labels: Sequence[str] | None = None,
        label_colors: Sequence[str] | None = None,
        hatched: Sequence[bool] | None = None,
    ) -> None:
        self._x0 = np.asarray(x0, dtype=float)
        self._x1 = np.asarray(x1, dtype=float)
        self._colors = [QColor(c) for c in colors]
        self._labels = list(labels) if labels is not None else []
        self._hatched = list(hatched) if hatched is not None else []
        if label_colors is not None:
            self._label_colors = [QColor(c) for c in label_colors]
        else:
            self._label_colors = [QColor(text_color(c)) for c in colors]
        self.prepareGeometryChange()
        self.update()

    def dataBounds(self, ax, frac=1.0, orthoRange=None):
        return None

    def pixelPadding(self):
        return 0

    def _view_y(self) -> tuple[float, float]:
        vb = self.getViewBox()
        if vb is None or not hasattr(vb, "viewRange"):
            return 0.0, 1.0
        ymin, ymax = vb.viewRange()[1]
        return float(ymin), float(ymax)

    def boundingRect(self):
        if len(self._x0) == 0:
            return QRectF()
        ymin, ymax = self._view_y()
        return QRectF(QPointF(self._x0.min(), ymin), QPointF(self._x1.max(), ymax)).normalized()

    def viewRangeChanged(self, *args):
        self.prepareGeometryChange()
        self.update()

    def paint(self, p, option, widget=None):
        if len(self._x0) == 0:
            return
        ymin, ymax = self._view_y()
        p.setPen(Qt.PenStyle.NoPen)
        for x0, x1, color in zip(self._x0, self._x1, self._colors):
            p.setBrush(color)
            p.drawRect(QRectF(x0, ymin, x1 - x0, ymax - ymin))
        if not self._labels and not any(self._hatched):
            return

        # Hatch and text are drawn in device pixels: a pattern brush left in
        # data coordinates would be stretched by the hours-wide x axis into
        # stripes of unrecognizable width.
        transform = p.transform()
        p.save()
        p.resetTransform()

        def device_rect(x0: float, x1: float) -> QRectF:
            return QRectF(
                transform.map(QPointF(x0, ymin)), transform.map(QPointF(x1, ymax))
            ).normalized()

        if any(self._hatched):
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(self._hatch)
            for x0, x1, hatched in zip(self._x0, self._x1, self._hatched):
                if hatched:
                    p.drawRect(device_rect(x0, x1))

        font = _device_font(self._label_px)
        p.setFont(font)
        metrics = QFontMetricsF(font)
        for x0, x1, text, color in zip(self._x0, self._x1, self._labels, self._label_colors):
            if not text:
                continue
            rect = device_rect(x0, x1)
            if metrics.horizontalAdvance(text) + 6 <= rect.width():
                p.setPen(color)
                p.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
        p.restore()


class SeamsItem(pg.GraphicsObject):
    """Dashed verticals where a merged recording passes from one instance to the next.

    A merged block is drawn as the single continuous recording its instances
    were cut from, so nothing else says where one window ended and the next
    began, and that is worth seeing, since a seam is where the labels of two
    windows were reconciled.

    Drawn in device pixels, and thinned: a seam that would land within
    ``MIN_SEAM_PX`` of the one before it is left out, so a recording stitched
    from seventy windows still shows a readable label band when it is zoomed
    out, and every seam appears as it is zoomed in. The time axis of this
    module drops colliding tick labels for the same reason.

    ``stitch`` draws the stitches of a stitched well instead: solid and in the
    muted text color, where the time axis jumps over a silence from one
    recording to the next, so a jump is never taken for a seam.
    """

    def __init__(self, z: float = 20.0, stitch: bool = False):
        super().__init__()
        self.setZValue(z)
        self._x = np.empty(0)
        self._stitch = stitch
        # Taken at build time: see ``SegmentsItem``.
        self._color = QColor(theme.current().muted if stitch else theme.current().gap_line)

    def set_seams(self, x: Sequence[float]) -> None:
        self._x = np.sort(np.asarray(x, dtype=float))
        self.prepareGeometryChange()
        self.update()

    def dataBounds(self, ax, frac=1.0, orthoRange=None):
        return None

    def pixelPadding(self):
        return 0

    def _view_y(self) -> tuple[float, float]:
        vb = self.getViewBox()
        if vb is None or not hasattr(vb, "viewRange"):
            return 0.0, 1.0
        ymin, ymax = vb.viewRange()[1]
        return float(ymin), float(ymax)

    def boundingRect(self):
        if len(self._x) == 0:
            return QRectF()
        ymin, ymax = self._view_y()
        return QRectF(QPointF(self._x.min(), ymin), QPointF(self._x.max(), ymax)).normalized()

    def viewRangeChanged(self, *args):
        self.prepareGeometryChange()
        self.update()

    def paint(self, p, option, widget=None):
        if len(self._x) == 0:
            return
        ymin, ymax = self._view_y()
        transform = p.transform()
        p.save()
        p.resetTransform()
        if self._stitch:
            p.setPen(QPen(self._color, 1.5, Qt.PenStyle.SolidLine))
        else:
            p.setPen(QPen(self._color, 1.0, Qt.PenStyle.DashLine))
        top = transform.map(QPointF(0.0, ymin)).y()
        bottom = transform.map(QPointF(0.0, ymax)).y()
        drawn = None
        for x in self._x:
            px = transform.map(QPointF(float(x), ymin)).x()
            if drawn is not None and abs(px - drawn) < MIN_SEAM_PX:
                continue
            drawn = px
            p.drawLine(QPointF(px, top), QPointF(px, bottom))
        p.restore()


class InstanceBarsItem(pg.GraphicsObject):
    """The instance bars of one well timeline, one per instance, on their stack level.

    A bar spans the instance in time on its lane, filled with its fault color
    tinted by reach and outlined with the full hue, and carries the timestamp
    of its filename in the longest format that fits. A bar that stands for
    several instances joined into one carries every color they had, as
    stripes from top to bottom, and a suffix after its timestamp. A bar with a
    reading no instrument could have produced wears the mark of it in its
    corner. While one bar is hovered it gets a heavy outline, the bars it
    overlaps a lighter one and, over the stretch they share, a hatch; every
    other bar fades.
    """

    def __init__(self, z: float = 5.0, label_px: int = 9):
        super().__init__()
        self.setZValue(z)
        self._label_px = label_px
        self._x0 = np.empty(0)
        self._x1 = np.empty(0)
        self._lanes = np.empty(0)
        self._fills: list[list[str]] = []
        self._edges: list[str] = []
        self._stamps: list[pd.Timestamp] = []
        self._suffixes: list[str] = []
        self._marks: list[int] = []
        self._hover = -1
        self._partners: set[int] = set()
        self._hatches: list[tuple[float, float, float]] = []

    def set_bars(
        self,
        x0,
        x1,
        lanes,
        fills: Sequence[str | Sequence[str]],
        edges: Sequence[str],
        stamps: Iterable[pd.Timestamp],
        suffixes: Sequence[str] | None = None,
        marks: Sequence[int] | None = None,
    ) -> None:
        """Place the bars; a bar's fill is one color or the list of colors it is striped with.

        ``marks`` are the corner marks of each bar, ``IMPLAUSIBLE_MARK`` and
        ``ORDER_MARK`` or'ed together.
        """
        self._x0 = np.asarray(x0, dtype=float)
        self._x1 = np.asarray(x1, dtype=float)
        self._lanes = np.asarray(lanes, dtype=float)
        self._fills = [[fill] if isinstance(fill, str) else list(fill) for fill in fills]
        self._edges = list(edges)
        self._stamps = [pd.Timestamp(s) for s in stamps]
        self._suffixes = list(suffixes) if suffixes is not None else [""] * len(self._fills)
        self._marks = [int(m) for m in marks] if marks is not None else [0] * len(self._fills)
        self.prepareGeometryChange()
        self.update()

    def set_positions(self, x0, x1) -> None:
        """Move the bars, e.g. when the time axis switches between compressed and calendar."""
        self._x0 = np.asarray(x0, dtype=float)
        self._x1 = np.asarray(x1, dtype=float)
        self.prepareGeometryChange()
        self.update()

    def set_highlight(
        self, hovered: int, partners: Iterable[int], hatches: Sequence[tuple[float, float, float]]
    ) -> None:
        """Highlight ``hovered`` and its ``partners``; hatch ``(x0, x1, lane)`` stretches."""
        self._hover = int(hovered)
        self._partners = {int(j) for j in partners}
        self._hatches = list(hatches)
        self.update()

    def clear_highlight(self) -> None:
        if self._hover != -1 or self._hatches:
            self._hover = -1
            self._partners = set()
            self._hatches = []
            self.update()

    def boundingRect(self):
        if len(self._x0) == 0:
            return QRectF()
        margin = 0.01 * max(float(self._x1.max() - self._x0.min()), 1e-6)
        return QRectF(
            QPointF(self._x0.min() - margin, self._lanes.min() - 0.5),
            QPointF(self._x1.max() + margin, self._lanes.max() + 0.5),
        ).normalized()

    def paint(self, p, option, widget=None):
        if len(self._x0) == 0:
            return
        transform = p.transform()
        p.save()
        p.resetTransform()
        font = _device_font(self._label_px)
        p.setFont(font)
        metrics = QFontMetricsF(font)
        half = BAR_HEIGHT / 2
        highlighting = self._hover >= 0
        colors = theme.current()

        for i in range(len(self._x0)):
            rect = QRectF(
                transform.map(QPointF(self._x0[i], self._lanes[i] - half)),
                transform.map(QPointF(self._x1[i], self._lanes[i] + half)),
            ).normalized()
            if rect.width() < 2.0:  # keep a very short instance visible
                rect = QRectF(rect.center().x() - 1.0, rect.top(), 2.0, rect.height())

            fills = [QColor(fill) for fill in self._fills[i]]
            edge, width = QColor(self._edges[i]), 1.0
            faded = False
            if highlighting:
                if i == self._hover:
                    edge, width = QColor(colors.outline), 2.5
                elif i in self._partners:
                    edge, width = QColor(colors.outline), 1.5
                else:
                    faded = True
                    for fill in fills:
                        fill.setAlphaF(0.22)
                    edge.setAlphaF(0.35)
            p.setPen(Qt.PenStyle.NoPen)
            if len(fills) == 1:
                p.setBrush(fills[0])
                p.drawRect(rect)
            else:
                # A joined bar shows every color its instances had, each stripe
                # the exact color of a legend entry, so the key still names them.
                stripe = rect.height() / len(fills)
                for k, fill in enumerate(fills):
                    p.setBrush(fill)
                    p.drawRect(QRectF(rect.left(), rect.top() + k * stripe, rect.width(), stripe))
            p.setPen(QPen(edge, width))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(rect)
            if self._marks[i] and rect.width() >= 2 * MARK_PX:
                mark = QColor(colors.warning)
                if faded:
                    mark.setAlphaF(0.35)
                if self._marks[i] & IMPLAUSIBLE_MARK:
                    draw_mark(p, rect.right(), rect.top(), mark)
                if self._marks[i] & ORDER_MARK:
                    draw_order_mark(p, rect.right(), rect.bottom(), mark)

            if rect.width() >= 28 and not faded:
                label_color = QColor(text_color(blend(self._fills[i])))
                for fmt in STAMP_FORMATS:
                    text = self._stamps[i].strftime(fmt) + self._suffixes[i]
                    if metrics.horizontalAdvance(text) + 6 <= rect.width():
                        p.setPen(label_color)
                        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
                        break

        if self._hatches:
            hatch = QColor(colors.overlap_hatch)
            hatch.setAlpha(80)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(hatch, Qt.BrushStyle.BDiagPattern))
            for hx0, hx1, lane in self._hatches:
                rect = QRectF(
                    transform.map(QPointF(hx0, lane - half)),
                    transform.map(QPointF(hx1, lane + half)),
                ).normalized()
                p.drawRect(rect)
        p.restore()


class TimeAxisItem(pg.AxisItem):
    """An axis in ``TimeMap`` hours labeled with the real dates.

    Two tick levels: the start of every recording block (long ticks, full
    dates) and, inside the blocks, round times at a step chosen from the zoom
    (short ticks, clock times or dates). Labels are placed only where they do
    not collide, so a well recorded in many short bursts keeps a readable axis;
    the dashed separators of the plot still mark every block.
    """

    def __init__(self, timemap: TimeMap | None = None, orientation: str = "bottom", **kwargs):
        super().__init__(orientation, **kwargs)
        self._timemap = timemap
        self._major_with_time = False
        self._overrides: dict[float, str] = {}  # tick position -> text replacing the level's format
        # Collisions are resolved here, so pyqtgraph's own crowding limit is relaxed.
        self.setStyle(textFillLimits=[(0, 0.95)])

    def set_timemap(self, timemap: TimeMap, major_with_time: bool = False) -> None:
        self._timemap = timemap
        self._major_with_time = major_with_time
        self.picture = None
        self.update()

    # -- geometry helpers

    def _metrics(self) -> QFontMetricsF:
        font = self.style.get("tickFont") or self.font()
        return QFontMetricsF(font)

    def _major_format(self) -> str:
        return "%Y-%m-%d %H:%M" if self._major_with_time else "%Y-%m-%d"

    def major_label_px(self) -> float:
        """Width in pixels of a block-start label, for callers padding their view."""
        sample = pd.Timestamp("2014-02-12 12:00").strftime(self._major_format())
        return self._metrics().horizontalAdvance(sample) + 10.0

    @staticmethod
    def _minor_text(stamp: pd.Timestamp, step_hours: float) -> str:
        if step_hours < 1 / 60:
            return stamp.strftime("%H:%M:%S")
        if step_hours < 24:
            if stamp.hour == 0 and stamp.minute == 0 and stamp.second == 0:
                return stamp.strftime("%m-%d")
            return stamp.strftime("%H:%M")
        return stamp.strftime("%m-%d")

    # -- pyqtgraph API

    def tickValues(self, minVal, maxVal, size):
        timemap = self._timemap
        if timemap is None or size <= 0 or maxVal <= minVal:
            return super().tickValues(minVal, maxVal, size)

        px_per_hour = size / (maxVal - minVal)
        metrics = self._metrics()
        occupied: list[tuple[float, float]] = []
        self._overrides = {}

        def place(x: float, text: str, out: list[float], override: str | None = None) -> bool:
            """Add a tick at ``x`` if its label fits inside the axis and collides with none placed."""
            px = (x - minVal) * px_per_hour
            half = 0.5 * metrics.horizontalAdvance(text) + 5.0
            if px - half < 0 or px + half > size:  # pyqtgraph drops labels crossing the edge
                return False
            if any(px - half < b and a < px + half for a, b in occupied):
                return False
            occupied.append((px - half, px + half))
            out.append(x)
            if override is not None:
                self._overrides[round(x, 9)] = override
            return True

        blocks = timemap.blocks
        linear = len(blocks) == 1
        majors: list[float] = []
        fmt = self._major_format()
        # Blocks whose start label could not be written (out of view, or too close to
        # the edge) pass the duty of stating the date on to their first inner label.
        dated: set[int] = set()
        for i, (x0, hours, start) in enumerate(zip(blocks["x0"], blocks["hours"], blocks["start"])):
            x0, hours = float(x0), float(hours)
            if minVal - 1e-9 <= x0 <= maxVal + 1e-9:
                if not place(x0, pd.Timestamp(start).strftime(fmt), majors):
                    majors.append(x0)  # a bare tick mark still shows where the block starts
                    self._overrides[round(x0, 9)] = ""
                    dated.add(i)
            elif x0 < minVal and (linear or x0 + hours > minVal):
                dated.add(i)

        min_px = 1.4 * metrics.horizontalAdvance("2014-02-12") + 10.0
        step = next(
            (s for s in TICK_STEPS_HOURS if s * px_per_hour >= min_px), TICK_STEPS_HOURS[-1]
        )
        months = 0
        if step >= 720:
            months = next(
                (m for m in MONTH_STEPS if m * HOURS_PER_MONTH * px_per_hour >= min_px),
                MONTH_STEPS[-1],
            )
        spacing = (YEAR_SPACING if months % 12 == 0 else MONTH_SPACING) if months else step
        if months:
            dated_fmt = "%Y" if months % 12 == 0 else "%Y-%m"
        else:
            dated_fmt = "%Y-%m-%d" if step >= 24 else "%Y-%m-%d %H:%M"

        minors: list[float] = []
        for i, (x0, hours, start) in enumerate(zip(blocks["x0"], blocks["hours"], blocks["start"])):
            x0, hours = float(x0), float(hours)
            lo, hi = max(float(minVal), x0), min(float(maxVal), x0 + hours)
            if linear:  # a linear axis extrapolates beyond its data
                lo, hi = float(minVal), float(maxVal)
            if hi < lo:
                continue
            start = pd.Timestamp(start)
            need_date = i in dated
            for stamp in self._ticks_from(start + pd.Timedelta(hours=lo - x0), step, months):
                x = x0 + (stamp - start) / pd.Timedelta(hours=1)
                if x > hi + 1e-9:
                    break
                if need_date:
                    text = stamp.strftime(dated_fmt)
                    if place(x, text, minors, override=text):
                        need_date = False
                    continue
                place(x, self._level_text(stamp, spacing), minors)
            if need_date:  # no round time inside the visible block: pin a date where it fits
                half = 0.5 * metrics.horizontalAdvance(start.strftime(dated_fmt)) + 5.0
                x = max(lo, float(minVal) + half / px_per_hour)
                if x <= hi:
                    stamp = start + pd.Timedelta(hours=x - x0)
                    text = stamp.strftime(dated_fmt)
                    place(x, text, minors, override=text)

        return [(MAJOR_SPACING, majors), (spacing, minors)]

    @staticmethod
    def _ticks_from(first: pd.Timestamp, step_hours: float, months: int):
        """Round times from ``first`` on: multiples of the step, or calendar months."""
        if months:
            index = first.year * 12 + first.month - 1
            if first.day > 1 or first.hour or first.minute or first.second:
                index += 1
            index = int(np.ceil(index / months)) * months
            for _ in range(600):
                yield pd.Timestamp(year=index // 12, month=index % 12 + 1, day=1)
                index += months
            return
        step_s = max(round(step_hours * 3600), 1)
        t = int(np.ceil(first.value / 10**9 / step_s)) * step_s
        for _ in range(600):
            yield pd.Timestamp(t, unit="s")
            t += step_s

    def _level_text(self, stamp: pd.Timestamp, spacing: float) -> str:
        if spacing == MAJOR_SPACING:
            return stamp.strftime(self._major_format())
        if spacing == YEAR_SPACING:
            return stamp.strftime("%Y")
        if spacing == MONTH_SPACING:
            return stamp.strftime("%Y-%m")
        return self._minor_text(stamp, float(spacing))

    def tickStrings(self, values, scale, spacing):
        timemap = self._timemap
        if timemap is None:
            return super().tickStrings(values, scale, spacing)
        strings = []
        for value in values:
            override = self._overrides.get(round(float(value), 9))
            if override is not None:
                strings.append(override)
                continue
            stamp = timemap.to_time(float(value))
            strings.append("" if stamp is None else self._level_text(stamp, float(spacing)))
        return strings


class HeaderLabel(pg.LabelItem):
    """A ``LabelItem`` that never widens its layout: a long text is clipped, not fitted.

    ``pyqtgraph.LabelItem`` sets its own minimum width to the width of its
    text, so a long line above a plot would stretch the whole layout past the
    viewport and cut every plot short on the right.
    """

    def updateMin(self):
        bounds = self.itemRect()
        self.setMinimumWidth(0)
        self.setMinimumHeight(bounds.height())
        self._sizeHint = {
            QSizePolicy.Policy.Minimum: (0, bounds.height()),
            QSizePolicy.Policy.Preferred: (0, bounds.height()),
            QSizePolicy.Policy.Maximum: (-1, -1),
            QSizePolicy.Policy.Expanding: (-1, -1),
            QSizePolicy.Policy.MinimumExpanding: (-1, -1),
        }
        self.updateGeometry()


class AnchoredText(pg.TextItem):
    """A text note pinned to a fixed fraction of the plot area, whatever the zoom.

    Parameters
    ----------
    html : str
        Rich text to show.
    frac : (float, float)
        Position inside the view, ``(1, 1)`` being the top-right corner.
    anchor : (float, float)
        Point of the text box placed there, in text-box fractions; values a
        little outside ``0..1`` inset the box from the edge.
    fill_alpha : int
        Opacity of the box, out of 255: at the default the trace stays faintly
        readable under the note; a note that sits over the trace for good, as
        the figures of an instance-window plot do, is given less.
    """

    def __init__(
        self,
        html: str,
        frac=(1.0, 1.0),
        anchor=(1.03, -0.25),
        boxed: bool = True,
        fill_alpha: int = 215,
    ):
        colors = theme.current()
        fill = QColor(colors.note_fill)
        fill.setAlpha(fill_alpha)
        super().__init__(
            html=html,
            anchor=anchor,
            fill=pg.mkBrush(fill) if boxed else None,
            border=pg.mkPen(colors.note_border, width=0.6) if boxed else None,
        )
        self._frac = frac
        self._vb = None
        self.setZValue(60)

    def attach(self, plot) -> None:
        plot.addItem(self, ignoreBounds=True)
        self._vb = plot.getViewBox()
        self._vb.sigRangeChanged.connect(self._reposition)
        self._reposition()

    def _reposition(self, *args) -> None:
        if self._vb is None:
            return
        (xmin, xmax), (ymin, ymax) = self._vb.viewRange()
        self.setPos(xmin + self._frac[0] * (xmax - xmin), ymin + self._frac[1] * (ymax - ymin))
