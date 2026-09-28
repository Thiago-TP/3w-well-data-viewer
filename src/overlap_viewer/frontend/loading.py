"""Loading with feedback: the start-up and the passes behind progress dialogs, instances behind a cache."""

from collections import OrderedDict
from collections.abc import Callable
from pathlib import Path

import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QProgressDialog, QWidget

from overlap_viewer.backend.config import FRAME_CACHE_ROWS
from overlap_viewer.backend.dataset import (
    DatasetInfo,
    JoinedStats,
    PairCounts,
    WellData,
    load_catalogue,
    load_instance,
    load_joined_stats,
    load_pair_counts,
)
from overlap_viewer.backend.profiles import Profiles, load_profiles


class FrameCache:
    """Recently loaded instances, kept while they fit in ``max_rows`` samples.

    Neighbouring instances of a well are usually clicked one after the other,
    and the same file then belongs to several groups; reading a parquet file
    is quick, but not free for the 700,000-sample recordings of some wells.
    """

    def __init__(self, max_rows: int = FRAME_CACHE_ROWS):
        self._max_rows = max_rows
        self._frames: OrderedDict[Path, pd.DataFrame] = OrderedDict()
        self._rows = 0

    def get(self, path: Path) -> pd.DataFrame:
        path = Path(path)
        if path in self._frames:
            self._frames.move_to_end(path)
            return self._frames[path]
        frame = load_instance(path)
        self._frames[path] = frame
        self._rows += len(frame)
        while self._rows > self._max_rows and len(self._frames) > 1:
            _, evicted = self._frames.popitem(last=False)
            self._rows -= len(evicted)
        return frame

    def read(self, path: Path) -> pd.DataFrame:
        """An instance from the cache if it is there, else from its file without keeping it.

        What a stitched well reads its hundreds of instances with: kept, they
        would push every other window's instances out of the cache and hold the
        well twice in memory, once as files and once stitched.
        """
        path = Path(path)
        if path in self._frames:
            return self._frames[path]
        return load_instance(path)


def progress_dialog(text: str, parent: QWidget | None):
    """A cancellable progress dialog and the callback that drives it, for any pass over the files.

    The callback takes ``(done, total, name)`` and returns ``False`` once the
    user has cancelled; the caller closes the dialog when it is through.
    """
    return _progress_dialog(text, parent)


def _progress_dialog(text: str, parent: QWidget | None):
    """A cancellable progress dialog and the callback that drives it, for a scan of the files."""
    dialog = QProgressDialog(text, "Cancel", 0, 100, parent)
    dialog.setWindowTitle("3W Real Instances Viewer")
    dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
    dialog.setMinimumDuration(400)
    dialog.setMinimumWidth(420)
    dialog.setAutoClose(False)
    dialog.setAutoReset(False)

    def progress(done: int, total: int, name: str) -> bool:
        dialog.setMaximum(total)
        dialog.setValue(done)
        dialog.setLabelText(f"Reading {name}\n({done} of {total} instances)")
        QApplication.processEvents()
        return not dialog.wasCanceled()

    return dialog, progress


class LaunchProgress:
    """One bar over the whole start-up, from the command to the window.

    Building the main window is most of a launch: every page lays out every
    well and every instance of the catalogue before anything is shown, which
    on 3W 2.0.0 is several seconds of nothing on screen. This dialog reports
    each step, and takes over the catalogue scan of a first launch, so that
    one window says everything that happens between the command and the
    viewer. There is no Cancel: the alternative to launching is quitting.
    """

    def __init__(self, steps: int):
        self._steps = steps
        self._done = 0
        self._dialog = QProgressDialog("Starting the viewer…", "", 0, steps, None)
        self._dialog.setWindowTitle("3W Real Instances Viewer")
        self._dialog.setCancelButton(None)
        self._dialog.setMinimumDuration(0)
        self._dialog.setMinimumWidth(460)
        self._dialog.setAutoClose(False)
        self._dialog.setAutoReset(False)
        self._dialog.setValue(0)
        self._dialog.show()
        QApplication.processEvents()

    def step(self, text: str) -> None:
        """Announce the step about to start; the bar shows the steps done so far."""
        self._dialog.setMaximum(self._steps)
        self._dialog.setValue(min(self._done, self._steps))
        self._dialog.setLabelText(text)
        self._done += 1
        QApplication.processEvents()

    def scanning(self, done: int, total: int, name: str) -> bool:
        """The catalogue scan's callback: the bar follows the files while the scan lasts."""
        self._dialog.setMaximum(total)
        self._dialog.setValue(done)
        self._dialog.setLabelText(
            f"Scanning the instances of the dataset…\nReading {name}\n({done} of {total} instances)"
        )
        QApplication.processEvents()
        return True

    def close(self) -> None:
        self._dialog.close()
        self._dialog.deleteLater()


def catalogue_with_progress(
    info: DatasetInfo,
    use_cache: bool = True,
    parent: QWidget | None = None,
    progress: Callable[[int, int, str], bool] | None = None,
) -> pd.DataFrame:
    """Load the catalogue, showing a cancellable progress dialog if the scan takes long.

    Raises ``dataset.ScanCancelled`` when the user cancels. A catalogue served
    from the cache never shows the dialog. Given a ``progress`` callback, the
    scan reports to it instead of to a dialog of its own (the start-up passes
    its launch bar).
    """
    if progress is not None:
        return load_catalogue(info, use_cache=use_cache, progress=progress)
    dialog, progress = _progress_dialog("Scanning the instances of the dataset…", parent)
    try:
        return load_catalogue(info, use_cache=use_cache, progress=progress)
    finally:
        dialog.close()
        dialog.deleteLater()


def joined_stats_with_progress(
    info: DatasetInfo,
    wells: list[WellData],
    sensors: list[str],
    use_cache: bool = True,
    parent: QWidget | None = None,
) -> JoinedStats:
    """Load the merged figures of every well, behind a progress dialog when the data is read.

    Raises ``dataset.ScanCancelled`` when the user cancels; served from the
    cache, the dialog never shows.
    """
    dialog, progress = _progress_dialog(
        "Reading the overlapping instances as the recordings they were cut from…", parent
    )
    try:
        return load_joined_stats(info, wells, sensors, use_cache=use_cache, progress=progress)
    finally:
        dialog.close()
        dialog.deleteLater()


def pair_counts_with_progress(
    info: DatasetInfo,
    sensors: list[str],
    use_cache: bool = True,
    parent: QWidget | None = None,
) -> PairCounts:
    """Load the pair counts of every instance, behind a progress dialog when the data is read.

    Raises ``dataset.ScanCancelled`` when the user cancels; served from the
    cache, the dialog never shows.
    """
    dialog, progress = _progress_dialog(
        "Reading which sensors carry a reading at the same instant…", parent
    )
    try:
        return load_pair_counts(info, sensors, use_cache=use_cache, progress=progress)
    finally:
        dialog.close()
        dialog.deleteLater()


def profiles_with_progress(
    info: DatasetInfo,
    wells: list[WellData],
    sensors: list[str],
    use_cache: bool = True,
    parent: QWidget | None = None,
) -> Profiles:
    """Load the profile of every sensor of every instance and bar, behind a progress dialog.

    The pass reads every file in full (about a minute and a half for the
    1,119 instances of 3W 2.0.0) and is cached, so the dialog shows once.
    Raises ``dataset.ScanCancelled`` when the user cancels.
    """
    dialog, progress = _progress_dialog(
        "Reading every instance in full: which samples are measurements, and what each "
        "sensor amounts to…",
        parent,
    )
    try:
        return load_profiles(info, wells, sensors, use_cache=use_cache, progress=progress)
    finally:
        dialog.close()
        dialog.deleteLater()
