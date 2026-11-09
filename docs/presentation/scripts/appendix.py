"""Figures and tables of the deck's appendix: the label changes across an unlabeled stretch.

Usage
-----
From the root of the repository::

    uv run python docs/presentation/scripts/appendix.py [--raw-dir PATH] [--no-shots]

A joined history (see ``timelines.py``) keeps a few unlabeled stretches between
two *different* labels: the label changes there, and no file says when. On
3W 2.0.0 they are the returns to normal operation the Timelines section
counts, every one at a file boundary, and the onsets of a fault the same way.
The appendix lists them and shows each in the viewer.

Writes:

``tables/appendix/changes.csv``
    one row per change, numbered by well and time: the well, when the label
    stops, the labels either side, how long nothing is labeled, the folders of
    the files either side, the sensor drawn and the stretch of time shown;
``figures/appendix/change-<n>.png``
    the instance window on the joined bar, around the change, on that sensor
    (skipped with ``--no-shots``).

The sensor is the first pressure of the fault's signature (``config``'s
``FAULT_SIGNATURES``, or ``BEST_EFFORT_SIGNATURES`` where the paper has no
figure) that every file around the change recorded and that moves in them,
from the footers the catalogue keeps; failing a pressure, the first such sensor
of the signature, then of the seabed sensors the viewer opens on
(``signature_sensor``).
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from timelines import duration, joined_history, label_text, write_csv

from overlap_viewer.backend.config import (
    BEST_EFFORT_SIGNATURES,
    DEFAULT_FEATURES,
    FAULT_SIGNATURES,
)
from overlap_viewer.backend.dataset import DatasetInfo, WellData, load_catalogue, split_wells
from overlap_viewer.backend.labels import label_fault, sensor_stats_from_json

ROOT = Path(__file__).resolve().parents[1]
FIGURES = ROOT / "figures" / "appendix"
TABLES = ROOT / "tables" / "appendix"

# How much of the history either side of the change the crop shows: at least
# this much, and twice the unlabeled stretch when that is longer.
PAD = pd.Timedelta(minutes=40)


def signature_sensor(well: WellData, members: list[int], fault: int, span: tuple) -> str:
    """The sensor drawn for a change of ``fault``, among the files that cover ``span``.

    The fault's signature, pressures first, then the sensors the viewer opens
    an instance window on: the first that every covering file recorded and
    that moves in each of them, else the first that every one recorded at all
    (a flat line says that nothing moved), else the first of the signature.
    """
    signature = FAULT_SIGNATURES.get(fault) or BEST_EFFORT_SIGNATURES.get(fault, ())
    candidates = sorted(signature, key=lambda sensor: not sensor.startswith("P-"))
    candidates += [sensor for sensor in DEFAULT_FEATURES if sensor not in candidates]
    rows = well.origin.rows.iloc[members]
    covering = rows[(rows["start"] <= span[1]) & (rows["end"] >= span[0])]
    stats = [sensor_stats_from_json(text) for text in covering["sensor_stats"]]

    def recorded(sensor: str) -> bool:
        return all(sensor in s and s[sensor][0] > 0 for s in stats)

    def moving(sensor: str) -> bool:
        return recorded(sensor) and all(s[sensor][1] < s[sensor][2] for s in stats)

    return next(
        (sensor for sensor in candidates if moving(sensor)),
        next((sensor for sensor in candidates if recorded(sensor)), candidates[0]),
    )


def change_facts(wells: list[WellData], info: DatasetInfo) -> list[dict]:
    """Every unlabeled stretch of a joined history between two different labels."""
    table = []
    for well in wells:
        joined = well.joined()
        for bar in range(joined.n_instances):
            runs = joined_history(well, bar)
            for k in range(1, len(runs) - 1):
                start, end, value, _ = runs[k]
                before, after = runs[k - 1], runs[k + 1]
                if not np.isnan(value) or before[2] == after[2]:
                    continue
                fault = label_fault(before[2]) or label_fault(after[2])
                gap = end - start
                pad = max(PAD, 2 * gap)
                span = (
                    max(start - pad, pd.Timestamp(joined.rows["start"].iloc[bar])),
                    min(end + pad, pd.Timestamp(joined.rows["end"].iloc[bar])),
                )
                table.append(
                    {
                        "n": len(table) + 1,
                        "well": well.well,
                        "label": f"WELL-{well.well:05d}",
                        "bar": bar,
                        "at": pd.Timestamp(start).strftime("%Y-%m-%d %H:%M"),
                        "before": label_text(before[2], info),
                        "after": label_text(after[2], info),
                        "unlabeled": duration(gap.total_seconds()),
                        "unlabeled_s": gap.total_seconds(),
                        "from_folder": before[3][-1],
                        "to_folder": after[3][0],
                        "sensor": signature_sensor(well, joined.members[bar], fault, span),
                        "shown_from": str(span[0].floor("s")),
                        "shown_to": str(span[1].ceil("s")),
                    }
                )
    return table


def take_shots(raw_dir: Path, changes: list[dict]) -> None:
    """One crop of the instance window per change, around it, on its sensor."""
    import offscreen

    window = offscreen.main_window(raw_dir)
    for change in changes:
        offscreen.save_stack(
            window,
            change["well"],
            change["bar"],
            [change["sensor"]],
            (change["shown_from"], change["shown_to"]),
            # Small, so that its text is not shrunk away on a quarter of a slide.
            (760, 400),
            FIGURES / f"change-{change['n']}.png",
            panel=False,
            fit=True,
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
    wells = split_wells(load_catalogue(info))
    changes = change_facts(wells, info)
    write_csv(TABLES / "changes.csv", changes)
    for change in changes:
        print(
            f"  {change['n']:2d} {change['label']} {change['at']}  {change['before']} -> "
            f"{change['after']}  ({change['unlabeled_s']:.0f} s)  on {change['sensor']}"
        )
    print(f"  written to {TABLES}", flush=True)

    if not opts.no_shots:
        take_shots(info.raw_dir, changes)
    return 0


if __name__ == "__main__":
    sys.exit(main())
