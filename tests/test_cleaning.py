"""Tests of the Toolkit's CleanSignals rule as the viewer applies it, and of the file-list export."""

import json
from pathlib import Path

import numpy as np
import pytest

from overlap_viewer.algorithms.cleaning import CleanRule, clean_signals
from overlap_viewer.backend.dataset import DatasetInfo
from overlap_viewer.backend.export import file_list_config, relative_file, write_file_list


def test_clean_signals_discards_by_the_quartiles_and_drops_the_missing_columns():
    """An event whose mean or spread sits beyond 3 IQR is discarded; a flat sensor always is; a mostly missing column goes."""
    rng = np.random.default_rng(3)
    n = 40
    sensors = ["P-TPT", "T-TPT", "QGL", "ESTADO-W1"]
    means = np.column_stack(
        [
            1e7 + rng.normal(0, 1e5, n),  # a pressure every event agrees on
            100 + rng.normal(0, 1, n),
            np.full(n, np.nan),  # a flow rate no event has
            rng.uniform(0, 1, n),  # a valve: exempt whatever it does
        ]
    )
    stds = np.column_stack(
        [
            1e4 + rng.normal(0, 1e3, n),
            0.5 + rng.normal(0, 0.05, n),
            np.full(n, np.nan),
            rng.uniform(0, 0.5, n),
        ]
    )
    missing = np.isnan(means)
    # Event 3 is stuck at another level, event 7 is frozen, event 9 is wildly noisy, event 11's valve is odd.
    means[3, 0] = 3e7
    stds[7, 1] = 0.0
    stds[9, 1] = 50.0
    means[11, 3] = 1e9
    # QGL missing in every event, T-TPT missing in 65 % of them (its figures kept where it is there).
    missing[: int(0.65 * n), 1] = True
    result = clean_signals(means, stds, missing, sensors, exempt=["ESTADO-W1"])
    assert result.n_events == n and result.sensors == sensors
    assert result.discarded[3, 0] and result.by_mean[3, 0] and not result.by_std[3, 0]
    assert result.discarded[7, 1] and result.by_std[7, 1]  # frozen: below the floored lower bound
    assert result.std_bounds[0][1] >= 1e-6
    assert result.discarded[9, 1] and result.by_std[9, 1]
    assert not result.discarded[11, 3] and result.exempt[3]  # a valve is left alone
    assert result.discarded[:, 0].sum() <= 3 and result.discarded[:, 1].sum() <= 4  # the rest pass
    assert np.isnan(result.mean_bounds[0][2])  # nothing to fit on
    assert result.dropped.tolist() == [False, True, True, False]
    assert result.dropped_sensors() == ["T-TPT", "QGL"]
    assert result.missing_shares[1] == pytest.approx(0.65) and result.missing_shares[2] == 1.0
    assert result.discarded_sensors(3) == ["P-TPT"]
    assert "mean outside" in result.why(3, 0) and "spread outside" in result.why(7, 1)
    # Of event 3's live, non-exempt sensors (P-TPT, T-TPT), T-TPT is dropped and P-TPT discarded.
    live = np.array([True, True, False, True])
    assert result.kept_share(3, live) == 0.0
    assert result.kept_share(0, live) == pytest.approx(0.5)
    assert np.isnan(result.kept_share(0, np.array([False, False, False, True])))
    # Looser thresholds keep more; a tighter missing share drops less.
    loose = clean_signals(
        means, stds, missing, sensors, exempt=["ESTADO-W1"], rule=CleanRule(iqr_factor=1000.0)
    )
    assert not loose.by_mean[3, 0] and loose.discarded[7, 1]  # the frozen one still fails the floor
    strict = clean_signals(
        means, stds, missing, sensors, rule=CleanRule(missing_share=0.9, std_floor=None)
    )
    assert strict.dropped.tolist() == [False, False, True, False]
    assert "IQR" in CleanRule().describe() and "60%" in CleanRule().describe()


def test_the_file_list_is_what_the_toolkit_loader_takes(tmp_path: Path):
    """Relative paths under the root, once each, sorted, in the configuration's own fields, with the provenance beside."""
    info = DatasetInfo(Path("H:/somewhere/dataset"), version="2.0.0")
    files = [
        (4, "WELL-00014_20170918230000.parquet"),
        (0, "WELL-00001_20170201010207.parquet"),
        (4, "WELL-00014_20170918230000.parquet"),  # a joined bar hands its instance over twice
    ]
    assert (
        relative_file(4, "WELL-00014_20170918230000.parquet")
        == "4/WELL-00014_20170918230000.parquet"
    )
    config = file_list_config(info, files)
    assert config["split"] == "list" and config["event_type"] == ["real"]
    assert config["file_list"] == [
        "0/WELL-00001_20170201010207.parquet",
        "4/WELL-00014_20170918230000.parquet",
    ]
    assert set(config) == {"path", "split", "file_list", "event_type", "version"}
    out = tmp_path / "list.json"
    note = write_file_list(out, info, files, source="the Faults page, Severe Slugging, WELL-00014")
    assert json.loads(out.read_text(encoding="utf-8")) == config
    written = json.loads(note.read_text(encoding="utf-8"))
    assert note.name == "list.provenance.json" and written["n_files"] == 2
    assert "Faults page" in written["source"] and "ParquetDatasetConfig" in written["load_with"]


def test_the_rule_reads_the_profiles_of_the_instances_and_of_the_bars(
    raw_dir: Path, tmp_path: Path, monkeypatch
):
    """Fitted on the profile table, keyed like it, exempting the valves, once per view."""
    from conftest import CACHE_HOME

    from overlap_viewer.algorithms.cleaning import clean_profiles
    from overlap_viewer.backend import dataset as ds
    from overlap_viewer.backend import profiles as pr

    monkeypatch.setenv(CACHE_HOME, str(tmp_path / "cache"))
    info = ds.DatasetInfo.load(raw_dir)
    catalogue = ds.load_catalogue(info, use_cache=False)
    wells = ds.split_wells(catalogue)
    profiles = pr.load_profiles(info, wells, info.sensor_names)
    keys = [(int(fc), str(f)) for fc, f in zip(catalogue["fault_class"], catalogue["file"])]
    cleaned = clean_profiles(profiles, keys, False, info, CleanRule(iqr_factor=0.5))
    assert cleaned.keys == keys and not cleaned.joined
    # QGL is missing everywhere and is dropped; the valve is exempt; T-TPT never moves,
    # so its spread of zero falls under the floor and it is discarded wherever it is there.
    dropped = cleaned.cleaning.dropped_sensors()
    assert "QGL" in dropped
    assert cleaned.cleaning.exempt[info.sensor_names.index("ESTADO-W1")]
    for key in keys:
        assert "T-TPT" in cleaned.discarded(key) and "ESTADO-W1" not in cleaned.discarded(key)
    assert "spread outside" in cleaned.why(keys[0], "T-TPT")
    assert "CleanSignals would discard" in cleaned.describe(keys[0])
    assert cleaned.describe(("x", "nowhere")) == "not among the events the rule was fitted on"
    assert cleaned.discarded(("x", "nowhere")) == [] and np.isnan(cleaned.kept_share(("x", "no")))
    # The kept share counts the live, non-exempt sensors: P-PDG is the only one that moves.
    share = cleaned.kept_share(keys[0])
    assert share in (0.0, 1.0)
    # The joined view is fitted on the bars, and keyed by (well, bar).
    joined_keys = [(w.well, b) for w in wells for b in range(w.joined().n_instances)]
    bars = clean_profiles(profiles, joined_keys, True, info)
    assert bars.joined and bars.keys == joined_keys and bars.cleaning.n_events == len(joined_keys)
