"""A PCA control chart over real instances, written in the viewer's model-output format.

The oldest tool of multivariate process monitoring, and the one Melo's thesis
and his BibMon package build on: fit a principal-component model on normal
operation, then follow two statistics along a recording (Hotelling's T², the
distance of a sample inside the model's plane, and Q (the squared prediction
error), its distance off the plane), and call a sample anomalous when either
exceeds the limit normal operation sets. The limits are the 99th percentile
of each statistic over the training samples.

Two ways of fitting are offered. ``--fit well`` (the default) fits one model
per well on every sample of the well's *Normal Operation* instances (class 0)
and scores every instance of the well with it, the setting a detector would
run in, one reference per well, so that a well without normal instances is
skipped. ``--fit instance`` fits on the samples labeled normal inside each
instance and scores that instance alone, so every instance is its own
reference and an instance labeled faulty throughout is skipped.

This is a *producer* of model outputs, not part of the viewer: it exists so
that the model-output format ships with an example whose provenance is
written down, and it is one of many things that could fill that format.

Usage
-----
    python scripts/pca_control_chart.py --raw-dir ../3W/dataset --well 4 \
        -o examples/model_outputs/pca_control_chart_well4

``--fault`` and ``--well`` may be repeated and narrow what is scored; with
neither, every real instance is.
"""

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from overlap_viewer.backend.config import plausible_range
from overlap_viewer.backend.dataset import DatasetInfo, load_catalogue, load_instance
from overlap_viewer.backend.labels import column_as_float
from overlap_viewer.backend.model_outputs import ModelSpec, write_outputs

MIN_NORMAL = 600  # samples of normal operation a model needs
VARIANCE_KEPT = 0.90  # the components kept explain at least this share of the normal variance
LIMIT_QUANTILE = 0.99  # the limit of each statistic: this quantile over the training samples
# The score is a ratio to the model's limit, 1 at the limit, read as a color or
# a figure and never to more than a decimal or two. Three decimals is past
# anything a reader of it can see, and it is what makes an example of this
# affordable: a float that moves every second is the one column that does not
# compress, and rounding it takes the outputs of four wells from 20 MB to 7.
SCORE_DECIMALS = 3


@dataclass(frozen=True)
class Model:
    """A fitted chart: the sensors, their scaling, the plane and the two limits."""

    sensors: list[str]
    mean: np.ndarray
    std: np.ndarray
    loadings: np.ndarray  # (sensors, k)
    variance: np.ndarray  # of the k components kept
    t2_limit: float
    q_limit: float


def plausible(frame: pd.DataFrame, name: str, info: DatasetInfo) -> np.ndarray:
    """One sensor as floats, readings outside its plausible range set to missing."""
    values = column_as_float(frame, name)
    low, high = plausible_range(info.unit(name))
    return np.where((values < low) | (values > high), np.nan, values)


def live_sensors(
    frame: pd.DataFrame, mask: np.ndarray, info: DatasetInfo, min_samples: int
) -> set[str]:
    """The analog sensors that move over the masked samples of one frame."""
    found = set()
    for name in info.sensor_names:
        if info.is_enumerated(name) or name not in frame.columns:
            continue
        values = plausible(frame, name, info)[mask]
        if np.isfinite(values).sum() >= min_samples and np.nanstd(values) > 0:
            found.add(name)
    return found


def matrix(frame: pd.DataFrame, sensors: list[str], info: DatasetInfo) -> np.ndarray:
    """The sensors of one frame as columns, gaps filled forward then backward, as a pipeline would."""
    X = np.column_stack([plausible(frame, name, info) for name in sensors])
    return pd.DataFrame(X).ffill().bfill().to_numpy()


def fit(training: np.ndarray, sensors: list[str]) -> Model | None:
    """The chart fitted on the training samples (rows), standardized column by column."""
    training = training[np.isfinite(training).all(axis=1)]
    if len(training) < MIN_NORMAL or training.shape[1] < 2:
        return None
    mean = training.mean(axis=0)
    std = training.std(axis=0)
    if not (std > 0).all():
        return None
    Z = (training - mean) / std
    _u, s, vt = np.linalg.svd(Z, full_matrices=False)
    variance = s**2 / max(len(Z) - 1, 1)
    share = np.cumsum(variance) / variance.sum()
    k = int(np.searchsorted(share, VARIANCE_KEPT) + 1)
    k = min(max(k, 1), len(variance) - 1)
    loadings = vt[:k].T
    t2, q = statistics(Z, loadings, variance[:k])
    return Model(
        sensors,
        mean,
        std,
        loadings,
        variance[:k],
        float(np.quantile(t2, LIMIT_QUANTILE)),
        float(np.quantile(q, LIMIT_QUANTILE)),
    )


def statistics(
    Z: np.ndarray, loadings: np.ndarray, variance: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    scores = Z @ loadings
    t2 = np.sum(scores**2 / variance, axis=1)
    residual = Z - scores @ loadings.T
    return t2, np.sum(residual**2, axis=1)


def score(model: Model, frame: pd.DataFrame, info: DatasetInfo) -> pd.DataFrame:
    """The chart over one frame: the label (1 beyond either limit) and the score (the larger ratio to its limit)."""
    X = matrix(frame, model.sensors, info)
    Z = (X - model.mean) / model.std
    Z = np.where(np.isfinite(Z), Z, 0.0)  # a sensor the instance lacks sits at the training mean
    t2, q = statistics(Z, model.loadings, model.variance)
    ratio = np.maximum(t2 / max(model.t2_limit, 1e-12), q / max(model.q_limit, 1e-12))
    return pd.DataFrame(
        {
            "label": (ratio > 1.0).astype(np.int8),
            # Rounded after the label is decided, so no sample is relabeled by it.
            "score": np.round(ratio, SCORE_DECIMALS).astype(np.float32),
        },
        index=pd.Index(frame.index, name="timestamp"),
    )


def per_instance(kept: pd.DataFrame, info: DatasetInfo, skipped: list[str]):
    for row in kept.itertuples():
        frame = load_instance(row.path)
        normal = column_as_float(frame, "class") == 0
        sensors = sorted(live_sensors(frame, normal, info, MIN_NORMAL // 2))
        model = fit(matrix(frame, sensors, info)[normal], sensors) if len(sensors) >= 2 else None
        if model is None:
            skipped.append(str(row.file))
            continue
        yield int(row.fault_class), str(row.file), score(model, frame, info)


def per_well(
    kept: pd.DataFrame, catalogue: pd.DataFrame, info: DatasetInfo, skipped: list[str], fitted: dict
):
    for well in sorted(kept["well"].unique()):
        training_rows = catalogue[(catalogue["well"] == well) & (catalogue["fault_class"] == 0)]
        frames = [load_instance(path) for path in training_rows["path"]]
        common: set[str] | None = None
        for frame in frames:
            live = live_sensors(frame, np.ones(len(frame), dtype=bool), info, MIN_NORMAL // 2)
            common = live if common is None else common & live
        sensors = sorted(common or [])
        model = None
        if frames and len(sensors) >= 2:
            training = np.vstack([matrix(frame, sensors, info) for frame in frames])
            model = fit(training, sensors)
        scored = kept[kept["well"] == well]
        if model is None:
            skipped += [str(f) for f in scored["file"]]
            continue
        fitted[int(well)] = {
            "training_instances": len(frames),
            "training_samples": int(sum(len(f) for f in frames)),
            "sensors": sensors,
            "components": int(model.loadings.shape[1]),
            "t2_limit": round(model.t2_limit, 4),
            "q_limit": round(model.q_limit, 4),
        }
        for row in scored.itertuples():
            yield int(row.fault_class), str(row.file), score(model, load_instance(row.path), info)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--raw-dir", type=Path, required=True, help="root of the 3W dataset")
    parser.add_argument(
        "--fault", type=int, action="append", default=[], help="a fault class to score (repeatable)"
    )
    parser.add_argument(
        "--well", type=int, action="append", default=[], help="a well to score (repeatable)"
    )
    parser.add_argument(
        "--fit", choices=("well", "instance"), default="well", help="what the model is fitted on"
    )
    parser.add_argument("-o", "--output", type=Path, required=True, help="the folder to write")
    args = parser.parse_args(argv)

    info = DatasetInfo.load(args.raw_dir)
    catalogue = load_catalogue(info)
    kept = catalogue
    if args.fault:
        kept = kept[kept["fault_class"].isin(args.fault)]
    if args.well:
        kept = kept[kept["well"].isin(args.well)]
    skipped: list[str] = []
    fitted: dict = {}
    outputs = (
        per_well(kept, catalogue, info, skipped, fitted)
        if args.fit == "well"
        else per_instance(kept, info, skipped)
    )
    choice = " ".join([*(f"--fault {f}" for f in args.fault), *(f"--well {w}" for w in args.well)])
    how = (
        "one model per well, fitted on every sample of the well's Normal Operation instances "
        "(class 0) and scoring every instance of the well"
        if args.fit == "well"
        else "one model per instance, fitted on the samples labeled normal inside it"
    )
    spec = ModelSpec(
        name=f"PCA control chart, fitted per {args.fit}",
        kind="detection",
        labels={0: "normal", 1: "anomalous"},
        description=(
            f"Hotelling's T² and the squared prediction error Q of a principal-component model ({how} "
            ") over the analog sensors live in every training instance (readings outside the "
            "plausible range masked, gaps filled forward then backward, standardized on the training "
            f"samples); the components kept explain {VARIANCE_KEPT:.0%} of the training variance. A "
            f"sample is anomalous when T² or Q exceeds the {LIMIT_QUANTILE:.0%} quantile of its "
            "statistic over the training samples; the score is the larger of the two ratios to their "
            f"limits, 1 at the limit, rounded to {SCORE_DECIMALS} decimals after the label is "
            "decided. A sensor an instance lacks sits at the training mean."
        ),
        provenance={
            "producer": "scripts/pca_control_chart.py of the 3W Real Instances Viewer",
            # Forward slashes whatever platform wrote it: the command is there
            # to be read and run again, and Windows takes them too.
            "command": (
                f"python scripts/pca_control_chart.py --raw-dir {args.raw_dir.as_posix()} "
                f"{choice} --fit {args.fit} -o {args.output.as_posix()}"
            ).replace("  ", " "),
            "parameters": {
                "fit": args.fit,
                "min_training_samples": MIN_NORMAL,
                "variance_kept": VARIANCE_KEPT,
                "limit_quantile": LIMIT_QUANTILE,
                "score_decimals": SCORE_DECIMALS,
            },
            "dataset": str(info.raw_dir),
            "dataset_version": info.version or "unknown",
            "reference": (
                "The PCA control chart of multivariate statistical process monitoring, as in "
                "A. Melo's doctoral thesis (chapter 4) and his BibMon package."
            ),
        },
    )
    n = write_outputs(args.output, spec, outputs, {"skipped": skipped, "models": fitted})
    print(f"{n} instances scored into {args.output}; {len(skipped)} skipped")
    return 0 if n else 1


if __name__ == "__main__":
    raise SystemExit(main())
