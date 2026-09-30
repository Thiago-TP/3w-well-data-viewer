"""The Windows page: one sensor of a well cut into windows of a fixed size, one label each.

A model of the 3W does not read an instance whole: it reads windows of a fixed
number of samples, and what each window is labeled is what it learns. This
page shows those windows. A well and a sensor are chosen, and every instance
of the well is read (behind a progress dialog) and cut into windows of 256, 512
or 1024 samples by ``algorithms.windows``, in software, on four rules: every
window holds exactly that many values; every window lies inside one run of
constant label, so it carries one label (normal operation, one fault's
transient or steady state, or none); the end of a run too short to fill a
window is completed with zero padding; and no instant is in two windows, the
head of an instance that repeats the instance before it being left out.

The windows are listed in a table that can be filtered (by instance, fault
folder, label, padding, missing readings), laid out as a grid of thumbnails,
page by page, each shaded in its label's color and captioned with its label's
name, and placed on the well's time axis in a strip above the grid. The
window selected is drawn large at the bottom, beside the instance it was cut
from with the window's place in it. *View* can swap the signal for one figure
of every window, among the viewer's own descriptors (those of the instance
window's statistics table and of the Timelines' descriptor coloring): one
point per window along the well, colored by label period, beside the
distribution of the figure per period and how well it tells normal windows from
event ones.
"""

import time
from collections import OrderedDict
from dataclasses import dataclass

import numpy as np
import pandas as pd
import pyqtgraph as pg
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QGraphicsItem,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTableView,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from overlap_viewer.algorithms import windows as wi
from overlap_viewer.algorithms.descriptors import SUMMARY, format_figure
from overlap_viewer.backend import theme
from overlap_viewer.backend.availability import ABSENT, LIVE, Availability
from overlap_viewer.backend.dataset import (
    DatasetInfo,
    WellData,
    filename_stamp,
    load_instance_columns,
    well_label,
)
from overlap_viewer.backend.labels import label_fault, label_kind, label_name, runs
from overlap_viewer.backend.palette import (
    background_color,
    bar_color,
    text_color,
    tint,
    unknown_background,
)
from overlap_viewer.backend.profiles import DESCRIPTOR_CHOICES, GRID_CAVEAT
from overlap_viewer.backend.timemap import TimeMap
from overlap_viewer.frontend.items import (
    ScrollFriendlyViewBox,
    SegmentsItem,
    TimeAxisItem,
    WheelToParent,
    restyle_axes,
)
from overlap_viewer.frontend.loading import progress_dialog
from overlap_viewer.frontend.overview import ElidedLabel

HINT = (
    "Every window holds the same number of samples and one label | click a row, a thumbnail, "
    "the strip or a point to see the window large, and where it sits in its instance | "
    "double-click a row to open the instance | Ctrl + wheel zooms the plots below | F1 for help"
)
PER_PAGE = 12
GRID_COLUMNS = 4
THUMB_PX = 190
MAP_PX = 74
MAX_MAP_WINDOWS = 20_000  # drawn at once in the strip; zoom in for more
MAX_GAP_LINES = 300
# Series read and kept for the session, by samples: the largest well of 3W 2.0.0
# holds 5.7 million samples of one sensor.
SERIES_CACHE_SAMPLES = 12_000_000
# The sensors the 3w_estudo sensor study found to show the faults most clearly,
# offered first.
PREFERRED_SENSORS = ("P-TPT", "T-TPT", "P-MON-CKP", "P-ANULAR", "P-JUS-CKGL", "T-JUS-CKP", "QGL")
SIGNAL = ""  # the View box's entry for the signal itself
ALL = -1  # the filter boxes' entry for everything
PERIODS = ("normal", "transient", "steady", "unknown")
PERIOD_NAMES = {
    "normal": "normal operation",
    "transient": "transient",
    "steady": "steady state",
    "unknown": "unlabeled",
}
# The figures View offers, the viewer's own: the statistics table's, then the
# ones the Timelines color by that the table does not show; (field, name).
_TABLE = [(name, header) for name, header, _tip in SUMMARY if name != "n"]
FIGURES = tuple(
    _TABLE
    + [
        (choice.column, choice.name)
        for choice in DESCRIPTOR_CHOICES
        if choice.column not in dict(_TABLE)
    ]
)
FIGURE_NAMES = dict(FIGURES)
FIGURE_TIPS = {name: tip for name, _header, tip in SUMMARY}
IN_UNIT = frozenset({"mean", "median", "std", "low", "q25", "q75", "high"})
LEVEL = IN_UNIT - {"std"}  # drawn over the window as a line; the spread as a band
PADDING_TEXTURE = Qt.BrushStyle.DiagCrossPattern
REPEATED_TEXTURE = Qt.BrushStyle.BDiagPattern

WELL_TIP = "The well whose instances are cut into windows; the count is its real instances."
SENSOR_TIP = (
    "The sensor cut into windows; the count is how many of the well's instances recorded it (live "
    "or frozen). The first look at a sensor of a well reads it from every instance, behind a "
    "progress dialog, and keeps it for the session."
)
INSTANCE_TIP = "Every window of the well, or those of one of its instances alone."
SIZE_TIP = (
    "Samples per window: 256, 512 or 1024 seconds on the 1 Hz grid of the 3W. The division is "
    "made here, in software, from the instance files: every window holds exactly this many "
    "values, and the end of a label run that does not fill one is zero padding."
)
VIEW_TIP = (
    "The signal of every window as a thumbnail, or one figure of every window: one point per "
    "window along the well, colored by label period, beside its distribution per period. The "
    "figures are the viewer's own descriptors, those of the instance window's statistics table "
    "and of the Timelines' descriptor coloring, taken over a window's real samples (the padding "
    "and the missing readings left out); the first figure asked of a cut computes them all, "
    f"behind a progress dialog, and keeps them for the session. {GRID_CAVEAT.capitalize()}."
)
FAULT_TIP = "Only the windows of the instances of one fault folder."
LABEL_TIP = (
    "Only the windows of one label: normal operation, one fault's transient or steady state, or "
    "unlabeled. Every window carries exactly one, since it never crosses from one label run to "
    "the next."
)
UNLABELED_TIP = "Leave out the windows of the stretches the experts left unlabeled."
COMPLETE_TIP = (
    "Only the windows filled with real samples: the last window of a label run that does not "
    "fill one is completed with zeros (cross-hatched), and is left out."
)
NO_MISSING_TIP = "Only the windows in which every real sample carries a reading."
SAME_SCALE_TIP = "Give every thumbnail of the page the same vertical scale."
REPEATED_TIP = (
    "Cut every instant of the well once: the samples an earlier instance already covers (on 3W, "
    "usually the first, unlabeled hour of an instance, a copy of the last hour of the one "
    "before) are left out of the windows. Unticked, every instance is cut whole and the windows "
    "of two instances can repeat each other."
)


@dataclass(frozen=True)
class LabelLook:
    """How one label of one instance's folder is written and painted."""

    code: str  # "0", "4", "104", or "—" for unlabeled
    name: str
    period: str  # a key of PERIODS
    strong: str  # the color of a bar, a table cell, a swatch
    background: str  # the shading behind a trace
    unknown: bool

    @property
    def text(self) -> str:
        return f"{self.code} · {self.name}"


class WindowsModel(QAbstractTableModel):
    """The windows passing the filters, one row each, read straight from the page's arrays."""

    COLUMNS = (
        "Instance",
        "Fault",
        "Window",
        "Start",
        "Label",
        "Period",
        "Real samples",
        "Padding",
        "Missing %",
    )
    LABEL_COLUMN = 4
    NUMERIC = frozenset({2, 6, 7, 8, 9})

    def __init__(self, page: "WindowsPage"):
        super().__init__()
        self._page = page
        self._rows = np.zeros(0, dtype=np.int64)
        self._feature = ""

    def set_rows(self, rows: np.ndarray, feature_header: str = "") -> None:
        self.beginResetModel()
        self._rows = rows
        self._feature = feature_header
        self.endResetModel()

    def rowCount(self, parent: QModelIndex | None = None):
        return 0 if parent is not None and parent.isValid() else len(self._rows)

    def columnCount(self, parent: QModelIndex | None = None):
        return len(self.COLUMNS) + (1 if self._feature else 0)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.COLUMNS[section] if section < len(self.COLUMNS) else self._feature
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        page = self._page
        i = int(self._rows[index.row()])
        column = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            return page.cell(i, column)
        if column == self.LABEL_COLUMN and role in (
            Qt.ItemDataRole.BackgroundRole,
            Qt.ItemDataRole.ForegroundRole,
        ):
            look = page.look(i)
            if role == Qt.ItemDataRole.BackgroundRole:
                return QBrush(QColor(look.strong))
            return QBrush(QColor(text_color(look.strong)))
        if role == Qt.ItemDataRole.TextAlignmentRole and column in self.NUMERIC:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if role == Qt.ItemDataRole.ToolTipRole:
            return page.describe(i)
        return None


class Heading(pg.LabelItem):
    """A heading above one plot of a grid: it takes the width of its column and clips a longer text.

    ``pyqtgraph.LabelItem`` asks for the width of its text as its minimum, so a
    long heading over one column of a grid widens that column and pushes the
    grid past its view. This one asks for no width at all, which leaves the
    plots under it to set the column, and clips what does not fit.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemClipsChildrenToShape)

    def updateMin(self):
        height = self.itemRect().height()
        self.setMinimumWidth(0)
        self.setMinimumHeight(height)
        self._sizeHint = {
            Qt.SizeHint.MinimumSize: (0, height),
            Qt.SizeHint.PreferredSize: (0, height),
            Qt.SizeHint.MaximumSize: (-1, -1),
            Qt.SizeHint.MinimumDescent: (0, 0),
        }
        self.updateGeometry()


class ThumbnailGrid(WheelToParent, pg.GraphicsLayoutWidget):
    """The grid of thumbnails: the plain wheel scrolls the area it sits in."""


class WindowsPage(QWidget):
    """The page: the boxes, the table, the thumbnails or the feature, and the window selected.

    Signals
    -------
    status(str)
        What the main window's status bar should say.
    summary_changed()
        The one-line description of the windows on show has changed.
    open_requested(WellData, int, list)
        A window's instance is to be opened: the well, the instance's position
        and the sensor to draw.
    """

    status = Signal(str)
    summary_changed = Signal()
    open_requested = Signal(object, int, object)

    def hint(self) -> str:
        return HINT

    def __init__(self, info: DatasetInfo, parent=None):
        super().__init__(parent)
        self.info = info
        self._catalogue: pd.DataFrame | None = None
        self._wells: dict[int, WellData] = {}
        self._availability: Availability | None = None
        self._timemap: TimeMap | None = None
        # The series read so far, by (well, sensor), the latest last.
        self._series: OrderedDict[tuple[int, str], wi.WellSeries] = OrderedDict()
        self._current_series: wi.WellSeries | None = None
        self._windows: wi.Windows | None = None
        self._x = np.zeros(0)  # where every window starts on the well's axis, in hours
        self._faults = np.zeros(0, dtype=np.int64)  # the fault folder of every window
        self._codes = np.zeros(0)  # the label code of every window
        self._refs: dict[int, wi.InstanceRef] = {}
        self._looks: dict[tuple[float, int], LabelLook] = {}
        # The descriptors of every window, figure by figure, by (well, sensor, size, drop).
        self._described: dict[tuple, dict[str, np.ndarray]] = {}
        self._figures: dict[str, np.ndarray] | None = None  # those of the windows on hand
        self._feature_values: np.ndarray | None = None  # the one View shows
        self._shown = np.zeros(0, dtype=np.int64)  # the windows passing the filters
        self._current = -1  # the window selected, as an index into the windows
        self._thumbs: list[tuple[pg.PlotItem, int]] = []
        self._map_bars: pg.BarGraphItem | None = None
        self._map_marker: pg.InfiniteLine | None = None
        self._map_extras: list = []
        self._brushes: dict[str, QBrush] = {}
        self._strip_brushes: dict[tuple[str, bool], QBrush] = {}
        self._pending = False
        self._listed_well: int | None = None  # the well the Instance box lists
        self._summary = ""
        self._read_s = 0.0
        self._note = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self._build_toolbar())
        layout.addWidget(self._build_filter_bar())
        self._title = QLabel("")
        self._title.setContentsMargins(8, 0, 8, 0)
        font = self._title.font()
        font.setBold(True)
        self._title.setFont(font)
        layout.addWidget(self._title)
        self._caption = ElidedLabel("")
        self._caption.setContentsMargins(8, 0, 8, 0)
        layout.addWidget(self._caption)

        self._model = WindowsModel(self)
        self._table = QTableView()
        self._table.setModel(self._model)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.verticalHeader().setVisible(False)
        self._table.verticalHeader().setDefaultSectionSize(22)
        self._table.horizontalHeader().setStretchLastSection(True)
        # Columns are fitted to their first rows, not to the thousands of a large well: every
        # row of a column reads alike, and measuring them all was most of a filter's cost.
        for header in (self._table.horizontalHeader(), self._table.verticalHeader()):
            header.setResizeContentsPrecision(200)
        self._table.setAlternatingRowColors(True)
        self._table.selectionModel().currentRowChanged.connect(
            lambda current, previous: self._on_row(current.row())
        )
        self._table.doubleClicked.connect(lambda index: self.open_selected())

        self._stack = QStackedWidget()
        self._stack.addWidget(self._build_grid_box())
        self._feature_panel = pg.GraphicsLayoutWidget()
        self._stack.addWidget(self._feature_panel)
        self._feature_plot: pg.PlotItem | None = None

        self._detail = pg.GraphicsLayoutWidget()
        self._detail.setMinimumHeight(220)

        top = QSplitter(Qt.Orientation.Horizontal)
        top.addWidget(self._table)
        top.addWidget(self._stack)
        top.setSizes([720, 980])
        body = QSplitter(Qt.Orientation.Vertical)
        body.addWidget(top)
        body.addWidget(self._detail)
        body.setSizes([560, 300])
        holder = QWidget()
        holder_layout = QHBoxLayout(holder)
        holder_layout.setContentsMargins(8, 0, 8, 4)
        holder_layout.addWidget(body)
        layout.addWidget(holder, 1)
        self._restyle()

    # -- construction

    def _build_toolbar(self) -> QToolBar:
        bar = QToolBar("Windows")
        bar.setMovable(False)
        bar.addWidget(QLabel(" Well "))
        self._well = QComboBox()
        self._well.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self._well.setToolTip(WELL_TIP)
        self._well.currentIndexChanged.connect(self._on_well_changed)
        bar.addWidget(self._well)
        bar.addWidget(QLabel(" Sensor "))
        self._sensor = QComboBox()
        self._sensor.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self._sensor.setToolTip(SENSOR_TIP)
        self._sensor.currentIndexChanged.connect(self._load)
        bar.addWidget(self._sensor)
        bar.addWidget(QLabel(" Instance "))
        self._instance = QComboBox()
        self._instance.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self._instance.setMaxVisibleItems(25)
        self._instance.setToolTip(INSTANCE_TIP)
        self._instance.currentIndexChanged.connect(self._on_instance_changed)
        bar.addWidget(self._instance)

        bar.addSeparator()
        bar.addWidget(QLabel(" Size "))
        self._size = QComboBox()
        for size in wi.SIZES:
            self._size.addItem(f"{size} samples ({size / 60:.1f} min)", size)
        self._size.setCurrentIndex(wi.SIZES.index(wi.DEFAULT_SIZE))
        self._size.setToolTip(SIZE_TIP)
        self._size.currentIndexChanged.connect(self._rebuild_windows)
        bar.addWidget(self._size)
        bar.addWidget(QLabel(" View "))
        self._view = QComboBox()
        self._view.addItem("The signal", SIGNAL)
        for field, name in FIGURES:
            self._view.addItem(name, field)
            if field in FIGURE_TIPS:
                self._view.setItemData(
                    self._view.count() - 1, FIGURE_TIPS[field], Qt.ItemDataRole.ToolTipRole
                )
        self._view.setMaxVisibleItems(30)
        self._view.setToolTip(VIEW_TIP)
        self._view.currentIndexChanged.connect(self._on_view_changed)
        bar.addWidget(self._view)
        bar.addSeparator()
        open_action = bar.addAction("Open instance")
        open_action.setToolTip(
            "Open the instance of the window selected in an instance window, on this sensor"
        )
        open_action.triggered.connect(self.open_selected)
        return bar

    def _build_filter_bar(self) -> QToolBar:
        bar = QToolBar("Filters")
        bar.setMovable(False)
        bar.addWidget(QLabel(" Fault "))
        self._fault = QComboBox()
        self._fault.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self._fault.setToolTip(FAULT_TIP)
        self._fault.currentIndexChanged.connect(self._apply_filters)
        bar.addWidget(self._fault)
        bar.addWidget(QLabel(" Label "))
        self._label = QComboBox()
        self._label.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self._label.setToolTip(LABEL_TIP)
        self._label.currentIndexChanged.connect(self._apply_filters)
        bar.addWidget(self._label)
        bar.addSeparator()
        self._hide_unlabeled = QCheckBox("Hide unlabeled")
        self._hide_unlabeled.setChecked(True)
        self._hide_unlabeled.setToolTip(UNLABELED_TIP)
        self._hide_unlabeled.toggled.connect(self._apply_filters)
        bar.addWidget(self._hide_unlabeled)
        self._complete = QCheckBox("Complete windows only")
        self._complete.setToolTip(COMPLETE_TIP)
        self._complete.toggled.connect(self._apply_filters)
        bar.addWidget(self._complete)
        self._no_missing = QCheckBox("No missing readings")
        self._no_missing.setChecked(True)
        self._no_missing.setToolTip(NO_MISSING_TIP)
        self._no_missing.toggled.connect(self._apply_filters)
        bar.addWidget(self._no_missing)
        bar.addSeparator()
        self._drop = QCheckBox("Each instant once")
        self._drop.setChecked(True)
        self._drop.setToolTip(REPEATED_TIP)
        self._drop.toggled.connect(self._rebuild_windows)
        bar.addWidget(self._drop)
        self._same_scale = QCheckBox("Same scale in the grid")
        self._same_scale.setToolTip(SAME_SCALE_TIP)
        self._same_scale.toggled.connect(self._draw_grid)
        bar.addWidget(self._same_scale)
        return bar

    def _build_grid_box(self) -> QWidget:
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        navigation = QHBoxLayout()
        navigation.addWidget(QLabel("Page"))
        self._page = QSpinBox()
        self._page.setMinimum(1)
        self._page.setToolTip("The page of the grid of thumbnails")
        self._page.valueChanged.connect(self._draw_grid)
        navigation.addWidget(self._page)
        self._pages = QLabel("")
        navigation.addWidget(self._pages)
        navigation.addStretch(1)
        layout.addLayout(navigation)

        self._map = pg.PlotWidget(
            viewBox=ScrollFriendlyViewBox(), axisItems={"bottom": TimeAxisItem()}
        )
        self._map.setFixedHeight(MAP_PX)
        plot = self._map.getPlotItem()
        plot.hideButtons()
        plot.setMenuEnabled(False)
        plot.setMouseEnabled(x=True, y=False)
        plot.setYRange(0, 1, padding=0)
        plot.getAxis("left").setTicks([[(0.5, "windows")]])
        plot.getAxis("left").setWidth(60)
        plot.getViewBox().sigXRangeChanged.connect(self._draw_map_bars)
        self._map.scene().sigMouseClicked.connect(self._on_map_clicked)
        self._map.scene().sigMouseMoved.connect(self._on_map_moved)
        layout.addWidget(self._map)

        self._grid = ThumbnailGrid()
        self._grid.setMinimumHeight(3 * THUMB_PX)
        self._grid.scene().sigMouseClicked.connect(self._on_grid_clicked)
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QScrollArea.Shape.NoFrame)
        area.setWidget(self._grid)
        layout.addWidget(area, 1)
        return box

    # -- appearance

    def _restyle(self) -> None:
        colors = theme.current()
        for widget in (self._map, self._grid, self._feature_panel, self._detail):
            widget.setBackground(colors.plot_background)
        # The strip is kept for the page's whole life, so its axes have to be
        # given the new foreground themselves.
        restyle_axes(self._map.getPlotItem())
        self._caption.setStyleSheet(f"color: {colors.muted};")

    def apply_theme(self) -> None:
        self._restyle()
        self._looks.clear()
        self._brushes.clear()
        self._strip_brushes.clear()
        if self._windows is not None:
            self._apply_filters()

    # -- the state of the boxes

    @property
    def well(self) -> int | None:
        data = self._well.currentData()
        return None if data is None else int(data)

    @property
    def sensor(self) -> str | None:
        data = self._sensor.currentData()
        return None if data is None else str(data)

    @property
    def size(self) -> int:
        data = self._size.currentData()
        return int(data) if data is not None else wi.DEFAULT_SIZE

    @property
    def feature(self) -> str:
        data = self._view.currentData()
        return str(data) if data else SIGNAL

    @property
    def drop_repeated(self) -> bool:
        return self._drop.isChecked()

    def _box_value(self, box: QComboBox):
        data = box.currentData()
        return ALL if data is None else data

    # -- data

    def set_catalogue(self, catalogue: pd.DataFrame, wells: list[WellData]) -> None:
        """Take a new catalogue: what was read described the old one and is dropped.

        The very same catalogue again is the main window laying the pages out
        in a new theme: the series read over it and the windows described are
        as true in one theme as in the other, so they are kept.
        """
        if catalogue is not self._catalogue:
            self._series.clear()
            self._described.clear()
            self._current_series = None
            self._windows = None
        self._catalogue = catalogue
        self._wells = {int(data.well): data for data in wells}
        self._availability = Availability.from_wells(wells, self.info)
        self._fill_wells()
        self._pending = True
        if self.isVisible():
            QTimer.singleShot(0, self._ensure_and_draw)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._pending:
            QTimer.singleShot(0, self._ensure_and_draw)

    def _ensure_and_draw(self) -> None:
        if not self._pending or not self.isVisible():
            return
        self._pending = False
        self._on_well_changed()

    def _fill_wells(self) -> None:
        wanted = self.well
        self._well.blockSignals(True)
        self._well.clear()
        for well in sorted(self._wells):
            data = self._wells[well]
            self._well.addItem(f"{data.label} ({data.n_instances} instances)", well)
        index = self._well.findData(wanted) if wanted is not None else -1
        if index < 0:  # the well with the most instances is the richest in windows
            busiest = max(self._wells, key=lambda w: self._wells[w].n_instances, default=None)
            index = self._well.findData(busiest) if busiest is not None else 0
        self._well.setCurrentIndex(max(index, 0))
        self._well.blockSignals(False)

    def _recorded(self, data: WellData) -> dict[str, tuple[int, int]]:
        """Per sensor, in how many of the well's instances it is recorded, and live."""
        availability = self._availability
        rows = [availability.index_of(data.well, k) for k in range(data.n_instances)]
        state = availability.state[rows]
        return {
            name: (int((state[:, j] != ABSENT).sum()), int((state[:, j] == LIVE).sum()))
            for j, name in enumerate(availability.sensors)
        }

    def _fill_sensors(self, data: WellData) -> None:
        """Offer every sensor, analog ones first, the first preferred one live in the well chosen."""
        wanted = self.sensor
        recorded = self._recorded(data)
        names = list(recorded)
        ordered = [n for n in names if not self.info.is_enumerated(n)] + [
            n for n in names if self.info.is_enumerated(n)
        ]
        self._sensor.blockSignals(True)
        self._sensor.clear()
        for name in ordered:
            count, live = recorded[name]
            self._sensor.addItem(f"{name} ({count})", name)
            item = self._sensor.model().item(self._sensor.count() - 1)
            item.setEnabled(count > 0)
            unit = self.info.shown_unit(name)
            item.setToolTip(
                f"{name}{f' [{unit}]' if unit else ''}\n"
                f"{self.info.sensor_descriptions.get(name, '')}\n"
                f"recorded in {count} of the {data.n_instances} instances of {data.label}, "
                f"live in {live}"
            )
        choice = wanted if wanted in recorded and recorded[wanted][0] > 0 else None
        if choice is None:
            choice = next((n for n in PREFERRED_SENSORS if recorded.get(n, (0, 0))[1] > 0), None)
        if choice is None:
            analog = [n for n in ordered if not self.info.is_enumerated(n)]
            choice = max(analog, key=lambda n: recorded[n][1], default=None)
        index = self._sensor.findData(choice) if choice is not None else -1
        self._sensor.setCurrentIndex(max(index, 0))
        self._sensor.blockSignals(False)

    def _fill_instances(self, data: WellData) -> None:
        """List the well's instances, keeping the one chosen when the well is the same (a theme switch)."""
        wanted = self._box_value(self._instance) if self._listed_well == data.well else ALL
        self._listed_well = data.well
        self._instance.blockSignals(True)
        self._instance.clear()
        self._instance.addItem(f"All instances ({data.n_instances})", ALL)
        rows = data.rows
        for k in range(data.n_instances):
            fault = int(rows["fault_class"].iloc[k])
            self._instance.addItem(
                f"{rows['title'].iloc[k]} | {fault}. {self.info.fault_name(fault)}", k
            )
        self._instance.setCurrentIndex(max(self._instance.findData(wanted), 0))
        self._instance.blockSignals(False)

    def _on_well_changed(self, *args) -> None:
        well = self.well
        if well is None or well not in self._wells or self._availability is None:
            return
        data = self._wells[well]
        self._timemap = TimeMap.build(*data.spans())
        self._map.getPlotItem().getAxis("bottom").set_timemap(self._timemap)
        self._fill_sensors(data)
        self._fill_instances(data)
        self._load()

    def _on_instance_changed(self, *args) -> None:
        self._apply_filters()
        self._frame_map()

    def _load(self, *args) -> None:
        """Have the series of the well and sensor chosen, reading it if need be, and cut it."""
        well, sensor = self.well, self.sensor
        if well is None or sensor is None or well not in self._wells:
            return
        key = (well, sensor)
        series = self._series.get(key)
        if series is None:
            series = self._read(self._wells[well], sensor)
            if series is None:
                self._current_series = None
                self._windows = None
                self._clear_views()
                self._title.setText(f"{well_label(well)} | {sensor}")
                self._caption.setText(
                    self._note
                    or "The instances were not read. Choose the sensor again to read them."
                )
                self._summary = ""
                self.summary_changed.emit()
                return
            self._series[key] = series
            while (
                sum(s.n_samples for s in self._series.values()) > SERIES_CACHE_SAMPLES
                and len(self._series) > 1
            ):
                self._series.popitem(last=False)
        else:
            self._series.move_to_end(key)
            self._read_s = 0.0
        self._current_series = series
        self._rebuild_windows()

    def _read(self, data: WellData, sensor: str) -> wi.WellSeries | None:
        """Read one sensor of every instance of a well, behind a progress dialog; ``None`` if cancelled."""
        self._note = ""
        rows = data.rows
        n = data.n_instances
        reader = wi.SeriesPass(sensor)
        dialog, progress = progress_dialog(
            f"Reading {sensor} from the {n} instances of {data.label}, to cut it into windows…",
            self.window(),
        )
        started = time.perf_counter()
        try:
            for k in range(n):
                title = str(rows["title"].iloc[k])
                try:
                    frame = load_instance_columns(rows["path"].iloc[k], [sensor, "class"])
                except Exception as error:  # noqa: BLE001 - one unreadable file must not take the page down
                    self._note = f"Could not read {title}: {type(error).__name__}: {error}"
                    return None
                ref = wi.InstanceRef(
                    k, int(rows["fault_class"].iloc[k]), str(rows["file"].iloc[k]), title
                )
                reader.add(frame, ref)
                if not progress(k + 1, n, title):
                    return None
        finally:
            dialog.close()
            dialog.deleteLater()
        self._read_s = time.perf_counter() - started
        return reader.result()

    def _rebuild_windows(self, *args) -> None:
        """Cut the series on hand into windows of the size chosen, and show them."""
        series = self._current_series
        if series is None:
            return
        # The window selected is found again in the new cut by the instant it starts at.
        place = self._place_of(self._current)
        # Whatever indexes the windows is let go before they are replaced. The
        # table reads its rows whenever the event loop runs, and the progress
        # dialog below runs it: rows of the old cut read out of the new one
        # were past its end (an IndexError on every cell), and the window
        # selected, drawn as the old cut's, was another window or none.
        self._forget_windows()
        self._windows = w = series.windows(self.size, self.drop_repeated)
        self._refs = {ref.position: ref for ref in w.refs}
        self._faults = w.fault
        self._codes = w.codes
        self._x = (
            self._timemap.to_x(w.start) if len(w) and self._timemap is not None else np.zeros(0)
        )
        self._fill_filters()
        if self.feature and not self._ensure_feature():
            self._set_view(SIGNAL)
        self._current = self._window_at(place)
        self._apply_filters()
        self._frame_map()

    def _forget_windows(self) -> None:
        """Empty the table and the selection, everything that points into the windows on hand."""
        self._shown = np.zeros(0, dtype=np.int64)
        self._current = -1
        self._figures = None
        self._feature_values = None
        self._thumbs = []
        self._model.set_rows(self._shown)

    def _place_of(self, i: int) -> tuple[int, int] | None:
        """Window ``i`` as its instance and the sample it starts at, which outlive a new cut."""
        w = self._windows
        if w is None or not 0 <= i < len(w):
            return None
        return int(w.instance[i]), int(w.first[i])

    def _window_at(self, place: tuple[int, int] | None) -> int:
        """The window holding a sample of an instance, ``-1`` when none does (left out, say)."""
        w = self._windows
        if place is None or w is None:
            return -1
        instance, first = place
        hit = np.flatnonzero(
            (w.instance == instance) & (w.first <= first) & (first < w.first + w.n_valid)
        )
        return int(hit[0]) if len(hit) else -1

    def _fill_filters(self) -> None:
        """Offer the fault folders and the labels the windows carry, keeping the choices that still apply."""
        wanted_fault, wanted_label = self._box_value(self._fault), self._box_value(self._label)
        self._fault.blockSignals(True)
        self._fault.clear()
        self._fault.addItem("All faults", ALL)
        folders, counts = np.unique(self._faults, return_counts=True)
        for folder, count in zip(folders, counts):
            self._fault.addItem(
                f"{folder}. {self.info.fault_name(int(folder))} ({count:,} windows)", int(folder)
            )
        index = self._fault.findData(wanted_fault)
        self._fault.setCurrentIndex(max(index, 0))
        self._fault.blockSignals(False)

        self._label.blockSignals(True)
        self._label.clear()
        self._label.addItem("All labels", ALL)
        codes, counts = np.unique(self._codes, return_counts=True)
        offset = self.info.transient_offset

        def order(code: float) -> tuple:
            if code == wi.UNLABELED:
                return (2, 0, 0)
            fault = label_fault(code, offset)
            return (0, 0, 0) if fault is None else (1, fault, code)

        for code, count in sorted(zip(codes, counts), key=lambda pair: order(pair[0])):
            look = self._look_of(code, -1)
            self._label.addItem(f"{look.text} ({count:,} windows)", float(code))
        index = self._label.findData(wanted_label)
        self._label.setCurrentIndex(max(index, 0))
        self._label.blockSignals(False)

    def _on_view_changed(self, *args) -> None:
        if self._windows is None:
            return
        if self.feature and not self._ensure_feature():
            self._set_view(SIGNAL)
        self._apply_filters()

    def _set_view(self, feature: str) -> None:
        self._view.blockSignals(True)
        self._view.setCurrentIndex(max(self._view.findData(feature), 0))
        self._view.blockSignals(False)

    def _ensure_feature(self) -> bool:
        """Have the figure chosen for every window, describing the windows if need be; ``False`` if cancelled.

        Every figure of every window comes out of one pass of
        ``descriptors.describe``, so the first figure asked of a cut pays for
        all of them and the others are then instant.
        """
        feature, w = self.feature, self._windows
        if not feature or w is None:
            return True
        key = (self.well, self.sensor, self.size, self.drop_repeated)
        described = self._described.get(key)
        if described is None:
            dialog, progress = progress_dialog(
                f"Describing the {len(w):,} windows of {self.sensor} (mean, spread, quartiles, "
                "moments, autocorrelation time, signal-to-noise ratio, Gaussianity)…",
                self.window(),
                verb="Describing",
                noun="windows",
            )
            try:
                described = wi.describe_windows(
                    w.values,
                    w.n_valid,
                    scale=self.info.shown_scale(self.sensor),
                    progress=lambda done, total: progress(done, total, "the windows"),
                )
            finally:
                dialog.close()
                dialog.deleteLater()
            if described is None:
                return False
            self._described[key] = described
        self._figures = described
        self._feature_values = described[feature]
        return True

    def _figure_unit(self, field: str) -> str:
        """The unit of one figure: the sensor's for a level or a spread, seconds for a time."""
        if field in IN_UNIT:
            return self.info.shown_unit(self.sensor)
        return "s" if field == "acf_half_s" else ""

    def _figure_text(self, field: str, value: float) -> str:
        """One figure as the statistics table writes it, with its unit."""
        unit = self._figure_unit(field)
        text = format_figure(float(value))
        return f"{text} {unit}" if unit and np.isfinite(value) else text

    # -- filtering

    def _apply_filters(self, *args) -> None:
        """Choose the windows the boxes let through, and show them."""
        w = self._windows
        if w is None:
            self._clear_views()
            return
        keep = np.ones(len(w), dtype=bool)
        instance = self._box_value(self._instance)
        if instance != ALL:
            keep &= w.instance == int(instance)
        fault = self._box_value(self._fault)
        if fault != ALL:
            keep &= self._faults == int(fault)
        label = self._box_value(self._label)
        if label != ALL:
            keep &= self._codes == float(label)
        if self._hide_unlabeled.isChecked():
            keep &= ~np.isnan(w.label)
        if self._complete.isChecked():
            keep &= w.n_valid == w.size
        if self._no_missing.isChecked():
            keep &= w.nan_share == 0
        self._shown = np.flatnonzero(keep)

        feature = self.feature
        header = ""
        if feature and self._feature_values is not None:
            unit = self._figure_unit(feature)
            header = f"{FIGURE_NAMES[feature]}{f' [{unit}]' if unit else ''}"
        self._model.set_rows(self._shown, header)
        self._table.resizeColumnsToContents()
        pages = max(1, int(np.ceil(len(self._shown) / PER_PAGE)))
        self._page.blockSignals(True)
        self._page.setMaximum(pages)
        self._page.setValue(1)
        self._page.blockSignals(False)
        self._pages.setText(f"of {pages}  |  {PER_PAGE} windows per page")
        self._write_header()
        if feature and self._feature_values is not None:
            self._stack.setCurrentIndex(1)
            self._draw_features()
        else:
            self._stack.setCurrentIndex(0)
            self._feature_panel.clear()
            self._feature_plot = None
            self._draw_map()
            self._draw_grid()
        # The window selected stays selected while it passes the filters, and
        # is drawn afresh: the statistic drawn over it may have changed.
        wanted, self._current = self._current, -1
        rows = np.flatnonzero(self._shown == wanted) if wanted >= 0 else []
        if len(rows):
            self._select_row(int(rows[0]))
        elif len(self._shown):
            self._select_row(0)
        else:
            self._current = -1
            self._detail.clear()
        self.summary_changed.emit()

    def _write_header(self) -> None:
        w = self._windows
        series = self._current_series
        size = w.size
        data = self._wells[self.well]
        self._title.setText(
            f"{data.label} | {self.sensor} | windows of {size} samples ({size / 60:.1f} min)"
        )
        parts = [f"{len(self._shown):,} of {len(w):,} windows pass the filters"]
        padded = int(w.padded().sum())
        parts.append(
            f"every window holds {size} values and one label, and none overlaps another; "
            f"{padded:,} end a label run with zero padding (cross-hatched)"
        )
        if self.drop_repeated and series.n_repeated:
            parts.append(
                f"{series.n_repeated:,} samples repeating an earlier instance left out "
                f"({series.n_repeated / max(series.n_samples, 1):.1%})"
            )
        if self._read_s >= 1.0:
            parts.append(f"read in {self._read_s:.0f} s")
        self._caption.setText(" | ".join(parts))
        noun = "window" if len(self._shown) == 1 else "windows"
        self._summary = (
            f"{len(self._shown):,} {noun} of {size} samples of {self.sensor} on {data.label} "
        )

    def _clear_views(self) -> None:
        self._forget_windows()
        self._grid.clear()
        self._feature_panel.clear()
        self._feature_plot = None
        self._detail.clear()
        self._clear_map()

    # -- what a window is

    def _look_of(self, code: float, folder: int) -> LabelLook:
        """How one label code reads and is painted in an instance of one fault folder.

        A normal stretch takes the hue of its instance's folder and a faulty
        one the hue of its own event, the way the instance window shades its
        class band; ``folder`` −1 names the label alone, in the colors of the
        fault it names (green for normal operation).
        """
        key = (float(code), int(folder))
        look = self._looks.get(key)
        if look is not None:
            return look
        colors = theme.current()
        offset = self.info.transient_offset
        value = float("nan") if code == wi.UNLABELED else float(code)
        kind = label_kind(value, offset)
        fault = label_fault(value, offset)
        hue = fault if fault is not None else max(folder, 0)
        if kind == "unknown":
            look = LabelLook("—", "unlabeled", "unknown", colors.hatch, unknown_background(), True)
        else:
            look = LabelLook(
                str(int(value)),
                label_name(value, self.info.fault_names, offset),
                kind,
                bar_color(hue, kind),
                background_color(hue, kind),
                False,
            )
        self._looks[key] = look
        return look

    def look(self, i: int) -> LabelLook:
        """How the label of window ``i`` reads and is painted."""
        return self._look_of(float(self._codes[i]), int(self._faults[i]))

    def _instance_stamp(self, i: int) -> str:
        ref = self._refs[int(self._windows.instance[i])]
        stamp = filename_stamp(ref.file)
        return stamp.strftime("%Y-%m-%d %H:%M") if stamp is not None else ref.title

    def _start_text(self, i: int) -> str:
        return pd.Timestamp(self._windows.start[i]).strftime("%Y-%m-%d %H:%M:%S")

    def cell(self, i: int, column: int) -> str:
        """The text of one cell of the table: window ``i``, column ``column``."""
        w = self._windows
        if column == 0:
            return self._refs[int(w.instance[i])].title
        if column == 1:
            return str(int(self._faults[i]))
        if column == 2:
            return str(int(w.number[i]))
        if column == 3:
            return self._start_text(i)
        if column == 4:
            return self.look(i).text
        if column == 5:
            return PERIOD_NAMES[self.look(i).period]
        if column == 6:
            return str(int(w.n_valid[i]))
        if column == 7:
            return str(int(w.size - w.n_valid[i]))
        if column == 8:
            return f"{100 * w.nan_share[i]:.1f}"
        values = self._feature_values
        return "" if values is None else format_figure(float(values[i]))

    def describe(self, i: int) -> str:
        """One line about window ``i``: its instance, its place, its label, its samples."""
        w = self._windows
        look = self.look(i)
        ref = self._refs[int(w.instance[i])]
        parts = [
            f"{ref.title} ({ref.fault}. {self.info.fault_name(ref.fault)})",
            f"window {int(w.number[i])}",
            f"starts {self._start_text(i)}",
            f"label {look.text} ({PERIOD_NAMES[look.period]})",
            f"{int(w.n_valid[i])} real samples of {w.size}",
        ]
        if w.nan_share[i] > 0:
            parts.append(f"{100 * w.nan_share[i]:.1f} % missing")
        values = self._feature_values
        if self.feature and values is not None and not np.isnan(values[i]):
            parts.append(
                f"{FIGURE_NAMES[self.feature]} {self._figure_text(self.feature, values[i])}"
            )
        return " | ".join(parts)

    def _brush(self, color: str) -> QBrush:
        brush = self._brushes.get(color)
        if brush is None:
            brush = self._brushes[color] = QBrush(QColor(color))
        return brush

    def _strip_brush(self, i: int, odd: bool) -> QBrush:
        """The fill of window ``i`` in the strip: its label's color, a tone apart from its neighbour's."""
        strong = self.look(i).strong
        brush = self._strip_brushes.get((strong, odd))
        if brush is None:
            brush = QBrush(QColor(tint(strong, 0.85 if odd else 0.5)))
            self._strip_brushes[(strong, odd)] = brush
        return brush

    def _shade_window(self, plot: pg.PlotItem, i: int) -> None:
        """Shade a plot of one window: its label's color over the real samples, the padding cross-hatched."""
        w = self._windows
        look = self.look(i)
        n_valid = int(w.n_valid[i])
        shading = SegmentsItem(z=-10)
        shading.set_segments([-0.5], [n_valid - 0.5], [look.background], hatched=[look.unknown])
        plot.addItem(shading, ignoreBounds=True)
        if n_valid < w.size:
            colors = theme.current()
            padding = SegmentsItem(z=-9, hatch=QBrush(QColor(colors.faint), PADDING_TEXTURE))
            padding.set_segments(
                [n_valid - 0.5], [w.size - 0.5], [colors.plot_background], hatched=[True]
            )
            plot.addItem(padding, ignoreBounds=True)

    def _swatch(self, look: LabelLook) -> str:
        return f"<span style='color:{look.strong}'>&#9632;</span>"

    def _period_key(self, periods: np.ndarray) -> str:
        """The colors of the label periods present, with their counts, as a line of swatches."""
        colors = self._period_colors()
        return " &nbsp; ".join(
            f"<span style='color:{colors[period]}'>&#9632;</span> {PERIOD_NAMES[period]} "
            f"({int((periods == period).sum()):,})"
            for period in PERIODS
            if (periods == period).any()
        )

    @staticmethod
    def _heading(
        widget: pg.GraphicsLayoutWidget, html: str, row: int, col: int, size: str = "9pt"
    ) -> None:
        """A heading above the plot of the next row, clipped rather than widening the layout.

        Its row keeps the height of the text and the plot's row takes the rest:
        a fixed height set on the heading instead (``setFixedHeight``, or a
        fixed size policy) makes pyqtgraph's layout shrink every row to its
        minimum.
        """
        heading = Heading(justify="left")
        heading.setText(html, size=size)
        widget.addItem(heading, row=row, col=col)
        widget.ci.layout.setRowStretchFactor(row, 0)
        widget.ci.layout.setRowStretchFactor(row + 1, 1)

    @staticmethod
    def _frame_flat(plot: pg.PlotItem, values: np.ndarray) -> None:
        """Give a window that barely moves a readable vertical range, not one of rounding error."""
        finite = values[np.isfinite(values)]
        if not len(finite):
            return
        low, high = float(finite.min()), float(finite.max())
        middle = 0.5 * (low + high)
        floor = max(abs(middle) * 1e-4, 1e-6)
        if high - low < floor:
            plot.setYRange(middle - floor, middle + floor, padding=0)

    # -- the strip of the windows along the well

    def _clear_map(self) -> None:
        plot = self._map.getPlotItem()
        for item in [self._map_bars, self._map_marker, *self._map_extras]:
            if item is not None:
                plot.removeItem(item)
        self._map_bars = None
        self._map_marker = None
        self._map_extras = []

    def _draw_map(self) -> None:
        self._clear_map()
        if self._windows is None or self._timemap is None:
            return
        plot = self._map.getPlotItem()
        pen = pg.mkPen(theme.current().gap_line, width=1, style=Qt.PenStyle.DashLine)
        for x in self._timemap.gap_centers()[:MAX_GAP_LINES]:
            line = pg.InfiniteLine(pos=x, angle=90, pen=pen)
            plot.addItem(line, ignoreBounds=True)
            self._map_extras.append(line)
        self._draw_map_bars()
        self._mark_map()

    def _frame_map(self) -> None:
        """Show the whole well in the strip, or the instance chosen."""
        if self._timemap is None:
            return
        instance = self._box_value(self._instance)
        plot = self._map.getPlotItem()
        if instance == ALL:
            plot.setXRange(0, self._timemap.span, padding=0.01)
            return
        data = self._wells[self.well]
        x0, x1 = self._timemap.to_x([data.starts[int(instance)], data.ends[int(instance)]])
        plot.setXRange(float(x0), float(max(x1, x0 + 1 / 60)), padding=0.02)

    def _draw_map_bars(self, *args) -> None:
        """Draw the windows passing the filters that fall in view, a tone apart from their neighbours."""
        plot = self._map.getPlotItem()
        if self._map_bars is not None:
            plot.removeItem(self._map_bars)
            self._map_bars = None
        w = self._windows
        if w is None or not len(self._shown) or self._stack.currentIndex() != 0:
            plot.setTitle("")
            return
        (x0, x1), _ = plot.getViewBox().viewRange()
        widths = w.n_valid[self._shown] / 3600.0
        xs = self._x[self._shown]
        visible = np.flatnonzero((xs + widths >= x0) & (xs <= x1))
        if len(visible) > MAX_MAP_WINDOWS:
            plot.setTitle(
                f"{len(visible):,} windows in view: zoom in (Ctrl + wheel) to draw them",
                size="8pt",
            )
            return
        plot.setTitle("")
        rows = self._shown[visible]
        brushes = [self._strip_brush(int(i), bool(k % 2)) for k, i in enumerate(rows)]
        self._map_bars = pg.BarGraphItem(
            x0=xs[visible],
            width=widths[visible],
            y0=0.1,
            height=0.8,
            brushes=brushes,
            pen=pg.mkPen(None),
        )
        plot.addItem(self._map_bars)

    def _mark_map(self) -> None:
        plot = self._map.getPlotItem()
        if self._map_marker is not None:
            plot.removeItem(self._map_marker)
            self._map_marker = None
        if self._current < 0 or self._stack.currentIndex() != 0:
            return
        x = float(self._x[self._current] + self._windows.n_valid[self._current] / 7200.0)
        self._map_marker = pg.InfiniteLine(
            pos=x, angle=90, pen=pg.mkPen(theme.current().outline, width=2)
        )
        plot.addItem(self._map_marker, ignoreBounds=True)

    def _map_window_at(self, scene_pos) -> int:
        """The row of the window under the pointer in the strip, or ``-1``."""
        vb = self._map.getPlotItem().getViewBox()
        if (
            self._windows is None
            or not len(self._shown)
            or not vb.sceneBoundingRect().contains(scene_pos)
        ):
            return -1
        x = vb.mapSceneToView(scene_pos).x()
        tolerance = 3 * vb.viewPixelSize()[0]
        xs = self._x[self._shown]
        ends = xs + self._windows.n_valid[self._shown] / 3600.0
        inside = np.flatnonzero((xs - tolerance <= x) & (ends + tolerance >= x))
        if not len(inside):
            return -1
        middle = (xs[inside] + ends[inside]) / 2
        return int(inside[np.argmin(np.abs(middle - x))])

    def _on_map_clicked(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        row = self._map_window_at(event.scenePos())
        if row >= 0:
            event.accept()
            self._select_row(row)

    def _on_map_moved(self, pos) -> None:
        row = self._map_window_at(pos)
        self.status.emit(self.describe(int(self._shown[row])) if row >= 0 else HINT)

    # -- the grid of thumbnails

    def _draw_grid(self, *args) -> None:
        self._grid.clear()
        self._thumbs = []
        w = self._windows
        colors = theme.current()
        if w is None or self._stack.currentIndex() != 0:
            return
        if not len(self._shown):
            self._grid.addLabel("No window passes the filters", color=colors.muted)
            return
        first = (self._page.value() - 1) * PER_PAGE
        rows = range(first, min(first + PER_PAGE, len(self._shown)))
        scale = self.info.shown_scale(self.sensor)
        traces = [w.real(int(self._shown[r])) * scale for r in rows]
        limits = None
        if self._same_scale.isChecked():
            finite = [t[np.isfinite(t)] for t in traces]
            finite = [t for t in finite if len(t)]
            if finite:
                limits = (min(t.min() for t in finite), max(t.max() for t in finite))
        pen = pg.mkPen(colors.trace, width=1.1)
        for k, (r, trace) in enumerate(zip(rows, traces)):
            i = int(self._shown[r])
            look = self.look(i)
            line, column = 2 * (k // GRID_COLUMNS), k % GRID_COLUMNS
            self._heading(
                self._grid,
                f"{self._instance_stamp(i)} · w{int(w.number[i])}<br>"
                f"{self._swatch(look)} <b>{look.text}</b>",
                line,
                column,
                size="8pt",
            )
            plot = self._grid.addPlot(row=line + 1, col=column)
            self._shade_window(plot, i)
            plot.plot(np.arange(len(trace)), trace, pen=pen, connect="finite")
            plot.setXRange(0, w.size, padding=0)
            plot.getAxis("bottom").setStyle(showValues=False)
            plot.getAxis("left").setWidth(52)
            plot.getAxis("left").enableAutoSIPrefix(False)
            plot.hideButtons()
            plot.setMenuEnabled(False)
            plot.setMouseEnabled(x=False, y=False)
            if limits is not None and limits[1] >= limits[0]:
                plot.setYRange(*limits, padding=0.05)
            else:
                self._frame_flat(plot, trace)
            self._thumbs.append((plot, r))
        self._outline_thumb()

    def _outline_thumb(self) -> None:
        colors = theme.current()
        for plot, r in self._thumbs:
            selected = int(self._shown[r]) == self._current
            plot.getViewBox().setBorder(pg.mkPen(colors.highlight, width=3) if selected else None)

    def _on_grid_clicked(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        for plot, r in self._thumbs:
            if plot.sceneBoundingRect().contains(event.scenePos()):
                event.accept()
                self._select_row(r)
                return

    # -- one statistic of every window

    def _draw_features(self) -> None:
        """One point per window along the well (color = label period), and the distribution per period."""
        panel = self._feature_panel
        panel.clear()
        self._feature_plot = None
        w, values = self._windows, self._feature_values
        colors = theme.current()
        feature = self.feature
        if w is None or values is None or self._timemap is None:
            return
        shown_values = values[self._shown]
        finite = np.isfinite(shown_values)
        if not finite.any():
            panel.addLabel(
                "No window passing the filters has this statistic (too few readings, or readings "
                "that never move)",
                color=colors.muted,
            )
            return
        rows = np.flatnonzero(finite)
        picked = self._shown[rows]
        y = shown_values[rows]
        unit = self._figure_unit(feature)
        name = f"{FIGURE_NAMES[feature]}{f' [{unit}]' if unit else ''}"
        period_colors = self._period_colors()
        periods = np.array([self.look(int(i)).period for i in picked])

        key = self._period_key(periods)
        self._heading(
            panel,
            f"<b>{name}</b> along the well: one point per window, joined to its neighbours; "
            f"click a point<br>{key}",
            0,
            0,
        )
        timeline = panel.addPlot(
            row=1,
            col=0,
            axisItems={"bottom": TimeAxisItem(self._timemap)},
            viewBox=ScrollFriendlyViewBox(),
        )
        self._feature_plot = timeline
        pen = pg.mkPen(colors.gap_line, width=1, style=Qt.PenStyle.DashLine)
        for x in self._timemap.gap_centers()[:MAX_GAP_LINES]:
            timeline.addItem(pg.InfiniteLine(pos=x, angle=90, pen=pen), ignoreBounds=True)
        middle = self._x[picked] + w.n_valid[picked] / 7200.0
        # Neighbouring windows are joined by a faint line, broken where a
        # window does not follow on from the one before (a silence, another
        # instance, a window filtered out).
        seconds = w.start[picked].astype("datetime64[s]").astype(np.int64)
        breaks = np.flatnonzero(seconds[1:] > seconds[:-1] + w.n_valid[picked[:-1]] + 1) + 1
        line_x = np.insert(middle, breaks, np.nan)
        line_y = np.insert(y, breaks, np.nan)
        timeline.plot(line_x, line_y, pen=pg.mkPen(colors.faint, width=1), connect="finite")
        scatter = pg.ScatterPlotItem(
            x=middle,
            y=y,
            size=6 if len(y) < 5000 else 4,
            pen=None,
            brush=[self._brush(period_colors[p]) for p in periods],
            data=rows,
        )
        scatter.sigClicked.connect(
            lambda item, points, *rest: len(points) and self._select_row(int(points[0].data()))
        )
        timeline.addItem(scatter)
        timeline.setLabel("left", name)
        timeline.showGrid(x=False, y=True, alpha=0.25)
        timeline.getAxis("left").setWidth(70)
        # The histogram beside shares this axis and reads its values plainly:
        # a prefix on one of the two would make the same value read twice.
        timeline.getAxis("left").enableAutoSIPrefix(False)
        instance = self._box_value(self._instance)
        if instance == ALL:
            timeline.setXRange(0, self._timemap.span, padding=0.01)
        else:
            data = self._wells[self.well]
            x0, x1 = self._timemap.to_x([data.starts[int(instance)], data.ends[int(instance)]])
            timeline.setXRange(float(x0), float(max(x1, x0 + 1 / 60)), padding=0.02)

        low, high = np.percentile(y, [0.5, 99.5]) if len(y) > 20 else (y.min(), y.max())
        if high <= low:
            high = low + max(abs(low) * 1e-6, 1e-9)
        edges = np.linspace(low, high, 41)
        histogram = panel.addPlot(row=1, col=1, viewBox=ScrollFriendlyViewBox())
        for period in PERIODS:
            values_of = y[periods == period]
            if len(values_of) < 3:
                continue
            density, _ = np.histogram(np.clip(values_of, low, high), bins=edges, density=True)
            color = QColor(period_colors[period])
            fill = QColor(color)
            fill.setAlpha(60)
            # A horizontal histogram, sharing the vertical axis of the points:
            # steps drawn by hand.
            ys = np.repeat(edges, 2)[1:-1]
            xs = np.repeat(density, 2)
            curve = pg.PlotCurveItem(xs, ys, pen=pg.mkPen(color, width=1.6))
            zero = pg.PlotCurveItem(np.zeros_like(xs), ys, pen=pg.mkPen(None))
            histogram.addItem(zero)
            histogram.addItem(curve)
            histogram.addItem(pg.FillBetweenItem(zero, curve, brush=pg.mkBrush(fill)))
        # How well the statistic tells normal windows from event ones, the
        # measure the 3w_estudo Janelas tab draws.
        event = np.isin(periods, ("transient", "steady"))
        normal = periods == "normal"
        caption = "distribution per label period"
        if event.sum() >= 5 and normal.sum() >= 5:
            both = event | normal
            caption += (
                f"<br>normal × event separation <b>{wi.separation(y[both], event[both]):.2f}</b>"
                " (|AUC − 0.5| · 2)"
            )
        self._heading(panel, caption, 0, 1)
        histogram.setLabel("bottom", "density")
        histogram.setYLink(timeline)
        margin = 0.05 * (high - low)
        timeline.setYRange(low - margin, high + margin, padding=0)
        panel.ci.layout.setColumnStretchFactor(0, 3)
        panel.ci.layout.setColumnStretchFactor(1, 1)
        self._mark_feature()

    def _period_colors(self) -> dict[str, str]:
        colors = theme.current()
        return {
            "normal": colors.live,
            "transient": colors.warning,
            "steady": colors.fallback_fault,
            "unknown": colors.faint,
        }

    def _mark_feature(self) -> None:
        plot = self._feature_plot
        if plot is None:
            return
        for item in list(plot.items):
            if getattr(item, "_selection_mark", False):
                plot.removeItem(item)
        values = self._feature_values
        if self._current < 0 or values is None or not np.isfinite(values[self._current]):
            return
        i = self._current
        mark = pg.ScatterPlotItem(
            x=[float(self._x[i] + self._windows.n_valid[i] / 7200.0)],
            y=[float(values[i])],
            size=13,
            pen=pg.mkPen(theme.current().outline, width=2),
            brush=pg.mkBrush(0, 0, 0, 0),
        )
        mark._selection_mark = True
        plot.addItem(mark)

    # -- the window selected

    def _select_row(self, row: int) -> None:
        """Select one row of the table, which draws its window below."""
        if 0 <= row < len(self._shown):
            self._table.selectRow(row)
            self._table.scrollTo(self._model.index(row, 0))
            if self._table.currentIndex().row() == row:
                self._on_row(row)

    def _on_row(self, row: int) -> None:
        if row < 0 or row >= len(self._shown) or self._windows is None:
            return
        i = int(self._shown[row])
        if i == self._current:
            return
        self._current = i
        page = row // PER_PAGE + 1
        if self._stack.currentIndex() == 0 and page != self._page.value():
            self._page.setValue(page)  # draws the grid, outlined
        else:
            self._outline_thumb()
        self._mark_map()
        self._mark_feature()
        self._draw_detail()
        self.status.emit(self.describe(i))

    def _draw_detail(self) -> None:
        """The window selected, large, and the instance it was cut from with its place in it."""
        self._detail.clear()
        i = self._current
        w, series = self._windows, self._current_series
        if i < 0 or w is None or series is None:
            return
        colors = theme.current()
        look = self.look(i)
        scale = self.info.shown_scale(self.sensor)
        unit = self.info.shown_unit(self.sensor)
        n_valid = int(w.n_valid[i])
        real = w.real(i) * scale

        window = self._detail.addPlot(row=1, col=0, viewBox=ScrollFriendlyViewBox())
        padding = f" | {w.size - n_valid} samples of padding" if n_valid < w.size else ""
        title = (
            f"window {int(w.number[i])} of {self._refs[int(w.instance[i])].title} | "
            f"{self._start_text(i)}{padding}<br>{self._swatch(look)} <b>{look.text}</b> "
            f"({PERIOD_NAMES[look.period]})"
        )
        feature, values = self.feature, self._feature_values
        if feature and values is not None and not np.isnan(values[i]):
            value = float(values[i])
            title += f" | <b>{FIGURE_NAMES[feature]} = {self._figure_text(feature, value)}</b>"
            marker = pg.mkPen(colors.highlight, width=2, style=Qt.PenStyle.DashLine)
            if feature in LEVEL:
                window.addItem(
                    pg.InfiniteLine(
                        pos=value,
                        angle=0,
                        pen=marker,
                        label=FIGURE_NAMES[feature],
                        labelOpts={"color": colors.highlight, "position": 0.05},
                    )
                )
            band = None
            if feature == "std" and self._figures is not None:
                mean = float(self._figures["mean"][i])
                band = (mean - value, mean + value)
            if band is not None:
                fill = QColor(colors.highlight)
                fill.setAlpha(45)
                window.addItem(
                    pg.LinearRegionItem(
                        values=band,
                        orientation="horizontal",
                        movable=False,
                        brush=pg.mkBrush(fill),
                        pen=marker,
                    )
                )
        self._heading(self._detail, title, 0, 0)
        self._shade_window(window, i)
        window.plot(
            np.arange(n_valid), real, pen=pg.mkPen(colors.trace, width=1.4), connect="finite"
        )
        window.setXRange(0, w.size, padding=0.01)
        self._frame_flat(window, real)
        window.setLabel("left", f"{self.sensor}{f' [{unit}]' if unit else ''}")
        window.getAxis("left").enableAutoSIPrefix(False)
        window.setLabel("bottom", "sample in the window (s)")

        instance = self._detail.addPlot(row=1, col=1, viewBox=ScrollFriendlyViewBox())
        k = series.index_of(int(w.instance[i]))
        span = series.span(k)
        stamps = series.stamps[span]
        hours = (stamps - stamps[0]) / np.timedelta64(3600, "s") if len(stamps) else np.zeros(0)
        labels = series.labels[span]
        shading = SegmentsItem(z=-10)
        x0, x1, fills, names, hatched = [], [], [], [], []
        folder = int(self._refs[int(w.instance[i])].fault)
        for a, b, value in runs(labels):
            run_look = self._look_of(wi.UNLABELED if np.isnan(value) else value, folder)
            x0.append(hours[a])
            x1.append(hours[b - 1] + 1 / 3600)
            fills.append(run_look.background)
            names.append(run_look.name)
            hatched.append(run_look.unknown)
        shading.set_segments(x0, x1, fills, names, hatched=hatched)
        instance.addItem(shading, ignoreBounds=True)
        repeated = series.repeated[span]
        if self.drop_repeated and repeated.any():
            faint = QColor(colors.faint)
            left_out = SegmentsItem(z=-9, hatch=QBrush(faint, REPEATED_TEXTURE))
            ends = [(a, b) for a, b, value in runs(repeated.astype(float)) if value]
            left_out.set_segments(
                [hours[a] for a, _ in ends],
                [hours[b - 1] + 1 / 3600 for _, b in ends],
                [f"#30{faint.name()[1:]}"] * len(ends),
                hatched=[True] * len(ends),
            )
            instance.addItem(left_out, ignoreBounds=True)
        # The window is a sliver of a long instance (512 s of twenty hours is
        # under 1 % of the axis), so it is told apart three ways: the rest of
        # the instance faded and the window's own stretch drawn full and thick,
        # a strong band with edges in the outline color, and a labeled marker
        # that stays in sight when the band is a pixel wide.
        readings = series.values[span] * scale
        trace = instance.plot(
            hours,
            readings,
            pen=pg.mkPen(tint(colors.trace, 0.5), width=1),
            connect="finite",
        )
        trace.setDownsampling(auto=True, method="peak")
        trace.setClipToView(True)
        first = int(w.first[i])
        start = hours[first] if first < len(hours) else 0.0
        end = start + n_valid / 3600
        fill = QColor(colors.highlight)
        fill.setAlpha(110)
        band = pg.LinearRegionItem(
            values=(start, end),
            movable=False,
            brush=pg.mkBrush(fill),
            pen=pg.mkPen(colors.outline, width=2),
        )
        band.setZValue(-5)  # over the label shading, under the traces
        instance.addItem(band)
        own = instance.plot(
            hours[first : first + n_valid],
            readings[first : first + n_valid],
            pen=pg.mkPen(colors.trace, width=2.4),
            connect="finite",
        )
        own.setZValue(5)
        marker = pg.InfiniteLine(
            pos=0.5 * (start + end),
            angle=90,
            pen=pg.mkPen(colors.outline, width=1, style=Qt.PenStyle.DashLine),
            label=f"window {int(w.number[i])}",
            labelOpts={
                "position": 0.92,
                "color": colors.text,
                "fill": pg.mkBrush(colors.note_fill),
                "border": pg.mkPen(colors.note_border, width=0.6),
            },
        )
        marker.setZValue(6)
        instance.addItem(marker, ignoreBounds=True)
        note = "the window (band and marker) in its instance, shaded by label, the rest faded"
        if self.drop_repeated and repeated.any():
            note += (
                "<br>the hatched head repeats an earlier instance and is left out of the windows"
            )
        self._heading(self._detail, note, 0, 1)
        instance.setLabel("bottom", "hours since the instance's first sample")
        instance.getAxis("left").enableAutoSIPrefix(False)
        self._detail.ci.layout.setColumnStretchFactor(0, 2)
        self._detail.ci.layout.setColumnStretchFactor(1, 3)

    def open_selected(self) -> None:
        """Open the instance of the window selected, on the page's sensor."""
        if self._current < 0 or self._windows is None or self.well not in self._wells:
            return
        position = int(self._windows.instance[self._current])
        self.open_requested.emit(self._wells[self.well], position, [self.sensor])

    # -- what leaves the page

    def summary(self) -> str:
        return self._summary

    def reset_views(self) -> None:
        self._frame_map()
        for item in self._detail.ci.items:
            if isinstance(item, pg.PlotItem):
                item.getViewBox().autoRange()
        if self._feature_plot is not None:
            self._draw_features()

    def shown_files(self) -> list[tuple[int, str]]:
        """The instances behind the windows on show, for the file list a Toolkit loader takes."""
        if self._windows is None:
            return []
        positions = sorted(set(self._windows.instance[self._shown].tolist()))
        return [(self._refs[p].fault, self._refs[p].file) for p in positions]

    def shown_source(self) -> str:
        """Where the file list came from, for its provenance."""
        filters = [self._fault.currentText(), self._label.currentText()]
        return (
            f"the Windows page | {well_label(self.well)} | {self.sensor} | windows of "
            f"{self.size} samples | {self._instance.currentText()} | "
            + " | ".join(text.split(" (")[0] for text in filters)
        )
