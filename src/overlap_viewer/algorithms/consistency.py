"""Whether the pressures of one recording read in the order the flow imposes. Numpy only; no Qt here.

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
    plausible_range,
)
from overlap_viewer.backend.labels import column_as_float, is_flat

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


__all__ = [
    "PRODUCTION",
    "SERVICE",
    "OrderBreak",
    "PressureOrder",
    "orders_of",
    "partners_by_sensor",
    "pressure_order_breaks",
]
