"""What one series amounts to in a handful of numbers. Numpy only.

The descriptors are the ones Melo's exploratory methodology (doctoral thesis,
section 4.1, and his KydLIB package) computes for every variable of a process
dataset, so that datasets can be compared on how dynamic, how noisy and how
Gaussian they are, together with the plain moments and quantiles. Here they
are computed per sensor of one instance, or of one merged recording, and
serve as the coordinates of an instance in the analyses that compare
instances.

- **Autocorrelation time** (thesis §4.1.3): the lag at which the sample
  autocorrelation first falls to one half, in seconds. A measure of how
  dynamic the series is, over a wide range of lags at once.
- **Signal-to-noise ratio** (thesis §4.1.4, after Feital and Pinto's
  variance spectrum): the variance of the whole series over the variance
  inside a window of two consecutive samples, the two being replicates of one
  measurement if the process does not move between them. A ratio, 1 meaning
  the series is all noise.
- **Gaussianity** (thesis §4.1.2, after Zhang et al. 2016): the squared
  Mahalanobis distances of the samples from their mean follow a scaled F
  distribution if the samples are Gaussian, so the order statistics of the
  distances are regressed on the quantiles of that distribution and the fit
  is judged: the regression must be tight (residual scatter under 15 % of the
  mean quantile), its slope within 0.2 of one and its offset within 5 % of
  the mean quantile. Here the test is univariate, one sensor at a time, so the
  distance is the squared z-score and the reference is F(1, n−1), which for
  the thousands of samples of an instance is the chi-squared distribution
  with one degree of freedom; its quantiles are computed here without SciPy.

Every descriptor is computed over the readings it is given: the caller
decides whether those are every sample of the 1 Hz grid or the measurements
alone (``algorithms.interpolation``). On the grid the straight lines the
historian drew between measurements make the series look far more
autocorrelated and far less noisy than the process is, which is the caveat
the viewer states wherever it shows these figures in *interpolated* mode.
"""

from dataclasses import dataclass

import numpy as np

# The autocorrelation is followed out to this lag and no further: a series
# that has not halved its autocorrelation in six hours is a drift, and its
# time is reported as infinite.
ACF_MAX_LAG_S = 6 * 3600.0
# The Gaussianity regression is fitted on at most this many samples, strided
# through the series: the test is about the shape of the distribution, which
# fifty thousand samples describe as well as a million.
GAUSS_MAX_SAMPLES = 50_000
# Zhang's thresholds: the residual scatter, the offset, the slope.
GAUSS_SCATTER_LIMIT = 0.15
GAUSS_OFFSET_LIMIT = 0.05
GAUSS_SLOPE_LIMIT = 0.2
# Below this many readings nothing is described.
MIN_SAMPLES = 8


@dataclass(frozen=True)
class Descriptors:
    """The figures of one series.

    ``acf_half_s`` is infinite when the autocorrelation never halves within
    ``ACF_MAX_LAG_S`` and NaN when it cannot be computed; ``snr`` is infinite
    for a series whose consecutive samples never differ. The three ``gauss_``
    figures are the slope of Zhang's regression, its offset and its residual
    scatter, the last two as shares of the mean reference quantile;
    ``gaussian`` is the verdict of his test.
    """

    n: int
    mean: float
    std: float
    skew: float
    kurtosis: float  # excess: zero for a Gaussian
    q05: float
    q25: float
    median: float
    q75: float
    q95: float
    low: float
    high: float
    acf_half_s: float
    snr: float
    gauss_slope: float
    gauss_offset: float
    gauss_scatter: float
    gaussian: bool

    @classmethod
    def empty(cls) -> "Descriptors":
        nan = float("nan")
        return cls(0, *([nan] * 16), False)


FIELDS = tuple(Descriptors.__dataclass_fields__)


def describe(values: np.ndarray, step_s: float = 1.0) -> Descriptors:
    """Every descriptor of one series of readings, taken ``step_s`` seconds apart.

    Missing values are dropped first; fewer than ``MIN_SAMPLES`` readings, or
    a series that never moves, give the moments and the quantiles and NaN for
    the rest.
    """
    y = np.asarray(values, dtype=float)
    y = y[~np.isnan(y)]
    n = len(y)
    if n == 0:
        return Descriptors.empty()
    mean = float(y.mean())
    std = float(y.std())
    q05, q25, median, q75, q95 = (float(q) for q in np.quantile(y, [0.05, 0.25, 0.5, 0.75, 0.95]))
    low, high = float(y.min()), float(y.max())
    nan = float("nan")
    if n < MIN_SAMPLES or std <= 0:
        return Descriptors(
            n,
            mean,
            std,
            nan,
            nan,
            q05,
            q25,
            median,
            q75,
            q95,
            low,
            high,
            nan,
            nan,
            nan,
            nan,
            nan,
            False,
        )
    z = (y - mean) / std
    skew = float(np.mean(z**3))
    kurtosis = float(np.mean(z**4) - 3.0)
    slope, offset, scatter, gaussian = gaussianity(y)
    return Descriptors(
        n,
        mean,
        std,
        skew,
        kurtosis,
        q05,
        q25,
        median,
        q75,
        q95,
        low,
        high,
        acf_half_time(y, step_s),
        signal_to_noise(y),
        slope,
        offset,
        scatter,
        gaussian,
    )


# -- dynamics


def autocorrelation(values: np.ndarray, max_lag: int) -> np.ndarray:
    """The sample autocorrelation ``rho_k`` for ``k = 0 .. max_lag`` (thesis eq. 4.9).

    Computed through the FFT of the zero-padded, demeaned series, which is the
    same sum as the direct formula, normalised by the total sum of squares.
    """
    y = np.asarray(values, dtype=float)
    y = y - y.mean()
    n = len(y)
    total = float(np.dot(y, y))
    if n < 2 or total <= 0:
        return np.ones(1)
    size = 1 << int(np.ceil(np.log2(2 * n)))
    spectrum = np.fft.rfft(y, size)
    acov = np.fft.irfft(spectrum * np.conj(spectrum), size)[: min(max_lag, n - 1) + 1]
    return acov / total


def acf_half_time(
    values: np.ndarray, step_s: float = 1.0, max_lag_s: float = ACF_MAX_LAG_S
) -> float:
    """The lag at which the autocorrelation first falls to 0.5, in seconds.

    Infinite when it has not halved by ``max_lag_s`` (or by the end of the
    series), which is a series dominated by a drift; NaN for a series too
    short or too flat to have an autocorrelation.
    """
    y = np.asarray(values, dtype=float)
    if len(y) < 2 or step_s <= 0:
        return float("nan")
    max_lag = max(1, int(max_lag_s / step_s))
    rho = autocorrelation(y, max_lag)
    if len(rho) < 2:
        return float("nan")
    below = np.flatnonzero(rho[1:] <= 0.5)
    if not len(below):
        return float("inf")
    k = int(below[0]) + 1
    # The crossing lies between k-1 and k; interpolate for a lag finer than the step.
    a, b = rho[k - 1], rho[k]
    frac = (a - 0.5) / (a - b) if a != b else 1.0
    return float((k - 1 + frac) * step_s)


# -- noise


def signal_to_noise(values: np.ndarray) -> float:
    """Total variance over the variance within two consecutive samples (thesis §4.1.4).

    The variance inside a window of two samples with its own mean is half the
    squared difference between them, so the noise variance is half the mean
    squared first difference. Infinite when consecutive samples never differ.
    """
    y = np.asarray(values, dtype=float)
    if len(y) < 3:
        return float("nan")
    total = float(y.var())
    noise = 0.5 * float(np.mean(np.diff(y) ** 2))
    if noise <= 0:
        return float("inf") if total > 0 else float("nan")
    return total / noise


# -- Gaussianity


def normal_quantile(p: np.ndarray) -> np.ndarray:
    """The quantile function of the standard normal distribution, to about 1e-9.

    Acklam's rational approximation, in three pieces; ``p`` strictly inside
    (0, 1). Kept here so that the descriptors need no SciPy.
    """
    p = np.asarray(p, dtype=float)
    a = (
        -3.969683028665376e01,
        2.209460984245205e02,
        -2.759285104469687e02,
        1.383577518672690e02,
        -3.066479806614716e01,
        2.506628277459239e00,
    )
    b = (
        -5.447609879822406e01,
        1.615858368580409e02,
        -1.556989798598866e02,
        6.680131188771972e01,
        -1.328068155288572e01,
    )
    c = (
        -7.784894002430293e-03,
        -3.223964580411365e-01,
        -2.400758277161838e00,
        -2.549732539343734e00,
        4.374664141464968e00,
        2.938163982698783e00,
    )
    d = (
        7.784695709041462e-03,
        3.224671290700398e-01,
        2.445134137142996e00,
        3.754408661907416e00,
    )
    low, high = 0.02425, 1 - 0.02425
    x = np.empty_like(p)
    tail = p < low
    if tail.any():
        q = np.sqrt(-2 * np.log(p[tail]))
        x[tail] = (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1
        )
    tail = p > high
    if tail.any():
        q = np.sqrt(-2 * np.log(1 - p[tail]))
        x[tail] = -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1
        )
    middle = ~(p < low) & ~(p > high)
    if middle.any():
        q = p[middle] - 0.5
        r = q * q
        x[middle] = (
            (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5])
            * q
            / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)
        )
    return x


def chi2_1_quantile(p: np.ndarray) -> np.ndarray:
    """Quantiles of the chi-squared distribution with one degree of freedom: the square of a normal one."""
    return normal_quantile(0.5 * (1.0 + np.asarray(p, dtype=float))) ** 2


def gaussianity(values: np.ndarray) -> tuple[float, float, float, bool]:
    """Zhang's regression of the squared distances on their reference quantiles (thesis eqs. 4.1-4.8).

    Returns the slope ``b`` of ``F = a + b × D``, the offset ``a`` and the
    residual scatter ``s``, both as shares of the mean reference quantile,
    and the verdict: Gaussian when ``s/F̄ < 0.15``, ``|a| ≤ 0.05 × F̄`` and
    ``|b − 1| ≤ 0.2``. The distances are the squared z-scores; the reference
    is ``(n+1)/n × F(1, n−1)``, taken as the chi-squared distribution with one
    degree of freedom, which it is to well within the thresholds for the
    sample sizes here.
    """
    y = np.asarray(values, dtype=float)
    y = y[~np.isnan(y)]
    if len(y) > GAUSS_MAX_SAMPLES:
        y = y[:: int(np.ceil(len(y) / GAUSS_MAX_SAMPLES))]
    n = len(y)
    nan = float("nan")
    if n < MIN_SAMPLES:
        return nan, nan, nan, False
    std = y.std()
    if std <= 0:
        return nan, nan, nan, False
    d = np.sort(((y - y.mean()) / std) ** 2)
    p = (np.arange(1, n + 1) - 0.5) / n
    f = chi2_1_quantile(p) * (n + 1) / n
    d_mean, f_mean = d.mean(), f.mean()
    ss = float(np.dot(d - d_mean, d - d_mean))
    if ss <= 0:
        return nan, nan, nan, False
    b = float(np.dot(d - d_mean, f - f_mean) / ss)
    a = float(f_mean - b * d_mean)
    residual = f - (a + b * d)
    s = float(np.sqrt(np.dot(residual, residual) / max(n - 2, 1)))
    scatter, offset = s / f_mean, abs(a) / f_mean
    gaussian = bool(
        scatter < GAUSS_SCATTER_LIMIT
        and offset <= GAUSS_OFFSET_LIMIT
        and abs(b - 1.0) <= GAUSS_SLOPE_LIMIT
    )
    return b, a / f_mean, scatter, gaussian
