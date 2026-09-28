"""The availability page: which sensors the real instances recorded, as one matrix.

Two matrices, chosen in the *Matrix* box, over the same bars.

**Sensor availability** puts one row per group of bars (a fault class, a well,
or the instances of one well or of one class one by one) and one column per
sensor; in every cell the share of the group's samples, or of its bars, in
which the sensor is live, frozen and absent, side by side (see
``availability``). A last row folds every bar shown, so the page also says what
the dataset as a whole recorded, and the sensors can be ordered by that.

**Sensor pairs** puts the sensors on both axes and asks a question no column of
the first matrix answers: how often two sensors carry a reading *at the same
instant*. Two sensors can each cover half a recording and never overlap, and a
pair with little coverage is one no model can lean on and a correlation nobody
should trust: Rabelo's figure 2.10.

Hovering anything puts the figures behind it in the status bar and in a tooltip
where the pointer is, a printed availability map writing that figure inside
every cell. Clicking a fault class or a well opens its instances as the rows,
and clicking an instance opens its time series with that sensor drawn.

Four boxes change the picture rather than the grouping. *Cells* counts by
samples or by bars. *Available from* sets the share of samples a sensor needs
readings in to count as available in a bar at all, so that Rabelo's rule, an
instance whose P-TPT is more than half missing is dropped, can be read off the
matrix. *Join overlapping instances* makes the bars the merged recordings the
timelines draw when joined, in which a sample two windows share is counted
once; the footers of the files cannot say which instants two windows share, so
the first tick reads the data, behind a progress dialog, and keeps the result
in the cache. *Measured vs filled* splits the live share of every cell into
the samples that were measured and the samples the historian filled in
between measurements (``algorithms.interpolation``), which takes the pass that
profiles every instance, likewise once and cached.

The page is well-wise, fault-wise and feature-wise at once because they are
three groupings of the same bars, and the Rows box is where the grouping is
chosen.
"""

import numpy as np
import pandas as pd
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSpinBox,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from overlap_viewer.algorithms.cleaning import Cleaned, CleanRule
from overlap_viewer.algorithms.correlation import (
    COEFFICIENTS,
    MIN_PAIRS,
    CorrelationPass,
    Correlations,
)
from overlap_viewer.algorithms.interpolation import format_spacing
from overlap_viewer.backend import theme
from overlap_viewer.backend.availability import (
    ABSENT,
    FROZEN,
    LIVE,
    Availability,
    AvailabilityTable,
    JoinedStats,
    PairCoverage,
    PairTable,
)
from overlap_viewer.backend.dataset import (
    DatasetInfo,
    PairCounts,
    ScanCancelled,
    WellData,
    merge_instances,
    well_label,
)
from overlap_viewer.backend.extras import missing
from overlap_viewer.backend.palette import bar_color, fault_color, tint
from overlap_viewer.backend.profiles import Profiles
from overlap_viewer.frontend.heatmap import ColorKey, HeatmapRow, HeatmapWidget, StateKey
from overlap_viewer.frontend.items import IMPLAUSIBLE_MARK, ORDER_MARK
from overlap_viewer.frontend.loading import (
    joined_stats_with_progress,
    pair_counts_with_progress,
    profiles_with_progress,
    progress_dialog,
)
from overlap_viewer.frontend.overview import describe_instance
from overlap_viewer.frontend.passes import Passes

MATRICES = ("Sensor availability", "Sensor pairs", "Sensor correlations")
MODES = ("Fault classes", "Wells", "Instances of one well", "Instances of one fault class")
ORDERS = ("Dataset order", "By coverage")
# Only the pair map can be ordered by what goes with what: it is the only one
# that knows which sensors are recorded at the same instant.
GROUPED = "Grouped by co-occurrence"
WEIGHTS = ("Share of samples", "Share of instances")
COUNTS = ("Both live", "Both recorded")

HINT = (
    "Hover a cell for the figures behind it | click a fault class or a well to see its instances "
    "one by one, an instance to open its time series with that sensor drawn | every column is a "
    "sensor, every row what the Rows box says | F1 for help"
)
PAIR_HINT = (
    "Every cell is a pair of sensors: the share of the samples in which both carry a reading at "
    "the same instant | hover one for the figures behind it | the diagonal is each sensor's own "
    "coverage | F1 for help"
)
CORR_HINT = (
    "Every cell is a pair of sensors: how they move together over the samples of the instances "
    "on show, pooled | blue positive, amber negative, full at ±1 | hover one for all three "
    "coefficients | F1 for help"
)


def _coefficient(value: float, name: str) -> str:
    """A coefficient to two digits: Pearson signed, the two others never negative."""
    return f"{value:+.2f}" if name == "Pearson" else f"{value:.2f}"


CORR_TIP = (
    "Which coefficient the cells show. Pearson: the linear correlation over every co-valid "
    "sample of the instances in the scope, pooled. Mutual information: Laarne's coefficient "
    "√(1 − e⁻²ᴵ) of the mutual information estimated by nearest neighbours on an even subsample "
    "of the same samples, 0 for independent variables and 1 for a deterministic relation, equal "
    "to |Pearson| when the two are jointly Gaussian. Nonlinear: what the second says beyond the "
    "first, ρ_I × (1 − |ρ|), Zhang's coefficient. All three after Melo (thesis §4.1.5)."
)


def _quantity(value: float, unit: str) -> str:
    return f"{value:.4g} {unit}".rstrip()


def _plural(n: int, noun: str) -> str:
    return f"{n} {noun}{'' if n == 1 else 's'}"


def _unit_html(unit: str, color: str) -> str:
    return f' <span style="color:{color};">[{unit}]</span>' if unit else ""


class AvailabilityPage(QWidget):
    """The page: its toolbar, the title line with the key, the matrix, and what it says.

    Signals
    -------
    status(str)
        What the main window's status bar should say: the figures behind the
        cell under the pointer, or the page's hint.
    summary_changed()
        The one-line count of what is on show has changed.
    open_requested(int, int, object, bool)
        An instance was clicked: its well, its bar in that well's view, the
        sensor clicked (``None`` on the label), and whether the view is the
        joined one.
    """

    status = Signal(str)
    summary_changed = Signal()
    open_requested = Signal(int, int, object, bool)

    def __init__(self, info: DatasetInfo, passes: Passes | None = None, parent=None):
        super().__init__(parent)
        self.info = info
        # The passes over the data, shared with the other pages; without them
        # the page reads what it needs itself, behind the same dialogs.
        self._passes = passes
        self._catalogue: pd.DataFrame | None = None
        self._wells: list[WellData] = []
        self._well_by_number: dict[int, WellData] = {}
        self._plain: Availability | None = None
        self._joined: Availability | None = None
        self._joined_stats: JoinedStats | None = None
        self._pair_counts: PairCounts | None = None
        self._pairs: PairCoverage | None = None
        self._joined_pairs: PairCoverage | None = None
        self._profiles: Profiles | None = None
        self._cleaned: Cleaned | None = None  # the Toolkit's rule over the bars on show
        self._table: AvailabilityTable | None = None
        self._pair_table: PairTable | None = None
        self._rows: list[HeatmapRow] = []
        self._ids: list[tuple[str, object]] = []  # per row: what it stands for
        self._mask: np.ndarray | None = None  # the bars the rows are made of
        self._struck_counts: np.ndarray | None = None  # per cell, bars the rule discards it in
        # The correlation matrices computed so far, by (scope kind, scope key, joined).
        self._correlations: dict[tuple, Correlations] = {}
        self._corr: Correlations | None = None  # the one on show
        self._corr_order: list[int] = []  # its sensors in the order drawn

        # The keys of the three matrices are built before the toolbar, which shows
        # one of them and hides the others as soon as it knows which matrix it is on.
        self._key = StateKey(
            ("live", "filled", "frozen", "absent", "implausible", "order", "cleaned")
        )
        self._key.set_visible("filled", False)
        self._key.set_visible("order", False)
        self._key.set_visible("cleaned", False)
        self._pair_key = StateKey(("live", "absent"))
        self._pair_key.set_text("live", "both carry a reading at the same instant")
        self._pair_key.set_text("absent", "not both")
        self._corr_key = ColorKey()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self._build_toolbar())

        # The title of the matrix, with the key of its cells at the right: a row
        # of its own, as the color key of the timelines is, so that it can never
        # be crowded out of a toolbar on a narrow window.
        heading = QWidget()
        heading_layout = QHBoxLayout(heading)
        heading_layout.setContentsMargins(8, 2, 8, 0)
        heading_layout.setSpacing(16)
        self._title = QLabel()
        self._title.setWordWrap(True)
        heading_layout.addWidget(self._title, 1)
        heading_layout.addWidget(self._key, 0, Qt.AlignmentFlag.AlignTop)
        heading_layout.addWidget(self._pair_key, 0, Qt.AlignmentFlag.AlignTop)
        heading_layout.addWidget(self._corr_key, 0, Qt.AlignmentFlag.AlignTop)
        layout.addWidget(heading)

        self._heatmap = HeatmapWidget()
        self._heatmap.hovered.connect(self._on_hovered)
        self._heatmap.clicked.connect(self._on_clicked)
        self._heatmap.set_tooltip_provider(self.tooltip)
        self._scroll = QScrollArea()
        # Resizable, so that the matrix is handed the width of the window and
        # spreads its columns over it; its minimum size keeps it scrollable.
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._scroll.setWidget(self._heatmap)
        layout.addWidget(self._scroll, 1)
        self.apply_theme()

    # -- construction

    def _build_toolbar(self) -> QToolBar:
        bar = QToolBar("Availability")
        bar.setMovable(False)
        # Which controls belong to which matrix; the rest are shared.
        self._availability_only: list = []
        self._pairs_only: list = []

        bar.addWidget(QLabel(" Matrix "))
        self._matrix = QComboBox()
        self._matrix.addItems(list(MATRICES))
        self._matrix.setToolTip(
            "What the matrix is about: what each group of instances recorded of every sensor; how "
            "often two sensors carry a reading at the same instant; or how two sensors move "
            "together over the samples they share, as Pearson, mutual-information and nonlinear "
            "coefficients."
        )
        self._matrix.currentIndexChanged.connect(self._on_matrix_changed)
        bar.addWidget(self._matrix)

        bar.addSeparator()
        self._availability_only.append(bar.addWidget(QLabel(" Rows ")))
        self._mode = QComboBox()
        self._mode.addItems(list(MODES))
        self._mode.setToolTip(
            "What the rows of the matrix are: the fault classes, the wells, or the instances of "
            "one well or of one fault class, one row each, in chronological order."
        )
        self._mode.currentIndexChanged.connect(self._on_mode_changed)
        self._availability_only.append(bar.addWidget(self._mode))
        self._subject_label = QLabel(" of ")
        self._subject_action = bar.addWidget(self._subject_label)
        self._subject = QComboBox()
        self._subject.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self._subject.currentIndexChanged.connect(self._refresh)
        self._subject_combo_action = bar.addWidget(self._subject)

        # The scope serves the pair map and the correlations alike.
        self._scope_actions = [bar.addWidget(QLabel(" Over "))]
        self._scope = QComboBox()
        self._scope.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self._scope.setToolTip(
            "The instances the pairs, or the correlations, are taken over: all of them, those of "
            "one fault class, or those of one well."
        )
        self._scope.currentIndexChanged.connect(self._refresh)
        self._scope_actions.append(bar.addWidget(self._scope))

        bar.addSeparator()
        bar.addWidget(QLabel(" Sensors "))
        self._order = QComboBox()
        # It grows a third entry in the pair map, and must show it whole.
        self._order.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self._order.addItems(list(ORDERS))
        self._order.setToolTip(
            "The order of the columns: the order the dataset declares its variables in, or by "
            "how much of what is on show each sensor is live in, most first. The pair map can "
            "also lay the sensors out so that those recorded at the same instant sit together, "
            "which turns its blocks into the sets of sensors a well carries or lacks together."
        )
        self._order.currentIndexChanged.connect(self._refresh)
        bar.addWidget(self._order)

        bar.addSeparator()
        self._availability_only.append(bar.addWidget(QLabel(" Cells ")))
        self._weight = QComboBox()
        self._weight.addItems(list(WEIGHTS))
        self._weight.setToolTip(
            "What a cell splits: the samples of its row, so that a six-day instance weighs more "
            "than a six-hour one (as Rabelo counts); or its instances, each weighing the same "
            "(as Rozo counts). The two disagree because instances range from hours to days."
        )
        self._weight.currentIndexChanged.connect(self._refresh)
        self._availability_only.append(bar.addWidget(self._weight))
        self._split = QCheckBox("Measured vs filled")
        self._split.setToolTip(
            "Split the live share of every cell into the samples that were measured (solid) and "
            "the samples the historian filled in between measurements (pale): the straight lines "
            "it drew from one reading to the next, and the readings it carried forward. Most "
            "sensors of 3W were read every ten seconds or every two minutes, so on the 1 Hz "
            "grid one live sample in sixteen is a measurement. Hover a cell for the share and the "
            "interval. The first tick reads every instance in full, behind a progress dialog, "
            "and keeps the result in the cache; the split is of samples, so it rests while the "
            "cells count instances."
        )
        self._split.toggled.connect(self._on_split_toggled)
        self._availability_only.append(bar.addWidget(self._split))

        self._clean = QCheckBox("Toolkit's CleanSignals")
        self._clean.setToolTip(
            "Mark, in every cell, the sensors the 3W Toolkit's CleanSignals rule would set to "
            "missing in at least one instance of the row, and grey the columns it would drop "
            "altogether. The rule is fitted on the instances on show: per sensor, bounds at the "
            "quartiles of the instances' means and spreads plus or minus a multiple of the "
            "interquartile range; an instance whose mean or spread falls outside them loses the "
            "sensor, a spread below 1e-6 always does, and a sensor missing in enough of the "
            "instances is dropped from all of them. The valve states are exempt. Hover a cell for "
            "how many instances and which bound; the two boxes beside move the thresholds. Needs "
            "the profile pass, read once and cached."
        )
        self._clean.toggled.connect(self._on_clean_toggled)
        self._availability_only.append(bar.addWidget(self._clean))
        self._clean_actions = [bar.addWidget(QLabel(" IQR × "))]
        self._iqr = QDoubleSpinBox()
        self._iqr.setRange(0.5, 20.0)
        self._iqr.setSingleStep(0.5)
        self._iqr.setDecimals(1)
        self._iqr.setValue(CleanRule().iqr_factor)
        self._iqr.setToolTip(
            "The multiple of the interquartile range the bounds sit beyond the quartiles; the "
            "Toolkit's default is 3."
        )
        self._iqr.valueChanged.connect(self._on_clean_rule_changed)
        self._clean_actions.append(bar.addWidget(self._iqr))
        self._clean_actions.append(bar.addWidget(QLabel(" drop if missing in ≥ ")))
        self._missing = QSpinBox()
        self._missing.setRange(1, 100)
        self._missing.setSingleStep(10)
        self._missing.setSuffix(" %")
        self._missing.setValue(round(CleanRule().missing_share * 100))
        self._missing.setToolTip(
            "A sensor entirely missing in at least this share of the instances is dropped from all "
            "of them; the Toolkit's default is 60 %."
        )
        self._missing.valueChanged.connect(self._on_clean_rule_changed)
        self._clean_actions.append(bar.addWidget(self._missing))
        for action in self._clean_actions:
            self._availability_only.append(action)
            action.setVisible(False)

        self._pairs_only.append(bar.addWidget(QLabel(" Count ")))
        self._count = QComboBox()
        self._count.addItems(list(COUNTS))
        self._count.setToolTip(
            "What a pair has to satisfy in an instance for that instance to count: both sensors "
            "live there, so that a dead instrument and a sensor below the availability threshold "
            "contribute nothing; or merely both recorded, every sample carrying two readings, "
            "which is how Rabelo counts."
        )
        self._count.currentIndexChanged.connect(self._refresh)
        self._pairs_only.append(bar.addWidget(self._count))

        self._corr_only: list = [bar.addWidget(QLabel(" Coefficient "))]
        self._coefficient = QComboBox()
        self._coefficient.addItems(list(COEFFICIENTS))
        self._coefficient.setToolTip(CORR_TIP)
        reason = missing("analysis")
        if reason is not None:
            for k in (1, 2):
                item = self._coefficient.model().item(k)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
                item.setToolTip(reason)
        self._coefficient.currentIndexChanged.connect(self._refresh)
        self._corr_only.append(bar.addWidget(self._coefficient))

        bar.addWidget(QLabel(" Available from "))
        self._threshold = QSpinBox()
        self._threshold.setRange(0, 100)
        self._threshold.setSingleStep(10)
        self._threshold.setSuffix(" % of samples")
        self._threshold.setToolTip(
            "The share of its samples a sensor needs readings in to count as available in an "
            "instance at all; below it the instance counts as absent for that sensor, readings "
            "and all. At 0 any reading counts. Rabelo's pipeline drops an instance whose P-TPT is "
            "more than half missing: set 50 to see what that rule keeps."
        )
        self._threshold.valueChanged.connect(self._on_threshold_changed)
        bar.addWidget(self._threshold)

        bar.addSeparator()
        self._join = QCheckBox("Join overlapping instances")
        self._join.toggled.connect(self._on_join_toggled)
        bar.addWidget(self._join)
        self._show_subject(False)
        self._sync_matrix_controls()
        return bar

    def _show_subject(self, shown: bool) -> None:
        first = not self.pairs and not self.correlations_on
        self._subject_action.setVisible(shown and first)
        self._subject_combo_action.setVisible(shown and first)

    def _sync_matrix_controls(self) -> None:
        """Show the controls of the matrix on show, and offer the orders it can be put in."""
        pairs, correlations = self.pairs, self.correlations_on
        first = not pairs and not correlations
        for action in self._availability_only:
            action.setVisible(first)
        for action in self._clean_actions:
            action.setVisible(first and self._clean.isChecked())
        for action in self._pairs_only:
            action.setVisible(pairs)
        for action in self._scope_actions:
            action.setVisible(pairs or correlations)
        for action in self._corr_only:
            action.setVisible(correlations)
        self._show_subject(self.mode.startswith("Instances"))
        self._join.setToolTip(
            "Count the bars the timelines draw when joined: the instances of a well that overlap "
            "with labels that agree, read as the single recording they were cut from, in which a "
            "sample two windows share is counted once and a sensor one window missed is filled in "
            "by another, which the pair map feels the most: two sensors that never share a "
            "sample inside one window often sharing plenty inside the recording the windows were "
            "cut from. The footers of the files cannot say which instants two windows share, so "
            "the first tick reads the data, behind a progress dialog, and keeps the result in the "
            "cache."
        )
        self._key.setVisible(first)
        self._pair_key.setVisible(pairs)
        self._corr_key.setVisible(correlations)
        # The grouped order belongs to the pair map alone, so it is offered and
        # withdrawn with it rather than sitting there greyed out.
        wanted = self._order.currentText()
        self._order.blockSignals(True)
        if pairs and self._order.count() == len(ORDERS):
            self._order.addItem(GROUPED)
        elif not pairs and self._order.count() > len(ORDERS):
            self._order.removeItem(len(ORDERS))
        found = self._order.findText(wanted)
        self._order.setCurrentIndex(max(found, 0))
        self._order.blockSignals(False)

    # -- appearance

    def apply_theme(self) -> None:
        """Take the colors of the theme now in force: the keys, the title, the matrix."""
        colors = theme.current()
        self._title.setStyleSheet(f"color: {colors.muted}; font-size: 9pt;")
        self._key.apply_theme()
        self._pair_key.apply_theme()
        self._corr_key.apply_theme()
        self._heatmap.update()

    # -- data

    @property
    def threshold(self) -> float:
        return self._threshold.value() / 100.0

    @property
    def pairs(self) -> bool:
        """Whether the matrix on show is the pair map."""
        return self._matrix.currentIndex() == 1

    @property
    def correlations_on(self) -> bool:
        """Whether the matrix on show is the correlation matrix."""
        return self._matrix.currentIndex() == 2

    @property
    def coefficient(self) -> str:
        return self._coefficient.currentText()

    @property
    def live_pairs(self) -> bool:
        return self._count.currentIndex() == 0

    @property
    def joined(self) -> bool:
        """Whether the bars are the merged recordings rather than the instances themselves."""
        return self._join.isChecked() and self._joined is not None

    @property
    def split(self) -> bool:
        """Whether the live share of a cell is split into measured and filled samples."""
        return self._split.isChecked() and self._profiles is not None and not self.by_instances

    @property
    def cleaning_on(self) -> bool:
        """Whether the Toolkit's rule marks the cells."""
        return self._clean.isChecked() and self._cleaned is not None

    @property
    def clean_rule(self) -> CleanRule:
        return CleanRule(iqr_factor=self._iqr.value(), missing_share=self._missing.value() / 100.0)

    @property
    def availability(self) -> Availability | None:
        """The bars on show: the instances, or the merged recordings."""
        return self._joined if self.joined else self._plain

    @property
    def pair_coverage(self) -> PairCoverage | None:
        """The pair counts of the bars on show."""
        return self._joined_pairs if self.joined else self._pairs

    def hint(self) -> str:
        """What the status bar says when the pointer is over nothing in particular."""
        if self.correlations_on:
            return CORR_HINT
        return PAIR_HINT if self.pairs else HINT

    def set_catalogue(self, catalogue: pd.DataFrame, wells: list[WellData]) -> None:
        """Take a new catalogue and its wells, keeping what the user had chosen where it still exists."""
        self._catalogue = catalogue
        self._wells = list(wells)
        self._well_by_number = {well.well: well for well in self._wells}
        self._joined_stats = None
        self._joined = None
        self._joined_pairs = None
        self._pair_counts = None
        self._pairs = None
        self._profiles = None
        self._cleaned = None
        self._correlations = {}
        self._corr = None
        self._rebuild_plain()
        self._fill_subjects()
        self._fill_scopes()
        if not self._ensure_data():
            self._fall_back()
        self._refresh()

    def _rebuild_plain(self) -> None:
        """Read what every instance recorded, under the threshold in force.

        Profiles an earlier session left in the cache are taken up without
        reading the data, for the marks of the pressures out of order.
        """
        if self._profiles is None and self._passes is not None:
            self._profiles = self._passes.profiles_if_loaded(self.info.sensor_names)
        self._plain = Availability.from_wells(
            self._wells, self.info, self.threshold, profiles=self._profiles
        )
        if self._pair_counts is not None:
            self._pairs = PairCoverage.from_counts(self._plain, self._pair_counts)

    def _rebuild_joined(self) -> None:
        """Read what every merged recording holds, under the threshold in force."""
        self._joined = Availability.from_wells(
            [well.joined() for well in self._wells],
            self.info,
            self.threshold,
            self._joined_stats,
            profiles=self._profiles,
        )
        self._joined_pairs = PairCoverage.from_joined(self._joined, self._joined_stats)

    def _set_join_checked(self, checked: bool) -> None:
        self._join.blockSignals(True)
        self._join.setChecked(checked)
        self._join.blockSignals(False)

    def _set_split_checked(self, checked: bool) -> None:
        self._split.blockSignals(True)
        self._split.setChecked(checked)
        self._split.blockSignals(False)

    def _load_joined(self) -> bool:
        """Have the merged figures on hand, reading the data if need be; ``False`` if cancelled."""
        if self._plain is None:
            return False
        if self._joined_stats is None:
            if self._passes is not None:
                self._joined_stats = self._passes.joined_stats(
                    self._plain.sensors, parent=self.window()
                )
            else:
                try:
                    self._joined_stats = joined_stats_with_progress(
                        self.info, self._wells, self._plain.sensors, parent=self.window()
                    )
                except ScanCancelled:
                    self._joined_stats = None
            if self._joined_stats is None:
                return False
        self._rebuild_joined()
        return True

    def _load_pairs(self) -> bool:
        """Have the pair counts on hand, reading the data if need be; ``False`` if cancelled."""
        if self._plain is None:
            return False
        if self._pair_counts is None:
            if self._passes is not None:
                self._pair_counts = self._passes.pair_counts(
                    self._plain.sensors, parent=self.window()
                )
            else:
                try:
                    self._pair_counts = pair_counts_with_progress(
                        self.info, self._plain.sensors, parent=self.window()
                    )
                except ScanCancelled:
                    self._pair_counts = None
            if self._pair_counts is None:
                return False
        self._pairs = PairCoverage.from_counts(self._plain, self._pair_counts)
        return True

    def _load_profiles(self) -> bool:
        """Have the profiles of every instance and bar on hand; ``False`` if the user cancels the pass.

        The profiles split the live readings of every bar into measured and
        filled, so both availabilities are built again with them.
        """
        if self._profiles is not None:
            return True
        sensors = self.info.sensor_names
        if self._passes is not None:
            self._profiles = self._passes.profiles(sensors, parent=self.window())
        else:
            try:
                self._profiles = profiles_with_progress(
                    self.info, self._wells, sensors, parent=self.window()
                )
            except ScanCancelled:
                self._profiles = None
        if self._profiles is None:
            return False
        self._rebuild_plain()
        if self._joined_stats is not None:
            self._rebuild_joined()
        return True

    def _load_cleaning(self) -> bool:
        """Have the Toolkit's verdicts over the bars on show; ``False`` if the profile pass is declined."""
        if not self._load_profiles():
            return False
        if self._passes is not None:
            self._cleaned = self._passes.cleaning(
                self.joined, self.clean_rule, parent=self.window()
            )
        else:
            from overlap_viewer.algorithms.cleaning import clean_profiles

            keys = self._event_keys()
            self._cleaned = clean_profiles(
                self._profiles, keys, self.joined, self.info, self.clean_rule
            )
        return self._cleaned is not None

    def _event_keys(self) -> list:
        """The bars on show as the profile table keys them."""
        bars = self.availability.bars
        if self.joined:
            return [(int(w), int(b)) for w, b in zip(bars["well"], bars["bar"])]
        return [(int(fc), str(f)) for fc, f in zip(bars["fault_class"], bars["file"])]

    def _ensure_data(self) -> bool:
        """Have on hand what the matrix on show asks for; ``False`` when the user cancels a scan.

        Three of the choices need a pass over the data, and each keeps its
        own cache: the merged recordings of the joined view, the pair counts
        of the instances as they are, and the profiles behind the split of
        the live share and the Toolkit's rule.
        """
        if self._join.isChecked() and not self._load_joined():
            return False
        if self._split.isChecked() and not self._load_profiles():
            self._set_split_checked(False)
        if self._clean.isChecked() and not self._load_cleaning():
            self._clean.blockSignals(True)
            self._clean.setChecked(False)
            self._clean.blockSignals(False)
        if self.correlations_on and not self._load_correlations():
            return False
        return not (self.pairs and not self.joined and not self._load_pairs())

    def _scope_key(self) -> tuple:
        kind, key = self._scope.currentData() or ("all", -1)
        return (str(kind), int(key), self.joined)

    def _load_correlations(self) -> bool:
        """Have the correlations of the scope on show; reads its instances once. ``False`` if cancelled."""
        if self.availability is None:
            return False
        key = self._scope_key()
        if key in self._correlations:
            self._corr = self._correlations[key]
            return True
        availability = self.availability
        bars = availability.bars
        mask = self._scope_mask()
        taken = np.arange(len(bars)) if mask is None else np.flatnonzero(mask)
        # The analog sensors only: a valve state is a position, not a measurement,
        # and its two values would dominate the matrix without saying anything.
        analog = [
            k for k, name in enumerate(availability.sensors) if not self.info.is_enumerated(name)
        ]
        accumulator = CorrelationPass(
            [availability.sensors[k] for k in analog],
            [availability.ranges[k] for k in analog],
            len(taken),
        )
        dialog, progress = progress_dialog(
            f"Reading the {len(taken)} {'bars' if self.joined else 'instances'} of "
            f"{self._scope.currentText().split(' (')[0]} for their correlations…",
            self.window(),
        )
        try:
            for k, i in enumerate(taken, start=1):
                row = bars.iloc[int(i)]
                data = self._well_by_number[int(row["well"])]
                paths = data.origin.rows["path"]
                frames = [self._frame(paths.iloc[member]) for member in row["members"]]
                accumulator.add(merge_instances(frames) if len(frames) > 1 else frames[0])
                if not progress(k, len(taken), str(row["title"])):
                    return False
        finally:
            dialog.close()
            dialog.deleteLater()
        self._corr = self._correlations[key] = accumulator.result()
        return True

    def _frame(self, path) -> pd.DataFrame:
        """One instance, through the shared cache when there is one."""
        if self._passes is not None:
            return self._passes.frames.get(path)
        from overlap_viewer.backend.dataset import load_instance

        return load_instance(path)

    def _on_split_toggled(self, checked: bool) -> None:
        if checked and not self._load_profiles():
            self._set_split_checked(False)
        self._refresh()

    def _on_clean_toggled(self, checked: bool) -> None:
        if checked and not self._load_cleaning():
            self._clean.blockSignals(True)
            self._clean.setChecked(False)
            self._clean.blockSignals(False)
        self._sync_matrix_controls()
        self._refresh()

    def _on_clean_rule_changed(self, *args) -> None:
        if self._clean.isChecked() and self._profiles is not None:
            self._load_cleaning()
        self._refresh()

    def _fall_back(self) -> None:
        """Show the matrix that needs no reading, the user having declined one."""
        self._set_join_checked(False)
        self._matrix.blockSignals(True)
        self._matrix.setCurrentIndex(0)
        self._matrix.blockSignals(False)
        self._sync_matrix_controls()

    def _on_matrix_changed(self, *args) -> None:
        if not self._ensure_data():
            self._matrix.blockSignals(True)
            self._matrix.setCurrentIndex(0)
            self._matrix.blockSignals(False)
        self._sync_matrix_controls()
        self._refresh()

    def _on_join_toggled(self, checked: bool) -> None:
        if not self._ensure_data():
            self._set_join_checked(not checked)
            self._ensure_data()
        # The rule is fitted on the bars on show, which just changed.
        if self._clean.isChecked() and self._profiles is not None:
            self._load_cleaning()
        self._refresh()

    def _on_threshold_changed(self, *args) -> None:
        if self._wells:
            self._rebuild_plain()
            if self._joined_stats is not None:
                self._rebuild_joined()
        self._refresh()

    @property
    def mode(self) -> str:
        return MODES[self._mode.currentIndex()]

    def _on_mode_changed(self, *args) -> None:
        self._fill_subjects()
        self._refresh()

    def _fill_subjects(self) -> None:
        """List, in the second box, the wells or the fault classes the rows can be the instances of."""
        mode = self.mode
        wanted = self._subject.currentData()
        self._subject.blockSignals(True)
        self._subject.clear()
        if self._catalogue is not None and mode == "Instances of one well":
            counts = self._catalogue["well"].value_counts()
            for well in sorted(counts.index):
                self._subject.addItem(
                    f"{well_label(int(well))} ({_plural(int(counts[well]), 'instance')})", int(well)
                )
        elif self._catalogue is not None and mode == "Instances of one fault class":
            counts = self._catalogue["fault_class"].value_counts()
            for fault in sorted(counts.index):
                name = self.info.fault_name(int(fault))
                self._subject.addItem(
                    f"{fault}. {name} ({_plural(int(counts[fault]), 'instance')})", int(fault)
                )
        index = self._subject.findData(wanted) if wanted is not None else -1
        self._subject.setCurrentIndex(max(index, 0))
        self._subject.blockSignals(False)
        self._show_subject(mode.startswith("Instances"))

    def _fill_scopes(self) -> None:
        """List, in the Over box, the instances the pair map can be counted over."""
        wanted = self._scope.currentData()
        self._scope.blockSignals(True)
        self._scope.clear()
        self._scope.addItem("All real instances", ("all", -1))
        if self._catalogue is not None:
            faults = self._catalogue["fault_class"].value_counts()
            if len(faults):
                self._scope.insertSeparator(self._scope.count())
            for fault in sorted(faults.index):
                self._scope.addItem(
                    f"{fault}. {self.info.fault_name(int(fault))} "
                    f"({_plural(int(faults[fault]), 'instance')})",
                    ("class", int(fault)),
                )
            wells = self._catalogue["well"].value_counts()
            if len(wells):
                self._scope.insertSeparator(self._scope.count())
            for well in sorted(wells.index):
                self._scope.addItem(
                    f"{well_label(int(well))} ({_plural(int(wells[well]), 'instance')})",
                    ("well", int(well)),
                )
        # Asked for nothing in particular, the search must not run: a separator
        # carries no data of its own, and looking for none of it finds one.
        index = self._scope.findData(wanted) if wanted is not None else -1
        self._scope.setCurrentIndex(max(index, 0))
        self._scope.blockSignals(False)

    def show_instances_of(self, kind: str, key: int) -> None:
        """Make the rows the instances of one ``well`` or one fault ``class``."""
        mode = "Instances of one well" if kind == "well" else "Instances of one fault class"
        self._mode.blockSignals(True)
        self._mode.setCurrentIndex(MODES.index(mode))
        self._mode.blockSignals(False)
        self._fill_subjects()
        index = self._subject.findData(int(key))
        if index >= 0 and index != self._subject.currentIndex():
            self._subject.setCurrentIndex(index)  # refreshes through the signal
        else:
            self._refresh()

    # -- the availability matrix

    def _build(
        self,
    ) -> tuple[list[HeatmapRow], list[tuple[str, object]], AvailabilityTable, np.ndarray | None]:
        """The rows the Rows box asks for, their meaning, their table with its total, and their mask."""
        availability, info = self.availability, self.info
        bars = availability.bars
        mode = self.mode
        noun = "bar" if self.joined else "instance"
        mask: np.ndarray | None = None
        rows: list[HeatmapRow] = []
        ids: list[tuple[str, object]] = []
        if mode == "Fault classes":
            keys = [int(k) for k in bars["fault_class"]]
            order = sorted(set(keys))
            table = availability.grouped(keys, order)
            rows = [HeatmapRow(f"{k}. {info.fault_name(k)}", fault_color(k)) for k in order]
            ids = [("class", k) for k in order]
            total_label = f"All real {noun}s"
        elif mode == "Wells":
            keys = [int(w) for w in bars["well"]]
            order = sorted(set(keys))
            table = availability.grouped(keys, order)
            rows = [HeatmapRow(well_label(w)) for w in order]
            ids = [("well", w) for w in order]
            total_label = f"All real {noun}s"
        else:
            column = "well" if mode == "Instances of one well" else "fault_class"
            subject = self._subject.currentData()
            if subject is None:  # an empty catalogue: nothing to list
                subject = -1
            mask = bars[column].to_numpy() == subject
            positions = np.flatnonzero(mask).tolist()
            table = availability.grouped(range(len(bars)), positions, mask)
            for position in positions:
                row = bars.iloc[position]
                rows.append(
                    HeatmapRow(
                        str(row["title"]), bar_color(int(row["fault_class"]), str(row["reach"]))
                    )
                )
                ids.append(("bar", position))
            what = well_label(int(subject)) if column == "well" else info.fault_name(int(subject))
            total_label = f"{what}: all {_plural(len(positions), noun)}"
        total = availability.total("total", mask=mask)
        table = table.stacked(total)
        rows.append(HeatmapRow(total_label, None, emphasized=True))
        ids.append(("total", None))
        if self._order.currentText() == "By coverage":
            table = table.with_columns(table.coverage_order(by_instances=self.by_instances))
        return rows, ids, table, mask

    @property
    def by_instances(self) -> bool:
        return self._weight.currentIndex() == 1

    # -- the pair matrix

    def _scope_mask(self) -> np.ndarray | None:
        """Which bars the pair map is counted over, ``None`` for all of them."""
        kind, key = self._scope.currentData() or ("all", -1)
        bars = self.availability.bars
        if kind == "class":
            return bars["fault_class"].to_numpy() == key
        if kind == "well":
            return bars["well"].to_numpy() == key
        return None

    def _build_pairs(self) -> PairTable:
        table = self.pair_coverage.table(
            self.availability, self._scope_mask(), live_only=self.live_pairs
        )
        order = self._order.currentText()
        if order == GROUPED:
            table = table.with_order(table.grouped_order())
        elif order == "By coverage":
            table = table.with_order(table.coverage_order())
        return table

    # -- drawing

    def _refresh(self, *args) -> None:
        if self.availability is None:
            return
        if self.correlations_on:
            if not self._load_correlations():
                self._fall_back()
                self._refresh_availability()
            else:
                self._refresh_correlations()
        elif self.pairs and self.pair_coverage is not None:
            self._refresh_pairs()
        else:
            self._refresh_availability()
        self.status.emit(self.hint())
        self.summary_changed.emit()

    # -- the correlation matrix

    def _corr_fill(self, value: float) -> str | None:
        """The color of one coefficient: blue for positive, amber for negative, full at one."""
        if not np.isfinite(value):
            return None
        colors = theme.current()
        strength = min(abs(float(value)), 1.0)
        hue = colors.live if value >= 0 else colors.warning
        return tint(hue, 0.06 + 0.94 * strength)

    def _refresh_correlations(self) -> None:
        corr = self._corr
        matrix = corr.matrix(self.coefficient)
        n = len(corr.sensors)
        order = list(range(n))
        if self._order.currentText() == "By coverage":
            own = np.diag(corr.pairs)
            order = sorted(order, key=lambda j: (-own[j], j))
        self._corr_order = order
        sensors = [corr.sensors[j] for j in order]
        if matrix is None:
            fills = [[None] * n for _ in range(n)]
        else:
            fills = [[self._corr_fill(matrix[i, j]) for j in order] for i in order]
        self._rows = [HeatmapRow(name) for name in sensors]
        self._ids = [("sensor", j) for j in order]
        self._mask = self._scope_mask()  # so that the export covers the scope
        present = corr.present()
        muted = [k for k, j in enumerate(order) if not present[j]]
        self._heatmap.set_fills(self._rows, sensors, fills, muted)
        colors = theme.current()
        ground = colors.block_fill
        if self.coefficient == "Pearson":
            entries = [
                (colors.live, "positive, full at +1"),
                (colors.warning, "negative, full at −1"),
                (ground, f"fewer than {MIN_PAIRS} co-valid samples"),
            ]
        else:
            entries = [
                (colors.live, f"{self.coefficient.lower()} coefficient, full at 1"),
                (ground, f"fewer than {MIN_PAIRS} co-valid samples, or the extra missing"),
            ]
        self._corr_key.set_entries(entries)
        self._title.setText(self._corr_title_text())

    def _corr_title_text(self) -> str:
        corr = self._corr
        linear, nonlinear = corr.global_coefficients()
        scope = self._scope.currentText().split(" (")[0] or "All real instances"
        noun = "bars" if self.joined else "instances"
        parts = [
            (
                f"Per pair of sensors: the {self.coefficient} coefficient over the samples of the "
                f"{corr.n_instances} {noun} of {scope}, pooled"
            ),
        ]
        if np.isfinite(linear):
            summary = f"global linear coefficient {linear:.2f}"
            if np.isfinite(nonlinear):
                summary += f", nonlinear {nonlinear:.2f}"
            parts.append(summary + " (Melo, eqs. 4.16 and 4.15)")
        if corr.mi_coefficient is not None and corr.mi_samples:
            parts.append(f"mutual information estimated on {corr.mi_samples:,} rows")
        elif self.coefficient != "Pearson":
            parts.append("mutual information needs the 'analysis' extra")
        if self._scope_key()[0] in ("all", "class"):
            parts.append(
                "pooling wells mixes their levels into the coefficients; pick one well to see the "
                "process alone"
            )
        else:
            parts.append(
                "pooled over the well's instances, so its shut-ins and restarts move every sensor "
                "together"
            )
        return " | ".join(parts)

    def _corr_values(self, row: int, column: int) -> dict[str, float]:
        corr = self._corr
        i, j = self._corr_order[row], self._corr_order[column]
        values = {"Pearson": float(corr.pearson[i, j])}
        if corr.mi_coefficient is not None:
            values["Mutual information"] = float(corr.mi_coefficient[i, j])
            values["Nonlinear"] = float(corr.nonlinear[i, j])
        values["pairs"] = float(corr.pairs[i, j])
        return values

    def _describe_corr(self, row: int, column: int) -> str:
        """One line about a cell, a row or a column of the correlation matrix."""
        corr = self._corr
        if row < 0 or column < 0:
            k = column if row < 0 else row
            j = self._corr_order[k]
            name = corr.sensors[j]
            rho = corr.pearson[j].copy()
            rho[j] = np.nan
            own = int(corr.pairs[j, j])
            if np.isfinite(rho).any():
                partner = int(np.nanargmax(np.abs(rho)))
                strongest = f"strongest with {corr.sensors[partner]}: Pearson {rho[partner]:+.2f}"
            else:
                strongest = "too few co-valid samples with any other sensor"
            return f"{name} | {own:,} samples in the scope | {strongest}"
        a = corr.sensors[self._corr_order[row]]
        b = corr.sensors[self._corr_order[column]]
        values = self._corr_values(row, column)
        if values["pairs"] < MIN_PAIRS:
            return f"{a} × {b} | only {int(values['pairs']):,} co-valid samples: nothing to say"
        parts = [f"{a} × {b}", f"Pearson {values['Pearson']:+.2f}"]
        if "Mutual information" in values:
            parts.append(f"mutual-information coefficient {values['Mutual information']:.2f}")
            parts.append(f"nonlinear {values['Nonlinear']:.2f}")
        parts.append(f"over {int(values['pairs']):,} co-valid samples")
        return " | ".join(parts)

    def _corr_tooltip(self, row: int, column: int) -> str:
        """The tooltip of a cell, a row or a column of the correlation matrix."""
        colors = theme.current()
        if row < 0 and column < 0:
            return ""
        if row < 0 or column < 0:
            return f"<b>{self._describe_corr(row, column)}</b>"
        corr = self._corr
        a = corr.sensors[self._corr_order[row]]
        b = corr.sensors[self._corr_order[column]]
        values = self._corr_values(row, column)
        if values["pairs"] < MIN_PAIRS:
            return f'<b>{a} × {b}</b><br><span style="color:{colors.muted};">too few co-valid samples</span>'
        shown = values.get(self.coefficient, values["Pearson"])
        hue = colors.live if shown >= 0 else colors.warning
        lines = [
            f"<b>{a} × {b}</b>",
            (
                f'<span style="font-size:13pt; color:{hue};"><b>{_coefficient(shown, self.coefficient)}'
                f"</b></span> {self.coefficient}"
            ),
        ]
        rest = [
            f"{k} {_coefficient(v, k)}"
            for k, v in values.items()
            if k not in ("pairs", self.coefficient)
        ]
        if rest:
            lines.append(f'<span style="color:{colors.muted};">{" | ".join(rest)}</span>')
        lines.append(
            f'<span style="color:{colors.muted};">{int(values["pairs"]):,} co-valid samples</span>'
        )
        return "<br>".join(lines)

    def _refresh_availability(self) -> None:
        self._rows, self._ids, self._table, self._mask = self._build()
        shares = self._table.instance_shares if self.by_instances else self._table.shares
        split = self.split
        struck, muted = self._cleaning_marks()
        marks = np.where(self._table.implausible > 0, IMPLAUSIBLE_MARK, 0)
        ordered = self._table.out_of_order is not None
        if ordered:
            marks |= np.where(self._table.out_of_order > 0, ORDER_MARK, 0)
        self._heatmap.set_matrix(
            self._rows,
            self._table.sensors,
            shares,
            marks,
            self._table.filled_shares if split else None,
            None if struck is None else struck > 0,
            muted,
        )
        # The split is of samples: while the cells count instances it rests, and says so.
        self._split.setEnabled(not self.by_instances)
        self._key.set_visible("filled", split)
        self._key.set_visible("cleaned", self.cleaning_on)
        self._key.set_visible("order", ordered)
        self._key.set_text("live", "measured" if split else "live")
        self._title.setText(self._title_text())

    def _cleaning_marks(self) -> tuple[np.ndarray | None, list[int]]:
        """Per cell of the table, how many of its bars the rule discards the sensor in; and the columns it drops."""
        self._struck_counts = None
        if not self.cleaning_on or self._table is None:
            return None, []
        cleaned = self._cleaned
        bars = self.availability.bars
        keys = self._event_keys()
        events = np.array([cleaned.event(key) for key in keys], dtype=object)
        n_rows, n_cols = len(self._rows), len(self._table.sensors)
        counts = np.zeros((n_rows, n_cols), dtype=int)
        columns = [
            cleaned.cleaning.sensors.index(s) if s in cleaned.cleaning.sensors else -1
            for s in self._table.sensors
        ]
        for r, (kind, key) in enumerate(self._ids):
            if kind == "class":
                members = np.flatnonzero(bars["fault_class"].to_numpy() == key)
            elif kind == "well":
                members = np.flatnonzero(bars["well"].to_numpy() == key)
            elif kind == "bar":
                members = np.array([int(key)])
            else:  # the total row
                members = (
                    np.flatnonzero(self._mask) if self._mask is not None else np.arange(len(bars))
                )
            rows = [events[m] for m in members if events[m] is not None]
            if not rows:
                continue
            block = cleaned.cleaning.discarded[rows]
            for c, j in enumerate(columns):
                if j >= 0:
                    counts[r, c] = int(block[:, j].sum())
        self._struck_counts = counts
        muted = [c for c, j in enumerate(columns) if j >= 0 and cleaned.cleaning.dropped[j]]
        return counts, muted

    def _refresh_pairs(self) -> None:
        table = self._pair_table = self._build_pairs()
        n = len(table.sensors)
        shares = np.zeros((n, n, 3))
        shares[:, :, LIVE] = table.shares
        shares[:, :, ABSENT] = 1.0 - shares[:, :, LIVE]
        self._rows = [HeatmapRow(name) for name in table.sensors]
        self._ids = [("sensor", j) for j in range(n)]
        self._mask = None
        self._heatmap.set_matrix(self._rows, table.sensors, shares, np.zeros((n, n), dtype=bool))
        self._title.setText(self._pair_title_text())

    def _title_text(self) -> str:
        table = self._table
        shown = int(table.n_instances[-1])
        samples = int(table.n_samples[-1])
        mode = self.mode
        noun = "bar" if self.joined else "instance"
        if mode == "Fault classes":
            what = "fault class"
        elif mode == "Wells":
            what = "well"
        else:
            what = f"{noun} of {self._rows[-1].label.split(': ')[0]}"
        unit = f"its {noun}s" if self.by_instances else "its samples"
        order = " | ◢ pressures out of order" if self._table.out_of_order is not None else ""
        parts = [
            (
                f"Per {what}: the share of {unit} in which each sensor is live, frozen or absent | "
                f"▲ a reading outside the plausible range{order}"
            ),
            f"{shown:,} real {noun}{'s' if shown != 1 else ''}, {samples:,} samples",
        ]
        if self.threshold > 0:
            parts.append(
                f"a sensor with readings in less than {self.threshold:.0%} of the samples of an "
                f"{noun} counts as absent there"
            )
        if self.split:
            parts.append(
                "the live share split into measurements (solid) and the samples the historian "
                "filled in between them (pale)"
            )
        if self.cleaning_on:
            dropped = self._cleaned.cleaning.dropped_sensors()
            parts.append(
                "╲ a sensor the Toolkit's CleanSignals would discard in at least one "
                f"{noun} of the row ({self.clean_rule.describe()})"
                + (f"; dropped altogether: {', '.join(dropped)}" if dropped else "")
            )
        if self.joined:
            parts.append(
                "overlapping instances read as the recordings they were cut from, each shared "
                "sample counted once"
            )
        else:
            parts.append("a sample two overlapping instances share is counted in both")
        return " | ".join(parts)

    def _pair_title_text(self) -> str:
        table = self._pair_table
        scope = self._scope.currentText() or "All real instances"
        noun = "bar" if self.joined else "real instance"
        rule = (
            f"counted only in the {noun}s where both sensors are live"
            if table.live_only
            else "every sample carrying both counted, frozen readings included"
        )
        parts = [
            (
                "Per pair of sensors: the share of the samples in which both carry a reading at "
                "the same instant"
            ),
            (
                f"{scope.split(' (')[0]} | {_plural(table.n_bars, noun)}, "
                f"{table.n_samples:,} samples"
            ),
            rule,
            "the diagonal is each sensor's own coverage",
        ]
        if self.threshold > 0 and table.live_only:
            parts.append(f"available from {self.threshold:.0%} of the samples of a {noun}")
        if self.joined:
            parts.append(
                "overlapping instances read as the recordings they were cut from, so a sensor one "
                "window missed is filled in by another"
            )
        return " | ".join(parts)

    def summary(self) -> str:
        """One line for the status bar: what the whole catalogue recorded."""
        availability = self.availability
        if availability is None:
            return ""
        version = f"3W {self.info.version} | " if self.info.version else ""
        if self.correlations_on and self._corr is not None:
            corr = self._corr
            linear, nonlinear = corr.global_coefficients()
            present = int(corr.present().sum())
            figures = f"global linear {linear:.2f}" if np.isfinite(linear) else "no pair to compare"
            if np.isfinite(nonlinear):
                figures += f", nonlinear {nonlinear:.2f}"
            return (
                f"{version}{present} sensors with co-valid samples over {corr.n_instances} "
                f"{'bars' if self.joined else 'instances'} | {figures} "
            )
        if self.pairs and self._pair_table is not None:
            table = self._pair_table
            n = len(table.sensors)
            total = n * (n - 1) // 2
            off = ~np.eye(n, dtype=bool)
            never = int((table.samples[off] == 0).sum() // 2)
            return (
                f"{version}{n} sensors | {total} pairs | {never} never carry a reading at the "
                f"same instant "
            )
        total = availability.total()
        n, s = availability.n_bars, len(availability.sensors)
        never = int((total.instances[0, :, ABSENT] == n).sum())
        flagged = int(availability.implausible.any(axis=1).sum())
        wells = self._catalogue["well"].nunique()
        noun = "bar" if self.joined else "real instance"
        disordered = (
            f" | {_plural(int((availability.out_of_order > 0).any(axis=1).sum()), noun)} with "
            "pressures out of order"
            if availability.out_of_order is not None
            else ""
        )
        measured = ""
        if self.split and total.measured:
            # Over the analog sensors: a valve state is not tested, and would
            # count as measured throughout.
            analog = [
                j for j, name in enumerate(total.sensors) if not self.info.is_enumerated(name)
            ]
            genuine = float(total.genuine[0, analog].sum())
            filled = float(total.filled[0, analog].sum())
            if genuine + filled > 0:
                measured = (
                    f" | {genuine / (genuine + filled):.1%} of the live samples of the analog "
                    "sensors are measurements"
                )
        return (
            f"{version}{_plural(n, noun)} on {wells} wells | {s} sensors, {never} never recorded | "
            f"{_plural(flagged, noun)} with readings outside the plausible range{disordered}"
            f"{measured} "
        )

    # -- pointer

    def _on_hovered(self, row: int, column: int) -> None:
        if self._table is None or (row < 0 and column < 0):
            self.status.emit(self.hint())
        elif self.correlations_on and self._corr is not None:
            self.status.emit(self._describe_corr(row, column))
        elif self.pairs and self._pair_table is not None:
            self.status.emit(self._describe_pair(row, column))
        elif row < 0:
            self.status.emit(self._describe_sensor(column))
        elif column < 0:
            self.status.emit(self._describe_row(row))
        else:
            self.status.emit(self._describe_cell(row, column))

    def _on_clicked(self, row: int, column: int) -> None:
        """A fault class or a well opens its instances; an instance opens its time series."""
        if row < 0 or self.pairs or self.correlations_on:
            return
        kind, key = self._ids[row]
        if kind in ("class", "well"):
            self.show_instances_of(kind, int(key))
        elif kind == "bar":
            entry = self.availability.bars.iloc[int(key)]
            sensor = self._table.sensors[column] if column >= 0 else None
            self.open_requested.emit(int(entry["well"]), int(entry["bar"]), sensor, self.joined)

    def _view_of(self, well: int) -> WellData:
        data = self._well_by_number[int(well)]
        return data.joined() if self.joined else data

    # -- what the status bar says

    def _describe_cell(self, row: int, column: int) -> str:
        table, info = self._table, self.info
        name = table.sensors[column]
        unit, scale = info.shown_unit(name), info.shown_scale(name)
        n_instances = int(table.n_instances[row])
        shares = table.shares[row, column]
        counts = table.instances[row, column]
        noun = "bar" if self.joined else "instance"
        parts = [f"{self._rows[row].label} | {name}" + (f" [{unit}]" if unit else "")]
        if n_instances == 1:
            n_total = int(table.n_samples[row])
            for code, word in ((LIVE, "live"), (FROZEN, "frozen"), (ABSENT, "absent")):
                if shares[code] > 0:
                    parts.append(f"{word} in {shares[code]:.1%} of its {n_total:,} samples")
        else:
            for code, word, note in (
                (LIVE, "live", ""),
                (FROZEN, "frozen", ""),
                (ABSENT, "absent", " with none of it"),
            ):
                if shares[code] > 0 or counts[code] > 0:
                    parts.append(
                        f"{word} in {shares[code]:.1%} of the samples "
                        f"({counts[code]} of {n_instances} {noun}s{note})"
                    )
        measured = self._measured_clause(row, column)
        if measured:
            parts.append(measured)
        low, high = table.low[row, column] * scale, table.high[row, column] * scale
        if not np.isnan(low):
            parts.append(f"readings {low:.4g} to {_quantity(high, unit)}")
        flagged = int(table.implausible[row, column])
        if flagged:
            lo, hi = info.shown_range(name)
            who = "readings" if n_instances == 1 else f"{_plural(flagged, noun)} with readings"
            parts.append(f"⚠ {who} outside the plausible range {lo:g} to {hi:g} {unit}".rstrip())
        order = self._order_clause(row, column)
        if order:
            parts.append(order)
        cleaned = self._cleaning_clause(row, column)
        if cleaned:
            parts.append(cleaned)
        return " | ".join(parts)

    def _order_clause(self, row: int, column: int) -> str:
        """How often this pressure reads out of order in the cell, and with which; empty if never."""
        table = self._table
        if table.out_of_order is None or not table.out_of_order[row, column]:
            return ""
        count, n = int(table.out_of_order[row, column]), int(table.n_instances[row])
        noun = "bar" if self.joined else "instance"
        where = "" if n == 1 else f" in {_plural(count, noun)}"
        partners = ", ".join(table.order_partners[row, column])
        return f"⚠ out of order with {partners}{where}"

    def _cleaning_clause(self, row: int, column: int) -> str:
        """What the Toolkit's rule would do to this cell, when the rule is on."""
        if not self.cleaning_on or self._struck_counts is None:
            return ""
        name = self._table.sensors[column]
        cleaned = self._cleaned
        if name not in cleaned.cleaning.sensors:
            return ""
        j = cleaned.cleaning.sensors.index(name)
        parts = []
        if cleaned.cleaning.dropped[j]:
            parts.append(
                f"CleanSignals drops {name} altogether: missing in "
                f"{cleaned.cleaning.missing_shares[j]:.0%} of the {'bars' if self.joined else 'instances'}"
            )
        count = int(self._struck_counts[row, column])
        if count:
            kind, key = self._ids[row]
            noun = "bar" if self.joined else "instance"
            if kind == "bar":
                why = cleaned.why(self._event_keys()[int(key)], name)
                parts.append(f"╲ CleanSignals would discard {name} here ({why})")
            else:
                n = int(self._table.n_instances[row])
                parts.append(
                    f"╲ CleanSignals would discard {name} in {count} of {_plural(n, noun)}"
                )
        return " | ".join(parts)

    def _measured_clause(self, row: int, column: int) -> str:
        """How much of one cell's live signal was measured, when the split is on and known."""
        table = self._table
        if not self.split or table is None or not table.measured:
            return ""
        share = table.measured_share(row, column)
        if not np.isfinite(share):
            return ""
        spacing = table.spacing_s(row, column)
        interval = (
            f", one every {format_spacing(spacing)} of signal" if np.isfinite(spacing) else ""
        )
        return f"measurements {share:.1%} of its live samples{interval}, the rest filled in"

    def _describe_sensor(self, column: int) -> str:
        table, info = self._table, self.info
        name = table.sensors[column]
        unit, scale = info.shown_unit(name), info.shown_scale(name)
        noun = "bar" if self.joined else "instance"
        parts = [f"{name}" + (f" [{unit}]" if unit else "")]
        described = info.sensor_descriptions.get(name, "")
        if described:
            parts.append(described)
        if info.is_enumerated(name):
            parts.append("a valve state: never frozen, only absent or live")
        total = len(table) - 1  # the total row folds every bar shown
        n = int(table.n_instances[total])
        counts = table.instances[total, column]
        parts.append(
            f"over the {_plural(n, noun)} shown: live in {table.shares[total, column, LIVE]:.1%} "
            f"of the samples, live in {counts[LIVE]}, frozen in {counts[FROZEN]}, "
            f"absent from {counts[ABSENT]}"
        )
        lo, hi = info.shown_range(name)
        parts.append(f"plausible range {lo:g} to {hi:g} {unit}".rstrip())
        if self.cleaning_on and name in self._cleaned.cleaning.sensors:
            cleaning = self._cleaned.cleaning
            j = cleaning.sensors.index(name)
            if cleaning.dropped[j]:
                parts.append(
                    f"CleanSignals drops it altogether: missing in {cleaning.missing_shares[j]:.0%} "
                    f"of the {noun}s"
                )
            elif not cleaning.exempt[j]:
                lo_m, hi_m = cleaning.mean_bounds[0][j] * scale, cleaning.mean_bounds[1][j] * scale
                lo_s, hi_s = cleaning.std_bounds[0][j] * scale, cleaning.std_bounds[1][j] * scale
                parts.append(
                    f"CleanSignals keeps a mean between {lo_m:.4g} and {_quantity(hi_m, unit)} "
                    f"and a spread between {lo_s:.4g} and {_quantity(hi_s, unit)}; discarded in "
                    f"{int(cleaning.discarded[:, j].sum())} {noun}s"
                )
        return " | ".join(parts)

    def _describe_row(self, row: int) -> str:
        kind, key = self._ids[row]
        bars, info = self.availability.bars, self.info
        if kind == "bar":
            entry = bars.iloc[int(key)]
            view = self._view_of(int(entry["well"]))
            return describe_instance(view, int(entry["bar"]), info, self._plain) + (
                " | click to open its time series"
            )
        if kind == "class":
            part = bars[bars["fault_class"] == key]
            head = f"{key}. {info.fault_name(int(key))}"
            tail = " | click to see them one by one"
        elif kind == "well":
            part = bars[bars["well"] == key]
            faults = sorted(int(f) for f in part["fault_class"].unique())
            head = f"{well_label(int(key))} | fault classes {', '.join(map(str, faults))}"
            tail = " | click to see them one by one"
        else:
            part = bars if self._mask is None else bars[self._mask]
            head = self._rows[row].label
            tail = ""
        wells = part["well"].nunique()
        noun = "bar" if self.joined else "real instance"
        return (
            f"{head} | {_plural(len(part), noun)} on {_plural(wells, 'well')} | "
            f"{int(part['n_samples'].sum()):,} samples | {part['hours'].sum():,.0f} h recorded{tail}"
        )

    def shown_files(self) -> list[tuple[int, str]]:
        """The instances behind the bars on show, for the file list a Toolkit loader takes."""
        availability = self.availability
        if availability is None:
            return []
        bars = availability.bars
        taken = np.arange(len(bars)) if self._mask is None else np.flatnonzero(self._mask)
        files = []
        for i in taken:
            row = bars.iloc[int(i)]
            data = self._well_by_number[int(row["well"])]
            origin = data.origin.rows
            for member in row["members"]:
                files.append(
                    (int(origin["fault_class"].iloc[member]), str(origin["file"].iloc[member]))
                )
        return files

    def shown_source(self) -> str:
        """Where the file list came from, for its provenance."""
        what = self._rows[-1].label if self._rows else self.mode
        return f"the Availability page | rows: {self.mode} | {what}" + (
            " | joined bars" if self.joined else ""
        )

    def _describe_pair(self, row: int, column: int) -> str:
        """One line about a cell, a row or a column of the pair map."""
        table, info = self._pair_table, self.info
        if row < 0 or column < 0:  # a label: the sensor's own coverage
            j = column if row < 0 else row
            name = table.sensors[j]
            own = table.shares[j, j]
            described = info.sensor_descriptions.get(name, "")
            partners = int((table.samples[j] > 0).sum()) - int(table.samples[j, j] > 0)
            return " | ".join(
                part
                for part in (
                    f"{name}" + (f" [{info.shown_unit(name)}]" if info.shown_unit(name) else ""),
                    described,
                    f"recorded in {own:.1%} of the samples on show",
                    (
                        f"carries a reading at the same instant as {partners} of the "
                        f"{len(table.sensors) - 1} other sensors"
                    ),
                )
                if part
            )
        a, b = table.sensors[row], table.sensors[column]
        share = table.shares[row, column]
        samples = int(table.samples[row, column])
        if row == column:
            return (
                f"{a} | its own coverage: {share:.1%} of the samples on show, {samples:,} of "
                f"{table.n_samples:,}"
            )
        own_a, own_b = table.shares[row, row], table.shares[column, column]
        bars = int(table.bars[row, column])
        overlap = f"{share / min(own_a, own_b):.0%}" if min(own_a, own_b) > 0 else "none"
        noun = "bar" if self.joined else "instance"
        return (
            f"{a} × {b} | both in {share:.1%} of the samples on show ({samples:,}) | "
            f"{a} alone in {own_a:.1%}, {b} alone in {own_b:.1%} | "
            f"{overlap} of the scarcer one's samples carry the other | "
            f"{_plural(bars, noun)} carry both"
        )

    # -- what the tooltip says

    def tooltip(self, row: int, column: int) -> str:
        """The rich text shown where the pointer is: the figure the cell draws, first of all."""
        if self._table is None:
            return ""
        if self.correlations_on and self._corr is not None:
            return self._corr_tooltip(row, column)
        if self.pairs and self._pair_table is not None:
            return self._pair_tooltip(row, column)
        if row < 0 and column < 0:
            return ""
        if row < 0:
            return self._sensor_tooltip(column)
        if column < 0:
            return self._row_tooltip(row)
        return self._cell_tooltip(row, column)

    def _cell_tooltip(self, row: int, column: int) -> str:
        table, info, colors = self._table, self.info, theme.current()
        name = table.sensors[column]
        unit, scale = info.shown_unit(name), info.shown_scale(name)
        noun = "bar" if self.joined else "instance"
        n = int(table.n_instances[row])
        by_bars = self.by_instances
        drawn = table.instance_shares[row, column] if by_bars else table.shares[row, column]
        other = table.shares[row, column] if by_bars else table.instance_shares[row, column]
        counts = table.instances[row, column]
        of_what = f"of its {_plural(n, noun)}" if by_bars else "of its samples"
        lines = [
            f"<b>{name}</b>{_unit_html(unit, colors.muted)}",
            f'<span style="color:{colors.muted};">{self._rows[row].label}</span>',
            (
                f'<span style="font-size:13pt; color:{colors.live};">'
                f"<b>{drawn[LIVE]:.1%}</b></span> live {of_what}"
            ),
        ]
        rest = []
        if drawn[FROZEN] > 0:
            rest.append(f"{drawn[FROZEN]:.1%} frozen")
        if drawn[ABSENT] > 0:
            rest.append(f"{drawn[ABSENT]:.1%} absent")
        if rest:
            lines.append(f'<span style="color:{colors.muted};">{" | ".join(rest)}</span>')
        if n > 1:
            lines.append(
                f'<span style="color:{colors.muted};">{other[LIVE]:.1%} of '
                f"{'the samples' if by_bars else f'the {noun}s'} | {counts[LIVE]} live, "
                f"{counts[FROZEN]} frozen, {counts[ABSENT]} absent of {n}</span>"
            )
        measured = self._measured_clause(row, column)
        if measured:
            lines.append(f'<span style="color:{colors.muted};">{measured}</span>')
        cleaned = self._cleaning_clause(row, column)
        if cleaned:
            lines.append(f'<span style="color:{colors.text};">{cleaned}</span>')
        low, high = table.low[row, column] * scale, table.high[row, column] * scale
        if not np.isnan(low):
            lines.append(
                f'<span style="color:{colors.muted};">readings {low:.4g} to '
                f"{_quantity(high, unit)}</span>"
            )
        flagged = int(table.implausible[row, column])
        if flagged:
            lo, hi = info.shown_range(name)
            who = "readings" if n == 1 else _plural(flagged, noun)
            lines.append(
                f'<span style="color:{colors.warning};">⚠ {who} outside {lo:g} to {hi:g} '
                f"{unit}</span>".replace(" </span>", "</span>")
            )
        order = self._order_clause(row, column)
        if order:
            lines.append(f'<span style="color:{colors.warning};">{order}</span>')
        return "<br>".join(lines)

    def _sensor_tooltip(self, column: int) -> str:
        table, info, colors = self._table, self.info, theme.current()
        name = table.sensors[column]
        unit = info.shown_unit(name)
        total = len(table) - 1
        noun = "bar" if self.joined else "instance"
        counts = table.instances[total, column]
        n = int(table.n_instances[total])
        lines = [
            f"<b>{name}</b>{_unit_html(unit, colors.muted)}",
            (
                f'<span style="font-size:13pt; color:{colors.live};">'
                f"<b>{table.shares[total, column, LIVE]:.1%}</b></span> live over everything shown"
            ),
            (
                f'<span style="color:{colors.muted};">live in {counts[LIVE]}, frozen in '
                f"{counts[FROZEN]}, absent from {counts[ABSENT]} of {_plural(n, noun)}</span>"
            ),
        ]
        described = info.sensor_descriptions.get(name, "")
        if described:
            lines.insert(1, f'<span style="color:{colors.muted};">{described}</span>')
        if info.is_enumerated(name):
            lines.append(f'<span style="color:{colors.muted};">a valve state: never frozen</span>')
        return "<br>".join(lines)

    def _row_tooltip(self, row: int) -> str:
        """What the row holds: its own label in bold, and the rest of its line under it."""
        colors = theme.current()
        head = self._rows[row].label
        rest = self._describe_row(row)
        if rest.startswith(head):  # the description opens with the label it belongs to
            rest = rest[len(head) :].lstrip(" |")
        tail = f'<br><span style="color:{colors.muted};">{rest}</span>' if rest else ""
        return f"<b>{head}</b>{tail}"

    def _pair_tooltip(self, row: int, column: int) -> str:
        table, info, colors = self._pair_table, self.info, theme.current()
        if row < 0 and column < 0:
            return ""
        if row < 0 or column < 0:
            j = column if row < 0 else row
            name = table.sensors[j]
            lines = [
                f"<b>{name}</b>{_unit_html(info.shown_unit(name), colors.muted)}",
                (
                    f'<span style="font-size:13pt; color:{colors.live};">'
                    f"<b>{table.shares[j, j]:.1%}</b></span> of the samples on show"
                ),
            ]
            described = info.sensor_descriptions.get(name, "")
            if described:
                lines.insert(1, f'<span style="color:{colors.muted};">{described}</span>')
            return "<br>".join(lines)
        a, b = table.sensors[row], table.sensors[column]
        share = table.shares[row, column]
        if row == column:
            return (
                f"<b>{a}</b><br>"
                f'<span style="font-size:13pt; color:{colors.live};"><b>{share:.1%}</b></span>'
                f" of the samples on show<br>"
                f'<span style="color:{colors.muted};">its own coverage, the diagonal</span>'
            )
        own_a, own_b = table.shares[row, row], table.shares[column, column]
        lines = [
            f"<b>{a} × {b}</b>",
            (
                f'<span style="font-size:13pt; color:{colors.live};"><b>{share:.1%}</b></span>'
                " of the samples carry both"
            ),
            (
                f'<span style="color:{colors.muted};">{a} alone {own_a:.1%} | {b} alone '
                f"{own_b:.1%}</span>"
            ),
            (
                f'<span style="color:{colors.muted};">'
                f"{int(table.samples[row, column]):,} samples in "
                f"{_plural(int(table.bars[row, column]), 'bar' if self.joined else 'instance')}"
                "</span>"
            ),
        ]
        if share == 0 and min(own_a, own_b) > 0:
            lines.append(
                f'<span style="color:{colors.warning};">never recorded at the same instant</span>'
            )
        return "<br>".join(lines)
