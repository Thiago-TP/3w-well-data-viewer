"""Tests of the dispersion pass: an even subsample of every instance, its label periods, its measurements, the pair and its density."""

import numpy as np
import pandas as pd
import pytest

from overlap_viewer.algorithms import dispersion as di

RNG = np.random.default_rng(11)
SENSORS = ["P-TPT", "T-TPT", "P-PDG"]
BOUNDS = [(0.0, 1e8), (-50.0, 250.0), (0.0, 1e8)]


def historian(n: int, every: int, level: float, amplitude: float) -> np.ndarray:
    """A series measured every ``every`` seconds and interpolated linearly between, as the PI historian does."""
    t = np.arange(0, n, every)
    signs = np.where(np.arange(len(t)) % 2 == 0, 1.0, -1.0)
    v = level + amplitude * np.sin(2 * np.pi * t / 600.0) + 0.3 * amplitude * signs
    return np.interp(np.arange(n), t, v)


def instance(n: int, start: str, level: float) -> pd.DataFrame:
    index = pd.date_range(start, periods=n, freq="1s", name="timestamp")
    labels = np.array([0] * (n // 3) + [104] * (n // 3) + [4] * (n - 2 * (n // 3)), dtype=float)
    labels[:10] = np.nan  # a few unlabeled samples at the start
    x = historian(n, 10, level, 1e5)
    # One relation for every instance whatever its level, so that pooling two
    # of them keeps it; read every second, so every sample is a measurement.
    y = 100 + 1e-4 * (x - 1e7) + RNG.normal(0, 0.5, n)
    z = np.full(n, np.nan)
    return pd.DataFrame(
        {"P-TPT": x, "T-TPT": y, "P-PDG": z, "class": pd.array(labels, dtype="Int16")}, index=index
    )


def test_the_pass_keeps_an_even_subsample_of_every_instance_with_its_periods_and_measurements():
    n = 3600
    a = instance(n, "2017-02-01", 1e7)
    b = instance(n, "2017-03-01", 1e7)  # the same level: a second recording of one relation
    refs = [
        di.InstanceRef(1, 0, 4, "a.parquet", "a", a.index[0]),
        di.InstanceRef(2, 3, 4, "b.parquet", "b", b.index[0]),
    ]
    reader = di.DispersionPass(SENSORS, BOUNDS, n_instances=2, budget=1200)
    reader.add(a, refs[0])
    reader.add(b, refs[1])
    cloud = reader.result()
    # 600 rows per instance: one in six, evenly.
    assert cloud.n == 1200 and cloud.n_samples == 2 * n and cloud.stride == pytest.approx(6.0)
    assert cloud.values.shape == (1200, 3) and cloud.values.dtype == np.float32
    assert cloud.instance.tolist() == [0] * 600 + [1] * 600
    assert cloud.well.tolist() == [1] * 600 + [2] * 600 and set(cloud.fault.tolist()) == {4}
    assert cloud.seconds[:3].tolist() == [0.0, 6.0, 12.0]
    assert cloud.timestamp(1) == a.index[0] + pd.Timedelta(seconds=6)
    assert cloud.ref(700) is refs[1]
    # The label periods: a third each, the first ten samples of each instance unlabeled.
    periods = np.bincount(cloud.period, minlength=4)
    assert periods[di.UNLABELED] == 2 * 2  # samples 0 and 6 of each instance
    assert abs(periods[di.NORMAL] - periods[di.TRANSIENT]) <= 4
    assert abs(periods[di.STEADY] - periods[di.NORMAL]) <= 4
    # The measurements: the pressure was read every 10 s, the temperature every second.
    assert cloud.genuine[:, 1].all()
    genuine_x = cloud.genuine[:, 0]
    assert 0.05 < genuine_x.mean() < 0.35  # one in ten measured, a subsample of one in six
    assert not cloud.genuine[:, 2].any()  # never recorded
    # A pair: co-valid rows only; the periods and the measurements filter.
    pair = cloud.pair("P-TPT", "T-TPT")
    assert pair.n == 1200 and pair.n_candidates == 1200
    assert cloud.pair("P-TPT", "P-PDG").n == 0
    steady = cloud.pair("P-TPT", "T-TPT", periods=[di.STEADY])
    assert steady.n == periods[di.STEADY]
    measured = cloud.pair("P-TPT", "T-TPT", genuine_only=True)
    assert measured.n == int(genuine_x.sum()) and measured.n < pair.n
    # The relation is linear, so the two agree; the density counts every row.
    assert pair.pearson() > 0.9
    counts, xedges, yedges = pair.density(bins=40)
    assert counts.shape == (40, 40) and counts.sum() == pair.n
    assert len(xedges) == 41 and xedges[0] <= pair.x.min() and xedges[-1] >= pair.x.max()
    assert yedges[0] <= pair.y.min() and yedges[-1] >= pair.y.max()
    k = di.bin_of(xedges, float(pair.x[0]))
    assert 0 <= k < 40 and xedges[k] <= pair.x[0] <= xedges[k + 1]
    assert di.bin_of(xedges, xedges[-1] + 1.0) == -1 and di.bin_of(xedges, float("nan")) == -1
    # At most so many dots, evenly.
    dots = pair.dots(limit=250)
    assert len(dots) <= 250 and dots[0] == 0 and np.all(np.diff(dots) == dots[1])
    assert len(pair.dots(limit=5000)) == pair.n


def test_implausible_readings_and_an_empty_pass():
    n = 3600
    a = instance(n, "2017-02-01", 1e7)
    ref = di.InstanceRef(1, 0, 0, "a.parquet", "a", a.index[0])
    # Readings outside the plausible range are dropped before anything else.
    hot = a.copy()
    hot["T-TPT"] = 400.0
    reader = di.DispersionPass(SENSORS, BOUNDS, 1, budget=100)
    reader.add(hot, ref)
    assert not np.isfinite(reader.result().values[:, 1]).any()
    # An empty pass is an empty cloud, and an empty pair a blank density.
    empty = di.DispersionPass(SENSORS, BOUNDS, 0).result()
    assert empty.n == 0 and empty.n_instances == 0 and np.isnan(empty.stride)
    blank = empty.pair("P-TPT", "T-TPT")
    assert blank.n == 0 and np.isnan(blank.pearson())
    counts, _, _ = blank.density(bins=10)
    assert counts.shape == (10, 10) and counts.sum() == 0
    # The period codes, one by one.
    codes = di.period_codes(np.array([np.nan, 0, 4, 104, 250, 100]), offset=100)
    assert codes.tolist() == [
        di.UNLABELED,
        di.NORMAL,
        di.STEADY,
        di.TRANSIENT,
        di.UNLABELED,
        di.UNLABELED,
    ]
