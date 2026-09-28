"""Tests of the order of the pressures along a line, on synthetic frames. No Qt involved."""

import numpy as np
import pandas as pd

from overlap_viewer.algorithms.consistency import (
    PRODUCTION,
    SERVICE,
    orders_of,
    pressure_order_breaks,
)

N = 1000
MPA = 1e6


def ramp(level_mpa: float) -> np.ndarray:
    """A pressure around ``level_mpa`` that moves, so that it is not frozen."""
    return (level_mpa + 0.1 * np.sin(np.arange(N) / 50.0)) * MPA


def test_the_production_line_is_compared_neighbour_by_neighbour_skipping_what_is_missing():
    orders = orders_of(["P-JUS-CKP", "P-PDG", "P-MON-CKP"])
    assert [(o.line, o.upstream, o.downstream) for o in orders] == [
        (PRODUCTION, "P-PDG", "P-MON-CKP"),
        (PRODUCTION, "P-MON-CKP", "P-JUS-CKP"),
    ]
    assert orders[1].gates == ("ABER-CKP",)  # across the choke, only while it is open
    # The tree against the gas-lift choke is not asked: the survey found it inverted.
    service = orders_of(["P-TPT", "P-JUS-CKGL", "P-ANULAR"])
    assert [(o.line, o.upstream, o.downstream) for o in service] == [
        (SERVICE, "P-ANULAR", "P-JUS-CKGL")
    ]


def test_pressures_in_order_raise_nothing_and_an_offset_gauge_is_caught():
    frame = pd.DataFrame({"P-PDG": ramp(25), "P-TPT": ramp(12), "P-MON-CKP": ramp(3)})
    assert pressure_order_breaks(frame) == []

    frame["P-PDG"] = ramp(10)  # a downhole gauge 2 MPa below the tree
    (brk,) = pressure_order_breaks(frame)
    assert (brk.order.upstream, brk.order.downstream) == ("P-PDG", "P-TPT")
    assert brk.compared == N and brk.broken == N and brk.share == 1.0
    assert abs(brk.worst - 2 * MPA) < 1e-3 * MPA
    assert brk.partner_of("P-PDG") == "P-TPT" and brk.partner_of("P-TPT") == "P-PDG"


def test_a_small_gap_and_a_few_stray_samples_are_tolerated():
    frame = pd.DataFrame({"P-TPT": ramp(10), "P-MON-CKP": ramp(10.5)})  # 0.5 MPa, under 1 MPa
    assert pressure_order_breaks(frame) == []
    frame = pd.DataFrame({"P-TPT": ramp(10), "P-MON-CKP": ramp(3)})
    frame.loc[:4, "P-MON-CKP"] = 20 * MPA  # 5 samples of 1000, under 1 %
    assert pressure_order_breaks(frame) == []
    frame.loc[:19, "P-MON-CKP"] = 20 * MPA  # 20 of 1000, over 1 %
    (brk,) = pressure_order_breaks(frame)
    assert brk.broken == 20 and brk.mask[:20].all() and not brk.mask[20:].any()


def test_a_closed_valve_frozen_sensor_or_implausible_reading_is_not_compared():
    closed = pd.DataFrame(
        {
            "P-ANULAR": ramp(5),
            "P-JUS-CKGL": ramp(15),
            "ESTADO-M2": np.ones(N),
            "ESTADO-W2": np.zeros(N),  # the wing valve cuts the annulus off
        }
    )
    assert pressure_order_breaks(closed) == []
    closed["ESTADO-W2"] = 1.0
    (brk,) = pressure_order_breaks(closed)
    assert brk.order.line == SERVICE
    # Not recorded, the valves count as open.
    assert len(pressure_order_breaks(closed.drop(columns=["ESTADO-M2", "ESTADO-W2"]))) == 1

    frozen = pd.DataFrame({"P-PDG": np.full(N, 5 * MPA), "P-TPT": ramp(12)})
    assert pressure_order_breaks(frozen) == []
    garbage = pd.DataFrame(
        {"P-PDG": ramp(25), "P-TPT": np.where(np.arange(N) < 500, 2e9, ramp(12))}
    )
    assert pressure_order_breaks(garbage) == []  # 2e9 Pa is out of the plausible range
