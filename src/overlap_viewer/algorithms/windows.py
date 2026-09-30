"""The windows of a well: one sensor of its instances cut into windows of a fixed size. Numpy only.

A model of the 3W reads its series in windows of a fixed number of samples,
and what a window is labeled decides what it is trained on. The division here
is made in software, from the instance files themselves, on four rules (the
ones the ``3w_estudo`` division writes to disk and audits):

1. **Exact size.** Every window holds exactly ``size`` values.
2. **One label.** An instance is split into runs of constant label (normal
   operation, every fault's steady state, every transient and the unlabeled
   stretches are distinct labels), and every run is cut into consecutive
   windows of its own. No window passes from normal operation to a transient
   or a fault, so the label of a window is the label of every one of its
   samples.
3. **Zero padding.** When the end of a run does not fill a window, the last
   window of the run is completed with zeros at its end; ``n_valid`` says how
   many of its samples are real. A NaN among the real samples is a reading the
   file does not have.
4. **No overlap.** No instant appears in two windows of a well. The instances
   are walked in chronological order and each loses the samples an earlier
   one already covered: on 3W the first unlabeled hour of an instance usually
   repeats, sample by sample, the last hour of the one before it. The rule can
   be lifted (``drop_repeated=False``), and the windows of every instance are
   then cut from the instance whole.

What a window amounts to is told by the viewer's own descriptors
(``descriptors.describe``, the figures of the instance window's statistics
table and of the Timelines' descriptor coloring), taken over the real samples
of every window, and how well one of them tells event windows from normal ones
by the separation ``|AUC − 0.5| · 2``.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd

from overlap_viewer.algorithms.descriptors import FIELDS, describe

# The window sizes offered, in samples (seconds, on the 1 Hz grid of the 3W).
SIZES = (256, 512, 1024)
DEFAULT_SIZE = 512
# The code of an unlabeled sample among the label codes, and of a sample left
# out as a repetition: neither is a value the ``class`` column can take.
UNLABELED = -1.0
_DROPPED = -999.0


@dataclass(frozen=True)
class InstanceRef:
    """The instance a stretch of the series came from.

    ``position`` is its row in the well's own table (``WellData.rows``),
    which is what opens it.
    """

    position: int
    fault: int
    file: str
    title: str


def label_codes(labels: np.ndarray) -> np.ndarray:
    """The labels as codes a run can be found in: the value, ``UNLABELED`` for a missing one."""
    labels = np.asarray(labels, dtype=float)
    return np.where(np.isnan(labels), UNLABELED, labels)


def cut(
    labels: np.ndarray,
    size: int,
    keep: np.ndarray | None = None,
    bounds: Sequence[int] = (),
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Cut a series into windows of ``size`` samples, one label each.

    Parameters
    ----------
    labels : np.ndarray
        The ``class`` of every sample, NaN where unlabeled.
    size : int
        Samples per window.
    keep : np.ndarray of bool, optional
        ``False`` for a sample left out (repeated from an earlier instance);
        every sample is kept by default.
    bounds : sequence of int
        Positions where a new instance starts: a run never crosses one.

    Returns
    -------
    first, n_valid, code : np.ndarray
        Per window, the position of its first sample, how many of its samples
        are real (the rest is padding) and the label code of its run
        (``UNLABELED`` for an unlabeled one), in the order of the series.
    """
    if size < 1:
        raise ValueError("A window holds at least one sample")
    codes = label_codes(labels)
    n = len(codes)
    empty = (np.zeros(0, dtype=np.int64), np.zeros(0, dtype=np.int64), np.zeros(0))
    if n == 0:
        return empty
    key = codes if keep is None else np.where(np.asarray(keep, dtype=bool), codes, _DROPPED)
    border = np.zeros(n, dtype=bool)
    border[0] = True
    border[1:] = key[1:] != key[:-1]
    inner = np.asarray([b for b in bounds if 0 < b < n], dtype=np.int64)
    border[inner] = True
    starts = np.flatnonzero(border)
    ends = np.append(starts[1:], n)
    runs = key[starts] != _DROPPED
    starts, ends = starts[runs], ends[runs]
    if len(starts) == 0:
        return empty
    counts = -(-(ends - starts) // size)
    run_of = np.repeat(np.arange(len(starts)), counts)
    within = np.arange(int(counts.sum())) - np.repeat(np.cumsum(counts) - counts, counts)
    first = starts[run_of] + within * size
    n_valid = np.minimum(size, ends[run_of] - first)
    return first.astype(np.int64), n_valid.astype(np.int64), codes[first]


@dataclass
class Windows:
    """The windows of one sensor of a well, in chronological order.

    Attributes
    ----------
    size : int
        Samples per window.
    instance : np.ndarray
        Per window, the position of its instance in the well's table.
    number : np.ndarray
        Its index among the windows of its instance (0, 1, …).
    first : np.ndarray
        The position of its first sample inside its instance.
    start : np.ndarray
        The timestamp of its first sample (``datetime64[ns]``).
    label : np.ndarray
        Its one label, NaN for an unlabeled window.
    n_valid : np.ndarray
        How many of its samples are real; the rest is zero padding.
    nan_share : np.ndarray
        The share of its real samples the file holds no reading for.
    values : np.ndarray
        ``(windows, size)``: the readings, in the file's unit, zero past
        ``n_valid``.
    refs : list[InstanceRef]
        The instances of the well, by position.
    """

    size: int
    instance: np.ndarray
    number: np.ndarray
    first: np.ndarray
    start: np.ndarray
    label: np.ndarray
    n_valid: np.ndarray
    nan_share: np.ndarray
    values: np.ndarray
    refs: list[InstanceRef]

    def __len__(self) -> int:
        return len(self.instance)

    @property
    def codes(self) -> np.ndarray:
        """The label of every window as a code, ``UNLABELED`` for an unlabeled one."""
        return label_codes(self.label)

    @property
    def fault(self) -> np.ndarray:
        """The fault folder of every window's instance."""
        folders = np.array([ref.fault for ref in self.refs], dtype=np.int64)
        return folders[self.instance] if len(self.instance) else np.zeros(0, dtype=np.int64)

    def real(self, k: int) -> np.ndarray:
        """The real samples of window ``k``, padding left out."""
        return self.values[k, : int(self.n_valid[k])]

    def padded(self) -> np.ndarray:
        """Whether each window carries padding."""
        return self.n_valid < self.size


@dataclass
class WellSeries:
    """One sensor of every instance of a well, laid end to end in chronological order.

    Attributes
    ----------
    sensor : str
        The sensor read.
    values : np.ndarray
        Every reading, in the file's unit, NaN where the file has none.
    labels : np.ndarray
        The ``class`` of every sample, NaN where unlabeled.
    stamps : np.ndarray
        The timestamp of every sample (``datetime64[ns]``).
    offsets : np.ndarray
        ``(instances + 1,)``: where each instance's samples start, and the end.
    repeated : np.ndarray
        Per sample, whether an earlier instance of the well already covers
        its instant.
    refs : list[InstanceRef]
        The instances, in the order of ``offsets``.
    """

    sensor: str
    values: np.ndarray
    labels: np.ndarray
    stamps: np.ndarray
    offsets: np.ndarray
    repeated: np.ndarray
    refs: list[InstanceRef]

    @property
    def n_samples(self) -> int:
        return len(self.values)

    @property
    def n_repeated(self) -> int:
        return int(self.repeated.sum())

    def span(self, k: int) -> slice:
        """The samples of the ``k``-th instance read."""
        return slice(int(self.offsets[k]), int(self.offsets[k + 1]))

    def index_of(self, position: int) -> int:
        """Where the instance at ``position`` of the well's table sits among those read, or ``-1``."""
        for k, ref in enumerate(self.refs):
            if ref.position == position:
                return k
        return -1

    def windows(self, size: int, drop_repeated: bool = True) -> Windows:
        """The windows of ``size`` samples of the series, under the four rules of the module."""
        keep = ~self.repeated if drop_repeated else None
        first, n_valid, codes = cut(self.labels, size, keep, self.offsets[1:-1])
        n = len(first)
        which = np.searchsorted(self.offsets, first, side="right") - 1
        # Windows are cut in the order of the series, which is instance after
        # instance, so an instance's windows are consecutive.
        change = np.ones(n, dtype=bool)
        change[1:] = which[1:] != which[:-1]
        number = np.arange(n) - np.maximum.accumulate(np.where(change, np.arange(n), 0))
        if n:
            columns = np.arange(size)
            index = np.minimum(first[:, None] + columns[None, :], len(self.values) - 1)
            real = columns[None, :] < n_valid[:, None]
            values = np.where(real, self.values[index], 0.0)
            nan_share = (np.isnan(values) & real).sum(axis=1) / n_valid
        else:
            values = np.zeros((0, size))
            nan_share = np.zeros(0)
        positions = np.array([ref.position for ref in self.refs], dtype=np.int64)
        return Windows(
            size=int(size),
            instance=positions[which] if n else np.zeros(0, dtype=np.int64),
            number=number.astype(np.int64),
            first=(first - self.offsets[which]).astype(np.int64),
            start=self.stamps[first] if n else np.zeros(0, dtype="datetime64[ns]"),
            label=np.where(codes == UNLABELED, np.nan, codes),
            n_valid=n_valid,
            nan_share=nan_share.astype(float),
            values=values,
            refs=list(self.refs),
        )


class SeriesPass:
    """Reads one sensor of the instances of a well, one frame at a time, into a ``WellSeries``.

    Parameters
    ----------
    sensor : str
        The column read from every frame.
    """

    def __init__(self, sensor: str):
        self.sensor = sensor
        self._values: list[np.ndarray] = []
        self._labels: list[np.ndarray] = []
        self._stamps: list[np.ndarray] = []
        self._refs: list[InstanceRef] = []

    def add(self, frame: pd.DataFrame, ref: InstanceRef) -> None:
        """Take one instance: a timestamp-indexed frame holding the sensor and ``class``."""
        n = len(frame)
        if self.sensor in frame.columns:
            values = frame[self.sensor].to_numpy(dtype=float, na_value=np.nan)
        else:
            values = np.full(n, np.nan)
        if "class" in frame.columns:
            labels = frame["class"].to_numpy(dtype=float, na_value=np.nan)
        else:
            labels = np.full(n, np.nan)
        self._values.append(values)
        self._labels.append(labels)
        self._stamps.append(np.asarray(frame.index, dtype="datetime64[ns]"))
        self._refs.append(ref)

    def result(self) -> WellSeries:
        """The series, instances in chronological order, with the samples an earlier one covered."""
        order = sorted(
            range(len(self._refs)),
            key=lambda k: (
                self._stamps[k][0] if len(self._stamps[k]) else np.datetime64("NaT"),
                self._stamps[k][-1] if len(self._stamps[k]) else np.datetime64("NaT"),
                self._refs[k].position,
            ),
        )
        values = [self._values[k] for k in order]
        labels = [self._labels[k] for k in order]
        stamps = [self._stamps[k] for k in order]
        repeated = []
        covered = None  # the last instant an earlier instance holds
        for part in stamps:
            if covered is None or not len(part):
                repeated.append(np.zeros(len(part), dtype=bool))
            else:
                repeated.append(part <= covered)
            if len(part):
                covered = part[-1] if covered is None else max(covered, part[-1])
        lengths = [len(part) for part in values]
        offsets = np.concatenate(([0], np.cumsum(lengths))).astype(np.int64)

        def joined(parts, dtype):
            return np.concatenate(parts).astype(dtype) if parts else np.zeros(0, dtype=dtype)

        return WellSeries(
            sensor=self.sensor,
            values=joined(values, float),
            labels=joined(labels, float),
            stamps=joined(stamps, "datetime64[ns]"),
            offsets=offsets,
            repeated=joined(repeated, bool),
            refs=[self._refs[k] for k in order],
        )


# -- what every window amounts to

# The figures of ``Descriptors`` that are numbers (its Gaussianity verdict is a yes or no).
DESCRIBED = tuple(name for name in FIELDS if name != "gaussian")


def describe_windows(
    values: np.ndarray,
    n_valid: np.ndarray,
    scale: float = 1.0,
    progress: Callable[[int, int], bool] | None = None,
    chunk: int = 500,
) -> dict[str, np.ndarray] | None:
    """The descriptors of every window, over its real samples, as one array per figure.

    Every window is handed to ``descriptors.describe`` exactly as the
    statistics table hands it a sensor: its padding left out, its missing
    readings dropped, its readings in ``scale`` times the file's unit (the
    unit the traces are drawn in). ``progress`` is told ``(done, total)``
    every ``chunk`` windows; returning ``False`` stops the pass, and ``None``
    is returned.
    """
    n = len(n_valid)
    out = {name: np.full(n, np.nan) for name in DESCRIBED}
    for k in range(n):
        figures = describe(values[k, : int(n_valid[k])] * scale)
        for name in DESCRIBED:
            out[name][k] = float(getattr(figures, name))
        report = progress is not None and ((k + 1) % chunk == 0 or k + 1 == n)
        if report and not progress(k + 1, n):
            return None
    return out


def auc(scores: np.ndarray, positive: np.ndarray) -> float:
    """The area under the ROC curve of ``scores`` for telling ``positive`` apart, ties halved."""
    scores = np.asarray(scores, dtype=float)
    positive = np.asarray(positive, dtype=bool)
    n_pos, n_neg = int(positive.sum()), int((~positive).sum())
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    order = np.argsort(scores, kind="mergesort")
    ranks = np.empty(len(scores))
    ranks[order] = np.arange(1, len(scores) + 1)
    # Tied scores share the mean of their ranks.
    edges = np.flatnonzero(np.diff(scores[order]) != 0) + 1
    for a, b in zip(np.r_[0, edges], np.r_[edges, len(scores)]):
        if b - a > 1:
            ranks[order[a:b]] = 0.5 * (a + 1 + b)
    return float((ranks[positive].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))


def separation(scores: np.ndarray, event: np.ndarray) -> float:
    """How well one figure tells event windows from normal ones: ``|AUC − 0.5| · 2``, 0 to 1."""
    value = auc(scores, event)
    return abs(value - 0.5) * 2 if np.isfinite(value) else float("nan")
