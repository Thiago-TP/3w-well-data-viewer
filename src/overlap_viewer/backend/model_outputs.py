"""Model outputs the viewer can draw: the format, its loader, and how far they agree with the labels. No Qt here.

The viewer displays what a model said; it does not train one. For a model's
verdicts to be drawn onto the data, every verdict has to say which instance
and which instant it is about, which is exactly what the 3W Toolkit's
assessment export leaves out (``backend.export``). So the viewer defines the
format itself, and it is the smallest one that says both.

A set of outputs is a **folder**::

    <folder>/
        model.json                       what the model is, what its labels mean, where it came from
        <fault_class>/<instance>.parquet one file per instance scored, mirroring the dataset's layout

``model.json`` holds ``name``, ``kind`` (``"detection"`` for a model that says
*anomalous or not*, ``"classification"`` for one that names the event by its
3W class number), ``labels`` (the meaning of every label value the parquet
files carry, e.g. ``{"0": "normal", "1": "anomalous"}``), a ``description``,
and ``provenance``: who produced the outputs, with what script and what
parameters, on which dataset version, when. Each parquet file has the
``timestamp`` of every sample scored as its index, an integer ``label``
column and, optionally, a float ``score`` column (the model's own figure, in
its own unit, larger meaning more anomalous). A model need not score every
sample of an instance, nor every instance.

**Agreement** is measured against the dataset's ``class`` labels, over the
stretches where both the model and the experts said something. For a
detection model the model agrees where it says *anomalous* and the label is a
fault, transient or steady, and where it says *normal* and the label is 0;
for a classification model where its class equals the fault the label names
(a transient label counts as its fault), or both are 0. The share of the
compared time in agreement is the instance's **agreement**, a figure the
pages color and sort by.
"""

import json
from collections import OrderedDict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from overlap_viewer.backend.config import DEFAULT_TRANSIENT_OFFSET
from overlap_viewer.backend.labels import Segment, label_fault, label_kind, label_segments

MODEL_FILE = "model.json"
TIMESTAMP = "timestamp"  # what a file's index is called, in the file and when read back
KINDS = ("detection", "classification")
REQUIRED = ("name", "kind", "labels")
FRAME_CACHE = 64  # instances' outputs kept in memory


@dataclass(frozen=True)
class ModelSpec:
    """What ``model.json`` says about a set of outputs."""

    name: str
    kind: str
    labels: dict[int, str]
    description: str = ""
    provenance: dict = field(default_factory=dict)
    label_column: str = "label"
    score_column: str | None = "score"

    def label_name(self, value: float) -> str:
        if np.isnan(value):
            return "no verdict"
        return self.labels.get(int(value), f"label {int(value)}")

    def to_json(self) -> dict:
        return {
            "name": self.name,
            "kind": self.kind,
            "labels": {str(k): v for k, v in self.labels.items()},
            "description": self.description,
            "provenance": self.provenance,
            "label_column": self.label_column,
            "score_column": self.score_column,
        }

    @classmethod
    def from_json(cls, data: dict) -> "ModelSpec":
        missing = [key for key in REQUIRED if key not in data]
        if missing:
            raise ValueError(f"{MODEL_FILE} lacks {', '.join(missing)}")
        if data["kind"] not in KINDS:
            raise ValueError(f"{MODEL_FILE}: kind must be one of {KINDS}, not {data['kind']!r}")
        labels = {int(k): str(v) for k, v in dict(data["labels"]).items()}
        return cls(
            str(data["name"]),
            str(data["kind"]),
            labels,
            str(data.get("description", "")),
            dict(data.get("provenance", {})),
            str(data.get("label_column", "label")),
            data.get("score_column", "score"),
        )


@dataclass(frozen=True)
class Agreement:
    """How far a model's verdicts on one instance agree with its labels.

    ``compared_s`` is the time, in seconds, over which both the model and
    the experts said something; ``agreed_s`` how much of it they agreed on;
    ``scored_s`` how much of the instance the model scored at all.
    """

    compared_s: float
    agreed_s: float
    scored_s: float

    @property
    def share(self) -> float:
        return self.agreed_s / self.compared_s if self.compared_s > 0 else float("nan")


def agrees(model_label: float, dataset_label: float, kind: str, offset: int) -> bool | None:
    """Whether one model verdict agrees with one dataset label; ``None`` where either is unknown."""
    if np.isnan(model_label) or np.isnan(dataset_label):
        return None
    dataset_kind = label_kind(dataset_label, offset)
    if dataset_kind == "unknown":
        return None
    if kind == "detection":
        return (int(model_label) != 0) == (dataset_kind != "normal")
    fault = label_fault(dataset_label, offset)
    return int(model_label) == (0 if fault is None else fault)


def agreement(
    model_runs: list[Segment],
    class_runs: list[Segment],
    kind: str,
    offset: int = DEFAULT_TRANSIENT_OFFSET,
) -> Agreement:
    """The agreement of a model's label runs with the dataset's, stretch by stretch.

    Both lists tile their spans, as ``labels.label_segments`` returns them;
    every stretch between two consecutive boundaries of either carries one
    value of each, and is compared where both are known.
    """
    if not model_runs:
        return Agreement(0.0, 0.0, 0.0)
    scored = sum((run.end - run.start).total_seconds() for run in model_runs)
    edges = sorted({t for run in model_runs + class_runs for t in (run.start, run.end)})
    compared = agreed = 0.0
    m = c = 0
    for a, b in pairwise(edges):
        while m < len(model_runs) and model_runs[m].end <= a:
            m += 1
        while c < len(class_runs) and class_runs[c].end <= a:
            c += 1
        if m >= len(model_runs) or model_runs[m].start > a:
            continue
        if c >= len(class_runs) or class_runs[c].start > a:
            continue
        verdict = agrees(model_runs[m].value, class_runs[c].value, kind, offset)
        if verdict is None:
            continue
        seconds = (b - a).total_seconds()
        compared += seconds
        if verdict:
            agreed += seconds
    return Agreement(compared, agreed, scored)


class ModelOutputs:
    """A folder of model outputs, opened once, its files read as they are asked for."""

    def __init__(self, folder: Path, spec: ModelSpec, files: dict[tuple[int, str], Path]):
        self.folder = Path(folder)
        self.spec = spec
        self.files = files
        self._frames: OrderedDict[tuple[int, str], pd.DataFrame] = OrderedDict()

    @classmethod
    def load(cls, folder: Path) -> "ModelOutputs":
        """Open a folder of outputs, or raise ``ValueError`` saying what is wrong with it."""
        folder = Path(folder)
        spec_path = folder / MODEL_FILE
        if not spec_path.is_file():
            raise ValueError(f"{folder} holds no {MODEL_FILE}")
        try:
            spec = ModelSpec.from_json(json.loads(spec_path.read_text(encoding="utf-8")))
        except json.JSONDecodeError as error:
            raise ValueError(f"{spec_path} is not valid JSON: {error}") from error
        files: dict[tuple[int, str], Path] = {}
        for class_dir in sorted(p for p in folder.iterdir() if p.is_dir() and p.name.isdigit()):
            for path in sorted(class_dir.glob("*.parquet")):
                files[(int(class_dir.name), path.name)] = path
        if not files:
            raise ValueError(f"{folder} holds no <class>/<instance>.parquet outputs")
        return cls(folder, spec, files)

    @property
    def n_instances(self) -> int:
        return len(self.files)

    def has(self, fault_class: int, file: str) -> bool:
        return (int(fault_class), str(file)) in self.files

    def frame(self, fault_class: int, file: str) -> pd.DataFrame | None:
        """The outputs of one instance: ``label`` and, if given, ``score``, indexed by timestamp."""
        key = (int(fault_class), str(file))
        path = self.files.get(key)
        if path is None:
            return None
        if key in self._frames:
            self._frames.move_to_end(key)
            return self._frames[key]
        frame = pd.read_parquet(path)
        if "timestamp" in frame.columns:
            frame = frame.set_index("timestamp")
        frame.index = pd.to_datetime(frame.index)
        if self.spec.label_column not in frame.columns:
            raise ValueError(f"{path} has no {self.spec.label_column!r} column")
        columns = {self.spec.label_column: "label"}
        if self.spec.score_column and self.spec.score_column in frame.columns:
            columns[self.spec.score_column] = "score"
        frame = frame.rename(columns=columns)[list(columns.values())].sort_index()
        self._frames[key] = frame
        while len(self._frames) > FRAME_CACHE:
            self._frames.popitem(last=False)
        return frame

    def runs(self, fault_class: int, file: str) -> list[Segment]:
        """The model's label runs on one instance, tiling the stretch it scored."""
        frame = self.frame(fault_class, file)
        return [] if frame is None or frame.empty else label_segments(frame, "label")

    def agreement(
        self, fault_class: int, file: str, class_runs: list[Segment], offset: int
    ) -> Agreement | None:
        """How far the model agrees with the labels of one instance; ``None`` when it did not score it."""
        if not self.has(fault_class, file):
            return None
        return agreement(self.runs(fault_class, file), class_runs, self.spec.kind, offset)

    def describe(self) -> str:
        spec = self.spec
        who = spec.provenance.get("producer", "an unknown producer")
        return f"{spec.name} ({spec.kind}, {self.n_instances} instances scored, from {who})"


def write_outputs(
    folder: Path,
    spec: ModelSpec,
    outputs: Iterable[tuple[int, str, pd.DataFrame]],
    provenance: dict | None = None,
) -> int:
    """Write a set of outputs in the format above; returns how many instances were written.

    ``outputs`` yields ``(fault_class, file, frame)`` with the frame indexed
    by timestamp and holding ``label`` (and ``score``). The provenance given
    is merged into the spec's, with the time of writing added.
    """
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    n = 0
    for fault_class, file, frame in outputs:
        out = folder / str(int(fault_class)) / Path(str(file)).name
        out.parent.mkdir(parents=True, exist_ok=True)
        table = pa.Table.from_pandas(frame.rename_axis(TIMESTAMP))
        # A verdict per second is mostly its own timestamp: one second after
        # the last. Written plainly that index is four fifths of the file, so
        # it is delta encoded, which costs a reader nothing (parquet undoes it)
        # and makes a set of outputs a quarter of the size.
        pq.write_table(
            table,
            out,
            compression="zstd",
            version="2.6",
            use_dictionary=False,
            column_encoding={TIMESTAMP: "DELTA_BINARY_PACKED"},
        )
        n += 1
    stamped = dict(spec.provenance)
    stamped.update(provenance or {})
    stamped["written_at"] = datetime.now(UTC).isoformat(timespec="seconds")
    stamped["instances"] = n
    complete = ModelSpec(
        spec.name,
        spec.kind,
        spec.labels,
        spec.description,
        stamped,
        spec.label_column,
        spec.score_column,
    )
    (folder / MODEL_FILE).write_text(json.dumps(complete.to_json(), indent=2), encoding="utf-8")
    return n
