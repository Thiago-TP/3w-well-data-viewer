"""Figures, tables and numbers of the Faults and Features section of the workshop deck.

Usage
-----
From the root of the repository::

    uv run python docs/presentation/scripts/faults.py [--raw-dir PATH] [--no-shots]

Writes into ``docs/presentation/tables/faults/``:

``signatures.csv``
    per fault class, its real instances and wells, and per signature variable
    of the class (the variables the 3W 2.0.0 paper plots for it, or, where it
    plots none, those Vargas's thesis names; ``config.FAULT_SIGNATURES`` and
    ``config.BEST_EFFORT_SIGNATURES``) a cell: the move the sources expect,
    how many instances make it of those that can show it, and how many
    instances lack the variable (absent or frozen, as the Availability page
    says);
``hydrate.csv``
    per real instance of Hydrate in Production Line, the well state under its
    transient and under its steady label;

into ``docs/presentation/figures/faults/``:

``numbers.tex``
    every figure the slides quote, as ``\\fa...`` macros;
``scaling.png``
    the Faults page on Scaling in PCK: P-MON-CKP of the earliest instance of
    each well from the onset of its transient, a color per well;
``well19.png``, ``well25.png``
    the instance window of a hydrate of WELL-00019 and of WELL-00025 on
    P-TPT, from the state band down (the three crops skipped with
    ``--no-shots``);
``simulated.csv``, ``simulated-bands.csv``
    a simulated hydrate, which the viewer does not read, for
    ``simulated.tikz`` to draw as the instance window would: its P-TPT,
    thinned to what a slide can show, and its state and label periods with
    the colors and names the window gives them (its note and its time ticks
    are macros of ``numbers.tex``).

**The moves.** A move is read per instance, from the median of the last hour
of normal operation before the event to the median of the last hour of the
event (its steady state if it reaches one, else the end of its transient),
on the plausible readings only. A change smaller than a dead band (0.01 MPa,
0.1 °C, 1 %) is no move. Severe Slugging and Flow Instability have no normal
operation to compare with, as their instances are labeled steady from end to
end; their mark is a swing, the spread from the 5th to the 95th percentile of
a pressure, which the paper puts above 10 bar at the downhole gauge and the
tree for severe slugging. Hydrate in Service Line has no published signature.
"""

import argparse
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
from availability import tex_unit
from timelines import number, write_csv

from overlap_viewer.algorithms.interpolation import (
    GENUINE,
    describe_sampling,
    sample_kinds,
    sampling_of,
)
from overlap_viewer.backend import theme
from overlap_viewer.backend.availability import ABSENT, FROZEN, sensor_state
from overlap_viewer.backend.config import (
    BEST_EFFORT_SIGNATURES,
    FAULT_SIGNATURES,
    WELL_STATES,
    plausible_range,
)
from overlap_viewer.backend.dataset import DatasetInfo, load_catalogue, load_instance_columns
from overlap_viewer.backend.labels import (
    column_as_float,
    feature_stats,
    format_delta,
    is_flat,
    label_kind,
    label_name,
    padded_range,
    runs,
    sensor_stats_from_json,
    state_name,
)
from overlap_viewer.backend.palette import background_color, bar_color, state_color, text_color

ROOT = Path(__file__).resolve().parents[1]
FIGURES = ROOT / "figures" / "faults"
TABLES = ROOT / "tables" / "faults"

# The columns of the table, by where they are measured (the viewer's
# placements), and their names in the CSV, which pgfplotstable reads as keys.
VARIABLES = {
    "ABER-CKP": "aber_ckp",
    "P-MON-CKP": "p_mon_ckp",
    "T-JUS-CKP": "t_jus_ckp",
    "P-TPT": "p_tpt",
    "T-TPT": "t_tpt",
    "P-PDG": "p_pdg",
}

# What the sources say each signature variable does under each event, as the
# viewer's help gives it (backend/help_text.py, FAULTS[...].signature): "up"
# and "down" for a level that moves, "swing" for an oscillation, None where no
# source says. Severe slugging: "oscillations above 10 bar at the downhole
# gauge and the tree", the other two swinging in phase; flow instability: the
# same variables, aperiodic and milder; hydrate in service line: no example.
EXPECTED: dict[int, dict[str, str | None]] = {
    1: {"P-MON-CKP": "down", "P-TPT": "down", "T-JUS-CKP": "up", "T-TPT": "up"},
    2: {"P-MON-CKP": "down", "P-PDG": "up", "P-TPT": "down", "T-TPT": "down"},
    3: {"P-MON-CKP": "swing", "P-PDG": "swing", "P-TPT": "swing", "T-JUS-CKP": "swing"},
    4: {"P-MON-CKP": "swing", "P-PDG": "swing", "P-TPT": "swing", "T-JUS-CKP": "swing"},
    5: {"P-MON-CKP": "down", "P-TPT": "down", "T-JUS-CKP": "down", "T-TPT": "down"},
    6: {"ABER-CKP": "down", "P-MON-CKP": "up", "P-PDG": "up", "P-TPT": "up"},
    7: {"P-MON-CKP": "up", "P-TPT": "up", "T-JUS-CKP": "down", "T-TPT": "down"},
    8: {"P-MON-CKP": "down", "P-PDG": "up", "P-TPT": "up", "T-TPT": "down"},
    9: {"P-MON-CKP": None, "P-PDG": None, "P-TPT": None, "T-TPT": None},
}
# The swing the paper states, and where: 10 bar at the downhole gauge and the tree.
SLUGGING, INSTABILITY = 3, 4
SWING = 1e6  # Pa
SWING_STATED = ("P-PDG", "P-TPT")
# A change smaller than this, in the unit the dataset records, is no move.
DEAD_BAND = {"Pa": 1e4, "°C": 0.1, "%": 1.0}
HOUR = pd.Timedelta(hours=1)
CELL = {"up": r"\faup", "down": r"\fadown", "swing": r"\faswing", None: r"\fanone"}

# The cases the slides name, each a fault, a variable and the well whose
# instances move against the sources.
SCALING, LOSS, RESTRICTION, HYDRATE = 7, 5, 6, 8
CASES = {"Scaling": (SCALING, "T-TPT", 24), "Loss": (LOSS, "P-TPT", 16)}
# The hydrates frame 8 sets side by side, each on one sensor, the tree
# pressure, whose course over the labels tells the most. WELL-00019's first
# hydrate (June 2012) is labeled transient while the well restarts, and
# steady still restarting; WELL-00025's is labeled transient while the well is
# closed with gas, and steady as it restarts; the simulated one is the first
# file of the folder, open throughout.
HYDRATE_SENSOR = "P-TPT"
HYDRATE_CROPS = {
    "well19": "WELL-00019_20120601165020.parquet",
    "well25": "WELL-00025_20200629194141.parquet",
}
SIMULATED = "SIMULATED_00001.parquet"
SIMULATED_POINTS = 600  # the samples kept of its 27,000: about one per slide pixel


def event_span(labels: np.ndarray, fault: int, offset: int):
    """Where the event's labels are: a mask, or None if the instance never leaves normal."""
    event = (labels == fault) | (labels == fault + offset)
    return event if event.any() else None


def plausible(frame: pd.DataFrame, sensor: str, info: DatasetInfo) -> np.ndarray | None:
    """A sensor's readings with the implausible ones as NaN; None if absent or flat."""
    if sensor not in frame.columns:
        return None
    values = column_as_float(frame, sensor)
    low, high = plausible_range(info.unit(sensor))
    values = np.where((values >= low) & (values <= high), values, np.nan)
    finite = values[np.isfinite(values)]
    if len(finite) < 2 or is_flat(float(finite.min()), float(finite.max())):
        return None
    return values


def move(frame: pd.DataFrame, labels, event, sensor, info) -> float | None:
    """The change of one sensor from the last normal hour to the last hour of the event.

    In the unit the dataset records; None where the instance cannot show it
    (no normal operation before the event, the sensor absent or frozen, or no
    plausible reading in either hour).
    """
    values = plausible(frame, sensor, info)
    index = frame.index
    onset = index[np.flatnonzero(event)[0]]
    normal = (labels == 0) & (index < onset)
    if values is None or not normal.any():
        return None
    last_normal = index[np.flatnonzero(normal)[-1]]
    end = index[np.flatnonzero(event)[-1]]
    before = values[normal & (index > last_normal - HOUR)]
    after = values[event & (index > end - HOUR)]
    if not np.isfinite(before).any() or not np.isfinite(after).any():
        return None
    return float(np.nanmedian(after) - np.nanmedian(before))


def swing(frame: pd.DataFrame, event, sensor, info) -> float | None:
    """The spread of a sensor over the event, 5th to 95th percentile; None if it cannot show it."""
    values = plausible(frame, sensor, info)
    if values is None:
        return None
    inside = values[event]
    inside = inside[np.isfinite(inside)]
    if len(inside) < 2:
        return None
    low, high = np.percentile(inside, [5, 95])
    return float(high - low)


def measure(catalogue, info: DatasetInfo) -> pd.DataFrame:
    """Per instance of every fault with a signature, and per signature variable, its move or swing."""
    offset = info.transient_offset
    rows = []
    for fault, signature in sorted({**FAULT_SIGNATURES, **BEST_EFFORT_SIGNATURES}.items()):
        if fault == 0:
            continue
        part = catalogue[catalogue["fault_class"] == fault]
        for path, well, file in zip(part["path"], part["well"], part["file"]):
            frame = load_instance_columns(Path(path), ["class", *signature])
            labels = column_as_float(frame, "class")
            event = event_span(labels, fault, offset)
            if event is None:
                continue
            hours = (
                frame.index[np.flatnonzero(event)[-1]] - frame.index[np.flatnonzero(event)[0]]
            ) / HOUR
            for sensor in signature:
                rows.append(
                    {
                        "fault": fault,
                        "well": int(well),
                        "file": file,
                        "sensor": sensor,
                        "hours": hours,
                        "move": move(frame, labels, event, sensor, info),
                        "swing": swing(frame, event, sensor, info),
                    }
                )
    return pd.DataFrame(rows)


def direction(row, info: DatasetInfo) -> str | None:
    """Which way a measured move went: "up", "down", "none", or None if unmeasured."""
    if row["move"] is None or pd.isna(row["move"]):
        return None
    band = DEAD_BAND[info.unit(row["sensor"])]
    return "up" if row["move"] > band else "down" if row["move"] < -band else "none"


def lacking(catalogue, info: DatasetInfo) -> dict[tuple[int, str], int]:
    """Per fault and variable, the instances whose footer says absent or frozen."""
    counts: dict[tuple[int, str], int] = Counter()
    for fault, text, n_total in zip(
        catalogue["fault_class"], catalogue["sensor_stats"], catalogue["n_samples"]
    ):
        stats = sensor_stats_from_json(text)
        for sensor in VARIABLES:
            n, low, high = stats.get(sensor, (0, np.nan, np.nan))
            state = sensor_state(n, n_total, low, high, info.is_enumerated(sensor))
            counts[int(fault), sensor] += state in (ABSENT, FROZEN)
    return counts


def signature_table(catalogue, info: DatasetInfo, moves: pd.DataFrame) -> list[dict]:
    """One row per fault class: its instances, wells, source and a cell per signature variable."""
    missing = lacking(catalogue, info)
    table = []
    for fault, part in catalogue.groupby("fault_class"):
        fault = int(fault)
        row = {
            "fault": info.fault_name(fault),
            "instances": len(part),
            "wells": int(part["well"].nunique()),
            "source": "paper"
            if fault in FAULT_SIGNATURES and fault != 0
            else "thesis"
            if fault in BEST_EFFORT_SIGNATURES and fault != 9
            else "none"
            if fault == 9
            else "",
        }
        for sensor, key in VARIABLES.items():
            row[key] = ""
            if sensor not in EXPECTED.get(fault, {}):
                continue
            expected = EXPECTED[fault][sensor]
            mine = moves[(moves["fault"] == fault) & (moves["sensor"] == sensor)]
            cell = CELL[expected]
            if expected in ("up", "down"):
                seen = mine.apply(direction, axis=1, info=info).dropna()
                cell += f" {int((seen == expected).sum())}/{len(seen)}" if len(seen) else r" \fanil"
            elif expected == "swing" and fault == SLUGGING and sensor in SWING_STATED:
                seen = mine["swing"].dropna()
                cell += f" {int((seen > SWING).sum())}/{len(seen)}"
            if missing[fault, sensor]:
                cell += rf" \famiss{{{missing[fault, sensor]}}}"
            row[key] = cell
        table.append(row)
    return table


def against(moves: pd.DataFrame, fault: int, sensor: str, well: int, info: DatasetInfo):
    """How many of one well's instances move against the sources, and of how many measured."""
    mine = moves[(moves["fault"] == fault) & (moves["sensor"] == sensor) & (moves["well"] == well)]
    seen = mine.apply(direction, axis=1, info=info).dropna()
    expected = EXPECTED[fault][sensor]
    opposite = {"up": "down", "down": "up"}[expected]
    return int((seen == opposite).sum()), len(seen)


def scaling_rates(moves: pd.DataFrame, info: DatasetInfo) -> pd.Series:
    """Per well, the median rise of P-MON-CKP over the event of Scaling in PCK, in MPa a day."""
    mine = moves[(moves["fault"] == SCALING) & (moves["sensor"] == "P-MON-CKP")].dropna(
        subset=["move"]
    )
    rate = mine["move"] * info.shown_scale("P-MON-CKP") / mine["hours"] * 24
    return rate.groupby(mine["well"]).median()


def hydrate_facts(catalogue, info: DatasetInfo) -> tuple[list[dict], dict]:
    """Per real instance of the production-line hydrate, the well state under each label; and the simulated."""
    offset = info.transient_offset
    part = catalogue[catalogue["fault_class"] == HYDRATE].sort_values(["well", "start"])
    table = []
    for path, well, start in zip(part["path"], part["well"], part["start"]):
        frame = load_instance_columns(Path(path), ["class", "state"])
        labels = column_as_float(frame, "class")
        states = column_as_float(frame, "state")
        row = {"well": f"WELL-{int(well):05d}", "start": pd.Timestamp(start).strftime("%Y-%m-%d")}
        for kind, value in (("transient", HYDRATE + offset), ("steady", HYDRATE)):
            under = states[labels == value]
            if not len(under):
                row[f"{kind}_hours"], row[f"{kind}_state"], row[f"{kind}_share"] = "", "never", ""
                row[f"{kind}_open"] = ""
                continue
            counts = Counter(WELL_STATES.get(int(v), "unknown") for v in under if np.isfinite(v))
            name, n = counts.most_common(1)[0]
            row[f"{kind}_hours"] = f"{len(under) / 3600:.0f}"
            row[f"{kind}_state"] = name
            row[f"{kind}_share"] = f"{100 * n / len(under):.0f}"
            row[f"{kind}_open"] = int(name == "Open")
        table.append(row)
    simulated = sorted((info.raw_dir / str(HYDRATE)).glob("SIMULATED_*.parquet"))
    open_samples = total = 0
    for path in simulated:
        states = column_as_float(load_instance_columns(path, ["state"]), "state")
        open_samples += int((states == 0).sum())
        total += len(states)
    facts = {
        "HydrateReal": len(table),
        "HydrateWells": int(part["well"].nunique()),
        "HydrateTransientClosed": sum(1 for row in table if row["transient_open"] == 0),
        "HydrateSteady": sum(1 for row in table if row["steady_state"] != "never"),
        "HydrateSteadyClosed": sum(1 for row in table if row["steady_open"] == 0),
        "HydrateSimulated": len(simulated),
        # A whole percent, as the table gives the real instances' shares.
        "HydrateSimulatedOpen": round(100 * open_samples / total),
    }
    return table, facts


def simulated_facts(info: DatasetInfo) -> tuple[list[dict], list[dict], dict]:
    """A simulated hydrate as the instance window would draw it on one sensor, for ``simulated.tikz``.

    The trace, thinned to ``SIMULATED_POINTS`` samples, in hours from the
    start, with which of them are measurements (dots, where the window would
    draw any); the state and label periods with the window's colors and names;
    and the figures the window writes in the corner of the plot.
    """
    theme.use("light")
    offset = info.transient_offset
    frame = load_instance_columns(
        info.raw_dir / str(HYDRATE) / SIMULATED, ["class", "state", HYDRATE_SENSOR]
    )
    start = frame.index[0]
    hours = (frame.index - start) / HOUR
    values = column_as_float(frame, HYDRATE_SENSOR)
    kinds = sample_kinds(values)
    keep = np.unique(np.linspace(0, len(frame) - 1, SIMULATED_POINTS).round().astype(int))
    trace = [
        {
            "hours": hours[k],
            "value": values[k] * info.shown_scale(HYDRATE_SENSOR),
            "measured": int(kinds[k] == GENUINE),
        }
        for k in keep
        if np.isfinite(values[k])
    ]

    def band(name, column, color, label):
        rows = []
        for a, b, value in runs(column_as_float(frame, column)):
            fill = color(value)
            rows.append(
                {
                    "band": name,
                    "start": hours[a],
                    # A period ends where the next begins, as the window draws it.
                    "end": hours[b] if b < len(frame) else hours[-1],
                    "fill": fill.lstrip("#").upper(),
                    "text": text_color(fill).lstrip("#").upper(),
                    "shade": background_color(HYDRATE, label_kind(value, offset))
                    .lstrip("#")
                    .upper()
                    if name == "class"
                    else "",
                    "label": label(value),
                }
            )
        return rows

    bands = band("state", "state", lambda v: state_color(int(v)), lambda v: state_name(v)) + band(
        "class",
        "class",
        lambda v: bar_color(HYDRATE, label_kind(v, offset)),
        lambda v: label_name(v, info.fault_names, offset),
    )
    stats = feature_stats(frame, HYDRATE_SENSOR)
    unit = info.shown_unit(HYDRATE_SENSOR)
    note = format_delta(stats.delta * info.shown_scale(HYDRATE_SENSOR), unit)
    if not stats.flat:
        note += " | " + describe_sampling(sampling_of(kinds))
    note += f" | coverage {stats.coverage:.1f} %"
    measured = int(((kinds == GENUINE) & np.isfinite(values)).sum())
    # Clock ticks two hours apart, written as the window's time axis writes
    # them at that spacing (see the crop of WELL-00019): the first with its
    # date and time, a later midnight as its month and day, the rest as times.
    ticks = pd.date_range(start.ceil("2h"), frame.index[-1], freq="2h")

    def tick_label(k: int, t: pd.Timestamp) -> str:
        if k == 0:
            return f"{t:%Y-%m-%d %H:%M}"
        return f"{t:%m-%d}" if t.hour == 0 and t.minute == 0 else f"{t:%H:%M}"

    facts = {
        "SimName": SIMULATED.removesuffix(".parquet").replace("_", "-"),
        "SimNote": note.replace("Δ", r"$\Delta$").replace("%", r"\%"),
        "SimTicks": ",".join(f"{(t - start) / HOUR:.4f}" for t in ticks),
        "SimTickLabels": ",".join(tick_label(k, t) for k, t in enumerate(ticks)),
        "SimLabel": f"{HYDRATE_SENSOR} [{tex_unit(unit)}]",
        "SimEnd": float(hours[-1]),
        # The value axis as the window ranges it.
        **dict(
            zip(
                ("SimYmin", "SimYmax"),
                (
                    f"{v:.4f}"
                    for v in padded_range(
                        float(np.nanmin(values)) * info.shown_scale(HYDRATE_SENSOR),
                        float(np.nanmax(values)) * info.shown_scale(HYDRATE_SENSOR),
                    )
                ),
            )
        ),
        # The colors of the window's light theme the TikZ needs besides the bands.
        "SimTraceColor": theme.current().trace.lstrip("#").upper(),
        "SimForeground": theme.current().plot_foreground.lstrip("#").upper(),
        "SimNoteFill": theme.current().note_fill.lstrip("#").upper(),
        "SimNoteBorder": theme.current().note_border.lstrip("#").upper(),
        # The window dots the measurements only where some samples are not
        # (traces.add_trace); a series measured throughout is a plain line.
        "SimDotted": int(0 < measured < int(np.isfinite(values).sum())),
    }
    return trace, bands, facts


def write_numbers(path: Path, catalogue, moves: pd.DataFrame, info: DatasetInfo, extra: dict):
    normal = catalogue[catalogue["fault_class"] == 0]
    rates = scaling_rates(moves, info)
    scaling = moves[(moves["fault"] == SCALING) & (moves["sensor"] == "P-MON-CKP")]
    scaling_seen = scaling.apply(direction, axis=1, info=info).dropna()
    missing = lacking(catalogue, info)
    restriction = catalogue[catalogue["fault_class"] == RESTRICTION]

    def swings(fault, sensor):
        seen = moves[(moves["fault"] == fault) & (moves["sensor"] == sensor)]["swing"].dropna()
        return seen * info.shown_scale(sensor), seen

    tpt3, raw_tpt3 = swings(SLUGGING, "P-TPT")
    pdg3, raw_pdg3 = swings(SLUGGING, "P-PDG")
    tpt4, _ = swings(INSTABILITY, "P-TPT")
    facts = {
        "Instances": len(catalogue),
        "NormalInstances": len(normal),
        "NormalWells": int(normal["well"].nunique()),
        "ScalingRise": int((scaling_seen == "up").sum()),
        "ScalingMeasured": len(scaling_seen),
        "ScalingRateLow": float(rates.min()),
        "ScalingRateHigh": float(rates.max()),
        "RestrictionInstances": len(restriction),
        "RestrictionPdgLacking": missing[RESTRICTION, "P-PDG"],
        "RestrictionChokeLive": len(restriction) - missing[RESTRICTION, "ABER-CKP"],
        "SluggingTpt": float(tpt3.median()),
        "SluggingTptOver": int((raw_tpt3 > SWING).sum()),
        "SluggingTptOf": len(raw_tpt3),
        "SluggingPdg": float(pdg3.median()),
        "SluggingPdgOver": int((raw_pdg3 > SWING).sum()),
        "SluggingPdgOf": len(raw_pdg3),
        "InstabilityTpt": float(tpt4.median()),
        **extra,
    }
    for name, (fault, sensor, well) in CASES.items():
        facts[f"Case{name}Against"], facts[f"Case{name}Of"] = against(
            moves, fault, sensor, well, info
        )
    lines = [
        "% Written by scripts/faults.py from the catalogue and the files of 3W; do not edit by hand.",
        *(f"\\newcommand{{\\fa{name}}}{{{fmt(value)}}}" for name, value in facts.items()),
        f"\\newcommand{{\\faScalingRateLowWell}}{{WELL-{int(rates.idxmin()):05d}}}",
        f"\\newcommand{{\\faScalingRateHighWell}}{{WELL-{int(rates.idxmax()):05d}}}",
        f"\\newcommand{{\\faPressureUnit}}{{{tex_unit(info.shown_unit('P-TPT'))}}}",
    ]
    for name, (_, sensor, well) in CASES.items():
        lines.append(f"\\newcommand{{\\faCase{name}Well}}{{WELL-{well:05d}}}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def fmt(value) -> str:
    """A figure as the slides write it; a share or a rate below 1 keeps two decimals; text as is."""
    if isinstance(value, str):
        return value
    if isinstance(value, float) and abs(value) < 1:
        return f"{value:.2f}"
    return number(value)


def take_shots(raw_dir: Path) -> None:
    """The Faults page on Scaling in PCK, and the instance windows of two real hydrates."""
    import offscreen
    from PySide6.QtCore import Qt

    window = offscreen.main_window(raw_dir)

    # Scaling in PCK on P-MON-CKP from the onset of each transient, the
    # earliest instance of each well in a grid of small multiples, each on its
    # own value axis and all on one time axis, in its well's color: the rise
    # is there in every well, at a pace of its own. Overlaid, the levels of
    # the wells (2 to 12 MPa) flatten every rise of a few tenths, and the 19
    # noisy instances of WELL-00024 cover the rest.
    page = window.faults
    window._tabs.setCurrentWidget(page)
    offscreen.settle(2.0)
    box = page._fault
    box.setCurrentIndex(box.findText("Scaling in PCK", Qt.MatchFlag.MatchContains))
    offscreen.settle(3.0)
    for name, check in page._checks.items():
        check.blockSignals(True)
        check.setChecked(name == "P-MON-CKP")
        check.blockSignals(False)
    page.set_layout("Small multiples")
    page._columns.setValue(3)
    first = {}
    for entry in page._instances:
        if entry["onset"] is not None and entry["start"] < first.get(
            entry["well"], pd.Timestamp.max
        ):
            first[entry["well"]] = entry["start"]
    page._building = True
    for entry, item in zip(page._instances, page._items):
        wanted = first.get(entry["well"]) == entry["start"]
        item.setCheckState(Qt.CheckState.Checked if wanted else Qt.CheckState.Unchecked)
    page._building = False
    page._replot()
    window.resize(1300, 620)
    offscreen.settle(8.0)
    path = FIGURES / "scaling.png"
    page._scroll.grab().save(str(path))
    print(f"  saved {path}", flush=True)

    # The two real hydrates of frame 8, each over its own recording, on the
    # sensor chosen (HYDRATE_SENSOR).
    for name, file in HYDRATE_CROPS.items():
        number_of_well = int(file[5:10])
        well = next(w for w in window._wells if w.well == number_of_well)
        joined = well.joined()
        bar = next(
            b
            for b in range(joined.n_instances)
            if file in {joined.origin.rows["file"].iloc[m] for m in joined.members[b]}
        )
        row = well.rows.loc[well.rows["file"] == file].iloc[0]
        offscreen.save_stack(
            window,
            number_of_well,
            bar,
            [HYDRATE_SENSOR],
            (row["start"], row["end"]),
            # One plot and the two bands, with no scroll bar, about twice as
            # wide as tall, so that two stack in half a slide.
            (720, 430),
            FIGURES / f"{name}.png",
            panel=False,
        )
    window.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--raw-dir", type=Path, default=Path("../3W/dataset"))
    parser.add_argument("--no-shots", action="store_true", help="skip the crops of the viewer")
    opts = parser.parse_args(argv)
    FIGURES.mkdir(parents=True, exist_ok=True)
    TABLES.mkdir(parents=True, exist_ok=True)

    info = DatasetInfo.load(opts.raw_dir)
    catalogue = load_catalogue(info)
    moves = measure(catalogue, info)
    hydrate, hydrate_numbers = hydrate_facts(catalogue, info)
    trace, bands, simulated_numbers = simulated_facts(info)

    write_csv(TABLES / "signatures.csv", signature_table(catalogue, info, moves))
    write_csv(TABLES / "hydrate.csv", hydrate)
    write_csv(FIGURES / "simulated.csv", trace)
    write_csv(FIGURES / "simulated-bands.csv", bands)
    write_numbers(
        FIGURES / "numbers.tex", catalogue, moves, info, hydrate_numbers | simulated_numbers
    )
    print((FIGURES / "numbers.tex").read_text(encoding="utf-8"))

    if not opts.no_shots:
        take_shots(info.raw_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
