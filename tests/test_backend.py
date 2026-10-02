"""Backend tests on a synthetic miniature of the 3W layout; no Qt involved."""

import re
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pytest
from conftest import CACHE_HOME, T0, hours

from overlap_viewer.algorithms.faults import (
    onset,
    onset_from_runs,
    plausible_extent,
    relative_hours,
    window_mask,
    zscore,
)
from overlap_viewer.algorithms.interpolation import GENUINE, sample_kinds
from overlap_viewer.backend import dataset as ds
from overlap_viewer.backend import help_text, theme
from overlap_viewer.backend.availability import (
    ABSENT,
    FROZEN,
    LIVE,
    Availability,
    PairCoverage,
    PairTable,
    implausible_sensors,
    outside_range,
    sensor_state,
)
from overlap_viewer.backend.config import (
    BEST_EFFORT_SIGNATURES,
    BEST_EFFORT_SOURCES,
    DEFAULT_FAULT_NAMES,
    DEFAULT_FEATURES,
    DEFAULT_SENSOR_UNITS,
    DEFAULT_TRANSIENT_CAPABLE,
    EXTREME_VALUE_LIMIT,
    FAULT_SIGNATURES,
    PLACEMENTS,
    REACH_TINTS,
    STATE_VALVE_RULES,
    WELL_STATES,
    asset_path,
    cache_dir,
    placement_of,
    plausible_range,
)
from overlap_viewer.backend.labels import (
    Segment,
    column_as_float,
    coverage_counts,
    fault_reach,
    feature_stats,
    format_duration,
    label_kind,
    label_name,
    label_segments,
    labels_agree,
    merge_label_runs,
    padded_range,
    period_durations,
    runs,
    segments_from_json,
    segments_to_json,
    sensor_stats_from_json,
    sensor_stats_to_json,
)
from overlap_viewer.backend.palette import (
    background_color,
    bar_color,
    blend,
    fault_color,
    legend_entries,
    legend_key,
    luminance,
    state_color,
    text_color,
    tint,
    to_rgb,
    unknown_background,
)
from overlap_viewer.backend.timemap import TimeMap
from overlap_viewer.frontend.help import valve_rule_text
from overlap_viewer.frontend.legend import row_breaks
from overlap_viewer.frontend.overview import bar_tooltip
from overlap_viewer.frontend.series_page import SeriesPage, sample_counts


def segments(*spans) -> list[Segment]:
    """Label runs from ``(start_hour, end_hour, value)`` triples."""
    return [Segment(hours(a), hours(b), float(v)) for a, b, v in spans]


def instance_row(well: int, fault_class: int, start: pd.Timestamp, labels) -> dict:
    """The catalogue row of an in-memory instance sampled once a second, files left out."""
    index = pd.date_range(start, periods=len(labels), freq="1s", name="timestamp")
    frame = pd.DataFrame({"class": pd.array(labels, dtype="Int16")}, index=index)
    return {
        "file": f"WELL-{well:05d}_{start:%Y%m%d%H%M%S}.parquet",
        "fault_class": fault_class,
        "well": well,
        "start": index[0],
        "end": index[-1],
        "n_samples": len(index),
        "reach": fault_reach(column_as_float(frame, "class")),
        "class_runs": segments_to_json(label_segments(frame, "class")),
        "size": 0,
        "mtime_ns": 0,
        "stamp": index[0],
        "hours": (index[-1] - index[0]).total_seconds() / 3600,
    }


def test_parse_names():
    assert ds.parse_well_id("WELL-00026_20170608230000.parquet") == 26
    assert ds.parse_well_id("SIMULATED_00001.parquet") is None
    assert ds.filename_stamp("WELL-00026_20170608230000.parquet") == pd.Timestamp(
        "2017-06-08 23:00:00"
    )
    assert ds.filename_stamp("WELL-00026.parquet") is None
    assert ds.well_label(7) == "WELL-00007"


def test_dataset_info_reads_ini(raw_dir: Path):
    info = ds.DatasetInfo.load(raw_dir)
    assert info.version == "9.9.9"
    assert info.fault_names == {0: "Normal Operation", 9: "Hydrate in Service Line"}
    assert info.sensor_names == ["P-PDG", "T-TPT", "QGL", "ESTADO-W1"]
    assert info.unit("P-PDG") == "Pa"
    assert info.unit("T-TPT") == "°C"
    assert info.unit("QGL") == "m³/s"
    assert info.unit("ESTADO-W1") == ""  # enumerated states have no unit
    assert info.is_enumerated("ESTADO-W1") and not info.is_enumerated("P-PDG")
    assert info.fault_classes == [0, 9]
    # Only the events the ini marks as having a transient do.
    assert info.transient_faults == frozenset({9})
    assert info.has_transient(9) and not info.has_transient(0)


def test_dataset_info_falls_back_without_ini(tmp_path: Path):
    info = ds.DatasetInfo.load(tmp_path)
    assert info.fault_name(3) == "Severe Slugging"
    assert "P-TPT" in info.sensor_names
    assert info.transient_faults == DEFAULT_TRANSIENT_CAPABLE
    assert not info.has_transient(3) and info.has_transient(8)


def test_pack_lanes_alternates_along_a_chain():
    starts = np.array([hours(h) for h in (0, 1, 2, 3)], dtype="datetime64[ns]")
    ends = np.array([hours(h) for h in (1.5, 2.5, 3.5, 4.5)], dtype="datetime64[ns]")
    assert ds.pack_lanes(starts, ends).tolist() == [0, 1, 0, 1]


def test_overlap_matrix_counts_a_shared_second():
    starts = np.array([hours(0), hours(1), hours(5)], dtype="datetime64[ns]")
    ends = np.array([hours(1), hours(2), hours(6)], dtype="datetime64[ns]")
    hits = ds.overlap_matrix(starts, ends)
    assert hits[0, 1] and hits[1, 0]
    assert not hits[0, 2] and not hits.diagonal().any()


def test_fault_reach_and_label_kinds():
    assert fault_reach(np.array([np.nan, 0.0, 109.0, 9.0])) == "steady"
    assert fault_reach(np.array([0.0, 109.0])) == "transient"
    assert fault_reach(np.array([0.0, np.nan])) == "normal"
    assert [label_kind(v) for v in (np.nan, 0.0, 4.0, 104.0, 250.0)] == [
        "unknown",
        "normal",
        "steady",
        "transient",
        "unknown",
    ]
    names = {0: "Normal Operation", 9: "Hydrate in Service Line"}
    assert label_name(109.0, names) == "Hydrate in Service Line - Transient"
    assert label_name(9.0, names) == "Hydrate in Service Line"
    assert label_name(np.nan, names) == "Unknown"


def test_runs_and_segments_tile_the_recording():
    values = np.array([np.nan, np.nan, 0.0, 0.0, 109.0])
    found = runs(values)
    assert [(s, e) for s, e, _ in found] == [(0, 2), (2, 4), (4, 5)]
    assert np.isnan(found[0][2]) and [v for _, _, v in found[1:]] == [0.0, 109.0]
    index = pd.date_range(T0, periods=5, freq="1s", name="timestamp")
    frame = pd.DataFrame({"class": pd.array([pd.NA, pd.NA, 0, 0, 109], dtype="Int16")}, index=index)
    segments = label_segments(frame, "class")
    assert [s.start for s in segments] == [index[0], index[2], index[4]]
    assert segments[-1].end == index[-1] + pd.Timedelta(seconds=1)
    assert segments[0].end == segments[1].start


def test_label_runs_survive_the_catalogue_cache():
    index = pd.date_range(T0, periods=5, freq="1s", name="timestamp")
    frame = pd.DataFrame({"class": pd.array([pd.NA, pd.NA, 0, 0, 109], dtype="Int16")}, index=index)
    original = label_segments(frame, "class")
    back = segments_from_json(segments_to_json(original))
    assert [(s.start, s.end) for s in back] == [(s.start, s.end) for s in original]
    assert np.isnan(back[0].value) and [s.value for s in back[1:]] == [0.0, 109.0]
    assert segments_from_json(segments_to_json([])) == []


def test_labels_agree_only_where_both_tracks_know_the_label():
    a = segments((0, 2, 0), (2, 3, 109))  # normal for two hours, then the transient
    assert labels_agree(a, segments((1, 2, 0), (2, 4, 109)))  # the same labels where shared
    assert not labels_agree(a, segments((1, 3, 0)))  # normal where ``a`` says transient
    assert labels_agree(a, segments((1, 3, np.nan)))  # unknown agrees with anything
    assert labels_agree(a, segments((5, 6, 4)))  # nothing shared at all
    assert labels_agree(a, []) and labels_agree([], a)
    # A contradiction one sampling step long still counts.
    second = pd.Timedelta(seconds=1)
    b = segments((0, 2, 0)) + [Segment(hours(2), hours(2) + second, 4.0)]
    assert not labels_agree(a, b) and not labels_agree(b, a)


def test_merged_label_runs_fill_the_unknown_and_remember_whose_label_it_is():
    """Merging labels shrinks the unlabeled stretches and keeps each one's folder."""
    normal = segments((0, 1, np.nan), (1, 4, 0))  # a Normal Operation file, unlabeled head
    hydrate = segments((3, 5, np.nan), (5, 6, 0), (6, 8, 108))  # a hydrate file, unlabeled head

    def spell(found):
        """The runs as ``(start hour, end hour, label or 'unlabeled', source)``."""
        return [
            (
                (s.start - T0) / pd.Timedelta(hours=1),
                (s.end - T0) / pd.Timedelta(hours=1),
                "unlabeled" if np.isnan(s.value) else s.value,
                source,
            )
            for s, source in found
        ]

    assert spell(merge_label_runs([normal, hydrate], [0, 8])) == [
        (0.0, 1.0, "unlabeled", None),  # nothing knows the first hour
        # The Normal Operation file's own label, which also fills the unlabeled
        # head of the hydrate window where the two overlap, at hour 3.
        (1.0, 4.0, 0.0, 0),
        (4.0, 5.0, "unlabeled", None),  # its window has ended, the hydrate's head is still blank
        (5.0, 6.0, 0.0, 8),  # normal, but labeled by the hydrate file: that file's color
        (6.0, 8.0, 108.0, 8),
    ]
    # One track is passed through as it is, and runs that agree coalesce.
    assert spell(merge_label_runs([normal], [0])) == [
        (0.0, 1.0, "unlabeled", None),
        (1.0, 4.0, 0.0, 0),
    ]
    assert merge_label_runs([], []) == []


def test_join_groups_merges_agreeing_chains_and_splits_conflicts():
    starts = np.array([hours(h) for h in (0, 1, 2.5, 3.5, 4.5)], dtype="datetime64[ns]")
    ends = np.array([hours(h) for h in (2, 3, 4, 5, 6)], dtype="datetime64[ns]")
    tracks = [
        segments((0, 2, 0)),
        segments((1, 3, 0)),
        segments((2.5, 3, 0), (3, 4, 109)),  # agrees with the one before on their shared half hour
        segments((3.5, 5, 0)),  # normal where the one before is transient: a conflict
        segments((4.5, 6, 109)),  # transient where the one before is normal: another
    ]
    assert ds.join_groups(starts, ends, tracks) == [[0, 1, 2], [3], [4]]
    # Nothing overlapping, nothing joined.
    assert ds.join_groups(starts[::2], ends[::2] - np.timedelta64(1, "h"), tracks[::2]) == [
        [0],
        [1],
        [2],
    ]


def test_joined_well_merges_agreeing_instances_and_carries_every_color():
    n = 3600
    catalogue = pd.DataFrame(
        [
            # A normal window whose tail is the normal period of a hydrate instance: joinable.
            instance_row(7, 0, hours(0), [0] * (2 * n)),
            instance_row(7, 8, hours(1), [0] * n + [108] * n + [8] * n),
            # A flow-instability window over the hydrate's steady state: a labeling conflict.
            instance_row(7, 4, hours(3.5), [4] * n),
            # A hydrate window that never leaves normal operation, apart from the rest.
            instance_row(7, 8, hours(5), [0] * n),
        ]
    )
    well = ds.WellData.from_catalogue(catalogue, 7)
    assert not well.joined_view and well.origin is well
    assert well.members == [[0], [1], [2], [3]]
    assert well.n_instances == 4 and well.n_overlapping == 3 and well.n_lanes == 2

    joined = well.joined()
    assert joined.joined_view and joined.origin is well and joined.joined() is joined
    assert joined.members == [[0, 1], [2], [3]]
    assert joined.colors == [[(0, "normal"), (8, "steady")], [(4, "steady")], [(8, "normal")]]
    rows = joined.rows
    assert rows["title"].tolist() == [
        "WELL-00007_20170201010000 +1",
        "WELL-00007_20170201043000",
        "WELL-00007_20170201060000",
    ]
    assert rows["fault_class"].tolist() == [8, 4, 8]
    assert rows["reach"].tolist() == ["steady", "steady", "normal"]
    assert rows["start"].iloc[0] == hours(0) and rows["end"].iloc[0] == hours(4) - pd.Timedelta(
        seconds=1
    )
    assert rows["hours"].iloc[0] == pytest.approx((4 * n - 1) / n)
    # The hour the two joined instances share is counted once.
    assert rows["n_samples"].tolist() == [4 * n, n, n]
    assert rows["stamp"].iloc[0] == hours(0)
    # The conflict is what still overlaps; the well keeps every color it drew before.
    assert joined.n_instances == 3 and joined.n_overlapping == 2 and joined.n_lanes == 2
    assert joined.present_colors() == well.present_colors()
    assert joined.fault_classes() == {0, 4, 8}
    # Clicking the joined bar opens it and the bar it overlaps, two blocks of three instances.
    assert joined.group(0) == [0, 1]
    assert [joined.members[p] for p in joined.group(0)] == [[0, 1], [2]]
    # The well-wide view is built once, so the overview and the windows share it.
    assert well.joined() is joined and joined.joined() is joined
    assert ds.instance_title(rows.iloc[0]) == "WELL-00007_20170201010000 +1"
    assert ds.instance_title(well.rows.iloc[0]) == "WELL-00007_20170201010000"


def test_a_stitched_well_lays_its_recordings_end_to_end_lane_by_lane():
    """Every lane of the joined view becomes one bar; a labeling conflict stitches on its own."""
    n = 3600
    catalogue = pd.DataFrame(
        [
            instance_row(7, 0, hours(0), [0] * (2 * n)),
            instance_row(7, 8, hours(1), [0] * n + [108] * n + [8] * n),
            instance_row(7, 4, hours(3.5), [4] * n),  # the conflict: a lane of its own
            instance_row(7, 8, hours(5), [0] * n),
        ]
    )
    well = ds.WellData.from_catalogue(catalogue, 7)
    joined = well.joined()
    stitched = well.stitched()
    assert stitched.stitched_view and stitched.joined_view and not joined.stitched_view
    assert well.stitched() is stitched and stitched.stitched() is stitched
    assert joined.stitched() is stitched and stitched.origin is well
    assert stitched.joined() is joined  # what an instance window asks of it
    # Lane 0 of the joined view is its first and third bars, lane 1 the conflict.
    assert stitched.pieces == [[0, 2], [1]]
    assert stitched.members == [[0, 1, 3], [2]]
    assert stitched.piece_members(0) == [[0, 1], [3]] and stitched.piece_members(1) == [[2]]
    assert well.piece_members(2) == [[2]]  # a bar that is not stitched is one recording
    rows = stitched.rows
    assert rows["title"].tolist() == ["WELL-00007_20170201010000 +2", "WELL-00007_20170201043000"]
    assert rows["fault_class"].tolist() == [8, 4] and rows["reach"].tolist() == ["steady", "steady"]
    assert rows["start"].iloc[0] == hours(0) and rows["end"].iloc[0] == hours(6) - pd.Timedelta(
        seconds=1
    )
    # What the bar holds is its recordings, not the calendar between them.
    assert rows["n_samples"].tolist() == [5 * n, n]
    assert rows["hours"].iloc[0] == pytest.approx((4 * n - 1 + n - 1) / n)
    assert stitched.colors[0] == [(0, "normal"), (8, "steady"), (8, "normal")]
    assert stitched.n_lanes == 2 and stitched.present_colors() == well.present_colors()
    # The axis of a stitched bar is built from its recordings.
    starts, ends = stitched.spans([0])
    assert list(starts) == [np.datetime64(hours(0)), np.datetime64(hours(5))]
    assert len(stitched.spans()[0]) == 3
    starts, ends = well.spans([1, 2])
    assert list(starts) == list(well.starts[[1, 2]]) and list(ends) == list(well.ends[[1, 2]])


def test_stitching_merges_each_recording_and_keeps_the_real_timestamps():
    """Overlapping windows merge once per recording; recordings far apart are only concatenated."""
    index = pd.date_range(hours(0), periods=6, freq="1s", name="timestamp")
    later = pd.date_range(hours(100), periods=3, freq="1s", name="timestamp")
    a = pd.DataFrame({"P-PDG": [1.0, 2, 3, 4, np.nan, np.nan]}, index=index)
    b = pd.DataFrame({"P-PDG": [np.nan, np.nan, 3.0, 4, 5, 6]}, index=index)
    c = pd.DataFrame({"P-PDG": [7.0, 8, 9]}, index=later)
    frame = ds.stitch_instances([[a, b], [c]])
    assert frame.index.is_monotonic_increasing and not frame.index.has_duplicates
    assert frame["P-PDG"].tolist() == [1.0, 2, 3, 4, 5, 6, 7, 8, 9]
    assert frame.index[6] == hours(100)  # the silence is still in the index, for the axis to skip
    assert ds.stitch_instances([[a]]) is a


def test_a_bar_tooltip_gives_its_start_end_and_duration():
    """A plain bar spans its instance; a joined one, from its first instance's start to its last's end."""
    assert format_duration(0) == "0 s"
    assert format_duration(59.6) == "1 min"
    assert format_duration(5 * 3600 + 56 * 60 + 15) == "5 h 56 min 15 s"
    assert format_duration(2 * 86400 + 3600) == "2 d 1 h"
    n = 3600
    catalogue = pd.DataFrame(
        [
            instance_row(7, 0, hours(0), [0] * (2 * n)),
            instance_row(7, 8, hours(1), [0] * n + [108] * n + [8] * n),
        ]
    )
    well = ds.WellData.from_catalogue(catalogue, 7)
    plain = bar_tooltip(well, 0)
    assert "<b>WELL-00007_20170201010000</b>" in plain and "joined" not in plain
    assert "2017-02-01 01:00:00" in plain and "2017-02-01 02:59:59" in plain
    assert "1 h 59 min 59 s (2.00 h)" in plain
    joined = bar_tooltip(well.joined(), 0)
    assert "(2 instances joined)" in joined
    assert "2017-02-01 01:00:00" in joined and "2017-02-01 04:59:59" in joined
    assert "3 h 59 min 59 s (4.00 h)" in joined
    stitched = bar_tooltip(well.stitched(), 0)
    assert "(2 instances stitched from 1 recording)" in stitched
    assert "recorded" in stitched and "span" in stitched


def test_joining_a_chosen_set_says_what_that_set_alone_amounts_to():
    """An instance window joins its own group, not the well: a bridge left out stays out."""
    n = 3600
    catalogue = pd.DataFrame(
        [
            instance_row(3, 0, hours(0), [0] * (2 * n)),  # [0 h, 2 h)
            instance_row(3, 0, hours(1), [0] * (2 * n)),  # [1 h, 3 h), overlapping both others
            instance_row(3, 0, hours(2.5), [0] * (2 * n)),  # [2.5 h, 4.5 h)
        ]
    )
    well = ds.WellData.from_catalogue(catalogue, 3)
    # The well reads as one recording: the middle instance bridges the other two.
    assert well.joined().members == [[0, 1, 2]]
    # Asked about the first and the last alone, it says they are two recordings. They
    # share no sample, and what would bridge them is not in the set being asked about.
    assert well.joined(among=[0, 2]).members == [[0], [2]]
    assert well.joined(among=[0, 1]).members == [[0, 1]]
    assert well.joined(among=[1]).members == [[1]]
    # Only the well-wide join is remembered, and asking about a subset leaves it alone.
    remembered = well.joined()
    assert well.joined(among=[0, 2]) is not remembered
    assert well.joined() is remembered
    # A joined bar still knows the instances behind it, whichever set it came from.
    pair = well.joined(among=[0, 1])
    assert pair.n_instances == 1 and pair.origin is well
    assert pair.rows["title"].iloc[0].endswith(" +1")


def test_merging_instances_keeps_each_instant_once_and_fills_what_one_window_missed():
    """Two windows of one recording read as the single series they were cut from."""
    index = pd.date_range(T0, periods=4, freq="1s", name="timestamp")
    early = pd.DataFrame(
        {
            "P-PDG": [1.0, 2.0, 3.0, 4.0],
            "T-TPT": [np.nan] * 4,  # a sensor this window did not record
            "class": pd.array([0, 0, 0, 0], dtype="Int16"),
        },
        index=index,
    )
    late = pd.DataFrame(
        {
            "P-PDG": [3.0, 4.0, 5.0],
            "T-TPT": [10.0, 11.0, 12.0],
            "class": pd.array([pd.NA, pd.NA, 109], dtype="Int16"),  # an unlabeled head
        },
        index=pd.date_range(T0 + pd.Timedelta(seconds=2), periods=3, freq="1s", name="timestamp"),
    )
    merged = ds.merge_instances([early, late])
    assert len(merged) == 5 and merged.index.is_monotonic_increasing
    assert merged["P-PDG"].tolist() == [1.0, 2.0, 3.0, 4.0, 5.0]
    # What one window says nothing about, the other one fills: the head of the later
    # window is labeled by the earlier one, and its sensor fills the earlier one's blank.
    assert merged["class"].tolist()[:4] == [0, 0, 0, 0] and merged["class"].iloc[4] == 109
    assert merged["class"].dtype == early["class"].dtype
    assert merged["T-TPT"].isna().tolist() == [True, True, False, False, False]
    assert merged["T-TPT"].dropna().tolist() == [10.0, 11.0, 12.0]
    assert merged.index.name == "timestamp"
    # One window is handed back untouched, and instances that do not overlap simply follow on.
    assert ds.merge_instances([early]) is early
    apart = ds.merge_instances([early, late.set_index(late.index + pd.Timedelta(hours=1))])
    assert len(apart) == 7 and apart.index.is_monotonic_increasing
    # The figures of the merged frame count each instant once and skip what is missing.
    stats = ds.merged_sensor_stats(merged)
    assert stats["P-PDG"] == (5, 1.0, 5.0)
    assert stats["T-TPT"] == (3, 10.0, 12.0)
    assert "class" not in stats


def test_timemap_compressed_roundtrip_and_gaps():
    starts = [hours(0), hours(2), hours(100)]
    ends = [hours(3), hours(5), hours(101)]
    timemap = TimeMap.build(starts, ends, gap_hours=12.0, compressed=True)
    assert len(timemap.blocks) == 2
    assert timemap.recorded_hours == pytest.approx(6.0)
    x = timemap.to_x(starts)
    assert x[0] == 0.0 and x[1] == pytest.approx(2.0)
    assert x[2] > 5.0  # after the collapsed silence
    for value, stamp in zip(x, starts):
        assert timemap.to_time(float(value)) == stamp
    assert timemap.to_time(timemap.gap_centers()[0]) is None
    assert timemap.to_x(ends)[2] == pytest.approx(timemap.span)


def test_timemap_linear_extrapolates():
    timemap = TimeMap.build([hours(0), hours(48)], [hours(1), hours(49)], compressed=False)
    assert len(timemap.blocks) == 1
    assert timemap.span == pytest.approx(49.0)
    assert timemap.to_time(-2.0) == hours(-2)
    assert timemap.to_time(60.0) == hours(60)


def test_coverage_counts_sweeps_boundaries():
    stretches = coverage_counts([hours(0), hours(1), hours(5)], [hours(2), hours(3), hours(6)])
    assert [(a, b, c) for a, b, c in stretches] == [
        (hours(0), hours(1), 1),
        (hours(1), hours(2), 2),
        (hours(2), hours(3), 1),
        (hours(3), hours(5), 0),
        (hours(5), hours(6), 1),
    ]


def test_padded_range_and_stats():
    low, high = padded_range(5.0, 5.0)
    assert low < 5.0 < high and high - low == pytest.approx(1.0)
    assert padded_range(0.0, 10.0) == (-0.6, 10.6)
    frame = pd.DataFrame({"a": [1.0, np.nan, 3.0], "b": [np.nan, np.nan, np.nan]})
    stats = feature_stats(frame, "a")
    assert (stats.n_valid, stats.n_total, stats.low, stats.high) == (2, 3, 1.0, 3.0)
    assert stats.coverage == pytest.approx(200 / 3)
    assert not feature_stats(frame, "b").recorded
    assert not feature_stats(frame, "missing").recorded


def test_palette_ladder_and_legend():
    assert tint("#000000", 0.0) == "#ffffff"
    assert tint("#17becf", 1.0) == "#17becf"
    steady, transient, normal = (bar_color(9, r) for r in ("steady", "transient", "normal"))
    assert steady == "#17becf"
    assert len({steady, transient, normal}) == 3
    assert bar_color(0, "normal") == bar_color(0, "steady") == "#4c9e4c"
    assert blend(["#000000", "#ffffff"]) == "#808080" and blend(["#17becf"]) == "#17becf"
    names = {0: "Normal Operation", 9: "Hydrate in Service Line"}
    entries = legend_entries({(0, "normal"), (9, "transient"), (9, "steady")}, names)
    assert [entry.label for entry in entries] == [
        "Normal Operation",
        "Hydrate in Service Line (steady state reached)",
        "Hydrate in Service Line (transient state reached)",
    ]
    assert [entry.fill for entry in entries] == [bar_color(0, "steady"), steady, transient]
    # The three reaches of a normal instance share one entry, so one key each.
    assert legend_key(0, "normal") == legend_key(0, "steady") == entries[0].key
    assert legend_key(9, "transient") == entries[2].key


def distance_from_ground(color: str) -> float:
    """How far a color has travelled from the plotting ground it is mixed toward."""
    ground = to_rgb(theme.current().plot_background)
    return sum(abs(a - b) for a, b in zip(ground, to_rgb(color)))


def test_every_theme_colors_everything_the_viewer_can_draw():
    for colors in theme.THEMES.values():
        assert set(colors.faults) == set(DEFAULT_FAULT_NAMES)
        assert set(colors.states) == set(WELL_STATES) | {None}
        assert set(colors.swatches) == {"plain", "highlight", "selected", "dimmed"}
        assert colors.name in theme.MODES
        # The wells of the faults page get a dozen colors before any repeats.
        assert len(colors.wells) >= 12 and len(set(colors.wells)) == len(colors.wells)
        assert len({colors.live, colors.frozen, colors.warning, colors.block_fill}) == 4


def test_a_mode_changes_every_color_the_plots_carry():
    light = {
        "bar": bar_color(9, "steady"),
        "hue": fault_color(3),
        "state": state_color(0),
        "unknown": unknown_background(),
    }
    assert theme.use("dark").dark
    dark = {
        "bar": bar_color(9, "steady"),
        "hue": fault_color(3),
        "state": state_color(0),
        "unknown": unknown_background(),
    }
    assert all(light[key] != dark[key] for key in light)
    with pytest.raises(ValueError):
        theme.use("solarized")


def test_the_tint_ladder_runs_away_from_the_ground_of_each_mode():
    """A weaker reach is always a step back toward the background, dark or light."""
    for mode in theme.MODES[1:]:
        colors = theme.use(mode)
        assert tint("#000000", 0.0) == colors.plot_background
        assert tint(colors.faults[9], 1.0) == colors.faults[9]
        steps = [distance_from_ground(bar_color(9, reach)) for reach in REACH_TINTS]
        assert steps == sorted(steps, reverse=True), mode  # steady, transient, normal
        # A bar always says its own color rather than blending into the plot.
        assert min(steps) > 0.05, mode
        # And whatever the bar, the stamp written inside it stays readable.
        for reach in REACH_TINTS:
            fill = bar_color(9, reach)
            assert text_color(fill) != fill


def test_the_trace_stays_visible_over_every_shading_it_can_sit_on():
    """A time series line keeps to one side of the ladder, the far side of it."""
    for mode in theme.MODES[1:]:
        colors = theme.use(mode)
        grounds = [background_color(f, r) for f in DEFAULT_FAULT_NAMES for r in REACH_TINTS]
        grounds += [tint(unknown_background(), 0.7), colors.plot_background]
        gaps = [luminance(ground) - luminance(colors.trace) for ground in grounds]
        if colors.dark:
            assert max(gaps) < -0.3, mode  # the trace sits above every shading
        else:
            assert min(gaps) > 0.3, mode  # and below every one of them here


def test_the_well_code_is_never_read_as_the_fault_code():
    """The faults page draws both codes in one plot, so they are kept in different registers."""
    for mode in theme.MODES[1:]:
        colors = theme.use(mode)
        hues = set(colors.faults.values())
        assert not hues & set(colors.wells), mode  # never the very same color
        grounds = [background_color(f, r) for f in DEFAULT_FAULT_NAMES for r in REACH_TINTS]
        grounds += [tint(unknown_background(), 0.7), colors.plot_background]
        for well in colors.wells:
            here = luminance(well)
            # A well line stays on the far side of every fault hue, so the two
            # codes cannot be confused whatever hue a well happens to be given.
            gaps = [here - luminance(hue) for hue in hues]
            # And, like the trace, on the far side of every shading it can sit on.
            over = [here - luminance(ground) for ground in grounds]
            if colors.dark:
                assert min(gaps) > 0, (mode, well)
                assert min(over) > 0.25, (mode, well)
            else:
                assert max(gaps) < 0, (mode, well)
                assert max(over) < -0.25, (mode, well)


def test_the_coverage_band_only_speaks_where_instances_pile_up():
    colors = theme.use("dark")
    assert colors.shared_fill(0) == colors.plot_background
    assert colors.shared_fill(1) == colors.block_fill
    assert colors.shared_fill(2) == colors.shared_fills[0]
    assert colors.shared_fill(99) == colors.shared_fills[-1]


def test_legend_keeps_each_gradient_on_its_own_row():
    """A fault drawn at several tints is only readable with its steps side by side."""
    names = {n: f"Fault {n}" for n in range(6)}
    entries = legend_entries(
        {(0, "normal"), (1, "steady"), (2, "steady"), (2, "transient"), (3, "steady")}, names
    )
    assert [(e.fault_class, e.reach) for e in entries] == [
        (0, "steady"),
        (1, "steady"),
        (2, "steady"),
        (2, "transient"),
        (3, "steady"),
    ]
    # Fault 2 is a gradient: it starts a row, and fault 3 starts the next one.
    assert row_breaks(entries) == [False, False, True, False, True]
    # With no gradient at all, nothing is forced onto its own row.
    plain = legend_entries({(0, "normal"), (1, "steady")}, names)
    assert row_breaks(plain) == [False, False]
    assert row_breaks([]) == []


def test_help_figures_are_declared_and_shipped():
    """The help's illustrations name a caption, a credit and a file that is there."""
    assert {"platform", "platform-overview"} <= set(help_text.FIGURES)
    for figure in help_text.FIGURES.values():
        assert figure.caption and figure.credit and figure.width > 0
        assert asset_path(figure.file) is not None, f"{figure.file} is not shipped"
    assert asset_path("no-such-illustration.png") is None


def test_help_text_covers_the_dataset():
    """Every class, variable and status the viewer can draw has help to show for it."""
    assert set(help_text.FAULTS) == set(DEFAULT_FAULT_NAMES)
    assert set(help_text.VARIABLES) == set(DEFAULT_SENSOR_UNITS)
    assert set(help_text.STATES) == set(WELL_STATES)
    assert set(help_text.TRANSIENT_CAPABLE) == set(DEFAULT_FAULT_NAMES) - {0, 3, 4}
    # A signature only ever names variables the dataset actually has.
    for fault, variables in FAULT_SIGNATURES.items():
        assert fault in DEFAULT_FAULT_NAMES
        assert set(variables) <= set(DEFAULT_SENSOR_UNITS)
        assert help_text.FAULTS[fault].figure, f"fault {fault} has a signature but names no figure"
        # ... and the figure is reproduced, with its own caption and credit.
        assert help_text.FAULTS[fault].illustration in help_text.FIGURES
    # Every other event has a best-effort signature, sourced, of the same four-variable
    # convention, and the two tables never overlap: a published figure is never second-guessed.
    assert set(BEST_EFFORT_SIGNATURES).isdisjoint(FAULT_SIGNATURES)
    assert set(BEST_EFFORT_SIGNATURES) | set(FAULT_SIGNATURES) == set(DEFAULT_FAULT_NAMES)
    assert set(BEST_EFFORT_SOURCES) == set(BEST_EFFORT_SIGNATURES)
    for fault, variables in BEST_EFFORT_SIGNATURES.items():
        assert len(variables) == 4 and set(variables) <= set(DEFAULT_SENSOR_UNITS)
    # Every variable sits at exactly one placement, the one its help page gives, and the
    # default features are the analog sensors of the seabed.
    places = [name for names in PLACEMENTS.values() for name in names]
    assert sorted(places) == sorted(DEFAULT_SENSOR_UNITS)
    where = {"Topside": "Topside", "Seabed": "Subsea christmas tree", "Subsurface": "Downhole"}
    for name, entry in help_text.VARIABLES.items():
        assert entry.where.startswith(where[placement_of(name)]), name
    assert placement_of("NO-SUCH-SENSOR") is None
    assert {placement_of(name) for name in DEFAULT_FEATURES} == {"Seabed"}
    assert not any(name.startswith("ESTADO") for name in DEFAULT_FEATURES)
    for entry in help_text.FAULTS.values():
        assert entry.what and entry.signature and entry.source
    # Every variable has its position in the paper's schematic, and no two share one.
    positions = [entry.position for entry in help_text.VARIABLES.values()]
    assert all(re.fullmatch(r"\d+\.\d+", position) for position in positions)
    assert len(set(positions)) == len(positions)
    # Every event but normal operation and the one added in 2.0.0 has a published
    # confirmation window; normal operation is not an occurrence to confirm.
    assert set(help_text.CONFIRMATION_WINDOWS) == set(DEFAULT_FAULT_NAMES) - {0, 9}
    # The usage help knows every page of the viewer.
    assert {
        "Timelines page",
        "Availability page",
        "Faults page",
        "Instance window",
        "Signal views",
    } <= set(help_text.USAGE)


def test_every_state_names_its_valves_in_the_help():
    """The rules are told in the help by the article's names, and only real states and valves."""
    assert set(STATE_VALVE_RULES) <= set(WELL_STATES)
    for rules in STATE_VALVE_RULES.values():
        for quantifier, position, valves in rules:
            assert quantifier in ("all", "any") and position in ("open", "closed")
            assert set(valves) <= set(help_text.VALVE_NAMES) <= set(DEFAULT_SENSOR_UNITS)
    assert valve_rule_text(0) == "M1, W1, SDV-P and PCK open; PXO and XO closed"
    assert valve_rule_text(8) == "SDV-P and PCK open; one of M1 and W1 closed; PXO and XO closed"
    assert valve_rule_text(4) == help_text.STATE_UNCHECKED  # Bullheading


def test_cache_dir_sits_under_the_platform_cache_home(tmp_path: Path, monkeypatch):
    """The catalogue cache goes where this platform keeps caches, named after the app."""
    monkeypatch.setenv(CACHE_HOME, str(tmp_path / "somewhere"))
    assert cache_dir() == tmp_path / "somewhere" / "overlap-viewer"


def test_cache_dir_falls_back_to_the_home_directory(monkeypatch):
    """With no cache home named, the cache still lands somewhere inside the user's home."""
    monkeypatch.delenv(CACHE_HOME, raising=False)
    assert Path.home() in cache_dir().parents


def test_catalogue_scan_wells_and_cache(raw_dir: Path, tmp_path: Path, monkeypatch):
    monkeypatch.setenv(CACHE_HOME, str(tmp_path / "cache"))
    info = ds.DatasetInfo.load(raw_dir)

    seen = []
    catalogue = ds.load_catalogue(info, progress=lambda i, n, name: seen.append((i, n)) or True)
    assert seen[-1] == (5, 5)
    assert list(catalogue["well"]) == [1, 1, 1, 2, 2]
    assert list(catalogue["reach"]) == ["normal", "normal", "normal", "transient", "normal"]
    assert catalogue["n_samples"].tolist() == [7200, 7200, 7200, 3600, 3600]
    assert all(isinstance(p, Path) and p.exists() for p in catalogue["path"])
    assert catalogue["hours"].iloc[3] == pytest.approx((3600 - 1) / 3600)
    # Inside the temporary directory, not in the user's real cache: were the
    # redirection to slip, a cache file left by an earlier run would let every
    # assertion below pass while testing nothing.
    assert ds.cache_path(raw_dir).is_relative_to(tmp_path)
    assert ds.cache_path(raw_dir).exists()

    def no_scan(*args, **kwargs):
        raise AssertionError("the cache should have been used")

    monkeypatch.setattr(ds, "scan_instances", no_scan)
    cached = ds.load_catalogue(info)
    pd.testing.assert_frame_equal(cached.drop(columns="path"), catalogue.drop(columns="path"))

    # Touching a file invalidates the cache and forces a new scan.
    monkeypatch.undo()
    monkeypatch.setenv(CACHE_HOME, str(tmp_path / "cache"))
    path = catalogue["path"].iloc[0]
    path.touch()
    calls = []
    original = ds.scan_instances
    monkeypatch.setattr(ds, "scan_instances", lambda *a, **k: calls.append(1) or original(*a, **k))
    ds.load_catalogue(info)
    assert calls == [1]

    # The label runs come out of the scan (and the cache) as they went in.
    hydrate_runs = segments_from_json(catalogue["class_runs"].iloc[3])
    assert [np.isnan(s.value) or s.value for s in hydrate_runs] == [True, 0.0, 109.0]
    assert hydrate_runs[0].start == hours(0) and hydrate_runs[-1].end == hours(1)

    wells = ds.split_wells(catalogue)
    assert [w.well for w in wells] == [1, 2]
    chain = wells[0]
    assert chain.n_instances == 3 and chain.n_overlapping == 3 and chain.n_lanes == 2
    assert chain.rows["lane"].tolist() == [0, 1, 0]
    assert chain.group(1) == [0, 1, 2]
    assert chain.group(0) == [0, 1]
    # All three windows carry the same label, so joined they are one four-hour bar.
    joined = chain.joined()
    assert joined.n_instances == 1 and joined.members == [[0, 1, 2]] and joined.n_lanes == 1
    assert joined.rows["n_samples"].iloc[0] == 4 * 3600
    assert joined.rows["title"].iloc[0] == "WELL-00001_20170201010000 +2"
    hydrate = wells[1]
    assert hydrate.n_overlapping == 0 and hydrate.n_lanes == 1
    assert hydrate.group(0) == [0]
    assert hydrate.present_colors() == {(9, "transient"), (9, "normal")}
    assert ds.lane_slots(wells, minimum=2, maximum=8) == 2


def test_cancelling_the_scan(raw_dir: Path):
    info = ds.DatasetInfo.load(raw_dir)
    entries = ds.list_real_instances(raw_dir, info.fault_classes)
    assert len(entries) == 5
    with pytest.raises(ds.ScanCancelled):
        ds.scan_instances(entries, progress=lambda i, n, name: False)


def test_sensor_stats_come_from_the_footer_or_from_the_data(raw_dir: Path):
    """What each sensor recorded is read from the footer, and from the columns when it lacks it."""
    info = ds.DatasetInfo.load(raw_dir)
    entries = ds.list_real_instances(raw_dir, info.fault_classes)
    with_footer, without_footer = entries[0][1], entries[-1][1]
    assert pq.ParquetFile(with_footer).metadata.row_group(0).column(0).statistics is not None
    assert pq.ParquetFile(without_footer).metadata.row_group(0).column(0).statistics is None
    for path, offset in ((with_footer, 0.0), (without_footer, -2.0e7)):
        with pq.ParquetFile(path) as parquet:
            stats = ds.read_sensor_stats(parquet)
        n = pq.ParquetFile(path).metadata.num_rows
        assert list(stats) == ["P-PDG", "T-TPT", "QGL", "ESTADO-W1"]  # labels and index left out
        assert stats["P-PDG"] == (n, pytest.approx(1.0e7 + offset), pytest.approx(1.1e7 + offset))
        assert stats["T-TPT"] == (n, 118.5, 118.5)
        assert stats["QGL"][0] == 0 and np.isnan(stats["QGL"][1]) and np.isnan(stats["QGL"][2])
        assert stats["ESTADO-W1"] == (n, 1.0, 1.0)
    # A partly recorded sensor counts its readings only.
    with pq.ParquetFile(entries[3][1]) as parquet:
        partial = ds.read_sensor_stats(parquet)
    assert partial["P-PDG"][0] == 1440 and partial["P-PDG"][1] == pytest.approx(1.06e7, rel=1e-3)
    # And they survive the catalogue cache as text.
    catalogue = ds.scan_instances(entries)
    back = sensor_stats_from_json(catalogue["sensor_stats"].iloc[-1])
    assert back["P-PDG"] == (3600, pytest.approx(-1.0e7), pytest.approx(-0.9e7))
    assert back["QGL"][0] == 0 and np.isnan(back["QGL"][1])
    assert sensor_stats_from_json(sensor_stats_to_json({})) == {}


def test_sensor_states_and_plausible_ranges():
    """Absent, frozen or live; a valve state is never frozen; a threshold; ranges follow the unit."""
    assert sensor_state(0, 10, np.nan, np.nan) == ABSENT
    assert sensor_state(10, 10, 5.0, 5.0) == FROZEN
    assert sensor_state(10, 10, 0.0, 0.0) == FROZEN  # frozen at zero, the usual case
    assert sensor_state(10, 10, 1.0e7, 1.0e7 + 1.0) == FROZEN  # moving less than the flat span
    assert sensor_state(10, 10, 1.0e7, 1.1e7) == LIVE
    assert sensor_state(10, 10, 1.0, 1.0, enumerated=True) == LIVE
    assert sensor_state(0, 10, np.nan, np.nan, enumerated=True) == ABSENT
    # Below the threshold a sensor is not available, whatever its readings say.
    assert sensor_state(4, 10, 1.0e7, 1.1e7, threshold=0.5) == ABSENT
    assert sensor_state(5, 10, 1.0e7, 1.1e7, threshold=0.5) == LIVE
    assert sensor_state(4, 10, 5.0, 5.0, threshold=0.5) == ABSENT
    assert sensor_state(4, 10, 1.0, 1.0, enumerated=True, threshold=0.5) == ABSENT

    assert plausible_range("Pa") == (0.0, EXTREME_VALUE_LIMIT)
    assert plausible_range("°C") == (-50.0, 250.0)
    assert plausible_range("%") == (0.0, 100.0)
    assert plausible_range("m³/s") == (0.0, 10.0)
    assert plausible_range("") == (-EXTREME_VALUE_LIMIT, EXTREME_VALUE_LIMIT)
    assert outside_range(-0.5, 2.0, plausible_range("m³/s"))  # a negative flow rate
    assert not outside_range(0.0, 4.31, plausible_range("m³/s"))  # closed gas lift, top rate
    assert outside_range(-1.0, 5.0, plausible_range("Pa"))  # a negative absolute pressure
    assert outside_range(1.0, 1.3e8, plausible_range("Pa"))  # 1,300 bar
    assert not outside_range(0.0, 4.9e7, plausible_range("Pa"))  # zero is left alone
    assert outside_range(-99.99, 40.0, plausible_range("%"))  # the choke's sentinel
    assert outside_range(10.0, 150.0, plausible_range("%"))  # an opening past fully open
    assert not outside_range(0.0, 100.0, plausible_range("%"))  # shut to fully open
    assert outside_range(-999.0, 20.0, plausible_range("°C"))  # a sentinel
    assert not outside_range(-33.8, 127.7, plausible_range("°C"))  # the real extremes of 3W
    assert not outside_range(np.nan, np.nan, plausible_range("Pa"))  # nothing recorded
    info = ds.DatasetInfo(Path("."))
    stats = {"P-PDG": (5, -1.2e42, 0.0), "T-TPT": (5, 20.0, 30.0), "QGL": (0, np.nan, np.nan)}
    assert implausible_sensors(stats, info) == ["P-PDG"]


def test_pressures_are_shown_in_mpa_and_ruled_in_pa():
    """What is shown converts; the unit the rules and ranges are keyed on does not."""
    info = ds.DatasetInfo(Path("."))
    assert info.unit("P-PDG") == "Pa"  # the file's unit, which the ranges are keyed on
    assert info.shown_unit("P-PDG") == "MPa" and info.shown_scale("P-PDG") == 1e-6
    assert info.shown_range("P-PDG") == (0.0, 100.0)
    assert info.shown_range("P-PDG") != plausible_range(info.unit("P-PDG"))
    # Every other quantity is shown as recorded.
    for sensor in ("T-TPT", "ABER-CKP", "QGL"):
        assert info.shown_unit(sensor) == info.unit(sensor) and info.shown_scale(sensor) == 1.0
        assert info.shown_range(sensor) == plausible_range(info.unit(sensor))
    assert info.shown_unit("ESTADO-W1") == ""  # a valve state has no unit to convert


def test_period_durations_add_up_to_the_span():
    """Normal, transient, steady and unlabeled time, from runs that tile a recording."""
    n = 3600
    frame = pd.DataFrame(
        {"class": [np.nan] * 600 + [0.0] * n + [108.0] * (n // 2) + [8.0] * (2 * n)},
        index=pd.date_range(T0, periods=600 + n + n // 2 + 2 * n, freq="1s"),
    )
    durations = period_durations(label_segments(frame, "class"), offset=100)
    assert list(durations) == ["normal", "transient", "steady", "unknown"]
    assert durations == {"normal": n, "transient": n / 2, "steady": 2 * n, "unknown": 600}
    assert sum(durations.values()) == len(frame)  # one second per sample: the whole span
    # A recording that never leaves normal operation has nothing in the other periods.
    calm = period_durations(label_segments(frame.iloc[600 : 600 + n], "class"), offset=100)
    assert calm == {"normal": n, "transient": 0, "steady": 0, "unknown": 0}


def test_section_headings_count_samples_and_measurements():
    """A reading is a sample; a measurement is a sample the historian archived; a valve has none."""
    ramp = np.array([1.0, 2.0, 3.0, 4.0, 4.0, np.nan, 5.0])
    kinds = sample_kinds(ramp)
    samples, measured = sample_counts(ramp, kinds)
    assert samples == 6 and measured == int((kinds == GENUINE).sum()) and 0 < measured < samples
    # A normalized series has its implausible readings blanked; the kinds still count them.
    blanked = ramp.copy()
    blanked[0] = np.nan
    assert sample_counts(blanked, kinds) == (samples, measured)
    assert sample_counts(np.array([0.0, 1.0, np.nan]), None) == (2, None)
    text = SeriesPage._counts_text([(100, 10), (50, 5), (30, None)])
    assert text == " | 180 samples, 15 measurements (8.3%)"
    assert SeriesPage._counts_text([(30, None)]) == " | 30 samples"
    assert SeriesPage._counts_text([]) == ""


def test_availability_folds_bars_into_groups(raw_dir: Path, tmp_path: Path, monkeypatch):
    """The table a page draws: shares of samples and of bars per state, counts, bounds, marks."""
    monkeypatch.setenv(CACHE_HOME, str(tmp_path / "cache"))
    info = ds.DatasetInfo.load(raw_dir)
    catalogue = ds.load_catalogue(info)
    availability = Availability.from_catalogue(catalogue, info)
    assert availability.sensors == ["P-PDG", "T-TPT", "QGL", "ESTADO-W1"]  # dataset order
    assert availability.n_bars == 5 and not availability.joined
    # One row per bar, well after well, remembering which instance it is.
    bars = availability.bars
    assert bars["well"].tolist() == [1, 1, 1, 2, 2] and bars["bar"].tolist() == [0, 1, 2, 0, 1]
    assert bars["members"].tolist() == [[0], [1], [2], [0], [1]]
    assert bars["title"].iloc[3] == "WELL-00002_20170201010000"
    assert bars["n_samples"].tolist() == catalogue["n_samples"].tolist()
    assert availability.index_of(2, 1) == 4
    # Per bar: the pressure moves, the temperature is frozen, the flow rate is
    # absent, and the valve state, constant as it is, is live.
    assert availability.state.tolist() == [[LIVE, FROZEN, ABSENT, LIVE]] * 5
    # Only the last bar, the one with the negative pressure, is implausible.
    assert availability.implausible[:, 0].tolist() == [False] * 4 + [True]
    assert not availability.implausible[:, 1:].any()
    assert availability.implausible_any([4]) and not availability.implausible_any([0, 1, 2])

    by_class = availability.grouped([int(k) for k in bars["fault_class"]])
    assert by_class.keys == [0, 9] and len(by_class) == 2
    assert by_class.n_instances.tolist() == [3, 2]
    assert by_class.n_samples.tolist() == [3 * 7200, 2 * 3600]
    # Every sample is in exactly one state, so the three shares of a cell sum to one.
    assert np.allclose(by_class.shares.sum(axis=2), 1.0)
    assert np.allclose(by_class.instance_shares.sum(axis=2), 1.0)
    # P-PDG: live throughout the normal windows; live in 70 % of the hydrate class's
    # samples, since one of its two instances misses the first 60 % of it.
    assert np.allclose(by_class.shares[:, 0], [[0.0, 0.0, 1.0], [0.3, 0.0, 0.7]])
    assert by_class.shares[:, 1].tolist() == [[0.0, 1.0, 0.0], [0.0, 1.0, 0.0]]  # T-TPT frozen
    assert by_class.shares[:, 2].tolist() == [[1.0, 0.0, 0.0], [1.0, 0.0, 0.0]]  # QGL absent
    assert by_class.instances[1, :, LIVE].tolist() == [2, 0, 0, 2]
    assert by_class.instances[1, :, FROZEN].tolist() == [0, 2, 0, 0]
    assert by_class.instances[1, :, ABSENT].tolist() == [0, 0, 2, 0]
    assert by_class.instance_shares[1, 0].tolist() == [0.0, 0.0, 1.0]  # both instances live
    assert by_class.implausible.tolist() == [[0, 0, 0, 0], [1, 0, 0, 0]]
    assert by_class.low[1, 0] == pytest.approx(-1.0e7) and by_class.high[1, 0] == pytest.approx(
        1.1e7
    )
    assert np.isnan(by_class.low[0, 2]) and np.isnan(by_class.high[0, 2])  # nothing recorded
    # The shares behind one bar, or behind several read together.
    shares, flagged = availability.shares_of([3], 0)
    assert np.allclose(shares, [0.6, 0.0, 0.4]) and not flagged
    shares, flagged = availability.shares_of([3, 4], 0)
    assert np.allclose(shares, [0.3, 0.0, 0.7]) and flagged

    # One row per bar of a well, in catalogue order, and a total over them.
    mask = (bars["well"] == 2).to_numpy()
    positions = np.flatnonzero(mask).tolist()
    per_bar = availability.grouped(range(5), positions, mask)
    assert per_bar.keys == positions and per_bar.n_instances.tolist() == [1, 1]
    total = availability.total("all", mask=mask)
    assert total.keys == ["all"] and total.n_instances.tolist() == [2]
    stacked = per_bar.stacked(total)
    assert len(stacked) == 3 and stacked.n_samples.tolist() == [3600, 3600, 7200]
    with pytest.raises(ValueError):
        per_bar.stacked(total.with_columns([0]))

    # Columns by coverage: the live sensors first, ties in dataset order, the absent one last.
    everything = availability.total()
    assert everything.coverage_order() == [3, 0, 1, 2]  # the valve state is live in every sample
    assert everything.coverage_order(by_instances=True) == [0, 3, 1, 2]  # by bars they tie
    reordered = everything.with_columns(everything.coverage_order())
    assert reordered.sensors == ["ESTADO-W1", "P-PDG", "T-TPT", "QGL"]
    assert reordered.shares[0, -1, ABSENT] == 1.0
    # An empty group is all zeros rather than a division by zero.
    empty = availability.grouped([int(k) for k in bars["fault_class"]], order=[3])
    assert empty.n_instances.tolist() == [0] and not empty.shares.any()

    # With a threshold, the partly recorded pressure is not available at all in
    # its instance, readings and all.
    strict = Availability.from_catalogue(catalogue, info, threshold=0.5)
    assert strict.threshold == 0.5
    assert strict.state[3, 0] == ABSENT and strict.state[4, 0] == LIVE
    by_class = strict.grouped([int(k) for k in bars["fault_class"]])
    assert np.allclose(by_class.shares[1, 0], [0.5, 0.0, 0.5])
    assert by_class.instances[1, 0].tolist() == [1, 0, 1]
    assert strict.implausible[4, 0]  # the threshold does not hide garbage


def same_stats(a, b) -> bool:
    """Whether two merged-figure tables agree, NaN bounds included."""
    if a.keys() != b.keys():
        return False
    for key in a:
        first, second = a[key], b[key]
        if first.n_samples != second.n_samples or first.sensors.keys() != second.sensors.keys():
            return False
        if first.pairs.tolist() != second.pairs.tolist():
            return False
        for name in first.sensors:
            va, vb = first.sensors[name], second.sensors[name]
            if va[0] != vb[0]:
                return False
            for x, y in zip(va[1:], vb[1:]):
                if not ((np.isnan(x) and np.isnan(y)) or x == pytest.approx(y)):
                    return False
    return True


def test_joined_sensor_figures_count_shared_instants_once(
    raw_dir: Path, tmp_path: Path, monkeypatch
):
    """The bars of the joined view read as merged recordings, from the data, and are cached."""
    monkeypatch.setenv(CACHE_HOME, str(tmp_path / "cache"))
    info = ds.DatasetInfo.load(raw_dir)
    catalogue = ds.load_catalogue(info)
    wells = ds.split_wells(catalogue)
    sensors = info.sensor_names
    seen = []
    stats = ds.scan_joined_stats(wells, sensors, lambda i, n, t: seen.append((i, n)) or True)
    assert seen[-1] == (5, 5)
    assert set(stats) == {(1, 0), (2, 0), (2, 1)}
    # The chain of three windows is one four-hour recording: its shared hours count once.
    chain = stats[(1, 0)]
    assert chain.n_samples == 4 * 3600
    assert chain.sensors["P-PDG"] == (4 * 3600, pytest.approx(1.0e7), pytest.approx(1.1e7))
    assert chain.sensors["T-TPT"] == (4 * 3600, 118.5, 118.5)
    assert chain.sensors["QGL"][0] == 0 and np.isnan(chain.sensors["QGL"][1])
    assert chain.sensors["ESTADO-W1"] == (4 * 3600, 1.0, 1.0)
    # The same pass counts the pairs of the merged recording.
    rows, cols = ds.pair_positions(len(sensors))
    pairs = {(sensors[a], sensors[b]): int(c) for a, b, c in zip(rows, cols, chain.pairs)}
    assert pairs[("P-PDG", "T-TPT")] == 4 * 3600 and pairs[("P-PDG", "QGL")] == 0
    # A bar of one instance is the instance itself.
    single = stats[(2, 0)]
    assert single.n_samples == 3600 and single.sensors["P-PDG"][0] == 1440

    joined = Availability.from_wells([well.joined() for well in wells], info, joined_stats=stats)
    assert joined.joined and joined.n_bars == 3
    assert joined.bars["title"].tolist() == [
        "WELL-00001_20170201010000 +2",
        "WELL-00002_20170201010000",
        "WELL-00002_20170203010000",
    ]
    assert joined.bars["members"].tolist() == [[0, 1, 2], [0], [1]]
    assert joined.n_total.tolist() == [4 * 3600, 3600, 3600]
    assert joined.state[0].tolist() == [LIVE, FROZEN, ABSENT, LIVE]
    with pytest.raises(ValueError):
        Availability.from_wells([wells[0].joined()], info)  # the merged figures are required

    # The pair map of the merged recordings: each shared instant counted once.
    coverage = PairCoverage.from_joined(joined, stats)
    table = coverage.table(joined, live_only=False)
    pdg, tpt = joined.sensors.index("P-PDG"), joined.sensors.index("T-TPT")
    assert table.n_bars == 3 and table.n_samples == 4 * 3600 + 2 * 3600
    assert table.samples[pdg, tpt] == 4 * 3600 + 1440 + 3600
    assert table.shares[pdg, tpt] == pytest.approx(19440 / 21600)

    # Cached under the platform cache home, and served from there while the files stand.
    loaded = ds.load_joined_stats(info, wells, sensors)
    assert same_stats(loaded, stats)
    assert ds.joined_cache_path(raw_dir).is_relative_to(tmp_path)
    assert ds.joined_cache_path(raw_dir).exists()

    def no_scan(*args, **kwargs):
        raise AssertionError("the cache should have been used")

    monkeypatch.setattr(ds, "scan_joined_stats", no_scan)
    assert same_stats(ds.load_joined_stats(info, wells, sensors), stats)
    # A touched file changes the listing, and the data is read again.
    monkeypatch.undo()
    monkeypatch.setenv(CACHE_HOME, str(tmp_path / "cache"))
    catalogue["path"].iloc[0].touch()
    calls = []
    original = ds.scan_joined_stats
    monkeypatch.setattr(
        ds, "scan_joined_stats", lambda *a, **k: calls.append(1) or original(*a, **k)
    )
    assert same_stats(ds.load_joined_stats(info, wells, sensors), stats)
    assert calls == [1]
    with pytest.raises(ds.ScanCancelled):
        ds.scan_joined_stats(wells, sensors, progress=lambda i, n, t: False)


def test_pair_counts_say_which_sensors_are_recorded_at_the_same_instant(
    raw_dir: Path, tmp_path: Path, monkeypatch
):
    """Two sensors can each cover half a recording and never overlap: the data has to say."""
    monkeypatch.setenv(CACHE_HOME, str(tmp_path / "cache"))
    info = ds.DatasetInfo.load(raw_dir)
    sensors = info.sensor_names  # P-PDG, T-TPT, QGL, ESTADO-W1
    entries = ds.list_real_instances(raw_dir, info.fault_classes)
    rows, cols = ds.pair_positions(len(sensors))
    assert len(rows) == 10  # the upper triangle of four sensors, diagonal included
    assert (rows[0], cols[0]) == (0, 0) and (rows[-1], cols[-1]) == (3, 3)

    # The hydrate instance records its pressure over the last 40 % of its samples
    # only, so that is all it can share with the sensors that cover the whole of it.
    with pq.ParquetFile(entries[3][1]) as parquet:
        counts = ds.read_pair_counts(parquet, sensors)
    pairs = {(sensors[a], sensors[b]): int(c) for a, b, c in zip(rows, cols, counts)}
    assert pairs[("P-PDG", "P-PDG")] == 1440
    assert pairs[("P-PDG", "T-TPT")] == 1440
    assert pairs[("T-TPT", "T-TPT")] == 3600
    assert pairs[("T-TPT", "ESTADO-W1")] == 3600
    assert pairs[("P-PDG", "QGL")] == 0 and pairs[("QGL", "QGL")] == 0

    seen = []
    scanned = ds.scan_pair_counts(entries, sensors, lambda i, n, name: seen.append((i, n)) or True)
    assert seen[-1] == (5, 5) and len(scanned) == 5
    assert scanned[(9, entries[3][1].name)].tolist() == counts.tolist()
    with pytest.raises(ds.ScanCancelled):
        ds.scan_pair_counts(entries, sensors, progress=lambda i, n, name: False)

    # Cached under the platform cache home, and served from there while the files stand.
    loaded = ds.load_pair_counts(info, sensors)
    assert {k: v.tolist() for k, v in loaded.items()} == {k: v.tolist() for k, v in scanned.items()}
    assert ds.pair_cache_path(raw_dir).is_relative_to(tmp_path)

    def no_scan(*args, **kwargs):
        raise AssertionError("the cache should have been used")

    monkeypatch.setattr(ds, "scan_pair_counts", no_scan)
    assert len(ds.load_pair_counts(info, sensors)) == 5
    # Asked for the sensors in another order, the cache cannot answer: the
    # counts are stored in the order they were taken in.
    with pytest.raises(AssertionError):
        ds.load_pair_counts(info, list(reversed(sensors)))


def test_pair_coverage_folds_the_counts_over_a_scope(raw_dir: Path, tmp_path: Path, monkeypatch):
    """The share of the samples of a scope in which both sensors of a pair carry a reading."""
    monkeypatch.setenv(CACHE_HOME, str(tmp_path / "cache"))
    info = ds.DatasetInfo.load(raw_dir)
    catalogue = ds.load_catalogue(info)
    availability = Availability.from_catalogue(catalogue, info)
    # Every bar of the plain view names the instance behind it, which is how the
    # counts, keyed by folder and file, find their bar.
    assert availability.bars["file"].tolist() == catalogue["file"].tolist()

    entries = ds.list_real_instances(raw_dir, info.fault_classes)
    counts = ds.scan_pair_counts(entries, availability.sensors)
    coverage = PairCoverage.from_counts(availability, counts)
    assert coverage.counts.shape == (5, 10)

    live = coverage.table(availability)
    assert live.live_only and live.n_bars == 5
    assert live.n_samples == 3 * 7200 + 2 * 3600
    order = live.sensors
    pdg, tpt, qgl, valve = (order.index(name) for name in ("P-PDG", "T-TPT", "QGL", "ESTADO-W1"))
    # 26,640 samples carry the pressure: three whole windows, one whole instance
    # and the last 40 % of another.
    assert live.samples[pdg, pdg] == 26640
    assert live.shares[pdg, pdg] == pytest.approx(26640 / 28800)
    assert live.samples[pdg, valve] == 26640 and live.samples[valve, pdg] == 26640
    assert live.samples[valve, valve] == 28800 and live.shares[valve, valve] == 1.0
    # The temperature is frozen in every instance, so no pair of it is *live*.
    assert live.samples[tpt, tpt] == 0 and live.samples[pdg, tpt] == 0
    assert live.samples[qgl].sum() == 0  # and nothing ever records the flow rate
    assert live.bars[pdg, valve] == 5

    # Counted as Rabelo counts, a frozen reading is still a reading.
    recorded = coverage.table(availability, live_only=False)
    assert not recorded.live_only
    assert recorded.samples[tpt, tpt] == 28800
    assert recorded.samples[pdg, tpt] == 26640
    assert recorded.samples[qgl].sum() == 0

    # One fault class alone, and the order the page can put the sensors in.
    mask = (availability.bars["fault_class"] == 9).to_numpy()
    hydrate = coverage.table(availability, mask, live_only=False)
    assert hydrate.n_bars == 2 and hydrate.n_samples == 7200
    assert hydrate.samples[pdg, tpt] == 1440 + 3600
    assert hydrate.shares[pdg, tpt] == pytest.approx(5040 / 7200)
    ordered = hydrate.with_order(hydrate.coverage_order())
    assert ordered.sensors[-1] == "QGL"  # nothing recorded it, so it sorts last
    assert ordered.samples[0, 0] >= ordered.samples[-1, -1]
    # An empty scope is all zeros rather than a division by zero.
    empty = coverage.table(availability, np.zeros(5, dtype=bool))
    assert empty.n_bars == 0 and empty.n_samples == 0 and not empty.shares.any()


def test_the_pair_map_can_be_ordered_so_that_what_goes_together_sits_together():
    """Spectral seriation: two groups of sensors, weakly bridged, come out contiguous."""
    sensors = ["a1", "b1", "a2", "b2", "dead"]  # the groups interleaved in dataset order
    samples = np.array(
        [
            # a1   b1   a2   b2  dead
            [100, 0, 100, 0, 0],
            [0, 100, 10, 100, 0],
            [100, 10, 100, 0, 0],
            [0, 100, 0, 100, 0],
            [0, 0, 0, 0, 0],  # nothing ever recorded it
        ]
    )
    table = PairTable(sensors, 1, 100, samples, (samples > 0).astype(int), live_only=True)
    order = [sensors[j] for j in table.grouped_order()]
    assert order == ["a1", "a2", "b1", "b2", "dead"]
    # Ordered by coverage instead, the groups stay interleaved: every sensor but
    # the dead one covers the same, so the ranking keeps them in dataset order.
    assert [sensors[j] for j in table.coverage_order()] == sensors
    # Too little to seriate is not an error; the sensors keep their order.
    tiny = np.array([[10, 10], [10, 10]])
    small = PairTable(["x", "y"], 1, 10, tiny, tiny, live_only=True)
    assert small.grouped_order() == [0, 1]
    empty = np.zeros((3, 3), dtype=int)
    assert PairTable(["x", "y", "z"], 0, 0, empty, empty, True).grouped_order() == [0, 1, 2]


def test_faults_are_aligned_where_the_event_begins_and_scaled_to_their_level():
    """The onset of an instance by its labels, from the frame or from the catalogue's runs."""
    index = pd.date_range(T0, periods=5, freq="1s", name="timestamp")
    frame = pd.DataFrame(
        {
            "class": pd.array([pd.NA, 0, 0, 109, 9], dtype="Int16"),
            "P-PDG": [1.0, 2.0, 3.0, 4.0, 5.0],
        },
        index=index,
    )
    assert onset(frame, 9, align="transient") == index[3]
    assert onset(frame, 9, align="steady") == index[4]
    assert onset(frame, 9, align="start") == index[0]
    assert onset(frame, 4, align="transient") is None  # another fault's labels
    assert onset(frame.iloc[:0], 9) is None
    with pytest.raises(ValueError):
        onset(frame, 9, align="middle")
    runs_of = label_segments(frame, "class")
    for align in ("transient", "steady", "start"):
        assert onset_from_runs(runs_of, 9, align=align) == onset(frame, 9, align=align)
    assert onset_from_runs(runs_of, 4) is None and onset_from_runs([], 9) is None

    hours_from = relative_hours(index, index[3])
    assert hours_from.tolist() == pytest.approx([-3 / 3600, -2 / 3600, -1 / 3600, 0.0, 1 / 3600])
    assert window_mask(np.array([-2.0, -0.5, 0.0, 3.0]), 1.0, 2.0).tolist() == [
        False,
        True,
        True,
        False,
    ]
    assert window_mask(np.array([-2.0, 3.0]), 0.0, 0.0).tolist() == [True, True]

    scaled = zscore(np.array([1.0, 2.0, 3.0, np.nan]))
    assert scaled[:3] == pytest.approx([-1.2247, 0.0, 1.2247], abs=1e-4) and np.isnan(scaled[3])
    assert zscore(np.array([5.0, 5.0, np.nan])).tolist()[:2] == [0.0, 0.0]  # a flat series
    assert np.isnan(zscore(np.array([np.nan, np.nan]))).all()

    bounds = plausible_range("Pa")
    assert plausible_extent(np.array([-1.2e42, 1.0e7, 2.0e7, np.nan]), bounds) == (1.0e7, 2.0e7)
    assert plausible_extent(np.array([-1.0, -2.0]), bounds) == (-2.0, -1.0)  # nothing plausible
    assert all(np.isnan(plausible_extent(np.array([np.nan]), bounds)))


def test_a_series_is_prepared_for_a_transform_or_declines():
    """Implausible readings masked, holes interpolated, trend removed; too little or flat declines."""
    from overlap_viewer.algorithms.spectral import prepare

    t = np.arange(600, dtype=float)
    y = 5.0 + 0.01 * t + np.sin(2 * np.pi * t / 60)
    y[100:110] = np.nan  # a hole
    y[300] = -1.0e42  # a sentinel
    prepared = prepare(y, plausible_range("Pa"))
    assert prepared is not None and len(prepared) == 600 and not np.isnan(prepared).any()
    assert abs(prepared.mean()) < 1e-6  # mean removed
    assert abs(np.polyfit(t, prepared, 1)[0]) < 1e-9  # trend removed
    assert np.allclose(
        prepared[105], np.sin(2 * np.pi * 105 / 60), atol=0.2
    )  # filled from neighbours
    assert prepare(np.full(600, 3.0)) is None  # frozen
    mostly_missing = np.where(np.arange(600) % 3 == 0, y, np.nan)
    assert prepare(mostly_missing) is None  # a third of the readings
    assert prepare(np.arange(5.0)) is None  # too short


def test_welch_finds_the_period_of_a_sine_and_says_what_it_resolves():
    from overlap_viewer.algorithms.spectral import TransformParams, prepare, welch

    t = np.arange(6 * 3600, dtype=float)
    rng = np.random.default_rng(1)
    y = 3.0 * np.sin(2 * np.pi * t / 5400) + 0.1 * rng.standard_normal(len(t))  # 90 min
    whole = welch(prepare(y), TransformParams())
    assert whole.n_segments == 1 and whole.segment_s == len(t)
    assert np.all(np.diff(whole.periods) > 0) and whole.periods[-1] == pytest.approx(len(t))
    period, share = whole.dominant()
    assert period == pytest.approx(5400, rel=0.05) and share > 0.5
    # Parseval, one-sided: the density integrates to the variance.
    variance = float(np.var(prepare(y)))
    df = 1.0 / len(t)
    assert whole.power.sum() * df == pytest.approx(variance, rel=0.05)
    # Shorter segments average more, and see nothing longer than themselves.
    short = welch(prepare(y), TransformParams(segment_s=3600, overlap=0.5))
    assert short.segment_s == 3600 and short.n_segments == 11
    assert short.periods[-1] == pytest.approx(3600)
    assert short.dominant()[0] <= 900  # the 90 min line is beyond what it can resolve
    noise = welch(prepare(rng.standard_normal(len(t))), TransformParams(window="Rectangular"))
    assert noise.dominant()[1] < 0.02  # power spread thin, as in a normal instance
    with pytest.raises(ValueError):
        TransformParams(window="Kaiser")
    with pytest.raises(ValueError):
        TransformParams(overlap=1.0)


def test_histogram_stacks_by_group_and_leaves_the_implausible_out():
    from overlap_viewer.algorithms.spectral import histogram

    values = np.array([1.0, 1.5, 2.0, 2.5, 3.0, np.nan, 1.0e9, 3.5])
    groups = np.array([0, 0, 1, 1, 1, 0, 0, 1])
    result = histogram(values, groups, bins=5, bounds=plausible_range("Pa"), keys=["a", "b"])
    assert result is not None
    assert result.left_out == 1 and result.total == 6
    assert result.mean == pytest.approx(2.25) and result.median == pytest.approx(2.25)
    assert list(result.stacks) == ["a", "b"]
    assert result.stacks["a"].sum() == 2 and result.stacks["b"].sum() == 4
    assert len(result.edges) == 6 and result.edges[0] == 1.0 and result.edges[-1] == 3.5
    assert result.counts.tolist() == (result.stacks["a"] + result.stacks["b"]).tolist()
    fixed = histogram(values, None, bins=3, edges=np.array([0.0, 2.0, 4.0]))
    assert fixed is not None and list(fixed.stacks) == [None]
    assert fixed.stacks[None].tolist() == [2, 4]  # nothing masked: 1e9 falls beyond the edges
    ordered = histogram(values, 1 - groups, bins=2, keys=["b", "a", "nobody"])
    assert list(ordered.stacks) == ["b", "a"]  # the order of the keys; an empty stack left out
    with pytest.raises(ValueError):
        histogram(values, groups, bins=2)
    flat = histogram(np.full(10, 7.0), None, bins=4)
    assert flat is not None and flat.edges[0] < 7.0 < flat.edges[-1]
    assert histogram(np.array([np.nan, np.nan]), None, bins=3) is None


def test_spectra_are_pooled_by_averaging_the_bands_they_reach():
    """Instances are cut from different months, so their spectra average; they never concatenate."""
    from overlap_viewer.algorithms.spectral import TransformParams, average_spectra, prepare, welch

    params = TransformParams()
    # Two stretches of the same process, of different lengths, so their
    # estimates land on different frequencies and cannot be averaged point by
    # point; both oscillate every 10 minutes.
    short = np.sin(2 * np.pi * np.arange(2 * 3600, dtype=float) / 600)
    long = np.sin(2 * np.pi * np.arange(6 * 3600, dtype=float) / 600)
    a, b = welch(prepare(short), params), welch(prepare(long), params)
    pooled = average_spectra([a, b])
    assert pooled is not None
    # The pooled estimate still finds the line, and reaches the longest period
    # the longest of them could resolve.
    assert pooled.dominant()[0] == pytest.approx(600, rel=0.1)
    # It reaches past what the shorter one could resolve, up to within a band
    # of the longest period the longer one saw (the grid carries bin centers,
    # so the topmost band sits half a bin below it).
    assert a.periods[-1] < pooled.periods[-1] <= b.periods[-1]
    assert pooled.periods[-1] > 0.9 * b.periods[-1]
    assert pooled.segment_s == max(a.segment_s, b.segment_s)
    # A band only one of them reaches is that one's alone, not halved by a
    # zero from the other.
    beyond = pooled.periods > a.periods[-1]
    assert beyond.any()
    periods_b, power_b = b.binned(160)
    at = np.interp(np.log10(pooled.periods[beyond]), np.log10(periods_b), power_b)
    assert np.allclose(pooled.power[beyond], at)
    # Pooling one is that one; pooling nothing is nothing.
    assert average_spectra([a]) is a
    assert average_spectra([]) is None


def test_a_histogram_counts_the_implausible_only_when_it_is_asked_to():
    """The clamp is what a histogram leaves out, and unticking it must let the garbage in."""
    from overlap_viewer.algorithms.spectral import TransformParams, histogram

    assert TransformParams().clamp is True  # what a histogram is normally asked for
    values = np.concatenate([np.linspace(1.0e7, 1.1e7, 200), np.full(20, 9.0e12)])
    bounds = plausible_range("Pa")
    clamped = histogram(values, None, bins=20, bounds=bounds)
    assert clamped is not None
    assert clamped.total == 200 and clamped.left_out == 20
    assert clamped.edges[-1] <= bounds[1]
    # Unclamped, the caller passes no bounds at all: every reading is counted
    # and the bins have to stretch over the garbage to hold them.
    loose = histogram(values, None, bins=20, bounds=None)
    assert loose is not None
    assert loose.total == 220 and loose.left_out == 0
    assert loose.edges[-1] == pytest.approx(9.0e12)
    # The fullest bin is still the one the real readings fall in, though with
    # the bins now stretched over five orders of magnitude it is a wide one,
    # which is the honest picture of a sensor reporting 10¹² Pa.
    assert loose.peak[1] == 200
    assert loose.edges[0] <= bounds[1] <= loose.edges[1]


def test_a_stamp_is_searched_at_the_resolution_the_frame_is_indexed_in():
    """A view edge carries nanoseconds; a 3W file read through pyarrow is indexed in microseconds."""
    from overlap_viewer.backend.labels import at_index_unit

    index = pd.date_range(T0, periods=5, freq="1s", name="timestamp").as_unit("us")
    frame = pd.DataFrame({"P-PDG": np.arange(5.0)}, index=index)
    edge = T0 + pd.Timedelta("2s") + pd.Timedelta(1, unit="ns")
    # Pandas would rather raise than move the boundary silently.
    with pytest.raises(ValueError):
        frame.index.searchsorted(edge)
    rounded = at_index_unit(frame, edge)
    assert rounded.unit == "us"
    # The odd nanosecond is rounded away, which for a view edge is nothing.
    assert rounded == T0 + pd.Timedelta("2s")
    assert int(frame.index.searchsorted(rounded)) == 2
    # A frame already indexed in nanoseconds is left alone, and so is a non-timestamp.
    nanos = pd.DataFrame({"P-PDG": np.arange(5.0)}, index=index.as_unit("ns"))
    assert at_index_unit(nanos, edge) == edge
    assert at_index_unit(frame, None) is None


def test_the_peak_of_a_histogram_is_the_fullest_bin():
    """What the readings pile up at, which a skewed or two-humped shape hides from the mean."""
    from overlap_viewer.algorithms.spectral import Histogram, histogram

    # A long tail to the right: the mean is dragged out of the hump, the peak is not.
    values = np.concatenate([np.full(40, 1.0), np.linspace(2.0, 11.0, 10)])
    result = histogram(values, None, bins=10)
    assert result is not None
    peak, count = result.peak
    assert count == 40 and peak == pytest.approx(1.5, abs=0.6)
    assert result.mean > peak  # the tail moved the mean off the hump
    # Two humps: the peak names the taller one, where the median sits between them.
    two = histogram(np.concatenate([np.full(30, 0.0), np.full(20, 10.0)]), None, bins=11)
    assert two is not None and two.peak[0] == pytest.approx(0.0, abs=0.5)
    assert two.peak[1] == 30
    # A tie goes to the lower bin, so the answer does not depend on the summing.
    tie = histogram(np.array([0.0, 0.0, 1.0, 1.0]), None, bins=2)
    assert tie is not None and tie.peak == (pytest.approx(0.25), 2)
    assert Histogram(np.array([0.0, 1.0])).peak == (pytest.approx(np.nan, nan_ok=True), 0)


def test_the_optional_groups_are_declared_once_and_answer_for_themselves(monkeypatch):
    """pyproject.toml, extras.py and the README name the same groups, and a group says how to install itself."""
    import tomllib

    from overlap_viewer.backend import extras
    from overlap_viewer.backend.config import PROJECT_DIR

    declared = tomllib.loads((PROJECT_DIR / "pyproject.toml").read_text(encoding="utf-8"))
    groups = declared["project"]["optional-dependencies"]
    assert set(groups) == set(extras.EXTRAS), "pyproject.toml and extras.py disagree on the groups"
    readme = (PROJECT_DIR / "README.md").read_text(encoding="utf-8")
    for name, extra in extras.EXTRAS.items():
        assert extra.name == name
        # Tolerate the padding a markdown formatter puts in to align the columns.
        listed = re.search(rf"^\|\s*`{re.escape(name)}`\s*\|", readme, re.MULTILINE)
        assert listed, f"the README table does not list the {name} group"
        assert extra.enables in readme, f"the README does not say what {name} enables"
    # A group that imports answers None; one that does not says what and how.
    extras.forget()
    monkeypatch.setitem(extras.EXTRAS, "core", extras.Extra("core", ("numpy",), "everything"))
    assert extras.missing("core") is None and extras.available("core")
    monkeypatch.setitem(
        extras.EXTRAS, "ghost", extras.Extra("ghost", ("no_such_module_anywhere",), "nothing")
    )
    reason = extras.missing("ghost")
    assert reason is not None and not extras.available("ghost")
    assert "no_such_module_anywhere" in reason and extras.install_command("ghost") in reason
    extras.forget()
