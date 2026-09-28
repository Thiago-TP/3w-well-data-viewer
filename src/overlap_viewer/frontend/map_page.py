"""The Instances map: every real instance as one point, placed by what its sensors amount to.

The other pages look at the instances one well, one fault or one sensor at a
time. This one looks at all of them at once, from above: each instance (or,
with *Join overlapping instances* ticked, each bar of the joined view) is a
point, placed on the plane by an embedding of its **representation**
(``algorithms.embedding``): the descriptors of its sensors, taken on the 1 Hz
grid or on the measurements alone; the same less the levels; or the DTW
distance between the instances of one class on one sensor. The points are
colored by fault class, by well, by the cluster a clustering puts them in, by
how typical an instance of its class each is, or by the verdict of a one-class
model of the normal instances; hovering one names it, clicking one opens its
time series.

Two things the map computes are handed to the other pages: the clusters and
the typicality become bar colorings of the Timelines, and the typicality and
the novelty score become sort keys of the instance lists of the Faults and
Features pages. What is on the right is the **label audit**: the instances
whose label disagrees with the one-class verdict (a fault instance that looks
normal, a normal instance that looks anomalous), class by class, each a click
away.

The representation needs the profiles of the instances (``backend.profiles``),
read once behind a progress dialog and shared with the other pages. The
embeddings beyond PCA, the clusterings, their scores and the novelty model
need the ``analysis`` extra (UMAP the ``umap`` extra, DTW the ``dtw`` extra);
a control whose extra is missing is greyed and its tooltip says what to
install.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd
import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QAction, QCursor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QToolBar,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from overlap_viewer.algorithms import embedding as em
from overlap_viewer.backend import theme
from overlap_viewer.backend.dataset import DatasetInfo, WellData, instance_title, well_label
from overlap_viewer.backend.extras import missing
from overlap_viewer.backend.palette import fault_color, tint
from overlap_viewer.backend.profiles import DESCRIPTOR_MODES, Profiles
from overlap_viewer.frontend.heatmap import ramp_color
from overlap_viewer.frontend.items import ScrollFriendlyViewBox, restyle_axes
from overlap_viewer.frontend.loading import progress_dialog
from overlap_viewer.frontend.overview import ElidedLabel
from overlap_viewer.frontend.passes import Passes
from overlap_viewer.frontend.series_page import LIST_WIDTH

HINT = (
    "Every point is one real instance, or one joined bar | hover a point to name it, click it to "
    "open its time series | the boxes choose what places the points, what colors them and how "
    "they are grouped | the list on the right is the label audit, drag its edge to resize it | "
    "F1 for help"
)
AUDIT_MIN_WIDTH = 200  # the audit can be dragged narrower than this only by retracting it
AUDIT_TOGGLE_TIP = (
    "Show or hide the label audit on the right, to give the map its width; drag its left edge to "
    "widen or narrow it. It retracts by itself under the DTW representation, which compares the "
    "instances of one class, and comes back as it was on leaving it."
)

COLORINGS = ("Fault class", "Well", "Cluster", "Typicality", "Novelty", "Model agreement")
POINT_PX = 9
HOVER_PX = 12
HIGHLIGHT_PX = 15
MAX_K = 12
DEFAULT_K = 4

REPRESENTATION_TIP = (
    "What an instance becomes a point by. Descriptors: per sensor the moments, the quantiles, "
    "the autocorrelation time, the signal-to-noise ratio, the Gaussianity slope and how it was "
    "measured, standardized column by column; a sensor enters only if it is live in at least half "
    "of the points, and a cell the instance lacks takes the column's median. Shape only: the same "
    "less the levels, so that the level of a well does not place its instances. DTW: the dynamic "
    "time warping distance between the instances of one class on one sensor, the 3W Toolkit's "
    "own comparison of shapes, each series z-scored and averaged into 400 blocks first."
)
MODE_TIP = (
    "Which descriptors. Interpolated: those taken over the whole 1 Hz grid, most of whose samples "
    "the historian drew between the readings it archived, which is what a pipeline reads. "
    "Measurements: those taken over the readings alone. Over the interpolated grid the straight "
    "lines make every series look smoother than the process (the signal-to-noise ratio and the "
    "autocorrelation time in particular), so the map drawn from it is a map of the lines as much "
    "as of the wells."
)
EMBEDDING_TIP = (
    "How the points are laid on the plane. PCA keeps the two directions of largest variance and "
    "says how much they carry; t-SNE and UMAP keep neighbourhoods instead, so distances between "
    "far groups mean little and the axes have no unit. On a DTW representation PCA becomes the "
    "principal coordinates of the distances."
)
COLORING_TIP = (
    "What colors a point: the fault folder of the instance, its well, the cluster a clustering "
    "put it in, how typical an instance of its class it is (full for the medoid, faint for the "
    "farthest), the verdict of the one-class model (blue looks normal, amber looks anomalous, "
    "with a dark ring where the verdict disagrees with the label) or, once model outputs are "
    "loaded, how far they agree with the instance's labels, full for all of the compared time, "
    "faint for none, grey where the model scored nothing."
)
CLUSTERING_TIP = (
    "Group the points: k-means and a Gaussian mixture on the coordinates, agglomerative clustering "
    "(average linkage) and DBSCAN on the distances, DBSCAN reading its radius from the data and "
    "leaving isolated points out. The status line scores the result: the silhouette (1 for tight, "
    "well-separated clusters), and the agreement with the fault classes and with the wells as "
    "the adjusted Rand index and the normalised mutual information: 1 for a clustering that is "
    "the classes, or the wells, under other names, near 0 for one unrelated to them. On 3W the "
    "wells usually win."
)
JOIN_TIP = (
    "Make the points the bars of the joined view: the instances of a well that overlap with "
    "labels that agree, read as the single recording they were cut from and profiled as such, so "
    "that a well recorded twice is one point where it was one recording."
)


@dataclass
class MapResults:
    """What the map computed, for the other pages to color and sort by.

    Keyed as the profile table keys its rows: ``(fault_class, file)`` for the
    instances, ``(well, bar)`` for the bars of the joined view; ``joined``
    says which. ``clusters`` maps a key to its cluster (``-1`` for a point
    DBSCAN left out) and is ``None`` when no clustering is on; ``typicality``
    maps a key to its distance to the medoid of its class and its rank there;
    ``novelty`` maps a key to the one-class score and whether it looks
    anomalous, ``None`` when the model could not run.
    """

    joined: bool
    representation: str
    clusters: dict | None
    typicality: dict
    novelty: dict | None

    def cluster_color(self, key) -> str | None:
        """The color of the cluster a key sits in, ``None`` when it is not on the map."""
        if self.clusters is None or key not in self.clusters:
            return None
        return cluster_color(self.clusters[key])

    def typicality_rank(self, key) -> float:
        entry = self.typicality.get(key)
        return float("nan") if entry is None else entry[1]

    def novelty_score(self, key) -> float:
        entry = None if self.novelty is None else self.novelty.get(key)
        return float("nan") if entry is None else entry[0]


def cluster_color(label: int) -> str:
    """The color of one cluster: the well palette, cycled, and the faint grey for a point left out."""
    colors = theme.current()
    if label < 0:
        return colors.faint
    palette = colors.wells
    return palette[label % len(palette)]


@dataclass
class Point:
    """One point of the map: which instance or bar it stands for, and how to open it."""

    key: tuple
    title: str
    fault: int
    well: int
    data: WellData  # the view (plain or joined) the point belongs to
    index: int  # its position in that view


class MapPage(QWidget):
    """The page: the boxes, the map, the label audit, and what it hands to the other pages.

    Signals
    -------
    status(str)
        What the main window's status bar should say.
    summary_changed()
        The one-line description of the map has changed.
    open_requested(WellData, int)
        A point was clicked: the view and the bar to open.
    results_changed(MapResults)
        The clusters, the typicality and the novelty were computed again.
    """

    status = Signal(str)
    summary_changed = Signal()
    open_requested = Signal(object, int)
    results_changed = Signal(object)

    def hint(self) -> str:
        return HINT

    def __init__(self, info: DatasetInfo, passes: Passes | None = None, parent=None):
        super().__init__(parent)
        self.info = info
        self._passes = passes
        self._catalogue: pd.DataFrame | None = None
        self._wells: list[WellData] = []
        self._profiles: Profiles | None = None
        self._points: list[Point] = []
        self._rep: em.Representation | None = None
        self._coords = np.zeros((0, 2))
        self._caption = ""
        self._clusters: np.ndarray | None = None
        self._scores: em.ClusterScores | None = None
        self._typicality: em.Typicality | None = None
        self._novelty: em.Novelty | None = None
        self._pending = False
        self._hover = -1
        self._summary = ""
        self._model_results = None  # the model outputs loaded, once they are

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self._build_toolbar())
        layout.addWidget(self._build_second_bar())
        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(8, 0, 8, 4)
        body_layout.setSpacing(8)
        self._plot_widget = pg.PlotWidget(viewBox=ScrollFriendlyViewBox())
        plot = self._plot_widget.getPlotItem()
        plot.hideButtons()
        plot.setMenuEnabled(True)
        plot.getViewBox().setMouseMode(pg.ViewBox.PanMode)
        plot.showGrid(x=True, y=True, alpha=0.15)
        self._scatter = pg.ScatterPlotItem(size=POINT_PX, pxMode=True)
        self._scatter.setZValue(10)
        plot.addItem(self._scatter)
        self._highlight = pg.ScatterPlotItem(size=HIGHLIGHT_PX, pxMode=True)
        self._highlight.setZValue(11)
        plot.addItem(self._highlight, ignoreBounds=True)
        self._plot_widget.scene().sigMouseMoved.connect(self._on_mouse_moved)
        self._plot_widget.scene().sigMouseClicked.connect(self._on_mouse_clicked)
        # The audit beside the map on a splitter, so that its handle trades the
        # width of one for the other; the toggle on the second row retracts it.
        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.setChildrenCollapsible(False)
        self._splitter.addWidget(self._plot_widget)
        self._audit_panel = self._build_audit_panel()
        self._splitter.addWidget(self._audit_panel)
        self._splitter.setStretchFactor(0, 1)
        self._splitter.setStretchFactor(1, 0)
        self._splitter.setSizes([10 * LIST_WIDTH, LIST_WIDTH])
        body_layout.addWidget(self._splitter, 1)
        layout.addWidget(body, 1)
        self._note = ElidedLabel("")
        self._note.setContentsMargins(8, 0, 8, 2)
        layout.addWidget(self._note)
        self._restyle()

    # -- construction

    def _build_toolbar(self) -> QToolBar:
        bar = QToolBar("Instances map")
        bar.setMovable(False)
        bar.addWidget(QLabel(" Representation "))
        self._representation = QComboBox()
        for key in em.REPRESENTATIONS:
            self._representation.addItem(em.REPRESENTATION_NAMES[key], key)
        self._representation.setToolTip(REPRESENTATION_TIP)
        self._grey(self._representation, em.REPRESENTATIONS.index("dtw"), missing("dtw"))
        self._representation.currentIndexChanged.connect(self._on_representation_changed)
        bar.addWidget(self._representation)

        self._mode_label = QLabel(" on ")
        self._mode_actions = [bar.addWidget(self._mode_label)]
        self._mode = QComboBox()
        self._mode.addItems(list(DESCRIPTOR_MODES))
        self._mode.setToolTip(MODE_TIP)
        self._mode.currentIndexChanged.connect(self._recompute)
        self._mode_actions.append(bar.addWidget(self._mode))

        self._dtw_actions = [bar.addWidget(QLabel(" Sensor "))]
        self._sensor = QComboBox()
        self._sensor.setToolTip("The sensor whose shape the DTW distance compares")
        self._sensor.currentIndexChanged.connect(self._recompute)
        self._dtw_actions.append(bar.addWidget(self._sensor))
        self._dtw_actions.append(bar.addWidget(QLabel(" Class ")))
        self._class = QComboBox()
        self._class.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self._class.setToolTip("The fault class whose instances the DTW distance compares")
        self._class.currentIndexChanged.connect(self._recompute)
        self._dtw_actions.append(bar.addWidget(self._class))

        bar.addSeparator()
        bar.addWidget(QLabel(" Embedding "))
        self._embedding = QComboBox()
        self._embedding.addItems(list(em.EMBEDDINGS))
        self._embedding.setToolTip(EMBEDDING_TIP)
        for k, method in enumerate(em.EMBEDDINGS):
            self._grey(self._embedding, k, em.embedding_available(method))
        self._embedding.currentIndexChanged.connect(self._recompute)
        bar.addWidget(self._embedding)

        bar.addSeparator()
        bar.addWidget(QLabel(" Color by "))
        self._coloring = QComboBox()
        self._coloring.addItems(list(COLORINGS))
        self._coloring.setToolTip(COLORING_TIP)
        self._coloring.currentIndexChanged.connect(self._redraw)
        self._coloring.model().item(COLORINGS.index("Model agreement")).setEnabled(False)
        bar.addWidget(self._coloring)

        bar.addSeparator()
        self._join = QCheckBox("Join overlapping instances")
        self._join.setToolTip(JOIN_TIP)
        self._join.toggled.connect(self._recompute)
        bar.addWidget(self._join)
        self._sync_representation_controls()
        return bar

    def _build_second_bar(self) -> QToolBar:
        bar = QToolBar("Clustering")
        bar.setMovable(False)
        bar.addWidget(QLabel(" Clustering "))
        self._clustering = QComboBox()
        self._clustering.addItems(list(em.CLUSTERINGS))
        self._clustering.setToolTip(CLUSTERING_TIP)
        reason = missing("analysis")
        for k in range(1, len(em.CLUSTERINGS)):
            self._grey(self._clustering, k, reason)
        self._clustering.currentIndexChanged.connect(self._on_clustering_changed)
        bar.addWidget(self._clustering)
        self._k_label = QLabel(" k ")
        self._k_action = bar.addWidget(self._k_label)
        self._k = QSpinBox()
        self._k.setRange(2, MAX_K)
        self._k.setValue(DEFAULT_K)
        self._k.setToolTip(
            "How many clusters k-means, the mixture and the agglomerative clustering make"
        )
        self._k.valueChanged.connect(self._recompute)
        self._k_spin_action = bar.addWidget(self._k)
        bar.addSeparator()
        self._scores_label = QLabel("")
        self._scores_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        bar.addWidget(self._scores_label)
        bar.addSeparator()
        self._show_audit = QAction("Label audit", self)
        self._show_audit.setCheckable(True)
        self._show_audit.setChecked(True)
        self._show_audit.setToolTip(AUDIT_TOGGLE_TIP)
        self._show_audit.toggled.connect(self._on_audit_toggled)
        bar.addAction(self._show_audit)
        # What the user asked of the audit outside the DTW representation,
        # which hides it: leaving DTW gives it back as it was.
        self._audit_wanted = True
        self._sync_clustering_controls()
        return bar

    def _on_audit_toggled(self, shown: bool) -> None:
        self._audit_panel.setVisible(shown)
        if self.representation != "dtw":
            self._audit_wanted = shown

    def _build_audit_panel(self) -> QWidget:
        panel = QWidget()
        panel.setMinimumWidth(AUDIT_MIN_WIDTH)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel("<b>Label audit</b>"))
        self._audit = QTreeWidget()
        self._audit.setHeaderHidden(True)
        self._audit.setMouseTracking(True)
        self._audit.itemClicked.connect(self._on_audit_clicked)
        self._audit.itemEntered.connect(self._on_audit_entered)
        layout.addWidget(self._audit, 1)
        self._audit_note = QLabel(
            "A one-class model of the normal instances scores every point. Listed here are the "
            "instances whose label disagrees with it: fault instances that look normal, normal "
            "instances that look anomalous. Click one to open it."
        )
        self._audit_note.setWordWrap(True)
        layout.addWidget(self._audit_note)
        return panel

    @staticmethod
    def _grey(box: QComboBox, index: int, reason: str | None) -> None:
        """Grey one entry of a box when its extra is missing, and say so in the tooltip."""
        item = box.model().item(index)
        if reason is None:
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEnabled)
            item.setToolTip("")
        else:
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            item.setToolTip(reason)

    def _sync_representation_controls(self) -> None:
        dtw = self.representation == "dtw"
        for action in self._mode_actions:
            action.setVisible(not dtw)
        for action in self._dtw_actions:
            action.setVisible(dtw)

    def _sync_audit_panel(self) -> None:
        """Retract the audit under the DTW representation, and give it back as it was on leaving.

        DTW compares the instances of one class only, so its map has the whole
        width to itself; the toggle still shows the audit if it is asked for.
        """
        wanted = self._audit_wanted and self.representation != "dtw"
        if self._show_audit.isChecked() != wanted:
            self._show_audit.blockSignals(True)
            self._show_audit.setChecked(wanted)
            self._show_audit.blockSignals(False)
        self._audit_panel.setVisible(wanted)

    def _sync_clustering_controls(self) -> None:
        wants_k = self.clustering in ("k-means", "Gaussian mixture", "Agglomerative")
        self._k_action.setVisible(wants_k)
        self._k_spin_action.setVisible(wants_k)

    # -- appearance

    def _restyle(self) -> None:
        colors = theme.current()
        self._plot_widget.setBackground(colors.plot_background)
        # This page keeps one plot for its whole life, so its axes have to be
        # given the new foreground themselves: pyqtgraph froze the old one into
        # their pens when they were built, grid included.
        restyle_axes(self._plot_widget.getPlotItem())
        self._note.setStyleSheet(f"color: {colors.muted}; font-size: 8pt;")
        self._audit_note.setStyleSheet(f"color: {colors.muted}; font-size: 8pt;")
        self._scores_label.setStyleSheet(f"color: {colors.muted};")

    def apply_theme(self) -> None:
        """Take the colors of the theme now in force: the plot, the points, and the audit's headings.

        Nothing is computed again: the map on show was placed by the data, and
        only what carries a color is made afresh.
        """
        self._restyle()
        self._redraw()
        if self._points:  # its class headings are written in the fault colors
            self._fill_audit()

    # -- the state of the boxes

    @property
    def representation(self) -> str:
        return str(self._representation.currentData() or "descriptors")

    @property
    def measured(self) -> bool:
        return self._mode.currentIndex() == 1

    @property
    def embedding(self) -> str:
        return self._embedding.currentText()

    @property
    def coloring(self) -> str:
        return self._coloring.currentText()

    @property
    def clustering(self) -> str:
        return self._clustering.currentText()

    @property
    def joined(self) -> bool:
        return self._join.isChecked()

    def set_coloring(self, name: str) -> None:
        self._coloring.setCurrentIndex(COLORINGS.index(name))

    def set_clustering(self, name: str) -> None:
        self._clustering.setCurrentIndex(em.CLUSTERINGS.index(name))

    def set_representation(self, key: str) -> None:
        self._representation.setCurrentIndex(em.REPRESENTATIONS.index(key))

    def set_embedding(self, name: str) -> None:
        self._embedding.setCurrentIndex(em.EMBEDDINGS.index(name))

    def set_model_results(self, results) -> None:
        """Take the model outputs loaded (or none), and offer the coloring by their agreement."""
        self._model_results = results
        item = self._coloring.model().item(COLORINGS.index("Model agreement"))
        item.setEnabled(results is not None)
        if self.coloring == "Model agreement":
            if results is None:
                self._coloring.setCurrentIndex(0)
            else:
                self._redraw()

    def _model_agreement(self, point: "Point") -> float:
        """How far the loaded model agrees with the labels behind one point, NaN when it scored none."""
        results = self._model_results
        if results is None:
            return float("nan")
        origin = point.data.origin.rows
        keys = [
            (int(origin["fault_class"].iloc[m]), str(origin["file"].iloc[m]))
            for m in point.data.members[point.index]
        ]
        return results.agreement_of_members(keys)

    # -- data

    def set_catalogue(self, catalogue: pd.DataFrame, wells: list[WellData]) -> None:
        """Take a new catalogue; the map is computed when the page is next on show.

        The very same catalogue again is the main window laying the pages out
        in a new theme, not new data: the points were placed by what the
        sensors amount to and not by the colors, so the map stands and
        ``apply_theme`` has already drawn it again. Computing it afresh would
        embed every instance once more, and under the DTW representation read
        a class of instances again behind a dialog.
        """
        same = catalogue is self._catalogue and bool(self._points)
        self._catalogue = catalogue
        self._wells = list(wells)
        if same:
            return
        self._profiles = None
        self._fill_dtw_boxes()
        self._pending = True
        if self.isVisible():
            QTimer.singleShot(0, self._ensure_and_compute)

    def _fill_dtw_boxes(self) -> None:
        wanted_sensor = self._sensor.currentText()
        self._sensor.blockSignals(True)
        self._sensor.clear()
        analog = [name for name in self.info.sensor_names if not self.info.is_enumerated(name)]
        self._sensor.addItems(analog)
        index = self._sensor.findText(wanted_sensor)
        self._sensor.setCurrentIndex(max(index, 0))
        self._sensor.blockSignals(False)
        wanted_class = self._class.currentData()
        self._class.blockSignals(True)
        self._class.clear()
        if self._catalogue is not None:
            counts = self._catalogue["fault_class"].value_counts()
            for fault in sorted(counts.index):
                self._class.addItem(
                    f"{fault}. {self.info.fault_name(int(fault))} ({int(counts[fault])})",
                    int(fault),
                )
        index = self._class.findData(wanted_class) if wanted_class is not None else -1
        self._class.setCurrentIndex(max(index, 0))
        self._class.blockSignals(False)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._pending:
            QTimer.singleShot(0, self._ensure_and_compute)

    def _ensure_profiles(self) -> bool:
        """Have the profiles on hand, reading the data if need be; ``False`` if cancelled."""
        if self._profiles is not None:
            return True
        if self._passes is None:
            return False
        self._profiles = self._passes.profiles(self.info.sensor_names, parent=self.window())
        return self._profiles is not None

    def _ensure_and_compute(self) -> None:
        if not self._pending or not self.isVisible():
            return
        if self.representation != "dtw" and not self._ensure_profiles():
            self._note.setText(
                "The map needs the profiles of the instances, which were not read. Show the page "
                "again to read them."
            )
            return
        self._pending = False
        self._compute()

    def _on_representation_changed(self, *args) -> None:
        self._sync_representation_controls()
        self._sync_audit_panel()
        self._recompute()

    def _on_clustering_changed(self, *args) -> None:
        self._sync_clustering_controls()
        self._recompute()

    def _recompute(self, *args) -> None:
        if self._catalogue is None:
            return
        self._pending = True
        if self.isVisible():
            self._ensure_and_compute()

    # -- the points and their representation

    def _list_points(self, only_class: int | None = None) -> list[Point]:
        """Every instance, or every joined bar, as a point; ``only_class`` keeps one class."""
        points: list[Point] = []
        for well in self._wells:
            view = well.joined() if self.joined else well
            rows = view.rows
            for index in range(len(rows)):
                row = rows.iloc[index]
                fault = int(row["fault_class"])
                if only_class is not None and fault != only_class:
                    continue
                key = (well.well, index) if self.joined else (fault, str(row["file"]))
                points.append(Point(key, instance_title(row), fault, well.well, view, index))
        return points

    def _build_representation(self) -> tuple[list[Point], em.Representation] | None:
        """The points and what places them, under the boxes; ``None`` when the DTW read was cancelled."""
        if self.representation == "dtw":
            return self._dtw_representation()
        points = self._list_points()
        rep = em.feature_matrix(
            self._profiles,
            [p.key for p in points],
            self.joined,
            self.info,
            shape_only=self.representation == "shape",
            measured=self.measured,
        )
        return points, rep

    def _dtw_representation(self) -> tuple[list[Point], em.Representation] | None:
        from overlap_viewer.algorithms.dtw import N_BLOCKS, WINDOW_SHARE, decimate, dtw_distances

        fault = self._class.currentData()
        sensor = self._sensor.currentText()
        if fault is None or not sensor or self._passes is None:
            return [], em.distance_representation([], np.zeros((0, 0)))
        candidates = self._list_points(int(fault))
        dialog, progress = progress_dialog(
            f"Reading the {sensor} series of the {len(candidates)} instances of "
            f"{self.info.fault_name(int(fault))}…",
            self.window(),
        )
        kept: list[Point] = []
        series: list[np.ndarray] = []
        try:
            from overlap_viewer.backend.dataset import merge_instances

            for k, point in enumerate(candidates, start=1):
                paths = point.data.origin.rows["path"]
                frame = merge_instances(
                    [
                        self._passes.frames.get(paths.iloc[m])
                        for m in point.data.members[point.index]
                    ]
                )
                if sensor in frame.columns:
                    blocks = decimate(frame[sensor].to_numpy(dtype=float))
                    if blocks is not None:
                        kept.append(point)
                        series.append(blocks)
                if not progress(k, len(candidates), point.title):
                    return None
        finally:
            dialog.close()
            dialog.deleteLater()
        QApplication.setOverrideCursor(QCursor(Qt.CursorShape.WaitCursor))
        try:
            D = dtw_distances(series) if series else np.zeros((0, 0))
        finally:
            QApplication.restoreOverrideCursor()
        left_out = len(candidates) - len(kept)
        note = (
            f"DTW of {sensor} within {self.info.fault_name(int(fault))}: {len(kept)} instances, "
            f"each z-scored and averaged into {N_BLOCKS} blocks, window {WINDOW_SHARE:.0%}"
            + (f" | {left_out} left out, the sensor flat or missing in them" if left_out else "")
        )
        return kept, em.distance_representation([p.key for p in kept], D, note)

    # -- computing

    def _compute(self) -> None:
        """Place, group and score the points under the boxes, draw them, and tell the other pages."""
        built = self._build_representation()
        if built is None:  # the DTW read was cancelled: back to the descriptors
            self._representation.blockSignals(True)
            self._representation.setCurrentIndex(0)
            self._representation.blockSignals(False)
            self._sync_representation_controls()
            if not self._ensure_profiles():
                return
            built = self._build_representation()
        self._points, self._rep = built
        rep = self._rep
        classes = [p.fault for p in self._points]
        wells = [p.well for p in self._points]
        QApplication.setOverrideCursor(QCursor(Qt.CursorShape.WaitCursor))
        try:
            try:
                self._coords, self._caption = em.embed(rep, self.embedding)
            except ImportError as error:
                self._coords, self._caption = em.embed(rep, "PCA")
                self._caption += f" (the {self.embedding} extra is missing: {error})"
            self._clusters = None
            self._scores = None
            if self.clustering != "None" and rep.n >= 2 and not missing("analysis"):
                self._clusters = em.cluster(rep, self.clustering, self._k.value())
                self._scores = em.cluster_scores(rep, self._clusters, classes, wells)
            self._typicality = em.typicality(rep, classes) if rep.n else None
            self._novelty = em.novelty(rep, classes) if rep.n else None
        finally:
            QApplication.restoreOverrideCursor()
        self._redraw()
        # Framed afresh only here, where the points have just been placed: a
        # change of coloring or of theme leaves them where they are, and the
        # zoom with them.
        self._plot_widget.getPlotItem().getViewBox().autoRange(padding=0.08)
        self._fill_audit()
        self._scores_label.setText(self._scores.describe() if self._scores else "")
        self._note.setText(" | ".join(part for part in (rep.note, self._caption) if part))
        n = rep.n
        noun = "bars" if self.joined else "instances"
        self._summary = f"{n} {noun} on the map | {self._caption} "
        self.summary_changed.emit()
        self.results_changed.emit(self.results())
        self.status.emit(HINT)

    def results(self) -> MapResults:
        """What the other pages take from the map: clusters, typicality and novelty by key."""
        keys = [p.key for p in self._points]
        clusters = (
            None
            if self._clusters is None
            else {key: int(label) for key, label in zip(keys, self._clusters)}
        )
        typ = self._typicality
        typicality = (
            {}
            if typ is None
            else {key: (float(typ.distance[i]), float(typ.rank[i])) for i, key in enumerate(keys)}
        )
        nov = self._novelty
        novelty = (
            None
            if nov is None
            else {key: (float(nov.score[i]), bool(nov.anomalous[i])) for i, key in enumerate(keys)}
        )
        return MapResults(self.joined, self.representation, clusters, typicality, novelty)

    # -- drawing

    def _well_colors(self) -> dict[int, str]:
        palette = theme.current().wells
        return {
            well.well: palette[k % len(palette)]
            for k, well in enumerate(sorted(self._wells, key=lambda w: w.well))
        }

    def _point_colors(self) -> tuple[list[str], list]:
        """The fill of every point under the coloring chosen, and the pen of each."""
        colors = theme.current()
        coloring = self.coloring
        n = len(self._points)
        pens = [pg.mkPen(colors.plot_background, width=0.8)] * n
        if coloring == "Fault class":
            fills = [fault_color(p.fault) for p in self._points]
        elif coloring == "Well":
            wells = self._well_colors()
            fills = [wells[p.well] for p in self._points]
        elif coloring == "Cluster":
            if self._clusters is None:
                fills = [colors.faint] * n
            else:
                fills = [cluster_color(int(label)) for label in self._clusters]
        elif coloring == "Typicality":
            if self._typicality is None:
                fills = [colors.faint] * n
            else:
                fills = [
                    ramp_color(rank) if np.isfinite(rank) else colors.faint
                    for rank in self._typicality.rank
                ]
        elif coloring == "Model agreement":
            fills = []
            for point in self._points:
                share = self._model_agreement(point)
                fills.append(ramp_color(share) if np.isfinite(share) else colors.faint)
        else:  # Novelty
            if self._novelty is None:
                fills = [colors.faint] * n
            else:
                fills = [
                    colors.warning if anomalous else colors.live
                    for anomalous in self._novelty.anomalous
                ]
                ring = pg.mkPen(colors.text, width=2)
                flagged = set(self._novelty.disagreements.tolist())
                pens = [ring if i in flagged else pens[i] for i in range(n)]
        return fills, pens

    def _redraw(self, *args) -> None:
        if not self._points:
            self._scatter.setData([], [])
            self._highlight.setData([], [])
            return
        fills, pens = self._point_colors()
        self._scatter.setData(
            x=self._coords[:, 0],
            y=self._coords[:, 1],
            brush=[pg.mkBrush(color) for color in fills],
            pen=pens,
            size=POINT_PX,
        )
        self._set_highlight(-1)
        plot = self._plot_widget.getPlotItem()
        if self.embedding == "PCA" and not (self._rep is not None and self._rep.metric):
            plot.setLabel("bottom", "PC1")
            plot.setLabel("left", "PC2")
        else:
            plot.setLabel("bottom", "")
            plot.setLabel("left", "")

    def _set_highlight(self, index: int) -> None:
        self._hover = index
        if index < 0 or index >= len(self._points):
            self._highlight.setData([], [])
            return
        colors = theme.current()
        self._highlight.setData(
            x=[self._coords[index, 0]],
            y=[self._coords[index, 1]],
            brush=pg.mkBrush(None),
            pen=pg.mkPen(colors.outline, width=2.5),
            size=HIGHLIGHT_PX,
        )

    # -- the audit

    def _fill_audit(self) -> None:
        self._audit.clear()
        nov = self._novelty
        classes = np.array([p.fault for p in self._points])
        if nov is None:
            why = missing("analysis") or (
                "the DTW representation has no coordinates for the model to learn from"
                if self.representation == "dtw"
                else "too few normal instances to learn from"
            )
            self._audit.addTopLevelItem(QTreeWidgetItem([f"No verdicts: {why}"]))
            return
        for klass in sorted(set(classes.tolist())):
            members = np.flatnonzero(classes == klass)
            flagged = nov.disagreements_of(classes, klass)
            verdict = "look anomalous" if klass == 0 else "look normal"
            heading = (
                f"{klass}. {self.info.fault_name(int(klass))}: {len(flagged)} of "
                f"{len(members)} {verdict}"
            )
            head = QTreeWidgetItem([heading])
            head.setData(0, Qt.ItemDataRole.UserRole, -1)
            head.setForeground(0, pg.mkColor(fault_color(int(klass))))
            for i in sorted(flagged.tolist(), key=lambda i: nov.score[i], reverse=klass != 0):
                child = QTreeWidgetItem([f"{self._points[i].title} (score {nov.score[i]:+.2f})"])
                child.setData(0, Qt.ItemDataRole.UserRole, int(i))
                head.addChild(child)
            head.setExpanded(len(flagged) <= 12)
            self._audit.addTopLevelItem(head)

    def _on_audit_clicked(self, item, _column) -> None:
        index = item.data(0, Qt.ItemDataRole.UserRole)
        if index is not None and int(index) >= 0:
            point = self._points[int(index)]
            self.open_requested.emit(point.data, point.index)

    def _on_audit_entered(self, item, _column) -> None:
        index = item.data(0, Qt.ItemDataRole.UserRole)
        if index is None or int(index) < 0:
            return
        self._set_highlight(int(index))
        self.status.emit(self.describe(int(index)))

    # -- pointer

    def _nearest(self, scene_pos) -> int:
        vb = self._plot_widget.getPlotItem().getViewBox()
        if not len(self._points) or not vb.sceneBoundingRect().contains(scene_pos):
            return -1
        point = vb.mapSceneToView(scene_pos)
        px, py = vb.viewPixelSize()
        dx = (self._coords[:, 0] - point.x()) / px
        dy = (self._coords[:, 1] - point.y()) / py
        distance = np.hypot(dx, dy)
        k = int(np.argmin(distance))
        return k if distance[k] <= HOVER_PX else -1

    def _on_mouse_moved(self, pos) -> None:
        index = self._nearest(pos)
        if index != self._hover:
            self._set_highlight(index)
        self.status.emit(self.describe(index) if index >= 0 else HINT)

    def _on_mouse_clicked(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        index = self._nearest(event.scenePos())
        if index >= 0:
            event.accept()
            point = self._points[index]
            self.open_requested.emit(point.data, point.index)

    def describe(self, index: int) -> str:
        """One line about a point: which instance, its class and well, and what the map made of it."""
        point = self._points[index]
        parts = [f"{well_label(point.well)} | {point.title} | {self.info.fault_name(point.fault)}"]
        if self._clusters is not None:
            label = int(self._clusters[index])
            parts.append("left out of every cluster" if label < 0 else f"cluster {label + 1}")
        typ = self._typicality
        if typ is not None and np.isfinite(typ.rank[index]):
            parts.append(
                f"typicality {typ.rank[index]:.2f} (distance {typ.distance[index]:.2f} to the "
                f"medoid of its class{', the medoid itself' if typ.rank[index] == 1.0 else ''})"
            )
        nov = self._novelty
        if nov is not None:
            verdict = "looks anomalous" if nov.anomalous[index] else "looks normal"
            flag = " ⚑ disagrees with the label" if index in nov.disagreements else ""
            parts.append(f"{verdict} to the one-class model (score {nov.score[index]:+.2f}){flag}")
        if self._rep is not None and not self._rep.metric and len(self._rep.imputed) > index:
            imputed = self._rep.imputed[index]
            if imputed > 0:
                parts.append(f"{imputed:.0%} of its cells imputed")
        if self._model_results is not None:
            share = self._model_agreement(point)
            parts.append(
                f"{self._model_results.name} agrees {share:.0%} of the compared time"
                if np.isfinite(share)
                else f"not scored by {self._model_results.name}"
            )
        return " | ".join(parts)

    def summary(self) -> str:
        return self._summary

    def reset_views(self) -> None:
        self._plot_widget.getPlotItem().getViewBox().autoRange(padding=0.08)

    # -- what leaves the page

    def shown_files(self) -> list[tuple[int, str]]:
        """The instances behind the points on the map, for the file list a Toolkit loader takes."""
        files = []
        for point in self._points:
            origin = point.data.origin.rows
            for member in point.data.members[point.index]:
                files.append(
                    (int(origin["fault_class"].iloc[member]), str(origin["file"].iloc[member]))
                )
        return files

    def shown_source(self) -> str:
        """Where a file list from this page came from, for its provenance."""
        what = em.REPRESENTATION_NAMES[self.representation]
        if self.representation == "dtw":
            what += f" | {self._sensor.currentText()} | {self._class.currentText()}"
        return f"the Instances map | {what}" + (" | joined bars" if self.joined else "")


__all__ = ["COLORINGS", "MapPage", "MapResults", "cluster_color", "tint"]
