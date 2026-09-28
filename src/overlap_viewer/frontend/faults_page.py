"""The faults page: every real instance of one fault, from every well, side by side or over one another.

Rabelo's figures 2.5 and 2.6 put two instances of the same fault side by side
to make a point: the same event, on two wells, has a different magnitude, a
different time to install itself and a different baseline. This page makes
that comparison for any fault and every well at once, on a time axis that
starts where the event begins in each instance, so that the shapes line up
whatever the clock said.

One fault is chosen and each **feature** gets a section; the drawing itself (
the three arrangements, the three domains, the window of hours around the
onset, the normalization, the transforms, the hover) is
``series_page.SeriesPage``, which the features page is the other half of.

The instances of a fault are listed on the right with the moment each can be
aligned on, read from the label runs the catalogue keeps, so the list costs
nothing; only the instances ticked are read from disk and drawn. Beyond a couple
of dozen the page starts with the earliest ones ticked and leaves the rest to
the user.
"""

import numpy as np
import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QLabel,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from overlap_viewer.algorithms.faults import (
    ALIGNMENT_NAMES,
    ALIGNMENTS,
    onset_from_runs,
    relative_hours,
)
from overlap_viewer.backend import theme
from overlap_viewer.backend.availability import ABSENT, Availability
from overlap_viewer.backend.config import (
    DEFAULT_FEATURES,
    MAX_OVERLAID_INSTANCES,
    MAX_SMALL_MULTIPLES,
    REACH_LABELS,
    placement_of,
)
from overlap_viewer.backend.dataset import DatasetInfo, WellData, well_label
from overlap_viewer.backend.labels import segments_from_json
from overlap_viewer.frontend.instance_window import PANEL_WIDTH
from overlap_viewer.frontend.loading import FrameCache
from overlap_viewer.frontend.placements import PlacementChecks
from overlap_viewer.frontend.series_page import (
    LIST_WIDTH,
    InstanceList,
    Section,
    Series,
    SeriesPage,
)

HINT = (
    "Every plot is one real instance of the fault, in the color of its well, on a time axis that "
    "starts where the event begins in it | hover a trace to name it and read it, click it to open "
    "its instance window on that feature | tick features on the left and instances on the right, "
    "click an instance's name to open it | Ctrl + wheel to zoom, the wheel scrolls | F1 for help"
)

DOMAIN_TIP = (
    "What every plot shows of the stretch the hours before and after the onset select. Time "
    "series: the readings against the hours from the onset. Distribution: a histogram of the "
    "readings, as a share of the instance's samples so that instances of different length "
    "compare, stacked by label period in the class colors in the grid, an area in the color of "
    "the well when overlaid, so that where two distributions sit on top of one another reads as "
    "a deeper shade, with a triangle over the fullest bin of each: the value that "
    "instance spends most of its time at, which the mean and the median both miss once the fault "
    "has skewed the readings or split them in two. Spectrum: the power spectral density against "
    "the period, both "
    "logarithmic, the mean and the trend removed first. Overlaid, the spectra of two dozen "
    "instances read together where their traces did not, since the question is whether their "
    "peaks line up."
)
LAYOUT_TIP = (
    "Small multiples give every instance a plot of its own, laid out in a grid, so that "
    "two dozen shapes can be read one against the next; overlaid draws them all on one "
    "set of axes, which says how far apart their levels are and little else once there "
    "are more than a handful. Overall pools every instance drawn into a single curve per "
    "feature, across every well at once: one distribution, or one spectrum, of the fault as the "
    "dataset holds it. It is offered off the time axis only: instances cut from different "
    "months have no common clock to be drawn against."
)
NORMALIZE_TIP = (
    "Scale every series to its own level: each reading as standard deviations from the "
    "mean of that sensor over the whole instance, which is how Rabelo's pipeline "
    "normalizes an instance. Wells run at different levels, and the shape of the change "
    "is what the instances have in common."
)


class FaultsPage(SeriesPage):
    """The page: the fault and its alignment in the toolbar, features left, plots center, instances right."""

    HINT = HINT

    def __init__(self, info: DatasetInfo, frames: FrameCache, passes=None, parent=None):
        super().__init__(info, passes, parent)
        self._frames = frames
        self._catalogue: pd.DataFrame | None = None
        self._wells: dict[int, WellData] = {}
        self._availability: Availability | None = None
        self._instances: list[
            dict
        ] = []  # per instance of the fault: well, position, title, onset, ...
        self._items: list[QListWidgetItem] = []
        self._checks: dict[str, QCheckBox] = {}
        # The alignment the user asked for last, kept across faults: a fault
        # without a transient falls back to what it allows, and the next fault
        # with one goes back to the onset of the transient.
        self._preferred = "transient"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self._build_toolbar())
        layout.addWidget(self.build_parameter_bar(NORMALIZE_TIP))
        self._feature_panel = self._build_feature_panel()
        self._instance_panel = self._build_instance_panel()
        layout.addWidget(self.build_body(self._feature_panel, self._instance_panel), 1)
        self._restyle()

    # -- construction

    def _build_toolbar(self) -> QToolBar:
        bar = QToolBar("Faults")
        bar.setMovable(False)
        bar.addWidget(QLabel(" Fault "))
        self._fault = QComboBox()
        self._fault.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self._fault.setToolTip("The fault whose real instances are drawn over one another")
        self._fault.currentIndexChanged.connect(self._on_fault_changed)
        bar.addWidget(self._fault)

        bar.addSeparator()
        self.add_alignment_control(bar)

        bar.addSeparator()
        self.add_shared_controls(bar, DOMAIN_TIP, LAYOUT_TIP)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        bar.addWidget(spacer)
        self._note = QLabel()
        bar.addWidget(self._note)
        bar.addSeparator()
        self._show_features = QAction("Features", self)
        self._show_features.setCheckable(True)
        self._show_features.setChecked(True)
        self._show_features.setToolTip(
            "Show or hide the list of features on the left, to give the plots its width"
        )
        self._show_features.toggled.connect(self._on_features_toggled)
        bar.addAction(self._show_features)
        self._show_instances = QAction("Instances", self)
        self._show_instances.setCheckable(True)
        self._show_instances.setChecked(True)
        self._show_instances.setToolTip(
            "Show or hide the list of instances on the right, to give the plots its width"
        )
        self._show_instances.toggled.connect(self._on_instances_toggled)
        bar.addAction(self._show_instances)
        return bar

    def _on_instances_toggled(self, shown: bool) -> None:
        self._instance_panel.setVisible(shown)

    def _on_features_toggled(self, shown: bool) -> None:
        self._feature_panel.setVisible(shown)

    def _build_feature_panel(self) -> QWidget:
        panel = QWidget()
        panel.setFixedWidth(PANEL_WIDTH)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel("<b>Features</b>"))
        buttons = QVBoxLayout()
        buttons.setSpacing(2)
        clear = QPushButton("Clear")
        clear.clicked.connect(lambda: self._set_all_features(False))
        every = QPushButton("All recorded")
        every.clicked.connect(lambda: self._set_all_features(True))
        buttons.addWidget(clear)
        buttons.addWidget(every)
        layout.addLayout(buttons)
        self._placements = PlacementChecks()
        self._placements.applied.connect(self._on_feature_toggled)
        layout.addWidget(self._placements)
        self._feature_scroll = QScrollArea()
        self._feature_scroll.setWidgetResizable(True)
        self._feature_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._feature_box = QWidget()
        self._feature_layout = QVBoxLayout(self._feature_box)
        self._feature_layout.setContentsMargins(0, 0, 0, 0)
        self._feature_layout.setSpacing(2)
        self._feature_scroll.setWidget(self._feature_box)
        layout.addWidget(self._feature_scroll, 1)
        self._feature_note = QLabel(
            "Greyed-out features were recorded by no instance of the fault."
        )
        self._feature_note.setWordWrap(True)
        layout.addWidget(self._feature_note)
        return panel

    def _build_instance_panel(self) -> QWidget:
        panel = QWidget()
        panel.setFixedWidth(LIST_WIDTH)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel("<b>Instances</b>"))
        self.add_instance_buttons(layout)
        self.add_sort_control(layout)
        self._list = InstanceList()
        self._list.setMouseTracking(True)
        self._list.open_requested.connect(self._on_item_open)
        self._list.itemChanged.connect(self._on_item_changed)
        self._list.itemEntered.connect(self._on_item_entered)
        self._list.viewportEntered.connect(lambda: self._highlight(-1))
        layout.addWidget(self._list, 1)
        self._instance_note = QLabel()
        self._instance_note.setWordWrap(True)
        layout.addWidget(self._instance_note)
        return panel

    def on_map_results(self) -> None:
        if self.ready():
            self._rebuild_instances()

    def on_sort_changed(self, *args) -> None:
        if self.ready():
            self._rebuild_instances()

    # -- appearance

    def _restyle(self) -> None:
        colors = theme.current()
        self._restyle_plots()
        for note in (self._feature_note, self._instance_note, self._note):
            note.setStyleSheet(f"color: {colors.muted}; font-size: 8pt;")

    def apply_theme(self) -> None:
        """Take the colors of the theme now in force; ``set_catalogue`` redraws the plots after it."""
        self._restyle()

    # -- data

    def set_catalogue(self, catalogue: pd.DataFrame, wells: list[WellData]) -> None:
        """Take a new catalogue and its wells; the fault chosen stays chosen where it still exists.

        The very same catalogue again is a theme switch: the list is written
        again for its well colors and the plots drawn again for theirs, with
        the features and instances ticked and every plot's zoom kept.
        """
        if catalogue is self._catalogue and self.ready():
            self._wells = {well.well: well for well in wells}
            self._rebuild_instances()
            self._replot(keep_views=True)
            return
        self._catalogue = catalogue
        self._wells = {well.well: well for well in wells}
        self._availability = Availability.from_wells(wells, self.info)
        wanted = self._fault.currentData()
        self._fault.blockSignals(True)
        self._fault.clear()
        counts = catalogue["fault_class"].value_counts()
        for fault in sorted(counts.index):
            # The name alone: how many instances on how many wells is what the
            # status bar says about the fault chosen, and the box is narrow enough
            # to leave the toolbar's other controls on screen.
            self._fault.addItem(f"{fault}. {self.info.fault_name(int(fault))}", int(fault))
        index = self._fault.findData(wanted)
        self._fault.setCurrentIndex(max(index, 0))
        self._fault.blockSignals(False)
        self._on_fault_changed()

    @property
    def fault(self) -> int | None:
        data = self._fault.currentData()
        return None if data is None else int(data)

    def ready(self) -> bool:
        return self._availability is not None and self.fault is not None

    def _allowed_alignments(self, fault: int) -> list[str]:
        allowed = ["start"]
        if fault != 0:
            allowed.insert(0, "steady")
            if self.info.has_transient(fault):
                allowed.insert(0, "transient")
        return allowed

    def _on_fault_changed(self, *args) -> None:
        """A new fault: offer the alignments it allows, list its instances, offer its features."""
        fault = self.fault
        if fault is None:
            return
        allowed = self._allowed_alignments(fault)
        model = self._align.model()
        self._align.blockSignals(True)
        for i, key in enumerate(ALIGNMENTS):
            item = model.item(i)
            enabled = key in allowed
            item.setFlags(
                item.flags() | Qt.ItemFlag.ItemIsEnabled
                if enabled
                else item.flags() & ~Qt.ItemFlag.ItemIsEnabled
            )
        wanted = self._preferred if self._preferred in allowed else allowed[0]
        if self.alignment != wanted:
            self._align.setCurrentIndex(ALIGNMENTS.index(wanted))
        self._align.blockSignals(False)
        self._rebuild_instances()
        self._rebuild_features()
        self._replot(keep_range=False)

    def _on_alignment_changed(self, *args) -> None:
        self._preferred = self.alignment
        self._rebuild_instances()
        self._replot(keep_range=False)

    def _instances_of(self, fault: int) -> list[dict]:
        """Every real instance of the fault, by well and start, with the moment it aligns on."""
        found = []
        for well in sorted(self._wells):
            data = self._wells[well]
            rows = data.rows
            for position in np.flatnonzero(rows["fault_class"].to_numpy() == fault).tolist():
                row = rows.iloc[position]
                runs = (
                    segments_from_json(str(row["class_runs"]))
                    if "class_runs" in rows.columns
                    else []
                )
                found.append(
                    {
                        "well": well,
                        "position": position,
                        "fault": fault,
                        "file": str(row["file"]) if "file" in rows.columns else "",
                        "title": str(row["file"]).rsplit(".", 1)[0]
                        if "file" in rows.columns
                        else str(row["title"]),
                        "reach": str(row["reach"]),
                        "start": pd.Timestamp(row["start"]),
                        "end": pd.Timestamp(row["end"]),
                        "hours": float(row["hours"]),
                        "onset": onset_from_runs(
                            runs, fault, self.info.transient_offset, self.alignment
                        ),
                        "runs": runs,
                        "implausible": self._availability is not None
                        and self._availability.implausible_any(
                            [self._availability.index_of(well, position)]
                        ),
                    }
                )
        return found

    def _well_colors(self) -> dict[int, str]:
        """One color per well of the whole catalogue, in well order.

        Over the catalogue and not over the instances of the fault on show, so
        that a well keeps its color from one fault to the next: the page exists
        to compare an event across wells, and a reader who has learnt that this
        green is WELL-00014 in one fault should not find it standing for
        another well in the next. The palette cycles when the dataset holds
        more wells than it has colors, which at least cycles in the same place
        every time.
        """
        palette = theme.current().wells
        return {well: palette[k % len(palette)] for k, well in enumerate(sorted(self._wells))}

    def _rebuild_instances(self) -> None:
        """List the instances of the fault, the earliest ticked, those without an onset greyed out."""
        fault = self.fault
        self._sync_sort_control()  # the descriptor orders name the first feature ticked
        previously = {
            (entry["well"], entry["position"])
            for entry, item in zip(self._instances, self._items)
            if item.checkState() == Qt.CheckState.Checked
        }
        fresh = not self._instances or self._instances[0].get("fault") != fault
        self._instances = self.sorted_entries(self._instances_of(fault))
        colors = self._well_colors()
        self._building = True
        self._list.clear()
        self._items = []
        ticked = 0
        for entry in self._instances:
            entry["color"] = colors[entry["well"]]
            item = QListWidgetItem(self._item_text(entry))
            item.setIcon(self.chip(entry["color"]))
            item.setToolTip(self._item_tooltip(entry))
            aligned = entry["onset"] is not None
            flags = Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsSelectable
            if aligned:
                flags |= Qt.ItemFlag.ItemIsEnabled
            item.setFlags(flags)
            if fresh:
                check = aligned and ticked < MAX_OVERLAID_INSTANCES
            else:
                check = aligned and (entry["well"], entry["position"]) in previously
            item.setCheckState(Qt.CheckState.Checked if check else Qt.CheckState.Unchecked)
            ticked += check
            self._list.addItem(item)
            self._items.append(item)
        self._building = False
        self._refresh_instance_note()

    def _item_text(self, entry: dict) -> str:
        onset = entry["onset"]
        when = f"{onset:%Y-%m-%d %H:%M}" if onset is not None else "no onset in the labels"
        mark = " ⚠" if entry["implausible"] else ""
        return f"{entry['title']}{mark} | {when}"

    def _item_tooltip(self, entry: dict) -> str:
        fault = self.fault
        reach = "" if fault == 0 else f" | {REACH_LABELS[entry['reach']]}"
        text = (
            f"{well_label(entry['well'])} | {self.info.fault_name(fault)}{reach}\n"
            f"{entry['start']:%Y-%m-%d %H:%M:%S} → {entry['end']:%Y-%m-%d %H:%M:%S} "
            f"({entry['hours']:.1f} h)"
        )
        if entry["onset"] is None:
            text += (
                f"\nThe labels never reach the {ALIGNMENT_NAMES[self.alignment].lower()}, so "
                "this instance cannot be aligned on it."
            )
        if entry["implausible"]:
            text += "\n⚠ A sensor reads outside its plausible range in this instance."
        return text + self.map_tooltip_lines(entry)

    def _rebuild_features(self) -> None:
        """Offer every sensor, greying those no instance of the fault recorded, the seabed's ticked."""
        fault = self.fault
        availability = self._availability
        for check in self._checks.values():
            self._feature_layout.removeWidget(check)
            check.deleteLater()
        self._checks = {}
        while self._feature_layout.count():
            item = self._feature_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        rows = np.flatnonzero(availability.bars["fault_class"].to_numpy() == fault)
        n = len(rows)
        recorded = {}
        for j, name in enumerate(availability.sensors):
            recorded[name] = int((availability.state[rows, j] != ABSENT).sum()) if n else 0
        # The same default for every fault (``config.DEFAULT_FEATURES``); with
        # none of it recorded, the sensor the most instances of the fault
        # recorded: the first in the alphabet is as likely as not to be one
        # none of them has, which would open the page on empty plots.
        default = {name for name in DEFAULT_FEATURES if recorded.get(name, 0) > 0}
        best = sorted(recorded, key=lambda name: (-recorded[name], name))
        default = default or {next((name for name in best if recorded[name] > 0), None)}
        for name in sorted(recorded):
            unit = self.info.shown_unit(name)
            check = QCheckBox(f"{name} [{unit}]" if unit else name)
            description = self.info.sensor_descriptions.get(name, "")
            place = placement_of(name)
            if place:
                description = f"{description} ({place.lower()})" if description else place
            count = f"recorded in {recorded[name]} of {n} instances of the fault"
            check.setToolTip(f"{description}\n{count}" if description else count)
            check.setEnabled(recorded[name] > 0)
            check.setChecked(name in default and recorded[name] > 0)
            check.toggled.connect(self._on_feature_toggled)
            self._checks[name] = check
            self._feature_layout.addWidget(check)
        self._feature_layout.addStretch(1)
        self._placements.set_checks(self._checks, "instances of the fault")

    def selected_features(self) -> list[str]:
        return [name for name, check in self._checks.items() if check.isChecked()]

    def sort_feature(self) -> str | None:
        """The descriptor orders read the first feature ticked, the one the first section draws."""
        return next(iter(self.selected_features()), None)

    def _on_feature_toggled(self, *args) -> None:
        self._placements.sync()
        # The descriptor orders name, and read, the first feature ticked.
        self._sync_sort_control()
        if self.descriptor_sort() is not None and self.ready():
            self._rebuild_instances()
        self._replot()

    def _set_all_features(self, checked: bool) -> None:
        for check in self._checks.values():
            check.blockSignals(True)
            check.setChecked(checked and check.isEnabled())
            check.blockSignals(False)
        self._on_feature_toggled()

    def _set_all_instances(self, checked: bool) -> None:
        self._building = True
        for item in self._items:
            if item.flags() & Qt.ItemFlag.ItemIsEnabled:
                item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        self._building = False
        self._replot()

    def _on_item_changed(self, item) -> None:
        if not getattr(self, "_building", False):
            self._replot()

    def _on_item_open(self, row: int) -> None:
        """A click on an instance's name opens its window, on its default features."""
        entry = self._instances[row]
        self.open_instance(entry["well"], entry["position"])

    def _checked_instances(self) -> list[dict]:
        return [
            entry
            for entry, item in zip(self._instances, self._items)
            if item.checkState() == Qt.CheckState.Checked and entry["onset"] is not None
        ]

    def _refresh_instance_note(self) -> None:
        n = len(self._instances)
        aligned = sum(1 for entry in self._instances if entry["onset"] is not None)
        drawn = len(self._checked_instances())
        parts = [f"{drawn} of {n} instances drawn"]
        if aligned < n:
            parts.append(
                f"{n - aligned} greyed out: their labels never reach the "
                f"{ALIGNMENT_NAMES[self.alignment].lower()}"
            )
        if n > MAX_OVERLAID_INSTANCES:
            parts.append(f"the earliest {MAX_OVERLAID_INSTANCES} were ticked to start with")
        if self.small_multiples and drawn > MAX_SMALL_MULTIPLES:
            parts.append(f"the grid draws the first {MAX_SMALL_MULTIPLES} of them")
        self._instance_note.setText(" | ".join(parts) + ".")
        self._note.setText(parts[0])

    # -- what the shared machinery asks of this page

    def before_replot(self) -> None:
        self._refresh_instance_note()

    def load_series(self) -> list[Series]:
        # Pooled, every instance of the fault becomes one curve per feature,
        # drawn across every well at once: the color of a well would then be
        # the color of whichever well happened to come first, so the curve
        # takes the neutral trace color instead.
        neutral = theme.current().trace if self.overall else None
        series = []
        for entry in self._checked_instances():
            data = self._wells[entry["well"]]
            frame = self._frames.get(data.rows["path"].iloc[entry["position"]])
            hours = relative_hours(frame.index, entry["onset"])
            series.append(
                Series(
                    entry["well"],
                    entry["position"],
                    entry["title"],
                    frame,
                    entry["onset"],
                    hours,
                    neutral or entry["color"],
                    int(entry["fault"]),
                    entry.get("runs", []),
                    self.model_runs_for(entry["fault"], entry.get("file", "")),
                )
            )
        return series

    def sections(self) -> list[Section]:
        """One section per feature ticked, every instance of the fault drawn in each."""
        members = list(range(len(self._series)))
        return [Section(feature, feature, feature, members) for feature in self.selected_features()]

    def read_out_features(self) -> list[str]:
        return self.selected_features()

    def empty_message(self) -> str:
        return "Tick a feature on the left to draw it."

    def series_headline(self, series: Series) -> str:
        return (
            f"{well_label(series.well)} | {series.title} | {self.info.fault_name(self.fault)} | "
            f"{ALIGNMENT_NAMES[self.alignment].lower()} at {series.onset:%Y-%m-%d %H:%M:%S}"
        )

    def pool_headline(self, members: list[int]) -> str:
        return f"{self.info.fault_name(self.fault)} | {super().pool_headline(members)}"

    def shown_source(self) -> str:
        """Where a file list from this page came from, for its provenance."""
        return f"the Faults page | {self.info.fault_name(self.fault)} | the instances ticked"

    def summary(self) -> str:
        """One line for the status bar: the fault, its instances and wells, how many are drawn."""
        fault = self.fault
        if fault is None or self._catalogue is None:
            return ""
        n = len(self._instances)
        wells = len({entry["well"] for entry in self._instances})
        aligned = sum(1 for entry in self._instances if entry["onset"] is not None)
        version = f"3W {self.info.version} | " if self.info.version else ""
        return (
            f"{version}{self.info.fault_name(fault)} | {n} real instances on {wells} wells | "
            f"{aligned} alignable at the {ALIGNMENT_NAMES[self.alignment].lower()} | "
            f"{len(self.drawn_series())} drawn "
        )

    # -- pointer

    def _on_item_entered(self, item) -> None:
        """Pointing at an instance in the list names its line."""
        try:
            position = self._items.index(item)
        except ValueError:
            return
        entry = self._instances[position]
        for i, series in enumerate(self._series):
            if series.well == entry["well"] and series.position == entry["position"]:
                self._highlight(i)
                self.status.emit(self._describe(i, None, None))
                return
        self._highlight(-1)
