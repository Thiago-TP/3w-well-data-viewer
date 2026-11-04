"""Figures and numbers of the Timelines section of the workshop deck.

Usage
-----
From the root of the repository::

    uv run python docs/presentation/scripts/timelines.py [--raw-dir PATH] [--no-shots]

Writes into ``docs/presentation/figures/timelines/``:

``numbers.tex``
    every figure the slides quote, as ``\\tl...`` macros, so that the text and
    the charts can never disagree;
``overlaps.csv``
    the wells whose instances overlap, with how many of their instances do;
``labels-pre-join.csv``
    per fault folder, the share of its files' time under each kind of label,
    every file apart, and how far its files get;
``labels-post-join.csv``
    the same shares once the overlapping files are joined, every instant of a
    joined history counted once (see ``joined_label_facts``);
``gaps.csv``
    the unlabeled stretches a joined history keeps, by kind;
``returns.csv``
    every return to normal operation along a joined history;
``well4_overlaps.png``, ``well4_restrictions.png``
    two crops of the viewer itself (skipped with ``--no-shots``).

Everything but the crops comes from the catalogue the viewer caches (the label
runs and time span of every real instance), so it takes seconds and reads no
sensor data. The crops are rendered offscreen by ``offscreen.py``; they read
the instances of WELL-00004 they show.

What the section calls things
-----------------------------
*Overlapping*: two instances of one well sharing at least one timestamp. A
*label collision*: an overlap in which the two files give the same instant two
different known labels. *Joined*: the viewer's *Join overlapping instances*,
which reads overlapping instances whose labels agree as the one recording they
were cut from (``WellData.joined``); a *joined history* is one such recording,
its labels merged by ``labels.merge_label_runs``. Its unlabeled stretches are a
*head* (before the first label), a *seam* (between two runs of the same label)
or a *change* (between two different labels); ``appendix.py`` lists the last.
"""

import argparse
import csv
import sys
from collections import Counter
from itertools import pairwise
from pathlib import Path

import numpy as np
import pandas as pd

from overlap_viewer.backend.dataset import DatasetInfo, WellData, load_catalogue, split_wells
from overlap_viewer.backend.labels import (
    label_fault,
    label_kind,
    labels_agree,
    merge_label_runs,
    segments_from_json,
)

OUT = Path(__file__).resolve().parents[1] / "figures" / "timelines"

# The case the third frame opens in the viewer: the last three instances of
# WELL-00004, three quick restrictions of the production choke in 75 minutes.
CASE_WELL = 4
CASE_FILES = (
    "WELL-00004_20171031171509.parquet",
    "WELL-00004_20171031181500.parquet",
    "WELL-00004_20171031184839.parquet",
)
CASE_SENSORS = ["P-MON-CKP", "ABER-CKP"]

KINDS = ("normal", "transient", "steady", "unknown")


# -- Facts -------------------------------------------------------------------


def joined_history(well: WellData, bar: int) -> list[list]:
    """The label runs of one joined bar, coalesced: ``[start, end, value, folders]`` each.

    ``merge_label_runs`` keeps apart two runs of one value that came from
    different files; here they are one run, the files that supplied it kept in
    ``folders`` (the fault folder of each).
    """
    origin = well.origin
    members = well.joined().members[bar]
    tracks = [segments_from_json(origin.rows["class_runs"].iloc[m]) for m in members]
    folders = [int(origin.rows["fault_class"].iloc[m]) for m in members]
    runs: list[list] = []
    for segment, folder in merge_label_runs(tracks, folders):
        value = segment.value
        last = runs[-1] if runs else None
        if last is not None and (value == last[2] or (np.isnan(value) and np.isnan(last[2]))):
            last[1] = segment.end
            last[3].append(folder)
        else:
            runs.append([segment.start, segment.end, value, [folder]])
    return runs


def label_text(value: float, info: DatasetInfo) -> str:
    """A ``class`` value as the slides name it: the fault, and its state unless normal."""
    kind = label_kind(value)
    if kind == "unknown":
        return "unlabeled"
    if kind == "normal":
        return "normal"
    return f"{info.fault_name(label_fault(value))} ({kind})"


def overlap_facts(catalogue: pd.DataFrame, wells: list[WellData]) -> tuple[dict, list[dict]]:
    """How the instances of each well overlap, and whether their labels collide where they do."""
    per_well = []
    pairs = collisions = across_folders = 0
    for well in wells:
        rows = well.rows
        tracks = [segments_from_json(text) for text in rows["class_runs"]]
        for i in range(len(rows)):
            for j in well.partners[i]:
                if j <= i:
                    continue
                pairs += 1
                across_folders += int(rows["fault_class"].iloc[i] != rows["fault_class"].iloc[j])
                collisions += int(not labels_agree(tracks[i], tracks[j]))
        if well.n_overlapping:
            per_well.append(
                {
                    "well": well.well,
                    "label": f"WELL-{well.well:05d}",
                    "instances": well.n_instances,
                    "overlapping": well.n_overlapping,
                    "apart": well.n_instances - well.n_overlapping,
                    "tag": f"{well.n_overlapping}/{well.n_instances}",
                }
            )
    rows_total = int(catalogue["n_samples"].sum())
    distinct = sum(int(well.joined().rows["n_samples"].sum()) for well in wells)
    facts = {
        "Wells": len(wells),
        "WellsOverlapping": len(per_well),
        "WellsApart": len(wells) - len(per_well),
        "Instances": len(catalogue),
        "InstancesOverlapping": sum(w["overlapping"] for w in per_well),
        "Pairs": pairs,
        "PairsAcrossFolders": across_folders,
        "Collisions": collisions,
        "StackedAfterJoin": sum(well.joined().n_lanes > 1 for well in wells),
        "Rows": rows_total,
        "RowsDistinct": distinct,
        "RowsTwice": rows_total - distinct,
        "RowsTwiceShare": 100.0 * (rows_total - distinct) / rows_total,
        "JoinedBars": sum(well.joined().n_instances for well in wells),
    }
    per_well.sort(key=lambda w: (-w["overlapping"], w["well"]))
    return facts, per_well


def label_facts(catalogue: pd.DataFrame, info: DatasetInfo) -> list[dict]:
    """Per fault folder, every file apart: the time under each kind of label, and how far its files get."""
    table = []
    for folder in sorted(catalogue["fault_class"].unique()):
        part = catalogue[catalogue["fault_class"] == folder]
        seconds = Counter()
        for text in part["class_runs"]:
            for segment in segments_from_json(text):
                seconds[label_kind(segment.value)] += (segment.end - segment.start).total_seconds()
        total = sum(seconds.values())
        reach = Counter(part["reach"])
        table.append(
            {
                "folder": int(folder),
                "name": info.fault_name(int(folder)),
                "files": len(part),
                "hours": total / 3600.0,
                **{kind: 100.0 * seconds[kind] / total for kind in KINDS},
                # How far each file gets: its reach, the strongest label it carries.
                "reach_normal": reach["normal"],
                "reach_transient": reach["transient"],
                "reach_steady": reach["steady"],
            }
        )
    return table


def joined_label_facts(wells: list[WellData], info: DatasetInfo) -> list[dict]:
    """Per fault folder, the files joined: the time under each kind of label.

    Every instant of a joined history is counted once, for the folder of the
    file its label comes from (the earliest file that labels it, the rule of
    ``merge_label_runs``); an instant no file labels is counted for the
    earliest file that covers it, whose unlabeled head it is. What changes from
    the files apart is what the join changes: the instants two files shared are
    no longer counted twice, and the unlabeled head of a file is labeled by the
    file before it wherever that one covers it.
    """
    seconds: dict[int, Counter] = {}
    for well in wells:
        origin, joined = well.origin, well.joined()
        for members in joined.members:
            tracks = [segments_from_json(origin.rows["class_runs"].iloc[m]) for m in members]
            folders = [int(origin.rows["fault_class"].iloc[m]) for m in members]
            spans = [(track[0].start, track[-1].end) for track in tracks]
            for segment, folder in merge_label_runs(tracks, folders):
                if folder is None:
                    folder = next(f for (a, b), f in zip(spans, folders) if a <= segment.start < b)
                elapsed = (segment.end - segment.start).total_seconds()
                seconds.setdefault(folder, Counter())[label_kind(segment.value)] += elapsed
    table = []
    for folder in sorted(seconds):
        total = sum(seconds[folder].values())
        table.append(
            {
                "folder": folder,
                "name": info.fault_name(folder),
                "hours": total / 3600.0,
                **{kind: 100.0 * seconds[folder][kind] / total for kind in KINDS},
            }
        )
    return table


def gap_facts(catalogue: pd.DataFrame, wells: list[WellData]) -> tuple[dict, list[dict]]:
    """The unlabeled stretches before and after the join, the latter by kind."""
    before = sum(
        (s.end - s.start).total_seconds()
        for text in catalogue["class_runs"]
        for s in segments_from_json(text)
        if np.isnan(s.value)
    )
    heads_per_file = Counter(
        round((segments_from_json(text)[0].end - segments_from_json(text)[0].start).total_seconds())
        for text in catalogue["class_runs"]
        if np.isnan(segments_from_json(text)[0].value)
    )
    gaps = []
    for well in wells:
        for bar in range(well.joined().n_instances):
            runs = joined_history(well, bar)
            for k, (start, end, value, _) in enumerate(runs):
                if not np.isnan(value):
                    continue
                before_value = runs[k - 1][2] if k > 0 else None
                after_value = runs[k + 1][2] if k + 1 < len(runs) else None
                if before_value is None:
                    kind = "head"
                elif after_value is None:
                    kind = "tail"
                elif before_value == after_value:
                    kind = "seam"
                else:
                    kind = "change"
                gaps.append((kind, (end - start).total_seconds(), after_value))
    after = sum(seconds for _, seconds, _ in gaps)
    table = []
    for kind in ("head", "seam", "change", "tail"):
        durations = np.array([s for k, s, _ in gaps if k == kind])
        if not len(durations):
            continue
        table.append(
            {
                "kind": kind,
                "count": len(durations),
                "share": 100.0 * durations.sum() / after,
                "median_s": float(np.median(durations)),
                "min_s": float(durations.min()),
                "max_s": float(durations.max()),
            }
        )
    heads_into_normal = sum(1 for k, _, nxt in gaps if k == "head" and nxt == 0)
    distinct = sum(int(well.joined().rows["n_samples"].sum()) for well in wells)
    facts = {
        "UnlabeledBefore": 100.0 * before / catalogue["n_samples"].sum(),
        "UnlabeledBeforeHours": round(before / 3600.0),
        "FilesWithUnlabeledHour": heads_per_file.get(3600, 0),
        "UnlabeledAfter": 100.0 * after / distinct,
        "UnlabeledAfterHours": round(after / 3600.0),
        "Gaps": len(gaps),
        "HeadsIntoNormal": heads_into_normal,
    }
    return facts, table


def return_facts(
    catalogue: pd.DataFrame, wells: list[WellData], info: DatasetInfo
) -> tuple[dict, list[dict]]:
    """Every return to normal operation: along one file's labels, and along a joined history."""
    within_files = 0
    for text in catalogue["class_runs"]:
        known = [s.value for s in segments_from_json(text) if not np.isnan(s.value)]
        within_files += sum(
            1 for a, b in pairwise(known) if label_kind(a) in ("steady", "transient") and b == 0
        )
    table = []
    for well in wells:
        for bar in range(well.joined().n_instances):
            known = [run for run in joined_history(well, bar) if not np.isnan(run[2])]
            for (_, end, value, folders), (start, _, after, after_folders) in pairwise(known):
                if label_kind(value) not in ("steady", "transient") or after != 0:
                    continue
                table.append(
                    {
                        "well": well.well,
                        "label": f"WELL-{well.well:05d}",
                        "at": str(pd.Timestamp(end).floor("s")),
                        "fault": info.fault_name(label_fault(value)),
                        "kind": label_kind(value),
                        "after_s": (start - end).total_seconds(),
                        "from_folder": folders[-1],
                        "to_folder": after_folders[0],
                    }
                )
    facts = {
        "ReturnsWithinFiles": within_files,
        "Returns": len(table),
        "ReturnsWells": len({row["well"] for row in table}),
        "ReturnsAcrossFolders": sum(row["from_folder"] != row["to_folder"] for row in table),
    }
    return facts, table


# -- Writing -----------------------------------------------------------------


def duration(seconds: float) -> str:
    """A duration as the slides write it: ``76 s``, ``6 min``, ``1 h``.

    The thin space is ``\\thinspace``, not ``\\,``, whose comma would split a
    cell of the CSV tables pgfplots reads.
    """
    if seconds < 90:
        return f"{seconds:.0f}\\thinspace{{}}s"
    if seconds < 3600 - 30:
        return f"{seconds / 60:.0f}\\thinspace{{}}min"
    return f"{seconds / 3600:.0f}\\thinspace{{}}h"


def number(value) -> str:
    """A figure as the slides write it: thousands separated, shares to one decimal."""
    if isinstance(value, (int, np.integer)):
        return f"{int(value):,}"
    return f"{value:,.1f}"


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        for row in rows:
            writer.writerow({k: round(v, 3) if isinstance(v, float) else v for k, v in row.items()})


def write_numbers(path: Path, facts: dict, labels: list[dict], gaps: list[dict]) -> None:
    lines = [
        "% Written by scripts/timelines.py from the catalogue of 3W; do not edit by hand.",
        *(f"\\newcommand{{\\tl{name}}}{{{number(value)}}}" for name, value in facts.items()),
    ]
    for row in gaps:
        key = row["kind"].capitalize()
        lines += [
            f"\\newcommand{{\\tlGap{key}Count}}{{{number(row['count'])}}}",
            f"\\newcommand{{\\tlGap{key}Share}}{{{number(row['share'])}}}",
            f"\\newcommand{{\\tlGap{key}Median}}{{{duration(row['median_s'])}}}",
            f"\\newcommand{{\\tlGap{key}Max}}{{{duration(row['max_s'])}}}",
        ]
    service = next(row for row in labels if row["folder"] == 9)
    scaling = next(row for row in labels if row["folder"] == 7)
    lines += [
        f"\\newcommand{{\\tlServiceFiles}}{{{service['files']}}}",
        f"\\newcommand{{\\tlServiceOnlyNormal}}{{{service['reach_normal']}}}",
        f"\\newcommand{{\\tlServiceNormalShare}}{{{service['normal']:.0f}}}",
        f"\\newcommand{{\\tlServiceSteadyShare}}{{{service['steady']:.1f}}}",
        f"\\newcommand{{\\tlScalingFiles}}{{{scaling['files']}}}",
        f"\\newcommand{{\\tlScalingNeverSteady}}{{{scaling['files'] - scaling['reach_steady']}}}",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# -- The crops of the viewer -------------------------------------------------


def take_shots(raw_dir: Path, out: Path) -> None:
    """Render the two crops offscreen: WELL-00004's timeline, and the instance window of its last bar.

    Both are rendered at a window size close to the space they take on a slide,
    so that their text is neither shrunk into illegibility nor blurred.
    """
    import offscreen

    window = offscreen.main_window(raw_dir)

    # The first day of WELL-00004 as the Timelines page draws it: windows of
    # three hours, a new one every two, stacked on two lanes, so that nearly
    # every hour of the well is in two files.
    plot = window.timelines._plots[CASE_WELL]
    rows = plot.data.rows
    first = rows[rows["start"] < rows["start"].min() + pd.Timedelta(hours=24)]
    x = plot.timemap.to_x(
        np.array([first["start"].min(), first["end"].max()], dtype="datetime64[ns]")
    )
    plot.resize(820, 96)
    plot.getViewBox().setXRange(float(x[0]), float(x[1]), padding=0.01)
    # The well's deepest pile-up is three, at its last three instances; this
    # day uses two lanes (0 and 1, labeled 1 and 2), and the third would only be blank.
    plot.getViewBox().setYRange(-0.55, 1.55, padding=0)
    offscreen.settle(1.0)
    plot.grab().save(str(out / "well4_overlaps.png"))
    print(f"  saved {out / 'well4_overlaps.png'}", flush=True)

    # The three quick restrictions, joined, on the sensors a choke moves; from
    # 18:00, the last quarter of the unlabeled hour the joined recording opens
    # with, so that the three labeled restrictions get the width.
    joined = next(w for w in window._wells if w.well == CASE_WELL).joined()
    bar = next(
        b
        for b in range(joined.n_instances)
        if {joined.origin.rows["file"].iloc[m] for m in joined.members[b]} == set(CASE_FILES)
    )
    offscreen.save_stack(
        window,
        CASE_WELL,
        bar,
        CASE_SENSORS,
        ("2017-10-31T18:00:00", "2017-10-31T20:29:30"),
        (900, 660),
        out / "well4_restrictions.png",
    )
    window.close()


# -- Main --------------------------------------------------------------------


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--raw-dir", type=Path, default=Path("../3W/dataset"))
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--no-shots", action="store_true", help="skip the crops of the viewer")
    opts = parser.parse_args(argv)
    opts.out.mkdir(parents=True, exist_ok=True)

    info = DatasetInfo.load(opts.raw_dir)
    catalogue = load_catalogue(info)
    wells = split_wells(catalogue)

    facts, overlaps = overlap_facts(catalogue, wells)
    gap_numbers, gaps = gap_facts(catalogue, wells)
    labels = label_facts(catalogue, info)
    return_numbers, returns = return_facts(catalogue, wells, info)
    facts |= gap_numbers | return_numbers

    write_csv(opts.out / "overlaps.csv", overlaps)
    write_csv(opts.out / "labels-pre-join.csv", labels)
    write_csv(opts.out / "labels-post-join.csv", joined_label_facts(wells, info))
    write_csv(opts.out / "gaps.csv", gaps)
    write_csv(opts.out / "returns.csv", returns)
    write_numbers(opts.out / "numbers.tex", facts, labels, gaps)
    for name, value in facts.items():
        print(f"  {name:24s} {number(value)}")
    print(f"  written to {opts.out}", flush=True)

    if not opts.no_shots:
        take_shots(info.raw_dir, opts.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
