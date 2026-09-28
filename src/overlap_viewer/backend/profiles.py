"""The profile of every sensor of every instance, and of every bar of the joined view. No Qt here.

One pass over the data, cached like the merged sensor figures, answers for
every sensor of every real instance (and of every bar the joined view draws,
read as the merged recording it is): how it was measured
(``algorithms.interpolation``: how many samples are measurements, how many
the historian filled in, how far apart the measurements are) and what it
amounts to (``algorithms.descriptors``: moments, quantiles, autocorrelation
time, signal-to-noise ratio, Gaussianity), the descriptors twice over: on
every sample of the 1 Hz grid, which is what a pipeline reads, and on the
measurements alone, which is what the process did. The two disagree exactly
where the straight lines the historian drew make the grid look smoother than
the process, and the viewer shows the grid's figures with that caveat. The
same pass checks the order of the pressures along each line
(``algorithms.consistency``), which also needs every sample, and records for
every pressure the others it contradicts.

The result is one long table, a row per (scope, instance or bar, sensor),
kept as parquet next to the catalogue and valid while the listing of the
files has the digest it was written under, the sensors are the ones it was
taken over and the rule is the version that wrote it. Every page that needs
a figure of an instance or a bar takes it from here, so the data is read once
for all of them.
"""

import contextlib
import hashlib
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from overlap_viewer.algorithms.consistency import partners_by_sensor, pressure_order_breaks
from overlap_viewer.algorithms.descriptors import ACF_MAX_LAG_S, FIELDS, Descriptors, describe
from overlap_viewer.algorithms.interpolation import (
    GENUINE,
    Sampling,
    format_spacing,
    sample_kinds,
    sampling_of,
)
from overlap_viewer.backend.config import cache_dir, plausible_range
from overlap_viewer.backend.dataset import (
    DatasetInfo,
    ScanCancelled,
    WellData,
    _listing,
    instance_title,
    is_sensor_column,
    list_real_instances,
    listing_digest,
    load_instance,
    merge_instances,
)
from overlap_viewer.backend.labels import column_as_float

ProgressCallback = Callable[[int, int, str], bool]

# Bumped whenever the rule or the columns change, so that an older cache is
# read again rather than trusted.
PROFILE_VERSION = 3

SCOPES = ("instance", "bar")
KEY_COLUMNS = ["scope", "well", "bar", "fault_class", "file", "sensor"]
SAMPLING_COLUMNS = [
    "n_total",
    "n_valid",
    "n_implausible",
    "n_genuine",
    "n_interpolated",
    "n_held",
    "spacing_s",
]
# The descriptors of the grid carry the field's own name; those of the
# measurements alone the same name with ``_g``.
GRID_COLUMNS = list(FIELDS)
GENUINE_COLUMNS = [f"{name}_g" for name in FIELDS]
# The samples in which a pressure reads out of order with another of its line,
# and those others, comma-separated (empty for a sensor in order).
ORDER_COLUMNS = ["n_out_of_order", "order_partners"]
PROFILE_COLUMNS = (
    KEY_COLUMNS
    + SAMPLING_COLUMNS
    + ORDER_COLUMNS
    + GRID_COLUMNS
    + GENUINE_COLUMNS
    + ["listing_digest", "version"]
)


@dataclass(frozen=True)
class DescriptorChoice:
    """One descriptor a page can color or sort by, and how to say its value.

    ``inflated`` marks the figures the historian's lines between
    measurements inflate when they are taken on the 1 Hz grid (the
    autocorrelation time and the signal-to-noise ratio), which is the caveat
    every surface that shows them on the grid carries.
    """

    name: str
    column: str
    seconds: bool = False  # a duration
    signed: bool = False  # worth a sign, like a skewness
    inflated: bool = False

    def format(self, value: float) -> str:
        """The value to two digits, a duration as one, the undefined as a dash."""
        if value is None or np.isnan(value):
            return "-"
        if np.isinf(value):
            return f"> {format_spacing(ACF_MAX_LAG_S)}" if self.seconds else "∞"
        if self.seconds:
            return format_spacing(value)
        if abs(value) >= 100:
            return f"{value:,.0f}"
        return f"{value:+.2f}" if self.signed else f"{value:.2f}"


# The descriptors offered as a bar coloring and as sort orders, in the order
# the boxes list them: Melo's characterisation of a variable first.
DESCRIPTOR_CHOICES = (
    DescriptorChoice("Autocorrelation time", "acf_half_s", seconds=True, inflated=True),
    DescriptorChoice("Signal-to-noise ratio", "snr", inflated=True),
    DescriptorChoice("Gaussianity slope", "gauss_slope"),
    DescriptorChoice("Skewness", "skew", signed=True),
    DescriptorChoice("Kurtosis", "kurtosis", signed=True),
)
# Which of the two sets of descriptors a box asks for. The first is the whole
# 1 Hz grid, which is named after what most of it is: on 3W 2.0.0 only 6 % of
# the samples of a live analog sensor were measured and the historian drew the
# rest, so "Interpolated" says what the figure was taken over better than
# "Grid", which sounds like a mere unit of time.
DESCRIPTOR_MODES = ("Interpolated", "Measurements")
GRID_CAVEAT = (
    "on the 1 Hz grid the straight lines the historian drew between measurements inflate the "
    "autocorrelation time and the signal-to-noise ratio; the measurements alone say what the "
    "process did"
)


def descriptor_column(choice: DescriptorChoice, measured: bool) -> str:
    """The table column of one descriptor: the grid's, or the measurements' (``_g``)."""
    return f"{choice.column}_g" if measured else choice.column


def _step_seconds(index) -> float:
    """The sampling step of a frame, in seconds: the median positive gap of its index."""
    if len(index) < 2:
        return 1.0
    deltas = np.diff(np.asarray(index, dtype="datetime64[ns]")).astype(np.int64)
    positive = deltas[deltas > 0]
    return float(np.median(positive)) / 1e9 if len(positive) else 1.0


def profile_series(
    values: np.ndarray, bounds: tuple[float, float], enumerated: bool, step_s: float
) -> tuple[Sampling, int, Descriptors, Descriptors]:
    """How one series was measured and what it amounts to, on the grid and on the measurements.

    Readings outside ``bounds`` are taken out first and counted: a gauge
    reporting 10¹² Pa would otherwise own every moment. An enumerated
    variable (a valve state) is not tested for interpolation (every reading
    of it counts as a measurement), since a valve held in one position for
    hours is a fact about the well, not a line the historian drew.
    """
    y = np.asarray(values, dtype=float).copy()
    valid = ~np.isnan(y)
    outside = valid & ((y < bounds[0]) | (y > bounds[1]))
    n_implausible = int(outside.sum())
    y[outside] = np.nan
    if enumerated:
        kinds = np.where(np.isnan(y), -1, GENUINE).astype(np.int8)
    else:
        kinds = sample_kinds(y)
    sampling = sampling_of(kinds, step_s)
    if enumerated:
        # A valve is not "measured every second": the spacing of its
        # measurements is not a figure this test can give.
        sampling = Sampling(sampling.n_valid, sampling.n_valid, 0, 0, np.nan)
    on_grid = describe(y, step_s)
    if enumerated or sampling.n_genuine == sampling.n_valid:
        on_measurements = on_grid
    else:
        genuine_step = sampling.spacing_s if np.isfinite(sampling.spacing_s) else step_s
        on_measurements = describe(y[kinds == GENUINE], genuine_step)
    return sampling, n_implausible, on_grid, on_measurements


def profile_frame(frame: pd.DataFrame, sensors: Sequence[str], info: DatasetInfo) -> list[dict]:
    """One row per sensor of one frame: an instance, or a merged recording."""
    step_s = _step_seconds(frame.index)
    present = {str(name) for name in frame.columns if is_sensor_column(str(name))}
    out_of_order = partners_by_sensor(pressure_order_breaks(frame))
    rows = []
    for sensor in sensors:
        n_total = len(frame)
        if sensor in present:
            values = column_as_float(frame, sensor)
        else:
            values = np.full(n_total, np.nan)
        sampling, n_implausible, on_grid, on_measurements = profile_series(
            values, plausible_range(info.unit(sensor)), info.is_enumerated(sensor), step_s
        )
        partners, broken = out_of_order.get(sensor, ([], None))
        row = {
            "sensor": sensor,
            "n_total": n_total,
            "n_valid": sampling.n_valid,
            "n_implausible": n_implausible,
            "n_genuine": sampling.n_genuine,
            "n_interpolated": sampling.n_interpolated,
            "n_held": sampling.n_held,
            "spacing_s": sampling.spacing_s,
            "n_out_of_order": 0 if broken is None else int(broken.sum()),
            "order_partners": ",".join(partners),
        }
        for name in FIELDS:
            row[name] = getattr(on_grid, name)
            row[f"{name}_g"] = getattr(on_measurements, name)
        rows.append(row)
    return rows


def scan_profiles(
    wells: list[WellData],
    sensors: Sequence[str],
    info: DatasetInfo,
    progress: ProgressCallback | None = None,
) -> pd.DataFrame:
    """Read every instance once and profile it, and every bar of the joined view as the recording it is.

    A bar of one instance takes that instance's profile as it stands; a bar
    joined from several is profiled from the merged frame
    (``dataset.merge_instances``), in which every instant appears once and
    what one window did not record another may have.

    Parameters
    ----------
    wells : list[WellData]
        The wells, instance by instance; their joined views are built here.
    sensors : sequence of str
        The sensors to profile, in this order.
    info : DatasetInfo
        For the units, the plausible ranges and the enumerated variables.
    progress : callable, optional
        Called as ``progress(done, total, title)`` with the count of instances
        gone through; return ``False`` to cancel, which raises ``ScanCancelled``.
    """
    total = sum(well.n_instances for well in wells)
    done = 0
    records: list[dict] = []
    for well in wells:
        origin, view = well.origin, well.joined()
        rows = origin.rows
        for bar, members in enumerate(view.members):
            frames = [load_instance(rows["path"].iloc[m]) for m in members]
            profiles = []
            for m, frame in zip(members, frames):
                profile = profile_frame(frame, sensors, info)
                profiles.append(profile)
                for row in profile:
                    records.append(
                        {
                            "scope": "instance",
                            "well": well.well,
                            "bar": -1,
                            "fault_class": int(rows["fault_class"].iloc[m]),
                            "file": str(rows["file"].iloc[m]),
                            **row,
                        }
                    )
            merged = (
                profiles[0]
                if len(frames) == 1
                else profile_frame(merge_instances(frames), sensors, info)
            )
            for row in merged:
                records.append(
                    {
                        "scope": "bar",
                        "well": well.well,
                        "bar": bar,
                        "fault_class": int(view.rows["fault_class"].iloc[bar]),
                        "file": "",
                        **row,
                    }
                )
            done += len(members)
            if progress is not None and not progress(
                done, total, instance_title(view.rows.iloc[bar])
            ):
                raise ScanCancelled()
    table = pd.DataFrame(records)
    for column in ("listing_digest", "version"):
        table[column] = ""
    return table[[c for c in PROFILE_COLUMNS if c in table.columns]]


def profiles_cache_path(raw_dir: Path) -> Path:
    """Cache file of the profiles of one dataset root, next to its catalogue."""
    digest = hashlib.sha1(str(Path(raw_dir).resolve()).encode("utf-8")).hexdigest()[:12]
    return cache_dir() / f"profiles_{digest}.parquet"


@dataclass
class Profiles:
    """The profile table with the lookups the pages need.

    Attributes
    ----------
    table : pd.DataFrame
        ``PROFILE_COLUMNS``, one row per (scope, instance or bar, sensor).
    sensors : list[str]
        The sensors profiled, in the order the matrices are laid out in.
    """

    table: pd.DataFrame
    sensors: list[str]
    _instances: dict[tuple[int, str], int] = field(default_factory=dict, repr=False)
    _bars: dict[tuple[int, int], int] = field(default_factory=dict, repr=False)
    _column: dict[str, int] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        self._column = {name: j for j, name in enumerate(self.sensors)}
        table = self.table
        # Every (instance or bar) owns one block of consecutive rows, one per
        # sensor in ``sensors`` order; the index kept is the block's first row.
        firsts = table.index[table["sensor"] == self.sensors[0]] if self.sensors else []
        for first in firsts:
            row = table.loc[first]
            if row["scope"] == "instance":
                self._instances[(int(row["fault_class"]), str(row["file"]))] = int(first)
            else:
                self._bars[(int(row["well"]), int(row["bar"]))] = int(first)

    def _block(self, key, joined: bool) -> int | None:
        return self._bars.get(key) if joined else self._instances.get(key)

    def row(self, key, sensor: str, joined: bool = False) -> pd.Series | None:
        """The profile of one sensor of one instance ``(fault_class, file)`` or bar ``(well, bar)``."""
        first = self._block(key, joined)
        j = self._column.get(sensor)
        if first is None or j is None:
            return None
        return self.table.iloc[first + j]

    def descriptor(self, key, sensor: str, column: str, joined: bool = False) -> float:
        """One descriptor column of one sensor of one instance or bar, NaN when nothing is known."""
        row = self.row(key, sensor, joined)
        if row is None or column not in row.index:
            return float("nan")
        return float(row[column])

    def sampling(self, key, sensor: str, joined: bool = False) -> Sampling | None:
        """How one sensor of one instance or bar was measured."""
        row = self.row(key, sensor, joined)
        if row is None:
            return None
        return Sampling(
            int(row["n_valid"]),
            int(row["n_genuine"]),
            int(row["n_interpolated"]),
            int(row["n_held"]),
            float(row["spacing_s"]),
        )

    def order_partners(self, key, sensor: str, joined: bool = False) -> list[str]:
        """The pressures one sensor of one instance or bar reads out of order with; empty if none."""
        row = self.row(key, sensor, joined)
        if row is None or "order_partners" not in row.index or not row["order_partners"]:
            return []
        return str(row["order_partners"]).split(",")

    def matrix(
        self, keys: Sequence, joined: bool, column: str, sensors: Sequence[str] | None = None
    ) -> np.ndarray:
        """One column of the table as a ``(len(keys), sensors)`` array, NaN where nothing is known.

        ``keys`` are ``(fault_class, file)`` pairs, or ``(well, bar)`` pairs
        for the bars of a joined view. The columns follow ``sensors`` when
        given (a sensor not profiled stays NaN) and this table's own
        sensors otherwise.
        """
        values = self.table[column].to_numpy(dtype=float)
        own = len(self.sensors)
        block = np.full((len(keys), own), np.nan)
        for i, key in enumerate(keys):
            first = self._block(key, joined)
            if first is not None:
                block[i] = values[first : first + own]
        if sensors is None:
            return block
        out = np.full((len(keys), len(sensors)), np.nan)
        for j, name in enumerate(sensors):
            k = self._column.get(name)
            if k is not None:
                out[:, j] = block[:, k]
        return out

    def scope(self, joined: bool) -> pd.DataFrame:
        """The rows of one scope: the instances, or the bars of the joined view."""
        return self.table[self.table["scope"] == ("bar" if joined else "instance")]


def load_profiles(
    info: DatasetInfo,
    wells: list[WellData],
    sensors: Sequence[str],
    use_cache: bool = True,
    progress: ProgressCallback | None = None,
    cache_only: bool = False,
) -> Profiles | None:
    """The profiles of every instance and every bar, from the cache when nothing has changed.

    Valid while the listing of the files (names, sizes, modification times)
    has the digest the cache was written under, the sensors are the ones it
    holds in that order, and the rule is the version that wrote it. Writing
    the cache is best effort, as for the catalogue. With ``cache_only`` the
    data is never read: a cache that is missing or out of date gives ``None``.
    """
    entries = list_real_instances(info.raw_dir, info.fault_classes)
    digest = listing_digest(_listing(entries))
    names = json.dumps(list(sensors), separators=(",", ":"))
    stamp = f"{PROFILE_VERSION}:{names}"
    path = profiles_cache_path(info.raw_dir)
    if use_cache and path.exists():
        # A corrupt cache is simply rebuilt, like the catalogue's.
        with contextlib.suppress(Exception):
            cached = pd.read_parquet(path)
            current = (
                len(cached)
                and set(PROFILE_COLUMNS) <= set(cached.columns)
                and (cached["listing_digest"] == digest).all()
                and (cached["version"] == stamp).all()
            )
            if current:
                return Profiles(cached.reset_index(drop=True), list(sensors))
    if cache_only:
        return None
    table = scan_profiles(wells, sensors, info, progress)
    table["listing_digest"] = digest
    table["version"] = stamp
    if use_cache:
        with contextlib.suppress(Exception):
            path.parent.mkdir(parents=True, exist_ok=True)
            table.to_parquet(path, index=False)
    return Profiles(table.reset_index(drop=True), list(sensors))
