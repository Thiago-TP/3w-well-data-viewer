"""Where every instance stands among the others: a representation, an embedding, clusterings, typicality, novelty.

The unit here is the **instance** (or, in the joined view, the bar, the
merged recording), never the window a pipeline cuts: 1,119 points, one per
real instance of 3W 2.0.0, which is what a reader can hold in view and click
on. An instance becomes a point through a **representation**:

- its **descriptors** (``backend.profiles``): per sensor the moments, the
  quantiles, the autocorrelation time, the signal-to-noise ratio, the
  Gaussianity slope, and how it was measured, either on the 1 Hz grid or on
  the measurements alone, which is the honest version wherever the
  historian's lines matter (``algorithms.interpolation``);
- the same descriptors **less the levels**, when the shape of the signals is
  the question and the level of a well is not;
- the **DTW distance** between the instances of one class on one sensor
  (``algorithms.dtw``), the 3W Toolkit's own way of comparing shapes.

The first two give a matrix of standardized columns; the third a matrix of
distances. From either, an **embedding** puts the points on a plane: PCA (or,
for distances, classical MDS), in numpy; t-SNE and UMAP through their
libraries, which are optional extras. A **clustering** groups the points (
k-means, a Gaussian mixture, agglomerative, DBSCAN, the short list Siqueira's
notebooks work through) and is scored by its silhouette and by how far it
agrees with the fault classes and with the wells (adjusted Rand index,
normalised mutual information). **Typicality** is an instance's distance to
the medoid of its class in the representation: how ordinary an instance of
its class it is. **Novelty** is a label audit: a one-class model of the normal
instances scores every instance, and an instance whose label disagrees with
the verdict (a fault that looks normal, a normal instance that looks
anomalous) is listed for a reader to look at.

Everything a library computes is an *analysis of the catalogue*, light enough
to run on every change of a box; nothing here is a model of the process, and
nothing is kept.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np

from overlap_viewer.algorithms.descriptors import ACF_MAX_LAG_S
from overlap_viewer.backend.dataset import DatasetInfo
from overlap_viewer.backend.extras import available
from overlap_viewer.backend.profiles import Profiles

REPRESENTATIONS = ("descriptors", "shape", "dtw")
REPRESENTATION_NAMES = {
    "descriptors": "Descriptors",
    "shape": "Descriptors, shape only",
    "dtw": "DTW of a sensor, within a class",
}
EMBEDDINGS = ("PCA", "t-SNE", "UMAP")
CLUSTERINGS = ("None", "k-means", "Gaussian mixture", "Agglomerative", "DBSCAN")

# A sensor enters the representation only if it is live in at least this share
# of the points: a sensor two wells carry says which two wells, and nothing
# about the other points, whose cells would all be imputed.
MIN_SENSOR_COVERAGE = 0.5
# The descriptors of a sensor, by name in the profile table. The levels are
# what the shape-only representation leaves out.
LEVEL_FIELDS = ("mean", "std", "median", "q05", "q95")
SHAPE_FIELDS = ("skew", "kurtosis", "acf_half_s", "snr", "gauss_slope")
SAMPLING_FIELDS = ("genuine_share", "spacing_s")
# Logarithms tame the two ratios and the two times, which range over decades.
LOG_FIELDS = {"acf_half_s", "snr", "spacing_s"}
ACF_CAP_S = 10 * ACF_MAX_LAG_S  # an infinite autocorrelation time lands here
SNR_RANGE = (1e-3, 1e9)
RANDOM_STATE = 0
# DBSCAN's radius is read from the data: the median distance to the k-th
# neighbour, k being the minimum size of a cluster.
DBSCAN_MIN_SAMPLES = 5


@dataclass
class Representation:
    """The points, as coordinates or as distances, with what went into them.

    ``X`` is ``(n, p)`` standardized (zero mean, unit variance per column) and
    ``distances`` ``None`` for the descriptor representations; for DTW ``X``
    is ``None`` and ``distances`` is the ``(n, n)`` matrix. ``keys`` name the
    points as the profile table does (``(fault_class, file)`` or
    ``(well, bar)``); ``columns`` name the columns of ``X``; ``imputed`` is
    the share of the cells of each point that had to be imputed.
    """

    keys: list
    X: np.ndarray | None
    columns: list[str] = field(default_factory=list)
    distances: np.ndarray | None = None
    imputed: np.ndarray = field(default_factory=lambda: np.zeros(0))
    sensors: list[str] = field(default_factory=list)
    note: str = ""

    @property
    def n(self) -> int:
        return len(self.keys)

    @property
    def metric(self) -> bool:
        """Whether the points come as distances rather than as coordinates."""
        return self.distances is not None

    def pairwise(self) -> np.ndarray:
        """Euclidean distances between the points, or the distances given."""
        if self.distances is not None:
            return self.distances
        return euclidean_distances(self.X)


def euclidean_distances(X: np.ndarray) -> np.ndarray:
    """All pairwise Euclidean distances of the rows of ``X``, exactly zero on the diagonal."""
    sq = np.einsum("ij,ij->i", X, X)
    d2 = sq[:, None] + sq[None, :] - 2.0 * (X @ X.T)
    D = np.sqrt(np.maximum(d2, 0.0))
    np.fill_diagonal(D, 0.0)
    return D


# -- the representations


def _transform(field_name: str, values: np.ndarray) -> np.ndarray:
    """Put one descriptor on a scale a distance can be taken over."""
    out = np.asarray(values, dtype=float).copy()
    if field_name == "acf_half_s":
        out = np.where(np.isinf(out), ACF_CAP_S, out)
        out = np.log10(np.clip(out, 1.0, ACF_CAP_S))
    elif field_name == "snr":
        out = np.log10(np.clip(out, *SNR_RANGE))
    elif field_name == "spacing_s":
        out = np.log10(np.clip(out, 1.0, None))
    return out


def feature_matrix(
    profiles: Profiles,
    keys: Sequence,
    joined: bool,
    info: DatasetInfo,
    shape_only: bool = False,
    measured: bool = False,
    min_coverage: float = MIN_SENSOR_COVERAGE,
) -> Representation:
    """The descriptor representation of ``keys``: one standardized column per (sensor, descriptor).

    A sensor is taken only if it is live (readings that move) in at least
    ``min_coverage`` of the points; an enumerated variable contributes its
    mean alone, the share of the time the valve was open. ``measured`` reads
    the descriptors taken on the measurements rather than on the grid
    (``backend.profiles``). Missing cells (the sensor absent or frozen in
    that instance) take the column's median, and ``imputed`` remembers how
    much of each point was made up that way. Columns that never move are
    dropped; the rest are standardized.
    """
    keys = list(keys)
    sensors = list(profiles.sensors)
    n_valid = profiles.matrix(keys, joined, "n_valid", sensors)
    std = profiles.matrix(keys, joined, "std", sensors)
    live = (np.nan_to_num(n_valid) > 0) & (np.nan_to_num(std) > 0)
    coverage = live.mean(axis=0) if len(keys) else np.zeros(len(sensors))
    taken = [j for j, name in enumerate(sensors) if coverage[j] >= min_coverage]
    columns: list[str] = []
    blocks: list[np.ndarray] = []
    suffix = "_g" if measured else ""
    for j in taken:
        name = sensors[j]
        if info.is_enumerated(name):
            fields = () if shape_only else ("mean",)
            sampling: tuple[str, ...] = ()
        else:
            fields = SHAPE_FIELDS if shape_only else LEVEL_FIELDS + SHAPE_FIELDS
            sampling = SAMPLING_FIELDS
        for field_name in fields:
            values = profiles.matrix(keys, joined, field_name + suffix, [name])[:, 0]
            values = np.where(live[:, j], values, np.nan)
            blocks.append(_transform(field_name, values))
            columns.append(f"{name} | {field_name}")
        for field_name in sampling:
            if field_name == "genuine_share":
                genuine = profiles.matrix(keys, joined, "n_genuine", [name])[:, 0]
                values = np.where(n_valid[:, j] > 0, genuine / np.maximum(n_valid[:, j], 1), np.nan)
            else:
                values = profiles.matrix(keys, joined, "spacing_s", [name])[:, 0]
            values = np.where(live[:, j], values, np.nan)
            blocks.append(_transform(field_name, values))
            columns.append(f"{name} | {field_name}")
    if not blocks:
        return Representation(keys, np.zeros((len(keys), 0)), [], None, np.ones(len(keys)))
    raw = np.column_stack(blocks)
    missing = np.isnan(raw)
    imputed = missing.mean(axis=1)
    X, kept = standardize(impute(raw))
    kept_columns = [columns[k] for k in kept]
    kept_sensors = sorted({column.split(" | ")[0] for column in kept_columns}, key=sensors.index)
    note = (
        f"{len(kept_sensors)} sensors live in at least {min_coverage:.0%} of the points | "
        f"{len(kept_columns)} columns | {imputed.mean():.0%} of the cells imputed"
    )
    return Representation(keys, X, kept_columns, None, imputed, kept_sensors, note)


def impute(raw: np.ndarray) -> np.ndarray:
    """Fill the missing cells of every column with the column's median (zero when all are missing)."""
    out = np.asarray(raw, dtype=float).copy()
    for j in range(out.shape[1]):
        column = out[:, j]
        missing = np.isnan(column)
        if missing.all():
            out[:, j] = 0.0
        elif missing.any():
            column[missing] = np.median(column[~missing])
    return out


def standardize(X: np.ndarray) -> tuple[np.ndarray, list[int]]:
    """Zero mean and unit variance per column, dropping the columns that never move.

    Returns the standardized matrix and the positions of the columns kept.
    """
    X = np.asarray(X, dtype=float)
    mean = X.mean(axis=0)
    std = X.std(axis=0)
    # A column of ten identical values has a spread of a few 1e-17 in floating
    # point, not zero; anything below rounding, relative to the level, is flat.
    floor = 1e-9 * np.maximum(np.abs(mean), 1.0)
    kept = [j for j in range(X.shape[1]) if np.isfinite(std[j]) and std[j] > floor[j]]
    Z = (X[:, kept] - mean[kept]) / std[kept]
    return Z, kept


def distance_representation(
    keys: Sequence, distances: np.ndarray, note: str = ""
) -> Representation:
    """The points as a matrix of distances between them, e.g. DTW within one class."""
    D = np.asarray(distances, dtype=float)
    return Representation(list(keys), None, [], D, np.zeros(len(keys)), [], note)


# -- embeddings


def pca(X: np.ndarray, n_components: int = 2) -> tuple[np.ndarray, np.ndarray]:
    """Principal components by SVD: the scores and the share of variance each explains."""
    X = np.asarray(X, dtype=float)
    n, p = X.shape
    k = min(n_components, p, max(n - 1, 1))
    if p == 0 or n == 0:
        return np.zeros((n, n_components)), np.zeros(n_components)
    centered = X - X.mean(axis=0)
    _u, s, vt = np.linalg.svd(centered, full_matrices=False)
    total = float(np.sum(s**2))
    scores = centered @ vt[:k].T
    explained = (s[:k] ** 2) / total if total > 0 else np.zeros(k)
    if k < n_components:
        scores = np.column_stack([scores, np.zeros((n, n_components - k))])
        explained = np.concatenate([explained, np.zeros(n_components - k)])
    return scores, explained


def classical_mds(D: np.ndarray, n_components: int = 2) -> tuple[np.ndarray, np.ndarray]:
    """Torgerson's principal coordinates of a distance matrix, and the share of its spread each carries."""
    D = np.asarray(D, dtype=float)
    n = len(D)
    if n == 0:
        return np.zeros((0, n_components)), np.zeros(n_components)
    J = np.eye(n) - np.ones((n, n)) / n
    B = -0.5 * J @ (D**2) @ J
    values, vectors = np.linalg.eigh(B)
    order = np.argsort(values)[::-1]
    values, vectors = values[order], vectors[:, order]
    positive = np.clip(values, 0.0, None)
    k = min(n_components, n)
    coords = vectors[:, :k] * np.sqrt(positive[:k])
    total = float(positive.sum())
    explained = positive[:k] / total if total > 0 else np.zeros(k)
    if k < n_components:
        coords = np.column_stack([coords, np.zeros((n, n_components - k))])
        explained = np.concatenate([explained, np.zeros(n_components - k)])
    return coords, explained


def embed(rep: Representation, method: str) -> tuple[np.ndarray, str]:
    """The points on a plane, by ``method``, and a caption saying what the axes are.

    PCA needs numpy alone; t-SNE needs the ``analysis`` extra and UMAP the
    ``umap`` extra. A metric representation goes through classical MDS in
    place of PCA and through the libraries' precomputed-distance modes.
    """
    if method not in EMBEDDINGS:
        raise ValueError(f"unknown embedding {method!r}; expected one of {EMBEDDINGS}")
    n = rep.n
    if n < 3:
        return np.zeros((n, 2)), "too few points to embed"
    if method == "PCA":
        if rep.metric:
            coords, explained = classical_mds(rep.distances)
            return coords, (
                f"principal coordinates of the distances | "
                f"{explained[0]:.0%} + {explained[1]:.0%} of the spread"
            )
        coords, explained = pca(rep.X)
        return coords, f"PC1 {explained[0]:.0%} + PC2 {explained[1]:.0%} of the variance"
    if method == "t-SNE":
        from sklearn.manifold import TSNE

        perplexity = float(min(30, max(2, (n - 1) // 3)))
        model = TSNE(
            n_components=2,
            perplexity=perplexity,
            init="random" if rep.metric else "pca",
            metric="precomputed" if rep.metric else "euclidean",
            random_state=RANDOM_STATE,
        )
        coords = model.fit_transform(rep.distances if rep.metric else rep.X)
        return coords, f"t-SNE, perplexity {perplexity:g} | the axes have no unit"
    import umap

    neighbors = int(min(15, max(2, n - 1)))
    model = umap.UMAP(
        n_components=2,
        n_neighbors=neighbors,
        metric="precomputed" if rep.metric else "euclidean",
        random_state=RANDOM_STATE,
    )
    coords = model.fit_transform(rep.distances if rep.metric else rep.X)
    return np.asarray(coords, dtype=float), f"UMAP, {neighbors} neighbours | the axes have no unit"


def embedding_available(method: str) -> str | None:
    """``None`` when the embedding can run here, else the sentence naming the missing extra."""
    from overlap_viewer.backend.extras import missing

    if method == "t-SNE":
        return missing("analysis")
    if method == "UMAP":
        return missing("umap")
    return None


# -- clusterings and their scores


def cluster(rep: Representation, method: str, k: int) -> np.ndarray:
    """Cluster labels per point, ``-1`` for a point DBSCAN leaves out; needs the ``analysis`` extra.

    The coordinate methods (k-means, the mixture) run on the standardized
    columns, or on the principal coordinates of a metric representation;
    agglomerative clustering and DBSCAN take the distances themselves.
    """
    if method not in CLUSTERINGS:
        raise ValueError(f"unknown clustering {method!r}; expected one of {CLUSTERINGS}")
    n = rep.n
    if method == "None" or n < 2:
        return np.zeros(n, dtype=int)
    k = int(max(1, min(k, n - 1)))
    if method in ("k-means", "Gaussian mixture"):
        X = rep.X if not rep.metric else classical_mds(rep.distances, min(10, n - 1))[0]
        if method == "k-means":
            from sklearn.cluster import KMeans

            return KMeans(n_clusters=k, n_init=10, random_state=RANDOM_STATE).fit_predict(X)
        from sklearn.mixture import GaussianMixture

        return GaussianMixture(
            n_components=k, covariance_type="diag", random_state=RANDOM_STATE
        ).fit_predict(X)
    D = rep.pairwise()
    if method == "Agglomerative":
        from sklearn.cluster import AgglomerativeClustering

        return AgglomerativeClustering(
            n_clusters=k, metric="precomputed", linkage="average"
        ).fit_predict(D)
    from sklearn.cluster import DBSCAN

    eps = dbscan_radius(D)
    return DBSCAN(eps=eps, min_samples=DBSCAN_MIN_SAMPLES, metric="precomputed").fit_predict(D)


def dbscan_radius(D: np.ndarray, min_samples: int = DBSCAN_MIN_SAMPLES) -> float:
    """A radius read from the data: the median distance to the ``min_samples``-th neighbour."""
    n = len(D)
    if n <= 1:
        return 1.0
    k = min(min_samples, n - 1)
    kth = np.sort(D, axis=1)[:, k]
    radius = float(np.median(kth))
    return radius if radius > 0 else float(np.max(D)) or 1.0


@dataclass(frozen=True)
class ClusterScores:
    """How good a clustering is on its own, and how far it agrees with what is known."""

    n_clusters: int
    n_noise: int
    silhouette: float
    ari_class: float
    nmi_class: float
    ari_well: float
    nmi_well: float

    def describe(self) -> str:
        parts = [f"{self.n_clusters} clusters"]
        if self.n_noise:
            parts[0] += f", {self.n_noise} points left out"
        if np.isfinite(self.silhouette):
            parts.append(f"silhouette {self.silhouette:.2f}")
        if np.isfinite(self.ari_class):
            parts.append(f"vs classes ARI {self.ari_class:.2f}, NMI {self.nmi_class:.2f}")
        if np.isfinite(self.ari_well):
            parts.append(f"vs wells ARI {self.ari_well:.2f}, NMI {self.nmi_well:.2f}")
        return " | ".join(parts)


def cluster_scores(
    rep: Representation, labels: np.ndarray, classes: Sequence[int], wells: Sequence[int]
) -> ClusterScores:
    """Silhouette of the clustering, and its agreement with the fault classes and the wells.

    The silhouette is taken over the points in a cluster (noise left out) and
    over the distances of the representation; the agreements are the adjusted
    Rand index and the normalised mutual information, 1 for a clustering that
    is the classes (or the wells) under other names, about 0 for one unrelated
    to them. NaN wherever a score is undefined.
    """
    from sklearn.metrics import (
        adjusted_rand_score,
        normalized_mutual_info_score,
        silhouette_score,
    )

    labels = np.asarray(labels)
    classes = np.asarray(list(classes))
    wells = np.asarray(list(wells))
    kept = labels >= 0
    n_clusters = len(set(labels[kept].tolist()))
    nan = float("nan")
    silhouette = nan
    if 2 <= n_clusters < int(kept.sum()):
        D = rep.pairwise()[np.ix_(kept, kept)]
        silhouette = float(silhouette_score(D, labels[kept], metric="precomputed"))
    if n_clusters >= 1 and kept.sum() >= 2:
        ari_c = float(adjusted_rand_score(classes[kept], labels[kept]))
        nmi_c = float(normalized_mutual_info_score(classes[kept], labels[kept]))
        ari_w = float(adjusted_rand_score(wells[kept], labels[kept]))
        nmi_w = float(normalized_mutual_info_score(wells[kept], labels[kept]))
    else:
        ari_c = nmi_c = ari_w = nmi_w = nan
    return ClusterScores(n_clusters, int((~kept).sum()), silhouette, ari_c, nmi_c, ari_w, nmi_w)


# -- typicality


@dataclass(frozen=True)
class Typicality:
    """How ordinary an instance of its class each point is.

    ``distance`` is the point's distance to the medoid of its class in the
    representation; ``rank`` its typicality rank inside the class, 1 for the
    medoid itself and 0 for the farthest member, NaN for a class of one;
    ``medoids`` names the medoid of each class by its position.
    """

    distance: np.ndarray
    rank: np.ndarray
    medoids: dict[int, int]


def typicality(rep: Representation, classes: Sequence[int]) -> Typicality:
    """The distance of every point to the medoid of its class, and its rank there.

    The medoid is the member whose distances to the others sum lowest: the
    most central instance the class actually has, which a mean need not be.
    """
    classes = np.asarray(list(classes))
    n = rep.n
    distance = np.full(n, np.nan)
    rank = np.full(n, np.nan)
    medoids: dict[int, int] = {}
    if n == 0:
        return Typicality(distance, rank, medoids)
    D = rep.pairwise()
    for klass in sorted(set(classes.tolist())):
        members = np.flatnonzero(classes == klass)
        block = D[np.ix_(members, members)]
        medoid = int(members[np.argmin(block.sum(axis=1))])
        medoids[int(klass)] = medoid
        d = D[members, medoid]
        distance[members] = d
        if len(members) > 1:
            order = np.argsort(np.argsort(d))  # 0 for the medoid, len-1 for the farthest
            rank[members] = 1.0 - order / (len(members) - 1)
    return Typicality(distance, rank, medoids)


# -- novelty


@dataclass(frozen=True)
class Novelty:
    """What a one-class model of the normal instances makes of every point.

    ``score`` is the model's decision function, positive for a point that
    looks normal, negative for one that looks anomalous; ``anomalous`` the
    verdict; ``disagreements`` the positions whose label says otherwise: a
    fault instance that looks normal, a normal instance that looks anomalous.
    """

    score: np.ndarray
    anomalous: np.ndarray
    disagreements: np.ndarray

    def disagreements_of(self, classes: Sequence[int], klass: int) -> np.ndarray:
        classes = np.asarray(list(classes))
        return self.disagreements[classes[self.disagreements] == klass]


# The share of the normal instances a one-class model is allowed to leave
# outside its boundary: the normal folder is not free of anomalies either,
# which is the point of the audit.
NOVELTY_NU = 0.05


def novelty(rep: Representation, classes: Sequence[int], normal_class: int = 0) -> Novelty | None:
    """A one-class SVM fitted on the normal instances, scoring every point; needs the ``analysis`` extra.

    The model is the one Siqueira's notebooks use for novelty on 3W, a
    radial-basis one-class SVM; it draws the boundary of the region the
    normal instances occupy in the representation, leaving ``NOVELTY_NU`` of
    them outside, and every point is scored by its signed distance to that
    boundary. ``None`` for a metric representation (the model needs
    coordinates) or when fewer than a handful of normal instances are there
    to learn from.
    """
    if rep.metric or rep.X is None or not available("analysis"):
        return None
    from sklearn.svm import OneClassSVM

    classes = np.asarray(list(classes))
    normal = np.flatnonzero(classes == normal_class)
    if len(normal) < 8 or rep.X.shape[1] == 0:
        return None
    model = OneClassSVM(kernel="rbf", nu=NOVELTY_NU, gamma="scale")
    model.fit(rep.X[normal])
    score = model.decision_function(rep.X)
    anomalous = model.predict(rep.X) == -1
    disagreements = np.flatnonzero(
        ((classes == normal_class) & anomalous) | ((classes != normal_class) & ~anomalous)
    )
    return Novelty(score, anomalous, disagreements)
