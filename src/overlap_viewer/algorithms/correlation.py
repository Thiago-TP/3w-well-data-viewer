"""How the sensors move together over a set of instances: Pearson and mutual information. Numpy only, the mutual information through the ``analysis`` extra.

Melo's exploratory methodology (doctoral thesis, section 4.1.5) reads the
relations between the variables of a dataset three ways at once. The
**Pearson coefficient** is the linear correlation. The **mutual-information
coefficient** is a nonlinear one: the mutual information *I* of two
variables, estimated by nearest neighbours (Kraskov, Stögbauer and
Grassberger's estimator, which ``ennemi`` and scikit-learn both implement),
turned into a coefficient between 0 and 1 by Laarne *et al.*'s normalisation,
``ρ_I = sqrt(1 − exp(−2 I))``, which equals the Pearson coefficient when the
two variables are jointly Gaussian. Zhang *et al.*'s **nonlinear
coefficient** is what the second says beyond the first, ``r = ρ_I (1 − |ρ|)``.
Over a whole set of variables the thesis sums each into a global figure
(equations 4.15 and 4.16): ``ρ = sqrt((Σ ρ_ij² − m) / (m² − m))`` and
``r = sqrt(Σ r_ij² / (m² − m))`` over the ``m × m`` matrix.

The thesis also smooths the series with a moving average before taking the
coefficients (its figures 4.11 and 4.26), noise hiding the relations. The
viewer used to offer that at several window lengths and no longer does: on 3W
the pooled coefficients hardly move with it (the whole dataset's global
coefficient went from 0.420 unsmoothed to 0.424 at five minutes), being set by
the levels the sensors sit at from one instance to the next.

The Pearson coefficients are exact over every co-valid sample of the
instances in the scope, accumulated as running sums so that a scope of a
million samples costs a pass and no memory. The mutual information is
estimated on an even subsample of the same samples, a few thousand rows,
which is what the estimator handles in a second and enough for a coefficient
read to two digits. Samples are pooled across the instances of the scope,
which is what a correlation *over a class* or *over a well* means here; a
scope that mixes wells mixes their levels, and the help says what that does.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from overlap_viewer.backend.extras import available

COEFFICIENTS = ("Pearson", "Mutual information", "Nonlinear")
# Fewer co-valid samples than this and a pair says nothing.
MIN_PAIRS = 300
# The subsample the mutual information is estimated on, over the whole scope.
MAX_MI_SAMPLES = 4000
MI_NEIGHBORS = 3


@dataclass(frozen=True)
class Correlations:
    """The three coefficients of every pair of sensors.

    Every matrix is ``(sensors, sensors)`` and symmetric, NaN where a pair
    has fewer than ``MIN_PAIRS`` co-valid samples (or, for the mutual
    information, where the extra is missing). ``pairs`` counts the co-valid
    samples; ``n_instances`` how many events the scope pooled.
    """

    sensors: list[str]
    pearson: np.ndarray
    pairs: np.ndarray
    mi_coefficient: np.ndarray | None
    nonlinear: np.ndarray | None
    n_instances: int
    mi_samples: int = 0

    def matrix(self, coefficient: str) -> np.ndarray | None:
        if coefficient == "Pearson":
            return self.pearson
        if coefficient == "Mutual information":
            return self.mi_coefficient
        return self.nonlinear

    def present(self) -> np.ndarray:
        """Which sensors have enough co-valid samples with at least one other sensor."""
        pairs = self.pairs.copy()
        np.fill_diagonal(pairs, 0)
        return (pairs >= MIN_PAIRS).any(axis=1)

    def global_coefficients(self) -> tuple[float, float]:
        """Melo's global linear and nonlinear coefficients (thesis eqs. 4.16 and 4.15) over the sensors present."""
        present = self.present()
        m = int(present.sum())
        if m < 2:
            return (float("nan"), float("nan"))
        rho = self.pearson[np.ix_(present, present)]
        rho_sum = float(np.nansum(rho**2))
        linear = float(np.sqrt(max(rho_sum - m, 0.0) / (m * m - m)))
        if self.nonlinear is None:
            return (linear, float("nan"))
        r = self.nonlinear[np.ix_(present, present)]
        nonlinear = float(np.sqrt(np.nansum(r**2) / (m * m - m)))
        return (linear, nonlinear)


def mi_coefficient(mutual_information: np.ndarray) -> np.ndarray:
    """Laarne's normalisation of a mutual information (in nats) into a coefficient between 0 and 1."""
    return np.sqrt(
        1.0 - np.exp(-2.0 * np.maximum(np.asarray(mutual_information, dtype=float), 0.0))
    )


class CorrelationPass:
    """Accumulates the co-valid sums of every pair of sensors over the frames it is fed.

    ``budget`` is how many rows the mutual-information subsample may take in
    all, spread evenly over the ``n_instances`` the scope holds.
    """

    def __init__(
        self,
        sensors: Sequence[str],
        bounds: Sequence[tuple[float, float]],
        n_instances: int,
        budget: int = MAX_MI_SAMPLES,
    ):
        self.sensors = list(sensors)
        self.bounds = list(bounds)
        self.n_instances = max(int(n_instances), 1)
        self.per_instance = max(budget // self.n_instances, 8)
        s = len(self.sensors)
        self._n = np.zeros((s, s))
        self._sx = np.zeros((s, s))
        self._sxx = np.zeros((s, s))
        self._sxy = np.zeros((s, s))
        self._rows: list[np.ndarray] = []
        self.fed = 0

    def add(self, frame: pd.DataFrame) -> None:
        """Take one instance, or one merged recording."""
        s = len(self.sensors)
        raw = np.full((len(frame), s), np.nan)
        for j, name in enumerate(self.sensors):
            if name in frame.columns:
                values = frame[name].to_numpy(dtype=float)
                low, high = self.bounds[j]
                raw[:, j] = np.where((values < low) | (values > high), np.nan, values)
        valid = ~np.isnan(raw)
        V = valid.astype(float)
        X0 = np.where(valid, raw, 0.0)
        self._n += V.T @ V
        self._sx += X0.T @ V  # Σ x_i over the samples where i and j are both valid
        self._sxx += (X0**2).T @ V
        self._sxy += X0.T @ X0
        if len(raw):
            stride = max(1, int(np.ceil(len(raw) / self.per_instance)))
            # A copy: a strided view would keep the whole frame alive for every
            # instance, gigabytes over a dataset.
            self._rows.append(raw[::stride].copy())
        self.fed += 1

    def result(self, mutual_information: bool = True) -> Correlations:
        """The coefficients from what was fed; the mutual information only with the ``analysis`` extra."""
        n, sx, sxx, sxy = self._n, self._sx, self._sxx, self._sxy
        sy, syy = sx.T, sxx.T
        with np.errstate(invalid="ignore", divide="ignore"):
            cov = n * sxy - sx * sy
            var_x = n * sxx - sx**2
            var_y = n * syy - sy**2
            rho = cov / np.sqrt(var_x * var_y)
        pearson = np.clip(np.where(n >= MIN_PAIRS, rho, np.nan), -1.0, 1.0)
        mi = nonlinear = None
        mi_samples = 0
        if mutual_information and available("analysis"):
            rows = np.vstack(self._rows) if self._rows else np.zeros((0, len(self.sensors)))
            mi_samples = len(rows)
            mi = self._mutual_information(rows, n)
            nonlinear = mi * (1.0 - np.abs(pearson))
        return Correlations(self.sensors, pearson, n, mi, nonlinear, self.fed, mi_samples)

    def _mutual_information(self, rows: np.ndarray, pairs: np.ndarray) -> np.ndarray:
        """Laarne's coefficient of every pair with enough co-valid rows in the subsample."""
        from sklearn.feature_selection import mutual_info_regression

        s = len(self.sensors)
        out = np.full((s, s), np.nan)
        for i in range(s):
            out[i, i] = 1.0 if pairs[i, i] >= MIN_PAIRS else np.nan
            for j in range(i + 1, s):
                if pairs[i, j] < MIN_PAIRS:
                    continue
                both = ~np.isnan(rows[:, i]) & ~np.isnan(rows[:, j])
                if both.sum() < 2 * MI_NEIGHBORS + 2:
                    continue
                x, y = rows[both, i], rows[both, j]
                if x.std() <= 0 or y.std() <= 0:
                    continue
                info = mutual_info_regression(
                    x[:, None], y, n_neighbors=MI_NEIGHBORS, random_state=0
                )[0]
                out[i, j] = out[j, i] = float(mi_coefficient(np.array([info]))[0])
        return out


@dataclass
class CorrelationScope:
    """What a correlation matrix was taken over, for its caption."""

    kind: str  # "all", "class" or "well"
    key: int
    joined: bool
    name: str = field(default="")
