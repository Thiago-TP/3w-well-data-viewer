"""The dispersion page: two sensors against each other over a scope, as a cloud one can read.

Melo's scatter plots of two 3W variables (thesis, section 4.2.5) are static
figures of one instance, and what they show is the historian's lines: the
cloud of two interpolated series is the trajectories of the interpolations,
straight segments between the few instants that were measured. This page
draws that cloud for any pair of sensors over every real instance, one fault
class or one well (or the joined bars) and lets it be read rather than
looked at: every dot is a sample that names its instance and its instant on
hover, lights up every other dot of that instance while the rest of the
cloud fades, and opens it on click; the density of the samples sits behind
the dots; the label periods are switched on and off; the dots can be the
measurements alone. The reading is done once per scope, every analog sensor
at once, so that everything else is instant.
"""

import time

import numpy as np
import pandas as pd
import pyqtgraph as pg
from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from overlap_viewer.algorithms import dispersion as di
from overlap_viewer.backend import theme
from overlap_viewer.backend.availability import LIVE, Availability
from overlap_viewer.backend.dataset import (
    DatasetInfo,
    WellData,
    load_instance,
    merge_instances,
    well_label,
)
from overlap_viewer.backend.palette import fault_color, tint
from overlap_viewer.frontend.heatmap import ColorKey
from overlap_viewer.frontend.items import ScrollFriendlyViewBox, restyle_axes
from overlap_viewer.frontend.loading import progress_dialog
from overlap_viewer.frontend.overview import ElidedLabel
from overlap_viewer.frontend.passes import Passes

HINT = (
    "Every dot is one sample of two sensors | hover a dot for its instance, its instant and its "
    "readings, and to light up every dot of that instance | click it to open the instance | the "
    "shading behind is the density of the samples | drag to pan | Ctrl + wheel to zoom | F1 for help"
)
COLORINGS = ("Fault class", "Well", "Label period", "Density")
DOT_PX = 3
DOT_ALPHA = 130
HIGHLIGHT_PX = 11
HOVER_PX = 8
KIN_PX = DOT_PX + 3  # the other dots of the hovered dot's instance
FADE_OPACITY = 0.18  # the rest of the cloud while one instance is lit
DENSITY_ALPHA = 0.45  # behind the dots; full when the density is the coloring

SENSOR_TIP = (
    "One of the two sensors: X runs along the bottom, Y up the side. Readings outside the "
    "plausible range are left out. The count is how many real instances recorded the sensor."
)
SCOPE_TIP = (
    "The instances the samples come from: all of them, those of one fault class, or those of one "
    "well. The first look at a scope reads its instances in full, behind a progress dialog, "
    "every analog sensor at once, and keeps an even subsample of the rows for the session, so "
    "that changing the sensors, the coloring or the filters is instant. Pooling wells mixes "
    "their levels: two clouds side by side may be two wells, not one relation."
)
COLORING_TIP = (
    "What colors the dots: the fault folder of the sample's instance, its well, or the label "
    "period the sample was in (normal operation, transient, steady state, unlabeled). Density "
    "hides the dots and shows the two-dimensional histogram of the samples alone, darkest where "
    "most of them fall."
)
GENUINE_TIP = (
    "Draw only the samples at which both sensors were actually measured (the readings the "
    "historian archived) rather than the samples it filled in by drawing lines between them. "
    "On 3W most sensors were read every ten seconds to every two minutes, so the cloud thins to "
    "a few per cent of its dots and the straight trajectories vanish. One caveat: a historian "
    "archives a reading when it has moved enough, so the instants at which both sensors were "
    "archived are instants at which both moved, and this cloud favours the relation between "
    "them: on the severe-slugging instances P-TPT × T-TPT reads +0.40 over every sample and +0.95 "
    "over the 5 % at which both were measured."
)
PERIODS_TIP = (
    "Which samples are drawn, by what the experts labeled the well as doing at that instant. A "
    "fault's steady state alone shows the relation under the fault; normal operation alone the "
    "relation the fault departs from; the transient the path between."
)
DENSITY_TIP = (
    "Shade the plane behind the dots by how many samples fall in each cell of a grid, darker for "
    "more, on a logarithmic scale; the dots are an even subsample of the samples, the density "
    "counts them all."
)


class DispersionPage(QWidget):
    """The page: the boxes, the cloud, its key and its caption, and the instance a dot opens.

    Signals
    -------
    status(str)
        What the main window's status bar should say.
    summary_changed()
        The one-line description of the cloud has changed.
    open_requested(WellData, int)
        A dot was clicked: the view and the bar to open.
    """

    status = Signal(str)
    summary_changed = Signal()
    open_requested = Signal(object, int)

    def hint(self) -> str:
        return HINT

    def __init__(self, info: DatasetInfo, passes: Passes | None = None, parent=None):
        super().__init__(parent)
        self.info = info
        self._passes = passes
        self._catalogue: pd.DataFrame | None = None
        self._wells: list[WellData] = []
        self._availability: Availability | None = None
        # The clouds read so far, by (scope kind, scope key, joined).
        self._clouds: dict[tuple, di.Cloud] = {}
        self._cloud: di.Cloud | None = None
        self._pair: di.Pair | None = None
        self._dots = np.zeros(0, dtype=int)  # positions in the pair drawn as dots
        self._density: tuple[np.ndarray, np.ndarray, np.ndarray] | None = None
        self._groups: list[pg.ScatterPlotItem] = []
        self._dot_instances = np.zeros(0, dtype=int)  # the instance of every dot drawn
        self._dot_fills = np.zeros(0, dtype=object)  # and its color
        self._pending = False
        self._hover = -1
        self._hover_instance = -1
        self._summary = ""
        self._read_s = 0.0
        # What the view was last framed on: the cloud and the pair and filters
        # drawn of it. The view is framed afresh only when that changes.
        self._framed: tuple | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self._build_toolbar())
        layout.addWidget(self._build_second_bar())
        self._plot_widget = pg.PlotWidget(viewBox=ScrollFriendlyViewBox())
        plot = self._plot_widget.getPlotItem()
        plot.hideButtons()
        plot.setMenuEnabled(True)
        plot.getViewBox().setMouseMode(pg.ViewBox.PanMode)
        plot.showGrid(x=True, y=True, alpha=0.15)
        self._image = pg.ImageItem()
        self._image.setZValue(0)
        plot.addItem(self._image)
        self._highlight = pg.ScatterPlotItem(size=HIGHLIGHT_PX, pxMode=True)
        self._highlight.setZValue(20)
        plot.addItem(self._highlight, ignoreBounds=True)
        # The other dots of the hovered dot's instance, brought forward over the faded cloud.
        self._kin = pg.ScatterPlotItem(size=KIN_PX, pxMode=True)
        self._kin.setZValue(15)
        plot.addItem(self._kin, ignoreBounds=True)
        self._plot_widget.scene().sigMouseMoved.connect(self._on_mouse_moved)
        self._plot_widget.scene().sigMouseClicked.connect(self._on_mouse_clicked)
        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(8, 0, 8, 0)
        body_layout.addWidget(self._plot_widget, 1)
        layout.addWidget(body, 1)
        self._note = ElidedLabel("")
        self._note.setContentsMargins(8, 0, 8, 2)
        layout.addWidget(self._note)
        self._restyle()

    # -- construction

    def _build_toolbar(self) -> QToolBar:
        bar = QToolBar("Dispersion")
        bar.setMovable(False)
        bar.addWidget(QLabel(" X "))
        self._x = QComboBox()
        self._x.setToolTip(SENSOR_TIP)
        self._x.currentIndexChanged.connect(self._redraw)
        bar.addWidget(self._x)
        bar.addWidget(QLabel(" Y "))
        self._y = QComboBox()
        self._y.setToolTip(SENSOR_TIP)
        self._y.currentIndexChanged.connect(self._redraw)
        bar.addWidget(self._y)

        bar.addSeparator()
        bar.addWidget(QLabel(" Over "))
        self._scope = QComboBox()
        self._scope.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self._scope.setToolTip(SCOPE_TIP)
        self._scope.currentIndexChanged.connect(self._refresh)
        bar.addWidget(self._scope)
        self._join = QCheckBox("Join overlapping instances")
        self._join.setToolTip(
            "Read the joined bars (the merged recordings of the instances of a well that overlap "
            "in time and agree in their labels) instead of the instances, so that a sample two "
            "windows share is drawn once."
        )
        self._join.toggled.connect(self._refresh)
        bar.addWidget(self._join)

        bar.addSeparator()
        bar.addWidget(QLabel(" Color by "))
        self._coloring = QComboBox()
        self._coloring.addItems(list(COLORINGS))
        self._coloring.setToolTip(COLORING_TIP)
        self._coloring.currentIndexChanged.connect(self._redraw)
        bar.addWidget(self._coloring)

        bar.addSeparator()
        self._genuine = QCheckBox("Measurements only")
        self._genuine.setToolTip(GENUINE_TIP)
        self._genuine.toggled.connect(self._redraw)
        bar.addWidget(self._genuine)
        return bar

    def _build_second_bar(self) -> QToolBar:
        bar = QToolBar("Filters")
        bar.setMovable(False)
        label = QLabel(" Label periods ")
        label.setToolTip(PERIODS_TIP)
        bar.addWidget(label)
        self._periods: dict[int, QCheckBox] = {}
        for code, name in enumerate(di.PERIODS):
            check = QCheckBox(di.PERIOD_NAMES[name])
            check.setChecked(True)
            check.setToolTip(PERIODS_TIP)
            check.toggled.connect(self._redraw)
            bar.addWidget(check)
            self._periods[code] = check
        bar.addSeparator()
        self._density_check = QCheckBox("Density behind the dots")
        self._density_check.setChecked(True)
        self._density_check.setToolTip(DENSITY_TIP)
        self._density_check.toggled.connect(self._redraw)
        bar.addWidget(self._density_check)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        bar.addWidget(spacer)
        self._key = ColorKey()
        bar.addWidget(self._key)
        bar.addWidget(QLabel("  "))
        return bar

    # -- appearance

    def _restyle(self) -> None:
        colors = theme.current()
        self._plot_widget.setBackground(colors.plot_background)
        # This page keeps one plot for its whole life, so its axes have to be
        # given the new foreground themselves: pyqtgraph froze the old one into
        # their pens when they were built, grid included.
        restyle_axes(self._plot_widget.getPlotItem())
        self._note.setStyleSheet(f"color: {colors.muted}; font-size: 8pt;")

    def apply_theme(self) -> None:
        self._restyle()
        self._key.apply_theme()
        self._redraw()

    # -- the state of the boxes

    @property
    def x(self) -> str | None:
        data = self._x.currentData()
        return None if data is None else str(data)

    @property
    def y(self) -> str | None:
        data = self._y.currentData()
        return None if data is None else str(data)

    @property
    def joined(self) -> bool:
        return self._join.isChecked()

    @property
    def coloring(self) -> str:
        return self._coloring.currentText()

    @property
    def genuine_only(self) -> bool:
        return self._genuine.isChecked()

    @property
    def periods(self) -> list[int]:
        return [code for code, check in self._periods.items() if check.isChecked()]

    def _scope_key(self) -> tuple:
        kind, key = self._scope.currentData() or ("all", -1)
        return (str(kind), int(key), self.joined)

    def _scope_name(self) -> str:
        text = self._scope.currentText().split(" (")[0]
        return text or "All real instances"

    # -- data

    def set_catalogue(self, catalogue: pd.DataFrame, wells: list[WellData]) -> None:
        """Take a new catalogue: what was read described the old one and is dropped.

        The very same catalogue again is the main window laying the pages out
        in a new theme, not new data: the clouds read over it are as true in
        one theme as in the other, and each of them is a pass over every
        instance of its scope. They are kept, and only drawn again.
        """
        if catalogue is not self._catalogue:
            self._clouds = {}
            self._framed = None
            self._cloud = None
            self._pair = None
        self._catalogue = catalogue
        self._wells = list(wells)
        self._availability = Availability.from_wells(wells, self.info)
        self._fill_sensors()
        self._fill_scopes()
        self._pending = True
        if self.isVisible():
            QTimer.singleShot(0, self._ensure_and_draw)

    def _analog_sensors(self) -> list[str]:
        availability = self._availability
        return [name for name in availability.sensors if not self.info.is_enumerated(name)]

    def _fill_sensors(self) -> None:
        """Offer every analog sensor in both boxes, the two best covered chosen to start with."""
        availability = self._availability
        live = {
            name: int((availability.state[:, j] == LIVE).sum())
            for j, name in enumerate(availability.sensors)
        }
        analog = self._analog_sensors()
        best = sorted(analog, key=lambda name: (-live[name], name))
        wanted = (self.x, self.y)
        defaults = (best[0] if best else None, best[1] if len(best) > 1 else None)
        for k, box in enumerate((self._x, self._y)):
            box.blockSignals(True)
            box.clear()
            for name in analog:
                box.addItem(f"{name} ({live[name]})", name)
                item = box.model().item(box.count() - 1)
                item.setEnabled(live[name] > 0)
                unit = self.info.shown_unit(name)
                item.setToolTip(
                    f"{name}{f' [{unit}]' if unit else ''}\n"
                    f"{self.info.sensor_descriptions.get(name, '')}\n"
                    f"live in {live[name]} real instances"
                )
            index = box.findData(wanted[k]) if wanted[k] is not None else -1
            if index < 0 and defaults[k] is not None:
                index = box.findData(defaults[k])
            box.setCurrentIndex(max(index, 0))
            box.blockSignals(False)

    def _fill_scopes(self) -> None:
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
                    f"{fault}. {self.info.fault_name(int(fault))} ({int(faults[fault])} instances)",
                    ("class", int(fault)),
                )
            wells = self._catalogue["well"].value_counts()
            if len(wells):
                self._scope.insertSeparator(self._scope.count())
            for well in sorted(wells.index):
                self._scope.addItem(
                    f"{well_label(int(well))} ({int(wells[well])} instances)", ("well", int(well))
                )
        index = -1
        if wanted is not None:
            for k in range(self._scope.count()):
                if self._scope.itemData(k) == wanted:
                    index = k
                    break
        self._scope.setCurrentIndex(max(index, 0))
        self._scope.blockSignals(False)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._pending:
            QTimer.singleShot(0, self._ensure_and_draw)

    def _ensure_and_draw(self) -> None:
        if not self._pending or not self.isVisible():
            return
        self._pending = False
        self._refresh()

    def _view_wells(self, joined: bool) -> list[WellData]:
        return [well.joined() for well in self._wells] if joined else self._wells

    def _in_scope(self, data: WellData, index: int, kind: str, key: int) -> bool:
        if kind == "well":
            return data.well == key
        if kind == "class":
            return key in {fault for fault, _ in data.colors[index]}
        return True

    def _frame(self, path) -> pd.DataFrame:
        if self._passes is not None:
            return self._passes.frames.get(path)
        return load_instance(path)

    def _load_cloud(self) -> bool:
        """Have the cloud of the scope and view on show, reading the data if need be; ``False`` if cancelled."""
        key = self._scope_key()
        if key in self._clouds:
            self._cloud = self._clouds[key]
            return True
        if self._availability is None:
            return False
        kind, scope_key, joined = key
        bars = [
            (data, index)
            for data in self._view_wells(joined)
            for index in range(data.n_instances)
            if self._in_scope(data, index, kind, scope_key)
        ]
        analog = self._analog_sensors()
        availability = self._availability
        bounds = [availability.ranges[availability.sensors.index(name)] for name in analog]
        reader = di.DispersionPass(
            analog, bounds, len(bars), transient_offset=self.info.transient_offset
        )
        noun = "bars" if joined else "instances"
        dialog, progress = progress_dialog(
            f"Reading the {len(bars)} {noun} of {self._scope_name()} for the dispersion view "
            f"(every analog sensor, one row in a few)…",
            self.window(),
        )
        started = time.perf_counter()
        try:
            for k, (data, index) in enumerate(bars, start=1):
                row = data.rows.iloc[index]
                paths = data.origin.rows["path"]
                frames = [self._frame(paths.iloc[m]) for m in data.members[index]]
                frame = merge_instances(frames) if len(frames) > 1 else frames[0]
                ref = di.InstanceRef(
                    int(data.well),
                    int(index),
                    int(row["fault_class"]),
                    str(row["file"]) if "file" in data.rows.columns and not joined else "",
                    str(row["title"]),
                    pd.Timestamp(frame.index[0]) if len(frame) else pd.Timestamp(row["start"]),
                )
                reader.add(frame, ref)
                if not progress(k, len(bars), str(row["title"])):
                    return False
        finally:
            dialog.close()
            dialog.deleteLater()
        self._read_s = time.perf_counter() - started
        self._cloud = self._clouds[key] = reader.result()
        return True

    def _refresh(self, *args) -> None:
        """Have the cloud of the boxes, reading if need be, and draw it."""
        if self._availability is None:
            return
        if not self._load_cloud():
            self._cloud = None
            self._pair = None
            self._clear_plot()
            self._note.setText("The instances were not read. Choose the scope again to read them.")
            self._summary = ""
            self.summary_changed.emit()
            return
        self._redraw()

    # -- drawing

    def _clear_plot(self) -> None:
        plot = self._plot_widget.getPlotItem()
        for item in self._groups:
            plot.removeItem(item)
        self._groups = []
        self._image.clear()
        self._highlight.setData([], [])
        self._kin.setData([], [])
        self._hover_instance = -1
        self._dots = np.zeros(0, dtype=int)
        self._dot_instances = np.zeros(0, dtype=int)
        self._dot_fills = np.zeros(0, dtype=object)
        self._density = None

    def _well_colors(self) -> dict[int, str]:
        palette = theme.current().wells
        return {
            well.well: palette[k % len(palette)]
            for k, well in enumerate(sorted(self._wells, key=lambda w: w.well))
        }

    def _period_colors(self) -> dict[int, str]:
        colors = theme.current()
        return {
            di.NORMAL: colors.live,
            di.TRANSIENT: colors.warning,
            di.STEADY: colors.fallback_fault,
            di.UNLABELED: colors.faint,
        }

    def _dot_colors(self, rows: np.ndarray) -> tuple[np.ndarray, list[tuple[str, str]]]:
        """The color of every dot under the coloring chosen, and the key that names the colors."""
        cloud, coloring = self._cloud, self.coloring
        if coloring == "Well":
            wells = self._well_colors()
            values = cloud.well[rows]
            present = sorted(set(values.tolist()))
            table = {w: wells.get(int(w), theme.current().faint) for w in present}
            colors = np.array([table[int(w)] for w in values]) if len(values) else np.array([])
            key = [(table[w], well_label(int(w))) for w in present]
            if len(key) > 12:
                key = key[:12] + [(theme.current().faint, f"+{len(present) - 12} more wells")]
            return colors, key
        if coloring == "Label period":
            table = self._period_colors()
            values = cloud.period[rows]
            present = sorted(set(values.tolist()))
            colors = np.array([table[int(p)] for p in values]) if len(values) else np.array([])
            key = [(table[p], di.PERIOD_NAMES[di.PERIODS[p]]) for p in present]
            return colors, key
        values = cloud.fault[rows]
        present = sorted(set(values.tolist()))
        table = {f: fault_color(int(f)) for f in present}
        colors = np.array([table[int(f)] for f in values]) if len(values) else np.array([])
        key = [(table[f], f"{f}. {self.info.fault_name(int(f))}") for f in present]
        return colors, key

    def _redraw(self, *args) -> None:
        """Draw the pair of sensors of the cloud on hand under the boxes; nothing is read."""
        cloud = self._cloud
        self._clear_plot()
        plot = self._plot_widget.getPlotItem()
        colors = theme.current()
        x, y = self.x, self.y
        if cloud is None or x is None or y is None or x not in cloud.sensors:
            self._pair = None
            return
        scales = (self.info.shown_scale(x), self.info.shown_scale(y))
        pair = cloud.pair(x, y, self.periods, self.genuine_only, scales)
        self._pair = pair
        self._dots = pair.dots(di.MAX_DOTS)
        self._dot_instances = cloud.instance[pair.rows[self._dots]]
        # The density of every row, behind the dots or in their place.
        density_shown = self.coloring == "Density" or self._density_check.isChecked()
        self._density = pair.density(di.BINS) if pair.n else None
        if density_shown and self._density is not None:
            counts, xedges, yedges = self._density
            image = np.log1p(counts)
            top = float(image.max())
            self._image.setImage(image / top if top > 0 else image, levels=(0.0, 1.0))
            self._image.setRect(
                QRectF(
                    float(xedges[0]),
                    float(yedges[0]),
                    float(xedges[-1] - xedges[0]),
                    float(yedges[-1] - yedges[0]),
                )
            )
            ramp = pg.ColorMap(
                [0.0, 1.0],
                [QColor(colors.plot_background), QColor(colors.live)],
            )
            self._image.setLookupTable(ramp.getLookupTable(0.0, 1.0, 256))
            self._image.setOpacity(1.0 if self.coloring == "Density" else DENSITY_ALPHA)
            self._image.show()
        else:
            self._image.hide()
        # The dots, one scatter item per color so that a hundred thousand draw at once.
        if self.coloring == "Density":
            key = [
                (colors.live, "many samples in the cell"),
                (tint(colors.live, 0.15), "few"),
            ]
        else:
            fills, key = self._dot_colors(pair.rows[self._dots])
            self._dot_fills = fills
            for color in sorted(set(fills.tolist())):
                picked = np.flatnonzero(fills == color)
                item = pg.ScatterPlotItem(
                    x=pair.x[self._dots[picked]],
                    y=pair.y[self._dots[picked]],
                    size=DOT_PX,
                    pxMode=True,
                    pen=None,
                    brush=pg.mkBrush(QColor(color[:7] + f"{DOT_ALPHA:02x}")),
                )
                item.setZValue(10)
                plot.addItem(item)
                self._groups.append(item)
        self._key.set_entries(key)
        unit_x, unit_y = self.info.shown_unit(x), self.info.shown_unit(y)
        plot.setLabel("bottom", f"{x}{f' [{unit_x}]' if unit_x else ''}")
        plot.setLabel("left", f"{y}{f' [{unit_y}]' if unit_y else ''}")
        # Framed afresh only when what is drawn changes: a new cloud, pair or
        # filter moves the points, while the coloring and the density behind
        # them do not, and throwing away a zoom for those would be a nuisance.
        framing = (self._scope_key(), x, y, tuple(self.periods), self.genuine_only)
        if pair.n and framing != self._framed:
            plot.getViewBox().autoRange(padding=0.04)
            self._framed = framing
        self._note.setText(self._caption(pair))
        self._summary = self._summary_text(pair)
        self.summary_changed.emit()
        self.status.emit(HINT)

    def _caption(self, pair: di.Pair) -> str:
        cloud = self._cloud
        noun = "bars" if self.joined else "instances"
        parts = [
            (
                f"{len(self._dots):,} dots of {pair.n:,} samples of {self.x} × {self.y}, kept one "
                f"in {cloud.stride:.0f} from the {cloud.n_samples:,} of the {cloud.n_instances} "
                f"{noun} of {self._scope_name()}"
            )
        ]
        if len(self.periods) < len(di.PERIODS):
            names = [di.PERIOD_NAMES[di.PERIODS[p]] for p in self.periods] or ["none"]
            parts.append("label periods: " + ", ".join(names))
        rho = pair.pearson()
        if np.isfinite(rho):
            parts.append(f"Pearson over these samples {rho:+.2f}")
        if self.genuine_only:
            parts.append(
                f"measurements only: both sensors read at the instant, "
                f"{pair.n / max(pair.n_candidates, 1):.1%} of the samples"
            )
        else:
            parts.append(
                "on the 1 Hz grid most dots lie on the historian's lines between measurements; "
                "tick Measurements only for the readings alone"
            )
        if self._read_s >= 1.0:
            parts.append(f"read in {self._read_s:.0f} s")
        return " | ".join(parts)

    def _summary_text(self, pair: di.Pair) -> str:
        cloud = self._cloud
        noun = "bars" if self.joined else "instances"
        return (
            f"{pair.n:,} samples of {self.x} × {self.y} over {cloud.n_instances} {noun} of "
            f"{self._scope_name()} "
        )

    def summary(self) -> str:
        return self._summary

    def reset_views(self) -> None:
        self._plot_widget.getPlotItem().getViewBox().autoRange(padding=0.04)

    # -- pointer

    def _nearest(self, scene_pos) -> int:
        """The dot under the pointer, as a position in the pair, or ``-1``."""
        vb = self._plot_widget.getPlotItem().getViewBox()
        pair = self._pair
        if (
            pair is None
            or not len(self._dots)
            or self.coloring == "Density"
            or not vb.sceneBoundingRect().contains(scene_pos)
        ):
            return -1
        point = vb.mapSceneToView(scene_pos)
        px, py = vb.viewPixelSize()
        dx = (pair.x[self._dots] - point.x()) / px
        dy = (pair.y[self._dots] - point.y()) / py
        distance = np.hypot(dx, dy)
        k = int(np.argmin(distance))
        return int(self._dots[k]) if distance[k] <= HOVER_PX else -1

    def _density_here(self, scene_pos) -> tuple[int, float, float] | None:
        """How many samples fall in the density cell under the pointer, and where that is."""
        if self._density is None:
            return None
        vb = self._plot_widget.getPlotItem().getViewBox()
        if not vb.sceneBoundingRect().contains(scene_pos):
            return None
        point = vb.mapSceneToView(scene_pos)
        counts, xedges, yedges = self._density
        i, j = di.bin_of(xedges, point.x()), di.bin_of(yedges, point.y())
        if i < 0 or j < 0:
            return None
        return int(counts[i, j]), float(point.x()), float(point.y())

    def _light_instance(self, instance: int) -> int:
        """Bring every dot of one instance forward and fade the rest; ``-1`` restores the cloud.

        The dots of one instance are its trajectory through the plane, which
        is what Melo read the scatter plots for; one lit against a faded cloud
        can be followed with the eye where a hundred thousand dots of every
        instance are one smear. Returns how many dots of the instance are on
        show.
        """
        if instance == self._hover_instance:
            return int((self._dot_instances == instance).sum()) if instance >= 0 else 0
        self._hover_instance = instance
        if instance < 0:
            self._kin.setData([], [])
            for item in self._groups:
                item.setOpacity(1.0)
            return 0
        pair = self._pair
        picked = np.flatnonzero(self._dot_instances == instance)
        kin = self._dots[picked]
        outline = pg.mkPen(theme.current().outline, width=0.8)
        self._kin.setData(
            pair.x[kin],
            pair.y[kin],
            brush=[pg.mkBrush(QColor(color)) for color in self._dot_fills[picked]],
            pen=outline,
        )
        for item in self._groups:
            item.setOpacity(FADE_OPACITY)
        return len(kin)

    def _on_mouse_moved(self, pos) -> None:
        index = self._nearest(pos)
        pair = self._pair
        if index != self._hover:
            self._hover = index
            if index >= 0 and pair is not None:
                colors = theme.current()
                self._highlight.setData(
                    [float(pair.x[index])],
                    [float(pair.y[index])],
                    pen=pg.mkPen(colors.outline, width=1.5),
                    brush=pg.mkBrush(0, 0, 0, 0),
                )
            else:
                self._highlight.setData([], [])
        kin = self._light_instance(
            int(self._cloud.instance[pair.rows[index]]) if index >= 0 and pair is not None else -1
        )
        text = self.describe(index) if index >= 0 else ""
        if index >= 0 and kin > 1:
            text = f"{text} | {kin:,} dots of this instance on show, brought forward"
        cell = self._density_here(pos)
        if cell is not None and (self._density_check.isChecked() or self.coloring == "Density"):
            count, px, py = cell
            here = (
                f"{count:,} samples in this cell of the density "
                f"({self.x} ≈ {px:g}, {self.y} ≈ {py:g})"
            )
            text = f"{text} | {here}" if text else here
        self.status.emit(text or HINT)

    def _on_mouse_clicked(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        index = self._nearest(event.scenePos())
        if index < 0 or self._cloud is None:
            return
        event.accept()
        ref = self._cloud.ref(int(self._pair.rows[index]))
        data = next((w for w in self._view_wells(self.joined) if w.well == ref.well), None)
        if data is not None:
            self.open_requested.emit(data, ref.position)

    def describe(self, index: int) -> str:
        """One line about a dot: its instance, its instant, its label period and its two readings."""
        cloud, pair = self._cloud, self._pair
        row = int(pair.rows[index])
        ref = cloud.ref(row)
        when = cloud.timestamp(row)
        period = di.PERIOD_NAMES[di.PERIODS[int(cloud.period[row])]]
        unit_x, unit_y = self.info.shown_unit(self.x), self.info.shown_unit(self.y)
        i, j = cloud.sensors.index(self.x), cloud.sensors.index(self.y)
        measured = [
            f"{name} {'measured' if cloud.genuine[row, k] else 'filled in'}"
            for name, k in ((self.x, i), (self.y, j))
        ]
        parts = [
            f"{well_label(ref.well)} | {ref.title} | {self.info.fault_name(ref.fault)} ({period})",
            f"{when:%Y-%m-%d %H:%M:%S}",
            f"{self.x} {pair.x[index]:g}{f' {unit_x}' if unit_x else ''}",
            f"{self.y} {pair.y[index]:g}{f' {unit_y}' if unit_y else ''}",
            *measured,
        ]
        return " | ".join(parts)

    # -- what leaves the page

    def shown_files(self) -> list[tuple[int, str]]:
        """The instances behind the cloud on show, for the file list a Toolkit loader takes."""
        if self._availability is None:
            return []
        kind, key, joined = self._scope_key()
        files = []
        for data in self._view_wells(joined):
            origin = data.origin.rows
            for index in range(data.n_instances):
                if not self._in_scope(data, index, kind, key):
                    continue
                for member in data.members[index]:
                    files.append(
                        (int(origin["fault_class"].iloc[member]), str(origin["file"].iloc[member]))
                    )
        return files

    def shown_source(self) -> str:
        """Where the file list came from, for its provenance."""
        return f"the Dispersions page | {self.x} × {self.y} | over {self._scope_name()}" + (
            " | joined bars" if self.joined else ""
        )

    def wait_cursor(self):
        """The wait cursor while the plot is rebuilt, for callers that redraw a large cloud."""
        QApplication.setOverrideCursor(QCursor(Qt.CursorShape.WaitCursor))
        return QApplication.restoreOverrideCursor
