"""Figures, tables and numbers of the Dispersions section of the workshop deck.

Usage
-----
From the root of the repository::

    uv run python docs/presentation/scripts/dispersions.py [--raw-dir PATH]

Writes into ``docs/presentation/tables/dispersions/``:

``pairs.csv``
    per fault class, its pair of sensors and their Pearson coefficient over
    its normal operation, its transient and its steady state, on every sample
    (the historian's interpolations among them) and on the measurements
    alone, with how many these are, pooled over its instances;

into ``docs/presentation/tables/appendix/``:

``wells.csv``
    the same, per well of the class;

and into ``docs/presentation/figures/dispersions/``:

``numbers.tex``
    every figure the slides quote, as ``\\dp...`` macros;
``wells.csv``, ``pooled.csv``
    every well's coefficient on every sample and on the measurements alone,
    by class and period, with its color on the viewer's pages and whether it
    rests on fewer than ``FEW`` measurements, and the pooled coefficients of
    each class and period likewise, for ``wells.tikz`` to draw.

**The pair.** Of the analog sensors every instance of a class records live,
the two recorded live in the most samples, ties going to the variables the
3W 2.0.0 paper plots for the class, or, where it plots none, those Vargas's
thesis names (``config.FAULT_SIGNATURES``, ``config.BEST_EFFORT_SIGNATURES``),
then to the name. A sensor some instances lack would leave the coefficient
to the wells that record it, so the issue's own rule (the sensors most
closely related to the fault) gives way to the coverage every instance
shares. Where the instances share fewer than two, the pair is completed by
the best-covered variables of the signature, the rule of the first draft, and
those are marked (``\\dpsig``). The pair is set in alphabetical order.

**The coefficient** is the page's: ``dispersion.Cloud.pair(...).pearson()``
on the plausible readings of both sensors, in the label periods asked for,
and, for the measurements alone, at the instants at which both were measured
(``interpolation.sample_kinds``). The page reads an even subsample of a scope;
here every row is read (``DispersionPass`` with no budget), so the figures
are exact. A well's coefficient needs ``MIN_SAMPLES`` samples, so that a
stretch of a few minutes does not stand for a well.
"""

import argparse
import sys
from pathlib import Path

import numpy as np
from timelines import number, write_csv

from well_data_viewer.algorithms.availability import LIVE, sensor_state
from well_data_viewer.algorithms.dispersion import (
    NORMAL,
    STEADY,
    TRANSIENT,
    Cloud,
    DispersionPass,
    InstanceRef,
)
from well_data_viewer.backend import theme
from well_data_viewer.backend.config import (
    BEST_EFFORT_SIGNATURES,
    FAULT_SIGNATURES,
    plausible_range,
)
from well_data_viewer.backend.dataset import DatasetInfo, load_catalogue, load_instance_columns
from well_data_viewer.backend.labels import sensor_stats_from_json
from well_data_viewer.backend.palette import well_colors

ROOT = Path(__file__).resolve().parents[1]
FIGURES = ROOT / "figures" / "dispersions"
TABLES = ROOT / "tables" / "dispersions"
APPENDIX = ROOT / "tables" / "appendix"

PERIODS = {"normal": NORMAL, "transient": TRANSIENT, "steady": STEADY}
FAULTS = range(1, 10)  # the undesirable events; normal operation is the period of each
# The samples a well needs for a coefficient of its own: five minutes at 1 Hz.
MIN_SAMPLES = 300
# Below this many, a coefficient on the measurements alone is set apart as
# resting on too few samples to say much.
FEW = 30
# The cases the slides name: a class and a period whose pooled coefficient on
# every sample no well of it shares.
CASES = {"Productivity": (5, "steady"), "Bsw": (1, "transient")}


def class_pair(catalogue, info: DatasetInfo, fault: int) -> tuple[tuple[str, str], set[str]]:
    """The pair of a class (see the module's docstring), alphabetical, and which of it are not shared.

    Of the analog sensors every instance records live, the two live in the
    most samples, ties to the signature and then to the name; completed, where
    fewer than two are shared, by the signature's best-covered variables.
    """
    signature = FAULT_SIGNATURES.get(fault) or BEST_EFFORT_SIGNATURES[fault]
    part = catalogue[catalogue["fault_class"] == fault]
    live: dict[str, int] = {}
    shared: set[str] | None = None
    for text, n_total in zip(part["sensor_stats"], part["n_samples"]):
        mine = set()
        for sensor, (n, low, high) in sensor_stats_from_json(text).items():
            if not info.is_enumerated(sensor) and sensor_state(n, n_total, low, high) == LIVE:
                mine.add(sensor)
                live[sensor] = live.get(sensor, 0) + n
        shared = mine if shared is None else shared & mine

    def best(candidates) -> list[str]:
        return sorted(candidates, key=lambda s: (-live.get(s, 0), s not in signature, s))

    chosen = best(shared or ())[:2]
    signed = [s for s in best(s for s in signature if not info.is_enumerated(s)) if s not in chosen]
    chosen += signed[: 2 - len(chosen)]
    x, y = sorted(chosen)
    return (x, y), set(chosen) - (shared or set())


def read_cloud(catalogue, info: DatasetInfo, fault: int, pair: tuple[str, str]) -> Cloud:
    """Every row of every instance of a class, on the two sensors, as the page reads a scope."""
    part = catalogue[catalogue["fault_class"] == fault]
    bounds = [plausible_range(info.unit(s)) for s in pair]
    reader = DispersionPass(
        list(pair), bounds, len(part), budget=10**15, transient_offset=info.transient_offset
    )
    for path, well, file, start in zip(part["path"], part["well"], part["file"], part["start"]):
        frame = load_instance_columns(Path(path), ["class", *pair])
        reader.add(frame, InstanceRef(int(well), 0, fault, file, file, start))
    return reader.result()


def coefficient(cloud: Cloud, keep: np.ndarray) -> tuple[float, int]:
    """Pearson's coefficient of the two sensors over the rows kept, and how many; NaN below two."""
    x = cloud.values[keep, 0].astype(float)
    y = cloud.values[keep, 1].astype(float)
    if len(x) < 2 or x.std() == 0 or y.std() == 0:
        return float("nan"), len(x)
    return float(np.corrcoef(x, y)[0, 1]), len(x)


def tex_r(r: float) -> str:
    """A coefficient as the slides write it: a sign always, a true minus, two decimals; a dash for none."""
    if not np.isfinite(r):
        return r"\dpnil"
    return f"+{r:.2f}" if r >= 0 else f"\\textminus{{}}{abs(r):.2f}"


def tex_measured(r: float, n: int) -> tuple[str, str]:
    """A coefficient on the measurements alone and how many it rests on, both set apart when few.

    No comma in them, which would have the CSV quote the cell: the count is
    left bare for ``\\dpn`` (``\\dpcount`` when few) to set.
    """
    if not np.isfinite(r):
        return r"\dpnil", ""
    if n < FEW:
        return f"\\dpfew{{{tex_r(r)}}}", f"\\dpfew{{\\dpcount{{{n}}}}}"
    return tex_r(r), f"\\dpn{{{n}}}"


def tex_cells(period: str, r: float, rm: float, nm: int) -> dict[str, str]:
    """The three cells of a period: on every sample, on the measurements, how many these are."""
    measured, count = tex_measured(rm, nm)
    return {
        f"{period}_all": tex_r(r),
        f"{period}_measured": measured,
        f"{period}_count": count,
    }


def tex_pair(pair: tuple[str, str], signed: set[str]) -> dict[str, str]:
    """The pair's three cells, the sensors either side of the times sign, one not shared marked."""
    x, y = (s + (r"\dpsig{}" if s in signed else "") for s in pair)
    return {"x": x, "times": r"\texttimes{}", "y": y}


def measure(catalogue, info: DatasetInfo) -> tuple[list[dict], list[dict], list[dict]]:
    """Per class, pooled and per well: the coefficients by period, on every sample and measured."""
    theme.use("light")
    colors = well_colors(catalogue["well"])
    pooled, wells, dots = [], [], []
    for fault in FAULTS:
        pair, signed = class_pair(catalogue, info, fault)
        print(f"  {fault} {info.fault_name(fault)}: {' x '.join(pair)}", flush=True)
        cloud = read_cloud(catalogue, info, fault, pair)
        valid = np.isfinite(cloud.values[:, 0]) & np.isfinite(cloud.values[:, 1])
        measured = cloud.genuine[:, 0] & cloud.genuine[:, 1]
        cells = tex_pair(pair, signed)
        row = {"fault": fault, "name": info.fault_name(fault), "pair": pair, **cells}
        for period, code in PERIODS.items():
            keep = valid & (cloud.period == code)
            r, n = coefficient(cloud, keep)
            rm, nm = coefficient(cloud, keep & measured)
            row |= {f"{period}_r": r, f"{period}_n": n, f"{period}_rm": rm, f"{period}_nm": nm}
            row |= tex_cells(period, r, rm, nm)
        pooled.append(row)
        first = True
        for well in sorted(set(cloud.well.tolist())):
            mine = valid & (cloud.well == well)
            # The class named on its first row only, and its pair beside it.
            line = {
                "fault": fault,
                "name": info.fault_name(fault) if first else "",
                **(cells if first else dict.fromkeys(cells, "")),
                "well": f"WELL-{well:05d}",
            }
            shown = False
            for period, code in PERIODS.items():
                keep = mine & (cloud.period == code)
                r, n = coefficient(cloud, keep)
                rm, nm = coefficient(cloud, keep & measured)
                if n < MIN_SAMPLES:
                    r, rm = float("nan"), float("nan")
                shown |= bool(np.isfinite(r))
                line |= tex_cells(period, r, rm, nm)
                # A dot on every sample and one on the measurements alone, the
                # latter set apart (hollow) when it rests on fewer than FEW.
                for kind, value, count in (("all", r, n), ("measured", rm, nm)):
                    if np.isfinite(value):
                        dots.append(
                            {
                                "fault": fault,
                                "period": period,
                                "kind": kind,
                                "well": well,
                                "r": value,
                                "n": count,
                                "few": int(count < FEW),
                                "color": colors[well].lstrip("#").upper(),
                            }
                        )
            if shown:
                wells.append(line)
                first = False
    return pooled, wells, dots


def write_numbers(path: Path, pooled: list[dict], dots: list[dict]) -> None:
    by_fault = {row["fault"]: row for row in pooled}
    dots = [d for d in dots if d["kind"] == "all"]  # the wells against the pooled, on every sample
    cells = [
        (row[f"{p}_r"], row[f"{p}_rm"], row[f"{p}_nm"])
        for row in pooled
        for p in PERIODS
        if np.isfinite(row[f"{p}_r"]) and np.isfinite(row[f"{p}_rm"])
    ]
    stronger = sum(abs(rm) > abs(r) for r, rm, _ in cells)
    counts = [nm for _, _, nm in cells]
    facts = {
        "Cells": len(cells),
        "MeasuredStronger": stronger,
        "MeasuredFewest": min(counts),
        "MeasuredMost": max(counts),
        "MeasuredFew": sum(n < FEW for n in counts),
        "Few": FEW,
        "MinSamples": MIN_SAMPLES,
    }
    for name, (fault, period) in CASES.items():
        mine = [d["r"] for d in dots if d["fault"] == fault and d["period"] == period]
        facts[f"{name}Pooled"] = by_fault[fault][f"{period}_r"]
        facts[f"{name}WellLow"] = min(mine)
        facts[f"{name}WellHigh"] = max(mine)
        facts[f"{name}Wells"] = len(mine)
    # Where the pooled coefficient lies outside the range of its wells.
    outside = 0
    shared = 0
    for row in pooled:
        for p in PERIODS:
            mine = [d["r"] for d in dots if d["fault"] == row["fault"] and d["period"] == p]
            if len(mine) >= 2 and np.isfinite(row[f"{p}_r"]):
                shared += 1
                outside += not (min(mine) <= row[f"{p}_r"] <= max(mine))
    facts["PooledOutside"] = outside
    facts["PooledShared"] = shared
    lines = [
        "% Written by scripts/dispersions.py from the files of 3W; do not edit by hand.",
        *(f"\\newcommand{{\\dp{name}}}{{{fmt(value)}}}" for name, value in facts.items()),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def fmt(value) -> str:
    """A count as the slides write it, a coefficient as ``tex_r`` does."""
    if isinstance(value, (int, np.integer)):
        return number(value)
    return tex_r(value)


def panel(period: str, kind: str) -> int:
    """The panel of ``wells.tikz`` a period and kind are drawn in: every sample, then measured."""
    return 2 * list(PERIODS).index(period) + (kind == "measured")


def write_dots(path: Path, pooled: list[dict], dots: list[dict]) -> None:
    """The dots of ``wells.tikz``, and beside them (``pooled.csv``) the pooled coefficients."""
    # The row of the class in the chart, from the top, and its panel.
    rows = [{**d, "row": d["fault"] - 1, "panel": panel(d["period"], d["kind"])} for d in dots]
    write_csv(path, rows)
    ticks = [
        {
            "fault": row["fault"],
            "row": row["fault"] - 1,
            "panel": panel(p, kind),
            "pooled": row[f"{p}_{r}"],
            "few": int(kind == "measured" and row[f"{p}_nm"] < FEW),
        }
        for row in pooled
        for p in PERIODS
        for kind, r in (("all", "r"), ("measured", "rm"))
        if np.isfinite(row[f"{p}_{r}"])
    ]
    write_csv(path.with_name("pooled.csv"), ticks)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--raw-dir", type=Path, default=Path("../3W/dataset"))
    opts = parser.parse_args(argv)
    for folder in (FIGURES, TABLES, APPENDIX):
        folder.mkdir(parents=True, exist_ok=True)

    info = DatasetInfo.load(opts.raw_dir)
    catalogue = load_catalogue(info)
    pooled, wells, dots = measure(catalogue, info)

    keep = [
        "fault",
        "name",
        "x",
        "times",
        "y",
        *(f"{p}_{k}" for p in PERIODS for k in ("all", "measured", "count")),
    ]
    write_csv(TABLES / "pairs.csv", [{k: row[k] for k in keep} for row in pooled])
    write_csv(APPENDIX / "wells.csv", wells)
    write_dots(FIGURES / "wells.csv", pooled, dots)
    write_numbers(FIGURES / "numbers.tex", pooled, dots)
    print((FIGURES / "numbers.tex").read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
