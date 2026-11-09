"""Figures, tables and numbers of the Instances section of the workshop deck.

Usage
-----
From the root of the repository::

    uv run python docs/presentation/scripts/instances.py [--raw-dir PATH]

Writes into ``docs/presentation/figures/instances/``:

``numbers.tex``
    every figure the slides quote, as ``\\is...`` macros, with the viewer's
    color of every fault class and, per map, its neighbour figures;
``maps/<rep><mode><emb>.csv``
    one per map: per representation (``d`` the descriptors, ``s`` the same
    less the levels), descriptor mode (``i`` interpolated, ``m``
    measurements) and embedding (``pca``, ``tsne``, ``umap``); per real
    instance its place (``x``, ``y``, the map scaled into the box of
    ``ASPECT`` by 1 the slides draw it in, its proportions kept), its fault
    class and the class its well's past names (``pred``; ``FIRST`` for a
    well's first instance, which has no past); the normal instances first,
    so that the faults are drawn over them;

into ``docs/presentation/tables/instances/``:

``legend.csv``
    the fault classes, ``LEGEND_COLUMNS`` to a row, each its dot, number and
    name (``\\isentry``), for the legend over the first maps;
``wellpast.csv``
    per fault class, its instances with a past in their well, how many of
    these the well's past names right, and what share;

and into ``docs/presentation/tables/appendix/``:

``descriptors.csv``
    per descriptor of a sensor, what it reads of the signal and which of the
    two representations takes it;
``embeddings.csv``
    per representation and data, its columns, the variance PCA's two axes
    carry, and how many of an instance's ``KEEP`` nearest neighbours in the
    columns each embedding keeps among its ``KEEP`` nearest on the plane.

**The maps** are the Instances page's (``algorithms.embedding``): every real
instance a point, represented by its descriptors taken on its labeled samples
alone (``feature_matrix(..., labeled=True)``), interpolated or measured, with
or without the levels, laid on the plane by PCA, t-SNE or UMAP, with the
page's settings and seeds. The profiles are the viewer's cached profile pass;
the first run without a current one reads the data, as the page does (some
minutes), and leaves the cache for the viewer.

**The neighbours.** On a map, an instance's nearest neighbour (Euclidean, on
the plane) shares its well, or its fault; and the nearest instance of another
well shares its fault. Chance, for the fault, is the probability that two
different instances drawn at random share it, the second drawn from those
left: the sum, over the classes, of ``n_c (n_c - 1) / (N (N - 1))``.

**The well's past** names an instance by the class seen most among the
earlier instances of its well (by their start), the most recent of a tie; a
well's first instance has no past, and is left out of the scores. It reads no
signal at all: what a model could learn by spotting the well.
"""

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

import numpy as np
from timelines import number, write_csv

from well_data_viewer.algorithms import embedding as em
from well_data_viewer.algorithms.profiles import load_profiles
from well_data_viewer.backend import theme
from well_data_viewer.backend.dataset import DatasetInfo, load_catalogue, split_wells
from well_data_viewer.backend.palette import fault_color

ROOT = Path(__file__).resolve().parents[1]
FIGURES = ROOT / "figures" / "instances"
TABLES = ROOT / "tables" / "instances"
APPENDIX = ROOT / "tables" / "appendix"

# The maps: (key, representation, measured, name) and the embeddings. (No
# comma in a name: the CSV tables are read by pgfplotstable, which takes no
# quotes.)
REPRESENTATIONS = (
    ("di", "descriptors", False, "Descriptors"),
    ("dm", "descriptors", True, "Descriptors"),
    ("si", "shape", False, "Shape only"),
    ("sm", "shape", True, "Shape only"),
)
DATA = {False: "interpolated", True: "measurements"}
EMBEDDINGS = (("pca", "PCA"), ("tsne", "t-SNE"), ("umap", "UMAP"))
ASPECT = 1.6  # width over height of a map on the slides
# The class of a well's first instance in the well's past, which has none: a
# number, as the slides filter the dots of a class by its number.
FIRST = 10
KEEP = 10  # the neighbourhood an embedding is asked to keep
LEGEND_COLUMNS = 5

# The descriptors of an analog sensor (embedding.LEVEL_FIELDS, SHAPE_FIELDS,
# SAMPLING_FIELDS), as the appendix names them.
DESCRIPTOR_NAMES = {
    "mean": "Mean",
    "std": "Standard deviation",
    "median": "Median",
    "q05": "5th percentile",
    "q95": "95th percentile",
    "skew": "Skewness",
    "kurtosis": "Kurtosis",
    "acf_half_s": "Autocorrelation time",
    "snr": "Signal-to-noise ratio",
    "gauss_slope": "Gaussianity slope",
    "genuine_share": "Share of samples measured",
    "spacing_s": "Spacing of the measurements",
}


def points_of(wells) -> list[dict]:
    """Every real instance, as the page lists its points: well by well, in the well's order."""
    points = []
    for well in wells:
        for k in range(len(well.rows)):
            row = well.rows.iloc[k]
            points.append(
                {
                    "key": (int(row["fault_class"]), str(row["file"])),
                    "fault": int(row["fault_class"]),
                    "well": int(well.well),
                    "start": row["start"],
                }
            )
    return points


def neighbours(coords: np.ndarray, fault: np.ndarray, well: np.ndarray) -> dict[str, float]:
    """How often the nearest neighbour shares the well, the fault, and the fault across wells."""
    D = em.euclidean_distances(coords)
    np.fill_diagonal(D, np.inf)
    nearest = D.argmin(axis=1)
    D[well[:, None] == well[None, :]] = np.inf
    across = D.argmin(axis=1)
    return {
        "well": float((well[nearest] == well).mean()),
        "fault": float((fault[nearest] == fault).mean()),
        "across": float((fault[across] == fault).mean()),
    }


def nearest(X: np.ndarray, k: int = KEEP) -> np.ndarray:
    """Per point, its ``k`` nearest others (Euclidean), in no order."""
    D = em.euclidean_distances(X)
    np.fill_diagonal(D, np.inf)
    return np.argpartition(D, k, axis=1)[:, :k]


def kept(columns: np.ndarray, plane: np.ndarray, k: int = KEEP) -> float:
    """The share of a point's ``k`` nearest neighbours in the columns still among its ``k`` on the plane."""
    a, b = nearest(columns, k), nearest(plane, k)
    return float(np.mean([len(set(x) & set(y)) / k for x, y in zip(a, b)]))


def well_past(points: list[dict]) -> np.ndarray:
    """Per instance, the class seen most among the earlier instances of its well; -1 for none."""
    pred = np.full(len(points), -1)
    order = sorted(range(len(points)), key=lambda i: (points[i]["well"], points[i]["start"]))
    seen: dict[int, list[int]] = {}
    for i in order:
        past = seen.setdefault(points[i]["well"], [])
        if past:
            counts = Counter(past)
            top = max(counts.values())
            pred[i] = next(c for c in reversed(past) if counts[c] == top)
        past.append(points[i]["fault"])
    return pred


def into_box(coords: np.ndarray) -> np.ndarray:
    """A map scaled into the box ``[0, ASPECT] × [0, 1]`` the slides draw, centred, its proportions kept."""
    low, high = coords.min(axis=0), coords.max(axis=0)
    span = np.maximum(high - low, 1e-12)
    scale = min(ASPECT / span[0], 1.0 / span[1])
    return (coords - (low + high) / 2) * scale + np.array([ASPECT / 2, 0.5])


def measure(info: DatasetInfo) -> tuple[list[dict], np.ndarray, dict]:
    catalogue = load_catalogue(info)
    wells = split_wells(catalogue)
    profiles = load_profiles(info, wells, info.sensor_names, cache_only=True)
    if profiles is None:
        print("  no current profile pass in the cache: reading the data, some minutes", flush=True)
        profiles = load_profiles(info, wells, info.sensor_names)
    points = points_of(wells)
    keys = [p["key"] for p in points]
    fault = np.array([p["fault"] for p in points])
    well = np.array([p["well"] for p in points])
    maps = {}
    for key, rep_name, measured, name in REPRESENTATIONS:
        rep = em.feature_matrix(
            profiles,
            keys,
            False,
            info,
            shape_only=rep_name == "shape",
            measured=measured,
            labeled=True,
        )
        maps[key] = {
            "name": name,
            "measured": measured,
            "sensors": list(rep.sensors),
            "columns": list(rep.columns),
            "imputed": float(rep.imputed.mean()),
            "variance": em.pca(rep.X)[1],
        }
        for emb, emb_name in EMBEDDINGS:
            coords, caption = em.embed(rep, emb_name)
            coords = np.asarray(coords, dtype=float)
            maps[key][emb] = {
                "coords": into_box(coords),
                "caption": caption,
                "scores": neighbours(coords, fault, well),
                "kept": kept(rep.X, coords),
            }
            print(f"  {name}, {DATA[measured]}, {emb_name}: {maps[key][emb]['scores']}", flush=True)
    return points, well_past(points), maps


def pct(value: float) -> str:
    """A share as the slides write it, a whole percent."""
    return f"{100 * value:.0f}\\%"


def listed(names: list[str]) -> str:
    """Names as the slides list them, the last after "and"."""
    return ", ".join(names[:-1]) + f" and {names[-1]}" if len(names) > 1 else "".join(names)


def write_maps(folder: Path, points: list[dict], pred: np.ndarray, maps: dict) -> None:
    """One small table per map, as the slides read a map class by class: a pass over few columns."""
    folder.mkdir(parents=True, exist_ok=True)
    order = sorted(range(len(points)), key=lambda i: (points[i]["fault"] != 0, i))
    for key, *_ in REPRESENTATIONS:
        for emb, _name in EMBEDDINGS:
            rows = []
            for i in order:
                x, y = maps[key][emb]["coords"][i]
                rows.append(
                    {
                        "x": float(x),
                        "y": float(y),
                        "fault": points[i]["fault"],
                        "pred": int(pred[i]) if pred[i] >= 0 else FIRST,
                    }
                )
            write_csv(folder / f"{key}{emb}.csv", rows)


def write_legend(path: Path, points: list[dict], info: DatasetInfo) -> None:
    """The fault classes, ``LEGEND_COLUMNS`` to a row, in reading order."""
    entries = [
        f"\\isentry{{{k}}}{{{info.fault_name(k)}}}" for k in sorted({p["fault"] for p in points})
    ]
    rows = []
    for start in range(0, len(entries), LEGEND_COLUMNS):
        cells = entries[start : start + LEGEND_COLUMNS]
        cells += [""] * (LEGEND_COLUMNS - len(cells))
        rows.append({f"c{j + 1}": cell for j, cell in enumerate(cells)})
    write_csv(path, rows)


def write_wellpast(path: Path, points: list[dict], pred: np.ndarray, info: DatasetInfo) -> None:
    """Per class, its instances with a past, and how many of these the well's past names right."""
    fault = np.array([p["fault"] for p in points])
    rows = []
    for k in sorted(set(fault.tolist())):
        past = (fault == k) & (pred >= 0)
        right = int((pred[past] == k).sum())
        rows.append(
            {
                "dot": f"\\isdot{{{k}}}",
                "fault": k,
                "name": info.fault_name(k),
                "past": int(past.sum()),
                "right": right,
                "share": pct(right / past.sum()) if past.any() else r"--",
            }
        )
    write_csv(path, rows)


def write_descriptors(path: Path) -> None:
    """Per descriptor of an analog sensor, what it reads and which representation takes it."""
    reads = {
        **dict.fromkeys(em.LEVEL_FIELDS, "level"),
        **dict.fromkeys(em.SHAPE_FIELDS, "shape"),
        **dict.fromkeys(em.SAMPLING_FIELDS, "sampling"),
    }
    rows = []
    for field, read in reads.items():
        log = " (log)" if field in em.LOG_FIELDS else ""
        rows.append(
            {
                "descriptor": DESCRIPTOR_NAMES[field] + log,
                "reads": read,
                "descriptors": r"\checkmark",
                "shape": "" if read == "level" else r"\checkmark",
            }
        )
    write_csv(path, rows)


def write_embeddings(path: Path, maps: dict) -> None:
    """Per representation and data: its columns, PCA's variance, and the neighbours each embedding keeps."""
    rows = []
    for key, _rep, measured, name in REPRESENTATIONS:
        m = maps[key]
        rows.append(
            {
                "representation": name,
                "data": DATA[measured],
                "columns": len(m["columns"]),
                "imputed": pct(m["imputed"]),
                "variance": f"{pct(m['variance'][0])} + {pct(m['variance'][1])}",
                **{emb: pct(m[emb]["kept"]) for emb, _name in EMBEDDINGS},
            }
        )
    write_csv(path, rows)


def write_numbers(path: Path, points: list[dict], pred: np.ndarray, maps: dict) -> str:
    fault = np.array([p["fault"] for p in points])
    counts = np.bincount(fault)
    n = len(points)
    classes = [int(c) for c in np.flatnonzero(counts)]
    pairs = sum(int(counts[c]) * (int(counts[c]) - 1) for c in classes)
    chance = pairs / (n * (n - 1))
    terms = [f"{tex_math(int(counts[c]))} \\cdot {tex_math(int(counts[c]) - 1)}" for c in classes]
    facts: dict[str, object] = {
        "Instances": n,
        "Wells": len({p["well"] for p in points}),
        # Chance: the probability that two different instances drawn at random
        # (the second from those left) share a class, spelt out for the
        # appendix: its first two terms and its last, in math mode.
        "Chance": pct(chance),
        "ChanceTerms": " + ".join([*terms[:2], r"\dots", terms[-1]]),
        "ChanceFirst": classes[0],
        "ChanceLast": classes[-1],
        "ChancePairs": int(pairs),
        "ChanceTotalTerms": f"{tex_math(n)} \\cdot {tex_math(n - 1)}",
        "ChanceTotal": int(n * (n - 1)),
        "ChanceExact": f"{chance:.3f}",
        "Sensors": len(maps["di"]["sensors"]),
        "SensorList": listed(maps["di"]["sensors"]),
        "Coverage": pct(em.MIN_SENSOR_COVERAGE),
        "Columns": len(maps["di"]["columns"]),
        "ShapeColumns": len(maps["si"]["columns"]),
        "Keep": KEEP,
        "Seed": em.RANDOM_STATE,
    }
    # The embeddings' settings, as the page's captions state them.
    facts["Perplexity"] = re.search(r"perplexity (\S+)", maps["di"]["tsne"]["caption"]).group(1)
    facts["UmapNeighbours"] = re.search(r"(\d+) neighbours", maps["di"]["umap"]["caption"]).group(1)
    # Per map: its three figures, as \isScore{rep}{emb}{kind} reads them.
    lines = []
    for key, *_ in REPRESENTATIONS:
        for emb, _name in EMBEDDINGS:
            for kind, value in maps[key][emb]["scores"].items():
                lines.append(
                    f"\\expandafter\\def\\csname is@{key}@{emb}@{kind}\\endcsname{{{pct(value)}}}"
                )
    # Per data: on how many maps the well beats the fault, and the fault across wells.
    for measured, suffix in ((False, "Interp"), (True, "Meas")):
        scores = [
            maps[key][emb]["scores"]
            for key, _rep, m, _name in REPRESENTATIONS
            if m == measured
            for emb, _ in EMBEDDINGS
        ]
        facts[f"Maps{suffix}"] = len(scores)
        facts[f"WellWins{suffix}"] = sum(s["well"] > s["fault"] for s in scores)
        facts[f"AcrossLow{suffix}"] = pct(min(s["across"] for s in scores))
        facts[f"AcrossHigh{suffix}"] = pct(max(s["across"] for s in scores))
    # The map that best gathers the faults, the one the well's past is set beside.
    best = max(
        ((key, emb) for key, *_ in REPRESENTATIONS for emb, _ in EMBEDDINGS),
        key=lambda ke: maps[ke[0]][ke[1]]["scores"]["fault"],
    )
    facts["BestRep"] = maps[best[0]]["name"]
    facts["BestData"] = DATA[maps[best[0]]["measured"]]
    facts["BestEmb"] = dict(EMBEDDINGS)[best[1]]
    facts["BestKey"] = best[0] + best[1]
    # The well's past.
    past = pred >= 0
    facts["PastInstances"] = int(past.sum())
    facts["FirstInstances"] = int((~past).sum())
    facts["PastRight"] = int((pred[past] == fault[past]).sum())
    facts["PastShare"] = pct(float((pred[past] == fault[past]).mean()))
    faults = past & (fault != 0)
    facts["PastFaults"] = pct(float((pred[faults] == fault[faults]).mean()))
    facts["PastFaultCount"] = int(faults.sum())
    facts["Majority"] = pct(float((fault[past] == 0).mean()))
    # The classes each coloring holds, in the order the slides draw them: the
    # normal instances first, a well's first instances last.
    facts["Classesfault"] = ",".join(str(k) for k in sorted(set(fault.tolist())))
    named = sorted(set(pred.tolist()) - {-1}) + ([FIRST] if (~past).any() else [])
    facts["Classespred"] = ",".join(str(k) for k in named)
    theme.use("light")
    text = [
        "% Written by scripts/instances.py from the viewer's profile pass; do not edit by hand.",
        *(f"\\newcommand{{\\is{name}}}{{{fmt(value)}}}" for name, value in facts.items()),
        "% The color of every fault class on the viewer's pages (palette.fault_color).",
        *(
            f"\\definecolor{{isc{k}}}{{HTML}}{{{fault_color(k).lstrip('#').upper()}}}"
            for k in sorted(set(fault.tolist()))
        ),
        "% Per map: \\isScore{di|dm|si|sm}{pca|tsne|umap}{well|fault|across}.",
        *lines,
        "\\newcommand{\\isScore}[3]{\\csname is@#1@#2@#3\\endcsname}",
    ]
    path.write_text("\n".join(text) + "\n", encoding="utf-8")
    return "\n".join(text)


def tex_math(value: int) -> str:
    """A count inside math mode, in the text font as the rest of the slides write figures."""
    return f"\\text{{{number(value)}}}"


def fmt(value) -> str:
    return number(value) if isinstance(value, (int, np.integer)) else str(value)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--raw-dir", type=Path, default=Path("../3W/dataset"))
    opts = parser.parse_args(argv)
    for folder in (FIGURES, TABLES, APPENDIX):
        folder.mkdir(parents=True, exist_ok=True)
    info = DatasetInfo.load(opts.raw_dir)
    points, pred, maps = measure(info)
    write_maps(FIGURES / "maps", points, pred, maps)
    write_legend(TABLES / "legend.csv", points, info)
    write_wellpast(TABLES / "wellpast.csv", points, pred, info)
    write_descriptors(APPENDIX / "descriptors.csv")
    write_embeddings(APPENDIX / "embeddings.csv", maps)
    print(write_numbers(FIGURES / "numbers.tex", points, pred, maps))
    return 0


if __name__ == "__main__":
    sys.exit(main())
