"""Whether the readings of one recording agree with each other. Numpy only; no Qt here.

Two checks, each of which no sensor can fail on its own: the pressures along
a line must read in the order the flow imposes, and the state label must be
one the valve states allow.

Fluid flows from high pressure to low, so along one line a pressure upstream
must read above one downstream: on the production line the downhole gauge
above the tree, the tree above the platform, the platform upstream of the
choke above downstream of it; on the service line, which carries the gas lift
down, the gas-lift header above the line past its choke, and the annulus at
the tree above the line at the platform. Which pairs are asked, and under
which valve states, is set in ``config`` from a survey of every real instance
of 3W 2.0.0; this module applies it to one frame.

A pair out of order says that one of the two instruments cannot be believed
(a gauge offset by some megapascals, a tag mapped to the wrong sensor), which
neither sensor shows on its own: each reading can be plausible, live and
smooth, and the two still contradict each other. Only readings that are
measurements take part: those outside the plausible range are already called
out, and a frozen sensor does not follow the process, so it is left out of
every comparison.

The operational status of the well, the ``state`` column, is defined in the
3W 2.0.0 article by the positions of the valves: an Open well has every
valve of the production path open and both crossovers closed, a Shut-In one
some valve of the path closed, and so on (``config.STATE_VALVE_RULES``). A
label the valves contradict says that either the expert's label or a valve's
tag cannot be believed; asking each state what its valves must read covers
both ways round, since valves that move under an unchanged label contradict
it. Only the valves recorded can contradict a rule, and the samples close to
a change of the label, which the experts set by hand a little before or
after the valves move, are not compared. A valve held in one position is not
frozen: it is what the well did, and it takes part.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise

import numpy as np
import pandas as pd

from overlap_viewer.backend.config import (
    PRESSURE_ORDER_MIN_SHARE,
    PRESSURE_ORDER_TOLERANCE,
    PRODUCTION_OPEN_BETWEEN,
    PRODUCTION_PRESSURES,
    SERVICE_PRESSURE_PAIRS,
    STATE_VALVE_GRACE_S,
    STATE_VALVE_MIN_SHARE,
    STATE_VALVE_RULES,
    plausible_range,
)
from overlap_viewer.backend.labels import column_as_float, is_flat, state_name

PRODUCTION = "production"
SERVICE = "service"


@dataclass(frozen=True)
class PressureOrder:
    """One pair of pressures that must read in order, and where it is asked.

    ``gates`` are the valve states and choke openings that must not read
    closed (zero) for a sample to be compared; one not recorded counts as open.
    """

    line: str
    upstream: str
    downstream: str
    gates: tuple[str, ...] = ()


@dataclass(frozen=True)
class OrderBreak:
    """How far one pair of one recording is out of order.

    ``compared`` is the samples in which both pressures carry a measurement and
    the line is open between them, ``broken`` those in which the downstream one
    reads above the upstream one by more than the tolerance, ``worst`` the
    largest such excess (Pa) and ``mask`` which samples they are.
    """

    order: PressureOrder
    compared: int
    broken: int
    worst: float
    mask: np.ndarray

    @property
    def share(self) -> float:
        return self.broken / self.compared if self.compared else 0.0

    def partner_of(self, sensor: str) -> str:
        """The other sensor of the pair."""
        order = self.order
        return order.downstream if sensor == order.upstream else order.upstream


def _measured(frame: pd.DataFrame, sensor: str) -> np.ndarray | None:
    """The plausible readings of one pressure, NaN elsewhere; ``None`` if absent or frozen."""
    if sensor not in frame.columns:
        return None
    values = column_as_float(frame, sensor)
    low, high = plausible_range("Pa")
    values = np.where((values >= low) & (values <= high), values, np.nan)
    finite = values[np.isfinite(values)]
    if len(finite) < 2 or is_flat(float(finite.min()), float(finite.max())):
        return None
    return values


def _open(frame: pd.DataFrame, gates: Sequence[str]) -> np.ndarray:
    """Where none of ``gates`` reads closed; a gate not recorded never closes the line."""
    open_ = np.ones(len(frame), dtype=bool)
    for gate in gates:
        if gate in frame.columns:
            open_ &= column_as_float(frame, gate) != 0
    return open_


def orders_of(present: Sequence[str]) -> list[PressureOrder]:
    """The pairs asked of a recording whose measured pressures are ``present``.

    On the production line each pressure is compared with the next one present
    downstream, so a missing tree still leaves the downhole gauge compared with
    the platform. The service pairs are asked as they are.
    """
    have = set(present)
    chain = [name for name in PRODUCTION_PRESSURES if name in have]
    orders = [
        PressureOrder(PRODUCTION, a, b, PRODUCTION_OPEN_BETWEEN.get(b, ()))
        for a, b in pairwise(chain)
    ]
    orders += [
        PressureOrder(SERVICE, a, b, gates)
        for a, b, gates in SERVICE_PRESSURE_PAIRS
        if a in have and b in have
    ]
    return orders


def pressure_order_breaks(
    frame: pd.DataFrame,
    tolerance: float = PRESSURE_ORDER_TOLERANCE,
    min_share: float = PRESSURE_ORDER_MIN_SHARE,
) -> list[OrderBreak]:
    """The pairs of pressures of one recording that read out of order, in the order they are asked.

    A pair counts once its downstream pressure exceeds the upstream one by more
    than ``tolerance`` (Pa) in more than ``min_share`` of the samples compared.
    """
    names = set(PRODUCTION_PRESSURES) | {n for pair in SERVICE_PRESSURE_PAIRS for n in pair[:2]}
    measured = {name: v for name in names if (v := _measured(frame, name)) is not None}
    breaks = []
    for order in orders_of(list(measured)):
        excess = measured[order.downstream] - measured[order.upstream]
        compared = np.isfinite(excess) & _open(frame, order.gates)
        n = int(compared.sum())
        if n == 0:
            continue
        mask = compared & (excess > tolerance)
        broken = int(mask.sum())
        if broken > min_share * n:
            breaks.append(OrderBreak(order, n, broken, float(excess[mask].max()), mask))
    return breaks


def partners_by_sensor(breaks: Sequence[OrderBreak]) -> dict[str, tuple[list[str], np.ndarray]]:
    """For every pressure of a broken pair, the pressures it contradicts and the samples where.

    The mask is the union over its pairs, so a sample counted against two
    partners is counted once.
    """
    out: dict[str, tuple[list[str], np.ndarray]] = {}
    for brk in breaks:
        for name in (brk.order.upstream, brk.order.downstream):
            partners, mask = out.get(name, ([], np.zeros(len(brk.mask), dtype=bool)))
            out[name] = ([*partners, brk.partner_of(name)], mask | brk.mask)
    return out


# -- The state label against the valves ---------------------------------------------

OPEN = "open"
CLOSED = "closed"


@dataclass(frozen=True)
class StateBreak:
    """How far one state of one recording is contradicted by its valves.

    ``compared`` is the samples with that label in which the valves recorded
    could contradict it and the label is not about to change or has not just
    changed, ``broken`` those in which they do and ``mask`` which
    samples they are. ``valves`` gives, per valve that contradicts the label
    somewhere, what it reads there (open or closed) and in which samples.
    """

    state: int
    compared: int
    broken: int
    mask: np.ndarray
    valves: dict[str, tuple[str, np.ndarray]]

    @property
    def share(self) -> float:
        return self.broken / self.compared if self.compared else 0.0

    @property
    def name(self) -> str:
        return state_name(float(self.state))

    def readings(self) -> str:
        """What the valves read against the label, ``ESTADO-W1 closed, ESTADO-PXO open``."""
        by_reading: dict[str, list[str]] = {}
        for valve, (reading, _mask) in self.valves.items():
            by_reading.setdefault(reading, []).append(valve)
        return ", ".join(f"{', '.join(names)} {reading}" for reading, names in by_reading.items())


def valve_positions(frame: pd.DataFrame, valve: str) -> np.ndarray:
    """1 where a valve reads open, 0 where closed, NaN where it does not say.

    A valve state is 1 open and 0 closed; 0.5, in between, says neither. A
    choke (``ABER-``) is closed at 0 % and open above it, and an opening
    outside its plausible range says nothing. A valve not recorded is all NaN.
    """
    values = column_as_float(frame, valve)
    if valve.startswith("ABER-"):
        low, high = plausible_range("%")
        plausible = (values >= low) & (values <= high)
        return np.where(plausible, (values > 0).astype(float), np.nan)
    return np.where(values == 1, 1.0, np.where(values == 0, 0.0, np.nan))


def _seconds(index: pd.Index) -> np.ndarray:
    """The instants of a frame in seconds; a frame without timestamps is taken at 1 Hz."""
    if isinstance(index, pd.DatetimeIndex):
        return index.to_numpy(dtype="datetime64[ns]").astype(np.int64) / 1e9
    return np.arange(len(index), dtype=float)


def _near_changes(labels: np.ndarray, seconds: np.ndarray, grace: float) -> np.ndarray:
    """The samples within ``grace`` seconds of a change of the label (unlabeled counts as one)."""
    coded = np.where(np.isnan(labels), -1.0, labels)
    changes = np.flatnonzero(coded[1:] != coded[:-1]) + 1
    if not len(changes) or grace <= 0:
        return np.zeros(len(labels), dtype=bool)
    at = seconds[changes]
    j = np.searchsorted(at, seconds)
    after = np.abs(at[np.clip(j, 0, len(at) - 1)] - seconds)
    before = np.abs(seconds - at[np.clip(j - 1, 0, len(at) - 1)])
    return np.minimum(after, before) <= grace


def _condition(
    positions: dict[str, np.ndarray], every: bool, wanted: str, valves: Sequence[str]
) -> tuple[np.ndarray, np.ndarray, dict[str, np.ndarray]]:
    """Where one condition could be broken, where it is, and which valves break it where.

    ``every`` asks all the valves in the ``wanted`` position, otherwise at
    least one. All of them is broken by any valve read in the other position,
    so it is tested wherever one valve says something; at least one is broken
    only when every valve is read there, each of which then breaks it, so a
    valve that says nothing leaves it untested.
    """
    want = 1.0 if wanted == OPEN else 0.0
    reads = np.stack([positions[valve] for valve in valves])
    against, says = reads == 1.0 - want, ~np.isnan(reads)
    if every:
        tested, broken = says.any(axis=0), against.any(axis=0)
        return tested, broken, {valve: against[k] for k, valve in enumerate(valves)}
    tested, broken = says.all(axis=0), against.all(axis=0)
    return tested, broken, {valve: broken for valve in valves}


def state_valve_breaks(
    frame: pd.DataFrame,
    grace: float = STATE_VALVE_GRACE_S,
    min_share: float = STATE_VALVE_MIN_SHARE,
) -> list[StateBreak]:
    """The states of one recording that its valves contradict, by state code.

    A sample is compared when its state has a rule, the valves recorded
    could contradict one of its conditions, and no change of the label lies
    within ``grace`` seconds. A
    state counts once its valves contradict it in more than ``min_share`` of
    the samples compared.
    """
    if "state" not in frame.columns or not len(frame):
        return []
    labels = column_as_float(frame, "state")
    settled = ~_near_changes(labels, _seconds(frame.index), grace)
    names = {
        valve for rules in STATE_VALVE_RULES.values() for *_, group in rules for valve in group
    }
    positions = {valve: valve_positions(frame, valve) for valve in sorted(names)}
    breaks = []
    for state, rules in STATE_VALVE_RULES.items():
        labeled = settled & (labels == state)
        if not labeled.any():
            continue
        tested = np.zeros(len(frame), dtype=bool)
        broken = np.zeros(len(frame), dtype=bool)
        against: dict[str, tuple[str, np.ndarray]] = {}
        for quantifier, wanted, valves in rules:
            could, bad, by_valve = _condition(positions, quantifier == "all", wanted, valves)
            tested |= could
            broken |= bad
            other = CLOSED if wanted == OPEN else OPEN
            for valve, mask in by_valve.items():
                against[valve] = (other, mask)
        compared = labeled & tested
        mask = labeled & broken
        n, bad = int(compared.sum()), int(mask.sum())
        if n and bad > min_share * n:
            valves = {
                valve: (reading, where & mask)
                for valve, (reading, where) in against.items()
                if (where & mask).any()
            }
            breaks.append(StateBreak(state, n, bad, mask, valves))
    return breaks


def valves_by_sensor(breaks: Sequence[StateBreak]) -> dict[str, tuple[list[str], np.ndarray]]:
    """For every valve that contradicts a label, the states it contradicts and the samples where.

    The mask is the union over its states, which never share a sample.
    """
    out: dict[str, tuple[list[str], np.ndarray]] = {}
    for brk in breaks:
        for valve, (_reading, where) in brk.valves.items():
            states, mask = out.get(valve, ([], np.zeros(len(where), dtype=bool)))
            out[valve] = ([*states, brk.name], mask | where)
    return out


__all__ = [
    "CLOSED",
    "OPEN",
    "PRODUCTION",
    "SERVICE",
    "OrderBreak",
    "PressureOrder",
    "StateBreak",
    "orders_of",
    "partners_by_sensor",
    "pressure_order_breaks",
    "state_valve_breaks",
    "valve_positions",
    "valves_by_sensor",
]
