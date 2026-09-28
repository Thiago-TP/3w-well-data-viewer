"""The main window: the pages, what they share, and the windows they open.

The viewer is several pages over one catalogue of the real instances. The
timelines page groups them by well and lays them out in time, the availability
page groups them by fault class or by well and says what their sensors
recorded; each page owns the controls that mean something only to it, and this
window owns what they share: the theme, the rescan, the help, the status bar the
pages write to, and the instance windows the pages open.
"""

from collections.abc import Callable
from functools import partial
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QTabWidget,
    QToolBar,
)

from overlap_viewer.backend import theme
from overlap_viewer.backend.config import DEFAULT_COLUMNS, DEFAULT_GAP_HOURS
from overlap_viewer.backend.dataset import DatasetInfo, ScanCancelled, WellData, split_wells
from overlap_viewer.backend.export import write_file_list
from overlap_viewer.backend.model_outputs import ModelOutputs
from overlap_viewer.frontend import styling
from overlap_viewer.frontend.availability_page import AvailabilityPage
from overlap_viewer.frontend.dispersion_page import DispersionPage
from overlap_viewer.frontend.faults_page import FaultsPage
from overlap_viewer.frontend.features_page import FeaturesPage
from overlap_viewer.frontend.help import HelpWindow, real_instance_counts
from overlap_viewer.frontend.loading import FrameCache, catalogue_with_progress
from overlap_viewer.frontend.map_page import MapPage
from overlap_viewer.frontend.overview import ElidedLabel, TimelinesPage
from overlap_viewer.frontend.passes import Passes

# Which tab of the help answers the questions a page raises.
HELP_TABS = {
    TimelinesPage: "Fault classes",
    AvailabilityPage: "Data availability",
    FaultsPage: "Fault classes",
    FeaturesPage: "Variables",
    MapPage: "Instances map",
    DispersionPage: "Dispersions",
}


class MainWindow(QMainWindow):
    """The pages side by side as tabs, under the toolbar they share, over the status bar they share.

    ``progress``, when given, is told what the window is doing while it is
    built (the page being made, then the page being laid out), for the bar of
    the start-up: building the pages over the whole catalogue is most of a
    launch, and it happens before anything is on screen.
    """

    PAGE_TITLES = ("Timelines", "Availability", "Faults", "Features", "Instances", "Dispersions")
    PAGE_TIPS = (
        "Every real instance of every well, laid out in time",
        "What the sensors recorded, per fault class, per well, or instance by instance",
        "Every real instance of one fault, from every well, drawn over the others",
        "One sensor, a section per fault class: what it reads under each event",
        (
            "Every real instance as one point, placed by what its sensors amount to: clusters, "
            "typicality, and the labels a one-class model disagrees with"
        ),
        (
            "Two sensors against each other over every instance, one class or one well: every "
            "sample a dot, the density behind, the measurements alone on request"
        ),
    )

    def __init__(
        self,
        info: DatasetInfo,
        catalogue,
        gap_hours: float = DEFAULT_GAP_HOURS,
        columns: int = DEFAULT_COLUMNS,
        frames: FrameCache | None = None,
        theme_mode: str = "system",
        progress: Callable[[str], None] | None = None,
        parent=None,
    ):
        super().__init__(parent)
        report = progress or (lambda text: None)
        self.info = info
        self._frames = frames or FrameCache()
        # The passes over the data, read once and shared: a page that asks for
        # one another page has paid for gets it at once.
        self._passes = Passes(info, self._frames)
        self._windows: list[QMainWindow] = []
        self._help: HelpWindow | None = None
        self._theme_mode = theme_mode
        self.setWindowTitle(f"3W Real Instances Viewer | {info.raw_dir}")

        self._build_toolbar()
        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)
        report("Building the Timelines page…")
        self.timelines = TimelinesPage(
            info, gap_hours=gap_hours, columns=columns, passes=self._passes
        )
        report("Building the Availability page…")
        self.availability = AvailabilityPage(info, passes=self._passes)
        report("Building the Faults page…")
        self.faults = FaultsPage(info, self._frames, passes=self._passes)
        report("Building the Features page…")
        self.features = FeaturesPage(info, self._frames, passes=self._passes)
        report("Building the Instances page…")
        self.map = MapPage(info, passes=self._passes)
        report("Building the Dispersions page…")
        self.dispersion = DispersionPage(info, passes=self._passes)
        # A tab's tooltip is not a widget's, so it is bounded here rather than
        # by the filter ``styling.install_tooltips`` puts on the application.
        for index, (title, page, tip) in enumerate(
            zip(self.PAGE_TITLES, self.pages, self.PAGE_TIPS)
        ):
            self._tabs.addTab(page, title)
            self._tabs.setTabToolTip(index, styling.bounded_tooltip(tip))
        self._tabs.currentChanged.connect(self._on_page_changed)
        self.setCentralWidget(self._tabs)
        self._catalogue = None
        self._wells: list[WellData] = []
        # Pages a theme switch left to be laid out when next shown, and what
        # the Instances map last computed, to hand to a page laid out late.
        self._stale: set = set()
        self._map_results = None

        self._status = ElidedLabel(self.timelines.hint())
        self.statusBar().addWidget(self._status, 1)
        # The count of what is on show sits at the right end of the status bar, where
        # it does not crowd the toolbar's controls off a window of ordinary width.
        self._dataset_label = QLabel()
        self.statusBar().addPermanentWidget(self._dataset_label)
        for page in self.pages:
            page.status.connect(partial(self._on_page_status, page))
            page.summary_changed.connect(self._refresh_summary)
        self.timelines.open_requested.connect(self.open_instances)
        self.availability.open_requested.connect(self._open_bar)
        self.map.open_requested.connect(self.open_instances)
        self.dispersion.open_requested.connect(self.open_instances)
        self.faults.open_requested.connect(self._open_on_feature)
        self.features.open_requested.connect(self._open_on_feature)
        self.map.results_changed.connect(self._on_map_results)

        self._restyle()
        self.set_catalogue(catalogue, progress=report)

        # A ``system`` mode has to keep up with the desktop changing its mind.
        # Queued, because installing a theme sets the color scheme itself and
        # would otherwise re-enter this window in the middle of a rebuild.
        QApplication.instance().styleHints().colorSchemeChanged.connect(
            self._on_system_scheme, Qt.ConnectionType.QueuedConnection
        )

    # -- construction

    @property
    def pages(self) -> tuple:
        return (
            self.timelines,
            self.availability,
            self.faults,
            self.features,
            self.map,
            self.dispersion,
        )

    def _on_map_results(self, results) -> None:
        """What the Instances map computed, handed to the pages that color and sort by it."""
        self._map_results = results
        self.timelines.set_map_results(results)
        self.faults.set_map_results(results)
        self.features.set_map_results(results)

    def set_model_outputs(self, outputs: ModelOutputs | None) -> None:
        """Take a set of model outputs (or none) and hand its agreements to every page."""
        results = self._passes.set_model_outputs(outputs)
        for page in (self.timelines, self.faults, self.features, self.map):
            page.set_model_results(results)
        for window in list(self._windows):
            window.set_model_results(results)
        if results is None:
            self._status.setText("No model outputs loaded.")
        else:
            scored = len(results.agreements)
            self._status.setText(
                f"{results.outputs.describe()} | {scored} of the {len(self._catalogue)} real "
                "instances of this catalogue scored"
            )

    def _load_model_outputs(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Open a folder of model outputs (model.json beside <class>/<instance>.parquet)"
        )
        if not folder:
            return
        try:
            outputs = ModelOutputs.load(Path(folder))
        except (ValueError, OSError) as error:
            QMessageBox.critical(self, "Could not load the model outputs", str(error))
            return
        self.set_model_outputs(outputs)

    def _build_toolbar(self) -> None:
        bar = QToolBar("Viewer")
        bar.setMovable(False)
        self.addToolBar(bar)

        bar.addWidget(QLabel(" Theme "))
        self._theme = QComboBox()
        self._theme.addItems([mode.capitalize() for mode in theme.MODES])
        self._theme.setCurrentIndex(theme.MODES.index(self._theme_mode))
        self._theme.setToolTip(
            "Light or dark for both the windows and the plots inside them; System follows the "
            "desktop. The choice is remembered."
        )
        self._theme.currentIndexChanged.connect(
            lambda index: self.set_theme_mode(theme.MODES[index])
        )
        bar.addWidget(self._theme)

        bar.addSeparator()
        reset = QAction("Reset views", self)
        reset.setShortcut("Ctrl+R")
        reset.setToolTip("Show every timeline whole again (Ctrl+R)")
        reset.triggered.connect(self.reset_views)
        bar.addAction(reset)
        rescan = QAction("Rescan dataset", self)
        rescan.setToolTip("Read every instance again, ignoring the cached catalogue")
        rescan.triggered.connect(self._rescan)
        bar.addAction(rescan)
        export = QAction("Export file list…", self)
        export.setToolTip(
            "Write the instances the current page has on show (the wells filtered, the instances "
            "ticked, the bars of a joined view) as the JSON of a 3W Toolkit ParquetDatasetConfig "
            "with split='list', which the Toolkit loads with "
            "ParquetDatasetConfig(**json.load(open(path))); its provenance is written beside it."
        )
        export.triggered.connect(self._export_file_list)
        bar.addAction(export)
        load_model = QAction("Load model outputs…", self)
        load_model.setToolTip(
            "Open a folder of model outputs (model.json beside one <class>/<instance>.parquet per "
            "instance scored, with a timestamp index and a label column; see the help) and draw "
            "them onto the data: a band under the class band of every instance window, an "
            "agreement figure per instance that colors the Timelines and the Instances map and "
            "sorts the instance lists, and the model's labels as a shading of the Faults and "
            "Features pages. examples/model_outputs holds one such folder, with its provenance."
        )
        load_model.triggered.connect(self._load_model_outputs)
        bar.addAction(load_model)
        help_action = QAction("Help", self)
        help_action.setShortcut("F1")
        help_action.setToolTip("What every fault class, variable and page means (F1)")
        help_action.triggered.connect(self.show_help)
        bar.addAction(help_action)

    # -- data

    def set_catalogue(
        self,
        catalogue,
        progress: Callable[[str], None] | None = None,
        lazy: bool = False,
    ) -> None:
        """Take a new catalogue: split it into wells once, and every page rebuilds from them.

        ``progress`` is told which page is being laid out, for the bar of the
        start-up. ``lazy`` lays out the page on show alone and leaves the
        others for when they are next shown, which is what a theme switch
        wants: the same catalogue in new colors, and five hidden pages that
        need not be drawn now.

        The very same catalogue again is a theme switch, not new data: the
        wells split from it and every pass read over it still describe it, and
        dropping them would make a change of color cost the minutes those
        passes took. They are kept, and the pages are handed the wells they
        already hold, so that a page can tell the two cases apart by identity.
        """
        same = catalogue is self._catalogue and bool(self._wells)
        if not same:
            self._map_results = None  # computed on the old catalogue
            self._discard_help()  # its instance counts describe the old catalogue
            self._wells = split_wells(catalogue)
            self._passes.set_wells(self._wells)
        self._catalogue = catalogue
        current = self._tabs.currentWidget()
        self._stale = set()
        for title, page in zip(self.PAGE_TITLES, self.pages):
            if lazy and page is not current:
                self._stale.add(page)
                continue
            if progress is not None:
                progress(f"Laying out the {title} page…")
            self._lay_out(page)
        self._refresh_summary()

    def _lay_out(self, page) -> None:
        """Lay one page out over the catalogue, and hand it what the others hold for it."""
        page.set_catalogue(self._catalogue, self._wells)
        if self._passes.model is not None and hasattr(page, "set_model_results"):
            page.set_model_results(self._passes.model)
        if self._map_results is not None and hasattr(page, "set_map_results"):
            page.set_map_results(self._map_results)

    def _discard_help(self) -> None:
        """Throw the help window away, so that the next F1 builds it over what is true now."""
        if self._help is not None:
            self._help.close()
            self._help.deleteLater()
            self._help = None

    def _refresh_summary(self, *args) -> None:
        self._dataset_label.setText(self._tabs.currentWidget().summary())

    def _on_page_status(self, page, text: str) -> None:
        """Show what a page says, if it is the page on show: a hidden page rebuilding stays quiet."""
        if self._tabs.currentWidget() is page:
            self._status.setText(text)

    def _on_page_changed(self, index: int) -> None:
        page = self._tabs.widget(index)
        if page in self._stale:  # a theme switch left it for now
            self._stale.discard(page)
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                self._lay_out(page)
            finally:
                QApplication.restoreOverrideCursor()
        self._status.setText(page.hint())
        self._refresh_summary()

    # -- appearance

    def _restyle(self) -> None:
        """Take the colors of the theme now in force, for the chrome this window owns."""
        self._dataset_label.setStyleSheet(f"color: {theme.current().muted};")

    def set_theme_mode(self, mode: str) -> None:
        """Switch to ``light``, ``dark`` or ``system``, and repaint every open window.

        Most plots cannot be recolored in place: pyqtgraph reads its background
        and its foreground when an item is built, so the pages are laid out
        again from the same catalogue, the page on show now and the others
        when they are next shown. Laying every page out at once took seven
        seconds on 3W 2.0.0, five of them for pages nobody was looking at. The
        catalogue handed back is the very same object, which is what tells the
        pages and the passes that no data has changed and nothing read over it
        need be read again.
        """
        self._theme_mode = mode
        styling.save_mode(mode)
        if self._theme.currentIndex() != theme.MODES.index(mode):  # a mode set in code
            self._theme.blockSignals(True)
            self._theme.setCurrentIndex(theme.MODES.index(mode))
            self._theme.blockSignals(False)
        before = theme.current()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            if styling.apply(mode) is before:
                return  # e.g. System on a light desktop, chosen while already light
            self._restyle()
            self._discard_help()  # its swatches carry the colors of the old theme
            for page in self.pages:
                page.apply_theme()
            for window in list(self._windows):
                window.apply_theme()
            self.set_catalogue(self._catalogue, lazy=True)
        finally:
            QApplication.restoreOverrideCursor()

    def _on_system_scheme(self, *args) -> None:
        """Follow the desktop switching between light and dark, while ``system`` is chosen."""
        if self._theme_mode == "system":
            self.set_theme_mode("system")

    # -- behaviour

    def reset_views(self) -> None:
        page = self._tabs.currentWidget()
        if hasattr(page, "reset_views"):
            page.reset_views()

    def show_help(self) -> None:
        """Open (or raise) the help window, on the tab that answers the current page's questions."""
        if self._help is None:
            self._help = HelpWindow(
                self.info, counts=real_instance_counts(self._catalogue), parent=self
            )
        self._help.show_tab(HELP_TABS.get(type(self._tabs.currentWidget()), "Fault classes"))

    def open_instances(self, data: WellData, index: int):
        """Open the time series of one bar of a timeline and of every bar it overlaps.

        Returns the window, or ``None`` when its files could not be read.
        """
        from overlap_viewer.frontend.instance_window import InstanceWindow

        try:
            window = InstanceWindow(data, index, self.info, self._frames, passes=self._passes)
        except Exception as error:  # noqa: BLE001 - one unreadable file must not take the app down
            QMessageBox.warning(
                self, "Could not open the instances", f"{type(error).__name__}: {error}"
            )
            return None
        window.destroyed.connect(
            lambda *_: self._windows.remove(window) if window in self._windows else None
        )
        self._windows.append(window)
        window.show()
        return window

    def _open_bar(self, well: int, bar: int, sensor, joined: bool) -> None:
        """Open, from the availability page, one bar of a well with one sensor drawn."""
        data = next((w for w in self._wells if w.well == well), None)
        if data is None:
            return
        self._open_on_feature(data.joined() if joined else data, bar, sensor)

    def _open_on_feature(self, data: WellData, index: int, sensor) -> None:
        """Open one bar with ``sensor`` drawn, or on the window's own default without one."""
        window = self.open_instances(data, index)
        if window is not None and sensor:
            window.select_features([sensor])

    def _export_file_list(self) -> None:
        """Write the instances the current page has on show as a Toolkit file list, where the user says."""
        page = self._tabs.currentWidget()
        files = page.shown_files() if hasattr(page, "shown_files") else []
        if not files:
            QMessageBox.information(
                self, "Export file list", "The current page has no instances on show to export."
            )
            return
        name = type(page).__name__.removesuffix("Page").lower()
        path, _filter = QFileDialog.getSaveFileName(
            self,
            "Export the instances on show as a 3W Toolkit file list",
            f"file_list_{name}.json",
            "JSON (*.json)",
        )
        if not path:
            return
        try:
            note = write_file_list(Path(path), self.info, files, page.shown_source())
        except OSError as error:
            QMessageBox.critical(self, "Export failed", f"{type(error).__name__}: {error}")
            return
        self._status.setText(
            f"{len(set(files))} files written to {path}, their provenance to {note.name} | load "
            "with ParquetDatasetConfig(**json.load(open(path)))"
        )

    def _rescan(self) -> None:
        try:
            catalogue = catalogue_with_progress(self.info, use_cache=False, parent=self)
        except ScanCancelled:
            return
        except Exception as error:  # noqa: BLE001 - report, keep the current catalogue
            QMessageBox.critical(self, "Rescan failed", f"{type(error).__name__}: {error}")
            return
        self.set_catalogue(catalogue)

    def closeEvent(self, event) -> None:
        for window in list(self._windows):
            window.close()
        super().closeEvent(event)
