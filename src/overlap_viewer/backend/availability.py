"""Which sensors the real instances recorded: one table, three states. No Qt here.

Every real instance carries every column the dataset declares, whether or not
the well had the sensor, so *what was recorded* is a question of its own. The
catalogue scan keeps, per instance and sensor, how many samples carry a reading
and the smallest and largest of them (``dataset.read_sensor_stats``); this
module reads those figures back and turns them into the state a sensor is in
inside one bar, and into the shares a group of bars (a fault class, a well, the
whole dataset) shows for every sensor. A bar is what the timelines draw: one
real instance or, in the joined view, one recording merged from the instances
that overlap with labels that agree, whose figures come from the data itself
(``dataset.scan_joined_sensor_stats``), since the footers cannot say which
instants two windows both record.

- **absent**: no sample carries a reading, the usual case for a sensor the
  well does not have; and, when a threshold is set, a sensor with readings in
  too small a share of the samples to count as available, which is how
  Rabelo's pipeline treats an instance whose P-TPT is more than half missing;
- **frozen**: readings, but one single value from end to end, a dead or
  disconnected instrument that a count of readings would pass off as
  available. Only analog sensors can freeze: a valve that holds one position
  for a whole recording is a fact about the well, so the enumerated variables
  (the valve states) are never frozen, only absent or live;
- **live**: readings that move.

A reading no instrument could have produced, a negative absolute pressure or a
temperature of thirty thousand degrees, is flagged apart from the three states
(``config.plausible_range``): the sample is there and it may move, so the
sensor is live, but what it says is not a measurement.

Shares are of samples, or of bars. Every sample of every bar in a group falls
into exactly one state, missing samples being absent, so the three sample
shares of a cell add up to one and a partially recorded sensor shows as partly
absent; the bar shares count how many of the group's bars have the sensor in
each state. A sample two overlapping instances share is counted in both, unless
the bars are the joined view's, where it is counted once.

A **live** sample is not necessarily a **measurement**. Most sensors of the
dataset were read every ten seconds or every two minutes and the historian
drew straight lines between the readings (``algorithms.interpolation``), so,
given the profiles of the bars (``profiles.Profiles``), the live share of a
cell is split further into the samples that were measured and the samples the
historian filled in, and a bar can be tinted by the share of its live samples
that are measurements.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from overlap_viewer.backend.config import plausible_range
from overlap_viewer.backend.dataset import (
    BarStats,
    DatasetInfo,
    JoinedStats,
    WellData,
    instance_title,
    split_wells,
)
from overlap_viewer.backend.labels import is_flat, sensor_stats_from_json
from overlap_viewer.backend.profiles import Profiles

# The states a sensor can be in inside one bar, and their codes.
STATES = ("absent", "frozen", "live")
ABSENT, FROZEN, LIVE = range(3)

# What one sensor of one bar amounts to: readings, smallest, largest.
SensorStats = tuple[int, float, float]

# What ``Availability.bars`` says about every bar. ``file`` names the instance
# behind a bar of the plain view and is empty for a merged recording, which is
# how the pair counts, keyed by file, find their bar.
BAR_COLUMNS = [
    "well",
    "bar",
    "title",
    "file",
    "fault_class",
    "reach",
    "start",
    "end",
    "hours",
    "n_samples",
    "members",
]


def sensor_state(
    n_valid: int,
    n_total: int,
    low: float,
    high: float,
    enumerated: bool = False,
    threshold: float = 0.0,
) -> int:
    """The state of one sensor inside one bar: ``ABSENT``, ``FROZEN`` or ``LIVE``.

    A sensor with readings in less than ``threshold`` of the samples counts as
    absent: not available, in the sense a cleaning rule gives the word. Frozen
    is judged by ``labels.is_flat``, the rule the instance window marks a plot
    *flat* by, so the two never disagree about a sensor. An enumerated variable
    is never frozen.
    """
    if n_valid <= 0 or (threshold > 0 and n_valid < threshold * n_total):
        return ABSENT
    if not enumerated and is_flat(low, high):
        return FROZEN
    return LIVE


def outside_range(low: float, high: float, bounds: tuple[float, float]) -> bool:
    """Whether readings spanning ``low`` to ``high`` leave the plausible ``bounds``."""
    if np.isnan(low) or np.isnan(high):
        return False
    return bool(low < bounds[0] or high > bounds[1])


def implausible_sensors(stats: Mapping[str, SensorStats], info: DatasetInfo) -> list[str]:
    """The sensors of one bar whose readings leave the plausible range, in the order given."""
    return [
        name
        for name, (n, low, high) in stats.items()
        if n > 0 and outside_range(low, high, plausible_range(info.unit(name)))
    ]


@dataclass(frozen=True)
class AvailabilityTable:
    """What a set of groups of bars recorded of every sensor, one row per group.

    Attributes
    ----------
    keys : list
        What each row stands for, in row order.
    sensors : list[str]
        The columns, in column order.
    n_instances, n_samples : np.ndarray
        Per row, how many bars the group holds and how many samples they
        carry between them.
    samples : np.ndarray
        ``(rows, sensors, 3)``: how many samples of the group are absent,
        frozen and live for each sensor (indexed by ``ABSENT``, ``FROZEN``,
        ``LIVE``). The three add up to ``n_samples``.
    instances : np.ndarray
        ``(rows, sensors, 3)``: how many bars of the group have the sensor in
        each state.
    implausible : np.ndarray
        ``(rows, sensors)``: how many bars of the group have a reading of the
        sensor outside its plausible range.
    low, high : np.ndarray
        ``(rows, sensors)``: the smallest and largest reading of the sensor in
        the group, NaN where nothing was recorded.
    genuine, filled : np.ndarray or None
        ``(rows, sensors)``: of the live samples of the group, how many are
        measurements and how many the historian filled in; ``None`` when the
        bars were built without their profiles.
    out_of_order : np.ndarray or None
        ``(rows, sensors)``: how many bars of the group have the pressure read
        out of order with another of its line; ``None`` without the profiles.
    order_partners : np.ndarray or None
        ``(rows, sensors)``, objects: the pressures it contradicts in the group,
        as a sorted tuple.
    """

    keys: list
    sensors: list[str]
    n_instances: np.ndarray
    n_samples: np.ndarray
    samples: np.ndarray
    instances: np.ndarray
    implausible: np.ndarray
    low: np.ndarray
    high: np.ndarray
    genuine: np.ndarray | None = None
    filled: np.ndarray | None = None
    out_of_order: np.ndarray | None = None
    order_partners: np.ndarray | None = None

    @staticmethod
    def _shares(counts: np.ndarray, totals: np.ndarray) -> np.ndarray:
        totals = totals[:, None, None].astype(float)
        with np.errstate(divide="ignore", invalid="ignore"):
            return np.where(totals > 0, counts / np.where(totals > 0, totals, 1.0), 0.0)

    @property
    def shares(self) -> np.ndarray:
        """``samples`` as shares of the group's samples, zero for an empty group."""
        return self._shares(self.samples, self.n_samples)

    @property
    def instance_shares(self) -> np.ndarray:
        """``instances`` as shares of the group's bars, zero for an empty group."""
        return self._shares(self.instances, self.n_instances)

    @property
    def measured(self) -> bool:
        """Whether the live share can be split into measurements and filled samples."""
        return self.genuine is not None and self.filled is not None

    @property
    def filled_shares(self) -> np.ndarray:
        """The samples the historian filled in, as shares of the group's samples; zeros when unknown."""
        if not self.measured:
            return np.zeros(self.samples.shape[:2])
        totals = self.n_samples[:, None].astype(float)
        with np.errstate(divide="ignore", invalid="ignore"):
            return np.where(totals > 0, self.filled / np.where(totals > 0, totals, 1.0), 0.0)

    def measured_share(self, row: int, column: int) -> float:
        """Of the live samples of one cell, the share that are measurements; NaN when unknown or none."""
        if not self.measured:
            return float("nan")
        genuine, filled = float(self.genuine[row, column]), float(self.filled[row, column])
        return genuine / (genuine + filled) if genuine + filled > 0 else float("nan")

    def spacing_s(self, row: int, column: int) -> float:
        """Seconds of live signal per measurement in one cell: how far apart the measurements are."""
        if not self.measured or self.genuine[row, column] <= 0:
            return float("nan")
        return float(self.samples[row, column, LIVE]) / float(self.genuine[row, column])

    def coverage_order(self, by_instances: bool = False) -> list[int]:
        """Column positions by the live share over every row, highest first, then dataset order."""
        counts = self.instances if by_instances else self.samples
        totals = self.n_instances if by_instances else self.n_samples
        live = counts[:, :, LIVE].sum(axis=0).astype(float)
        total = float(totals.sum())
        share = live / total if total > 0 else live
        return sorted(range(len(self.sensors)), key=lambda j: (-share[j], j))

    def with_columns(self, order: Sequence[int]) -> "AvailabilityTable":
        """The same table with its columns in ``order``."""
        order = list(order)
        return AvailabilityTable(
            self.keys,
            [self.sensors[j] for j in order],
            self.n_instances,
            self.n_samples,
            self.samples[:, order],
            self.instances[:, order],
            self.implausible[:, order],
            self.low[:, order],
            self.high[:, order],
            None if self.genuine is None else self.genuine[:, order],
            None if self.filled is None else self.filled[:, order],
            None if self.out_of_order is None else self.out_of_order[:, order],
            None if self.order_partners is None else self.order_partners[:, order],
        )

    def stacked(self, other: "AvailabilityTable") -> "AvailabilityTable":
        """This table with the rows of ``other`` appended, e.g. a total row."""
        if other.sensors != self.sensors:
            raise ValueError("the two tables do not share their sensors")
        both = self.measured and other.measured
        ordered = self.out_of_order is not None and other.out_of_order is not None
        return AvailabilityTable(
            [*self.keys, *other.keys],
            self.sensors,
            np.concatenate([self.n_instances, other.n_instances]),
            np.concatenate([self.n_samples, other.n_samples]),
            np.concatenate([self.samples, other.samples]),
            np.concatenate([self.instances, other.instances]),
            np.concatenate([self.implausible, other.implausible]),
            np.concatenate([self.low, other.low]),
            np.concatenate([self.high, other.high]),
            np.concatenate([self.genuine, other.genuine]) if both else None,
            np.concatenate([self.filled, other.filled]) if both else None,
            np.concatenate([self.out_of_order, other.out_of_order]) if ordered else None,
            np.concatenate([self.order_partners, other.order_partners]) if ordered else None,
        )

    def __len__(self) -> int:
        return len(self.keys)


@dataclass(frozen=True)
class Availability:
    """What every bar of a set of wells recorded of every sensor.

    Built once per catalogue (and once more for the joined view, and again when
    the threshold changes) from the sensor figures the scan kept; the rows are
    the bars of the views given, well after well and bar after bar, and
    ``grouped`` folds them into the table a page draws.

    Attributes
    ----------
    bars : pd.DataFrame
        One row per bar, ``BAR_COLUMNS``: its well and its position in that
        well's view, its title, fault class and reach, time span, hours,
        samples, and the positions of the instances behind it in the well's
        own instance table.
    sensors : list[str]
        Every sensor, in dataset order, followed by any the files carry that
        the dataset does not declare.
    sensor_units : list[str]
        Unit per sensor, empty when it has none.
    ranges : list[(float, float)]
        Plausible range per sensor.
    threshold : float
        The share of samples a sensor needs readings in to count as available.
    n_total : np.ndarray
        Samples per bar.
    n_valid, low, high : np.ndarray
        ``(bars, sensors)``: readings, smallest and largest, per sensor.
    state : np.ndarray
        ``(bars, sensors)``: ``ABSENT``, ``FROZEN`` or ``LIVE``.
    implausible : np.ndarray
        ``(bars, sensors)``: whether a reading leaves the plausible range.
    genuine, filled : np.ndarray or None
        ``(bars, sensors)``: how many readings of the sensor are measurements
        and how many the historian filled in, from the bars' profiles; ``None``
        when the bars were built without them.
    out_of_order : np.ndarray or None
        ``(bars, sensors)``: the samples in which the pressure reads out of
        order with another of its line (``algorithms.consistency``), from the
        profiles, which read every sample; ``None`` without them.
    order_partners : np.ndarray or None
        ``(bars, sensors)``, objects: the pressures it contradicts, a tuple.
    """

    bars: pd.DataFrame
    sensors: list[str]
    sensor_units: list[str]
    ranges: list[tuple[float, float]]
    threshold: float
    n_total: np.ndarray
    n_valid: np.ndarray
    low: np.ndarray
    high: np.ndarray
    state: np.ndarray
    implausible: np.ndarray
    genuine: np.ndarray | None = None
    filled: np.ndarray | None = None
    out_of_order: np.ndarray | None = None
    order_partners: np.ndarray | None = None
    _index: dict = field(default_factory=dict, repr=False, compare=False)

    def __post_init__(self) -> None:
        self._index.update(
            {
                (int(well), int(bar)): i
                for i, (well, bar) in enumerate(zip(self.bars["well"], self.bars["bar"]))
            }
        )

    @classmethod
    def from_wells(
        cls,
        views: Sequence[WellData],
        info: DatasetInfo,
        threshold: float = 0.0,
        joined_stats: JoinedStats | None = None,
        profiles: Profiles | None = None,
    ) -> "Availability":
        """Read the sensor figures of every bar of the ``views`` into arrays.

        Parameters
        ----------
        views : sequence of WellData
            The wells, instance by instance, or their joined views.
        info : DatasetInfo
            For the sensors the dataset declares, their units and which are
            enumerated.
        threshold : float
            Share of samples a sensor needs readings in to count as available.
        joined_stats : JoinedStats, optional
            The merged figures of every bar of a joined view, from
            ``dataset.load_joined_sensor_stats``; required for joined views.
        profiles : Profiles, optional
            The profiles of the bars (``profiles.load_profiles``), which split
            the readings of a live sensor into measurements and filled samples
            and say which pressures read out of order.
        """
        records: list[dict] = []
        parsed: list[Mapping[str, SensorStats]] = []
        totals: list[int] = []
        keys: list[tuple] = []
        joined = any(view.joined_view for view in views)
        for view in views:
            rows = view.rows
            has_stats = "sensor_stats" in rows.columns
            for bar in range(len(rows)):
                row = rows.iloc[bar]
                if view.joined_view:
                    if joined_stats is None or (view.well, bar) not in joined_stats:
                        raise ValueError(f"no merged sensor figures for bar {bar} of {view.label}")
                    merged = joined_stats[(view.well, bar)]
                    n_total, stats = merged.n_samples, merged.sensors
                else:
                    n_total = int(row["n_samples"])
                    stats = sensor_stats_from_json(str(row["sensor_stats"])) if has_stats else {}
                parsed.append(stats)
                totals.append(int(n_total))
                keys.append(
                    (view.well, bar)
                    if view.joined_view
                    else (int(row["fault_class"]), str(row.get("file", "")))
                )
                records.append(
                    {
                        "well": view.well,
                        "bar": bar,
                        "title": instance_title(row),
                        "file": str(row.get("file", "")),
                        "fault_class": int(row["fault_class"]),
                        "reach": str(row["reach"]),
                        "start": pd.Timestamp(row["start"]),
                        "end": pd.Timestamp(row["end"]),
                        "hours": float(row["hours"]),
                        "n_samples": int(n_total),
                        "members": list(view.members[bar]),
                    }
                )
        bars = pd.DataFrame(records, columns=BAR_COLUMNS)
        declared = list(info.sensor_names)
        extra = sorted({name for stats in parsed for name in stats} - set(declared))
        sensors = declared + extra
        units = [info.unit(name) for name in sensors]
        ranges = [plausible_range(unit) for unit in units]
        enumerated = [info.is_enumerated(name) for name in sensors]

        n, s = len(parsed), len(sensors)
        n_total = np.asarray(totals, dtype=int)
        n_valid = np.zeros((n, s), dtype=int)
        low = np.full((n, s), np.nan)
        high = np.full((n, s), np.nan)
        for i, stats in enumerate(parsed):
            for j, name in enumerate(sensors):
                if name in stats:
                    n_valid[i, j], low[i, j], high[i, j] = stats[name]
        state = np.full((n, s), ABSENT, dtype=np.int8)
        implausible = np.zeros((n, s), dtype=bool)
        for j in range(s):
            for i in range(n):
                state[i, j] = sensor_state(
                    n_valid[i, j], n_total[i], low[i, j], high[i, j], enumerated[j], threshold
                )
                implausible[i, j] = n_valid[i, j] > 0 and outside_range(
                    low[i, j], high[i, j], ranges[j]
                )
        genuine = filled = out_of_order = order_partners = None
        if profiles is not None:
            out_of_order = np.nan_to_num(
                profiles.matrix(keys, joined, "n_out_of_order", sensors), nan=0.0
            ).astype(int)
            order_partners = np.empty((n, s), dtype=object)
            order_partners.fill(())
            for i, j in zip(*np.nonzero(out_of_order)):
                order_partners[i, j] = tuple(profiles.order_partners(keys[i], sensors[j], joined))
            genuine = np.nan_to_num(
                profiles.matrix(keys, joined, "n_genuine", sensors), nan=0.0
            ).astype(int)
            filled = np.nan_to_num(
                profiles.matrix(keys, joined, "n_interpolated", sensors)
                + profiles.matrix(keys, joined, "n_held", sensors),
                nan=0.0,
            ).astype(int)
        return cls(
            bars,
            sensors,
            units,
            ranges,
            threshold,
            n_total,
            n_valid,
            low,
            high,
            state,
            implausible,
            genuine,
            filled,
            out_of_order,
            order_partners,
        )

    @classmethod
    def from_catalogue(
        cls, catalogue: pd.DataFrame, info: DatasetInfo, threshold: float = 0.0
    ) -> "Availability":
        """The bars of a catalogue, instance by instance."""
        return cls.from_wells(split_wells(catalogue), info, threshold)

    @property
    def n_bars(self) -> int:
        return len(self.n_total)

    @property
    def joined(self) -> bool:
        """Whether the bars are merged recordings rather than the instances themselves."""
        return bool(len(self.bars)) and any(len(members) > 1 for members in self.bars["members"])

    @property
    def measured(self) -> bool:
        """Whether the bars carry their profiles, so live readings split into measured and filled."""
        return self.genuine is not None and self.filled is not None

    def index_of(self, well: int, bar: int) -> int:
        """The row of one bar of one well's view."""
        return self._index[(int(well), int(bar))]

    def measured_of(self, rows: Sequence[int], sensor: int) -> tuple[float, float]:
        """Of one sensor's live readings over some bars, the share measured, and the seconds per measurement.

        What tints a timeline bar by how a sensor was measured. Both are NaN
        without profiles, or where the sensor is live in none of the bars.
        """
        if not self.measured:
            return (float("nan"), float("nan"))
        rows = np.asarray(list(rows), dtype=int)
        live = self.state[rows, sensor] == LIVE
        genuine = float(self.genuine[rows, sensor][live].sum())
        filled = float(self.filled[rows, sensor][live].sum())
        if genuine + filled <= 0:
            return (float("nan"), float("nan"))
        share = genuine / (genuine + filled)
        spacing = float(self.n_valid[rows, sensor][live].sum()) / genuine if genuine else np.nan
        return (share, spacing)

    def shares_of(self, rows: Sequence[int], sensor: int) -> tuple[np.ndarray, bool]:
        """The sample shares of one sensor over some bars, and whether any of them reads implausibly.

        What colors a timeline bar by one sensor: the bar's own row, or the
        rows of the instances behind a joined bar.
        """
        rows = np.asarray(list(rows), dtype=int)
        shares = np.zeros(3)
        total = float(self.n_total[rows].sum())
        if total > 0:
            valid = self.n_valid[rows, sensor]
            state = self.state[rows, sensor]
            shares[LIVE] = valid[state == LIVE].sum() / total
            shares[FROZEN] = valid[state == FROZEN].sum() / total
            shares[ABSENT] = 1.0 - shares[LIVE] - shares[FROZEN]
        return shares, bool(self.implausible[rows, sensor].any())

    def implausible_any(self, rows: Sequence[int]) -> bool:
        """Whether any sensor of any of these bars reads outside its plausible range."""
        return bool(self.implausible[np.asarray(list(rows), dtype=int)].any())

    def order_any(self, rows: Sequence[int], sensor: int | None = None) -> bool:
        """Whether a pressure of any of these bars (or ``sensor`` alone) reads out of order."""
        if self.out_of_order is None:
            return False
        block = self.out_of_order[np.asarray(list(rows), dtype=int)]
        return bool((block if sensor is None else block[:, sensor]).any())

    def out_of_order_pairs(self, rows: Sequence[int]) -> list[tuple[str, str]]:
        """The pairs of pressures read out of order in any of these bars, each once, in sensor order."""
        if self.out_of_order is None:
            return []
        pairs: list[tuple[str, str]] = []
        for i in np.asarray(list(rows), dtype=int):
            for j in np.flatnonzero(self.out_of_order[i]):
                for other in self.order_partners[i, j]:
                    pair = tuple(sorted((self.sensors[j], other)))
                    if pair not in pairs:
                        pairs.append(pair)
        return pairs

    def grouped(
        self, keys: Sequence, order: Sequence | None = None, mask: np.ndarray | None = None
    ) -> AvailabilityTable:
        """Fold the bars into one row per distinct key.

        Parameters
        ----------
        keys : sequence
            One key per bar: its fault class, its well, its own position for
            one row per bar, a constant for a single total row.
        order : sequence, optional
            The keys to make rows of, in row order; the default is every
            distinct key of the bars taken, sorted.
        mask : np.ndarray, optional
            Which bars to take (boolean, one per bar); the default takes all.
        """
        keys = np.asarray(list(keys), dtype=object)
        taken = np.ones(self.n_bars, dtype=bool) if mask is None else np.asarray(mask, bool)
        rows = list(order) if order is not None else sorted(set(keys[taken].tolist()))
        r, s = len(rows), len(self.sensors)
        n_instances = np.zeros(r, dtype=int)
        n_samples = np.zeros(r, dtype=int)
        samples = np.zeros((r, s, 3), dtype=int)
        instances = np.zeros((r, s, 3), dtype=int)
        implausible = np.zeros((r, s), dtype=int)
        low = np.full((r, s), np.nan)
        high = np.full((r, s), np.nan)
        measured = self.measured
        genuine = np.zeros((r, s), dtype=int) if measured else None
        filled = np.zeros((r, s), dtype=int) if measured else None
        ordered = self.out_of_order is not None
        out_of_order = np.zeros((r, s), dtype=int) if ordered else None
        order_partners = np.empty((r, s), dtype=object) if ordered else None
        if ordered:
            order_partners.fill(())
        for k, key in enumerate(rows):
            members = np.flatnonzero(taken & (keys == key))
            if not len(members):
                continue
            n_instances[k] = len(members)
            n_samples[k] = int(self.n_total[members].sum())
            state = self.state[members]
            valid = self.n_valid[members]
            samples[k, :, FROZEN] = np.where(state == FROZEN, valid, 0).sum(axis=0)
            samples[k, :, LIVE] = np.where(state == LIVE, valid, 0).sum(axis=0)
            if measured:
                # Only a live sensor has measurements to split: a frozen one is
                # one value throughout, and counts as frozen, not as filled.
                genuine[k] = np.where(state == LIVE, self.genuine[members], 0).sum(axis=0)
                filled[k] = np.where(state == LIVE, self.filled[members], 0).sum(axis=0)
            # Whatever is neither is absent: the missing samples, and the
            # readings of a sensor too sparse to count as available.
            samples[k, :, ABSENT] = n_samples[k] - samples[k, :, FROZEN] - samples[k, :, LIVE]
            for code in (ABSENT, FROZEN, LIVE):
                instances[k, :, code] = (state == code).sum(axis=0)
            implausible[k] = self.implausible[members].sum(axis=0)
            if ordered:
                broken = self.out_of_order[members] > 0
                out_of_order[k] = broken.sum(axis=0)
                for j in np.flatnonzero(out_of_order[k]):
                    order_partners[k, j] = tuple(
                        sorted(
                            {p for i in members[broken[:, j]] for p in self.order_partners[i, j]}
                        )
                    )
            # The bounds of a sensor nobody recorded stay NaN, without the
            # warning ``nanmin`` raises over an all-NaN column.
            lows = np.where(np.isnan(self.low[members]), np.inf, self.low[members]).min(axis=0)
            highs = np.where(np.isnan(self.high[members]), -np.inf, self.high[members]).max(axis=0)
            low[k] = np.where(np.isinf(lows), np.nan, lows)
            high[k] = np.where(np.isinf(highs), np.nan, highs)
        return AvailabilityTable(
            rows,
            list(self.sensors),
            n_instances,
            n_samples,
            samples,
            instances,
            implausible,
            low,
            high,
            genuine,
            filled,
            out_of_order,
            order_partners,
        )

    def total(self, key="all", mask: np.ndarray | None = None) -> AvailabilityTable:
        """One row folding every bar taken."""
        return self.grouped([key] * self.n_bars, order=[key], mask=mask)


@dataclass(frozen=True)
class PairTable:
    """How often two sensors carry a reading at the same instant, over one set of bars.

    Rabelo's figure 2.10: the share of the samples in which both sensors of a
    pair have a valid reading. A pair with little coverage is a pair no model
    can lean on and a correlation nobody should trust, whatever each sensor's
    own coverage says: two sensors can each cover half a recording and never
    overlap.

    Attributes
    ----------
    sensors : list[str]
        The sensors, in the order of both axes of the square matrix.
    n_bars, n_samples : int
        How many bars the scope holds and how many samples they carry.
    samples : np.ndarray
        ``(sensors, sensors)``: samples carrying both, symmetric; the diagonal
        is the sensor's own count.
    bars : np.ndarray
        ``(sensors, sensors)``: how many bars of the scope carry both at all.
    live_only : bool
        Whether a sensor had to be live in a bar for that bar to count (see
        ``PairCoverage.table``).
    """

    sensors: list[str]
    n_bars: int
    n_samples: int
    samples: np.ndarray
    bars: np.ndarray
    live_only: bool

    @property
    def shares(self) -> np.ndarray:
        """``samples`` as shares of the scope's samples, zero for an empty scope."""
        if self.n_samples <= 0:
            return np.zeros(self.samples.shape, dtype=float)
        return self.samples / float(self.n_samples)

    def coverage_order(self) -> list[int]:
        """Sensor positions by their own coverage, the diagonal, highest first."""
        own = np.diag(self.samples).astype(float)
        return sorted(range(len(self.sensors)), key=lambda j: (-own[j], j))

    def grouped_order(self) -> list[int]:
        """Sensor positions laid out so that the sensors recorded together sit together.

        Ordered by coverage the matrix ranks its sensors; ordered like this it
        shows its blocks: the sets of sensors a well carries or lacks
        together, which is what says which subsets of the dataset a model could
        be built on at all.

        The order is the classic spectral seriation. Sensors are related by the
        share of the scarcer one's samples that carry both, which is 1 for two
        sensors that always appear together and 0 for two that never do; the
        second eigenvector of the Laplacian of that similarity (the Fiedler
        vector) lays them on a line, and sorting by it puts strongly related
        sensors near one another. Sensors nothing recorded are related to
        nothing and go last, in dataset order.
        """
        own = np.diag(self.samples).astype(float)
        present = [j for j in range(len(self.sensors)) if own[j] > 0]
        missing = [j for j in range(len(self.sensors)) if own[j] <= 0]
        if len(present) < 3:
            return present + missing
        block = self.samples[np.ix_(present, present)].astype(float)
        scarcer = np.minimum(own[present][:, None], own[present][None, :])
        similarity = np.divide(block, scarcer, out=np.zeros_like(block), where=scarcer > 0)
        np.fill_diagonal(similarity, 0.0)
        laplacian = np.diag(similarity.sum(axis=1)) - similarity
        fiedler = np.linalg.eigh(laplacian)[1][:, 1]
        # The sign of an eigenvector is arbitrary, so the best covered sensor is
        # put on the near side of the line and the order is the same every time.
        if fiedler[int(np.argmax(own[present]))] > 0:
            fiedler = -fiedler
        order = sorted(range(len(present)), key=lambda k: (fiedler[k], -own[present][k]))
        return [present[k] for k in order] + missing

    def with_order(self, order: Sequence[int]) -> "PairTable":
        """The same table with its sensors, and so both axes, in ``order``."""
        order = list(order)
        grid = np.ix_(order, order)
        return PairTable(
            [self.sensors[j] for j in order],
            self.n_bars,
            self.n_samples,
            self.samples[grid],
            self.bars[grid],
            self.live_only,
        )


@dataclass(frozen=True)
class PairCoverage:
    """The co-valid sample counts of every pair of sensors, bar by bar.

    Built once from the counts the pair scan reads out of the files
    (``dataset.load_pair_counts``) and folded into a ``PairTable`` over
    whatever scope a page asks for. Only the upper triangle is held, the
    matrix being symmetric.

    Attributes
    ----------
    sensors : list[str]
        The sensors the counts are in the order of.
    counts : np.ndarray
        ``(bars, pairs)``: samples carrying both sensors of the pair.
    rows, cols : np.ndarray
        ``(pairs,)``: which two sensors each column of ``counts`` belongs to.
    """

    sensors: list[str]
    counts: np.ndarray
    rows: np.ndarray
    cols: np.ndarray

    @classmethod
    def from_counts(
        cls, availability: Availability, counts: Mapping[tuple[int, str], np.ndarray]
    ) -> "PairCoverage":
        """Line the scanned counts up with the bars of ``availability``, by fault folder and file.

        A merged recording has no file of its own and carries no counts: the
        pair map is about the instances as the dataset stores them.
        """
        n = len(availability.sensors)
        rows, cols = np.triu_indices(n, 0)
        table = np.zeros((availability.n_bars, len(rows)), dtype=np.int64)
        bars = availability.bars
        for i, (fault_class, file) in enumerate(zip(bars["fault_class"], bars["file"])):
            found = counts.get((int(fault_class), str(file)))
            if found is not None:
                table[i] = found
        return cls(list(availability.sensors), table, rows, cols)

    @classmethod
    def from_joined(cls, availability: Availability, joined: JoinedStats) -> "PairCoverage":
        """The counts of the merged recordings, lined up with the bars of a joined view.

        Joining changes the answer rather than merely the arithmetic: a sensor
        one window did not record may be there in the window it overlaps, so
        two sensors that never share a sample inside one window can share
        plenty inside the recording the windows were cut from.
        """
        n = len(availability.sensors)
        rows, cols = np.triu_indices(n, 0)
        table = np.zeros((availability.n_bars, len(rows)), dtype=np.int64)
        bars = availability.bars
        for i, (well, bar) in enumerate(zip(bars["well"], bars["bar"])):
            found = joined.get((int(well), int(bar)))
            if found is not None:
                table[i] = found.pairs
        return cls(list(availability.sensors), table, rows, cols)

    def table(
        self,
        availability: Availability,
        mask: np.ndarray | None = None,
        live_only: bool = True,
    ) -> PairTable:
        """Fold the bars taken into one square matrix.

        Parameters
        ----------
        availability : Availability
            The bars the counts were lined up with; its states decide which
            bars a pair may count in.
        mask : np.ndarray, optional
            Which bars to take (boolean, one per bar); the default takes all.
        live_only : bool
            When set, a bar counts for a pair only if both sensors are *live*
            in it, so that a dead instrument and a sensor below the
            availability threshold contribute nothing: the page's own
            vocabulary. Unset, every sample carrying both readings counts,
            which is how Rabelo counts.
        """
        taken = np.ones(len(self.counts), dtype=bool) if mask is None else np.asarray(mask, bool)
        counts = self.counts[taken]
        if live_only:
            live = availability.state[taken] == LIVE
            counts = np.where(live[:, self.rows] & live[:, self.cols], counts, 0)
        n = len(self.sensors)
        samples = np.zeros((n, n), dtype=np.int64)
        bars = np.zeros((n, n), dtype=np.int64)
        samples[self.rows, self.cols] = counts.sum(axis=0)
        bars[self.rows, self.cols] = (counts > 0).sum(axis=0)
        samples[self.cols, self.rows] = samples[self.rows, self.cols]
        bars[self.cols, self.rows] = bars[self.rows, self.cols]
        return PairTable(
            list(self.sensors),
            int(taken.sum()),
            int(availability.n_total[taken].sum()),
            samples,
            bars,
            live_only,
        )


__all__ = [
    "ABSENT",
    "BAR_COLUMNS",
    "FROZEN",
    "LIVE",
    "STATES",
    "Availability",
    "AvailabilityTable",
    "BarStats",
    "JoinedStats",
    "PairCoverage",
    "PairTable",
    "SensorStats",
    "implausible_sensors",
    "outside_range",
    "sensor_state",
]
