"""A matrix of cells, each a stacked bar of shares, with row labels, slanted column labels, hover and click.

The availability page draws its table with this widget: one row per group of
bars, one column per sensor, and in every cell the shares of the group that are
live, frozen and absent, side by side from the left. From afar a cell reads as
a heatmap (the fuller, the more available); up close it reads as exact
proportions, and the frozen part carries a flat line so that it cannot be taken
for the live part in a print or by an eye that does not tell the colors apart.
A reading outside the plausible range puts a small mark in the top-right corner
of its cell, the same mark the timeline bars wear; pressures read out of order
along their line put one in the bottom-right corner, and a valve that
contradicts the well state a red one in the top-left corner.

The cells take the width they are given: at least a floor, so that a matrix
wider than the window scrolls, and up to a ceiling, so that a wide window is
filled rather than left blank at the right. Everything is painted here rather
than built from widgets: forty wells by twenty-seven sensors is over a thousand
cells, and three hundred instances are eight thousand, which QPainter draws in
a few milliseconds and a grid of widgets would not. Only the rows inside the
exposed rectangle are painted.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from math import cos, radians, sin

import numpy as np
from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QImage,
    QLinearGradient,
    QPainter,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QToolTip, QWidget

from overlap_viewer.backend import theme
from overlap_viewer.backend.availability import FROZEN, LIVE
from overlap_viewer.backend.palette import tint
from overlap_viewer.frontend.items import (
    IMPLAUSIBLE_MARK,
    MARK_PX,
    ORDER_MARK,
    STATE_MARK,
    draw_marks,
)
from overlap_viewer.frontend.styling import TOOLTIP_FOREVER_MS, bounded_tooltip

CELL_MIN_W, CELL_MAX_W = (
    34,
    110,
)  # a cell is never narrower than the first, never wider than the second
CELL_H = 22
CELL_INSET = 1  # a cell is drawn this far inside its pitch, so two pixels separate neighbours
LABEL_ANGLE = 60.0  # degrees a column label is raised from the horizontal
SWATCH_PX = 10  # the square keying a row by a color, before its label
MAX_LABEL_PX = 260  # a row label wider than this is elided
PAD = 6

# A live share below this is still drawn at this strength, so that a sensor
# recorded in a few samples is told from one not recorded at all.
RAMP_FLOOR = 0.2

# What a swatch of the key can show: the three states of a cell, the filled
# part of a live cell, the mark, and the ramp of tints a timeline bar takes
# from the share of samples live.
SWATCH_KINDS = (
    "live",
    "filled",
    "frozen",
    "absent",
    "implausible",
    "order",
    "state",
    "cleaned",
    "ramp",
)
SWATCH_SIZE = (22, 14)
RAMP_SIZE = (64, 14)
# How much of the live color the filled part of a cell keeps: pale enough to
# read as "less", strong enough not to be taken for the ground.
FILLED_TINT = 0.4
# The slash of a sensor the Toolkit's rule would discard, in the bottom-left corner.
SLASH_PX = 6

KEY_LABELS = {
    "live": "live",
    "filled": "filled in between measurements",
    "frozen": "frozen (one constant reading)",
    "absent": "absent",
    "implausible": "a reading outside the plausible range",
    "order": "pressures out of order",
    "state": "a valve against the well state",
    "cleaned": "the Toolkit's CleanSignals would discard it",
    "ramp": "share of samples live, from a few to all",
}
KEY_TOOLTIPS = {
    "cleaned": (
        "In at least one instance of the row the 3W Toolkit's CleanSignals rule would set this "
        "sensor to missing: its mean or its spread there falls outside the quartiles of the "
        "dataset's by more than the IQR factor, or it never moves. Hover the cell for how many, "
        "and for the bound it failed."
    ),
    "live": "Samples carrying a reading that moves over the instance.",
    "filled": (
        "Live samples that were not measured: a straight line the historian drew between two "
        "measurements, or the last measurement carried forward until the next. They carry a "
        "reading that moves, but nothing was read there. The solid part of the live share is "
        "the measurements; this paler part is the rest."
    ),
    "frozen": (
        "Samples carrying a reading, but one single value from end to end: a dead or "
        "disconnected instrument, which a count of readings would pass off as available. A "
        "valve state that holds one position is a fact about the well, so the ESTADO variables "
        "are never frozen."
    ),
    "absent": (
        "Samples carrying no reading: the well does not have the sensor, or lost it. With a "
        "threshold set, also a sensor with too few readings to count as available."
    ),
    "implausible": (
        "At least one instance has a reading of this sensor that no instrument could have "
        "produced: a negative absolute pressure or flow rate, a temperature outside -50 to "
        "250 °C, a magnitude beyond 1e8. Hover for how many, and for the range."
    ),
    "order": (
        "At least one instance has this pressure read out of order with another of its line: "
        "downstream above upstream by more than 1 MPa, which the flow cannot do, so one of the "
        "two instruments is not to be believed. Hover for how many, and for the other "
        "pressure. Known once the profile pass has run (the first tick of 'Measured vs "
        "filled' runs it); it reads every sample."
    ),
    "state": (
        "At least one instance has this valve contradict the well state its experts labeled: "
        "Open while the valve of the production path reads closed or a crossover open, Shut-In "
        "while every valve of the path reads open, and so on, as the 3W 2.0.0 article defines "
        "the states. Either the label or the valve's tag is not to be believed. Hover for how "
        "many, and for the states. Known once the profile pass has run; it reads every sample."
    ),
    "ramp": (
        "The bar is tinted by the share of its samples in which the sensor is live: faint for a "
        "few, full for all. A sensor frozen throughout takes the frozen grey, one never recorded "
        "leaves the bar empty."
    ),
}


@dataclass(frozen=True)
class HeatmapRow:
    """One row of the matrix: its label, the color keying it, and whether it stands out."""

    label: str
    swatch: str | None = None  # a color drawn as a square before the label, e.g. the fault hue
    emphasized: bool = False  # a total row: bold, under a rule


def _span(share: float, width: int) -> int:
    """Pixels a share of a cell takes: none for nothing, at least one for anything."""
    if share <= 0:
        return 0
    return max(1, round(share * width))


def ramp_color(live_share: float) -> str:
    """The tint a timeline bar takes from the share of its samples in which a sensor is live."""
    strength = RAMP_FLOOR + (1.0 - RAMP_FLOOR) * min(max(float(live_share), 0.0), 1.0)
    return tint(theme.current().live, strength)


def filled_color() -> str:
    """The pale live color of the samples the historian filled in."""
    return tint(theme.current().live, FILLED_TINT)


def draw_slash(p: QPainter, left: float, bottom: float, color: QColor) -> None:
    """Paint the slash of a sensor the Toolkit's rule would discard, into the bottom-left corner."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setPen(QPen(color, 1.6))
    p.drawLine(QPointF(left + 1, bottom - 1), QPointF(left + 1 + SLASH_PX, bottom - 1 - SLASH_PX))
    p.restore()


def paint_cell(
    p: QPainter, rect: QRect, shares, mark: int, filled: float = 0.0, struck: bool = False
) -> None:
    """Fill ``rect`` with the live, frozen and absent shares, and the marks if there are any.

    ``mark`` is the corner marks, ``IMPLAUSIBLE_MARK``, ``ORDER_MARK`` and
    ``STATE_MARK`` or'ed together (``True`` is the first alone).

    ``filled`` is the share of the cell's samples that are live but were not
    measured; that much of the live span, at its right end, is drawn in the
    pale live color, so the solid part is the measurements. ``struck`` puts
    the slash of the Toolkit's rule in the bottom-left corner. Shared with the
    keys of the pages and with the help, so that a swatch shows exactly what a
    cell shows.
    """
    colors = theme.current()
    p.setPen(Qt.PenStyle.NoPen)
    p.fillRect(rect, QColor(colors.block_fill))
    width = rect.width()
    live = _span(float(shares[LIVE]), width)
    frozen = min(_span(float(shares[FROZEN]), width), width - live)
    if live:
        p.fillRect(QRect(rect.left(), rect.top(), live, rect.height()), QColor(colors.live))
        pale = min(_span(float(filled), width), live)
        if pale:
            p.fillRect(
                QRect(rect.left() + live - pale, rect.top(), pale, rect.height()),
                QColor(filled_color()),
            )
    if frozen:
        frozen_rect = QRect(rect.left() + live, rect.top(), frozen, rect.height())
        p.fillRect(frozen_rect, QColor(colors.frozen))
        # The flat line of a sensor that never moved.
        p.setPen(QPen(QColor(colors.muted), 1))
        y = frozen_rect.center().y()
        p.drawLine(frozen_rect.left(), y, frozen_rect.right(), y)
    if mark:
        draw_marks(p, rect, int(mark), QColor(colors.warning))
    if struck:
        draw_slash(p, rect.left(), rect.bottom() + 1, QColor(colors.text))


def swatch_image(kind: str, size: tuple[int, int] | None = None) -> QImage:
    """A swatch of one kind of cell, for the keys of the pages and for the help.

    ``live``, ``frozen`` and ``absent`` fill the whole swatch with that state;
    ``implausible`` is an empty cell wearing the mark; ``ramp`` runs the tints
    a timeline bar can take, from the floor to the full live color.
    """
    if kind not in SWATCH_KINDS:
        raise ValueError(f"unknown swatch {kind!r}; expected one of {SWATCH_KINDS}")
    size = size or (RAMP_SIZE if kind == "ramp" else SWATCH_SIZE)
    image = QImage(*size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    if kind == "ramp":
        gradient = QLinearGradient(0, 0, size[0], 0)
        gradient.setColorAt(0.0, QColor(ramp_color(0.0)))
        gradient.setColorAt(1.0, QColor(ramp_color(1.0)))
        painter.fillRect(image.rect(), gradient)
    else:
        shares = np.zeros(3)
        if kind in ("live", "filled"):
            shares[LIVE] = 1.0
        elif kind == "frozen":
            shares[FROZEN] = 1.0
        paint_cell(
            painter,
            image.rect(),
            shares,
            {"implausible": IMPLAUSIBLE_MARK, "order": ORDER_MARK, "state": STATE_MARK}.get(
                kind, 0
            ),
            1.0 if kind == "filled" else 0.0,
            kind == "cleaned",
        )
    painter.setPen(QPen(QColor(theme.current().border), 1))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRect(image.rect().adjusted(0, 0, -1, -1))
    painter.end()
    return image


class StateKey(QWidget):
    """The key of the cells, or of the bars: one swatch per kind, painted as the cells are."""

    def __init__(self, kinds=("live", "frozen", "absent", "implausible"), parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._chips: list[tuple[QLabel, str]] = []
        self._texts: dict[str, QLabel] = {}
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        for kind in kinds:
            chip = QLabel()
            chip.setToolTip(KEY_TOOLTIPS[kind])
            text = QLabel(KEY_LABELS[kind])
            text.setToolTip(KEY_TOOLTIPS[kind])
            entry = QHBoxLayout()
            entry.setContentsMargins(0, 0, 0, 0)
            entry.setSpacing(5)
            entry.addWidget(chip)
            entry.addWidget(text)
            layout.addLayout(entry)
            self._chips.append((chip, kind))
            self._texts[kind] = text
        self.apply_theme()

    def set_text(self, kind: str, text: str) -> None:
        """Reword one entry, e.g. to name the sensor a ramp is about."""
        self._texts[kind].setText(text)

    def set_visible(self, kind: str, shown: bool) -> None:
        """Show or withdraw one entry, e.g. the filled part while the split is off."""
        self._texts[kind].setVisible(shown)
        for chip, name in self._chips:
            if name == kind:
                chip.setVisible(shown)

    def apply_theme(self) -> None:
        """Paint the swatches again in the theme now in force."""
        for chip, kind in self._chips:
            chip.setPixmap(QPixmap.fromImage(swatch_image(kind)))


class ColorKey(QWidget):
    """A key of plain colors: one swatch and one text per entry, for a matrix of single fills."""

    def __init__(self, entries: Sequence[tuple[str, str]] = (), parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(14)
        self._chips: list[tuple[QLabel, str]] = []
        self.set_entries(entries)

    def set_entries(self, entries: Sequence[tuple[str, str]]) -> None:
        """Replace the entries: ``(color, text)`` pairs, a color being ``#rrggbb``."""
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.layout() is not None:
                while item.layout().count():
                    inner = item.layout().takeAt(0)
                    if inner.widget() is not None:
                        inner.widget().deleteLater()
        self._chips = []
        for color, text in entries:
            chip = QLabel()
            label = QLabel(text)
            entry = QHBoxLayout()
            entry.setContentsMargins(0, 0, 0, 0)
            entry.setSpacing(5)
            entry.addWidget(chip)
            entry.addWidget(label)
            self._layout.addLayout(entry)
            self._chips.append((chip, color))
        self.apply_theme()

    def apply_theme(self) -> None:
        border = theme.current().border
        for chip, color in self._chips:
            image = QImage(*SWATCH_SIZE, QImage.Format.Format_ARGB32)
            image.fill(QColor(color))
            painter = QPainter(image)
            painter.setPen(QPen(QColor(border), 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(image.rect().adjusted(0, 0, -1, -1))
            painter.end()
            chip.setPixmap(QPixmap.fromImage(image))


class HeatmapWidget(QWidget):
    """The matrix itself: cells, labels, and what the pointer is over.

    Signals
    -------
    hovered(int, int)
        Row and column under the pointer. Over a row label the column is
        ``-1``, over a column label the row is; both are ``-1`` over nothing.
    clicked(int, int)
        The same pair, for a left click on a cell or a label.
    """

    hovered = Signal(int, int)
    clicked = Signal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        self._rows: list[HeatmapRow] = []
        self._columns: list[str] = []
        self._shares = np.zeros((0, 0, 3))
        self._marks = np.zeros((0, 0), dtype=int)
        self._filled: np.ndarray | None = None
        self._struck: np.ndarray | None = None
        self._muted_columns: set[int] = set()
        self._fills: list[list[str | None]] | None = None  # single-color cells, when set
        self._tooltip: Callable[[int, int], str] | None = None
        self._hover = (-1, -1)
        self._left = 0  # x at which the cells start; the row labels sit before it
        self._top = 0  # y at which the cells start; the column labels sit above it
        self._right = 0  # room after the last column for the label leaning past it
        self._cell_w = CELL_MIN_W
        self._measure()

    # -- contents

    def set_matrix(
        self, rows, columns, shares, marks, filled=None, struck=None, muted_columns=()
    ) -> None:
        """Show ``rows`` by ``columns``; ``shares`` is ``(rows, columns, 3)``, ``marks`` ``(rows, columns)``.

        ``marks`` are corner-mark flags (``items.IMPLAUSIBLE_MARK``,
        ``items.ORDER_MARK``, ``items.STATE_MARK``), or booleans for the first alone.

        ``filled``, ``(rows, columns)`` when given, is the share of each cell
        that is live but was not measured, drawn as the pale end of the live
        span; ``struck``, ``(rows, columns)`` when given, puts the slash of
        the Toolkit's rule on a cell; ``muted_columns`` are the positions of
        the columns whose label is drawn muted, the sensors that rule drops.
        """
        self._rows = list(rows)
        self._columns = list(columns)
        shape = (len(self._rows), len(self._columns))
        self._shares = np.asarray(shares, dtype=float).reshape(*shape, 3)
        self._marks = np.asarray(marks, dtype=int).reshape(shape)
        self._filled = None if filled is None else np.asarray(filled, dtype=float).reshape(shape)
        self._struck = None if struck is None else np.asarray(struck, dtype=bool).reshape(shape)
        self._muted_columns = set(muted_columns)
        self._fills = None
        self._hover = (-1, -1)
        self._measure()
        self.update()

    def set_fills(self, rows, columns, fills, muted_columns=()) -> None:
        """Show ``rows`` by ``columns`` as cells of one color each: ``fills[i][j]`` is ``#rrggbb`` or ``None`` for the ground.

        What a matrix of coefficients is drawn as, where a cell is a value
        and not a split of shares.
        """
        self._rows = list(rows)
        self._columns = list(columns)
        shape = (len(self._rows), len(self._columns))
        self._shares = np.zeros((*shape, 3))
        self._marks = np.zeros(shape, dtype=int)
        self._filled = None
        self._struck = None
        self._muted_columns = set(muted_columns)
        self._fills = [list(row) for row in fills]
        self._hover = (-1, -1)
        self._measure()
        self.update()

    @property
    def rows(self) -> list[HeatmapRow]:
        return self._rows

    @property
    def columns(self) -> list[str]:
        return self._columns

    def set_tooltip_provider(self, provider: Callable[[int, int], str] | None) -> None:
        """Take what turns a ``(row, column)`` into the rich text of its tooltip.

        A printed availability map writes the figure inside every cell; a cell
        of this one is 34 pixels wide and could not hold it, so the figure is
        shown where the pointer is instead. The status bar says the same and
        more, but it is at the other end of the window, and a reader comparing
        two cells should not have to look away from them.
        """
        self._tooltip = provider

    def event(self, event) -> bool:
        if event.type() == QEvent.Type.ToolTip and self._tooltip is not None:
            row, column = self.hit(event.pos())
            text = self._tooltip(row, column) if (row >= 0 or column >= 0) else ""
            if text:
                QToolTip.showText(
                    event.globalPos(), bounded_tooltip(text), self, QRect(), TOOLTIP_FOREVER_MS
                )
            else:
                QToolTip.hideText()
                event.ignore()
            return True
        return super().event(event)

    def _fonts(self) -> tuple[QFont, QFont]:
        normal = QFont(self.font())
        bold = QFont(normal)
        bold.setBold(True)
        return normal, bold

    def _measure(self) -> None:
        """Size the widget from its labels: the widest row label, the longest column label.

        The result is a minimum: the scroll area hands the widget the width of
        its viewport when that is more, and ``_fit`` spreads the cells over it.
        """
        _, bold = self._fonts()
        metrics = QFontMetrics(bold)  # labels are measured bold, so emphasis cannot widen them
        widest = max((metrics.horizontalAdvance(row.label) for row in self._rows), default=0)
        self._left = PAD + SWATCH_PX + 6 + min(widest, MAX_LABEL_PX) + 8
        longest = max((metrics.horizontalAdvance(name) for name in self._columns), default=0)
        angle = radians(LABEL_ANGLE)
        self._top = PAD + int(longest * sin(angle) + metrics.height() * cos(angle)) + 8
        self._right = int(longest * cos(angle)) + PAD  # the last label leans past its column
        width = self._left + len(self._columns) * CELL_MIN_W + self._right
        height = self._top + len(self._rows) * CELL_H + PAD
        self.setMinimumSize(max(width, 1), max(height, 1))
        self._fit()

    def _fit(self) -> None:
        """Spread the columns over the width on hand, between the floor and the ceiling of a cell."""
        if not self._columns:
            self._cell_w = CELL_MIN_W
            return
        room = self.width() - self._left - self._right
        self._cell_w = int(min(CELL_MAX_W, max(CELL_MIN_W, room // len(self._columns))))

    def sizeHint(self):
        return self.minimumSize()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._fit()
        self.update()

    # -- geometry

    @property
    def cell_width(self) -> int:
        return self._cell_w

    def cell_rect(self, row: int, column: int) -> QRect:
        return QRect(
            self._left + column * self._cell_w, self._top + row * CELL_H, self._cell_w, CELL_H
        )

    def hit(self, pos: QPoint) -> tuple[int, int]:
        """What is under a point: a cell, a row label (column ``-1``), a column label, or nothing."""
        x, y = pos.x(), pos.y()
        columns_end = self._left + len(self._columns) * self._cell_w
        rows_end = self._top + len(self._rows) * CELL_H
        column = (x - self._left) // self._cell_w if self._left <= x < columns_end else -1
        row = (y - self._top) // CELL_H if self._top <= y < rows_end else -1
        if column == -1 and x >= self._left:  # right of the matrix
            return -1, -1
        if row == -1 and y >= self._top:  # below it
            return -1, -1
        return int(row), int(column)

    # -- painting

    def paintEvent(self, event) -> None:
        colors = theme.current()
        rows, columns = len(self._rows), len(self._columns)
        cell_w = self._cell_w
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        normal, bold = self._fonts()
        metrics = QFontMetrics(normal)
        hover_row, hover_column = self._hover

        p.fillRect(
            QRect(self._left, self._top, columns * cell_w, rows * CELL_H),
            QColor(colors.plot_background),
        )
        exposed = event.rect()
        first = max(0, (exposed.top() - self._top) // CELL_H)
        last = min(rows, (exposed.bottom() - self._top) // CELL_H + 1)

        for i in range(first, last):
            row = self._rows[i]
            y = self._top + i * CELL_H
            if row.emphasized:
                p.setPen(QPen(QColor(colors.border), 1))
                p.drawLine(PAD, y, self._left + columns * cell_w + PAD, y)
            for j in range(columns):
                rect = self.cell_rect(i, j).adjusted(
                    CELL_INSET, CELL_INSET, -CELL_INSET, -CELL_INSET
                )
                if self._fills is not None:
                    fill = self._fills[i][j]
                    p.setPen(Qt.PenStyle.NoPen)
                    p.fillRect(rect, QColor(fill if fill else colors.block_fill))
                    continue
                paint_cell(
                    p,
                    rect,
                    self._shares[i, j],
                    int(self._marks[i, j]),
                    float(self._filled[i, j]) if self._filled is not None else 0.0,
                    bool(self._struck[i, j]) if self._struck is not None else False,
                )

            # The row label, keyed by its swatch; the space of the swatch is
            # kept even when there is none, so the labels line up.
            font = bold if row.emphasized or i == hover_row else normal
            p.setFont(font)
            x = PAD
            if row.swatch:
                p.setPen(QPen(QColor(colors.border), 1))
                p.setBrush(QColor(row.swatch))
                p.drawRect(QRect(x, y + (CELL_H - SWATCH_PX) // 2, SWATCH_PX, SWATCH_PX))
            x += SWATCH_PX + 6
            room = self._left - x - 8
            p.setPen(QColor(colors.highlight if i == hover_row else colors.text))
            text = QFontMetrics(font).elidedText(row.label, Qt.TextElideMode.ElideRight, room)
            p.drawText(
                QRect(x, y, room, CELL_H),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                text,
            )

        # The column labels, each rising from the middle of its column.
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        for j, name in enumerate(self._columns):
            font = bold if j == hover_column else normal
            p.setFont(font)
            if j == hover_column:
                p.setPen(QColor(colors.highlight))
            else:
                p.setPen(QColor(colors.faint if j in self._muted_columns else colors.text))
            p.save()
            p.translate(self._left + j * cell_w + cell_w / 2, self._top - 6)
            p.rotate(-LABEL_ANGLE)
            p.drawText(QPointF(0, (metrics.ascent() - metrics.descent()) / 2), name)
            p.restore()
        p.restore()

        if hover_row >= 0 or hover_column >= 0:
            band = QColor(colors.highlight)
            band.setAlpha(28)
            if hover_row >= 0:
                p.fillRect(
                    QRect(self._left, self._top + hover_row * CELL_H, columns * cell_w, CELL_H),
                    band,
                )
            if hover_column >= 0:
                p.fillRect(
                    QRect(self._left + hover_column * cell_w, self._top, cell_w, rows * CELL_H),
                    band,
                )
        if hover_row >= 0 and hover_column >= 0:
            p.setPen(QPen(QColor(colors.outline), 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(self.cell_rect(hover_row, hover_column).adjusted(0, 0, -1, -1))
        p.end()

    # -- pointer

    def mouseMoveEvent(self, event) -> None:
        hit = self.hit(event.position().toPoint())
        if hit != self._hover:
            self._hover = hit
            self.hovered.emit(*hit)
            self.update()

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        if self._hover != (-1, -1):
            self._hover = (-1, -1)
            self.hovered.emit(-1, -1)
            self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            row, column = self.hit(event.position().toPoint())
            if row >= 0 or column >= 0:
                self.clicked.emit(row, column)
                event.accept()
                return
        super().mousePressEvent(event)


__all__ = [
    "CELL_H",
    "CELL_MAX_W",
    "CELL_MIN_W",
    "KEY_LABELS",
    "MARK_PX",
    "SWATCH_KINDS",
    "ColorKey",
    "HeatmapRow",
    "HeatmapWidget",
    "StateKey",
    "draw_slash",
    "filled_color",
    "paint_cell",
    "ramp_color",
    "swatch_image",
]
