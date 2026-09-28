"""Tests of the model-output format: the spec, the loader, the agreement with the labels."""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from conftest import hours

from overlap_viewer.backend import model_outputs as mo
from overlap_viewer.backend.labels import Segment, label_segments


def outputs_frame(start, labels, score=None) -> pd.DataFrame:
    index = pd.date_range(start, periods=len(labels), freq="1s", name="timestamp")
    data = {"label": np.asarray(labels, dtype=np.int8)}
    if score is not None:
        data["score"] = np.asarray(score, dtype=np.float32)
    return pd.DataFrame(data, index=index)


def test_agreement_is_the_share_of_the_compared_time_the_model_gets_right():
    """Detection agrees where anomalous meets a fault and normal meets 0; classification names the fault."""
    # The experts: 10 min normal, 10 min transient of fault 9, 10 min steady fault 9, 10 min unlabeled.
    labels = [0] * 600 + [109] * 600 + [9] * 600 + [np.nan] * 600
    frame = pd.DataFrame(
        {"class": pd.array([None if np.isnan(v) else int(v) for v in labels], dtype="Int16")},
        index=pd.date_range(hours(0), periods=2400, freq="1s"),
    )
    class_runs = label_segments(frame, "class")
    # A detector that wakes up five minutes late and sleeps through the unlabeled tail.
    model = outputs_frame(hours(0), [0] * 900 + [1] * 900 + [0] * 600)
    runs = label_segments(model, "label")
    result = mo.agreement(runs, class_runs, "detection")
    assert result.compared_s == pytest.approx(1800.0)  # the unlabeled tail is not compared
    assert result.agreed_s == pytest.approx(1500.0)  # late by 300 s
    assert result.share == pytest.approx(1500 / 1800)
    assert result.scored_s == pytest.approx(2400.0)
    # A classifier naming fault 9 agrees through the transient and the steady state alike.
    classifier = outputs_frame(hours(0), [0] * 600 + [9] * 1200 + [4] * 600)
    result = mo.agreement(label_segments(classifier, "label"), class_runs, "classification")
    assert result.share == pytest.approx(1.0)
    wrong = outputs_frame(hours(0), [0] * 600 + [4] * 1200)
    assert mo.agreement(
        label_segments(wrong, "label"), class_runs, "classification"
    ).share == pytest.approx(1 / 3)
    # Verdicts sample by sample, and the cases nothing can be said about.
    assert mo.agrees(1, 109, "detection", 100) and mo.agrees(0, 0, "detection", 100)
    assert not mo.agrees(1, 0, "detection", 100) and not mo.agrees(0, 9, "detection", 100)
    assert mo.agrees(9, 109, "classification", 100) and not mo.agrees(9, 4, "classification", 100)
    assert (
        mo.agrees(0, np.nan, "detection", 100) is None
        and mo.agrees(np.nan, 0, "detection", 100) is None
    )
    assert mo.agreement([], class_runs, "detection").compared_s == 0
    assert np.isnan(mo.agreement([], class_runs, "detection").share)
    # A model that scored a stretch the experts never labeled compares nothing.
    late = [Segment(hours(0.5), hours(0.6), 1.0)]
    assert mo.agreement(late, class_runs, "detection").compared_s == 0


def test_a_folder_of_outputs_is_written_and_read_back_in_the_documented_shape(tmp_path: Path):
    """model.json plus <class>/<file>.parquet, the spec validated, the frames read on demand and cached."""
    spec = mo.ModelSpec(
        "a test detector",
        "detection",
        {0: "normal", 1: "anomalous"},
        "says anomalous after ten minutes",
        {"producer": "tests"},
    )
    frames = [
        (
            9,
            "WELL-00002_20170201010000.parquet",
            outputs_frame(hours(0), [0] * 600 + [1] * 600, [0.5] * 600 + [2.0] * 600),
        ),
        (0, "WELL-00001_20170201010000.parquet", outputs_frame(hours(0), [0] * 1200)),
    ]
    folder = tmp_path / "outputs"
    assert mo.write_outputs(folder, spec, frames, {"command": "pytest"}) == 2
    written = json.loads((folder / mo.MODEL_FILE).read_text(encoding="utf-8"))
    assert written["labels"] == {"0": "normal", "1": "anomalous"} and written["kind"] == "detection"
    assert written["provenance"]["producer"] == "tests" and written["provenance"]["instances"] == 2
    assert "written_at" in written["provenance"] and written["provenance"]["command"] == "pytest"
    assert (folder / "9" / "WELL-00002_20170201010000.parquet").is_file()

    loaded = mo.ModelOutputs.load(folder)
    assert loaded.n_instances == 2 and loaded.spec.name == "a test detector"
    assert loaded.has(9, "WELL-00002_20170201010000.parquet")
    assert not loaded.has(9, "WELL-00099_20170201010000.parquet")
    frame = loaded.frame(9, "WELL-00002_20170201010000.parquet")
    assert list(frame.columns) == ["label", "score"] and len(frame) == 1200
    assert frame.index.name == "timestamp" and frame["label"].iloc[600] == 1
    assert loaded.frame(0, "WELL-00001_20170201010000.parquet")["label"].sum() == 0
    assert "score" not in loaded.frame(0, "WELL-00001_20170201010000.parquet").columns
    assert loaded.frame(3, "nowhere.parquet") is None
    runs = loaded.runs(9, "WELL-00002_20170201010000.parquet")
    assert len(runs) == 2 and runs[0].value == 0 and runs[1].value == 1
    assert (
        loaded.spec.label_name(1) == "anomalous" and loaded.spec.label_name(np.nan) == "no verdict"
    )
    assert "2 instances scored" in loaded.describe() and "tests" in loaded.describe()
    # Agreement against the experts of that instance.
    labels = pd.DataFrame(
        {"class": pd.array([0] * 900 + [109] * 300, dtype="Int16")},
        index=pd.date_range(hours(0), periods=1200, freq="1s"),
    )
    result = loaded.agreement(
        9, "WELL-00002_20170201010000.parquet", label_segments(labels, "class"), 100
    )
    assert result.share == pytest.approx(900 / 1200)
    assert loaded.agreement(3, "nowhere.parquet", [], 100) is None

    # What the loader refuses, and why.
    with pytest.raises(ValueError, match="holds no model.json"):
        mo.ModelOutputs.load(tmp_path / "empty")
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / mo.MODEL_FILE).write_text('{"name": "x", "kind": "detection"}', encoding="utf-8")
    with pytest.raises(ValueError, match="lacks labels"):
        mo.ModelOutputs.load(bad)
    (bad / mo.MODEL_FILE).write_text(
        '{"name": "x", "kind": "regression", "labels": {"0": "a"}}', encoding="utf-8"
    )
    with pytest.raises(ValueError, match="kind must be one of"):
        mo.ModelOutputs.load(bad)
    (bad / mo.MODEL_FILE).write_text(
        '{"name": "x", "kind": "detection", "labels": {}}', encoding="utf-8"
    )
    with pytest.raises(ValueError, match="holds no <class>"):
        mo.ModelOutputs.load(bad)
