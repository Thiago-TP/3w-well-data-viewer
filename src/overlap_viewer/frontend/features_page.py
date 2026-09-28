"""The features page: one sensor, across every fault class, from every well.

The faults page fixes a fault and asks what its instances did to each sensor.
This one turns the question round: it fixes a **sensor** and gives each fault
class a section, so that what a gauge reads under a hydrate can be set beside
what the same gauge reads under severe slugging and under normal operation.
That is the feature-wise grouping of the catalogue the viewer was missing (the
timelines are the well-wise one and the faults page the fault-wise one) and
the histogram of one sensor per class is the closest the viewer comes to the
pairplot diagonal a pipeline would start from.

Everything between the choice and the picture is
``series_page.SeriesPage``: the same two layouts, the same three domains, the
same window of hours around an onset, the same transforms and the same hover.

**Color.** A class is drawn in its own hue when the layout draws the classes
over one another and the line is the only key there is. In the grid it is not:
every small plot sits under a heading that names its class, so the line takes
the neutral trace color of the theme and leaves the hues to the shading of the
label periods behind it and to the stacks of a histogram, which carry that
class's hue at full strength, and which a line of the same hue would vanish
into.

**Align at** defaults to the start of the recording here, the one anchor every
class has: normal operation has no transient and no steady fault state, so
anchoring on either would silently drop every normal instance.
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
from overlap_viewer.backend.availability import ABSENT, LIVE, Availability
from overlap_viewer.backend.config import MAX_SMALL_MULTIPLES, REACH_LABELS
from overlap_viewer.backend.dataset import DatasetInfo, WellData, well_label
from overlap_viewer.backend.labels import segments_from_json
from overlap_viewer.backend.palette import fault_color
from overlap_viewer.frontend.instance_window import PANEL_WIDTH
from overlap_viewer.frontend.loading import FrameCache
from overlap_viewer.frontend.series_page import (
    LIST_WIDTH,
    InstanceList,
    Section,
    Series,
    SeriesPage,
)

HINT = (
    "One sensor: a section per fault class in the grid, every class over the others in one plot "
    "when overlaid, in the colors the list on the left keys | hover a trace to name its instance "
    "and read it, click it to open its instance window on this sensor | tick the classes on the "
    "left and the instances on the right, click an instance's name to open it | Ctrl + wheel to "
    "zoom, the wheel scrolls | F1 for help"
)

# How many instances of each class are ticked when the page opens, or when the
# sensor or the well changes. Enough to show the spread of a class without
# opening a file per instance of a dataset that holds thousands.
DEFAULT_PER_CLASS = 4

FEATURE_TIP = (
    "The sensor every plot draws. The count beside a name is how many real instances recorded "
    "it at all; a sensor no instance recorded is greyed out."
)
WELL_TIP = (
    "Narrow the page to one well, so that the classes are compared at one place and one set of "
    "instruments, rather than across wells that run at different levels."
)
DOMAIN_TIP = (
    "What every plot shows of the stretch the hours before and after the onset select. Time "
    "series: the readings against the hours from the onset. Distribution: a histogram of the "
    "readings, as a share of the instance's samples so that instances of different length "
    "compare, stacked by label period in the class colors in the grid, an area in the color of "
    "its class when overlaid, so that where two classes sit on top of one another reads as a "
    "deeper shade, with a triangle over the fullest bin of each. Spectrum: the power spectral "
    "density against the period, both logarithmic, the mean and the trend removed first."
)
LAYOUT_TIP = (
    "Small multiples give every instance a plot of its own, in a grid under a heading per fault "
    "class, so that the shapes of one class can be read one against the next and against the "
    "class below. Overlaid draws every class on one set of axes, each instance in the color of "
    "its class, which is what makes the classes comparable rather than merely adjacent, and the "
    "natural view for histograms and spectra, where the question is whether the classes sit at "
    "different values or peak at different periods. Overall goes one further and pools each "
    "class into a single curve, so the plot becomes one distribution, or one spectrum, per fault "
    "class over every instance of it, the feature-level view this page was built for. It is "
    "offered off the time axis only, instances cut from different months having no common clock."
)
NORMALIZE_TIP = (
    "Scale every series to its own level: each reading as standard deviations from the mean of "
    "that sensor over the whole instance. Wells run at different levels, and with the classes of "
    "several wells in one section it is the shape of each that is being compared, not the level."
)
ALIGN_NOTE = (
    "Normal operation has no transient and no steady fault state, so anchoring on either leaves "
    "every normal instance greyed out; the start of the recording is the one anchor every class "
    "has."
)


class FeaturesPage(SeriesPage):
    """One sensor in the toolbar, fault classes left, plots center, instances right."""

    HINT = HINT

    def __init__(self, info: DatasetInfo, frames: FrameCache, passes=None, parent=None):
        super().__init__(info, passes, parent)
        self._frames = frames
        self._catalogue: pd.DataFrame | None = None
        self._wells: dict[int, WellData] = {}
        self._availability: Availability | None = None
        self._instances: list[dict] = []
        self._items: list[QListWidgetItem] = []
        self._class_checks: dict[int, QCheckBox] = {}
        self._recorded: dict[str, int] = {}
        self._building = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self._build_toolbar())
        layout.addWidget(self.build_parameter_bar(NORMALIZE_TIP))
        self._class_panel = self._build_class_panel()
        self._instance_panel = self._build_instance_panel()
        layout.addWidget(self.build_body(self._class_panel, self._instance_panel), 1)
        # Every class has a start; not every class has an onset (see ALIGN_NOTE).
        self._align.setCurrentIndex(ALIGNMENTS.index("start"))
        self._restyle()

    # -- construction

    def _build_toolbar(self) -> QToolBar:
        bar = QToolBar("Features")
        bar.setMovable(False)
        bar.addWidget(QLabel(" Feature "))
        self._feature = QComboBox()
        self._feature.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self._feature.setToolTip(FEATURE_TIP)
        self._feature.currentIndexChanged.connect(self._on_feature_changed)
        bar.addWidget(self._feature)

        bar.addWidget(QLabel(" Well "))
        self._well = QComboBox()
        self._well.setToolTip(WELL_TIP)
        self._well.currentIndexChanged.connect(self._on_well_changed)
        bar.addWidget(self._well)

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
        self._show_classes = QAction("Classes", self)
        self._show_classes.setCheckable(True)
        self._show_classes.setChecked(True)
        self._show_classes.setToolTip(
            "Show or hide the list of fault classes on the left, to give the plots its width"
        )
        self._show_classes.toggled.connect(lambda on: self._class_panel.setVisible(on))
        bar.addAction(self._show_classes)
        self._show_instances = QAction("Instances", self)
        self._show_instances.setCheckable(True)
        self._show_instances.setChecked(True)
        self._show_instances.setToolTip(
            "Show or hide the list of instances on the right, to give the plots its width"
        )
        self._show_instances.toggled.connect(lambda on: self._instance_panel.setVisible(on))
        bar.addAction(self._show_instances)
        return bar

    def _build_class_panel(self) -> QWidget:
        panel = QWidget()
        panel.setFixedWidth(PANEL_WIDTH)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel("<b>Fault classes</b>"))
        buttons = QVBoxLayout()
        buttons.setSpacing(2)
        clear = QPushButton("Clear")
        clear.clicked.connect(lambda: self._set_all_classes(False))
        every = QPushButton("All")
        every.clicked.connect(lambda: self._set_all_classes(True))
        buttons.addWidget(clear)
        buttons.addWidget(every)
        layout.addLayout(buttons)
        self._class_scroll = QScrollArea()
        self._class_scroll.setWidgetResizable(True)
        self._class_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._class_box = QWidget()
        self._class_layout = QVBoxLayout(self._class_box)
        self._class_layout.setContentsMargins(0, 0, 0, 0)
        self._class_layout.setSpacing(2)
        self._class_scroll.setWidget(self._class_box)
        layout.addWidget(self._class_scroll, 1)
        self._class_note = QLabel(
            "Each class ticked gets a section of its own. Greyed-out classes have no instance "
            "that recorded this sensor."
        )
        self._class_note.setWordWrap(True)
        layout.addWidget(self._class_note)
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
            self._rebuild_instances(fresh=False)

    def on_sort_changed(self, *args) -> None:
        if self.ready():
            self._rebuild_instances(fresh=False)

    # -- appearance

    def _restyle(self) -> None:
        colors = theme.current()
        self._restyle_plots()
        for note in (self._class_note, self._instance_note, self._note):
            note.setStyleSheet(f"color: {colors.muted}; font-size: 8pt;")

    def apply_theme(self) -> None:
        """Take the colors of the theme now in force; ``set_catalogue`` redraws the plots after it."""
        self._restyle()

    # -- data

    def set_catalogue(self, catalogue: pd.DataFrame, wells: list[WellData]) -> None:
        """Take a new catalogue and its wells; the sensor and the well chosen stay chosen.

        The very same catalogue again is a theme switch: the lists are written
        again for their class colors and the plots drawn again for theirs, with
        the classes and instances ticked and every plot's zoom kept.
        """
        if catalogue is self._catalogue and self.ready():
            self._wells = {well.well: well for well in wells}
            self._rebuild_classes()
            self._rebuild_instances(fresh=False)
            self._replot(keep_views=True)
            return
        self._catalogue = catalogue
        self._wells = {well.well: well for well in wells}
        self._availability = Availability.from_wells(wells, self.info)
        self._recorded = self._recorded_counts()

        wanted_well = self._well.currentData()
        self._well.blockSignals(True)
        self._well.clear()
        self._well.addItem("All wells", None)
        for well in sorted(self._wells):
            self._well.addItem(well_label(well), well)
        index = self._well.findData(wanted_well)
        self._well.setCurrentIndex(max(index, 0))
        self._well.blockSignals(False)

        wanted = self._feature.currentData()
        self._feature.blockSignals(True)
        self._feature.clear()
        for name in self._availability.sensors:
            count = self._recorded.get(name, 0)
            self._feature.addItem(f"{name} ({count})", name)
            item = self._feature.model().item(self._feature.count() - 1)
            item.setEnabled(count > 0)
            unit = self.info.shown_unit(name)
            description = self.info.sensor_descriptions.get(name, "")
            item.setToolTip(
                f"{name}{f' [{unit}]' if unit else ''}\n{description}\n"
                f"recorded in {count} real instances"
            )
        index = self._feature.findData(wanted)
        if index < 0:
            index = self._feature.findData(self._best_feature())
        self._feature.setCurrentIndex(max(index, 0))
        self._feature.blockSignals(False)

        self._sync_sort_control()  # the descriptor orders name the feature chosen
        self._rebuild_classes()
        self._rebuild_instances(fresh=True)
        self._replot(keep_range=False)

    def _recorded_counts(self) -> dict[str, int]:
        """How many real instances carry a reading of each sensor at all."""
        availability = self._availability
        return {
            name: int((availability.state[:, j] != ABSENT).sum())
            for j, name in enumerate(availability.sensors)
        }

    def _best_feature(self) -> str | None:
        """The measuring sensor the most instances recorded a moving reading of.

        Two things have to be kept out of the way of the default. A valve state
        is carried by nearly every instance and is counted *live* even while it
        holds one position for a whole recording (that is a fact about the
        well, not a frozen gauge), so the plainest count opens the page on a
        row of flat lines whose spectrum declines every one of them. And a
        gauge that is present but frozen says as little. So: the measuring
        variables first, ranked by how many instances they are live in.
        """
        availability = self._availability
        live = {
            name: int((availability.state[:, j] == LIVE).sum())
            for j, name in enumerate(availability.sensors)
        }
        best = sorted(live, key=lambda name: (self.info.is_enumerated(name), -live[name], name))
        return next(
            (name for name in best if live[name] > 0),
            next((name for name in sorted(self._recorded) if self._recorded[name] > 0), None),
        )

    @property
    def feature(self) -> str | None:
        data = self._feature.currentData()
        return None if data is None else str(data)

    @property
    def well_filter(self) -> int | None:
        return self._well.currentData()

    def ready(self) -> bool:
        return self._availability is not None and self.feature is not None

    def sort_feature(self) -> str | None:
        """The descriptor orders read the feature on show."""
        return self.feature

    def _on_feature_changed(self, *args) -> None:
        if not self.ready():
            return
        self._sync_sort_control()  # the descriptor orders name the feature
        self._rebuild_classes()
        self._rebuild_instances(fresh=True)
        self._replot(keep_range=False)

    def _on_well_changed(self, *args) -> None:
        if not self.ready():
            return
        self._rebuild_classes()
        self._rebuild_instances(fresh=True)
        self._replot(keep_range=False)

    def _on_alignment_changed(self, *args) -> None:
        # The page sets its own default anchor while it is still being built,
        # before there is a catalogue to list instances from.
        if not self.ready():
            return
        self._rebuild_instances(fresh=False)
        self._replot(keep_range=False)

    # -- the fault classes on the left

    def _classes_present(self) -> list[int]:
        """Every fault class in the catalogue, in folder order."""
        if self._catalogue is None:
            return []
        return sorted(int(fault) for fault in self._catalogue["fault_class"].unique())

    def _class_counts(self) -> dict[int, int]:
        """Per class, how many of its instances recorded the sensor chosen, under the well filter."""
        availability, feature = self._availability, self.feature
        counts = {fault: 0 for fault in self._classes_present()}
        if availability is None or feature is None:
            return counts
        column = availability.sensors.index(feature)
        bars = availability.bars
        faults = bars["fault_class"].to_numpy()
        wells = bars["well"].to_numpy()
        recorded = availability.state[:, column] != ABSENT
        chosen = self.well_filter
        for fault in counts:
            rows = (faults == fault) & recorded
            if chosen is not None:
                rows &= wells == chosen
            counts[fault] = int(rows.sum())
        return counts

    def _rebuild_classes(self) -> None:
        """Offer every fault class, greying those with no instance of the sensor chosen."""
        wanted = {fault for fault, check in self._class_checks.items() if check.isChecked()}
        fresh = not self._class_checks
        for check in self._class_checks.values():
            check.deleteLater()
        self._class_checks = {}
        while self._class_layout.count():
            item = self._class_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        counts = self._class_counts()
        for fault, count in counts.items():
            check = QCheckBox(f"{fault}. {self.info.fault_name(fault)} ({count})")
            check.setIcon(self.chip(fault_color(fault)))
            check.setToolTip(
                f"{self.info.fault_name(fault)}: {count} real instances recorded "
                f"{self.feature}{' at this well' if self.well_filter is not None else ''}"
            )
            check.setEnabled(count > 0)
            check.setChecked(count > 0 and (fresh or fault in wanted))
            check.toggled.connect(self._on_class_toggled)
            self._class_checks[fault] = check
            self._class_layout.addWidget(check)
        self._class_layout.addStretch(1)

    def selected_classes(self) -> list[int]:
        return [fault for fault, check in self._class_checks.items() if check.isChecked()]

    def _on_class_toggled(self, *args) -> None:
        self._rebuild_instances(fresh=True)
        self._replot(keep_range=False)

    def _set_all_classes(self, checked: bool) -> None:
        for check in self._class_checks.values():
            check.blockSignals(True)
            check.setChecked(checked and check.isEnabled())
            check.blockSignals(False)
        self._on_class_toggled()

    # -- the instances on the right

    def _instances_of(self) -> list[dict]:
        """Every real instance of a ticked class that recorded the sensor, by class then by well."""
        availability, feature = self._availability, self.feature
        column = availability.sensors.index(feature)
        chosen_well = self.well_filter
        found = []
        for fault in self.selected_classes():
            for well in sorted(self._wells):
                if chosen_well is not None and well != chosen_well:
                    continue
                data = self._wells[well]
                rows = data.rows
                for position in np.flatnonzero(rows["fault_class"].to_numpy() == fault).tolist():
                    row = availability.index_of(well, position)
                    if availability.state[row, column] == ABSENT:
                        continue  # nothing of this sensor here: never worth a read
                    entry = rows.iloc[position]
                    runs = (
                        segments_from_json(str(entry["class_runs"]))
                        if "class_runs" in rows.columns
                        else []
                    )
                    found.append(
                        {
                            "fault": fault,
                            "well": well,
                            "position": position,
                            "file": str(entry["file"]) if "file" in rows.columns else "",
                            "title": str(entry["file"]).rsplit(".", 1)[0]
                            if "file" in rows.columns
                            else str(entry["title"]),
                            "reach": str(entry["reach"]),
                            "start": pd.Timestamp(entry["start"]),
                            "end": pd.Timestamp(entry["end"]),
                            "hours": float(entry["hours"]),
                            "onset": onset_from_runs(
                                runs, fault, self.info.transient_offset, self.alignment
                            ),
                            "runs": runs,
                            "implausible": bool(availability.implausible[row, column]),
                        }
                    )
        return found

    def _rebuild_instances(self, fresh: bool) -> None:
        """List the instances, the earliest few of each class ticked when the question changed."""
        previously = {
            (entry["fault"], entry["well"], entry["position"])
            for entry, item in zip(self._instances, self._items)
            if item.checkState() == Qt.CheckState.Checked
        }
        self._instances = self.sorted_entries(self._instances_of())
        self._building = True
        self._list.clear()
        self._items = []
        per_class: dict[int, int] = {}
        for entry in self._instances:
            item = QListWidgetItem(self._item_text(entry))
            item.setIcon(self.chip(fault_color(entry["fault"])))
            item.setToolTip(self._item_tooltip(entry))
            aligned = entry["onset"] is not None
            flags = Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsSelectable
            if aligned:
                flags |= Qt.ItemFlag.ItemIsEnabled
            item.setFlags(flags)
            if fresh:
                # The earliest few of each class rather than the earliest few
                # overall: a class whose instances all come later would
                # otherwise open with nothing in its section.
                taken = per_class.get(entry["fault"], 0)
                check = aligned and taken < DEFAULT_PER_CLASS
                per_class[entry["fault"]] = taken + check
            else:
                check = aligned and (
                    (entry["fault"], entry["well"], entry["position"]) in previously
                )
            item.setCheckState(Qt.CheckState.Checked if check else Qt.CheckState.Unchecked)
            self._list.addItem(item)
            self._items.append(item)
        self._building = False
        self._refresh_instance_note()

    def _item_text(self, entry: dict) -> str:
        onset = entry["onset"]
        when = f"{onset:%Y-%m-%d %H:%M}" if onset is not None else "no onset in the labels"
        mark = " ⚠" if entry["implausible"] else ""
        return f"{entry['fault']}. {entry['title']}{mark} | {when}"

    def _item_tooltip(self, entry: dict) -> str:
        fault = entry["fault"]
        reach = "" if fault == 0 else f" | {REACH_LABELS[entry['reach']]}"
        text = (
            f"{well_label(entry['well'])} | {self.info.fault_name(fault)}{reach}\n"
            f"{entry['start']:%Y-%m-%d %H:%M:%S} → {entry['end']:%Y-%m-%d %H:%M:%S} "
            f"({entry['hours']:.1f} h)"
        )
        if entry["onset"] is None:
            text += (
                f"\nThe labels never reach the {ALIGNMENT_NAMES[self.alignment].lower()}, so "
                f"this instance cannot be aligned on it. {ALIGN_NOTE}"
            )
        if entry["implausible"]:
            text += f"\n⚠ {self.feature} reads outside its plausible range in this instance."
        return text + self.map_tooltip_lines(entry)

    def _on_item_changed(self, item) -> None:
        if not self._building:
            self._replot()

    def _on_item_open(self, row: int) -> None:
        """A click on an instance's name opens its window, on its default features."""
        entry = self._instances[row]
        self.open_instance(entry["well"], entry["position"])

    def _set_all_instances(self, checked: bool) -> None:
        self._building = True
        for item in self._items:
            if item.flags() & Qt.ItemFlag.ItemIsEnabled:
                item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        self._building = False
        self._replot()

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
        classes = len(self.selected_classes())
        parts = [f"{drawn} of {n} instances drawn, in {classes} classes"]
        if aligned < n:
            parts.append(
                f"{n - aligned} greyed out: their labels never reach the "
                f"{ALIGNMENT_NAMES[self.alignment].lower()}"
            )
        if n > drawn and drawn:
            parts.append(
                f"the earliest {DEFAULT_PER_CLASS} of each class were ticked to start with"
            )
        limit = self._per_section_limit()
        if self.small_multiples and any(
            sum(1 for entry in self._checked_instances() if entry["fault"] == fault) > limit
            for fault in self.selected_classes()
        ):
            # Only where it bites: the cap is spent per class, so it is silent
            # until one class is ticked past its share of the grid.
            parts.append(f"the grid draws the first {limit} of each class")
        self._instance_note.setText(" | ".join(parts) + ".")
        self._note.setText(parts[0])

    # -- what the shared machinery asks of this page

    def before_replot(self) -> None:
        self._refresh_instance_note()

    def _per_section_limit(self) -> int:
        """How many instances of one class a grid draws, so that every class gets a share of it.

        The faults page caps the grid at the first few dozen instances of the
        one fault it draws; here the cap has to be spent per class, or the last
        classes of a long list would come out empty while the first filled the
        screen.
        """
        classes = max(len(self.selected_classes()), 1)
        return max(1, MAX_SMALL_MULTIPLES // classes)

    def _drawn_members(self, section: Section) -> list[int]:
        if not self.small_multiples:
            return list(section.members)
        return section.members[: self._per_section_limit()]

    def load_series(self) -> list[Series]:
        # In the grid every plot holds one instance under a heading naming its
        # class, so the line carries nothing the heading does not and takes the
        # neutral trace color; the class hues are left to the shading behind it
        # and to the stacks of a histogram, which carry that class's hue at
        # full strength and which a line of the same hue would vanish into.
        # Overlaid, every class is in one plot and the line is the only key
        # there is, so it takes its class's hue.
        neutral = theme.current().trace if self.small_multiples else None
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
                    neutral or fault_color(entry["fault"]),
                    int(entry["fault"]),
                    entry.get("runs", []),
                    self.model_runs_for(entry["fault"], entry.get("file", "")),
                )
            )
        return series

    def sections(self) -> list[Section]:
        """The grid: one section per class. Overlaid: one plot, every class in it.

        A section becomes one plot when the layout is *Overlaid*, so a section
        per class would draw each class on a set of axes of its own, where
        every curve carries that class's color and the color therefore says
        nothing: the reader is comparing instances inside one class, and the
        key has told them nothing. Overlaying is worth doing here precisely
        *across* the classes: one histogram, or one set of spectra, with the
        classes over one another in their own hues, which is the question the
        page was asked for. So the overlay folds them into a single section and
        the color becomes the key, read off the list of classes on the left.
        """
        feature = self.feature
        if feature is None or not self._series:
            return []
        if not self.small_multiples:
            return [Section(feature, feature, feature, list(range(len(self._series))))]
        members: dict[int, list[int]] = {fault: [] for fault in self.selected_classes()}
        for i, series in enumerate(self._series):
            members.setdefault(series.fault, []).append(i)
        return [
            Section(fault, feature, f"{fault}. {self.info.fault_name(fault)}", members[fault])
            for fault in self.selected_classes()
            if members.get(fault)
        ]

    def pool_key(self, series: Series):
        """Pooled, a class becomes one curve: telling the classes apart is what the page is for."""
        return series.fault

    def shown_source(self) -> str:
        """Where a file list from this page came from, for its provenance."""
        classes = ", ".join(str(c) for c in self.selected_classes())
        well = self._well.currentText()
        return f"the Features page | {self.feature} | classes {classes} | {well} | the instances ticked"

    def pool_headline(self, members: list[int]) -> str:
        fault = self._series[members[0]].fault
        return (
            f"{fault}. {self.info.fault_name(fault)} | {self.feature} | "
            f"{SeriesPage.pool_headline(self, members)}"
        )

    def read_out_features(self) -> list[str]:
        feature = self.feature
        return [feature] if feature else []

    def empty_message(self) -> str:
        if not self.selected_classes():
            return "Tick a fault class on the left to draw it."
        return "No instance of the classes ticked is aligned and recorded this sensor."

    def section_note(self, section: Section, drawn: int, total: int) -> str:
        whole = len([i for i in section.members])
        if drawn == whole:
            return ""
        return f" | {whole - drawn} more ticked, beyond what this layout draws"

    def series_headline(self, series: Series) -> str:
        return (
            f"{well_label(series.well)} | {series.title} | "
            f"{self.info.fault_name(series.fault)} | {self.feature} | "
            f"{ALIGNMENT_NAMES[self.alignment].lower()} at {series.onset:%Y-%m-%d %H:%M:%S}"
        )

    def summary(self) -> str:
        """One line for the status bar: the sensor, the classes it is drawn over, what is on show."""
        feature = self.feature
        if feature is None or self._catalogue is None:
            return ""
        version = f"3W {self.info.version} | " if self.info.version else ""
        unit = self.info.shown_unit(feature)
        where = "" if self.well_filter is None else f" | {well_label(self.well_filter)}"
        return (
            f"{version}{feature}{f' [{unit}]' if unit else ''}{where} | recorded in "
            f"{self._recorded.get(feature, 0)} real instances | "
            f"{len(self.selected_classes())} classes | {len(self._series)} drawn "
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
