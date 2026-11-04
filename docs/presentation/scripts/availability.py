"""Figures, tables and numbers of the Availability section of the workshop deck.

Usage
-----
From the root of the repository::

    uv run python docs/presentation/scripts/availability.py [--raw-dir PATH]

Writes into ``docs/presentation/figures/availability/``:

``numbers.tex``
    every figure the slides quote, as ``\\av...`` macros;
``coverage.csv``
    per variable, the samples of every real instance live, frozen and missing,
    and the readings among the live and frozen ones that are implausible, out
    of order or against the state, as counts and shares; the instances it is
    live in, frozen in, absent from and has each kind of problem reading in;
    and its reading farthest outside the plausible range. Ranked as the page's
    *By coverage* ranks the sensors. The chart on the slide draws it, and the
    appendix sets it as numbers.

Every sample of a variable is *live*, *frozen* or *missing*, as the footer of
its instance says: the checks have no say in it. Some live and frozen readings
are also problem readings: *implausible* outside the plausible range, *out of
order* (a pressure read below the one downstream of it) or *against the state*
(a valve that contradicts the labeled well state). The checks leave the
implausible readings out, and no variable is in both checks, so the problem
readings never overlap each other. Their shares within the live part and
within the frozen part are written too, for the chart to lay each over the
part that holds it. A check that does not compare a variable leaves its cells
``nan``, set as a dash.

Everything is what the viewer's Availability page reads: the live, frozen and
absent states come from the footers of the files the catalogue caches
(``availability.sensor_state``, with the page's default of any reading
counting), and the implausible and inconsistent readings from the profile pass
(``profiles.load_profiles``), which the page runs the first time *Measured vs
filled* is ticked and caches. The script reads the cache only, so the numbers
take seconds; it stops if the pass has not been run (open the viewer's
Availability page and tick *Measured vs filled* once).

Counted over the files as 3W ships them, the samples two overlapping instances
share counted in each, as the page counts them without the join.
"""

import argparse
import sys
from pathlib import Path

import numpy as np
from timelines import number, write_csv

from overlap_viewer.backend.availability import ABSENT, FROZEN, LIVE, sensor_state
from overlap_viewer.backend.config import (
    PRODUCTION_PRESSURES,
    SERVICE_PRESSURE_PAIRS,
    STATE_VALVE_RULES,
    plausible_range,
)
from overlap_viewer.backend.dataset import DatasetInfo, load_catalogue, split_wells
from overlap_viewer.backend.labels import sensor_stats_from_json
from overlap_viewer.backend.profiles import load_profiles

ROOT = Path(__file__).resolve().parents[1]
FIGURES = ROOT / "figures" / "availability"

# The kinds of variable the ranges table names, by the unit the dataset declares.
QUANTITIES = {"Pa": "Pressure", "°C": "Temperature", "%": "ValveOpening", "m³/s": "FlowRate"}

# The groups of the appendix table: the three states of a sample, and between
# them the problem readings, which are among the live and frozen ones.
PARTS = ("live", "frozen", "implausible", "out_of_order", "against_state", "missing")
# The states a reading can be in.
RECORDED = ("live", "frozen")
# The problem readings, as the profile pass counts them per instance, in the
# order the chart lays them over a part.
PROBLEMS = {
    "out_of_order": "n_out_of_order",
    "against_state": "n_against_state",
    "implausible": "n_implausible",
}
# The variables each consistency check compares: the pressures along the
# production and service lines, and the valves the well states are defined by.
CHECKED = {
    "out_of_order": set(PRODUCTION_PRESSURES)
    | {name for pair in SERVICE_PRESSURE_PAIRS for name in pair[:2]},
    "against_state": {
        valve for rules in STATE_VALVE_RULES.values() for *_, valves in rules for valve in valves
    },
}


def tex_number(value: float) -> str:
    """A reading as the slides write it, in the text font: ``−0.498``, ``−1.7×10³⁸``.

    The exponent is smashed, so that it does not open up the line of a table.
    """
    sign = "\\textminus{}" if value < 0 else ""
    value = abs(value)
    if value != 0 and (value >= 1e4 or value < 1e-2):
        mantissa, exponent = f"{value:.1e}".split("e")
        return f"{sign}{mantissa}\\texttimes{{}}10\\smash{{\\textsuperscript{{{int(exponent)}}}}}"
    return f"{sign}{value:.4g}"


def tex_bound(value: float) -> str:
    """A bound of a range as the slides write it, a negative one with a true minus sign."""
    return f"\\textminus{{}}{abs(value):g}" if value < 0 else f"{value:g}"


def tex_unit(unit: str) -> str:
    """A unit as TeX reads it: the percent sign escaped, which would start a comment."""
    return unit.replace("%", "\\%")


def instance_rows(profiles):
    """The profile pass's rows for the instances, the merged recordings left out."""
    table = profiles.table
    return table[table["scope"] == "instance"]


def coverage_facts(catalogue, profiles, info: DatasetInfo) -> list[dict]:
    """Per variable: its samples live, frozen and missing, the problem readings among them, the instances.

    A problem reading is counted in the state of the instance that holds it,
    so that the chart can lay it over the live or the frozen part.
    """
    rows = instance_rows(profiles)
    keys = zip(rows["file"].astype(str), rows["fault_class"].astype(int), rows["sensor"])
    found = dict(zip(keys, zip(*(rows[column].astype(int) for column in PROBLEMS.values()))))
    sensors = info.sensor_names
    samples = {s: dict.fromkeys(("live", "frozen", "missing"), 0) for s in sensors}
    within = {s: {(p, state): 0 for p in PROBLEMS for state in RECORDED} for s in sensors}
    instances = {s: dict.fromkeys(("live", "frozen", "absent", *PROBLEMS), 0) for s in sensors}
    for file, fault_class, text, n_total in zip(
        catalogue["file"],
        catalogue["fault_class"],
        catalogue["sensor_stats"],
        catalogue["n_samples"],
    ):
        stats = sensor_stats_from_json(text)
        for sensor in sensors:
            n, low, high = stats.get(sensor, (0, np.nan, np.nan))
            state = sensor_state(n, n_total, low, high, info.is_enumerated(sensor))
            problems = dict(zip(PROBLEMS, found[(str(file), int(fault_class), sensor)]))
            # The problem readings never overlap, and an absent sensor has none.
            assert sum(problems.values()) <= n and (state != ABSENT or n == 0), (file, sensor)
            name = {LIVE: "live", FROZEN: "frozen", ABSENT: "absent"}[state]
            instances[sensor][name] += 1
            samples[sensor]["missing"] += n_total - n
            if state == ABSENT:
                continue
            samples[sensor][name] += n
            for problem, count in problems.items():
                within[sensor][problem, name] += count
                instances[sensor][problem] += count > 0
    total = int(catalogue["n_samples"].sum())
    table = []
    for sensor in sensors:
        assert sum(samples[sensor].values()) == total, sensor
        counts = samples[sensor] | {
            p: sum(within[sensor][p, state] for state in RECORDED) for p in PROBLEMS
        }
        # A check that does not compare the variable has no count, not a zero.
        applies = {part: part not in CHECKED or sensor in CHECKED[part] for part in PARTS}
        assert all(applies[part] or not counts[part] for part in PARTS), sensor
        row = {"sensor": sensor, "valve": int(info.is_enumerated(sensor))}
        row |= {part: counts[part] if applies[part] else np.nan for part in PARTS}
        row |= {
            f"{part}_share": 100.0 * counts[part] / total if applies[part] else np.nan
            for part in PARTS
        }
        row |= {
            f"instances_{kind}": count if applies.get(kind, True) else np.nan
            for kind, count in instances[sensor].items()
        }
        # Where the chart lays the problem readings: their shares within the
        # live part and within the frozen part, zero where there are none.
        row |= {
            f"{problem}_in_{state}_share": 100.0 * within[sensor][problem, state] / total
            for state in RECORDED
            for problem in PROBLEMS
        }
        # What the chart writes at the end of the bar.
        recorded = counts["missing"] < total
        row["tag"] = f"{row['live_share']:.1f}" if recorded else "never recorded"
        table.append(row)
    # As the page ranks by coverage: the largest live share first, then what is
    # at least recorded, so that a frozen sensor ranks above a missing one.
    table.sort(key=lambda row: (-row["live"], -row["frozen"], row["sensor"]))
    return table


def profile_facts(profiles) -> dict:
    """The problem readings over every instance, and the instances that hold any."""
    rows = instance_rows(profiles)
    return {
        "InstancesImplausible": int(rows.loc[rows["n_implausible"] > 0, "file"].nunique()),
        "InstancesOutOfOrder": int(rows.loc[rows["n_out_of_order"] > 0, "file"].nunique()),
        "InstancesAgainstState": int(rows.loc[rows["n_against_state"] > 0, "file"].nunique()),
        "Implausible": int(rows["n_implausible"].sum()),
        "OutOfOrder": int(rows["n_out_of_order"].sum()),
        "AgainstState": int(rows["n_against_state"].sum()),
    }


def extreme_readings(catalogue, info: DatasetInfo, coverage: list[dict]) -> None:
    """Add to each variable the reading farthest outside its range, from the footers.

    The profile's extremes leave the implausible readings out; the footers of
    the files keep every reading's minimum and maximum. A variable without
    implausible readings gets an empty cell.
    """
    for row in coverage:
        row["worst"] = ""
        if not row["implausible"]:
            continue
        sensor = row["sensor"]
        low, high = plausible_range(info.unit(sensor))
        worst, gap = np.nan, 0.0
        for text in catalogue["sensor_stats"]:
            n, lo, hi = sensor_stats_from_json(text).get(sensor, (0, np.nan, np.nan))
            if not n:
                continue
            for value in (lo, hi):
                beyond = max(low - value, value - high, 0.0)
                if beyond > gap:
                    worst, gap = value, beyond
        row["worst"] = (
            f"{tex_number(worst * info.shown_scale(sensor))}\\thinspace{{}}"
            f"{tex_unit(info.shown_unit(sensor))}"
        )


def write_numbers(
    path: Path, info: DatasetInfo, catalogue, coverage: list[dict], facts: dict
) -> None:
    never = [row["sensor"] for row in coverage if row["tag"] == "never recorded"]
    valves = [row for row in coverage if row["valve"]]
    pdg = next(row for row in coverage if row["sensor"] == "P-PDG")
    facts = {
        "Variables": len(coverage),
        "Instances": len(catalogue),
        "Samples": int(catalogue["n_samples"].sum()),
        "NeverRecorded": len(never),
        "BestLiveShare": coverage[0]["live_share"],
        "ValvesLiveLow": min(row["live_share"] for row in valves),
        "ValvesLiveHigh": max(row["live_share"] for row in valves),
        "PdgFrozenShare": pdg["frozen_share"],
        "PdgFrozenInstances": pdg["instances_frozen"],
        "PdgLiveInstances": pdg["instances_live"],
        **facts,
    }
    lines = [
        "% Written by scripts/availability.py from the viewer's caches; do not edit by hand.",
        *(f"\\newcommand{{\\av{name}}}{{{number(value)}}}" for name, value in facts.items()),
        f"\\newcommand{{\\avNeverRecordedNames}}{{{', '.join(never)}}}",
        f"\\newcommand{{\\avBestCovered}}{{{coverage[0]['sensor']}}}",
    ]
    for unit, quantity in QUANTITIES.items():
        sensor = next(s for s in info.sensor_names if info.unit(s) == unit)
        low, high = info.shown_range(sensor)
        lines.append(
            f"\\newcommand{{\\avRange{quantity}}}{{{tex_bound(low)} to {tex_bound(high)}\\thinspace{{}}"
            f"{tex_unit(info.shown_unit(sensor))}}}"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--raw-dir", type=Path, default=Path("../3W/dataset"))
    opts = parser.parse_args(argv)
    FIGURES.mkdir(parents=True, exist_ok=True)

    info = DatasetInfo.load(opts.raw_dir)
    catalogue = load_catalogue(info)
    profiles = load_profiles(info, split_wells(catalogue), info.sensor_names, cache_only=True)
    if profiles is None:
        raise SystemExit(
            "no current profile pass in the cache: open the viewer's Availability page and tick "
            "Measured vs filled once"
        )

    coverage = coverage_facts(catalogue, profiles, info)
    extreme_readings(catalogue, info, coverage)

    write_csv(FIGURES / "coverage.csv", coverage)
    write_numbers(FIGURES / "numbers.tex", info, catalogue, coverage, profile_facts(profiles))
    print((FIGURES / "numbers.tex").read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
