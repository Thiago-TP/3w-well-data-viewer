"""What the faults page and the features page both are: sections of instances, in a chosen domain.

The two pages ask the same question with the roles of *fault* and *feature*
swapped. The faults page fixes a fault class and gives each **feature** a
section, every instance of that fault drawn inside it in the color of its well;
the features page fixes a sensor and gives each **fault class** a section, the
instances of that class drawn inside it in the color of the class. Everything
between the choice and the picture is the same: the same three arrangements,
the same three domains, the same window of hours around an onset, the same
normalization, the same transforms, the same hover.

So that machinery lives here, and a page supplies only what differs: which
instances it reads, what a section is, what color a series takes and what the
status bar should call it. A *section* is a heading, the sensor its plots draw,
and the instances that belong in it; the layouts below know nothing else about
why those instances are together.

Three arrangements, chosen in the *Layout* box. **Small multiples** give every
instance a small plot of its own, laid out in a grid, each with its own value
axis and its label periods shaded behind the trace: two dozen shapes can be
read at a glance, and the eye compares them one against the next. **Overlaid**
draws them all on one set of axes, which says how far apart the levels are and
little else once there are more than a handful, the reason the grid is the
default. **Overall** is not a third placement but a reduction before them: the
instances of a group are pooled into one curve, and the overlaid arrangement
draws the result. It is offered off the time axis only; there is no common
clock to draw a pooled time series against.

Each series can be scaled to its own level (a z-score over the instance, as
Rabelo's pipeline does) so that shapes can be compared where the readings
themselves cannot.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from math import ceil

import numpy as np
import pandas as pd
import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QCursor, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from overlap_viewer.algorithms.faults import (
    ALIGNMENT_AXES,
    ALIGNMENT_NAMES,
    ALIGNMENTS,
    plausible_extent,
    relative_hours,
    window_mask,
    zscore,
)
from overlap_viewer.algorithms.interpolation import GENUINE, MISSING, sample_kinds
from overlap_viewer.algorithms.spectral import (
    Histogram,
    Spectrum,
    average_spectra,
    format_period,
    histogram,
    lomb_scargle,
    prepare,
    prepare_irregular,
    welch,
)
from overlap_viewer.backend import theme
from overlap_viewer.backend.config import MAX_SMALL_MULTIPLES
from overlap_viewer.backend.dataset import (
    DatasetInfo,
    WellData,
    join_groups,
    merge_instances,
    well_label,
)
from overlap_viewer.backend.labels import (
    Segment,
    at_index_unit,
    column_as_float,
    label_fault,
    label_kind,
    label_name,
    padded_range,
    state_name,
)
from overlap_viewer.backend.palette import background_color, bar_color, tint, unknown_background
from overlap_viewer.backend.profiles import (
    DESCRIPTOR_CHOICES,
    DESCRIPTOR_MODES,
    GRID_CAVEAT,
    DescriptorChoice,
    descriptor_column,
)
from overlap_viewer.frontend.instance_window import AXIS_WIDTH, PlotStack
from overlap_viewer.frontend.items import (
    AnchoredText,
    HeaderLabel,
    ScrollFriendlyViewBox,
    SegmentsItem,
)
from overlap_viewer.frontend.spectral_items import (
    TransformControls,
    add_center_lines,
    add_peak_marker,
    add_spectrum_curve,
    add_stacked_bars,
    add_step_outline,
    caption_for,
    histogram_fill,
    power_axis,
    power_label,
    set_log_period_axis,
    shade_implausible,
    shade_unresolved,
    spectrum_grid,
    spectrum_xy,
)
from overlap_viewer.frontend.traces import Trace, add_trace

# The three arrangements of the same sections. *Overall* is not a third way of
# placing the plots but a reduction before them: the instances of a group are
# pooled into one curve, which the overlaid arrangement then draws. It says
# nothing in the time domain (the instances are cut from different months, and
# a pooled time series would be a line across a calendar of gaps), so it is
# greyed there.
LAYOUTS = ("Small multiples", "Overlaid", "Overall")
VALUE_AXES = ("Per instance", "Shared")
# What every plot shows of the stretch selected: the readings against time, their
# distribution, or their spectrum.
DOMAINS = ("time", "distribution", "spectrum")
DOMAIN_NAMES = {"time": "Time series", "distribution": "Distribution", "spectrum": "Spectrum"}
HIST_KINDS = ("normal", "transient", "steady", "unknown")

ALIGN_TIP = (
    "Where the time axis of every instance starts: the first sample labeled with the transient of "
    "its fault, the first labeled with its steady state, or the first sample of the recording. An "
    "instance whose labels never reach the state chosen cannot be aligned on it and is left out, "
    "greyed in the list."
)
JOIN_TIP = (
    "Before pooling, read the instances of a well that overlap in time as the single recording "
    "they were cut from, wherever their labels agree on the shared stretch. Without it the "
    "samples two windows share are counted twice, which inflates a histogram exactly where a "
    "well was recorded twice; with it every instant is counted once, and a sensor one window "
    "missed is filled in by the window it overlaps. Instances whose labels disagree there stay "
    "apart, as they do everywhere else in the viewer."
)
# Why the box is greyed: off the time axis nothing is drawn against the hours
# from the onset, and with both hour boxes at *all* the whole recording is
# transformed whatever the anchor, so the choice has nothing left to change.
ALIGN_MOOT_TIP = (
    "The anchor only reaches a distribution or a spectrum through the stretch the hours before "
    "and after it select, and both hour boxes are at 'all', so the whole recording is transformed "
    "whichever moment it is aligned on. Ask for hours around the onset, or go back to the time "
    "series, to choose it again."
)
# How the instance lists can be ordered. The two map orders wait for the
# Instances map to have computed something on the instances; the model order
# for a set of model outputs to be loaded.
SORTS = (
    "Well and start",
    "Typicality (Instances map)",
    "Novelty score (Instances map)",
    "Agreement with the model outputs",
    *(choice.name for choice in DESCRIPTOR_CHOICES),
)
FIRST_DESCRIPTOR_SORT = (
    4  # the descriptor orders follow the four above, in DESCRIPTOR_CHOICES order
)
SORT_TIP = (
    "The order of the list: by well and start, as the catalogue is; by typicality, the most "
    "typical instance of its class first (its distance to the medoid of the class on the "
    "Instances map, in the representation chosen there); by the one-class model's score, the "
    "instance that looks most anomalous first; by the agreement of the loaded model outputs "
    "with the labels, the instance the model disagrees with most first; or by one descriptor of "
    "the feature on show (the time its autocorrelation takes to halve, its signal-to-noise "
    "ratio, the slope of Zhang's Gaussianity regression, its skewness or its kurtosis, Melo's "
    "characterisation of a variable), largest first, taken on the grid or on the measurements "
    "as the box beside says. The two map orders are offered once the map has been computed on "
    "the instances (not on the joined bars), the model order once outputs are loaded, the "
    "descriptor orders once a feature is on show (the first look reads every instance in full, "
    "behind a progress dialog, and keeps the result in the cache), and the tooltip of every "
    "instance then carries the figures."
)
SORT_MODE_TIP = (
    "What the descriptor is taken over. Interpolated: the whole 1 Hz grid, most of whose samples "
    "the historian drew between the readings it archived, which is what a pipeline reads. "
    f"Measurements: the readings alone. {GRID_CAVEAT.capitalize()}."
)
# What shades the label periods behind a small plot: the experts' labels, or
# the loaded model's verdicts in the same vocabulary.
SHADINGS = ("Dataset labels", "Model outputs")
SHADING_TIP = (
    "What shades the label periods behind every small plot: the class labels the experts gave, "
    "or the verdicts of the model outputs loaded (a detector's 'anomalous' drawn as the "
    "instance's own fault, its 'normal' as normal operation; a classifier's classes as "
    "themselves), so that where the model and the experts differ shows as a shading that does "
    "not match the trace's list entry. Offered once model outputs are loaded."
)
PLOT_PX = 230  # height of one overlaid section plot
SMALL_PLOT_PX = 132  # height of one small multiple
SMALL_AXIS_WIDTH = 48  # every small plot keeps this width for its left axis, so the grid aligns
SMALL_AXIS_PX = 26  # the time axis under the last row of a grid section
SECTION_PX = 22  # the heading above one section's grid
LIST_WIDTH = 380  # the instances panel: room for a title, the mark and an onset
CHIP_PX = 12  # the square of a series color before an instance
HOVER_PX = 10  # a line closer than this to the pointer, in pixels, is the one named
FADE_ALPHA = 70  # the other lines while one is named
DEFAULT_COLUMNS = 1  # small plots per row of the grid, until the user asks for more


def sample_counts(y: np.ndarray, kinds: np.ndarray | None) -> tuple[int, int | None]:
    """How many samples of one series carry a reading, and how many of those were measured.

    Counted on the kinds when there are some, since a normalized series has
    already had its implausible readings blanked; ``None`` measurements for an
    enumerated variable, which is not tested.
    """
    if kinds is None:
        return int((~np.isnan(y)).sum()), None
    return int((kinds != MISSING).sum()), int((kinds == GENUINE).sum())


class InstanceList(QListWidget):
    """The list of instances beside the plots: its check boxes draw, its names open.

    A click on an instance's check box ticks or unticks it, as in any list; a
    click anywhere else on its row asks for its instance window. The two are
    told apart by whether the click changed the check state, which leaves the
    question of where the box is drawn to the style that draws it. A greyed
    instance, which cannot be ticked, can still be opened.

    Signals
    -------
    open_requested(int)
        The row whose name was clicked.
    """

    open_requested = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pressed = None
        self._double = False

    def mousePressEvent(self, event) -> None:
        self._pressed = self.itemAt(event.position().toPoint())
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        # The release that ends a double click would open the window a second time.
        self._double = True
        super().mouseDoubleClickEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        item = self.itemAt(event.position().toPoint())
        before = item.checkState() if item is not None else None
        super().mouseReleaseEvent(event)
        double, self._double = self._double, False
        if (
            item is not None
            and item is self._pressed
            and event.button() == Qt.MouseButton.LeftButton
            and not double
            and item.checkState() == before
        ):
            self.open_requested.emit(self.row(item))
        self._pressed = None


@dataclass
class Series:
    """One instance as drawn: which it is, its frame, where it is aligned, its hours and color."""

    well: int
    position: int  # in the well's instance table
    title: str
    frame: pd.DataFrame
    onset: pd.Timestamp
    hours: np.ndarray
    color: str
    fault: int = 0  # the fault class of the instance itself, for its shading
    runs: list[Segment] = field(default_factory=list)  # its label runs, for the shading
    # The loaded model's verdicts on it, as label runs in the dataset's vocabulary.
    model_runs: list[Segment] = field(default_factory=list)

    @property
    def label(self) -> str:
        """What a small plot writes in its corner: the well and the day it was aligned on.

        Short enough to sit inside a plot a seventh of a window wide; the list
        on the right carries the filename and the hour.
        """
        return f"{well_label(self.well)} | {self.onset:%Y-%m-%d}"


@dataclass
class Section:
    """One heading and the plots under it: a sensor, and the instances drawn of it.

    ``key`` is whatever the page groups by (a sensor name on the faults page,
    a fault class on the features page) and is only ever passed back to the
    page that made it. ``members`` are positions in the page's series.
    """

    key: object
    feature: str
    title: str
    members: list[int]


def merge_overlapping(series: list[Series], group_of) -> list[Series]:
    """Read the instances of a well that overlap in time as the single recording they were cut from.

    Only ever within one well and one group: two windows of different wells
    share no instant, and two of different fault classes are being counted
    apart on purpose. Inside that, the rule is the viewer's own: the groups
    are ``dataset.join_groups``, so windows whose labels disagree where they
    overlap stay apart, and the frames are merged by ``merge_instances``, so
    every instant is kept once and what one window says nothing about the
    others fill in.

    This is what keeps a pooled histogram from counting the samples two
    windows share twice, which would inflate it at exactly the levels a well
    was recorded twice at.
    """
    merged: list[Series] = []
    order: dict = {}
    for i, one in enumerate(series):
        order.setdefault((group_of(one), one.well), []).append(i)
    for members in order.values():
        if len(members) == 1:
            merged.append(series[members[0]])
            continue
        parts = [series[i] for i in members]
        starts = np.array([part.frame.index[0] for part in parts], dtype="datetime64[ns]")
        ends = np.array([part.frame.index[-1] for part in parts], dtype="datetime64[ns]")
        for group in join_groups(starts, ends, [part.runs for part in parts]):
            chain = [parts[k] for k in group]
            if len(chain) == 1:
                merged.append(chain[0])
                continue
            frame = merge_instances([part.frame for part in chain])
            head = chain[0]
            merged.append(
                Series(
                    head.well,
                    head.position,
                    f"{len(chain)} instances joined",
                    frame,
                    head.onset,
                    relative_hours(frame.index, head.onset),
                    head.color,
                    head.fault,
                    [],
                )
            )
    return merged


class SeriesPage(QWidget):
    """Sections of instances, drawn in one of three domains and one of two layouts.

    Subclasses build their own first toolbar row (calling ``add_shared_controls``
    for the part every page has), own the panels left and right of the plots,
    and answer four questions: which instances to read (``load_series``), how
    they group into sections (``sections``), what the status bar should call one
    of them (``series_headline``) and what its heading should note
    (``section_note``).

    Signals
    -------
    status(str)
        What the main window's status bar should say: the instance under the
        pointer and its reading, or the page's hint.
    summary_changed()
        The one-line count of what is on show has changed.
    open_requested(WellData, int, object)
        Open the instance window of one instance: its well, its position in
        the well's instance table, and the sensor to draw in it, or ``None``
        for the window's own default.
    """

    status = Signal(str)
    summary_changed = Signal()
    open_requested = Signal(object, int, object)

    HINT = ""

    def hint(self) -> str:
        """What the status bar says when the pointer is over nothing in particular."""
        return self.HINT

    def __init__(self, info: DatasetInfo, passes=None, parent=None):
        super().__init__(parent)
        self.info = info
        # Where the profiles of the instances come from, when a sort order asks
        # for them; without it the descriptor orders are not offered.
        self._passes = passes
        self._wells: dict[int, WellData] = {}
        self._series: list[Series] = []
        self._plots: list[pg.PlotItem] = []
        self._plot_features: list[str] = []  # per plot: the sensor it draws
        self._curves: dict[int, list[pg.PlotDataItem]] = {}  # series index -> its curve per plot
        self._plot_series: list[
            list[tuple[int, np.ndarray, np.ndarray]]
        ] = []  # per plot: (series, x, y)
        self._spectra_by_plot: dict[tuple[int, int], Spectrum] = {}  # (plot, series) -> spectrum
        # (plot, series) -> the fullest bin of its histogram and its share, for
        # the marker on the plot and the reading in the status bar.
        self._peaks_by_plot: dict[tuple[int, int], tuple[float, float]] = {}
        # Per section, the ``sample_counts`` of every instance the grid draws off the time axis.
        self._section_counts: dict[object, list[tuple[int, int | None]]] = {}
        # While the instances are pooled: the series that stands for a group,
        # and the ones it stands for, so the status bar can say so.
        self._pool: dict[int, list[int]] = {}
        self._hover = -1
        self._x_range: tuple[float, float] | None = None
        self._map_results = None  # what the Instances map computed, once it has
        self._model_results = None  # the model outputs loaded, once they are
        self._sort: QComboBox | None = None
        self._sort_mode: QComboBox | None = None
        self._sort_mode_label: QLabel | None = None
        self._shading: QComboBox | None = None
        self._shading_actions: list = []

    # -- construction, the parts every page shares

    def add_instance_buttons(self, layout) -> None:
        """*All* and *Clear* over an instance list, stacked as over the list on the left."""
        buttons = QVBoxLayout()
        buttons.setSpacing(2)
        every = QPushButton("All")
        every.clicked.connect(lambda: self._set_all_instances(True))
        clear = QPushButton("Clear")
        clear.clicked.connect(lambda: self._set_all_instances(False))
        buttons.addWidget(every)
        buttons.addWidget(clear)
        layout.addLayout(buttons)

    def _set_all_instances(self, checked: bool) -> None:
        """Tick, or untick, every instance of the list that can be; a page supplies its own."""

    def open_instance(self, well: int, position: int, feature: str | None = None) -> None:
        """Ask for the instance window of one instance, with ``feature`` drawn if one is given."""
        data = self._wells.get(well)
        if data is not None:
            self.open_requested.emit(data, int(position), feature)

    def add_sort_control(self, layout) -> QComboBox:
        """The *Sort* box of an instance list, its map orders greyed until the map has run."""
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        row.addWidget(QLabel("Sort"))
        self._sort = QComboBox()
        self._sort.addItems(list(SORTS))
        self._sort.setToolTip(SORT_TIP)
        self._sort.currentIndexChanged.connect(self._on_sort_index_changed)
        row.addWidget(self._sort, 1)
        # The descriptor orders' own box: on the grid, or on the measurements.
        self._sort_mode_label = QLabel("on")
        row.addWidget(self._sort_mode_label)
        self._sort_mode = QComboBox()
        self._sort_mode.addItems(list(DESCRIPTOR_MODES))
        self._sort_mode.setToolTip(SORT_MODE_TIP)
        self._sort_mode.currentIndexChanged.connect(self.on_sort_changed)
        row.addWidget(self._sort_mode)
        layout.addLayout(row)
        self._sync_sort_control()
        return self._sort

    def _on_sort_index_changed(self, *args) -> None:
        self._sync_sort_control()
        self.on_sort_changed()

    def _sync_sort_control(self) -> None:
        if self._sort is None:
            return
        map_usable = self._map_results is not None and not self._map_results.joined
        feature = self.sort_feature()
        descriptors_usable = self._passes is not None and feature is not None
        usable = {1: map_usable, 2: map_usable, 3: self._model_results is not None}
        model = self._sort.model()
        for k, choice in enumerate(DESCRIPTOR_CHOICES, start=FIRST_DESCRIPTOR_SORT):
            usable[k] = descriptors_usable
            # The order names the feature it reads, as the feature changes.
            model.item(k).setText(f"{choice.name} of {feature}" if feature else choice.name)
        for k, allowed in usable.items():
            item = model.item(k)
            flags = item.flags()
            item.setFlags(
                flags | Qt.ItemFlag.ItemIsEnabled if allowed else flags & ~Qt.ItemFlag.ItemIsEnabled
            )
        current = self._sort.currentIndex()
        if current and not usable.get(current, True):
            self._sort.blockSignals(True)
            self._sort.setCurrentIndex(0)
            self._sort.blockSignals(False)
        by_descriptor = self.descriptor_sort() is not None
        self._sort_mode_label.setVisible(by_descriptor)
        self._sort_mode.setVisible(by_descriptor)

    def sort_feature(self) -> str | None:
        """The sensor whose descriptors the descriptor orders read; a page names its own."""
        return None

    def descriptor_sort(self) -> DescriptorChoice | None:
        """The descriptor the list is ordered by, or ``None`` under the other orders."""
        if self._sort is None or self._sort.currentIndex() < FIRST_DESCRIPTOR_SORT:
            return None
        return DESCRIPTOR_CHOICES[self._sort.currentIndex() - FIRST_DESCRIPTOR_SORT]

    @property
    def sort_measured(self) -> bool:
        """Whether the descriptor orders read the measurements' figures rather than the grid's."""
        return self._sort_mode is not None and self._sort_mode.currentIndex() == 1

    def _sort_profiles(self):
        """The profiles the descriptor orders read, reading the data if need be; ``None`` if declined."""
        if self._passes is None:
            return None
        profiles = self._passes.profiles(self.info.sensor_names, parent=self.window())
        if profiles is None and self._sort is not None:
            # The pass was declined: back to the order that needs none.
            self._sort.blockSignals(True)
            self._sort.setCurrentIndex(0)
            self._sort.blockSignals(False)
            self._sync_sort_control()
        return profiles

    def descriptor_lines(self, entry: dict) -> list[str]:
        """The descriptor an instance list is ordered by, in one instance, on the grid and on the measurements."""
        choice, feature = self.descriptor_sort(), self.sort_feature()
        profiles = (
            self._passes.profiles_if_loaded(self.info.sensor_names)
            if self._passes is not None
            else None
        )
        if choice is None or feature is None or profiles is None:
            return []
        key = (int(entry["fault"]), str(entry.get("file", "")))
        grid = profiles.descriptor(key, feature, choice.column)
        genuine = profiles.descriptor(key, feature, f"{choice.column}_g")
        lines = [
            (
                f"{choice.name} of {feature}: {choice.format(grid)} on the grid, "
                f"{choice.format(genuine)} on the measurements."
            )
        ]
        if choice.inflated and not self.sort_measured:
            lines.append(f"Ordered by the grid's figure; {GRID_CAVEAT}.")
        return lines

    def set_map_results(self, results) -> None:
        """Take what the Instances map computed; the instance lists gain its figures and its orders."""
        self._map_results = results
        self._sync_sort_control()
        self.on_map_results()

    def set_model_results(self, results) -> None:
        """Take the model outputs loaded (or none): a sort order, tooltip figures and a shading."""
        self._model_results = results
        for action in self._shading_actions:
            action.setVisible(results is not None)
        if results is None and self._shading is not None and self._shading.currentIndex() != 0:
            self._shading.blockSignals(True)
            self._shading.setCurrentIndex(0)
            self._shading.blockSignals(False)
        self._sync_sort_control()
        self.on_map_results()

    @property
    def shade_by_model(self) -> bool:
        """Whether the small plots are shaded by the loaded model's verdicts rather than the labels."""
        return (
            self._model_results is not None
            and self._shading is not None
            and self._shading.currentIndex() == 1
        )

    def model_runs_for(self, fault: int, file: str) -> list[Segment]:
        """The loaded model's verdicts on one instance as label runs, empty without outputs."""
        if self._model_results is None or not file:
            return []
        return self._model_results.class_runs(int(fault), str(file), self.info.transient_offset)

    def on_map_results(self) -> None:
        """Called once the map's or the model's figures are on hand; a page rebuilds its instance list."""

    def on_sort_changed(self, *args) -> None:
        """Called when the *Sort* box changes; a page rebuilds its instance list."""

    def map_figures(self, fault: int, file: str) -> tuple[float, float]:
        """The typicality rank and the novelty score of one instance, NaN when the map has none."""
        results = self._map_results
        if results is None or results.joined:
            return (float("nan"), float("nan"))
        key = (int(fault), str(file))
        return (results.typicality_rank(key), results.novelty_score(key))

    def model_agreement(self, fault: int, file: str) -> float:
        """How far the loaded model agrees with the labels of one instance, NaN without outputs."""
        if self._model_results is None:
            return float("nan")
        return self._model_results.agreement(int(fault), str(file))

    def sorted_entries(self, entries: list[dict]) -> list[dict]:
        """The entries of an instance list in the order the *Sort* box asks for.

        The catalogue's own order stands; typicality puts the most typical
        first; the novelty score puts the most anomalous-looking first; the
        model agreement puts the instance the model disagrees with most
        first. An instance without the figure goes last.
        """
        if self._sort is None or self._sort.currentIndex() == 0:
            return entries
        which = self._sort.currentIndex()
        choice = self.descriptor_sort()
        if choice is not None:
            profiles, feature = self._sort_profiles(), self.sort_feature()
            if profiles is None or feature is None:
                return entries
            column = descriptor_column(choice, self.sort_measured)

            def descriptor(entry: dict) -> float:
                value = profiles.descriptor(
                    (int(entry["fault"]), str(entry.get("file", ""))), feature, column
                )
                # Largest first, an infinite figure largest of all, the unknown last.
                return np.inf if np.isnan(value) else -value

            return sorted(entries, key=descriptor)

        def figure(entry: dict) -> float:
            fault, file = entry["fault"], entry.get("file", "")
            if which == 3:
                value = self.model_agreement(fault, file)
            else:
                rank, score = self.map_figures(fault, file)
                value = -rank if which == 1 else score
            return value if np.isfinite(value) else np.inf

        return sorted(entries, key=figure)

    def shown_files(self) -> list[tuple[int, str]]:
        """The instances ticked, for the file list a Toolkit loader takes."""
        return [
            (int(entry["fault"]), str(entry["file"]))
            for entry in self._checked_instances()
            if entry.get("file")
        ]

    def _checked_instances(self) -> list[dict]:
        """The entries of the instance list that are ticked; a page supplies its own."""
        return []

    def map_tooltip_lines(self, entry: dict) -> str:
        """What the map knows about one instance, for the tooltip of its list item."""
        rank, score = self.map_figures(entry["fault"], entry.get("file", ""))
        lines = []
        if np.isfinite(rank):
            lines.append(f"Typicality {rank:.2f} in its class on the Instances map.")
        if np.isfinite(score):
            verdict = "looks anomalous" if score < 0 else "looks normal"
            lines.append(f"One-class score {score:+.2f}: {verdict} to the Instances map's model.")
        if self._model_results is not None:
            lines.append(self._model_results.describe(entry["fault"], entry.get("file", "")) + ".")
        lines += self.descriptor_lines(entry)
        return ("\n" + "\n".join(lines)) if lines else ""

    def build_body(self, left: QWidget | None, right: QWidget | None) -> QWidget:
        """The plots, with the page's own panels on either side of them."""
        body = QWidget()
        layout = QHBoxLayout(body)
        layout.setContentsMargins(8, 0, 8, 4)
        layout.setSpacing(8)
        if left is not None:
            layout.addWidget(left)
        self._stack = PlotStack()
        self._stack.ci.layout.setVerticalSpacing(4)
        self._stack.ci.setContentsMargins(0, 0, 0, 0)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._scroll.setWidget(self._stack)
        layout.addWidget(self._scroll, 1)
        if right is not None:
            layout.addWidget(right)
        self._stack.scene().sigMouseMoved.connect(self._on_mouse_moved)
        self._stack.scene().sigMouseClicked.connect(self._on_mouse_clicked)
        return body

    def add_alignment_control(self, bar: QToolBar) -> None:
        """The *Align at* box: the moment every instance's time axis starts from."""
        bar.addWidget(QLabel(" Align at "))
        self._align = QComboBox()
        for key in ALIGNMENTS:
            self._align.addItem(ALIGNMENT_NAMES[key], key)
        self._align.setToolTip(ALIGN_TIP)
        self._align.currentIndexChanged.connect(self._on_alignment_changed)
        bar.addWidget(self._align)

    def add_shared_controls(self, bar: QToolBar, domain_tip: str, layout_tip: str) -> None:
        """The *Domain* and *Layout* boxes, and the two controls only the grid uses."""
        bar.addWidget(QLabel(" Domain "))
        self._domain = QComboBox()
        for key in DOMAINS:
            self._domain.addItem(DOMAIN_NAMES[key], key)
        self._domain.setToolTip(domain_tip)
        self._domain.currentIndexChanged.connect(self._on_domain_changed)
        bar.addWidget(self._domain)

        bar.addSeparator()
        bar.addWidget(QLabel(" Layout "))
        self._layout_box = QComboBox()
        self._layout_box.addItems(list(LAYOUTS))
        self._layout_box.setToolTip(layout_tip)
        self._layout_box.currentIndexChanged.connect(self._on_layout_changed)
        bar.addWidget(self._layout_box)
        self._join = QCheckBox("Join overlapping")
        self._join.setToolTip(JOIN_TIP)
        self._join.toggled.connect(self._on_layout_changed)
        self._overall_only: list = [bar.addWidget(self._join)]
        self._grid_only: list = []
        self._grid_only.append(bar.addWidget(QLabel(" Columns ")))
        self._columns = QSpinBox()
        self._columns.setRange(1, 8)
        self._columns.setValue(DEFAULT_COLUMNS)
        self._columns.setToolTip("Small plots per row of the grid")
        self._columns.valueChanged.connect(self._replot)
        self._grid_only.append(bar.addWidget(self._columns))
        self._grid_only.append(bar.addWidget(QLabel(" Axis ")))
        self._value_axis = QComboBox()
        self._value_axis.addItems(list(VALUE_AXES))
        self._value_axis.setToolTip(
            "Per instance, every small plot scales to its own readings, so that every shape is "
            "legible whatever the level of its well; shared, they all take the same value axis, "
            "so that the plots say how far apart those levels are, which is the very thing that "
            "flattens most of them."
        )
        self._value_axis.currentIndexChanged.connect(self._replot)
        self._grid_only.append(bar.addWidget(self._value_axis))

    def build_parameter_bar(self, normalize_tip: str) -> QToolBar:
        """The second row: the stretch around the onset, the normalization, the transforms.

        On one row with the rest these fell behind the toolbar's overflow
        chevron as soon as the page was narrower than a screen; the first row
        now holds what chooses the question, this one what tunes the answer.
        """
        bar = QToolBar("Parameters")
        bar.setMovable(False)
        bar.addWidget(QLabel(" Show "))
        self._before = QDoubleSpinBox()
        self._before.setRange(0.0, 999.0)
        self._before.setDecimals(1)
        self._before.setSingleStep(0.5)
        self._before.setSuffix(" h before")
        self._before.setSpecialValueText("all before")
        self._before.setToolTip(
            "Hours before the onset to draw; at zero, everything recorded before it"
        )
        self._before.valueChanged.connect(self._on_window_changed)
        bar.addWidget(self._before)
        self._after = QDoubleSpinBox()
        self._after.setRange(0.0, 999.0)
        self._after.setDecimals(1)
        self._after.setSingleStep(0.5)
        self._after.setSuffix(" h after")
        self._after.setSpecialValueText("all after")
        self._after.setToolTip(
            "Hours after the onset to draw; at zero, everything recorded after it"
        )
        self._after.valueChanged.connect(self._on_window_changed)
        bar.addWidget(self._after)

        bar.addSeparator()
        self._normalize = QCheckBox("Normalize per instance")
        self._normalize.setToolTip(normalize_tip)
        self._normalize.toggled.connect(self._replot)
        bar.addWidget(self._normalize)
        self._shading_actions = [bar.addWidget(QLabel(" Shade by "))]
        self._shading = QComboBox()
        self._shading.addItems(list(SHADINGS))
        self._shading.setToolTip(SHADING_TIP)
        self._shading.currentIndexChanged.connect(self._replot)
        self._shading_actions.append(bar.addWidget(self._shading))
        for action in self._shading_actions:
            action.setVisible(False)

        self._parameter_separator = bar.addSeparator()
        self._controls = TransformControls()
        self._controls.changed.connect(self._replot)
        bar.addWidget(self._controls)
        self._parameter_bar = bar
        self._sync_layout_controls()
        return bar

    # -- the state of the controls

    def _sync_layout_controls(self) -> None:
        """Show the controls only the grid, or only the domain chosen, has a use for."""
        # First, since it can move the layout off Overall and the rest reads it.
        self._sync_overall_control()
        for action in self._grid_only:
            action.setVisible(self.small_multiples)
        for action in self._overall_only:
            action.setVisible(self.overall)
        self._controls.show_spectral(self.domain == "spectrum")
        self._controls.show_bins(self.domain == "distribution")
        self._parameter_separator.setVisible(self.domain != "time")
        self._sync_alignment_control()

    def _sync_overall_control(self) -> None:
        """Grey *Overall* in the time domain, and leave it if the domain moves there.

        Pooling the readings of instances cut from different months says
        something about their distribution and about their spectrum, and
        nothing at all about their time series: there is no common clock to
        draw them against, and no useful one to invent.
        """
        item = self._layout_box.model().item(LAYOUTS.index("Overall"))
        allowed = self.domain != "time"
        flags = item.flags()
        item.setFlags(
            flags | Qt.ItemFlag.ItemIsEnabled if allowed else flags & ~Qt.ItemFlag.ItemIsEnabled
        )
        if not allowed and self.overall:
            self._layout_box.blockSignals(True)
            self._layout_box.setCurrentIndex(LAYOUTS.index("Overlaid"))
            self._layout_box.blockSignals(False)

    def _sync_alignment_control(self) -> None:
        """Grey *Align at* wherever the anchor has nothing left to change.

        Off the time axis no plot is drawn against the hours from the onset,
        so the anchor reaches a distribution or a spectrum only through the
        stretch the hour boxes cut around it; with both of them at *all* the
        whole recording is transformed whichever moment it is aligned on. The
        box comes back as soon as a window is asked for, or the time series
        is.
        """
        moot = self.domain != "time" and self._before.value() == 0 and self._after.value() == 0
        self._align.setEnabled(not moot)
        self._align.setToolTip(ALIGN_MOOT_TIP if moot else ALIGN_TIP)

    def _on_layout_changed(self, *args) -> None:
        self._sync_layout_controls()
        self._replot(keep_range=False)

    def _on_domain_changed(self, *args) -> None:
        self._sync_layout_controls()
        self._replot(keep_range=False)

    def _on_window_changed(self, *args) -> None:
        """The hours around the onset changed: the anchor may have become worth choosing again."""
        self._sync_alignment_control()
        self._replot()

    def _on_alignment_changed(self, *args) -> None:
        self._replot(keep_range=False)

    @property
    def domain(self) -> str:
        return str(self._domain.currentData() or "time")

    def set_domain(self, domain: str) -> None:
        """Show every plot in one domain, as the box would."""
        if domain not in DOMAINS:
            raise ValueError(f"unknown domain {domain!r}; expected one of {DOMAINS}")
        self._domain.setCurrentIndex(DOMAINS.index(domain))

    @property
    def small_multiples(self) -> bool:
        return self._layout_box.currentIndex() == 0

    @property
    def overall(self) -> bool:
        """Whether the instances of a group are pooled into one curve."""
        return self._layout_box.currentIndex() == LAYOUTS.index("Overall")

    @property
    def joined(self) -> bool:
        """Whether overlapping instances are read as one recording before they are pooled."""
        return self._join.isChecked()

    def set_layout(self, name: str) -> None:
        """Arrange the plots as the box would."""
        if name not in LAYOUTS:
            raise ValueError(f"unknown layout {name!r}; expected one of {LAYOUTS}")
        self._layout_box.setCurrentIndex(LAYOUTS.index(name))

    @property
    def per_instance_axis(self) -> bool:
        """Whether every small plot scales to its own readings."""
        return self._value_axis.currentIndex() == 0

    @property
    def alignment(self) -> str:
        return str(self._align.currentData())

    @property
    def clamped(self) -> bool:
        """Whether the histograms count only the physically plausible readings."""
        return self._controls.params().clamp

    def bounds_of(self, feature: str) -> tuple[float, float]:
        """The range a reading of ``feature`` has to be in to be believed, in its shown unit."""
        return self.info.shown_range(feature)

    def hist_bounds(self, feature: str, normalize: bool) -> tuple[float, float] | None:
        """What a histogram of ``feature`` leaves out: nothing, unless the clamp is on.

        A normalized series is already scaled over the plausible readings only,
        so its z-scores have no range of their own to be clipped to.
        """
        if normalize or not self.clamped:
            return None
        return self.bounds_of(feature)

    # -- appearance

    def _restyle_plots(self) -> None:
        self._stack.setBackground(theme.current().plot_background)

    # -- what a subclass answers

    def load_series(self) -> list[Series]:
        """The instances to draw, in the order the page wants them."""
        raise NotImplementedError

    def sections(self) -> list[Section]:
        """The headings and, under each, the sensor and the instances drawn."""
        raise NotImplementedError

    def series_headline(self, series: Series) -> str:
        """What the status bar calls one instance, before the reading under the pointer."""
        raise NotImplementedError

    def section_note(self, section: Section, drawn: int, total: int) -> str:
        """What the heading adds after the counts; empty for nothing."""
        return "" if drawn == total else f" | {total - drawn} recorded none of it"

    def before_replot(self) -> None:
        """Called before the plots are laid out again, for a page's own bookkeeping."""

    def pool_key(self, series: Series):
        """Which group an instance is pooled into when *Overall* is on.

        The faults page pools everything it draws into one curve per feature;
        the features page keeps the classes apart, since telling them apart is
        the whole of what it is for.
        """
        return "everything"

    def pool_headline(self, members: list[int]) -> str:
        """What the status bar calls a pooled curve, in place of naming one instance."""
        wells = {self._series[i].well for i in members}
        recordings = "recording" if len(members) == 1 else "recordings"
        return (
            f"{len(members)} {recordings} pooled from "
            f"{len(wells)} well{'s' if len(wells) > 1 else ''}"
        )

    # -- drawing

    def _replot(self, *args, keep_range: bool = True, keep_views: bool = False) -> None:
        """Read the ticked instances and lay the plots out again.

        The stretch of time on screen is kept, so that ticking a feature or an
        instance does not throw away a zoom; a new question (a new grouping, a
        new alignment, a new layout) starts from the whole of it. With
        ``keep_views`` every plot gets back both of its ranges, as long as the
        same plots come back: what a theme switch asks, the question being
        the same and only the colors new.
        """
        if not self.ready():
            return
        views = [plot.getViewBox().viewRange() for plot in self._plots] if keep_views else []
        self.before_replot()
        if not keep_range:
            self._x_range = None
        elif self._plots:
            self._x_range = tuple(self._plots[0].getViewBox().viewRange()[0])
        QApplication.setOverrideCursor(QCursor(Qt.CursorShape.WaitCursor))
        try:
            self._series = self.load_series()
            if self.overall and self.joined:
                # Before anything is counted: the windows of a well that
                # overlap become the one recording they were cut from, so a
                # shared sample is not counted once per window that holds it.
                self._series = merge_overlapping(self._series, self.pool_key)
            self._lay_out()
            if views and len(views) == len(self._plots):
                for plot, (x_range, y_range) in zip(self._plots, views, strict=True):
                    plot.getViewBox().setRange(xRange=x_range, yRange=y_range, padding=0)
        finally:
            QApplication.restoreOverrideCursor()
        self.summary_changed.emit()

    def ready(self) -> bool:
        """Whether there is a catalogue to draw from yet."""
        return True

    def drawn_series(self) -> list[Series]:
        """The instances a layout actually draws: all of them, or as many as a grid can hold."""
        if self.small_multiples:
            return self._series[:MAX_SMALL_MULTIPLES]
        return self._series

    def _drawn_members(self, section: Section) -> list[int]:
        """The members of one section a layout actually draws."""
        limit = len(self.drawn_series())
        return [i for i in section.members if i < limit]

    @staticmethod
    def chip(color: str) -> QIcon:
        """The small square of a series color, before an instance in a list."""
        pixmap = QPixmap(CHIP_PX, CHIP_PX)
        pixmap.fill(QColor(color))
        return QIcon(pixmap)

    # -- one series, one feature

    def _xy(
        self, series: Series, feature: str, normalize: bool, before: float, after: float, bounds
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray | None] | None:
        """The hours, the readings and the kinds of sample of one series for one feature, inside the window.

        The kinds (``interpolation.sample_kinds``: measured, interpolated,
        held, missing) are found on the raw readings, before any scaling, and
        are ``None`` for an enumerated variable, which is not tested. The
        readings come in their shown unit (a pressure in MPa), which is also
        the unit of ``bounds``. ``None`` altogether when this instance says
        nothing about the feature, so that a plot is never built for a blank.
        """
        frame = series.frame
        if feature not in frame.columns:
            return None
        y = column_as_float(frame, feature)
        if not (~np.isnan(y)).any():
            return None
        kinds = None if self.info.is_enumerated(feature) else sample_kinds(y)
        scale = self.info.shown_scale(feature)
        if scale != 1.0:
            y = y * scale
        if normalize:
            # Scaled over the plausible readings only, as the pipelines mask the
            # garbage before they normalize: one absurd level would otherwise
            # squash every genuine reading into zero.
            y = zscore(np.where((y >= bounds[0]) & (y <= bounds[1]), y, np.nan))
            if not (~np.isnan(y)).any():
                return None
        mask = window_mask(series.hours, before, after)
        x, y = series.hours[mask], y[mask]
        if kinds is not None:
            kinds = kinds[mask]
        return (x, y, kinds) if len(x) else None

    def _window_values(
        self, series: Series, feature: str, normalize: bool, before: float, after: float, bounds
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray | None] | None:
        """The readings of one series inside the window, with the hours, label kind and sample kind of each.

        What the distribution and the spectrum are computed from: the same
        stretch the time series draws, in the same order, so that "2 h after
        the onset" means the same in every domain.
        """
        got = self._xy(series, feature, normalize, before, after, bounds)
        if got is None:
            return None
        x, y, kinds = got
        mask = window_mask(series.hours, before, after)
        labels = column_as_float(series.frame, "class")[mask]
        return x, y, self._kind_codes(labels), kinds

    def _kind_codes(self, labels: np.ndarray) -> np.ndarray:
        """``label_kind`` of every sample at once, as positions in ``HIST_KINDS``."""
        offset = self.info.transient_offset
        transient = (labels > offset) & (labels < 2 * offset)
        return np.select(
            [np.isnan(labels), labels == 0, transient],
            [
                HIST_KINDS.index("unknown"),
                HIST_KINDS.index("normal"),
                HIST_KINDS.index("transient"),
            ],
            default=HIST_KINDS.index("steady"),
        ).astype(np.int64)

    # -- the pieces both layouts build from

    def _new_plot(self, row: int, col: int) -> pg.PlotItem:
        """A plot in the stack; in the time domain, with the dashed vertical marking the onset."""
        plot = self._stack.addPlot(row=row, col=col, viewBox=ScrollFriendlyViewBox())
        plot.hideButtons()
        plot.getViewBox().disableAutoRange()
        if self.domain == "time":
            onset_line = pg.InfiniteLine(
                pos=0.0,
                angle=90,
                movable=False,
                pen=pg.mkPen(theme.current().gap_line, width=1, style=Qt.PenStyle.DashLine),
            )
            onset_line.setZValue(-5)
            plot.addItem(onset_line, ignoreBounds=True)
        return plot

    def _bottom_label(self, feature: str, normalize: bool) -> str:
        """What the horizontal axis of a plot means in the domain chosen."""
        if self.domain == "time":
            return ALIGNMENT_AXES[self.alignment]
        if self.domain == "distribution":
            unit = "z-score" if normalize else self.info.shown_unit(feature)
            return f"{feature} [{unit}]" if unit else feature
        return "period"

    def _prepare_left_axis(
        self,
        plot: pg.PlotItem,
        feature: str,
        normalize: bool,
        width: int,
        values: bool,
        label: bool,
    ) -> None:
        """The left axis in the domain chosen: readings, a share of samples, or a power."""
        if self.domain == "time":
            self._prepare_axis(plot, feature, normalize, width, values, label)
            return
        axis = plot.getAxis("left")
        axis.setWidth(width)
        axis.enableAutoSIPrefix(False)
        if self.domain == "distribution":
            if label:
                plot.setLabel("left", "% of samples")
        else:
            unit = "" if normalize else self.info.shown_unit(feature)
            power_axis(plot, "left", power_label(unit) if label else "")
        if not values:
            axis.setStyle(showValues=False)

    def _prepare_bottom_axis(self, plot: pg.PlotItem, feature: str, normalize: bool) -> None:
        """The bottom axis in the domain chosen; a period axis for the spectrum."""
        if self.domain == "spectrum":
            set_log_period_axis(plot, "bottom", "period")
        else:
            plot.setLabel("bottom", self._bottom_label(feature, normalize))

    def _prepare_axis(
        self,
        plot: pg.PlotItem,
        feature: str,
        normalize: bool,
        width: int,
        values: bool,
        label: bool,
    ) -> None:
        """Give a plot its left axis: the same width everywhere, so a grid of them lines up."""
        axis = plot.getAxis("left")
        axis.setWidth(width)
        unit = self.info.shown_unit(feature)
        # One unit per quantity on every axis: pyqtgraph's own prefix would
        # label one pressure kPa and the next MPa.
        axis.enableAutoSIPrefix(False)
        if label:
            if normalize:
                plot.setLabel("left", f"{feature} (z-score)")
            else:
                plot.setLabel("left", f"{feature} [{unit}]" if unit else feature)
        if not values:
            axis.setStyle(showValues=False)

    # -- one series, one feature, off the time axis

    def _histogram_of(self, values: np.ndarray, codes: np.ndarray, edges, bounds):
        """The histogram of one series, stacked by label kind."""
        return histogram(
            values,
            codes,
            self._controls.params().bins,
            bounds,
            edges=edges,
            keys=list(HIST_KINDS),
        )

    def _spectrum_of(
        self, values: np.ndarray, bounds, normalize, times_s: np.ndarray | None = None
    ) -> Spectrum | None:
        """Welch's estimate on the grid, or, given the instants of the measurements, Lomb-Scargle over them."""
        # The spectrum always masks the implausible: interpolating over a spike
        # of 10¹² is the spectrum of the spike, not of the signal. The clamp is
        # about what a histogram counts, which is a question of reading.
        limits = None if normalize else bounds
        if times_s is not None:
            prepared = prepare_irregular(times_s, values, limits)
            return None if prepared is None else lomb_scargle(*prepared)
        prepared = prepare(values, limits)
        if prepared is None:
            return None
        return welch(prepared, self._controls.params())

    def _kind_brush(self, kind: str, fault: int):
        """The fill of one stack of a histogram: the class color of the label period."""
        if kind == "unknown":
            return pg.mkBrush(tint(unknown_background(), 0.7))
        return pg.mkBrush(bar_color(fault, kind))

    def _mark_peak(self, plot: pg.PlotItem, index: int, result: Histogram, color: str) -> None:
        """Put the triangle over the fullest bin of one instance's histogram, and remember it.

        The height is the share of the instance's samples, which is what the
        value axis carries, so that instances of different length are marked at
        the height their own curve reaches.
        """
        value, count = result.peak
        if not count:
            return
        share = 100.0 * count / result.total
        self._peaks_by_plot[(id(plot), index)] = (value, share)
        add_peak_marker(plot, value, share, color, horizontal=False)

    def _shade_outside(self, plot: pg.PlotItem, feature: str, normalize: bool) -> None:
        """With the clamp off, say where the believable readings end."""
        if self.clamped or normalize or self.domain != "distribution":
            return
        shade_implausible(plot, self.bounds_of(feature), "x")

    def _add_curve(
        self, plot: pg.PlotItem, series: Series, x, y, kinds: np.ndarray | None = None
    ) -> Trace:
        """One time series in the color of its series: its measurements as dots, the lines between them faint."""
        return add_trace(plot, x, y, series.color, 1.2, kinds)

    def _add_shading(self, plot: pg.PlotItem, series: Series) -> None:
        """Shade the label periods of one instance behind its trace, as the instance window does.

        The runs come from the catalogue, so this costs no reading; with them a
        small plot says not only what the readings did but how long the experts
        left the instance in normal operation, in the transient and in the
        steady state, which is the very thing that differs from well to well.

        A stretch nobody labeled is hatched rather than merely grey, as it is
        everywhere else in the viewer: two of the fault hues are themselves
        grey, and a texture says *nothing is known here* where one more shade
        would just read as one more class.
        """
        runs = series.model_runs if self.shade_by_model and series.model_runs else series.runs
        if not runs:
            return
        offset = self.info.transient_offset
        x0, x1, fills, unknown = [], [], [], []
        for run in runs:
            start, end = relative_hours([run.start, run.end], series.onset)
            kind = label_kind(run.value, offset)
            if kind == "unknown":
                fill = tint(unknown_background(), 0.7)
            else:
                hue = label_fault(run.value, offset)
                fill = background_color(series.fault if hue is None else hue, kind)
            x0.append(float(start))
            x1.append(float(end))
            fills.append(fill)
            unknown.append(kind == "unknown")
        shading = SegmentsItem(z=-10)
        shading.set_segments(x0, x1, fills, hatched=unknown)
        plot.addItem(shading, ignoreBounds=True)

    # -- laying out

    def _lay_out(self) -> None:
        stack = self._stack
        stack.clear()
        self._plots = []
        self._plot_features = []
        self._curves = {i: [] for i in range(len(self._series))}
        self._plot_series = []
        self._spectra_by_plot = {}
        self._peaks_by_plot = {}
        self._pool = {}
        self._hover = -1
        sections = self.sections()
        if not sections:
            label = stack.addLabel(
                self.empty_message(),
                row=0,
                col=0,
                color=theme.current().faint,
            )
            label.setMinimumHeight(60)
            stack.setMinimumHeight(80)
        else:
            height = (
                self._lay_out_grid(sections)
                if self.small_multiples
                else self._lay_out_overlay(sections)
            )
            stack.setMinimumHeight(max(height, self._stack_height_floor(), 80))
        stack.resizeEvent(None)
        self._apply_x_range()

    def empty_message(self) -> str:
        return "Nothing to draw."

    def _stack_height_floor(self) -> int:
        """The layout's own idea of its minimum height, as a floor under the estimate above.

        The estimate sums a fixed height per row and a flat few pixels per
        section for the gaps between them, which undercounts a grid with many
        rows: each real gap between two rows of a pyqtgraph layout costs its
        own spacing, and a grid of, say, eight rows has seven of them per
        section, not the one or two pixels the flat fudge budgets. The layout
        already knows its rows and its spacing once they are built, so its own
        effective size hint is the authority the estimate only approximates;
        short of it, the scroll area was clipping the last row.
        """
        return int(self._stack.ci.layout.effectiveSizeHint(Qt.SizeHint.MinimumSize).height())

    def _lay_out_overlay(self, sections: list[Section]) -> int:
        """One plot per section, every instance in it drawn over the others."""
        if self.domain != "time":
            return self._lay_out_overlay_off_time(sections)
        normalize = self._normalize.isChecked()
        before, after = self._before.value(), self._after.value()
        master = None
        for row, section in enumerate(sections):
            feature = section.feature
            plot = self._new_plot(row, 0)
            plot.setMinimumHeight(PLOT_PX)
            self._stack.ci.layout.setRowStretchFactor(row, 1)
            self._prepare_axis(plot, feature, normalize, AXIS_WIDTH, values=True, label=True)
            if row == len(sections) - 1:
                plot.setLabel("bottom", ALIGNMENT_AXES[self.alignment])
            else:
                plot.hideAxis("bottom")
            if master is None:
                master = plot
            else:
                plot.setXLink(master)

            drawn: list[tuple[int, np.ndarray, np.ndarray]] = []
            lows, highs = [], []
            bounds = self.bounds_of(feature)
            for i in self._drawn_members(section):
                series = self._series[i]
                got = self._xy(series, feature, normalize, before, after, bounds)
                if got is None:
                    continue
                x, y, kinds = got
                self._curves[i].append(self._add_curve(plot, series, x, y, kinds))
                drawn.append((i, x, y))
                low, high = plausible_extent(y, (-np.inf, np.inf) if normalize else bounds)
                if not np.isnan(low):
                    lows.append(low)
                    highs.append(high)
            if lows:
                plot.getViewBox().setYRange(*padded_range(min(lows), max(highs)), padding=0)
            self._plots.append(plot)
            self._plot_features.append(feature)
            self._plot_series.append(drawn)
        return PLOT_PX * len(sections) + 8

    def _lay_out_grid(self, sections: list[Section]) -> int:
        """One small plot per instance, in a grid under a heading per section."""
        if self.domain != "time":
            return self._lay_out_grid_off_time(sections)
        normalize = self._normalize.isChecked()
        before, after = self._before.value(), self._after.value()
        columns = self._columns.value()
        per_instance = self.per_instance_axis
        master = None
        row, height = 0, 0
        for index, section in enumerate(sections):
            feature = section.feature
            members = self._drawn_members(section)
            bounds = self.bounds_of(feature)
            prepared: list[tuple[int, np.ndarray, np.ndarray, np.ndarray | None]] = []
            lows, highs = [], []
            for i in members:
                got = self._xy(self._series[i], feature, normalize, before, after, bounds)
                if got is None:
                    continue
                x, y, kinds = got
                prepared.append((i, x, y, kinds))
                low, high = plausible_extent(y, (-np.inf, np.inf) if normalize else bounds)
                if not np.isnan(low):
                    lows.append(low)
                    highs.append(high)
            shared = padded_range(min(lows), max(highs)) if lows else None

            heading = HeaderLabel(justify="left")
            counts = [sample_counts(y, kinds) for _i, _x, y, kinds in prepared]
            heading.setText(
                self._section_html(section, normalize, len(prepared), len(members), counts)
            )
            heading.setFixedHeight(SECTION_PX)
            self._stack.addItem(heading, row=row, col=0, colspan=columns)
            row += 1
            height += SECTION_PX
            if not prepared:
                continue

            n_rows = ceil(len(prepared) / columns)
            section_master = None
            for k, (i, x, y, kinds) in enumerate(prepared):
                place, column = divmod(k, columns)
                bottom = place == n_rows - 1
                plot = self._new_plot(row + place, column)
                plot.setMinimumHeight(SMALL_PLOT_PX + (SMALL_AXIS_PX if bottom else 0))
                self._prepare_axis(
                    plot,
                    feature,
                    normalize,
                    SMALL_AXIS_WIDTH,
                    values=per_instance or column == 0,
                    label=False,
                )
                if not bottom:
                    plot.hideAxis("bottom")
                elif index == len(sections) - 1:
                    plot.setLabel("bottom", ALIGNMENT_AXES[self.alignment])
                if master is None:
                    master = plot
                else:
                    plot.setXLink(master)
                if per_instance:
                    low, high = plausible_extent(y, (-np.inf, np.inf) if normalize else bounds)
                    plot.getViewBox().setYRange(*padded_range(low, high), padding=0)
                elif section_master is None:
                    section_master = plot
                    if shared is not None:
                        plot.getViewBox().setYRange(*shared, padding=0)
                else:
                    plot.setYLink(section_master)
                self._add_shading(plot, self._series[i])
                self._curves[i].append(self._add_curve(plot, self._series[i], x, y, kinds))
                self._corner_label(plot, self._series[i])
                self._plots.append(plot)
                self._plot_features.append(feature)
                self._plot_series.append([(i, x, y)])
            row += n_rows
            height += n_rows * SMALL_PLOT_PX + SMALL_AXIS_PX + 8
        return height + 8

    def _corner_label(self, plot: pg.PlotItem, series: Series) -> None:
        AnchoredText(
            f'<span style="font-size:7pt; color:{series.color};">{series.label}</span>',
            frac=(0.02, 0.98),
            anchor=(0, 0),
            boxed=False,
        ).attach(plot)

    # -- the other domains: the same two layouts, drawing what the transforms give

    def _prepared_off_time(self, sections: list[Section]):
        """Per section, what every drawn member gives in the domain chosen: values or a spectrum."""
        normalize = self._normalize.isChecked()
        before, after = self._before.value(), self._after.value()
        genuine = self._controls.params().genuine
        prepared: dict[object, list] = {}
        self._section_counts = {}
        for section in sections:
            feature = section.feature
            bounds = self.bounds_of(feature)
            hist_bounds = self.hist_bounds(feature, normalize)
            rows = []
            counts = self._section_counts.setdefault(section.key, [])
            for i in self._drawn_members(section):
                got = self._window_values(
                    self._series[i], feature, normalize, before, after, bounds
                )
                if got is None:
                    continue
                x, values, codes, kinds = got
                counts.append(sample_counts(values, kinds))
                # The measurements alone, when asked: the historian's lines
                # between them are left out of the count and of the transform.
                measured = genuine and kinds is not None
                if measured:
                    keep = kinds == GENUINE
                    x, values, codes = x[keep], values[keep], codes[keep]
                if self.domain == "spectrum":
                    spectrum = self._spectrum_of(
                        values, bounds, normalize, x * 3600.0 if measured else None
                    )
                    if spectrum is not None:
                        rows.append((i, spectrum))
                else:
                    inside = values[~np.isnan(values)]
                    if hist_bounds is not None:
                        inside = inside[(inside >= hist_bounds[0]) & (inside <= hist_bounds[1])]
                    if len(inside):
                        rows.append((i, values, codes, float(inside.min()), float(inside.max())))
            prepared[section.key] = self._pool_rows(rows) if self.overall else rows
        return prepared, normalize

    def _pool_rows(self, rows: list) -> list:
        """Fold the rows of one section into one per group, for *Overall*.

        A distribution pools by putting the readings together: a histogram of
        the union is a histogram, whatever order the samples arrive in. A
        spectrum does not, and cannot be taken over the concatenation (a
        transform reads consecutive samples as one second apart, so the months
        between two instances would become a step), so the estimates are
        averaged band by band instead, which is what Welch's method already
        does one level down.

        The group keeps the position of its first member, whose color and
        whose section it takes; ``_pool`` remembers the rest so that the status
        bar can say how many recordings and how many wells are behind the
        curve.
        """
        groups: dict = {}
        for row in rows:
            groups.setdefault(self.pool_key(self._series[row[0]]), []).append(row)
        folded = []
        for members in groups.values():
            head = members[0][0]
            self._pool[head] = [row[0] for row in members]
            if self.domain == "spectrum":
                pooled = average_spectra([row[1] for row in members])
                if pooled is not None:
                    folded.append((head, pooled))
            else:
                folded.append(
                    (
                        head,
                        np.concatenate([row[1] for row in members]),
                        np.concatenate([row[2] for row in members]),
                        min(row[3] for row in members),
                        max(row[4] for row in members),
                    )
                )
        return folded

    def _shared_edges(self, rows) -> np.ndarray | None:
        """Bins spanning the readings of every series of one section, for histograms on one axis."""
        if not rows:
            return None
        low = min(row[3] for row in rows)
        high = max(row[4] for row in rows)
        if high <= low:
            margin = max(abs(low) * 0.01, 0.5)
            low, high = low - margin, high + margin
        return np.linspace(low, high, self._controls.params().bins + 1)

    @staticmethod
    def _log_period_span(spectra: list[Spectrum]) -> tuple[float, float]:
        lows = [np.log10(s.periods[0]) for s in spectra]
        highs = [np.log10(s.periods[-1]) for s in spectra]
        return (float(min(lows)), float(max(highs)))

    def _shade_fixed_segment(self, plot: pg.PlotItem) -> None:
        """Grey the periods a fixed segment cannot resolve; a whole-stretch one differs per instance."""
        segment = self._controls.params().segment_s
        if segment > 0:
            shade_unresolved(plot, float(np.log10(segment)), "x")

    def _lay_out_overlay_off_time(self, sections: list[Section]) -> int:
        """One plot per section: the histograms, or the spectra, of every instance over one another."""
        prepared, normalize = self._prepared_off_time(sections)
        for row, section in enumerate(sections):
            feature = section.feature
            rows = prepared[section.key]
            plot = self._new_plot(row, 0)
            plot.setMinimumHeight(PLOT_PX)
            self._stack.ci.layout.setRowStretchFactor(row, 1)
            self._prepare_left_axis(plot, feature, normalize, AXIS_WIDTH, values=True, label=True)
            self._prepare_bottom_axis(plot, feature, normalize)
            if self.domain == "spectrum":
                spectrum_grid(plot)
            drawn: list[tuple[int, np.ndarray, np.ndarray]] = []
            vb = plot.getViewBox()
            if self.domain == "distribution":
                edges = self._shared_edges(rows)
                self._shade_outside(plot, feature, normalize)
                top = 0.0
                for i, values, codes, _low, _high in rows:
                    result = self._histogram_of(
                        values, codes, edges, self.hist_bounds(feature, normalize)
                    )
                    if result is None or result.total == 0:
                        continue
                    share = 100.0 * result.counts / result.total
                    top = max(top, float(share.max()))
                    curve = add_step_outline(
                        plot,
                        result.edges,
                        share,
                        pg.mkPen(self._series[i].color, width=1.2),
                        fill=self._series[i].color,
                    )
                    self._curves[i].append(curve)
                    self._mark_peak(plot, i, result, self._series[i].color)
                    centers = 0.5 * (result.edges[:-1] + result.edges[1:])
                    drawn.append((i, centers, share))
                if edges is not None:
                    vb.setXRange(float(edges[0]), float(edges[-1]), padding=0.02)
                    vb.setYRange(0.0, top * 1.05 if top > 0 else 1.0, padding=0)
            else:
                spectra = [spectrum for _i, spectrum in rows]
                lows, highs = [], []
                for i, spectrum in rows:
                    curve = add_spectrum_curve(
                        plot, spectrum, pg.mkPen(self._series[i].color, width=1.2), "x"
                    )
                    self._curves[i].append(curve)
                    self._spectra_by_plot[(id(plot), i)] = spectrum
                    x, y = spectrum_xy(spectrum, "x")
                    drawn.append((i, x, y))
                    finite = y[np.isfinite(y)]
                    if len(finite):
                        lows.append(float(finite.min()))
                        highs.append(float(finite.max()))
                if spectra:
                    vb.setXRange(*self._log_period_span(spectra), padding=0.01)
                    low, high = min(lows), max(highs)
                    pad = 0.05 * max(high - low, 1.0)
                    vb.setYRange(low - pad, high + pad, padding=0)
                    self._shade_fixed_segment(plot)
            if not drawn:
                AnchoredText(
                    f'<span style="font-size:10pt; color:{theme.current().faint};">nothing to '
                    "transform: too few readings, or flat signals</span>",
                    frac=(0.5, 0.5),
                    anchor=(0.5, 0.5),
                    boxed=False,
                ).attach(plot)
            self._plots.append(plot)
            self._plot_features.append(feature)
            self._plot_series.append(drawn)
        return PLOT_PX * len(sections) + 8

    def _lay_out_grid_off_time(self, sections: list[Section]) -> int:
        """One small plot per instance: its histogram stacked by label period, or its spectrum."""
        prepared, normalize = self._prepared_off_time(sections)
        columns = self._columns.value()
        per_instance = self.per_instance_axis
        colors = theme.current()
        row, height = 0, 0
        for index, section in enumerate(sections):
            feature = section.feature
            rows = prepared[section.key]
            hist_bounds = self.hist_bounds(feature, normalize)
            heading = HeaderLabel(justify="left")
            heading.setText(
                self._section_html(
                    section,
                    normalize,
                    len(rows),
                    len(self._drawn_members(section)),
                    self._section_counts.get(section.key, []),
                )
            )
            heading.setFixedHeight(SECTION_PX)
            self._stack.addItem(heading, row=row, col=0, colspan=columns)
            row += 1
            height += SECTION_PX
            if not rows:
                continue
            edges = self._shared_edges(rows) if self.domain == "distribution" else None
            span = (
                self._log_period_span([s for _i, s in rows]) if self.domain == "spectrum" else None
            )
            n_rows = ceil(len(rows) / columns)
            section_master = None
            for k, entry in enumerate(rows):
                i = entry[0]
                place, column = divmod(k, columns)
                bottom = place == n_rows - 1
                plot = self._new_plot(row + place, column)
                plot.setMinimumHeight(SMALL_PLOT_PX + (SMALL_AXIS_PX if bottom else 0))
                self._prepare_left_axis(
                    plot,
                    feature,
                    normalize,
                    SMALL_AXIS_WIDTH,
                    values=per_instance or column == 0,
                    label=False,
                )
                if bottom:
                    self._prepare_bottom_axis(plot, feature, normalize)
                    if index != len(sections) - 1:
                        plot.setLabel("bottom", "")
                elif self.domain == "spectrum":
                    set_log_period_axis(plot, "bottom", "")
                    plot.hideAxis("bottom")
                else:
                    plot.hideAxis("bottom")
                vb = plot.getViewBox()
                if self.domain == "distribution":
                    _i, values, codes, _low, _high = entry
                    result = self._histogram_of(
                        values, codes, None if per_instance else edges, hist_bounds
                    )
                    if result is None or result.total == 0:
                        continue
                    self._shade_outside(plot, feature, normalize)
                    shares = {
                        kind: 100.0 * counts / result.total
                        for kind, counts in result.stacks.items()
                    }
                    scaled = Histogram(
                        result.edges, shares, result.left_out, result.mean, result.median
                    )
                    brushes = {
                        kind: self._kind_brush(kind, self._series[i].fault) for kind in shares
                    }
                    add_stacked_bars(
                        plot,
                        scaled,
                        brushes,
                        horizontal=False,
                        pen=pg.mkPen(colors.plot_background, width=0.5),
                    )
                    total_share = 100.0 * result.counts / result.total
                    outline = add_step_outline(
                        plot, result.edges, total_share, pg.mkPen(self._series[i].color, width=1.2)
                    )
                    self._curves[i].append(outline)
                    add_center_lines(plot, result.mean, result.median, horizontal=False)
                    self._mark_peak(plot, i, result, self._series[i].color)
                    centers = 0.5 * (result.edges[:-1] + result.edges[1:])
                    x, y = centers, total_share
                    vb.setXRange(float(result.edges[0]), float(result.edges[-1]), padding=0.02)
                    top = float(total_share.max()) * 1.05 if total_share.max() > 0 else 1.0
                else:
                    _i, spectrum = entry
                    curve = add_spectrum_curve(
                        plot, spectrum, pg.mkPen(self._series[i].color, width=1.2), "x"
                    )
                    self._curves[i].append(curve)
                    self._spectra_by_plot[(id(plot), i)] = spectrum
                    spectrum_grid(plot)
                    x, y = spectrum_xy(spectrum, "x")
                    vb.setXRange(*span, padding=0.01)
                    finite = y[np.isfinite(y)]
                    low_p, high_p = (
                        (float(finite.min()), float(finite.max())) if len(finite) else (0, 1)
                    )
                    pad = 0.05 * max(high_p - low_p, 1.0)
                    top = (low_p - pad, high_p + pad)
                    self._shade_fixed_segment(plot)
                if per_instance:
                    if self.domain == "distribution":
                        vb.setYRange(0.0, top, padding=0)
                    else:
                        vb.setYRange(*top, padding=0)
                elif section_master is None:
                    section_master = plot
                    if self.domain == "distribution":
                        vb.setYRange(0.0, top, padding=0)
                    else:
                        vb.setYRange(*top, padding=0)
                else:
                    plot.setYLink(section_master)
                    if not per_instance:
                        # Widen the section's shared axis to hold this plot too.
                        master_vb = section_master.getViewBox()
                        (lo, hi) = master_vb.viewRange()[1]
                        if self.domain == "distribution":
                            master_vb.setYRange(0.0, max(hi, top), padding=0)
                        else:
                            master_vb.setYRange(min(lo, top[0]), max(hi, top[1]), padding=0)
                self._corner_label(plot, self._series[i])
                self._plots.append(plot)
                self._plot_features.append(feature)
                self._plot_series.append([(i, x, y)])
            row += n_rows
            height += n_rows * SMALL_PLOT_PX + SMALL_AXIS_PX + 8
        return height + 8

    def _section_html(
        self,
        section: Section,
        normalize: bool,
        drawn: int,
        total: int,
        counts: Sequence[tuple[int, int | None]] = (),
    ) -> str:
        """The heading above one section's grid: what it groups, what it holds, and what its axes mean.

        ``counts`` are ``sample_counts`` of every instance drawn, over the
        window of hours chosen: the heading gives their sum, and how many of
        those samples the historian actually archived.
        """
        colors = theme.current()
        unit = "z-score" if normalize else self.info.shown_unit(section.feature)
        head = f"{section.title}" + (f" [{unit}]" if unit else "")
        what = {
            "time": "value axis",
            "distribution": "share axis",
            "spectrum": "power axis",
        }[self.domain]
        axis = f"each plot on its own {what}" if self.per_instance_axis else f"all on one {what}"
        if self.domain == "spectrum":
            axis += ", the period along the bottom"
        return (
            f'<span style="font-size:10pt; color:{colors.text};"><b>{head}</b></span>'
            f'<span style="font-size:8pt; color:{colors.muted};">&nbsp;&nbsp;'
            f"{drawn} of {total} instances{self._counts_text(counts)} | {axis}"
            f"{self.section_note(section, drawn, total)}</span>"
        )

    @staticmethod
    def _counts_text(counts: Sequence[tuple[int, int | None]]) -> str:
        """`` | 21,376 samples, 1,712 measurements (8.0 %)``, or nothing with no instance drawn."""
        if not counts:
            return ""
        samples = sum(n for n, _m in counts)
        text = f" | {samples:,} samples"
        measured = [m for _n, m in counts if m is not None]
        if measured and samples:
            total = sum(measured)
            text += f", {total:,} measurements ({total / samples:.1%})"
        return text

    def _apply_x_range(self) -> None:
        if not self._plots or self.domain != "time":
            return  # off the time axis every plot set its own range as it was built
        vb = self._plots[0].getViewBox()
        if self._x_range is not None:
            vb.setXRange(*self._x_range, padding=0)
            return
        xs = [x for drawn in self._plot_series for _, x, _ in drawn]
        if not xs:
            return
        starts = [float(x.min()) for x in xs]
        ends = [float(x.max()) for x in xs]
        if self.small_multiples and len(xs) >= 4:
            # One instance recorded for days would leave every other plot of the
            # grid a sliver against its left edge, so the grid opens on the
            # stretch most of the instances cover and leaves the rest to the
            # zoom; the hours boxes set it outright.
            lo, hi = float(np.quantile(starts, 0.1)), float(np.quantile(ends, 0.9))
        else:
            lo, hi = min(starts), max(ends)
        before, after = self._before.value(), self._after.value()
        if before > 0:
            lo = max(lo, -before)
        if after > 0:
            hi = min(hi, after)
        if hi <= lo:
            hi = lo + 1.0
        vb.setXRange(lo, hi, padding=0.02)

    def reset_views(self) -> None:
        self._x_range = None
        self._apply_x_range()

    # -- pointer

    def _highlight(self, index: int) -> None:
        """Bring one series to the front by width and fade the others; ``-1`` restores them all."""
        if index == self._hover:
            return
        self._hover = index
        for i, curves in self._curves.items():
            if i >= len(self._series):
                continue
            base = self._series[i].color
            color = QColor(base)
            faded = index >= 0 and i != index
            if faded:
                color.setAlpha(FADE_ALPHA)
                pen = pg.mkPen(color, width=1.0)
            elif i == index:
                pen = pg.mkPen(color, width=2.6)
            else:
                pen = pg.mkPen(color, width=1.2)
            # A histogram outline carries a wash under it, which has to fade
            # with its line or the faded curve stays the loudest thing on the
            # plot. Setting a fill brush on a curve that has no fill level (
            # a trace, a spectrum) does nothing, so this needs no test.
            fill = histogram_fill(base)
            if faded:
                fill.setAlpha(max(fill.alpha() * FADE_ALPHA // 255, 8))
            for curve in curves:
                if isinstance(curve, Trace):
                    curve.set_state("faded" if faded else "front" if i == index else "normal")
                    continue
                curve.setPen(pen)
                curve.setFillBrush(pg.mkBrush(fill))

    def _series_at(self, pos) -> tuple[int, int, float] | None:
        """The plot under a scene position, the series nearest it there (or -1) and the x under it.

        ``None`` when the position is over no plot at all.
        """
        for k, (plot, drawn) in enumerate(zip(self._plots, self._plot_series)):
            vb = plot.getViewBox()
            if not vb.sceneBoundingRect().contains(pos):
                continue
            point = vb.mapSceneToView(pos)
            px_per_y = vb.viewPixelSize()[1]
            best, best_px = -1, HOVER_PX
            for i, x, y in drawn:
                j0 = int(np.searchsorted(x, point.x()))
                candidates = [j for j in (j0 - 1, j0) if 0 <= j < len(x)]
                for j in candidates:
                    if np.isnan(y[j]):
                        continue
                    distance = abs(y[j] - point.y()) / px_per_y if px_per_y > 0 else np.inf
                    if distance < best_px:
                        best, best_px = i, distance
            return k, best, float(point.x())
        return None

    def _on_mouse_moved(self, pos) -> None:
        """Name the line nearest the pointer, and read the instance at that moment."""
        found = self._series_at(pos)
        if found is None:
            self._highlight(-1)
            self.status.emit(self.hint())
            return
        k, best, x = found
        self._highlight(best)
        if best >= 0:
            self.status.emit(self._describe(best, self._plots[k], x))
        else:
            self.status.emit(self.hint())

    def _on_mouse_clicked(self, event) -> None:
        """Open the instance clicked in its own window, on the sensor of the plot clicked.

        A small plot holds one instance, so a click anywhere in it names it; an
        overlaid plot holds many, and the one opened is the line the hover has
        named, the one nearest the pointer. A pooled curve stands for many
        instances and opens none.
        """
        if event.button() != Qt.MouseButton.LeftButton or event.double() or self.overall:
            return
        found = self._series_at(event.scenePos())
        if found is None:
            return
        k, best, _x = found
        drawn = self._plot_series[k]
        if self.small_multiples and len(drawn) == 1:
            best = drawn[0][0]
        if best < 0:
            return
        event.accept()
        series = self._series[best]
        self.open_instance(series.well, series.position, self._plot_features[k])

    def _describe(self, index: int, plot, hours: float | None) -> str:
        series = self._series[index]
        members = self._pool.get(index)
        # A pooled curve stands for many instances, so naming the one whose
        # position it happens to carry would be a lie.
        parts = [self.pool_headline(members) if members else self.series_headline(series)]
        if hours is not None and self.domain != "time":
            # Off the time axis the coordinate under the pointer is a reading or a period.
            x = hours
            drawn = next(
                (entry for k, entry in enumerate(self._plot_series) if self._plots[k] is plot), []
            )
            own = next((row for row in drawn if row[0] == index), None)
            if self.domain == "distribution":
                if own is not None:
                    _i, centers, share = own
                    k = int(np.clip(np.searchsorted(centers, x), 0, len(centers) - 1))
                    parts.append(f"around {centers[k]:.4g}: {share[k]:.1f} % of its samples")
                peak = self._peaks_by_plot.get((id(plot), index))
                if peak is not None:
                    parts.append(f"peak ▾ at {peak[0]:.4g}, {peak[1]:.1f} % of its samples")
            else:
                if own is not None:
                    _i, log_periods, log_power = own
                    k = int(np.clip(np.searchsorted(log_periods, x), 0, len(log_periods) - 1))
                    parts.append(
                        f"period {format_period(10 ** log_periods[k])}: power {10 ** log_power[k]:.3g}"
                    )
                    spectrum = self._spectra_by_plot.get((id(plot), index))
                    if spectrum is not None:
                        parts.append(caption_for(spectrum, ""))
            return " | ".join(parts)
        if hours is not None:
            stamp = series.onset + pd.Timedelta(hours=hours)
            frame = series.frame
            parts.append(f"t = {hours:+.2f} h ({stamp:%Y-%m-%d %H:%M:%S})")
            if frame.index[0] <= stamp <= frame.index[-1]:
                i = min(
                    int(frame.index.searchsorted(at_index_unit(frame, stamp), side="right")) - 1,
                    len(frame) - 1,
                )
                klass = column_as_float(frame, "class")[i]
                state = column_as_float(frame, "state")[i]
                parts.append(
                    f"{label_name(klass, self.info.fault_names, self.info.transient_offset)} / "
                    f"{state_name(state)}"
                )
                readings = []
                for feature in self.read_out_features():
                    if feature in frame.columns:
                        value = column_as_float(frame, feature)[i] * self.info.shown_scale(feature)
                        unit = self.info.shown_unit(feature)
                        readings.append(
                            f"{feature} = {'-' if np.isnan(value) else f'{value:.4g} {unit}'.rstrip()}"
                        )
                if readings:
                    parts.append(", ".join(readings))
            else:
                parts.append("outside the instance")
        return " | ".join(parts)

    def read_out_features(self) -> list[str]:
        """The sensors the status bar reads at the moment under the pointer."""
        return sorted({section.feature for section in self.sections()})
