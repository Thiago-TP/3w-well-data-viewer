"""Labels of an instance: kinds, names, runs in time, feature statistics. No Qt here.

The ``class`` column of a 3W instance is 0 for normal operation, the fault
number while the fault is installed (its steady state) and the fault number
plus the transient offset while it installs itself; missing values are
unlabeled stretches. Everything a plot needs from that column (the runs of
constant value, their names, the reach of the instance) is computed here.
"""

import json
from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise

import numpy as np
import pandas as pd

from overlap_viewer.backend.config import (
    DEFAULT_TRANSIENT_OFFSET,
    FLAT_SPAN,
    LABEL_COLUMNS,
    WELL_STATES,
)


def label_kind(value: float, offset: int = DEFAULT_TRANSIENT_OFFSET) -> str:
    """Classify one ``class`` value as ``normal``, ``steady``, ``transient`` or ``unknown``."""
    if np.isnan(value):
        return "unknown"
    if value == 0:
        return "normal"
    if 1 <= value < offset:
        return "steady"
    if offset + 1 <= value < 2 * offset:
        return "transient"
    return "unknown"


def label_fault(value: float, offset: int = DEFAULT_TRANSIENT_OFFSET) -> int | None:
    """Fault number a ``class`` value refers to; ``None`` for normal or unknown."""
    kind = label_kind(value, offset)
    if kind == "steady":
        return int(value)
    if kind == "transient":
        return int(value) - offset
    return None


def label_name(
    value: float, fault_names: dict[int, str], offset: int = DEFAULT_TRANSIENT_OFFSET
) -> str:
    """Human-readable name of one ``class`` value."""
    kind = label_kind(value, offset)
    if kind == "unknown":
        return "Unknown"
    if kind == "normal":
        return fault_names.get(0, "Normal Operation")
    fault = label_fault(value, offset)
    name = fault_names.get(fault, f"Class {fault}")
    return name if kind == "steady" else f"{name} - Transient"


def state_name(value: float) -> str:
    """Human-readable name of one ``state`` value."""
    return "Unknown" if np.isnan(value) else WELL_STATES.get(int(value), f"Status {int(value)}")


def fault_reach(class_values: np.ndarray, offset: int = DEFAULT_TRANSIENT_OFFSET) -> str:
    """Tell how far a fault developed inside one instance, from its labels.

    Returns the strongest state the labels reach: ``"steady"``,
    ``"transient"``, or ``"normal"`` when the recording never leaves normal
    operation (or is unlabeled throughout).
    """
    present = class_values[~np.isnan(class_values)]
    if np.any((present >= 1) & (present < offset)):
        return "steady"
    if np.any((present > offset) & (present < 2 * offset)):
        return "transient"
    return "normal"


def runs(values: np.ndarray) -> list[tuple[int, int, float]]:
    """Split a 1-D float array into runs of constant value (NaN counts as a value).

    Returns ``(start, end, value)`` per run, ``end`` exclusive.
    """
    if len(values) == 0:
        return []
    codes = np.where(np.isnan(values), -1.0, values)
    change = np.flatnonzero(codes[1:] != codes[:-1]) + 1
    starts = np.concatenate(([0], change))
    ends = np.concatenate((change, [len(codes)]))
    return [(int(s), int(e), float(values[s])) for s, e in zip(starts, ends)]


def column_as_float(df: pd.DataFrame, column: str) -> np.ndarray:
    """One column as a float array with NaN for missing, or all NaN when absent.

    The 3W label columns are nullable integers, which ``to_numpy`` cannot
    hand out as floats without an explicit missing-value replacement.
    """
    if column not in df.columns:
        return np.full(len(df), np.nan)
    return df[column].to_numpy(dtype=float, na_value=np.nan)


@dataclass(frozen=True)
class Segment:
    """One stretch of constant label: its time span and its value."""

    start: pd.Timestamp
    end: pd.Timestamp
    value: float


def label_segments(df: pd.DataFrame, column: str) -> list[Segment]:
    """Runs of one label column as time spans.

    A run ends where the next one starts; the last run ends one sampling
    interval after the last sample, so consecutive segments tile the recording
    without gaps and the final one is not lost when the run is one sample long.
    """
    values = column_as_float(df, column)
    index = df.index
    if len(index) == 0:
        return []
    step = pd.Timedelta(seconds=1)
    if len(index) > 1:
        deltas = np.diff(index.to_numpy(dtype="datetime64[ns]"))
        positive = deltas[deltas > np.timedelta64(0, "ns")]
        if len(positive):
            step = pd.Timedelta(np.median(positive))
    segments = []
    for start, end, value in runs(values):
        t_end = index[end] if end < len(index) else index[-1] + step
        segments.append(Segment(pd.Timestamp(index[start]), pd.Timestamp(t_end), value))
    return segments


def segments_to_json(segments: list[Segment]) -> str:
    """Write label runs as ``[[start, end, value], ...]``, for the catalogue cache.

    Times are nanoseconds since the epoch, so nothing is rounded, and an
    unlabeled run carries ``null``. A file has only a few runs, so the text
    stays short whatever the length of the recording.
    """
    return json.dumps(
        [
            [int(s.start.value), int(s.end.value), None if np.isnan(s.value) else int(s.value)]
            for s in segments
        ],
        separators=(",", ":"),
    )


def segments_from_json(text: str) -> list[Segment]:
    """Read back what ``segments_to_json`` wrote."""
    return [
        Segment(pd.Timestamp(start), pd.Timestamp(end), np.nan if value is None else float(value))
        for start, end, value in json.loads(text)
    ]


def sensor_stats_to_json(stats) -> str:
    """Write the per-sensor figures of one instance as ``{"P-PDG": [n, low, high], ...}``.

    ``stats`` maps a sensor to ``(readings, lowest, highest)``, as
    ``dataset.read_sensor_stats`` returns them. A sensor with no reading has
    ``null`` for its bounds; the text goes into the catalogue cache next to the
    label runs.
    """

    def number(value: float) -> float | None:
        return None if value is None or np.isnan(value) else float(value)

    return json.dumps(
        {name: [int(n), number(low), number(high)] for name, (n, low, high) in stats.items()},
        separators=(",", ":"),
    )


def sensor_stats_from_json(text: str) -> dict[str, tuple[int, float, float]]:
    """Read back what ``sensor_stats_to_json`` wrote."""
    return {
        name: (
            int(n),
            np.nan if low is None else float(low),
            np.nan if high is None else float(high),
        )
        for name, (n, low, high) in json.loads(text).items()
    }


def merge_label_runs(
    tracks: list[list[Segment]], sources: list[int]
) -> list[tuple[Segment, int | None]]:
    """Read several overlapping label tracks as one, remembering what each stretch came from.

    At every instant the value is the one of the first track that knows a label
    there, the tracks being given in chronological order; where none does, the
    stretch stays unlabeled. This is the rule ``dataset.merge_instances``
    applies to the ``class`` column of the frames themselves, so the two agree,
    and it is what shrinks the unlabeled stretches of a merged recording: the
    unlabeled head of a window is usually labeled by the window before it.

    Each stretch is returned with the entry of ``sources`` belonging to the
    track that supplied it (``None`` where nothing is known), so a drawing of
    the merged recording can keep saying which file a label came from: the
    fault folder, for this viewer, and so the hue of the shading. A stretch
    labeled *normal* by a Normal Operation file therefore stays that file's
    color inside a merged recording that goes on to develop a fault.

    Parameters
    ----------
    tracks : list[list[Segment]]
        The label runs of every instance, each tiling its own span, earliest
        instance first (as ``label_segments`` returns them).
    sources : list[int]
        What to remember per track.

    Returns
    -------
    list[(Segment, int | None)]
        The merged runs, chronological and coalesced, with their source.
    """
    edges = sorted({t for track in tracks for run in track for t in (run.start, run.end)})
    starts = [[run.start for run in track] for track in tracks]
    merged: list[tuple[Segment, int | None]] = []
    for a, b in pairwise(edges):
        value: float = np.nan
        source: int | None = None
        for track, track_starts, origin in zip(tracks, starts, sources):
            i = bisect_right(track_starts, a) - 1
            if i < 0:
                continue
            run = track[i]
            if run.start <= a < run.end and not np.isnan(run.value):
                value, source = run.value, origin
                break
        if merged:
            last, last_source = merged[-1]
            same = last.value == value or (np.isnan(last.value) and np.isnan(value))
            if last_source == source and same and last.end == a:
                merged[-1] = (Segment(last.start, b, value), source)
                continue
        merged.append((Segment(a, b, value), source))
    return merged


def labels_agree(a: list[Segment], b: list[Segment]) -> bool:
    """Whether two label tracks never contradict each other where both have samples.

    Two labels contradict each other when both are known and differ; an
    unlabeled (NaN) stretch agrees with anything, and so does a stretch only
    one of the tracks covers. This is the condition under which two
    overlapping instances can be joined into one recording without any sample
    ending up under two different labels. Both tracks must tile their span,
    as ``label_segments`` returns them.
    """
    if not a or not b:
        return True
    t = max(a[0].start, b[0].start)
    hi = min(a[-1].end, b[-1].end)
    i = j = 0
    while t < hi:
        while a[i].end <= t:
            i += 1
        while b[j].end <= t:
            j += 1
        va, vb = a[i].value, b[j].value
        if not (np.isnan(va) or np.isnan(vb) or va == vb):
            return False
        t = min(a[i].end, b[j].end)
    return True


def sensor_columns(df: pd.DataFrame) -> list[str]:
    """Every column of an instance that is a sensor rather than a label."""
    return [c for c in df.columns if c not in LABEL_COLUMNS]


@dataclass(frozen=True)
class FeatureStats:
    """What a plot panel reports about one sensor of one instance."""

    n_valid: int
    n_total: int
    low: float
    high: float

    @property
    def recorded(self) -> bool:
        return self.n_valid > 0

    @property
    def coverage(self) -> float:
        """Share of the samples carrying a reading, in percent."""
        return 100.0 * self.n_valid / self.n_total if self.n_total else 0.0

    @property
    def delta(self) -> float:
        """Total variation of the signal (max - min)."""
        return self.high - self.low

    @property
    def flat(self) -> bool:
        """Whether the signal never moves relative to its own level."""
        return self.recorded and is_flat(self.low, self.high)


def feature_stats(df: pd.DataFrame, sensor: str) -> FeatureStats:
    """Coverage and range of one sensor of one instance."""
    if sensor not in df.columns:
        return FeatureStats(0, len(df), np.nan, np.nan)
    values = df[sensor].to_numpy(dtype=float)
    valid = values[~np.isnan(values)]
    if len(valid) == 0:
        return FeatureStats(0, len(df), np.nan, np.nan)
    return FeatureStats(len(valid), len(df), float(valid.min()), float(valid.max()))


def at_index_unit(frame: pd.DataFrame, stamp: pd.Timestamp) -> pd.Timestamp:
    """``stamp`` at the resolution ``frame`` is indexed in, rounding if it has to.

    A 3W file read back through pyarrow is indexed in **microseconds**, while a
    timestamp worked out from the edge of a view, or from an axis coordinate,
    carries nanoseconds. Pandas will not search a microsecond index with such a
    value: rather than move the boundary silently it raises ``Cannot losslessly
    convert units``. The boundary here is a view edge or a pointer position,
    where a nanosecond either way is nothing, so it is rounded and the search
    goes ahead.
    """
    # ``DatetimeIndex.dtype`` is a plain numpy ``M8[us]``, which carries no
    # ``unit`` attribute; the index itself is what knows its resolution.
    unit = getattr(frame.index, "unit", None)
    if unit is None or not isinstance(stamp, pd.Timestamp):
        return stamp
    return stamp.as_unit(unit, round_ok=True)


def is_flat(low: float, high: float) -> bool:
    """Whether a range is below ``FLAT_SPAN`` of its own level."""
    center = 0.5 * (low + high)
    return high - low <= FLAT_SPAN * max(abs(center), 1.0)


def padded_range(low: float, high: float, pad: float = 0.06) -> tuple[float, float]:
    """Axis limits for a signal range: padded, or centered when the signal is flat.

    A frozen or barely moving variable left to autoscale fills its axis with
    amplified noise that reads like a signal; it is instead centered with a
    margin of 1 % of its level (at least 0.5), so the line reads as the flat
    line it is and the ticks state its level.
    """
    if np.isnan(low) or np.isnan(high):
        return (-1.0, 1.0)
    if is_flat(low, high):
        center = 0.5 * (low + high)
        margin = max(abs(center) * 0.01, 0.5)
        return (center - margin, center + margin)
    margin = (high - low) * pad
    return (low - margin, high + margin)


def format_delta(delta: float, unit: str) -> str:
    """``Δ = 0.638 MPa``, unit omitted when unknown."""
    return f"Δ = {delta:.3g} {unit}".rstrip()


# The label periods in the order an event develops, as ``label_kind`` names them.
PERIOD_KINDS = ("normal", "transient", "steady", "unknown")


def period_durations(
    runs: Sequence[Segment], offset: int = DEFAULT_TRANSIENT_OFFSET
) -> dict[str, float]:
    """The seconds a recording spends in each label period, in ``PERIOD_KINDS`` order.

    ``runs`` are label runs that tile the recording (``label_segments``,
    ``merge_label_runs``), so the durations add up to its span; a period it
    never enters has zero.
    """
    durations = dict.fromkeys(PERIOD_KINDS, 0.0)
    for run in runs:
        seconds = (pd.Timestamp(run.end) - pd.Timestamp(run.start)).total_seconds()
        durations[label_kind(run.value, offset)] += max(seconds, 0.0)
    return durations


def format_duration(seconds: float) -> str:
    """``5 h 56 min 15 s``: days, hours, minutes and seconds, the ones that are zero left out."""
    total = round(max(float(seconds), 0.0))
    days, rest = divmod(total, 86400)
    hours, rest = divmod(rest, 3600)
    minutes, secs = divmod(rest, 60)
    parts = [
        f"{value} {name}"
        for value, name in ((days, "d"), (hours, "h"), (minutes, "min"), (secs, "s"))
        if value
    ]
    return " ".join(parts) or "0 s"


def coverage_counts(starts, ends) -> list[tuple[pd.Timestamp, pd.Timestamp, int]]:
    """How many instances cover each stretch of time.

    Sweeps the starts and ends of the instances and returns, for every
    stretch between two consecutive boundaries, how many instances span it;
    stretches covered by none are returned with a count of zero, so the result
    tiles the whole range from the first start to the last end.
    """
    starts = pd.to_datetime(np.asarray(starts))
    ends = pd.to_datetime(np.asarray(ends))
    events = sorted([(t, 1) for t in starts] + [(t, -1) for t in ends], key=lambda e: (e[0], e[1]))
    stretches = []
    count = 0
    for (t, delta), (t_next, _) in pairwise(events):
        count += delta
        if t_next > t:
            stretches.append((pd.Timestamp(t), pd.Timestamp(t_next), count))
    return stretches
