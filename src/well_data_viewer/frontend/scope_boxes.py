"""The scope of a page as two boxes, a fault class and a well, that narrow it together.

The Dispersions page and the pair map of the Availability page are counted
over a scope: every real instance, those of one fault class, those of one well,
or those of one fault class on one well. One box listing the classes and the
wells side by side made the last impossible; two boxes, each with its *All*,
make it the intersection of what each asks for. Each box counts its entries
under the other's choice and greys out the empty ones, so that a scope with no
instance in it cannot be chosen: *All* in the other box brings an entry back.
"""

import pandas as pd
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QComboBox, QLabel, QToolBar

from well_data_viewer.backend.dataset import DatasetInfo, well_label
from well_data_viewer.frontend import styling

ALL = -1  # the key of the All entry of either box


def _instances(count: int) -> str:
    return f"{count} instance{'s' if count != 1 else ''}"


class ScopeBoxes(QObject):
    """A *Class* and a *Well* box, filled from a catalogue, that say which instances are in scope.

    Signals
    -------
    changed()
        Either box was changed by the reader; both have been counted again.
    """

    changed = Signal()

    def __init__(self, info: DatasetInfo, tip: str, parent=None):
        super().__init__(parent)
        self.info = info
        self._catalogue: pd.DataFrame | None = None
        self.class_box = self._box(tip)
        self.well_box = self._box(tip)

    def _box(self, tip: str) -> QComboBox:
        box = QComboBox()
        box.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        styling.limit_popup(box)
        box.setToolTip(tip)
        box.currentIndexChanged.connect(self._on_changed)
        return box

    def add_to(self, bar: QToolBar) -> list[QAction]:
        """Put the two boxes and their labels on ``bar``; the actions, to show and hide them."""
        return [
            bar.addWidget(QLabel(" Class ")),
            bar.addWidget(self.class_box),
            bar.addWidget(QLabel(" Well ")),
            bar.addWidget(self.well_box),
        ]

    # -- what the boxes say

    @property
    def fault(self) -> int:
        """The fault class in scope, ``ALL`` for every class."""
        data = self.class_box.currentData()
        return ALL if data is None else int(data)

    @property
    def well(self) -> int:
        """The well in scope, ``ALL`` for every well."""
        data = self.well_box.currentData()
        return ALL if data is None else int(data)

    def key(self) -> tuple[int, int]:
        """``(fault, well)``, ``ALL`` for either box's *All*."""
        return (self.fault, self.well)

    def name(self) -> str:
        """The scope in words: ``1. Abrupt Increase of BSW on WELL-00002``, ``All real instances``."""
        fault, well = self.key()
        if fault == ALL and well == ALL:
            return "All real instances"
        name = "" if fault == ALL else f"{fault}. {self.info.fault_name(fault)}"
        if well == ALL:
            return name
        return f"{name} on {well_label(well)}" if name else well_label(well)

    def mask(self, bars: pd.DataFrame):
        """Which rows of ``bars`` (with ``fault_class`` and ``well`` columns) are in scope, ``None`` for all."""
        fault, well = self.key()
        if fault == ALL and well == ALL:
            return None
        keep = pd.Series(True, index=bars.index)
        if fault != ALL:
            keep &= bars["fault_class"] == fault
        if well != ALL:
            keep &= bars["well"] == well
        return keep.to_numpy()

    # -- filling

    def set_catalogue(self, catalogue: pd.DataFrame | None) -> None:
        """List the classes and the wells of ``catalogue``, keeping the choice where it still holds."""
        self._catalogue = catalogue
        self._fill()

    def set_scope(self, fault: int = ALL, well: int = ALL) -> None:
        """Choose the instances of ``fault`` on ``well`` in code (``ALL`` lifts either); emits ``changed``."""
        for box, value in ((self.class_box, fault), (self.well_box, well)):
            index = box.findData(int(value))
            if index < 0:
                raise ValueError(f"no fault class or well {value!r} in the catalogue")
            box.blockSignals(True)
            box.setCurrentIndex(index)
            box.blockSignals(False)
        self._on_changed()

    def _on_changed(self, *args) -> None:
        self._fill()
        self.changed.emit()

    def _fill(self) -> None:
        """Count each box's entries under the other's choice, greying out the empty ones.

        A pair with no instance (set in code, or emptied by a rescan) keeps the
        class and lets the well go.
        """
        catalogue = self._catalogue
        fault, well = self.key()
        if catalogue is None:
            self._fill_box(self.class_box, "All classes (0 instances)", [], ALL)
            self._fill_box(self.well_box, "All wells (0 instances)", [], ALL)
            return
        if ALL not in (fault, well):
            pair = (catalogue["fault_class"] == fault) & (catalogue["well"] == well)
            if not pair.any():
                well = ALL
        on_well = catalogue if well == ALL else catalogue[catalogue["well"] == well]
        of_fault = catalogue if fault == ALL else catalogue[catalogue["fault_class"] == fault]
        faults_here = on_well["fault_class"].value_counts()
        wells_here = of_fault["well"].value_counts()
        classes = sorted(int(f) for f in catalogue["fault_class"].unique())
        wells = sorted(int(w) for w in catalogue["well"].unique())
        self._fill_box(
            self.class_box,
            f"All classes ({_instances(len(on_well))})",
            [(f"{f}. {self.info.fault_name(f)}", f, int(faults_here.get(f, 0))) for f in classes],
            fault,
        )
        self._fill_box(
            self.well_box,
            f"All wells ({_instances(len(of_fault))})",
            [(well_label(w), w, int(wells_here.get(w, 0))) for w in wells],
            well,
        )

    @staticmethod
    def _fill_box(
        box: QComboBox, every: str, entries: list[tuple[str, int, int]], wanted: int
    ) -> None:
        box.blockSignals(True)
        box.clear()
        box.addItem(every, ALL)
        if entries:
            box.insertSeparator(box.count())
        for text, key, count in entries:
            box.addItem(f"{text} ({_instances(count)})", key)
            box.model().item(box.count() - 1).setEnabled(count > 0)
        index = box.findData(wanted)
        enabled = index >= 0 and box.model().item(index).isEnabled()
        box.setCurrentIndex(index if enabled else 0)
        box.blockSignals(False)
