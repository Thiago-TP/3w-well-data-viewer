"""Tests of the Instances map's algorithms: representations, embeddings, clusterings, typicality, novelty, DTW."""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from overlap_viewer.algorithms import embedding as em

RNG = np.random.default_rng(11)


def planted_points(n_per: int = 40, spread: float = 0.3):
    """Three tight clouds on a plane inside a noisy 6-D space, with their class and well labels."""
    centers = np.array([[0, 0], [6, 0], [0, 6]], dtype=float)
    X, classes, wells = [], [], []
    for k, center in enumerate(centers):
        cloud = center + spread * RNG.normal(size=(n_per, 2))
        X.append(np.column_stack([cloud, 0.1 * RNG.normal(size=(n_per, 4))]))
        classes += [k] * n_per
        wells += [(k * 7 + i) % 5 for i in range(n_per)]
    return np.vstack(X), np.array(classes), np.array(wells)


def test_the_embeddings_and_the_clusterings_find_planted_clouds():
    """PCA and MDS recover a planted plane; the clusterings and their scores agree with the classes that made it."""
    X, classes, wells = planted_points()
    Z, kept = em.standardize(np.column_stack([X, np.ones(len(X)), np.full(len(X), 0.1)]))
    assert kept == list(range(6))  # the two constant columns are dropped, rounding or no rounding
    assert Z.shape == (len(X), 6) and np.allclose(Z.std(axis=0), 1.0)
    # The clouds are read in their own units: standardizing would give the
    # four noise columns the weight of the two planted ones.
    rep = em.Representation(list(range(len(X))), X, [f"c{j}" for j in range(6)])
    coords, caption = em.embed(rep, "PCA")
    assert coords.shape == (len(X), 2) and "PC1" in caption
    # The two planted directions carry nearly all the variance, in the first two components.
    _scores, explained = em.pca(X)
    assert explained[0] + explained[1] > 0.95
    # Principal coordinates of the Euclidean distances are the same picture, and
    # with every coordinate kept they reproduce the distances exactly.
    D = em.euclidean_distances(X)
    assert D.shape == (len(X), len(X)) and D[0, 0] == 0 and D[0, 1] == pytest.approx(D[1, 0])
    metric = em.distance_representation(list(range(len(X))), D)
    mds, caption = em.embed(metric, "PCA")
    assert "principal coordinates" in caption
    upper = np.triu_indices(len(D), 1)
    assert np.corrcoef(D[upper], em.euclidean_distances(mds)[upper])[0, 1] > 0.99
    full, spread = em.classical_mds(D, 6)
    assert np.allclose(em.euclidean_distances(full), D, atol=1e-6) and spread.sum() > 0.999
    # Typicality: the medoid of a class ranks 1, the farthest member 0.
    typ = em.typicality(rep, classes)
    for klass, medoid in typ.medoids.items():
        assert classes[medoid] == klass and typ.rank[medoid] == 1.0
        members = np.flatnonzero(classes == klass)
        assert typ.rank[members].min() == 0.0 and np.all(typ.distance[members] >= 0)
    assert typ.distance[typ.medoids[0]] == 0.0
    pytest.importorskip("sklearn")
    for method in ("k-means", "Gaussian mixture", "Agglomerative"):
        labels = em.cluster(rep, method, 3)
        scores = em.cluster_scores(rep, labels, classes, wells)
        assert scores.n_clusters == 3 and scores.ari_class > 0.95, (method, scores)
        assert scores.nmi_class > 0.95 and scores.silhouette > 0.7
        assert abs(scores.ari_well) < 0.2  # the wells were dealt out regardless of the clouds
        assert "silhouette" in scores.describe()
    # DBSCAN reads its radius from the data and may split a cloud or leave a
    # few points out; what it finds still follows the classes.
    labels = em.cluster(rep, "DBSCAN", 3)
    scores = em.cluster_scores(rep, labels, classes, wells)
    assert scores.n_clusters >= 3 and scores.ari_class > 0.8 and scores.n_noise < 30
    assert em.dbscan_radius(em.euclidean_distances(X)) > 0
    assert (em.cluster(rep, "None", 3) == 0).all()
    tsne, caption = em.embed(rep, "t-SNE")
    assert tsne.shape == (len(X), 2) and "t-SNE" in caption
    assert em.embedding_available("PCA") is None and em.embedding_available("t-SNE") is None


def test_the_novelty_audit_lists_the_labels_that_disagree_with_the_forest():
    """A fault instance that sits among the normal ones, and a normal one far from them, are the disagreements."""
    pytest.importorskip("sklearn")
    X, classes, _wells = planted_points(n_per=60, spread=0.2)
    # Class 1 is the fault; move one of its points into the normal cloud, and one normal point far away.
    fault_in_normal = int(np.flatnonzero(classes == 1)[0])
    X[fault_in_normal] = [0.05, -0.05, 0.0, 0.0, 0.0, 0.0]
    normal_far = int(np.flatnonzero(classes == 0)[3])
    X[normal_far, :2] = [-30.0, 25.0]
    rep = em.Representation(list(range(len(X))), X, [f"c{j}" for j in range(6)])
    verdict = em.novelty(rep, classes)
    assert verdict is not None
    assert not verdict.anomalous[fault_in_normal] and verdict.anomalous[normal_far]
    assert fault_in_normal in verdict.disagreements and normal_far in verdict.disagreements
    assert normal_far in verdict.disagreements_of(classes, 0)
    assert fault_in_normal in verdict.disagreements_of(classes, 1)
    # Every point of the far cloud (class 2) looks anomalous, so it is not a disagreement.
    assert verdict.anomalous[classes == 2].all()
    assert len(verdict.disagreements_of(classes, 2)) == 0
    # Nothing to learn from: no normal instances, or a metric representation.
    assert em.novelty(rep, np.full(len(X), 4)) is None
    metric = em.distance_representation(rep.keys, em.euclidean_distances(X))
    assert em.novelty(metric, classes) is None


def test_the_descriptor_matrix_is_built_from_the_profile_table():
    """Sensors too rarely live are left out, an enumerated one gives its mean alone, gaps are imputed and remembered."""
    from overlap_viewer.backend import profiles as pr
    from overlap_viewer.backend.dataset import DatasetInfo

    sensors = ["P-PDG", "T-TPT", "QGL", "ESTADO-W1"]
    info = DatasetInfo(
        Path("."), sensor_units={"P-PDG": "Pa", "T-TPT": "°C", "QGL": "m³/s", "ESTADO-W1": "-"}
    )
    rows = []
    keys = [(0, f"WELL-00001_{i}.parquet") for i in range(10)]
    for i, (fault, file) in enumerate(keys):
        for sensor in sensors:
            live = sensor != "QGL" and not (sensor == "T-TPT" and i % 2)  # QGL never, T-TPT half
            row = dict.fromkeys(pr.PROFILE_COLUMNS, np.nan)
            row.update(
                scope="instance", well=1, bar=-1, fault_class=fault, file=file, sensor=sensor
            )
            row.update(n_total=100, n_valid=100 if live else 0, n_implausible=0)
            row.update(n_genuine=10 if live else 0, n_interpolated=90 if live else 0, n_held=0)
            row.update(spacing_s=10.0 if live else np.nan)
            for name in pr.GRID_COLUMNS:
                row[name] = float(i) if live else np.nan
                row[f"{name}_g"] = float(2 * i) if live else np.nan
            row.update({"std": 1.0 if live else 0.0, "std_g": 1.0 if live else 0.0})
            row.update(listing_digest="x", version="1")
            rows.append(row)
    table = pd.DataFrame(rows)[pr.PROFILE_COLUMNS]
    profiles = pr.Profiles(table, sensors)
    rep = em.feature_matrix(profiles, keys, False, info)
    assert rep.n == 10 and "QGL" not in rep.sensors and "ESTADO-W1" in rep.sensors
    assert "T-TPT" in rep.sensors  # live in half of the points, on the threshold
    assert "ESTADO-W1 | mean" in rep.columns
    assert not any(c.startswith("ESTADO-W1 | skew") for c in rep.columns)
    assert "P-PDG | genuine_share" not in rep.columns  # constant: dropped
    assert rep.X.shape[0] == 10 and np.allclose(rep.X.mean(axis=0), 0, atol=1e-9)
    assert rep.imputed[1] > rep.imputed[0]  # the odd points lack T-TPT
    assert "imputed" in rep.note
    shape = em.feature_matrix(profiles, keys, False, info, shape_only=True)
    assert not any("mean" in c for c in shape.columns) and "ESTADO-W1" not in shape.sensors
    measured = em.feature_matrix(profiles, keys, False, info, measured=True)
    assert measured.columns == rep.columns  # the same columns, read from the ``_g`` figures
    # A threshold no sensor meets leaves an empty representation that still embeds.
    empty = em.feature_matrix(profiles, keys, False, info, min_coverage=1.5)
    assert empty.X.shape == (10, 0) and em.embed(empty, "PCA")[0].shape == (10, 2)


def test_dtw_compares_shapes_after_decimation():
    """Two cycles of different phase are close, two of different period far; the decimation keeps the shape."""
    from overlap_viewer.algorithms.dtw import N_BLOCKS, decimate

    t = np.arange(7200, dtype=float)
    slow = np.sin(2 * np.pi * t / 1800)
    shifted = np.sin(2 * np.pi * (t + 300) / 1800)
    fast = np.sin(2 * np.pi * t / 400)
    blocks = decimate(1e7 + 1e5 * slow)
    assert blocks is not None and len(blocks) == N_BLOCKS
    assert blocks.mean() == pytest.approx(0.0, abs=1e-9) and blocks.std() == pytest.approx(1.0)
    holed = slow.copy()
    holed[1000:1400] = np.nan
    assert decimate(holed) is not None and np.isfinite(decimate(holed)).all()
    assert decimate(np.full(7200, 3.0)) is None and decimate(np.full(7200, np.nan)) is None
    pytest.importorskip("dtaidistance")
    from overlap_viewer.algorithms.dtw import dtw_distances

    D = dtw_distances([decimate(slow), decimate(shifted), decimate(fast)])
    assert D.shape == (3, 3) and np.allclose(np.diag(D), 0) and D[0, 1] == pytest.approx(D[1, 0])
    assert D[0, 1] < D[0, 2] and D[1, 2] > D[0, 1]
