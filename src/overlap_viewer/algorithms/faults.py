"""Comparing the instances of one fault across wells: where each begins, and the series made comparable. No Qt here.

Rabelo's figures 2.5 and 2.6 put two instances of the same fault side by side
to make a point the models have to live with: the same event, on two wells,
has a different magnitude, a different time to install itself and a different
baseline. The faults page draws every real instance of a fault over the
others so that the point can be seen for every fault and every well, and this
module supplies what the drawing needs: the moment the event begins inside
each instance, to align them on; each series scaled to its own level, to
compare shapes where the absolute readings cannot be compared; and the extent
of a series once the readings no instrument could have produced are left out,
so that one broken gauge does not flatten every other line on the plot.
"""

from collections.abc import Sequence

import numpy as np
import pandas as pd

from overlap_viewer.backend.config import DEFAULT_TRANSIENT_OFFSET
from overlap_viewer.backend.labels import Segment, column_as_float

# Where the instances of a fault can be aligned: the first sample labeled with
# the transient of the event, the first labeled with its steady state, or the
# first sample of the recording.
ALIGNMENTS = ("transient", "steady", "start")
ALIGNMENT_NAMES = {
    "transient": "Onset of the transient",
    "steady": "Onset of the steady state",
    "start": "Start of the instance",
}
ALIGNMENT_AXES = {
    "transient": "Hours from the onset of the transient",
    "steady": "Hours from the onset of the steady state",
    "start": "Hours from the start of the instance",
}


def onset(
    frame: pd.DataFrame,
    fault: int,
    offset: int = DEFAULT_TRANSIENT_OFFSET,
    align: str = "transient",
) -> pd.Timestamp | None:
    """When the event begins inside one instance, by the labels: the moment to align it on.

    Parameters
    ----------
    frame : pd.DataFrame
        The instance, timestamp-indexed, with its ``class`` column.
    fault : int
        The fault class the instance is filed under.
    offset : int
        Offset between a fault label and its transient label.
    align : str
        ``"transient"`` for the first sample labeled with the transient of the
        fault, ``"steady"`` for the first labeled with its steady state,
        ``"start"`` for the first sample whatever its label.

    Returns
    -------
    pd.Timestamp or None
        ``None`` when the labels never reach the state asked for, which is the
        case of every instance that never leaves normal operation, and of every
        instance of a fault that has no transient period when the transient is
        asked for.
    """
    if align not in ALIGNMENTS:
        raise ValueError(f"unknown alignment {align!r}; expected one of {ALIGNMENTS}")
    if len(frame) == 0:
        return None
    if align == "start":
        return pd.Timestamp(frame.index[0])
    target = fault + offset if align == "transient" else fault
    hits = np.flatnonzero(column_as_float(frame, "class") == target)
    return pd.Timestamp(frame.index[hits[0]]) if len(hits) else None


def onset_from_runs(
    runs: Sequence[Segment],
    fault: int,
    offset: int = DEFAULT_TRANSIENT_OFFSET,
    align: str = "transient",
) -> pd.Timestamp | None:
    """The moment ``onset`` finds, read from the label runs the catalogue keeps.

    A run starts at the first sample carrying its label, so the first run
    labeled with the state asked for begins exactly where ``onset`` would
    point, and no file has to be opened to list the instances of a fault with
    the moment each can be aligned on.
    """
    if align not in ALIGNMENTS:
        raise ValueError(f"unknown alignment {align!r}; expected one of {ALIGNMENTS}")
    if not runs:
        return None
    if align == "start":
        return pd.Timestamp(runs[0].start)
    target = fault + offset if align == "transient" else fault
    for run in runs:
        if not np.isnan(run.value) and run.value == target:
            return pd.Timestamp(run.start)
    return None


def relative_hours(index, origin: pd.Timestamp) -> np.ndarray:
    """Every timestamp of ``index`` as hours from ``origin``, negative before it."""
    stamps = pd.DatetimeIndex(index).to_numpy(dtype="datetime64[ns]")
    return (stamps - np.datetime64(origin, "ns")) / np.timedelta64(1, "h")


def zscore(values: np.ndarray) -> np.ndarray:
    """Each reading as standard deviations from the mean of the series, missing values kept.

    The scaling is per series, over every reading it carries, which is how
    Rabelo's pipeline normalizes an instance: different wells run at different
    levels, and a model, or a reader, is after the change relative to the
    level rather than the level. A series that never moves comes out as zeros
    wherever it has a reading.
    """
    values = np.asarray(values, dtype=float)
    valid = ~np.isnan(values)
    if not valid.any():
        return values.copy()
    mean = values[valid].mean()
    std = values[valid].std()
    scaled = np.full(values.shape, np.nan)
    scaled[valid] = (values[valid] - mean) / std if std > 0 else 0.0
    return scaled


def window_mask(hours: np.ndarray, before: float, after: float) -> np.ndarray:
    """Which samples fall within ``before`` hours before the origin and ``after`` hours after it.

    A bound of zero or less means no bound on that side, so ``(0, 0)`` keeps
    every sample.
    """
    hours = np.asarray(hours, dtype=float)
    mask = np.ones(hours.shape, dtype=bool)
    if before > 0:
        mask &= hours >= -before
    if after > 0:
        mask &= hours <= after
    return mask


def plausible_extent(values: np.ndarray, bounds: tuple[float, float]) -> tuple[float, float]:
    """The smallest and largest reading inside the plausible ``bounds``, for an axis to span.

    A sensor frozen at -1.2e42 would otherwise stretch the shared axis until
    every other instance is a flat line at zero. When no reading is plausible
    the readings speak for themselves, and when there is none at all both
    bounds are NaN.
    """
    values = np.asarray(values, dtype=float)
    valid = values[~np.isnan(values)]
    if len(valid) == 0:
        return (np.nan, np.nan)
    inside = valid[(valid >= bounds[0]) & (valid <= bounds[1])]
    kept = inside if len(inside) else valid
    return (float(kept.min()), float(kept.max()))
