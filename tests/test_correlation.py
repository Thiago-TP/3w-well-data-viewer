"""Tests of the correlation matrices: Pearson exact over pooled samples, and the mutual-information coefficient."""

import numpy as np
import pandas as pd
import pytest

from overlap_viewer.algorithms import correlation as co

RNG = np.random.default_rng(5)


def frame(n: int, x: np.ndarray, y: np.ndarray, z: np.ndarray, start="2017-02-01") -> pd.DataFrame:
    index = pd.date_range(start, periods=n, freq="1s", name="timestamp")
    return pd.DataFrame(
        {"P-TPT": x, "T-TPT": y, "P-PDG": z, "QGL": np.full(n, np.nan)}, index=index
    )


def test_pearson_is_exact_over_the_pooled_samples():
    """Two instances pooled give the correlation of their union."""
    sensors = ["P-TPT", "T-TPT", "P-PDG", "QGL"]
    bounds = [(0.0, 1e8), (-50.0, 250.0), (0.0, 1e8), (0.0, 1e8)]
    n = 6000
    t = np.arange(n, dtype=float)
    signal = 1e7 + 1e5 * np.sin(2 * np.pi * t / 900)
    x = signal + RNG.normal(0, 3e4, n)
    y = 100 + 1e-4 * (signal - 1e7) + RNG.normal(0, 4.0, n)  # linear in the signal, noisy
    z = 5e6 + RNG.normal(0, 1e4, n)  # unrelated
    z[:1000] = np.nan  # partly missing
    a = frame(n, x, y, z)
    b = frame(n, x, y, z, start="2017-03-01")  # a second recording of the same relation
    accumulator = co.CorrelationPass(sensors, bounds, n_instances=2)
    accumulator.add(a)
    accumulator.add(b)
    result = accumulator.result(mutual_information=False)
    assert result.n_instances == 2
    rho = result.pearson
    assert rho.shape == (4, 4) and np.allclose(np.diag(rho)[:3], 1.0)
    assert rho[0, 1] == pytest.approx(rho[1, 0])
    # Exactly the Pearson coefficient of the pooled samples.
    assert rho[0, 1] == pytest.approx(np.corrcoef(x, y)[0, 1], abs=1e-9)
    assert abs(rho[0, 2]) < 0.05  # unrelated
    assert np.isnan(rho[0, 3]) and np.isnan(rho[3, 3])  # never recorded
    assert result.pairs[0, 2] == 2 * (n - 1000) and result.pairs[0, 1] == 2 * n
    # The caveat the help states: pooling instances recorded at different levels
    # mixes the levels into the coefficient, here lowering it.
    shifted = co.CorrelationPass(sensors, bounds, n_instances=2)
    shifted.add(a)
    shifted.add(frame(n, x + 2e5, y + 5, z, start="2017-03-01"))
    mixed = shifted.result(mutual_information=False).pearson[0, 1]
    assert mixed == pytest.approx(
        np.corrcoef(np.concatenate([x, x + 2e5]), np.concatenate([y, y + 5]))[0, 1], abs=1e-9
    )
    assert mixed < rho[0, 1]
    # The global linear coefficient (eq. 4.16) over the three sensors present.
    linear, nonlinear = result.global_coefficients()
    present = result.present()
    assert present.tolist() == [True, True, True, False]
    expected = np.sqrt((np.nansum(rho[:3, :3] ** 2) - 3) / 6)
    assert linear == pytest.approx(expected) and np.isnan(nonlinear)
    assert result.matrix("Pearson") is rho and result.matrix("Mutual information") is None
    # A pair with too few co-valid samples says nothing.
    short = co.CorrelationPass(sensors, bounds, n_instances=1)
    short.add(a.iloc[:100])
    assert np.isnan(short.result(mutual_information=False).pearson[0, 1])


def test_the_mutual_information_coefficient_sees_what_pearson_cannot():
    """A square relation has no linear correlation and a large mutual information; the nonlinear coefficient is the gap."""
    pytest.importorskip("sklearn")
    sensors = ["P-TPT", "T-TPT", "P-PDG", "QGL"]
    bounds = [(-1e8, 1e8)] * 4
    n = 4000
    x = RNG.uniform(-1, 1, n)
    y = x**2 + RNG.normal(0, 0.02, n)  # nonlinear, tight
    z = RNG.uniform(-1, 1, n)  # independent
    accumulator = co.CorrelationPass(sensors, bounds, n_instances=1, budget=3000)
    accumulator.add(frame(n, x, y, z))
    result = accumulator.result()
    assert result.mi_coefficient is not None and result.mi_samples <= 3000
    rho, mi, r = result.pearson, result.mi_coefficient, result.nonlinear
    assert abs(rho[0, 1]) < 0.1 and mi[0, 1] > 0.7 and r[0, 1] > 0.6
    assert mi[0, 2] < 0.2 and abs(rho[0, 2]) < 0.1
    assert mi[0, 0] == 1.0 and np.isnan(mi[0, 3])
    assert mi[0, 1] == pytest.approx(mi[1, 0])
    linear, nonlinear = result.global_coefficients()
    assert 0 <= linear < 0.2 and nonlinear > 0.3
    assert co.mi_coefficient(np.array([0.0]))[0] == 0.0
    assert co.mi_coefficient(np.array([10.0]))[0] == pytest.approx(1.0, abs=1e-6)
