"""Tests of the windows of a well: the four rules of the division and what every window amounts to. No Qt involved."""

import numpy as np
import pandas as pd
import pytest

from overlap_viewer.algorithms import windows as wi
from overlap_viewer.algorithms.descriptors import describe

RNG = np.random.default_rng(5)


def frame(start: str, labels, values=None) -> pd.DataFrame:
    labels = np.asarray(labels, dtype=float)
    n = len(labels)
    index = pd.date_range(start, periods=n, freq="1s", name="timestamp")
    values = np.arange(n, dtype=float) if values is None else np.asarray(values, dtype=float)
    return pd.DataFrame(
        {
            "P-TPT": values,
            "class": pd.array(np.where(np.isnan(labels), pd.NA, labels), dtype="Int16"),
        },
        index=index,
    )


def ref(position: int, fault: int = 1) -> wi.InstanceRef:
    return wi.InstanceRef(position, fault, f"i{position}.parquet", f"i{position}")


def test_cut_gives_every_run_windows_of_its_own_padding_its_last():
    labels = np.array([0.0] * 10 + [101.0] * 3 + [np.nan] * 5 + [1.0] * 8)
    first, n_valid, code = wi.cut(labels, 4)
    # Normal: 4 + 4 + 2; transient: 3; unlabeled: 4 + 1; steady: 4 + 4.
    assert first.tolist() == [0, 4, 8, 10, 13, 17, 18, 22]
    assert n_valid.tolist() == [4, 4, 2, 3, 4, 1, 4, 4]
    assert code.tolist() == [0, 0, 0, 101, -1, -1, 1, 1]
    # Every sample is in exactly one window, and every window in one run.
    covered = np.concatenate([np.arange(f, f + v) for f, v in zip(first, n_valid)])
    assert covered.tolist() == list(range(len(labels)))
    for f, v, c in zip(first, n_valid, code):
        assert set(wi.label_codes(labels[f : f + v]).tolist()) == {c}


def test_cut_leaves_out_what_is_not_kept_and_never_crosses_an_instance():
    labels = np.zeros(12)
    keep = np.ones(12, dtype=bool)
    keep[:3] = False
    first, n_valid, _ = wi.cut(labels, 5, keep, bounds=[8])
    # Samples 3..7 are one instance's normal run, 8..11 the next one's.
    assert first.tolist() == [3, 8] and n_valid.tolist() == [5, 4]
    assert wi.cut(np.zeros(0), 5)[0].size == 0
    assert wi.cut(np.zeros(4), 5, np.zeros(4, dtype=bool))[0].size == 0
    with pytest.raises(ValueError):
        wi.cut(labels, 0)


def test_the_windows_of_a_well_hold_size_values_one_label_and_no_repeated_instant():
    a = frame("2017-02-01 00:00:00", [np.nan] * 5 + [0] * 20 + [104] * 7)
    # The second instance starts 10 s before the first ends: its head repeats it.
    b = frame("2017-02-01 00:00:22", [np.nan] * 10 + [4] * 30, values=np.full(40, 7.0))
    reader = wi.SeriesPass("P-TPT")
    reader.add(b, ref(1, 4))  # handed out of order: the pass sorts them
    reader.add(a, ref(0, 4))
    series = reader.result()
    assert [r.position for r in series.refs] == [0, 1]
    assert series.offsets.tolist() == [0, 32, 72]
    assert series.n_repeated == 10 and series.repeated[32:42].all()

    w = series.windows(8)
    assert w.values.shape == (len(w), 8)
    # Instance 0: unlabeled 5, normal 8 + 8 + 4, transient 7; instance 1: steady 8 * 3 + 6.
    assert w.n_valid.tolist() == [5, 8, 8, 4, 7, 8, 8, 8, 6]
    assert w.instance.tolist() == [0] * 5 + [1] * 4
    assert w.number.tolist() == [0, 1, 2, 3, 4, 0, 1, 2, 3]
    assert np.isnan(w.label[0]) and w.label[1:5].tolist() == [0, 0, 0, 104]
    assert w.first[5] == 10 and w.start[5] == b.index[10]
    assert (w.values[0, 5:] == 0).all() and w.values[0, :5].tolist() == [0, 1, 2, 3, 4]
    assert w.fault.tolist() == [4] * 9 and w.padded().sum() == 4
    # No instant in two windows.
    instants = np.concatenate(
        [w.start[k] + np.arange(w.n_valid[k]) * np.timedelta64(1, "s") for k in range(len(w))]
    )
    assert len(np.unique(instants)) == len(instants)

    # Lifted, the second instance is cut whole: its unlabeled head is back.
    whole = series.windows(8, drop_repeated=False)
    assert whole.n_valid.sum() == 72 and np.isnan(whole.label[5])


def test_a_window_counts_its_missing_readings_among_its_real_samples_only():
    values = np.arange(10, dtype=float)
    values[[1, 2]] = np.nan
    reader = wi.SeriesPass("P-TPT")
    reader.add(frame("2017-02-01", [0] * 10, values), ref(0))
    w = reader.result().windows(8)
    assert w.nan_share.tolist() == pytest.approx([2 / 8, 0.0])
    assert w.real(1).tolist() == [8.0, 9.0]


def test_a_sensor_the_file_lacks_reads_as_missing():
    reader = wi.SeriesPass("QGL")
    reader.add(frame("2017-02-01", [0] * 4), ref(0))
    series = reader.result()
    assert np.isnan(series.values).all() and series.index_of(0) == 0 and series.index_of(3) == -1


def test_every_window_is_described_by_the_viewers_own_descriptors_over_its_real_samples():
    values = np.zeros((3, 64))
    values[0] = RNG.normal(5.0, 2.0, 64)
    values[1, :40] = RNG.normal(-1.0, 0.5, 40)  # 24 samples of padding
    values[1, 3] = np.nan  # a missing reading, dropped as the statistics table drops it
    values[2, :4] = 1.0  # too few readings for anything but the moments and quantiles
    n_valid = np.array([64, 40, 4])
    figures = wi.describe_windows(values, n_valid, scale=2.0)
    assert set(figures) == set(wi.DESCRIBED) and "gaussian" not in figures
    for k in range(3):
        expected = describe(values[k, : n_valid[k]] * 2.0)
        for name in wi.DESCRIBED:
            assert figures[name][k] == pytest.approx(getattr(expected, name), nan_ok=True), name
    assert figures["n"][1] == 39 and figures["mean"][1] == pytest.approx(
        2.0 * np.nanmean(values[1, :40])
    )
    assert np.isnan(figures["skew"][2]) and figures["high"][2] == 2.0


def test_a_stopped_description_returns_nothing():
    seen = []

    def progress(done, total):
        seen.append((done, total))
        return done < 20

    values = RNG.normal(size=(50, 32))
    assert wi.describe_windows(values, np.full(50, 32), progress=progress, chunk=10) is None
    assert seen == [(10, 50), (20, 50)]


def test_separation_is_zero_for_indistinct_scores_and_one_for_split_ones():
    event = np.array([False] * 5 + [True] * 5)
    assert wi.separation(np.arange(10.0), event) == pytest.approx(1.0)
    assert wi.separation(np.arange(10.0)[::-1], event) == pytest.approx(1.0)
    assert wi.separation(np.ones(10), event) == pytest.approx(0.0)
    assert wi.auc(
        np.array([1.0, 2.0, 2.0, 3.0]), np.array([False, False, True, True])
    ) == pytest.approx(0.875)
    assert np.isnan(wi.separation(np.arange(3.0), np.zeros(3, dtype=bool)))
