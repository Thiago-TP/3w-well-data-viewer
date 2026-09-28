"""Render the screenshots under ``docs/assets`` offscreen, one per page of the viewer.

Usage
-----
    uv run python scripts/screenshots.py docs/assets [--raw-dir PATH] [--only NAME ...]

Offscreen, so that no window ever reaches the desktop and the figures can be
taken again on any machine that has the dataset: the pages are laid out,
rendered and grabbed in a hidden application, and the result is what a real
window would have drawn. The offscreen platform plugin ships **no font
database of its own**, so ``QT_QPA_FONTDIR`` is pointed at the system fonts
below; without it the plugin reports zero font families and every glyph comes
out an empty box.

Each figure is framed on what it has to show rather than on one window size:
the availability matrix is eleven rows and no taller, the correlation matrix
holds the analog sensors alone, and the color key is grabbed as a widget of its
own. A few are set up before they are taken (a fault that oscillates, a sensor
that is not a flat valve opening, a pointer resting on a cell so that the status
line reads it) because the default state of a page is not always the state that
shows what the page is for; every such choice is commented where it is made.

The passes over the data are cached (``~/.cache/overlap-viewer`` or the platform
equivalent), so the first run is minutes and the next is seconds; the
correlation and dispersion scopes are read per session and always cost their
read.
"""

import argparse
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if not os.environ.get("QT_QPA_FONTDIR"):
    for candidate in (r"C:\Windows\Fonts", "/usr/share/fonts", "/System/Library/Fonts"):
        if Path(candidate).is_dir():
            os.environ["QT_QPA_FONTDIR"] = candidate
            break

import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication

from overlap_viewer.app import build_window, parse_args
from overlap_viewer.frontend import styling

PAGE = (1600, 900)  # wide enough that no page's toolbar falls behind the overflow chevron
SHORT = (1600, 545)  # the availability matrix is eleven rows and no taller
CORR = (1600, 680)  # the correlation matrix holds the analog sensors alone
WIDE = (1600, 1000)
TALL = (1500, 1000)
HELP = (1000, 800)


def hover_cell(page, row: int, column: int) -> None:
    """Put the pointer on one cell of a matrix, as a reader would, for the status line."""
    heatmap = page._heatmap
    heatmap._hover = (row, column)
    heatmap.hovered.emit(row, column)
    heatmap.update()


def settle(seconds: float = 0.8) -> None:
    """Pump the event loop so deferred layouts, timers and data passes finish."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        QApplication.processEvents()
        time.sleep(0.005)
    QApplication.processEvents()


class Shooter:
    def __init__(self, out: Path, only: set[str] | None):
        self.out = out
        self.only = only
        self.taken: list[str] = []

    def wants(self, name: str) -> bool:
        return self.only is None or name in self.only

    def save(self, widget, name: str, size=PAGE, wait: float = 1.2) -> None:
        widget.resize(*size)
        settle(wait)
        path = self.out / f"{name}.png"
        started = time.monotonic()
        ok = widget.grab().save(str(path))
        kb = path.stat().st_size // 1024 if path.exists() else 0
        print(
            f"  {'saved ' if ok else 'FAILED'} {name:18s} {size[0]}x{size[1]}  {kb:4d} KB"
            f"  ({time.monotonic() - started:.1f}s)",
            flush=True,
        )
        self.taken.append(name)


def pick_fault(page, wanted: str) -> None:
    box = page._fault
    index = box.findText(wanted, Qt.MatchFlag.MatchContains)
    if index >= 0:
        box.setCurrentIndex(index)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("out", type=Path)
    parser.add_argument("--raw-dir", default="../3W/dataset")
    parser.add_argument("--only", nargs="*", default=None)
    opts = parser.parse_args(argv)
    out = opts.out
    out.mkdir(parents=True, exist_ok=True)
    only = set(opts.only) if opts.only else None
    shooter = Shooter(out, only)

    pg.setConfigOptions(antialias=True)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setOrganizationName(styling.SETTINGS[0])
    app.setApplicationName(styling.SETTINGS[1])
    app.setStyle("Fusion")
    print(f"platform: {app.platformName()} | fonts: {len(QFontDatabase.families())}", flush=True)

    window = build_window(parse_args(["--raw-dir", str(opts.raw_dir), "--theme", "light"]))
    if window is None:
        print("could not build the window", file=sys.stderr)
        return 1
    window.resize(*PAGE)
    window.show()
    settle(1.5)

    tabs = window._tabs  # the main window offers no public accessor for its tabs

    def page(widget, name, size=PAGE, wait=1.5):
        if not shooter.wants(name):
            return False
        tabs.setCurrentWidget(widget)
        settle(wait)
        return True

    # -- Timelines -------------------------------------------------------------
    if page(window.timelines, "overview"):
        shooter.save(window, "overview")

    # -- The color key on its own, for the color-code note ---------------------
    if page(window.timelines, "color_key"):
        legend = window.timelines._legend
        shooter.save(legend, "color_key", (legend.width(), 186))

    # -- Availability, its three matrices --------------------------------------
    if page(window.availability, "availability", wait=2.5):
        hover_cell(window.availability, 8, 20)  # P-TPT under Hydrate in Production Line
        settle(0.5)
        shooter.save(window, "availability", SHORT)
    if page(window.availability, "pairs", wait=2.0):
        window.availability._matrix.setCurrentText("Sensor pairs")
        settle(4.0)
        hover_cell(window.availability, 19, 26)  # P-TPT × T-TPT, the best-covered pair
        settle(0.5)
        shooter.save(window, "pairs")
    if page(window.availability, "correlations", wait=1.0):
        window.availability._matrix.setCurrentText("Sensor correlations")
        settle(180.0)  # reads every instance the first time
        hover_cell(window.availability, 14, 17)  # T-JUS-CKP × T-TPT, the strongest common pair
        settle(0.5)
        shooter.save(window, "correlations", CORR)
    window.availability._matrix.setCurrentText("Sensor availability")

    # -- Faults ----------------------------------------------------------------
    if page(window.faults, "faults", wait=3.0):
        pick_fault(window.faults, "Severe Slugging")
        settle(6.0)
        shooter.save(window, "faults")
    if page(window.faults, "faults_spectra", wait=1.0):
        pick_fault(window.faults, "Severe Slugging")
        settle(3.0)
        window.faults.set_domain("spectrum")
        window.faults.set_layout("Overlaid")
        settle(8.0)
        shooter.save(window, "faults_spectra", WIDE)
        window.faults.set_domain("time")
        window.faults.set_layout("Small multiples")

    # -- Features --------------------------------------------------------------
    # Not the time-series grid: one instance recorded for days stretches the
    # shared hour axis and leaves every trace a sliver against the left edge.
    # The pooled distribution is the view the page was built for anyway, one
    # curve per fault class, in the class colors, over the one sensor.
    if page(window.features, "features", wait=6.0):
        window.features.set_domain("distribution")
        window.features.set_layout("Overall")
        settle(10.0)
        shooter.save(window, "features")

    # -- Instances map ---------------------------------------------------------
    if page(window.map, "instances", wait=8.0):
        shooter.save(window, "instances")

    # -- Dispersions -----------------------------------------------------------
    # A handful of readings at 80 MPa push the whole cloud into the bottom
    # fifth of an auto-ranged view, so the frame is set on the cloud itself.
    if page(window.dispersion, "dispersion", wait=1.0):
        settle(240.0)  # reads every instance of the scope the first time
        box = window.dispersion._plot_widget.getPlotItem().getViewBox()
        box.setRange(xRange=(-30, 125), yRange=(0, 29), padding=0.0)
        settle(1.0)
        shooter.save(window, "dispersion")

    # -- The help window -------------------------------------------------------
    if shooter.wants("help"):
        tabs.setCurrentWidget(window.timelines)
        settle(0.5)
        window.show_help()
        settle(1.5)
        shooter.save(window._help, "help", HELP)
        window._help.close()

    # -- An instance window, plain and with the signal views -------------------
    # WELL-00014 under severe slugging: overlapping windows, and a sensor that
    # oscillates, so the trace, its distribution and its spectrum all say
    # something. The default feature of a flow-instability well is a flat valve
    # opening, which declines every transform.
    if shooter.wants("instance_window") or shooter.wants("signal_views"):
        data = next((w for w in window._wells if w.well == 14), window._wells[0])
        slugging = data.rows["fault_class"].to_numpy() == 3
        index = next(
            (i for i in range(len(data.rows)) if slugging[i] and len(data.partners[i]) > 0),
            next((i for i in range(len(data.rows)) if len(data.partners[i]) > 0), 0),
        )
        instances = window.open_instances(data, index)
        if instances is None:
            print("could not open the instance window", file=sys.stderr)
        else:
            settle(3.0)
            if shooter.wants("instance_window"):
                # As it opens: on the analog sensors of the seabed.
                settle(1.0)
                shooter.save(instances, "instance_window")
            if shooter.wants("signal_views"):
                instances.select_features(["P-MON-CKP"])
                instances.set_views(["distribution", "spectrum"])
                settle(8.0)
                shooter.save(instances, "signal_views", TALL)
            instances.close()

    print(f"\n{len(shooter.taken)} written to {out}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
