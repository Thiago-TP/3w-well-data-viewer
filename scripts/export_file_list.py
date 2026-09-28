"""Write a 3W Toolkit file list of the real instances that match a choice, without opening the viewer.

The viewer's *Export file list…* button writes the instances a page has on
show; this is the same writer from the command line, for a choice made by
fault class and by well, so that an example can be produced and reproduced.

Usage
-----
    python scripts/export_file_list.py --raw-dir ../3W/dataset --fault 4 --well 14 \
        -o examples/file_list_severe_slugging_well14.json

Every ``--fault`` and every ``--well`` may be repeated; with neither, every
real instance is listed. The file written is the JSON of a
``ParquetDatasetConfig`` with ``split="list"``, which the Toolkit loads with
``ParquetDatasetConfig(**json.load(open(path)))``; its provenance is written
beside it as ``<name>.provenance.json``.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from overlap_viewer.backend.dataset import DatasetInfo, load_catalogue
from overlap_viewer.backend.export import write_file_list


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--raw-dir", type=Path, required=True, help="root of the 3W dataset")
    parser.add_argument(
        "--fault", type=int, action="append", default=[], help="a fault class to keep (repeatable)"
    )
    parser.add_argument(
        "--well", type=int, action="append", default=[], help="a well number to keep (repeatable)"
    )
    parser.add_argument("-o", "--output", type=Path, required=True, help="the JSON to write")
    args = parser.parse_args(argv)

    info = DatasetInfo.load(args.raw_dir)
    catalogue = load_catalogue(info)
    kept = catalogue
    if args.fault:
        kept = kept[kept["fault_class"].isin(args.fault)]
    if args.well:
        kept = kept[kept["well"].isin(args.well)]
    files = list(zip(kept["fault_class"].astype(int), kept["file"].astype(str)))
    if not files:
        print("no real instance matches the choice", file=sys.stderr)
        return 1
    choice = (
        " ".join([*(f"--fault {f}" for f in args.fault), *(f"--well {w}" for w in args.well)])
        or "every real instance"
    )
    note = write_file_list(
        args.output, info, files, f"scripts/export_file_list.py {choice}".strip()
    )
    print(f"{len(files)} files written to {args.output}; provenance in {note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
