"""Tests of the pressures along a line and of the state against the valves, on synthetic frames.

No Qt involved.
"""

import numpy as np
import pandas as pd

from overlap_viewer.algorithms.consistency import (
    PRODUCTION,
    SERVICE,
    orders_of,
    pressure_order_breaks,
    state_valve_breaks,
    valve_positions,
    valves_by_sensor,
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


# -- The state label against the valves


def well(state: float, **valves: float) -> pd.DataFrame:
    """A recording of one label throughout, timestamped at 1 Hz, with valves held as given."""
    index = pd.date_range("2020-01-01", periods=N, freq="s")
    frame = pd.DataFrame({"state": np.full(N, state)}, index=index)
    for name, value in valves.items():
        frame[name.replace("_", "-")] = np.full(N, float(value))
    return frame


OPEN_WELL = {
    "ESTADO_M1": 1,
    "ESTADO_W1": 1,
    "ESTADO_SDV_P": 1,
    "ABER_CKP": 40,
    "ESTADO_PXO": 0,
    "ESTADO_XO": 0,
}


def test_valves_as_the_article_defines_each_state_raise_nothing():
    assert state_valve_breaks(well(0, **OPEN_WELL)) == []
    assert state_valve_breaks(well(1, **{**OPEN_WELL, "ESTADO_SDV_P": 0})) == []
    flushing = {**OPEN_WELL, "ESTADO_M1": 0, "ESTADO_XO": 1}
    assert state_valve_breaks(well(2, **flushing)) == []
    assert state_valve_breaks(well(7, **OPEN_WELL)) == []
    # Depressurization: the line bled to the platform, one valve of the tree closing the well.
    assert state_valve_breaks(well(8, **{**OPEN_WELL, "ESTADO_W1": 0})) == []
    # Bullheading is not asked: no set of valve positions holds through it on 3W 2.0.0.
    assert state_valve_breaks(well(4, **{**OPEN_WELL, "ESTADO_M1": 0})) == []


def test_a_label_its_valves_contradict_is_caught_with_the_valves_that_do():
    (brk,) = state_valve_breaks(well(0, **{**OPEN_WELL, "ESTADO_W1": 0, "ESTADO_PXO": 1}))
    assert (brk.state, brk.name, brk.compared, brk.broken) == (0, "Open", N, N)
    assert set(brk.valves) == {"ESTADO-W1", "ESTADO-PXO"}
    assert brk.readings() == "ESTADO-W1 closed, ESTADO-PXO open"
    # Shut-in with every valve of the path open: each of them contradicts it.
    (brk,) = state_valve_breaks(well(1, **OPEN_WELL))
    assert set(brk.valves) == {"ESTADO-M1", "ESTADO-W1", "ESTADO-SDV-P", "ABER-CKP"}
    assert all(reading == "open" for reading, _ in brk.valves.values())
    assert valves_by_sensor([brk])["ABER-CKP"][0] == ["Shut-In"]


def test_valves_not_recorded_or_in_between_decide_nothing():
    # Open with only the crossovers recorded, closed: nothing says the path is shut.
    assert state_valve_breaks(well(0, ESTADO_PXO=0, ESTADO_XO=0)) == []
    # Shut-in with the choke not recorded: it may be the valve closed.
    shut = {k: v for k, v in OPEN_WELL.items() if k != "ABER_CKP"}
    assert state_valve_breaks(well(1, **shut)) == []
    # A valve in between, or a choke opening no instrument could read, says neither.
    assert state_valve_breaks(well(0, **{**OPEN_WELL, "ESTADO_W1": 0.5})) == []
    assert state_valve_breaks(well(1, **{**OPEN_WELL, "ABER_CKP": -99.99})) == []
    # A closed choke reads 0 %, an open one anything above.
    assert len(state_valve_breaks(well(0, **{**OPEN_WELL, "ABER_CKP": 0}))) == 1
    assert valve_positions(well(0, ABER_CKP=0.2), "ABER-CKP")[0] == 1.0
    assert state_valve_breaks(pd.DataFrame({"P-TPT": ramp(10)})) == []  # no label at all


def test_the_samples_near_a_change_of_the_label_and_a_few_strays_are_tolerated():
    frame = well(0, **OPEN_WELL)
    # The label turns Shut-In 2 minutes after the SDV closes: a hand label's lag.
    frame.loc[frame.index[500:], "ESTADO-SDV-P"] = 0.0
    frame.loc[frame.index[620:], "state"] = 1.0
    assert state_valve_breaks(frame) == []
    (brk,) = state_valve_breaks(frame, grace=0)
    assert brk.state == 0 and brk.broken == 120 and brk.mask[500:620].all()
    # Out of the grace, a blip of the wing valve of under 1 % of the samples is let go.
    frame = well(0, **OPEN_WELL)
    frame.loc[frame.index[100:105], "ESTADO-W1"] = 0.0
    assert state_valve_breaks(frame) == []
    frame.loc[frame.index[100:120], "ESTADO-W1"] = 0.0
    (brk,) = state_valve_breaks(frame)
    assert brk.broken == 20 and brk.share == 20 / N
