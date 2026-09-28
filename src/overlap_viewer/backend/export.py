"""What the viewer writes for the 3W Toolkit: a file list its dataset loader takes. No Qt here.

The Toolkit reads a dataset through ``ParquetDatasetConfig``
(``ThreeWToolkit.dataset.parquet_dataset``); with ``split="list"`` it loads
exactly the files named in ``file_list``, each a path relative to the dataset
root, ``"4/WELL-00014_20170918230000.parquet"``, and refuses any it cannot
find under the root. So the instances a page of the viewer has on show (the
wells filtered, the instances ticked, the bars of a joined view) can be
handed to the Toolkit as they stand: this module writes them as the JSON of
that configuration, which loads back with
``ParquetDatasetConfig(**json.load(open(path)))``.

What the Toolkit writes back cannot come the other way. Its ``ModelAssessment``
exports ``predictions_<timestamp>.csv`` with the columns ``true_values``,
``predictions``, ``model_name``, ``task_type`` and ``timestamp``: one row per
window the model scored, in the order the windows were fed, with no instance
and no instant in it. Nothing in that file says which file, let alone which
second, a prediction belongs to, so it cannot be drawn back onto the data.
The viewer's own model-output format (``backend.model_outputs``) is what such
an export would have to carry: the instance's file, the timestamp of every
label.
"""

import json
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from overlap_viewer.backend.dataset import DatasetInfo

# What the Toolkit's loader calls a real instance, and the one version it loads.
EVENT_TYPE_REAL = "real"
TOOLKIT_VERSION = "2.0.0"


def relative_file(fault_class: int, file: str) -> str:
    """The path of one instance relative to the dataset root, as the Toolkit lists events."""
    return f"{int(fault_class)}/{Path(str(file)).name}"


def file_list_config(info: DatasetInfo, files: Iterable[tuple[int, str]]) -> dict:
    """The ``ParquetDatasetConfig`` of exactly these instances, as a JSON-ready dict.

    The fields are the configuration's own and nothing else, so that the
    dict loads straight into it. The files are sorted by class and name, and
    listed once each, a bar of the joined view being handed over as its
    instances.
    """
    listed = sorted({relative_file(fc, name) for fc, name in files})
    return {
        "path": str(info.raw_dir),
        "split": "list",
        "file_list": listed,
        "event_type": [EVENT_TYPE_REAL],
        "version": info.version or TOOLKIT_VERSION,
    }


def provenance(info: DatasetInfo, source: str, n_files: int) -> dict:
    """Where a file list came from: the dataset, the page and the choice it was taken from, when."""
    return {
        "written_by": "3W Real Instances Viewer",
        "written_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "dataset": str(info.raw_dir),
        "dataset_version": info.version or "unknown",
        "source": source,
        "n_files": n_files,
        "load_with": "ThreeWToolkit.dataset.parquet_dataset.ParquetDatasetConfig(**config)",
    }


def write_file_list(
    path: Path, info: DatasetInfo, files: Iterable[tuple[int, str]], source: str
) -> Path:
    """Write the configuration to ``path`` and its provenance beside it, as ``<name>.provenance.json``.

    Two files rather than one, because the configuration must hold the
    Toolkit's fields alone to load unchanged, and a reader of the list still
    deserves to know where it came from.
    """
    path = Path(path)
    config = file_list_config(info, files)
    path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    note = path.with_suffix(".provenance.json")
    note.write_text(
        json.dumps(provenance(info, source, len(config["file_list"])), indent=2),
        encoding="utf-8",
    )
    return note
