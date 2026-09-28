"""The placement boxes of a feature panel: Topside, Seabed, Subsurface.

Each box ticks, in one click, every recorded sensor measured at one placement
of the production system (``config.PLACEMENTS``), and a second click clears
them again; the boxes add up, so two placements can be on show together. A
box is ticked while every recorded sensor of its placement is selected, half
ticked while some are, and greyed out when none of its sensors is recorded.
It replaced a per-fault "Signature" box, whose sets are not agreed on and
steered the reading toward them; which part of the system matters for an
analysis is left to the user.
"""

from collections.abc import Callable, Mapping

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QCheckBox, QVBoxLayout, QWidget

from overlap_viewer.backend.config import PLACEMENT_NOTES, PLACEMENTS


class PlacementChecks(QWidget):
    """Three boxes over the feature checkboxes of a panel.

    ``set_checks`` hands the panel's feature boxes over (a disabled one is a
    sensor not recorded); ``sync`` brings the three in line with a selection
    changed by hand. ``applied`` is emitted after a box has ticked or cleared
    its sensors, with the feature boxes' own signals blocked, so the page
    redraws once.
    """

    applied = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        self._features: Mapping[str, QCheckBox] = {}
        self._noun = "instances"
        self._boxes: dict[str, QCheckBox] = {}
        for place in PLACEMENTS:
            box = QCheckBox(place)
            box.clicked.connect(self._clicked(place))
            layout.addWidget(box)
            self._boxes[place] = box

    def set_checks(self, features: Mapping[str, QCheckBox], noun: str = "instances") -> None:
        """Take the feature boxes of the panel, and say what the recordings are called."""
        self._features = features
        self._noun = noun
        for place, box in self._boxes.items():
            recorded = self._members(place)
            missing = [name for name in PLACEMENTS[place] if name not in recorded]
            text = (
                f"{place}: {PLACEMENT_NOTES[place]}.\nTicks {', '.join(recorded) or 'nothing'}; "
                "a second click clears them."
            )
            if missing:
                text += f"\nNot recorded by these {noun}, so left out: {', '.join(missing)}."
            box.setToolTip(text)
            box.setEnabled(bool(recorded))
        self.sync()

    def _members(self, place: str) -> list[str]:
        """The sensors of one placement this panel offers and some recording carries."""
        return [
            name
            for name in PLACEMENTS[place]
            if name in self._features and self._features[name].isEnabled()
        ]

    def _clicked(self, place: str) -> Callable[[bool], None]:
        def apply(_checked: bool) -> None:
            members = self._members(place)
            # Ticked in full, a click clears the placement; otherwise it fills it in.
            wanted = not all(self._features[name].isChecked() for name in members)
            for name in members:
                check = self._features[name]
                check.blockSignals(True)
                check.setChecked(wanted)
                check.blockSignals(False)
            self.sync()
            self.applied.emit()

        return apply

    def sync(self) -> None:
        """Tick each box in full, in half or not at all, as its sensors are selected."""
        for place, box in self._boxes.items():
            members = self._members(place)
            ticked = sum(self._features[name].isChecked() for name in members)
            if not members or ticked == 0:
                state = Qt.CheckState.Unchecked
            elif ticked == len(members):
                state = Qt.CheckState.Checked
            else:
                state = Qt.CheckState.PartiallyChecked
            box.blockSignals(True)
            box.setCheckState(state)
            box.blockSignals(False)
