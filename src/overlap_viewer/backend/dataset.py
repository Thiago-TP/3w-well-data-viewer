"""The dataset side of the viewer: metadata, instance catalogue, per-well overlaps.

``DatasetInfo`` reads what the 3W ``dataset.ini`` states about the data; the
catalogue lists every real instance with the facts the pages need (well, fault
folder, time span, reach, what each sensor recorded) and is cached on disk,
since gathering them means opening every file; ``WellData`` stacks the
instances of one well and finds which ones overlap. Only pandas, numpy and
pyarrow are needed here.
"""

import configparser
import contextlib
import hashlib
import json
import os
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from overlap_viewer.backend.config import (
    DEFAULT_FAULT_NAMES,
    DEFAULT_SENSOR_UNITS,
    DEFAULT_TRANSIENT_CAPABLE,
    DEFAULT_TRANSIENT_OFFSET,
    LABEL_COLUMNS,
    REACH_TINTS,
    REAL_PREFIX,
    cache_dir,
    display_unit,
    plausible_range,
)
from overlap_viewer.backend.labels import (
    Segment,
    column_as_float,
    coverage_counts,
    fault_reach,
    label_segments,
    labels_agree,
    segments_from_json,
    segments_to_json,
    sensor_stats_from_json,
    sensor_stats_to_json,
)

# Facts recorded per instance by ``scan_instances`` and kept in the cache.
# ``class_runs`` holds the runs of the ``class`` column (``labels.segments_to_json``),
# which is what deciding whether two overlapping instances may be joined needs;
# ``sensor_stats`` how many readings each sensor carries and their bounds
# (``availability.sensor_stats_to_json``), which is what the availability page
# is drawn from. A cache without a column listed here is scanned again.
CATALOGUE_COLUMNS = [
    "file",
    "fault_class",
    "well",
    "start",
    "end",
    "n_samples",
    "reach",
    "class_runs",
    "sensor_stats",
    "size",
    "mtime_ns",
]

ProgressCallback = Callable[[int, int, str], bool]


class ScanCancelled(Exception):
    """Raised when the progress callback asks the scan to stop."""


# -- dataset.ini ------------------------------------------------------------------


@dataclass(frozen=True)
class DatasetInfo:
    """What the dataset says about itself, with fallbacks for a missing ini file.

    Attributes
    ----------
    raw_dir : Path
        Root of the dataset (the folder holding ``0/`` .. ``9/``).
    fault_names : dict[int, str]
        Event description per fault-class label.
    transient_offset : int
        Offset between a fault label and its transient label.
    sensor_units : dict[str, str]
        Unit per variable, in dataset order (``-`` for enumerated states).
    sensor_descriptions : dict[str, str]
        Full description per variable, for tooltips.
    version : str
        Dataset version, empty when unknown.
    transient_faults : frozenset[int]
        The fault classes that have a transient period at all.
    """

    raw_dir: Path
    fault_names: dict[int, str] = field(default_factory=lambda: dict(DEFAULT_FAULT_NAMES))
    transient_offset: int = DEFAULT_TRANSIENT_OFFSET
    sensor_units: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_SENSOR_UNITS))
    sensor_descriptions: dict[str, str] = field(default_factory=dict)
    version: str = ""
    transient_faults: frozenset[int] = DEFAULT_TRANSIENT_CAPABLE

    @property
    def sensor_names(self) -> list[str]:
        """Every variable the dataset declares, in dataset order."""
        return list(self.sensor_units)

    @property
    def fault_classes(self) -> list[int]:
        """Fault-class folders present under ``raw_dir``, ascending."""
        return sorted(
            int(p.name) for p in self.raw_dir.iterdir() if p.is_dir() and p.name.isdigit()
        )

    def fault_name(self, fault_class: int) -> str:
        return self.fault_names.get(fault_class, f"Class {fault_class}")

    def has_transient(self, fault_class: int) -> bool:
        """Whether instances of this fault can carry a transient label at all."""
        return fault_class in self.transient_faults

    def unit(self, sensor: str) -> str:
        unit = self.sensor_units.get(sensor, "")
        return "" if unit == "-" else unit

    def shown_unit(self, sensor: str) -> str:
        """The unit the viewer shows a variable's readings in (MPa for a pressure)."""
        return display_unit(self.unit(sensor))[0]

    def shown_scale(self, sensor: str) -> float:
        """The factor that takes a reading from the file's unit to ``shown_unit``."""
        return display_unit(self.unit(sensor))[1]

    def shown_range(self, sensor: str) -> tuple[float, float]:
        """The plausible range of a variable, in ``shown_unit``."""
        low, high = plausible_range(self.unit(sensor))
        scale = self.shown_scale(sensor)
        return low * scale, high * scale

    def is_enumerated(self, sensor: str) -> bool:
        """Whether a variable takes a few discrete values (a valve state) rather than measuring.

        The dataset writes such a variable's "unit" as the list of values it
        can take, which ``load`` records as ``-``. A valve that holds one
        position for a whole recording is a fact about the well, not a frozen
        sensor, so the availability analysis treats these apart.
        """
        return self.sensor_units.get(sensor, "") == "-"

    @classmethod
    def load(cls, raw_dir: Path) -> "DatasetInfo":
        """Read ``dataset.ini`` under ``raw_dir``; fall back to the built-in constants."""
        raw_dir = Path(raw_dir)
        ini_path = raw_dir / "dataset.ini"
        if not ini_path.exists():
            return cls(raw_dir)
        parser = configparser.ConfigParser()
        parser.read(ini_path, encoding="utf-8")

        units, descriptions = dict(DEFAULT_SENSOR_UNITS), {}
        if "PARQUET_FILE_PROPERTIES" in parser:
            units, descriptions = {}, {}
            for key, desc in parser["PARQUET_FILE_PROPERTIES"].items():
                name = key.upper()
                if name in ("TIMESTAMP", *(c.upper() for c in LABEL_COLUMNS)):
                    continue
                match = re.search(r"\[([^\[\]]+)\]\s*$", desc)
                unit = match.group(1) if match else ""
                if "," in unit or " or " in unit:
                    unit = "-"
                units[name] = unit.replace("oC", "°C").replace("m3/s", "m³/s")
                descriptions[name] = re.sub(r"\s*\[[^\[\]]+\]\s*$", "", desc)

        names, offset = dict(DEFAULT_FAULT_NAMES), DEFAULT_TRANSIENT_OFFSET
        transient = DEFAULT_TRANSIENT_CAPABLE
        if "EVENTS" in parser:
            events = parser["EVENTS"]
            offset = events.getint("TRANSIENT_OFFSET", DEFAULT_TRANSIENT_OFFSET)
            listed = [n.strip() for n in events.get("NAMES", "").replace("\n", " ").split(",")]
            parsed, with_transient = {}, set()
            for event in filter(None, listed):
                if event in parser and "LABEL" in parser[event]:
                    label = parser[event].getint("LABEL")
                    parsed[label] = parser[event].get(
                        "DESCRIPTION", event.replace("_", " ").title()
                    )
                    if parser[event].getboolean("TRANSIENT", fallback=False):
                        with_transient.add(label)
            if parsed:
                names = parsed
                transient = frozenset(with_transient)

        version = parser["VERSION"].get("DATASET", "") if "VERSION" in parser else ""
        return cls(
            raw_dir,
            names,
            offset,
            units,
            descriptions,
            version,
            transient_faults=transient,
        )


# -- Instance discovery -------------------------------------------------------------


def parse_well_id(filename: str) -> int | None:
    """Well number of a real instance filename (``WELL-00026_...`` -> 26)."""
    match = re.match(r"WELL-(\d+)", Path(filename).stem, flags=re.IGNORECASE)
    return int(match.group(1)) if match else None


def well_label(well: int) -> str:
    """Filename-style name of a well (``WELL-00026``)."""
    return f"WELL-{well:05d}"


def filename_stamp(filename: str) -> pd.Timestamp | None:
    """Timestamp a real instance filename is keyed by, when it carries one.

    Real instances are named ``WELL-000{id}_{YYYYMMDDhhmmss}.parquet``; the
    stamp is the first timestamp of the recording and the literal piece of the
    filename a suspicious bar can be looked up by.
    """
    match = re.search(r"_(\d{14})", Path(filename).stem)
    if not match:
        return None
    stamp = pd.to_datetime(match.group(1), format="%Y%m%d%H%M%S", errors="coerce")
    return None if pd.isna(stamp) else stamp


def list_real_instances(raw_dir: Path, fault_classes: list[int]) -> list[tuple[int, Path]]:
    """Every real instance file, folder by folder, sorted by name within a folder."""
    entries = []
    for fault_class in fault_classes:
        class_dir = Path(raw_dir) / str(fault_class)
        if not class_dir.is_dir():
            continue
        for path in sorted(class_dir.glob("*.parquet")):
            if path.name.upper().startswith(REAL_PREFIX) and parse_well_id(path.name) is not None:
                entries.append((fault_class, path))
    return entries


def _listing(entries: list[tuple[int, Path]]) -> pd.DataFrame:
    """Name, folder, size and modification time of every entry, for cache validation."""
    rows = []
    for fault_class, path in entries:
        stat = path.stat()
        rows.append((path.name, fault_class, stat.st_size, stat.st_mtime_ns))
    return pd.DataFrame(rows, columns=["file", "fault_class", "size", "mtime_ns"])


def is_sensor_column(name: str) -> bool:
    """Whether a column of an instance file is a sensor: not a label, not the time index."""
    return (
        name not in LABEL_COLUMNS and name != "timestamp" and not name.startswith("__index_level_")
    )


def read_sensor_stats(parquet: pq.ParquetFile) -> dict[str, tuple[int, float, float]]:
    """How many readings each sensor of one file carries, and the smallest and largest.

    Read from the footer of the file, where parquet keeps a count of the
    missing values and the minimum and maximum of every column, so that the
    data itself is not read: the 3W files carry these figures. A column whose
    footer lacks them (a file written without statistics, or a float column
    whose statistics ignore its NaN) is read in full instead, which costs a
    little time and nothing else.

    Returns
    -------
    dict[str, (int, float, float)]
        Per sensor, in file order: readings, lowest, highest (NaN when none).
    """
    metadata = parquet.metadata
    names = [name for name in parquet.schema_arrow.names if is_sensor_column(name)]
    counts: dict[str, int] = dict.fromkeys(names, 0)
    lows: dict[str, float] = {}
    highs: dict[str, float] = {}
    unread: set[str] = set()
    for g in range(metadata.num_row_groups):
        group = metadata.row_group(g)
        for j in range(group.num_columns):
            column = group.column(j)
            name = column.path_in_schema
            if name not in counts or name in unread:
                continue
            stats = column.statistics
            if stats is None or not stats.has_null_count:
                unread.add(name)
                continue
            valid = group.num_rows - stats.null_count
            if valid > 0:
                if not stats.has_min_max:
                    unread.add(name)
                    continue
                # ``+ 0.0`` turns the ``-0.0`` parquet keeps for a column of zeros into ``0.0``.
                lows[name] = min(lows.get(name, np.inf), float(stats.min) + 0.0)
                highs[name] = max(highs.get(name, -np.inf), float(stats.max) + 0.0)
            counts[name] += valid
    if unread:
        frame = parquet.read(columns=sorted(unread)).to_pandas()
        for name in unread:
            values = column_as_float(frame, name)
            valid = values[~np.isnan(values)]
            counts[name] = len(valid)
            if len(valid):
                lows[name], highs[name] = float(valid.min()), float(valid.max())
            else:
                lows.pop(name, None)
                highs.pop(name, None)
    return {name: (counts[name], lows.get(name, np.nan), highs.get(name, np.nan)) for name in names}


def scan_instances(
    entries: list[tuple[int, Path]],
    transient_offset: int = DEFAULT_TRANSIENT_OFFSET,
    progress: ProgressCallback | None = None,
) -> pd.DataFrame:
    """Read the time span, length, reach, label runs and sensor figures of every instance.

    Only the ``class`` column (and the timestamp index) of each file is read;
    what every sensor recorded comes from the footer of the file
    (``read_sensor_stats``). The whole dataset takes some seconds.

    Parameters
    ----------
    entries : list[(int, Path)]
        Fault class and path of every file, from ``list_real_instances``.
    transient_offset : int
        Offset between a fault label and its transient label.
    progress : callable, optional
        Called as ``progress(done, total, filename)`` after each file; return
        ``False`` to cancel, which raises ``ScanCancelled``.

    Returns
    -------
    pd.DataFrame
        One row per instance with ``CATALOGUE_COLUMNS``.
    """
    rows = []
    for i, (fault_class, path) in enumerate(entries, start=1):
        with pq.ParquetFile(path) as parquet:
            labels = parquet.read(columns=["class"], use_pandas_metadata=True).to_pandas()
            sensors = read_sensor_stats(parquet)
        stat = path.stat()
        rows.append(
            {
                "file": path.name,
                "fault_class": fault_class,
                "well": parse_well_id(path.name),
                "start": labels.index.min(),
                "end": labels.index.max(),
                "n_samples": len(labels),
                "reach": fault_reach(column_as_float(labels, "class"), transient_offset),
                "class_runs": segments_to_json(label_segments(labels, "class")),
                "sensor_stats": sensor_stats_to_json(sensors),
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
            }
        )
        if progress is not None and not progress(i, len(entries), path.name):
            raise ScanCancelled()
    return pd.DataFrame(rows, columns=CATALOGUE_COLUMNS)


def cache_path(raw_dir: Path) -> Path:
    """Cache file of one dataset root, named by a digest of its resolved path."""
    digest = hashlib.sha1(str(Path(raw_dir).resolve()).encode("utf-8")).hexdigest()[:12]
    return cache_dir() / f"catalogue_{digest}.parquet"


def _cache_is_current(cached: pd.DataFrame, listing: pd.DataFrame) -> bool:
    """Whether the cached catalogue describes exactly the files listed now."""
    if len(cached) != len(listing) or not set(CATALOGUE_COLUMNS) <= set(cached.columns):
        return False
    keys = ["file", "fault_class"]
    merged = listing.merge(
        cached[keys + ["size", "mtime_ns"]], on=keys, how="left", suffixes=("", "_cached")
    )
    return bool(
        merged["size_cached"].notna().all()
        and (merged["size"] == merged["size_cached"]).all()
        and (merged["mtime_ns"] == merged["mtime_ns_cached"]).all()
    )


def load_catalogue(
    info: DatasetInfo,
    use_cache: bool = True,
    progress: ProgressCallback | None = None,
) -> pd.DataFrame:
    """The catalogue of every real instance, from the cache when it is current.

    The cache is keyed by the dataset path and validated against the current
    listing (names, sizes, modification times) with a handful of ``stat``
    calls, so a changed or added file triggers a fresh scan. Writing the cache
    is best effort: a read-only home directory only costs the speed-up.

    Parameters
    ----------
    info : DatasetInfo
        Dataset to catalogue.
    use_cache : bool
        Read and write the on-disk cache (default on).
    progress : callable, optional
        Progress callback of ``scan_instances``.

    Returns
    -------
    pd.DataFrame
        ``CATALOGUE_COLUMNS`` plus ``path`` (the file's location), ``stamp``
        (the filename timestamp, falling back to ``start``) and ``hours`` (the
        recording's duration), sorted by well and start.
    """
    entries = list_real_instances(info.raw_dir, info.fault_classes)
    if not entries:
        raise FileNotFoundError(f"No real ({REAL_PREFIX}*) instances under {info.raw_dir}")
    listing = _listing(entries)
    path = cache_path(info.raw_dir)

    catalogue = None
    if use_cache and path.exists():
        try:
            cached = pd.read_parquet(path)
            if _cache_is_current(cached, listing):
                catalogue = cached[CATALOGUE_COLUMNS]
        except Exception:  # noqa: BLE001 - a corrupt cache is simply rebuilt
            catalogue = None

    if catalogue is None:
        catalogue = scan_instances(entries, info.transient_offset, progress)
        if use_cache:
            # Caching is a convenience, never a requirement: a read-only home costs the speed-up only.
            with contextlib.suppress(Exception):
                path.parent.mkdir(parents=True, exist_ok=True)
                catalogue.to_parquet(path, index=False)

    catalogue = catalogue.copy()
    locations = {(fault_class, p.name): p for fault_class, p in entries}
    catalogue["path"] = [
        locations[(fc, name)] for fc, name in zip(catalogue["fault_class"], catalogue["file"])
    ]
    catalogue["start"] = pd.to_datetime(catalogue["start"])
    catalogue["end"] = pd.to_datetime(catalogue["end"])
    stamps = [filename_stamp(name) for name in catalogue["file"]]
    catalogue["stamp"] = [s if s is not None else t for s, t in zip(stamps, catalogue["start"])]
    catalogue["hours"] = (catalogue["end"] - catalogue["start"]).dt.total_seconds() / 3600.0
    return catalogue.sort_values(["well", "start", "file"]).reset_index(drop=True)


def load_instance(path: Path) -> pd.DataFrame:
    """Read one instance in full, sensors as floats, timestamp-indexed."""
    return pd.read_parquet(path)


def load_instance_columns(path: Path, columns: Sequence[str]) -> pd.DataFrame:
    """Read some columns of one instance, timestamp-indexed; one the file lacks comes back empty.

    What a pass over one sensor of a well reads: two columns of a file cost
    about a third of reading it whole (0.55 s against 1.4 s for the 326
    instances of WELL-00002 on 3W 2.0.0).
    """
    present = set(pq.read_schema(path).names)
    frame = pd.read_parquet(path, columns=[name for name in columns if name in present])
    for name in columns:
        if name not in frame.columns:
            frame[name] = np.nan
    return frame[list(columns)]


def merge_instances(frames: list[pd.DataFrame]) -> pd.DataFrame:
    """One continuous recording from the instances of a well that overlap in time.

    The instances of a well are windows cut from the same recording, so the
    samples two of them share carry the same readings twice; the merged frame
    keeps every instant once. Where one window says nothing about a column (a
    sensor it did not record, or a sample the experts left unlabeled) the
    value is taken from whichever window does say something, which is what
    makes merging worth doing: the unlabeled head of a window is usually
    labeled by the window before it, so the ``class`` column comes out with far
    fewer unlabeled samples than any of its parts, and a model is trained on
    what a reader of the merged recording would see.

    Windows only reach this function when their labels agree wherever both are
    known (see ``join_groups``), so nothing is silently preferred over a
    different reading. On 3W 2.0.0 no two real instances disagree on a known
    value of any column at a shared timestamp.
    """
    if len(frames) == 1:
        return frames[0]
    stacked = pd.concat(frames)
    if not stacked.index.has_duplicates:
        return stacked.sort_index(kind="stable")
    # ``first`` is per column and skips the missing values, which is the fill
    # above; it also sorts by the index, so the result is chronological.
    return stacked.groupby(level=0).first()


def stitch_instances(pieces: list[list[pd.DataFrame]]) -> pd.DataFrame:
    """One frame from the recordings of a well laid end to end, the silences between them left out.

    Every piece is a group of overlapping instances, merged as
    ``merge_instances`` merges a joined bar; the pieces follow one another in
    time without overlapping, so they are only concatenated. The index keeps
    the real timestamps: it jumps wherever a silence was left out, and it is
    the time map of whoever draws the frame (``TimeMap`` with no gap) that lays
    the pieces back to back.
    """
    merged = [merge_instances(frames) for frames in pieces]
    if len(merged) == 1:
        return merged[0]
    return pd.concat(merged).sort_index(kind="stable")


# -- Overlaps within a well -----------------------------------------------------------


def pack_lanes(starts: np.ndarray, ends: np.ndarray) -> np.ndarray:
    """Stack overlapping instances, one lane per level of simultaneity.

    Instances are placed in chronological order, each one taking the lowest
    lane whose last instance has already ended; a new lane opens only when
    every existing one is still busy. Two instances therefore share a lane
    exactly when they do not overlap, so the number of lanes is the deepest
    pile-up of the well, and a chain of sliding windows alternates between
    two lanes, its overlaps visible as the horizontal offset between them.
    This is the rule a simple deduplication would use to drop overlapping
    instances by (keep the bottom lane only); the viewer draws every lane
    instead.

    Returns the lane index (0-based) per instance, in the input order.
    """
    lane_of = np.zeros(len(starts), dtype=int)
    lane_ends: list = []
    for i in np.argsort(starts, kind="stable"):
        for lane, lane_end in enumerate(lane_ends):
            if starts[i] > lane_end:
                lane_of[i] = lane
                lane_ends[lane] = ends[i]  # starts are sorted, so this only grows
                break
        else:
            lane_of[i] = len(lane_ends)
            lane_ends.append(ends[i])
    return lane_of


def overlap_matrix(starts: np.ndarray, ends: np.ndarray) -> np.ndarray:
    """Which pairs of instances share at least one timestamp.

    Touching at a single shared second counts, since that second is then
    labeled twice. The diagonal is ``False``.
    """
    starts, ends = np.asarray(starts), np.asarray(ends)
    hits = (starts[:, None] <= ends[None, :]) & (starts[None, :] <= ends[:, None])
    np.fill_diagonal(hits, False)
    return hits


def join_groups(starts: np.ndarray, ends: np.ndarray, runs: list[list[Segment]]) -> list[list[int]]:
    """Group the instances that overlap in time and agree in their labels.

    Instances are taken in order of start. Each one joins the first group that
    holds an instance it overlaps, provided its labels agree
    (``labels.labels_agree``) with those of every member it overlaps, and
    opens a group of its own otherwise. A group is therefore one continuous
    stretch of recording (every member overlaps another) in which no sample
    sits under two different known labels, so its members can be read as a
    single instance.

    Two groups that still overlap afterwards always disagree somewhere: the
    instance that opened the later group overlapped a member of the earlier
    one when it was placed (or a member added since overlaps one it did) and
    was refused, which only a disagreement does. What stays stacked after a
    join is exactly the labeling conflicts.

    Parameters
    ----------
    starts, ends : array-like of datetime64
        First and last timestamp of every instance.
    runs : list[list[Segment]]
        The ``class`` runs of every instance, as ``labels.label_segments``
        returns them.

    Returns
    -------
    list[list[int]]
        The positions of every group's members; groups and members in
        chronological order.
    """
    starts, ends = np.asarray(starts), np.asarray(ends)
    groups: list[list[int]] = []
    for i in np.argsort(starts, kind="stable").tolist():
        for group in groups:
            touching = [m for m in group if starts[i] <= ends[m] and starts[m] <= ends[i]]
            if touching and all(labels_agree(runs[i], runs[m]) for m in touching):
                group.append(i)
                break
        else:
            groups.append([i])
    return groups


def _distinct_samples(part: pd.DataFrame, runs: list[list[Segment]]) -> int:
    """How many sampling instants a group of instances covers between them.

    The shared samples of overlapping instances are counted once: the runs of
    each instance tile it up to one sampling step past its last sample, so the
    union of those spans, in steps, is the number of distinct instants.
    """
    if len(part) == 1 or any(not track for track in runs):
        return int(part["n_samples"].sum())
    tiled_ends = [track[-1].end for track in runs]
    step = tiled_ends[0] - pd.Timestamp(part["end"].iloc[0])
    covered = sum(
        (b - a for a, b, count in coverage_counts(part["start"], tiled_ends) if count >= 1),
        pd.Timedelta(0),
    )
    return round(covered / step)


@dataclass
class WellData:
    """The bars of one well, stacked, with their overlaps resolved.

    A bar is one real instance, or (in the view ``joined`` builds) one group
    of overlapping instances whose labels agree, drawn as one.

    Attributes
    ----------
    well : int
        Well number.
    rows : pd.DataFrame
        One row per bar, sorted by start and re-indexed from zero, with the
        catalogue facts of the instance (or the summary of the group), its
        ``title``, plus ``lane`` (stack level, 0-based) and ``overlaps``
        (whether the bar shares a timestamp with another).
    partners : list[np.ndarray]
        Per bar, the row positions of the bars it overlaps.
    members : list[list[int]]
        Per bar, the positions in ``origin.rows`` of the instances behind it:
        the bar's own position when nothing is joined.
    colors : list[list[tuple[int, str]]]
        Per bar, the fault class and reach of every instance behind it, one
        entry per distinct pair, by fault class and then by decreasing tint
        strength, the colors the bar has to carry.
    source : WellData or None
        The unjoined bars a joined or stitched view was built from; ``None``
        otherwise.
    pieces : list[list[int]] or None
        In the stitched view only: per bar, the positions in the joined view
        of the bars laid end to end in it, chronological.
    """

    well: int
    rows: pd.DataFrame
    partners: list[np.ndarray]
    members: list[list[int]]
    colors: list[list[tuple[int, str]]]
    source: "WellData | None" = None
    pieces: list[list[int]] | None = None
    # The joined view of this well, built once and handed to everyone who asks
    # for it: the overview draws it, and an instance window opened from either
    # view switches between the two without building anything again.
    _joined: "WellData | None" = field(default=None, repr=False, compare=False)
    _stitched: "WellData | None" = field(default=None, repr=False, compare=False)

    @classmethod
    def from_catalogue(cls, catalogue: pd.DataFrame, well: int) -> "WellData":
        rows = (
            catalogue[catalogue["well"] == well]
            .sort_values(["start", "file"])
            .reset_index(drop=True)
        )
        if rows.empty:
            raise ValueError(f"No instances of {well_label(well)} in the catalogue")
        rows["title"] = [os.path.splitext(str(name))[0] for name in rows["file"]]
        members = [[i] for i in range(len(rows))]
        colors = [
            [(int(fault_class), str(reach))]
            for fault_class, reach in zip(rows["fault_class"], rows["reach"])
        ]
        return cls._stacked(well, rows, members, colors, None)

    @classmethod
    def _stacked(
        cls,
        well: int,
        rows: pd.DataFrame,
        members: list[list[int]],
        colors: list[list[tuple[int, str]]],
        source: "WellData | None",
        pieces: list[list[int]] | None = None,
    ) -> "WellData":
        """Lay ``rows`` (chronological) on their lanes and find which ones overlap."""
        starts = rows["start"].to_numpy(dtype="datetime64[ns]")
        ends = rows["end"].to_numpy(dtype="datetime64[ns]")
        hits = overlap_matrix(starts, ends)
        rows["lane"] = pack_lanes(starts, ends)
        rows["overlaps"] = hits.any(axis=1)
        partners = [np.flatnonzero(row) for row in hits]
        return cls(well, rows, partners, members, colors, source, pieces)

    def joined(self, among: list[int] | None = None) -> "WellData":
        """The groups of agreeing, overlapping instances of this well, each drawn as one bar.

        The groups are those of ``join_groups``, read from the ``class_runs``
        the catalogue carries. A joined bar spans from the first start to the
        last end of its members and remembers them in ``members``; its
        ``colors`` are those of all of them, and its ``fault_class`` and
        ``reach`` summarize what the joined labels reach: the strongest reach
        among the members, and the class of the member that reached it (a
        fault before normal operation, and the earliest, on a tie). Its title
        is the first member's followed by how many more it joins.

        Parameters
        ----------
        among : list[int], optional
            Join only these instances, and return only what they make up.
            Two of them that overlap only through an instance left out stay
            apart, so the result is what joining that set alone says rather
            than what the whole well says, which is what an instance window
            asks for, its own group being all it is about. The default joins
            the well, and is built once and remembered, so that asking for it
            again hands back the very object the overview is drawing.
        """
        if self.source is not None:
            return self if self.pieces is None else self.source.joined(among)
        if among is not None:
            return self._build_joined(sorted(among))
        if self._joined is None:
            self._joined = self._build_joined(None)
        return self._joined

    def _build_joined(self, among: list[int] | None) -> "WellData":
        rows = self.rows
        taken = list(range(len(rows))) if among is None else list(among)
        scope = rows.iloc[taken]
        runs = {p: segments_from_json(text) for p, text in zip(taken, scope["class_runs"])}
        # ``join_groups`` numbers what it is given; the groups are put back into
        # the well's own numbering, which is what ``members`` promises.
        groups = [
            [taken[k] for k in group]
            for group in join_groups(
                scope["start"].to_numpy(dtype="datetime64[ns]"),
                scope["end"].to_numpy(dtype="datetime64[ns]"),
                [runs[p] for p in taken],
            )
        ]
        records, members, colors = [], [], []
        for group in groups:
            part = rows.iloc[group]
            first = part.iloc[0]
            classes = [int(fault_class) for fault_class in part["fault_class"]]
            reaches = [str(reach) for reach in part["reach"]]
            lead = max(
                range(len(group)),
                key=lambda k: (REACH_TINTS[reaches[k]], classes[k] != 0, -k),
            )
            keys = sorted(
                set(zip(classes, reaches)), key=lambda key: (key[0], -REACH_TINTS[key[1]])
            )
            start, end = pd.Timestamp(part["start"].min()), pd.Timestamp(part["end"].max())
            more = len(group) - 1
            records.append(
                {
                    "title": f"{first['title']} +{more}" if more else str(first["title"]),
                    "fault_class": classes[lead],
                    "well": self.well,
                    "start": start,
                    "end": end,
                    "n_samples": _distinct_samples(part, [runs[i] for i in group]),
                    "reach": reaches[lead],
                    "stamp": first["stamp"],
                    "hours": (end - start).total_seconds() / 3600.0,
                }
            )
            members.append(list(group))
            colors.append(keys)
        return self._stacked(self.well, pd.DataFrame(records), members, colors, self)

    def stitched(self) -> "WellData":
        """The well's history as one bar: the joined bars laid end to end, the silences left out.

        What a reader asks to see how the levels of a well changed from one
        recording to the next, months apart: the joined bars of each lane
        (``joined``) become one bar spanning from the first start to the last
        end, whose ``members`` are every instance behind them and whose
        ``pieces`` say which joined bars it is laid from. Its ``hours`` and
        ``n_samples`` are those of the recordings, not of the calendar span.
        On 3W 2.0.0 the joined view of every well is a single lane, so every
        well stitches into one bar; a lane of its own, which only a labeling
        conflict leaves, would stitch into a second bar rather than have two
        disagreeing labels merged. Built once and remembered.
        """
        if self.pieces is not None:
            return self
        origin = self.origin
        if origin._stitched is None:
            origin._stitched = origin._build_stitched()
        return origin._stitched

    def _build_stitched(self) -> "WellData":
        joined = self.joined()
        bars = joined.rows
        records, members, colors, pieces = [], [], [], []
        for lane in sorted(set(bars["lane"].tolist())):
            taken = [i for i in range(len(bars)) if int(bars["lane"].iloc[i]) == lane]
            part = bars.iloc[taken]
            classes = [int(fault_class) for fault_class in part["fault_class"]]
            reaches = [str(reach) for reach in part["reach"]]
            lead = max(
                range(len(taken)),
                key=lambda k: (REACH_TINTS[reaches[k]], classes[k] != 0, -k),
            )
            keys = sorted(
                {key for i in taken for key in joined.colors[i]},
                key=lambda key: (key[0], -REACH_TINTS[key[1]]),
            )
            behind = [m for i in taken for m in joined.members[i]]
            first = self.rows.iloc[behind[0]]
            records.append(
                {
                    "title": f"{first['title']} +{len(behind) - 1}"
                    if len(behind) > 1
                    else str(first["title"]),
                    "fault_class": classes[lead],
                    "well": self.well,
                    "start": pd.Timestamp(part["start"].min()),
                    "end": pd.Timestamp(part["end"].max()),
                    "n_samples": int(part["n_samples"].sum()),
                    "reach": reaches[lead],
                    "stamp": first["stamp"],
                    "hours": float(part["hours"].sum()),
                }
            )
            members.append(behind)
            colors.append(keys)
            pieces.append(taken)
        return self._stacked(self.well, pd.DataFrame(records), members, colors, self, pieces)

    @property
    def joined_view(self) -> bool:
        """Whether the bars are groups of instances rather than the instances themselves."""
        return self.source is not None

    @property
    def stitched_view(self) -> bool:
        """Whether the bars are the well's recordings laid end to end (``stitched``)."""
        return self.pieces is not None

    def piece_members(self, index: int) -> list[list[int]]:
        """The instances behind each recording one bar is laid from; one group for an unstitched bar."""
        if self.pieces is None:
            return [list(self.members[index])]
        joined = self.source.joined()
        return [list(joined.members[p]) for p in self.pieces[index]]

    def spans(self, positions: Sequence[int] | None = None) -> tuple[np.ndarray, np.ndarray]:
        """The starts and ends of the recordings behind some bars (all by default), for a time axis.

        A stitched bar spans the calendar from its first recording to its last
        and stands for the recordings alone, so its axis is built from those;
        any other bar is its own span.
        """
        positions = range(self.n_instances) if positions is None else positions
        if self.pieces is None:
            return self.starts[list(positions)], self.ends[list(positions)]
        joined = self.source.joined()
        taken = sorted({p for position in positions for p in self.pieces[position]})
        return joined.starts[taken], joined.ends[taken]

    @property
    def origin(self) -> "WellData":
        """The instances themselves: ``source`` of a joined view, else this object."""
        return self.source if self.source is not None else self

    @property
    def label(self) -> str:
        return well_label(self.well)

    @property
    def n_instances(self) -> int:
        return len(self.rows)

    @property
    def n_overlapping(self) -> int:
        return int(self.rows["overlaps"].sum())

    @property
    def n_lanes(self) -> int:
        return int(self.rows["lane"].max()) + 1

    @property
    def starts(self) -> np.ndarray:
        return self.rows["start"].to_numpy(dtype="datetime64[ns]")

    @property
    def ends(self) -> np.ndarray:
        return self.rows["end"].to_numpy(dtype="datetime64[ns]")

    def group(self, index: int) -> list[int]:
        """Row positions of one bar and of every bar it overlaps, chronological."""
        return sorted({int(index), *(int(j) for j in self.partners[index])})

    def fault_classes(self) -> set[int]:
        """The fault-class folders this well has instances in."""
        return {fault_class for keys in self.colors for fault_class, _ in keys}

    def present_colors(self) -> set[tuple[int, str]]:
        """Fault class and reach of every color this well draws."""
        return {key for keys in self.colors for key in keys}


def split_wells(catalogue: pd.DataFrame) -> list[WellData]:
    """One ``WellData`` per well of the catalogue, by ascending well number."""
    return [
        WellData.from_catalogue(catalogue, int(well)) for well in sorted(catalogue["well"].unique())
    ]


def lane_slots(wells: list[WellData], minimum: int, maximum: int) -> int:
    """Stack levels every timeline shows: the deepest pile-up, within bounds."""
    deepest = max((well.n_lanes for well in wells), default=1)
    return int(min(max(deepest, minimum), maximum))


def instance_title(row: pd.Series) -> str:
    """The name of a bar: its ``title`` when it has one, else its filename without extension."""
    if "title" in row.index:
        return str(row["title"])
    return os.path.splitext(str(row["file"]))[0]


# -- Sensor figures of merged recordings -----------------------------------------------


class BarStats(NamedTuple):
    """What the data pass says about one bar of the joined view.

    Attributes
    ----------
    n_samples : int
        Distinct instants of the merged recording.
    sensors : dict[str, (int, float, float)]
        Per sensor, its readings and their bounds.
    pairs : np.ndarray
        Per pair of sensors, the samples carrying both (``pair_positions``).
    """

    n_samples: int
    sensors: dict[str, tuple[int, float, float]]
    pairs: np.ndarray


JoinedStats = dict[tuple[int, int], BarStats]

JOINED_COLUMNS = ["well", "bar", "n_total", "sensor_stats", "pairs", "sensors", "listing_digest"]


def merged_sensor_stats(frame: pd.DataFrame) -> dict[str, tuple[int, float, float]]:
    """What each sensor of one frame recorded: readings, lowest, highest; the data's own footer."""
    stats = {}
    for name in frame.columns:
        if not is_sensor_column(str(name)):
            continue
        values = column_as_float(frame, name)
        valid = values[~np.isnan(values)]
        if len(valid):
            stats[str(name)] = (len(valid), float(valid.min()), float(valid.max()))
        else:
            stats[str(name)] = (0, np.nan, np.nan)
    return stats


def scan_joined_stats(
    wells: list[WellData], sensors: list[str], progress: ProgressCallback | None = None
) -> JoinedStats:
    """What every bar of the joined view of every well recorded, sensor by sensor and pair by pair.

    A bar joined from several instances is read as the single recording they
    were cut from (``merge_instances``), and a sensor's readings are counted
    once per instant: what one window did not record another may have, and
    what two windows both record is not two readings. The same merged
    recording answers which sensors carry a reading at the same instant, a
    question the footers cannot answer at all and which joining changes, since
    a sensor one window missed is filled in by another where they overlap.

    Both figures therefore come from one pass over the data, which takes a few
    seconds per hundred instances and is cached.

    Parameters
    ----------
    wells : list[WellData]
        The wells, instance by instance; their joined views are built here.
    sensors : list[str]
        The sensors the pair counts are taken in the order of.
    progress : callable, optional
        Called as ``progress(done, total, title)`` with the count of instances
        gone through; return ``False`` to cancel, which raises ``ScanCancelled``.

    Returns
    -------
    JoinedStats
        ``(well, bar) -> BarStats``.
    """
    total = sum(well.n_instances for well in wells)
    done = 0
    result: JoinedStats = {}
    for well in wells:
        origin, view = well.origin, well.joined()
        paths = origin.rows["path"]
        for bar, members in enumerate(view.members):
            merged = merge_instances([load_instance(paths.iloc[m]) for m in members])
            result[(well.well, bar)] = BarStats(
                len(merged),
                merged_sensor_stats(merged),
                pair_counts_from_frame(merged, sensors),
            )
            done += len(members)
            if progress is not None and not progress(
                done, total, instance_title(view.rows.iloc[bar])
            ):
                raise ScanCancelled()
    return result


def listing_digest(listing: pd.DataFrame) -> str:
    """A digest of what the dataset holds now: names, folders, sizes, modification times."""
    ordered = listing.sort_values(["fault_class", "file"])
    text = "\n".join(
        f"{fc}/{name}:{size}:{mtime}"
        for fc, name, size, mtime in zip(
            ordered["fault_class"], ordered["file"], ordered["size"], ordered["mtime_ns"]
        )
    )
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def joined_cache_path(raw_dir: Path) -> Path:
    """Cache file of the merged sensor figures of one dataset root, next to its catalogue."""
    digest = hashlib.sha1(str(Path(raw_dir).resolve()).encode("utf-8")).hexdigest()[:12]
    return cache_dir() / f"joined_{digest}.parquet"


def load_joined_stats(
    info: DatasetInfo,
    wells: list[WellData],
    sensors: list[str],
    use_cache: bool = True,
    progress: ProgressCallback | None = None,
) -> JoinedStats:
    """The merged figures of every well, from the cache when nothing has changed.

    The joined view of a well is a function of the catalogue, and the
    catalogue of the files, so the cache is valid exactly while the listing of
    the files (names, sizes, modification times) has the digest it was written
    under, and while the sensors asked for are the ones the pair counts were
    taken in the order of. Writing it is best effort, as for the catalogue.
    """
    entries = list_real_instances(info.raw_dir, info.fault_classes)
    digest = listing_digest(_listing(entries))
    names = json.dumps(list(sensors), separators=(",", ":"))
    path = joined_cache_path(info.raw_dir)
    if use_cache and path.exists():
        # A corrupt cache is simply rebuilt, like the catalogue's.
        with contextlib.suppress(Exception):
            cached = pd.read_parquet(path)
            current = (
                len(cached)
                and set(JOINED_COLUMNS) <= set(cached.columns)
                and (cached["listing_digest"] == digest).all()
                and (cached["sensors"] == names).all()
            )
            if current:
                return {
                    (int(well), int(bar)): BarStats(
                        int(n_total),
                        sensor_stats_from_json(str(text)),
                        np.asarray(json.loads(pairs), dtype=np.int64),
                    )
                    for well, bar, n_total, text, pairs in zip(
                        cached["well"],
                        cached["bar"],
                        cached["n_total"],
                        cached["sensor_stats"],
                        cached["pairs"],
                    )
                }
    result = scan_joined_stats(wells, sensors, progress)
    if use_cache:
        with contextlib.suppress(Exception):
            path.parent.mkdir(parents=True, exist_ok=True)
            pd.DataFrame(
                [
                    {
                        "well": well,
                        "bar": bar,
                        "n_total": stats.n_samples,
                        "sensor_stats": sensor_stats_to_json(stats.sensors),
                        "pairs": json.dumps([int(c) for c in stats.pairs], separators=(",", ":")),
                        "sensors": names,
                        "listing_digest": digest,
                    }
                    for (well, bar), stats in result.items()
                ],
                columns=JOINED_COLUMNS,
            ).to_parquet(path, index=False)
    return result


# -- Sensors recorded at the same instant --------------------------------------------

# What one instance contributes to the pair map: the co-valid sample counts of
# every pair of sensors, cached as text next to the catalogue.
PairCounts = dict[tuple[int, str], np.ndarray]

PAIR_COLUMNS = ["file", "fault_class", "pairs", "sensors", "listing_digest"]


def pair_positions(n: int) -> tuple[np.ndarray, np.ndarray]:
    """Which two sensors each stored count belongs to: the upper triangle, diagonal included.

    The matrix is symmetric (two sensors read together as often as they read
    together) so only half of it is kept, and the diagonal with it, where a
    pair of one sensor is that sensor's own count of readings.
    """
    return np.triu_indices(n, 0)


def pair_counts_from_frame(frame: pd.DataFrame, sensors: list[str]) -> np.ndarray:
    """How many samples of one recording carry readings of both sensors, pair by pair.

    The footers cannot answer this. A count of missing values says how much of
    a column is there, not *which* samples are there, and two sensors can each
    cover half a recording and never overlap; only the pattern of the missing
    values says whether a model could have used them together. So the validity
    pattern is multiplied by itself, which is one small matrix product.

    Returns the upper triangle of the symmetric matrix, in the order
    ``pair_positions`` gives, with a zero for every sensor the recording does
    not carry.
    """
    n = len(sensors)
    index = {name: i for i, name in enumerate(sensors)}
    present = [name for name in frame.columns if name in index]
    counts = np.zeros((n, n), dtype=np.int64)
    if present and len(frame):
        # float32 rather than bool: the product is a BLAS matrix multiply, and
        # a count of samples is far below the 2^24 where float32 stops being exact.
        valid = frame[present].notna().to_numpy().astype(np.float32)
        positions = [index[name] for name in present]
        counts[np.ix_(positions, positions)] = np.rint(valid.T @ valid).astype(np.int64)
    rows, cols = pair_positions(n)
    return counts[rows, cols]


def read_pair_counts(parquet: pq.ParquetFile, sensors: list[str]) -> np.ndarray:
    """``pair_counts_from_frame`` for one instance, reading only the columns it needs."""
    wanted = set(sensors)
    present = [name for name in parquet.schema_arrow.names if name in wanted]
    if not present:
        return np.zeros(len(pair_positions(len(sensors))[0]), dtype=np.int64)
    return pair_counts_from_frame(parquet.read(columns=present).to_pandas(), sensors)


def scan_pair_counts(
    entries: list[tuple[int, Path]],
    sensors: list[str],
    progress: ProgressCallback | None = None,
) -> PairCounts:
    """Read every instance and count, per pair of sensors, the samples carrying both.

    Parameters
    ----------
    entries : list[(int, Path)]
        Fault class and path of every file, from ``list_real_instances``.
    sensors : list[str]
        The sensors to count, in the order the pair map will show them.
    progress : callable, optional
        Progress callback of ``scan_instances``.

    Returns
    -------
    PairCounts
        ``(fault class, filename) -> the upper triangle of the pair matrix``.
    """
    result: PairCounts = {}
    for i, (fault_class, path) in enumerate(entries, start=1):
        with pq.ParquetFile(path) as parquet:
            result[(fault_class, path.name)] = read_pair_counts(parquet, sensors)
        if progress is not None and not progress(i, len(entries), path.name):
            raise ScanCancelled()
    return result


def pair_cache_path(raw_dir: Path) -> Path:
    """Cache file of the pair counts of one dataset root, next to its catalogue."""
    digest = hashlib.sha1(str(Path(raw_dir).resolve()).encode("utf-8")).hexdigest()[:12]
    return cache_dir() / f"pairs_{digest}.parquet"


def load_pair_counts(
    info: DatasetInfo,
    sensors: list[str],
    use_cache: bool = True,
    progress: ProgressCallback | None = None,
) -> PairCounts:
    """The pair counts of every instance, from the cache when nothing has changed.

    The cache is valid while the listing of the files has the digest it was
    written under and the sensors asked for are the ones it holds, since the
    counts are stored in that order. Writing it is best effort, as for the
    catalogue.
    """
    entries = list_real_instances(info.raw_dir, info.fault_classes)
    digest = listing_digest(_listing(entries))
    names = json.dumps(list(sensors), separators=(",", ":"))
    path = pair_cache_path(info.raw_dir)
    if use_cache and path.exists():
        # A corrupt cache is simply rebuilt, like the catalogue's.
        with contextlib.suppress(Exception):
            cached = pd.read_parquet(path)
            current = (
                len(cached)
                and set(PAIR_COLUMNS) <= set(cached.columns)
                and (cached["listing_digest"] == digest).all()
                and (cached["sensors"] == names).all()
            )
            if current:
                return {
                    (int(fault_class), str(file)): np.asarray(json.loads(text), dtype=np.int64)
                    for file, fault_class, text in zip(
                        cached["file"], cached["fault_class"], cached["pairs"]
                    )
                }
    result = scan_pair_counts(entries, sensors, progress)
    if use_cache:
        with contextlib.suppress(Exception):
            path.parent.mkdir(parents=True, exist_ok=True)
            pd.DataFrame(
                [
                    {
                        "file": file,
                        "fault_class": fault_class,
                        "pairs": json.dumps([int(c) for c in counts], separators=(",", ":")),
                        "sensors": names,
                        "listing_digest": digest,
                    }
                    for (fault_class, file), counts in result.items()
                ],
                columns=PAIR_COLUMNS,
            ).to_parquet(path, index=False)
    return result
