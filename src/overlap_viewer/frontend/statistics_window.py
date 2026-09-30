"""The statistics table: what the readings of every sensor on show amount to, in numbers.

Opened from the instance window, one row per selected sensor of every block,
one column per figure of ``descriptors.SUMMARY`` (the mean, the median, the
spread, the extremes, the quartiles, the skewness and the kurtosis), every
figure in the unit the traces are drawn in. The table follows the window: a
sensor ticked or cleared there, or the instances joined, and it is counted
again.

*Stretch on screen only* describes the samples inside the stretch of time
the instance window shows, so that zooming or panning the plots chooses the
window described, and the table follows every pan and zoom; otherwise every
block is described whole.

*Measurements only* describes the samples the historian archived rather than
every sample of the 1 Hz grid, the straight lines it drew between them left
out: the mean barely moves, the spread and the tails can.
"""

from collections.abc import Callable
from typing import NamedTuple

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from overlap_viewer.algorithms.descriptors import SUMMARY, describe, format_figure, summary
from overlap_viewer.backend import theme

MEASUREMENTS_TIP = (
    "Describe only the samples the historian archived, leaving out the ones it held or "
    "interpolated between them; the valve states are always described whole"
)
ON_SCREEN_TIP = (
    "Describe only the stretch of time on screen: zoom or pan the plots of the instance window "
    "to choose it, and the table follows"
)
COPY_TIP = "Copy the table, tab separated, to paste into a spreadsheet"
WHOLE_NOTE = "Every block whole"
ON_SCREEN_NOTE = "Only the stretch of time on screen (zoom or pan the plots to choose it)"
GRID_NOTE = "every sample of the 1 Hz grid, the historian's interpolated and held ones included"
MEASURED_NOTE = "the measurements alone, as the historian archived them"
PLAUSIBLE_NOTE = "readings outside the plausible range are counted as they are (⚠)."


class StatisticsRow(NamedTuple):
    """The readings of one sensor of one block, as the table describes them."""

    instance: str
    sensor: str  # its name, with its unit and a ⚠ when it reads outside its plausible range
    values: np.ndarray


class StatisticsWindow(QDialog):
    """A table of the figures of every sensor on show in an instance window.

    ``source(measurements_only, on_screen_only)`` gives the rows to describe;
    ``refresh`` asks it again, which the instance window does whenever what it
    shows changes, and after every pan and zoom when the stretch on screen is
    what is described.
    """

    def __init__(
        self, source: Callable[[bool, bool], list[StatisticsRow]], title: str, parent=None
    ):
        super().__init__(parent)
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.setWindowTitle(f"Statistics | {title}")
        self._source = source

        layout = QVBoxLayout(self)
        controls = QHBoxLayout()
        self._on_screen = QCheckBox("Stretch on screen only")
        self._on_screen.setToolTip(ON_SCREEN_TIP)
        self._on_screen.toggled.connect(self.refresh)
        controls.addWidget(self._on_screen)
        self._measured = QCheckBox("Measurements only")
        self._measured.setToolTip(MEASUREMENTS_TIP)
        self._measured.toggled.connect(self.refresh)
        controls.addWidget(self._measured)
        controls.addStretch(1)
        copy = QPushButton("Copy")
        copy.setToolTip(COPY_TIP)
        copy.clicked.connect(self.copy)
        controls.addWidget(copy)
        layout.addLayout(controls)

        self._table = QTableWidget(0, 2 + len(SUMMARY))
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        for column, (header, tip) in enumerate(
            [("Instance", ""), ("Sensor", "")] + [(h, t) for _n, h, t in SUMMARY]
        ):
            item = QTableWidgetItem(header)
            item.setToolTip(tip)
            self._table.setHorizontalHeaderItem(column, item)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self._table, 1)
        self._note = QLabel()
        self._note.setWordWrap(True)
        layout.addWidget(self._note)
        self.restyle()
        self.resize(1000, 360)
        self.refresh()

    @property
    def measurements_only(self) -> bool:
        return self._measured.isChecked()

    @property
    def on_screen_only(self) -> bool:
        return self._on_screen.isChecked()

    def restyle(self) -> None:
        self._note.setStyleSheet(f"color: {theme.current().muted}; font-size: 8pt;")

    def refresh(self, *args) -> None:
        """Describe the rows the source gives now, and fill the table with them."""
        QApplication.setOverrideCursor(QCursor(Qt.CursorShape.WaitCursor))
        try:
            rows = self._source(self.measurements_only, self.on_screen_only)
            self._table.setRowCount(len(rows))
            for r, row in enumerate(rows):
                figures = [format_figure(value) for value in summary(describe(row.values))]
                for c, text in enumerate([row.instance, row.sensor, *figures]):
                    item = QTableWidgetItem(text)
                    if c >= 2:
                        item.setTextAlignment(
                            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                        )
                    self._table.setItem(r, c, item)
        finally:
            QApplication.restoreOverrideCursor()
        # One block has nothing to tell its rows apart by.
        self._table.setColumnHidden(0, len({row.instance for row in rows}) < 2)
        scope = ON_SCREEN_NOTE if self.on_screen_only else WHOLE_NOTE
        samples = MEASURED_NOTE if self.measurements_only else GRID_NOTE
        self._note.setText(f"{scope}, {samples}; {PLAUSIBLE_NOTE}")

    def text(self) -> str:
        """The table as tab-separated text, a header line first, the hidden column left out."""
        table = self._table
        columns = [c for c in range(table.columnCount()) if not table.isColumnHidden(c)]
        lines = ["\t".join(table.horizontalHeaderItem(c).text() for c in columns)]
        for r in range(table.rowCount()):
            lines.append("\t".join(table.item(r, c).text() for c in columns))
        return "\n".join(lines)

    def copy(self) -> None:
        QApplication.clipboard().setText(self.text())
