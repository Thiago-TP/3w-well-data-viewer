"""Figures, tables and numbers of the Windows section of the workshop deck.

Usage
-----
From the root of the repository::

    uv run python docs/presentation/scripts/windows.py [--raw-dir PATH]

Writes into ``docs/presentation/tables/appendix/``:

``windows.csv``
    per well, its sensor, how many sensors tied for it, its normal and event
    windows of 512 samples, every statistic's separation at that size, and
    whether these rest on few windows;

and into ``docs/presentation/figures/windows/``:

``numbers.tex``
    every figure the slides quote, as ``\\wi...`` macros;
``statistics.csv``, ``medians.csv``
    every well's separation by every statistic at 512 samples, with the well's
    color on the viewer's pages and whether it rests on few windows, and per
    statistic its short name, the median over the wells and how many wells it
    is the best in at that size, for ``statistics.tikz`` to draw.

**The windows** are the page's (``algorithms.windows``): one sensor of every
instance of a well, laid end to end in chronological order, the samples an
earlier instance already holds left out, cut into windows of 256, 512 and
1024 samples, one label each, the end of a run padded. Every window is
described as the page describes it (``windows.describe_windows``, its padding
and missing readings left out); the twelve statistics are the ones the page's
*View* offers. A window is normal when its label is normal operation, an event
window when it is a transient or a steady state; unlabeled ones are left out.

**The separation** is the page's: ``|AUC − 0.5| · 2`` of a statistic for
telling event windows from normal ones, over the windows the statistic is
defined on, and only with ``MIN_WINDOWS`` of each kind (``windows.separation``).
A well's separations resting on fewer than ``FEW`` windows of a kind are set
apart: a hollow dot in the chart, an orange line in the appendix.

**The sensor** of a well is, as the issue asks, the analog one it records live
in the most samples; where several tie, the one whose best statistic
separates most, averaged over the three sizes, then the name. One sensor per
well, so that its three sizes compare.

**The best statistic** of a well and a size is the one of highest separation;
several often tie (a perfect split is often reached by several levels at
once), and each is then set in bold in the appendix and counted in the chart.

**The sizes**: the slides show 512 samples, the page's default; the other two
only enter as the median best separation at each size (``MedianSmall``,
``MedianLarge``) and how far they move a well's (``SizeWellMax``).
"""

import argparse
import sys
from pathlib import Path

import numpy as np
from timelines import number, write_csv

from well_data_viewer.algorithms import windows as wi
from well_data_viewer.backend import theme
from well_data_viewer.backend.availability import LIVE, sensor_state
from well_data_viewer.backend.dataset import DatasetInfo, load_catalogue, load_instance_columns
from well_data_viewer.backend.labels import label_kind, sensor_stats_from_json
from well_data_viewer.backend.palette import well_colors

ROOT = Path(__file__).resolve().parents[1]
FIGURES = ROOT / "figures" / "windows"
APPENDIX = ROOT / "tables" / "appendix"

# The statistics of the page's View, by what they read of a window: its level,
# its spread, or its shape (unchanged by the window's level and scale alike).
# (field of descriptors.Descriptors, name on the page, short name, group)
STATISTICS = (
    ("mean", "Mean", "Mean", "level"),
    ("median", "Median", "Median", "level"),
    ("low", "Min", "Min", "level"),
    ("q25", "Q1", "Q1", "level"),
    ("q75", "Q3", "Q3", "level"),
    ("high", "Max", "Max", "level"),
    ("std", "Std", "Std", "spread"),
    ("skew", "Skewness", "Skew", "shape"),
    ("kurtosis", "Kurtosis", "Kurt", "shape"),
    ("acf_half_s", "Autocorrelation time", "ACF", "shape"),
    ("snr", "Signal-to-noise ratio", "SNR", "shape"),
    ("gauss_slope", "Gaussianity slope", "Gauss", "shape"),
)
FIELDS = [field for field, *_ in STATISTICS]
SIZES = wi.SIZES
SHOWN = 512  # the page's default size, the one the chart and the appendix set
MIN_WINDOWS = 5  # the page's: no separation on fewer windows of a kind
FEW = 30  # below this many windows of a kind, a well's separations are set apart


def live_samples(part, info: DatasetInfo) -> dict[str, int]:
    """Per analog sensor, the samples the instances of a well record it live in."""
    live: dict[str, int] = {}
    for text, n_total in zip(part["sensor_stats"], part["n_samples"]):
        for sensor, (n, low, high) in sensor_stats_from_json(text).items():
            if not info.is_enumerated(sensor) and sensor_state(n, n_total, low, high) == LIVE:
                live[sensor] = live.get(sensor, 0) + n
    return live


def read_well(part, sensors: list[str]) -> dict[str, wi.WellSeries]:
    """Several sensors of every instance of a well, each as the page reads one."""
    passes = {sensor: wi.SeriesPass(sensor) for sensor in sensors}
    for k, (path, fault, file) in enumerate(zip(part["path"], part["fault_class"], part["file"])):
        frame = load_instance_columns(Path(path), [*sensors, "class"])
        ref = wi.InstanceRef(k, int(fault), str(file), str(file))
        for reader in passes.values():
            reader.add(frame, ref)
    return {sensor: reader.result() for sensor, reader in passes.items()}


def score(series: wi.WellSeries, info: DatasetInfo, size: int) -> dict:
    """Every statistic's separation of a sensor's windows of one size, and the windows of each kind."""
    w = series.windows(size)
    figures = wi.describe_windows(w.values, w.n_valid, scale=info.shown_scale(series.sensor))
    kinds = np.array([label_kind(v, info.transient_offset) for v in w.label])
    event = np.isin(kinds, ("transient", "steady"))
    normal = kinds == "normal"
    separations = {}
    for field in FIELDS:
        finite = np.isfinite(figures[field])
        e, n = event & finite, normal & finite
        if e.sum() >= MIN_WINDOWS and n.sum() >= MIN_WINDOWS:
            both = e | n
            separations[field] = wi.separation(figures[field][both], e[both])
        else:
            separations[field] = float("nan")
    described = np.isfinite(figures["mean"])
    return {
        "separations": separations,
        "normal": int((normal & described).sum()),
        "event": int((event & described).sum()),
        "windows": len(w),
    }


def best_of(separations: dict[str, float]) -> tuple[str | None, float, int]:
    """The statistic of highest separation (the first of ``STATISTICS`` on a tie), it, and how many tie."""
    finite = {f: v for f, v in separations.items() if np.isfinite(v)}
    if not finite:
        return None, float("nan"), 0
    top = max(finite.values())
    tied = [f for f in FIELDS if finite.get(f) == top]
    return tied[0], top, len(tied) - 1


def merit(scores: dict[int, dict]) -> float:
    """A tied sensor's claim: its best separation, averaged over the sizes that have one."""
    bests = [best_of(scores[size]["separations"])[1] for size in SIZES]
    bests = [b for b in bests if np.isfinite(b)]
    return float(np.mean(bests)) if bests else -1.0


def measure(catalogue, info: DatasetInfo) -> list[dict]:
    """Per well: its sensor, how many tied, and per size every statistic's separation."""
    theme.use("light")
    colors = well_colors(catalogue["well"])
    wells = []
    for well in sorted(set(catalogue["well"].tolist())):
        part = catalogue[catalogue["well"] == well].reset_index(drop=True)
        live = live_samples(part, info)
        top = max(live.values())
        tied = sorted(s for s, n in live.items() if n == top)
        series = read_well(part, tied)
        scores = {s: {size: score(series[s], info, size) for size in SIZES} for s in tied}
        sensor = min(tied, key=lambda s: (-merit(scores[s]), s))
        wells.append(
            {
                "well": int(well),
                "faults": sorted(set(part["fault_class"].astype(int).tolist())),
                "sensor": sensor,
                "tied": len(tied),
                "live": top,
                "scores": scores[sensor],
                "color": colors[well].lstrip("#").upper(),
            }
        )
        print(f"  WELL-{well:05d}: {sensor} (of {len(tied)} tied)", flush=True)
    return wells


def few(w: dict) -> bool:
    """Whether a well's separations at ``SHOWN`` rest on fewer than ``FEW`` windows of a kind."""
    sc = w["scores"][SHOWN]
    return best_of(sc["separations"])[0] is not None and min(sc["normal"], sc["event"]) < FEW


def tex_r(value: float) -> str:
    """A separation as the slides write it, two decimals; a dash for none."""
    return f"{value:.2f}" if np.isfinite(value) else r"\winil"


def write_appendix(path: Path, wells: list[dict]) -> None:
    """Every well's separations at ``SHOWN`` samples, its best in bold, with its windows and whether few."""
    rows = []
    for w in wells:
        sc = w["scores"][SHOWN]
        field, _value, _more = best_of(sc["separations"])
        top = sc["separations"].get(field, np.nan) if field else np.nan
        row = {
            "well": f"WELL-{w['well']:05d}",
            "sensor": w["sensor"],
            "tied": w["tied"],
            "normal": sc["normal"],
            "event": sc["event"],
            "few": int(few(w)),
        }
        for f in FIELDS:
            value = sc["separations"][f]
            text = tex_r(value)
            row[f] = f"\\textbf{{{text}}}" if np.isfinite(value) and value == top else text
        rows.append(row)
    write_csv(path, rows)


def write_chart(folder: Path, wells: list[dict]) -> dict[str, dict]:
    """The dots of ``statistics.tikz`` (every well, every statistic, at ``SHOWN``), medians and wins."""
    dots = []
    for w in wells:
        for k, field in enumerate(FIELDS):
            value = w["scores"][SHOWN]["separations"][field]
            if np.isfinite(value):
                dots.append(
                    {
                        "row": k,
                        "well": w["well"],
                        "separation": value,
                        "color": w["color"],
                        "few": int(few(w)),
                    }
                )
    write_csv(folder / "statistics.csv", dots)
    # A well counts for every statistic that reaches its best, ties included,
    # so that the order of STATISTICS decides no count.
    wins = dict.fromkeys(FIELDS, 0)
    for w in wells:
        separations = w["scores"][SHOWN]["separations"]
        _field, top, _more = best_of(separations)
        for field in FIELDS:
            if np.isfinite(top) and separations[field] == top:
                wins[field] += 1
    summary = {}
    rows = []
    for k, (field, name, short, group) in enumerate(STATISTICS):
        values = [d["separation"] for d in dots if d["row"] == k]
        median = float(np.median(values)) if values else float("nan")
        summary[field] = {"median": median, "wins": wins[field], "group": group}
        rows.append(
            {
                "row": k,
                "name": name,
                "short": short,
                "group": group,
                "median": median,
                "wins": wins[field],
            }
        )
    write_csv(folder / "medians.csv", rows)
    return summary


def ranges(numbers: list[int]) -> str:
    """Well numbers as the slides list them: runs joined by an en dash, the last after "and"."""
    runs, start = [], None
    for k, n in enumerate(numbers):
        if start is None:
            start = n
        if k + 1 == len(numbers) or numbers[k + 1] != n + 1:
            # A run of two is two wells, not a range.
            runs += (
                [f"{start}"]
                if start == n
                else [f"{start}", f"{n}"]
                if n == start + 1
                else [f"{start}--{n}"]
            )
            start = None
    return ", ".join(runs[:-1]) + f" and {runs[-1]}" if len(runs) > 1 else runs[0]


def write_numbers(path: Path, wells: list[dict], summary: dict[str, dict]) -> None:
    facts: dict[str, object] = {"Wells": len(wells), "MinWindows": MIN_WINDOWS, "Few": FEW}
    best = {w["well"]: {z: best_of(w["scores"][z]["separations"]) for z in SIZES} for w in wells}
    scored = [n for n in best if best[n][SHOWN][0]]
    unscored = [n for n in best if not best[n][SHOWN][0]]
    facts["Scored"] = len(scored)
    facts["Unscored"] = len(unscored)
    facts["UnscoredList"] = ranges(unscored)
    facts["Tied"] = sum(w["tied"] > 1 for w in wells)
    medians = {}
    for size, name in zip(SIZES, ("Small", "Mid", "Large")):
        values = [best[n][size][1] for n in scored if best[n][size][0]]
        medians[size] = float(np.median(values))
        facts[f"Median{name}"] = medians[size]
    facts["StrongMid"] = sum(best[n][SHOWN][1] >= 0.9 for n in scored)
    # How far the other sizes move a well's best separation (where the other
    # size has one).
    others = [z for z in SIZES if z != SHOWN]
    facts["SizeWellMax"] = max(
        abs(best[n][z][1] - best[n][SHOWN][1]) for n in scored for z in others if best[n][z][0]
    )
    # The wells whose best reads the window's level (the first of a tie; at
    # this size no tie mixes the groups).
    facts["LevelWins"] = sum(summary[best[n][SHOWN][0]]["group"] == "level" for n in scored)
    shape = [s["median"] for s in summary.values() if s["group"] == "shape"]
    levels = [s["median"] for s in summary.values() if s["group"] == "level"]
    facts["ShapeLow"], facts["ShapeHigh"] = min(shape), max(shape)
    facts["LevelLow"], facts["LevelHigh"] = min(levels), max(levels)
    facts["StdMedian"] = summary["std"]["median"]
    facts["ShapeWins"] = sum(s["wins"] for s in summary.values() if s["group"] == "shape")
    # The wells resting on few windows; their rows in the appendix's table
    # (from 0, in the order of ``wells``), which tables/appendix/windows.tex
    # sets apart.
    facts["FewWells"] = sum(few(w) for w in wells)
    facts["FewList"] = ranges([w["well"] for w in wells if few(w)])
    facts["FewRows"] = ",".join(str(k) for k, w in enumerate(wells) if few(w))
    lines = [
        "% Written by scripts/windows.py from the files of 3W; do not edit by hand.",
        *(f"\\newcommand{{\\wi{name}}}{{{fmt(value)}}}" for name, value in facts.items()),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def fmt(value) -> str:
    """A count as the slides write it, a separation with two decimals, text as it is."""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, np.integer)):
        return number(value)
    return f"{value:+.2f}".replace("+", "") if value >= 0 else f"\\textminus{{}}{abs(value):.2f}"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--raw-dir", type=Path, default=Path("../3W/dataset"))
    opts = parser.parse_args(argv)
    for folder in (FIGURES, APPENDIX):
        folder.mkdir(parents=True, exist_ok=True)

    info = DatasetInfo.load(opts.raw_dir)
    catalogue = load_catalogue(info)
    wells = measure(catalogue, info)

    write_appendix(APPENDIX / "windows.csv", wells)
    summary = write_chart(FIGURES, wells)
    write_numbers(FIGURES / "numbers.tex", wells, summary)
    print((FIGURES / "numbers.tex").read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
