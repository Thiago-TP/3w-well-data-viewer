"""Tests of the profile pass: how every sensor of every instance and bar was measured, cached. No Qt involved."""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from conftest import CACHE_HOME, hours

from overlap_viewer.algorithms.interpolation import Sampling
from overlap_viewer.backend import dataset as ds
from overlap_viewer.backend import profiles as pr


def write_historian_instance(
    folder: Path, well: int, start: pd.Timestamp, n: int, every: int
) -> Path:
    """A normal instance whose downhole pressure was measured every ``every`` seconds and interpolated between."""
    index = pd.date_range(start, periods=n, freq="1s", name="timestamp")
    t_meas = np.arange(0, n, every)
    signs = np.where(np.arange(len(t_meas)) % 2 == 0, 1.0, -1.0)
    v_meas = 1e7 + 1e5 * np.sin(2 * np.pi * t_meas / 600.0) + 3e4 * signs
    pdg = np.interp(np.arange(n), t_meas, v_meas).astype(np.float32).astype(float)
    frame = pd.DataFrame(
        {
            "P-PDG": pdg,
            "T-TPT": np.full(n, 118.5),
            "QGL": np.full(n, np.nan),
            "ESTADO-W1": np.full(n, 1.0),
            "class": pd.array([0] * n, dtype="Int16"),
            "state": pd.array([0] * n, dtype="Int16"),
        },
        index=index,
    )
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"WELL-{well:05d}_{start:%Y%m%d%H%M%S}.parquet"
    frame.to_parquet(path)
    return path


def test_the_profile_pass_reads_every_instance_once_and_every_bar_as_the_recording_it_is(
    raw_dir: Path, tmp_path: Path, monkeypatch
):
    """Measurements are counted per instance and per joined bar, cached, and looked up by either key."""
    # A third well, measured every 10 s and interpolated between, cut into two
    # windows overlapping by half an hour, so that its joined bar merges them.
    write_historian_instance(raw_dir / "0", 3, hours(100), 3600, 10)
    write_historian_instance(raw_dir / "0", 3, hours(100.5), 3600, 10)
    monkeypatch.setenv(CACHE_HOME, str(tmp_path / "cache"))
    info = ds.DatasetInfo.load(raw_dir)
    catalogue = ds.load_catalogue(info, use_cache=False)
    wells = ds.split_wells(catalogue)
    sensors = info.sensor_names
    calls: list[tuple[int, int]] = []

    def progress(done, total, _title):
        calls.append((done, total))
        return True

    profiles = pr.load_profiles(info, wells, sensors, progress=progress)
    table = profiles.table
    assert calls and calls[-1] == (7, 7)  # every instance gone through, once
    assert list(table.columns) == pr.PROFILE_COLUMNS
    assert (table[table["scope"] == "instance"].shape[0]) == 7 * len(sensors)
    # Well 1's three windows join into one bar, well 2's two stay apart, well 3's two join.
    bars = table[table["scope"] == "bar"]
    assert sorted(set(zip(bars["well"], bars["bar"]))) == [(1, 0), (2, 0), (2, 1), (3, 0)]

    # The historian's pressure: one measurement every 10 s, the rest interpolated.
    key = (0, f"WELL-00003_{hours(100):%Y%m%d%H%M%S}.parquet")
    sampling = profiles.sampling(key, "P-PDG")
    assert isinstance(sampling, Sampling)
    assert sampling.n_valid == 3600 and sampling.n_genuine == 360
    assert sampling.spacing_s == pytest.approx(10.0)
    # ``np.interp`` holds the last measurement over the nine seconds after it.
    assert sampling.n_interpolated == 3600 - 360 - 9 and sampling.n_held == 9
    # Its two windows read as one recording: every instant once, measured every 10 s throughout.
    merged = profiles.sampling((3, 0), "P-PDG", joined=True)
    assert merged.n_valid == 3600 + 1800 and merged.n_genuine == 540
    assert merged.spacing_s == pytest.approx(10.0)
    # A perfect straight line has two measurements, a frozen sensor one, an
    # absent sensor none, and a valve state is not tested at all.
    plain = (0, f"WELL-00001_{hours(0):%Y%m%d%H%M%S}.parquet")
    assert profiles.sampling(plain, "P-PDG").n_genuine == 2
    frozen = profiles.sampling(plain, "T-TPT")
    assert frozen.n_genuine == 1 and frozen.n_held == 7200 - 1
    assert profiles.sampling(plain, "QGL").n_valid == 0
    valve = profiles.sampling(plain, "ESTADO-W1")
    assert valve.n_genuine == valve.n_valid == 7200 and np.isnan(valve.spacing_s)
    # The descriptors come twice: on the grid, and on the measurements alone,
    # which for the historian's pressure are far noisier and far less autocorrelated.
    row = profiles.row(key, "P-PDG")
    assert row["n"] == 3600 and row["n_g"] == 360
    assert row["snr"] > 20 * row["snr_g"]
    assert row["mean"] == pytest.approx(row["mean_g"], rel=1e-3)
    assert profiles.row(plain, "T-TPT")["std"] == 0 and np.isnan(
        profiles.row(plain, "T-TPT")["skew"]
    )
    # Readings outside the plausible range are taken out and counted.
    negative = (9, f"WELL-00002_{hours(48):%Y%m%d%H%M%S}.parquet")
    row = profiles.row(negative, "P-PDG")
    assert row["n_implausible"] == 3600 and row["n_valid"] == 0
    # The matrix lines a column up with any list of keys, NaN where nothing is known.
    matrix = profiles.matrix([key, plain, ("x", "nowhere")], joined=False, column="n_genuine")
    assert matrix.shape == (3, len(sensors))
    assert matrix[0, sensors.index("P-PDG")] == 360 and matrix[1, sensors.index("P-PDG")] == 2
    assert np.isnan(matrix[2]).all()
    assert profiles.row(("x", "nowhere"), "P-PDG") is None
    assert len(profiles.scope(joined=True)) == 4 * len(sensors)
    # The descriptors a page colors or sorts by are columns of the table, twice
    # over, and looked up by either key; the unknown is NaN.
    for choice in pr.DESCRIPTOR_CHOICES:
        assert pr.descriptor_column(choice, False) in pr.PROFILE_COLUMNS
        assert pr.descriptor_column(choice, True) in pr.PROFILE_COLUMNS
    snr = pr.DESCRIPTOR_CHOICES[1]
    assert snr.column == "snr"
    assert profiles.descriptor(key, "P-PDG", "snr") == float(profiles.row(key, "P-PDG")["snr"])
    assert profiles.descriptor(key, "P-PDG", "snr") > profiles.descriptor(key, "P-PDG", "snr_g")
    assert np.isfinite(profiles.descriptor((3, 0), "P-PDG", "acf_half_s", joined=True))
    assert np.isnan(profiles.descriptor(("x", "nowhere"), "P-PDG", "snr"))
    assert np.isnan(profiles.descriptor(key, "P-PDG", "no_such_column"))
    # How the figures are said: durations as such, the infinite and the undefined plainly.
    acf, skew = pr.DESCRIPTOR_CHOICES[0], pr.DESCRIPTOR_CHOICES[3]
    assert acf.format(73.0) == "73 s" and acf.format(444.0) == "7.4 min"
    assert acf.format(float("inf")) == "> 6.0 h" and acf.format(float("nan")) == "-"
    assert snr.format(35922.0) == "35,922" and snr.format(1.46) == "1.46"
    assert snr.format(float("inf")) == "∞"
    assert skew.format(-0.5) == "-0.50" and skew.format(0.5) == "+0.50"
    assert acf.inflated and snr.inflated and not skew.inflated

    # Served from the cache the second time, without touching the data.
    calls.clear()
    again = pr.load_profiles(info, wells, sensors, progress=progress)
    assert not calls
    pd.testing.assert_frame_equal(again.table, table)
    # A new version of the rule reads the data again; so does a different set of sensors.
    monkeypatch.setattr(pr, "PROFILE_VERSION", pr.PROFILE_VERSION + 1)
    pr.load_profiles(info, wells, sensors, progress=progress)
    assert calls
    calls.clear()
    fewer = pr.load_profiles(info, wells, sensors[:2], progress=progress)
    assert calls and fewer.sensors == sensors[:2]
    assert len(fewer.table) == (7 + 4) * 2


def test_the_availability_splits_a_live_cell_into_measured_and_filled(
    raw_dir: Path, tmp_path: Path, monkeypatch
):
    """Given the profiles, every live share knows how much of it was measured, per instance and per bar."""
    from overlap_viewer.backend.availability import LIVE, Availability

    write_historian_instance(raw_dir / "0", 3, hours(100), 3600, 10)
    write_historian_instance(raw_dir / "0", 3, hours(100.5), 3600, 10)
    monkeypatch.setenv(CACHE_HOME, str(tmp_path / "cache"))
    info = ds.DatasetInfo.load(raw_dir)
    catalogue = ds.load_catalogue(info, use_cache=False)
    wells = ds.split_wells(catalogue)
    sensors = info.sensor_names
    profiles = pr.load_profiles(info, wells, sensors)

    # Without the profiles nothing is split; with them, every live reading is one or the other.
    plain = Availability.from_wells(wells, info)
    assert not plain.measured and not plain.grouped(range(plain.n_bars)).measured
    assert np.isnan(plain.measured_of([0], sensors.index("P-PDG"))[0])
    measured = Availability.from_wells(wells, info, profiles=profiles)
    assert measured.measured
    pdg = sensors.index("P-PDG")
    # Every plausible live reading is a measurement or a filled sample; the
    # implausible ones (well 2's negative pressure) are neither.
    live = (measured.state[:, pdg] == LIVE) & ~measured.implausible[:, pdg]
    assert live.sum() >= 5
    assert (
        measured.genuine[live, pdg] + measured.filled[live, pdg] == measured.n_valid[live, pdg]
    ).all()

    # Well 3's instances: one measurement in ten, one every 10 s of signal.
    rows = [measured.index_of(3, 0), measured.index_of(3, 1)]
    share, spacing = measured.measured_of(rows, pdg)
    assert share == pytest.approx(0.1, abs=0.002) and spacing == pytest.approx(10.0, abs=0.05)
    # Well 1's straight line is two measurements, so nearly all of it is filled.
    share, _ = measured.measured_of([measured.index_of(1, 0)], pdg)
    assert share == pytest.approx(2 / 7200, abs=1e-6)
    # A frozen sensor has nothing to split, an enumerated one is all measurement.
    assert np.isnan(measured.measured_of([measured.index_of(1, 0)], sensors.index("T-TPT"))[0])
    assert measured.measured_of([measured.index_of(1, 0)], sensors.index("ESTADO-W1"))[0] == 1.0

    # Folded by well: the filled share of a cell is the pale end of its live share.
    table = measured.grouped([int(w) for w in measured.bars["well"]], [1, 2, 3])
    assert table.measured
    filled = table.filled_shares
    assert filled[2, pdg] == pytest.approx(0.9, abs=0.002)
    assert filled[2, pdg] <= table.shares[2, pdg, LIVE]
    assert table.measured_share(2, pdg) == pytest.approx(0.1, abs=0.002)
    assert table.spacing_s(2, pdg) == pytest.approx(10.0, abs=0.05)
    assert np.isnan(table.measured_share(1, sensors.index("QGL")))
    # Reordering the columns and stacking a total row carry the split along.
    order = table.coverage_order()
    reordered = table.with_columns(order)
    assert reordered.filled_shares[2, order.index(pdg)] == pytest.approx(filled[2, pdg])
    total = measured.total("all")
    stacked = table.stacked(total)
    assert stacked.measured and stacked.filled_shares.shape == (4, len(sensors))
    assert not table.stacked(plain.total("all")).measured

    # The joined view is profiled as the merged recordings, not as the sum of
    # the windows: well 3's two windows share half an hour, counted once.
    stats = ds.load_joined_stats(info, wells, sensors, use_cache=False)
    joined = Availability.from_wells(
        [well.joined() for well in wells], info, joined_stats=stats, profiles=profiles
    )
    assert joined.measured and joined.joined
    bar = joined.index_of(3, 0)
    assert joined.genuine[bar, pdg] == 540 and joined.n_valid[bar, pdg] == 5400
    share, spacing = joined.measured_of([bar], pdg)
    assert share == pytest.approx(0.1, abs=0.002) and spacing == pytest.approx(10.0, abs=0.05)


def test_the_profile_pass_marks_the_pressures_read_out_of_order(tmp_path: Path, monkeypatch):
    """A downhole gauge below its tree is found in the pass and reaches the availability, per bar and group."""
    from overlap_viewer.backend.availability import Availability

    root = tmp_path / "dataset"
    root.mkdir()
    (root / "dataset.ini").write_text(
        "[PARQUET_FILE_PROPERTIES]\ntimestamp = Instant\nP-PDG = Downhole pressure [Pa]\n"
        "P-TPT = Xmas-tree pressure [Pa]\nclass = Label\nstate = Status\n"
        "[EVENTS]\nNAMES = NORMAL\nTRANSIENT_OFFSET = 100\n"
        "[NORMAL]\nLABEL = 0\nDESCRIPTION = Normal Operation\n",
        encoding="utf-8",
    )
    n = 3600
    wave = 1e5 * np.sin(np.arange(n) / 60.0)
    for well, pdg in ((1, 2.5e7), (2, 1.0e7)):  # well 2's gauge reads 2 MPa below its tree
        frame = pd.DataFrame(
            {
                "P-PDG": pdg + wave,
                "P-TPT": 1.2e7 + wave,
                "class": pd.array([0] * n, dtype="Int16"),
                "state": pd.array([0] * n, dtype="Int16"),
            },
            index=pd.date_range(hours(10 * well), periods=n, freq="1s", name="timestamp"),
        )
        (root / "0").mkdir(exist_ok=True)
        frame.to_parquet(root / "0" / f"WELL-{well:05d}_{hours(10 * well):%Y%m%d%H%M%S}.parquet")
    monkeypatch.setenv(CACHE_HOME, str(tmp_path / "cache"))
    info = ds.DatasetInfo.load(root)
    wells = ds.split_wells(ds.load_catalogue(info, use_cache=False))
    sensors = info.sensor_names

    # Nothing is read for a cache that is not there.
    assert pr.load_profiles(info, wells, sensors, cache_only=True) is None
    profiles = pr.load_profiles(info, wells, sensors)
    assert pr.load_profiles(info, wells, sensors, cache_only=True) is not None
    bad = (0, f"WELL-00002_{hours(20):%Y%m%d%H%M%S}.parquet")
    good = (0, f"WELL-00001_{hours(10):%Y%m%d%H%M%S}.parquet")
    assert profiles.row(bad, "P-PDG")["n_out_of_order"] == n
    assert profiles.order_partners(bad, "P-PDG") == ["P-TPT"]
    assert profiles.order_partners(bad, "P-TPT") == ["P-PDG"]
    assert profiles.order_partners(good, "P-PDG") == []
    assert profiles.order_partners((2, 0), "P-TPT", joined=True) == ["P-PDG"]

    plain = Availability.from_wells(wells, info)
    assert plain.out_of_order is None and not plain.order_any([0, 1])
    marked = Availability.from_wells(wells, info, profiles=profiles)
    first, second = marked.index_of(1, 0), marked.index_of(2, 0)
    assert not marked.order_any([first]) and marked.order_any([second])
    assert marked.order_any([second], sensors.index("P-TPT"))
    assert marked.out_of_order_pairs([first, second]) == [("P-PDG", "P-TPT")]
    table = marked.grouped([int(w) for w in marked.bars["well"]], [1, 2])
    pdg = sensors.index("P-PDG")
    assert list(table.out_of_order[:, pdg]) == [0, 1]
    assert table.order_partners[1, pdg] == ("P-TPT",)
    stacked = table.stacked(marked.total("all")).with_columns([1, 0])
    assert list(stacked.out_of_order[:, 1]) == [0, 1, 1]
    assert table.stacked(plain.total("all")).out_of_order is None
