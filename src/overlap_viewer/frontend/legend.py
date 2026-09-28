"""The color key of the overview: one clickable swatch per fault and reach drawn.

The key doubles as a filter and as a mirror of the plots. Clicking a swatch
restricts the grid to the wells that recorded an instance of that fault;
hovering a bar in any plot lights up the swatches of the hovered instance and
of the instances it overlaps, and dims the rest, so the color under the pointer
can be named without leaving the plot.

A full key is sixteen entries tall, which is a lot of screen to spend on
something one consults rather than reads, so it retracts to its title bar. It
keeps working retracted: hovering a bar then pops just the entries of that
instance and of the instances it overlaps into the title row, which is the only
part of the key that hover actually needs.

Entries are laid out by ``FlowLayout``, which wraps like text but on a fixed
column pitch, so entries line up down the rows, and which keeps the entries of
one fault together: a fault whose instances differ in how far the fault
developed contributes a gradient of two or three swatches, and reading a
gradient means seeing its steps side by side, so such a group gets a row of its
own.
"""

from PySide6.QtCore import QMargins, QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from overlap_viewer.backend import theme
from overlap_viewer.backend.palette import LegendEntry

CHIP_SIZE = (18, 12)
MAX_POPPED = 4  # entries the retracted key shows at once before counting the rest


class FlowLayout(QLayout):
    """Left-to-right layout that wraps to a new row, with columns and forced breaks.

    Qt ships no flow layout, and the alternatives do not fit: a grid wastes a
    whole column on the widest entry in every row, and one long rich-text label
    cannot keep a group of entries together. In ``uniform`` mode every item is
    placed on the pitch of the widest one, so entries line up down the rows;
    items added with ``break_before=True`` always start a row.
    """

    def __init__(self, parent=None, horizontal: int = 16, vertical: int = 2, uniform: bool = True):
        super().__init__(parent)
        self._items: list = []
        self._breaks: list[bool] = []
        self._horizontal = horizontal
        self._vertical = vertical
        self._uniform = uniform
        self.setContentsMargins(QMargins(0, 0, 0, 0))

    # -- QLayout API

    def addItem(self, item) -> None:
        self._items.append(item)
        self._breaks.append(False)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int):
        if not 0 <= index < len(self._items):
            return None
        self._breaks.pop(index)
        return self._items.pop(index)

    def expandingDirections(self) -> Qt.Orientations:
        return Qt.Orientations()

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._lay_out(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._lay_out(rect, apply=True)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        return size.grownBy(self.contentsMargins())

    # -- the flow itself

    def add_widget(self, widget: QWidget, break_before: bool = False) -> None:
        """Append a widget, optionally starting a new row with it."""
        self.addWidget(widget)
        self._breaks[-1] = break_before

    def _lay_out(self, rect: QRect, apply: bool) -> int:
        """Place every item; return the total height the items need at this width."""
        margins = self.contentsMargins()
        area = rect.marginsRemoved(margins)
        if not self._items:
            return margins.top() + margins.bottom()

        sizes = [item.sizeHint() for item in self._items]
        pitch = max(size.width() for size in sizes) + self._horizontal
        columns = max(1, (area.width() + self._horizontal) // pitch)
        x, y, row_height, column = area.x(), area.y(), 0, 0

        for item, break_before, size in zip(self._items, self._breaks, sizes):
            if self._uniform:
                if column > 0 and (break_before or column >= columns):
                    y, column, row_height = y + row_height + self._vertical, 0, 0
                x = area.x() + column * pitch
                column += 1
            else:
                if (break_before and x > area.x()) or (
                    row_height > 0 and x + size.width() > area.right() + 1
                ):
                    x, y, row_height = area.x(), y + row_height + self._vertical, 0
            if apply:
                item.setGeometry(QRect(QPoint(x, y), size))
            if not self._uniform:
                x += size.width() + self._horizontal
            row_height = max(row_height, size.height())
        return y + row_height - rect.y() + margins.bottom()


def row_breaks(entries: list[LegendEntry]) -> list[bool]:
    """Which entries must start a new row of the key.

    A fault with more than one entry is a gradient (the same hue at two or
    three tints) and its steps are only readable side by side, so the group
    starts a row and whatever follows it starts the next. Faults with a single
    entry simply flow.

    Parameters
    ----------
    entries : list[LegendEntry]
        The key's entries, the entries of one fault consecutive (as
        ``palette.legend_entries`` returns them).

    Returns
    -------
    list[bool]
        One flag per entry, ``True`` where a row must begin.
    """
    sizes: dict[int, int] = {}
    for entry in entries:
        sizes[entry.fault_class] = sizes.get(entry.fault_class, 0) + 1
    breaks, previous = [], None
    for entry in entries:
        first_of_group = entry.fault_class != previous
        gradient = sizes[entry.fault_class] > 1
        after_gradient = previous is not None and sizes[previous] > 1
        breaks.append(first_of_group and (gradient or after_gradient))
        previous = entry.fault_class
    return breaks


class LegendSwatch(QFrame):
    """One entry of the key: the exact color of a set of bars, and what it means."""

    clicked = Signal(int)  # the fault class of this entry

    def __init__(self, entry: LegendEntry, tooltip: str, parent=None):
        super().__init__(parent)
        self.entry = entry
        self._selected = False
        self._state = "plain"
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(tooltip)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 0, 6, 0)
        layout.setSpacing(5)
        chip = QFrame()
        chip.setFixedSize(*CHIP_SIZE)
        self._label = QLabel(entry.label)
        # Highlighting bolds the text, which is wider; the label is sized for the
        # bold version from the start so that pointing at an entry cannot shift
        # the column the other entries are lined up on.
        bold = QFont(self._label.font())
        bold.setBold(True)
        self._label.setFixedWidth(QFontMetrics(bold).horizontalAdvance(entry.label) + 2)
        layout.addWidget(chip)
        layout.addWidget(self._label)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._chip = chip
        self.apply_theme()

    def apply_theme(self) -> None:
        """Take the colors of the theme now in force, chip and state styling alike."""
        entry = self.entry
        self._chip.setStyleSheet(f"background-color: {entry.fill}; border: 1px solid {entry.edge};")
        self._restyle()

    def set_state(self, state: str) -> None:
        """Set the pointing state: ``plain``, ``highlight`` or ``dimmed``."""
        if state != self._state:
            self._state = state
            self._restyle()

    def set_selected(self, selected: bool) -> None:
        """Mark this entry as the one the grid is filtered by."""
        if selected != self._selected:
            self._selected = selected
            self._restyle()

    def _restyle(self) -> None:
        state = "selected" if self._selected and self._state != "dimmed" else self._state
        background, border, text = theme.current().swatches[state]
        weight = "bold" if state in ("highlight", "selected") else "normal"
        self.setStyleSheet(
            f"LegendSwatch {{ background-color: {background}; border: 1px solid {border};"
            f" border-radius: 3px; }}"
        )
        self._label.setStyleSheet(f"color: {text}; font-weight: {weight};")

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.entry.fault_class)
            event.accept()
            return
        super().mousePressEvent(event)


class LegendBar(QWidget):
    """The whole key: a title that retracts it, the swatches, and the popped entries.

    Signals
    -------
    fault_clicked(int)
        A swatch was clicked; the receiver decides what filtering it means.
    """

    fault_clicked = Signal(int)

    TITLE = "Bar color: fault folder (severity reach)"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._entries: list[LegendEntry] = []
        self._swatches: list[LegendSwatch] = []
        self._popped: list[LegendSwatch] = []
        self._highlighted: set[tuple[int, str]] = set()
        self._selected: int | None = None
        self._collapsed = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(2)

        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(10)
        self._toggle = QToolButton()
        self._toggle.setAutoRaise(True)
        self._toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self._toggle.clicked.connect(lambda: self.set_collapsed(not self._collapsed))
        header_layout.addWidget(self._toggle)
        self._pop_layout = QHBoxLayout()
        self._pop_layout.setContentsMargins(0, 0, 0, 0)
        self._pop_layout.setSpacing(8)
        header_layout.addLayout(self._pop_layout)
        self._more = QLabel()
        header_layout.addWidget(self._more)
        self._hint = QLabel()
        header_layout.addWidget(self._hint)
        header_layout.addStretch(1)
        # Fixed, so that popping an entry in and out cannot change the height of
        # the row: the grid below would shift under the pointer and the hover it
        # is reacting to would change, which flickers.
        header.setFixedHeight(max(self._toggle.sizeHint().height(), 24))
        outer.addWidget(header)

        self._body = QWidget()
        policy = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        policy.setHeightForWidth(True)
        self._body.setSizePolicy(policy)
        self._flow = FlowLayout(self._body)
        outer.addWidget(self._body)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        self.apply_theme()
        self._refresh_header()

    def apply_theme(self) -> None:
        """Take the colors of the theme now in force."""
        colors = theme.current()
        self._more.setStyleSheet(f"color: {colors.muted};")
        self._hint.setStyleSheet(f"color: {colors.faint};")
        for swatch in (*self._swatches, *self._popped):
            swatch.apply_theme()

    # -- contents

    def set_entries(self, entries: list[LegendEntry], fault_names: dict[int, str]) -> None:
        """Rebuild the key, keeping the swatches of one fault on a single row."""
        for swatch in (*self._swatches, *self._popped):
            swatch.setParent(None)
            swatch.deleteLater()
        self._entries = list(entries)
        self._swatches = []
        self._popped = []

        for entry, break_before in zip(entries, row_breaks(entries)):
            name = fault_names.get(entry.fault_class, f"class {entry.fault_class}")
            tooltip = f"Click to show only the wells that recorded {name}"
            swatch = LegendSwatch(entry, tooltip, self._body)
            swatch.clicked.connect(self.fault_clicked)
            self._flow.add_widget(swatch, break_before=break_before)
            self._swatches.append(swatch)

            popped = LegendSwatch(entry, tooltip, self)
            popped.clicked.connect(self.fault_clicked)
            popped.hide()
            self._pop_layout.addWidget(popped)
            self._popped.append(popped)

        present = {entry.fault_class for entry in entries}
        self.set_selected_fault(self._selected if self._selected in present else None)
        self.apply_theme()
        self._refresh_header()
        self.updateGeometry()

    # -- state

    def highlight(self, keys: set[tuple[int, str]]) -> None:
        """Light up the entries in ``keys`` and dim the others; empty clears both."""
        self._highlighted = set(keys)
        for swatch in self._swatches:
            if not keys:
                swatch.set_state("plain")
            else:
                swatch.set_state("highlight" if swatch.entry.key in keys else "dimmed")
        self._refresh_popped()

    def set_selected_fault(self, fault_class: int | None) -> None:
        """Mark the fault the grid is filtered by, ``None`` for no filter."""
        self._selected = fault_class
        for swatch in (*self._swatches, *self._popped):
            swatch.set_selected(swatch.entry.fault_class == fault_class)

    def set_collapsed(self, collapsed: bool) -> None:
        """Retract the key to its title row, or open it again."""
        self._collapsed = collapsed
        self._body.setVisible(not collapsed)
        self._refresh_header()
        self._refresh_popped()
        self.updateGeometry()

    @property
    def collapsed(self) -> bool:
        return self._collapsed

    @property
    def selected_fault(self) -> int | None:
        return self._selected

    # -- painting the header

    def _refresh_header(self) -> None:
        arrow = "▸" if self._collapsed else "▾"
        self._toggle.setText(f"{arrow}  {self.TITLE}")
        self._toggle.setToolTip(
            "Show the whole color key" if self._collapsed else "Retract the color key"
        )

    def _refresh_popped(self) -> None:
        """Show, in the title row of a retracted key, the entries under the pointer."""
        popping = self._collapsed and bool(self._highlighted)
        shown = 0
        for swatch in self._popped:
            visible = popping and swatch.entry.key in self._highlighted and shown < MAX_POPPED
            swatch.setVisible(visible)
            shown += visible
        missing = len(self._highlighted) - shown if popping else 0
        self._more.setText(f"+{missing} more" if missing > 0 else "")
        self._more.setVisible(missing > 0)
        self._hint.setText(
            f"{len(self._entries)} colors; hover a bar, or click to open"
            if self._collapsed and not popping
            else ""
        )
        self._hint.setVisible(self._collapsed and not popping)
