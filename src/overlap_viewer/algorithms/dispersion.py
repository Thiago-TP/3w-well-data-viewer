"""Two sensors against each other over a scope: the point cloud, the density behind it, and what the historian's lines do to it. Numpy only.

Melo's exploratory methodology (doctoral thesis, section 4.2.5) reads the
relation between two variables off their scatter plot, and on 3W that plot
is where the historian's lines show themselves: the cloud of two series is
mostly the trajectories of two interpolations, straight segments between the
few instants that were measured: "spurious dynamics" that no pooled
coefficient betrays and every scatter plot does. So the view draws the cloud three ways: every
sample as a dot, the density of the samples behind the dots, and the
measurements alone, the readings the historian archived.

A scope (every real instance, one fault class or one well, as instances or
as the joined bars) is read once and kept for the session. Every instance contributes an even subsample of its rows, ``BUDGET``
rows in all, each row carrying every analog sensor, its label period, which
of its readings were measured and when it was, so that changing the pair of
sensors, the coloring, the label periods or the measurements filter costs
nothing. The density is a two-dimensional histogram of the same rows, an
unbiased if coarser estimate of the density of all of them.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from math import ceil

import numpy as np
import pandas as pd

from overlap_viewer.algorithms.interpolation import GENUINE, sample_kinds
from overlap_viewer.backend.labels import column_as_float

# Rows kept over a whole scope, spread evenly over its instances; and the
# most of them drawn as dots; the density draws them all.
BUDGET = 400_000
MAX_DOTS = 150_000
BINS = 120
# The label period of a sample, by code: what the experts said the well was
# doing at that instant.
PERIODS = ("normal", "transient", "steady", "unlabeled")
PERIOD_NAMES = {
    "normal": "normal operation",
    "transient": "transient",
    "steady": "steady state",
    "unlabeled": "unlabeled",
}
NORMAL, TRANSIENT, STEADY, UNLABELED = range(4)


@dataclass(frozen=True)
class InstanceRef:
    """The instance, or joined bar, a row of the cloud came from.

    ``position`` is the bar's position in the view it was read from (the
    well's instances, or its joined bars), which is what opens it.
    """

    well: int
    position: int
    fault: int
    file: str
    title: str
    start: pd.Timestamp


def period_codes(class_values: np.ndarray, offset: int) -> np.ndarray:
    """The label period of every sample from its ``class`` value: normal, transient, steady, unlabeled."""
    values = np.asarray(class_values, dtype=float)
    codes = np.full(len(values), UNLABELED, dtype=np.int8)
    known = ~np.isnan(values)
    codes[known & (values == 0)] = NORMAL
    codes[known & (values >= 1) & (values < offset)] = STEADY
    codes[known & (values > offset) & (values < 2 * offset)] = TRANSIENT
    return codes


@dataclass
class Pair:
    """Two sensors' co-valid rows of a cloud, after the filters: what the view draws."""

    x: np.ndarray
    y: np.ndarray
    rows: np.ndarray  # positions in the cloud
    n_candidates: int  # rows of the cloud before the filters

    @property
    def n(self) -> int:
        return len(self.rows)

    def dots(self, limit: int = MAX_DOTS) -> np.ndarray:
        """The positions (into ``x``, ``y``, ``rows``) of an even subsample of at most ``limit`` points."""
        if self.n <= limit:
            return np.arange(self.n)
        stride = ceil(self.n / limit)
        return np.arange(0, self.n, stride)

    def density(self, bins: int = BINS) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """A two-dimensional histogram of every row: ``counts[x_bin, y_bin]`` and the two edge arrays."""
        if self.n == 0:
            edges = np.linspace(0.0, 1.0, bins + 1)
            return np.zeros((bins, bins)), edges, edges
        x_range = _padded(self.x)
        y_range = _padded(self.y)
        counts, xedges, yedges = np.histogram2d(self.x, self.y, bins=bins, range=(x_range, y_range))
        return counts, xedges, yedges

    def pearson(self) -> float:
        """The Pearson coefficient of the rows drawn, NaN below two rows or for a constant sensor."""
        if self.n < 2 or self.x.std() == 0 or self.y.std() == 0:
            return float("nan")
        return float(np.corrcoef(self.x, self.y)[0, 1])


def _padded(values: np.ndarray) -> tuple[float, float]:
    """The range of a coordinate, a hair wider so that the extreme sample lands inside the last bin."""
    low, high = float(values.min()), float(values.max())
    if high <= low:
        pad = abs(low) * 1e-6 + 1e-9
        return (low - pad, high + pad)
    return (low, high)


@dataclass
class Cloud:
    """The rows read over a scope, every analog sensor at once.

    Attributes
    ----------
    values : np.ndarray
        ``(rows, sensors)`` readings, NaN where missing or implausible.
    genuine : np.ndarray
        ``(rows, sensors)``: whether the reading was measured rather than
        drawn by the historian.
    period, fault, well, instance, seconds : np.ndarray
        Per row: its label period code, the fault folder and the well of its
        instance, the position of its instance in ``instances``, and the
        seconds since that instance's first sample.
    n_samples : int
        How many rows the instances held before the subsample.
    """

    sensors: list[str]
    values: np.ndarray
    genuine: np.ndarray
    period: np.ndarray
    fault: np.ndarray
    well: np.ndarray
    instance: np.ndarray
    seconds: np.ndarray
    instances: list[InstanceRef]
    n_samples: int

    @property
    def n(self) -> int:
        return len(self.period)

    @property
    def n_instances(self) -> int:
        return len(self.instances)

    @property
    def stride(self) -> float:
        """One row kept in how many, over the scope."""
        return self.n_samples / self.n if self.n else float("nan")

    def pair(
        self,
        x: str,
        y: str,
        periods: Sequence[int] | None = None,
        genuine_only: bool = False,
        scales: tuple[float, float] = (1.0, 1.0),
    ) -> Pair:
        """The co-valid rows of two sensors, in the label periods asked for, measured on both if asked.

        ``scales`` multiplies the readings of ``x`` and ``y``: the factors that
        take each sensor to the unit it is shown in (a pressure to MPa).
        """
        i, j = self.sensors.index(x), self.sensors.index(y)
        xs = self.values[:, i].astype(float) * scales[0]
        ys = self.values[:, j].astype(float) * scales[1]
        keep = np.isfinite(xs) & np.isfinite(ys)
        if periods is not None:
            keep &= np.isin(self.period, list(periods))
        if genuine_only:
            keep &= self.genuine[:, i] & self.genuine[:, j]
        rows = np.flatnonzero(keep)
        return Pair(xs[rows], ys[rows], rows, self.n)

    def timestamp(self, row: int) -> pd.Timestamp:
        """When one row was recorded."""
        ref = self.instances[int(self.instance[row])]
        return ref.start + pd.Timedelta(seconds=float(self.seconds[row]))

    def ref(self, row: int) -> InstanceRef:
        return self.instances[int(self.instance[row])]


class DispersionPass:
    """Reads the instances of a scope into a ``Cloud``: an even subsample of every one, all sensors at once."""

    def __init__(
        self,
        sensors: Sequence[str],
        bounds: Sequence[tuple[float, float]],
        n_instances: int,
        budget: int = BUDGET,
        transient_offset: int = 100,
    ):
        self.sensors = list(sensors)
        self.bounds = list(bounds)
        self.transient_offset = int(transient_offset)
        self.per_instance = max(budget // max(int(n_instances), 1), 50)
        self._values: list[np.ndarray] = []
        self._genuine: list[np.ndarray] = []
        self._period: list[np.ndarray] = []
        self._seconds: list[np.ndarray] = []
        self._instances: list[InstanceRef] = []
        self.n_samples = 0

    def add(self, frame: pd.DataFrame, ref: InstanceRef) -> None:
        """Take one instance, or one merged recording."""
        n, s = len(frame), len(self.sensors)
        raw = np.full((n, s), np.nan)
        genuine = np.zeros((n, s), dtype=bool)
        for j, name in enumerate(self.sensors):
            if name not in frame.columns:
                continue
            values = frame[name].to_numpy(dtype=float)
            low, high = self.bounds[j]
            values = np.where((values < low) | (values > high), np.nan, values)
            raw[:, j] = values
            genuine[:, j] = sample_kinds(values) == GENUINE
        period = period_codes(column_as_float(frame, "class"), self.transient_offset)
        if n:
            index = frame.index
            seconds = (index - index[0]).total_seconds().to_numpy(dtype=float)
        else:
            seconds = np.zeros(0)
        stride = max(1, ceil(n / self.per_instance))
        take = np.arange(0, n, stride)
        self._values.append(raw[take].astype(np.float32))
        self._genuine.append(genuine[take])
        self._period.append(period[take])
        self._seconds.append(seconds[take])
        self._instances.append(ref)
        self.n_samples += n

    def result(self) -> Cloud:
        s = len(self.sensors)
        counts = [len(p) for p in self._period]
        instance = np.repeat(np.arange(len(counts), dtype=np.int32), counts)
        fault = np.repeat(np.array([r.fault for r in self._instances], dtype=np.int16), counts)
        well = np.repeat(np.array([r.well for r in self._instances], dtype=np.int16), counts)
        return Cloud(
            self.sensors,
            np.vstack(self._values) if self._values else np.zeros((0, s), dtype=np.float32),
            np.vstack(self._genuine) if self._genuine else np.zeros((0, s), dtype=bool),
            np.concatenate(self._period) if self._period else np.zeros(0, dtype=np.int8),
            fault,
            well,
            instance,
            np.concatenate(self._seconds) if self._seconds else np.zeros(0),
            list(self._instances),
            self.n_samples,
        )


def bin_of(edges: np.ndarray, value: float) -> int:
    """Which bin of a histogram axis a coordinate falls in, ``-1`` outside."""
    if not np.isfinite(value) or value < edges[0] or value > edges[-1]:
        return -1
    k = int(np.searchsorted(edges, value, side="right") - 1)
    return min(max(k, 0), len(edges) - 2)
