"""The viewer, built offscreen, for the crops the deck shows of it.

The sections' scripts import this module only when they render crops, so that
their numbers and tables need no Qt at all. Importing it sets the environment
the offscreen platform needs, as ``scripts/screenshots.py`` does for the README
figures: the platform itself, the system fonts (the offscreen plugin ships no
font database, and every glyph would come out an empty box), and twice the
pixel density, so that a crop shrunk onto a slide keeps its text crisp.
"""

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_SCALE_FACTOR", "2")
if not os.environ.get("QT_QPA_FONTDIR"):
    for candidate in (r"C:\Windows\Fonts", "/usr/share/fonts", "/System/Library/Fonts"):
        if Path(candidate).is_dir():
            os.environ["QT_QPA_FONTDIR"] = candidate
            break

import numpy as np
import pandas as pd
import pyqtgraph as pg
from PySide6.QtCore import QRect
from PySide6.QtWidgets import QApplication

from well_data_viewer.app import build_window, parse_args
from well_data_viewer.backend.labels import padded_range
from well_data_viewer.frontend import styling


def settle(seconds: float) -> None:
    """Pump the event loop so deferred layouts, timers and reads finish."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        QApplication.processEvents()
        time.sleep(0.005)
    QApplication.processEvents()


def main_window(raw_dir: Path):
    """The viewer's main window on ``raw_dir``, in the light theme, laid out and hidden."""
    pg.setConfigOptions(antialias=True)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setOrganizationName(styling.SETTINGS[0])
    app.setApplicationName(styling.SETTINGS[1])
    app.setStyle("Fusion")
    # Arial, as the crops were first taken in (the offscreen platform's own
    # fallback is wider, and the bars' labels then drop their seconds).
    font = app.font()
    font.setFamily("Arial")
    app.setFont(font)
    # Not verbose: a slide shows what the viewer draws, and says the rest itself.
    window = build_window(
        parse_args(["--raw-dir", str(raw_dir), "--theme", "light", "--no-verbose"])
    )
    if window is None:
        raise SystemExit("could not build the viewer's window")
    window.resize(1600, 900)
    window.show()
    settle(2.0)
    return window


def save_stack(
    window,
    well: int,
    bar: int,
    sensors: list[str],
    span: tuple,
    size: tuple[int, int],
    path: Path,
    panel: bool = True,
    fit: bool = False,
) -> None:
    """Open one joined bar in an instance window and save its stack from the state band down.

    Parameters
    ----------
    window : MainWindow
        From ``main_window``.
    well, bar : int
        The well, and the position of the bar in the well's joined view.
    sensors : list[str]
        The sensors drawn, one plot each.
    span : (start, end)
        The stretch of time shown, anything ``numpy.datetime64`` reads.
    size : (width, height)
        The window's size in logical pixels; tall enough that the stack needs
        no scrolling, and the plots share what the bands leave.
    path : Path
        Where the PNG goes.
    panel : bool
        Whether the feature panel stays on the left of the plots.
    fit : bool
        Whether each plot's value axis fits the stretch shown rather than the
        whole recording, as the viewer draws it; readings outside the plausible
        range are left out of the fit.
    """
    data = next(w for w in window._wells if w.well == well).joined()
    instances = window.open_instances(data, bar, sensors)
    if instances is None:
        raise SystemExit(f"could not open the instance window of WELL-{well:05d}")
    if not panel:
        instances._show_features.setChecked(False)
    instances.resize(*size)
    settle(3.0)
    x = instances.timemap.to_x(np.array(span, dtype="datetime64[ns]"))
    instances._master.getViewBox().setXRange(float(x[0]), float(x[1]), padding=0)
    if fit:
        start, end = (pd.Timestamp(t) for t in span)
        for feature, master in instances._feature_masters.items():
            scale = instances.info.shown_scale(feature)
            low, high = instances.info.shown_range(feature)
            values = np.concatenate(
                [
                    frame.loc[start:end, feature].to_numpy(dtype=float) * scale
                    for frame in instances.frames
                    if feature in frame
                ]
            )
            values = values[np.isfinite(values) & (values >= low) & (values <= high)]
            if len(values):
                master.getViewBox().setYRange(*padded_range(values.min(), values.max()), padding=0)
    settle(1.5)
    # The crop starts at the state band, row 2 of the stack, under the empty
    # "shared" band and the block's header, which the width cuts short.
    stack = instances._layout_widget
    band = stack.ci.getItem(2, 0)
    top = stack.mapFromScene(band.mapRectToScene(band.boundingRect()).topLeft()).y()
    shot = instances._scroll.grab()
    skip = max(0, int((top - 2) * shot.devicePixelRatio()))
    shot.copy(QRect(0, skip, shot.width(), shot.height() - skip)).save(str(path))
    instances.close()
    print(f"  saved {path}", flush=True)
