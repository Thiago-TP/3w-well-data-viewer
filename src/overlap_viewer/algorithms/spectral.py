"""The signal views beyond the time series: distribution and spectrum. No Qt here, numpy only.

The 3W signals are sampled once a second and the events are slow: severe
slugging cycles every 50 to 90 minutes, flow instability every 45, so a
six-hour instance holds four to seven cycles. That fixes the conventions of
this module. The frequency axis is a **period** in seconds, logarithmic,
because a frequency of 0.0002 Hz says nothing to anyone and "every 90 minutes"
does. The default spectrum is taken over the whole stretch shown (a
periodogram), because any segment shorter than the stretch sees nothing longer
than itself, and a segment of a few minutes, the size a pipeline windows by,
holds no cycle of the events at all. Shorter segments are offered, averaged as
Welch does, and every result carries the longest period it can resolve so that
a plot can grey the axis beyond it rather than leave the long periods silently
empty.

A series is prepared before any transform: readings outside the plausible
range are masked, the missing samples are interpolated inside the stretch (the
grid is a fixed 1 Hz and the holes are rare), and the mean and the linear trend
are removed, since the trend would otherwise own every long period. A stretch
with fewer than half its readings, or a frozen sensor, declines: the caller
writes a note in place of a plot.

The 1 Hz grid is itself an interpolation for most sensors of the dataset (see
``algorithms.interpolation``): the historian drew straight lines between
measurements taken every ten seconds or every two minutes. A transform of the
grid is therefore a transform of those lines. Asked for the **measurements
only**, the views count the histogram over the genuine samples and take the
spectrum with the Lomb-Scargle periodogram, which needs no grid: it fits a
sinusoid of each period to the measurements at the instants they were taken,
and is the honest spectrum of an irregularly sampled series.
"""

from dataclasses import dataclass, field

import numpy as np

from overlap_viewer.backend.labels import is_flat

# The Lomb-Scargle periodogram is evaluated at this many periods, equally
# spaced in log period, and over at most this many measurements (thinned
# evenly beyond it: a merged recording of days has hundreds of thousands, and
# the periods of interest are minutes to hours).
LOMB_SCARGLE_PERIODS = 400
LOMB_SCARGLE_MAX_POINTS = 60_000
LOMB_SCARGLE_CHUNK = 16  # periods evaluated at once: chunk × points doubles of memory

# The window functions offered, by the name a toolbar shows for them. Numpy's
# own; a rectangular window is the plain segment.
WINDOWS: dict[str, object] = {
    "Hann": np.hanning,
    "Hamming": np.hamming,
    "Blackman": np.blackman,
    "Rectangular": np.ones,
}

# Below this share of readings a stretch is not transformed: interpolating over
# most of a series would draw the spectrum of the interpolation.
MIN_COVERAGE = 0.5
# And below this many readings there is nothing to estimate from.
MIN_SAMPLES = 16
# The dominant period is looked for among the periods the stretch holds at
# least this many cycles of: a single half-cycle is a trend, not a line.
MIN_CYCLES = 4.0


@dataclass(frozen=True)
class TransformParams:
    """What the user sets in the toolbar, shared by every view that transforms.

    ``segment_s`` is the segment length in samples (seconds); zero means the
    whole stretch, one segment, a periodogram. ``overlap`` is the share of a
    segment the next one repeats. ``bins`` and ``clamp`` are for the
    histograms: ``clamp`` counts only the readings inside the plausible range,
    which is how a histogram is normally read, and unticking it lets the
    garbage be looked at rather than only counted. ``genuine`` restricts every
    view to the measurements, leaving out the samples the historian filled in
    between them: the histograms count the measurements alone and the spectra
    become Lomb-Scargle periodograms over the instants of measurement.
    """

    segment_s: int = 0
    overlap: float = 0.5
    window: str = "Hann"
    bins: int = 40
    clamp: bool = True
    genuine: bool = False

    def __post_init__(self):
        if self.window not in WINDOWS:
            raise ValueError(f"unknown window {self.window!r}; expected one of {tuple(WINDOWS)}")
        if not 0.0 <= self.overlap < 1.0:
            raise ValueError("overlap must be in [0, 1)")
        if self.bins < 1:
            raise ValueError("at least one bin")


@dataclass(frozen=True)
class Spectrum:
    """A power spectral density against period, and what it can resolve.

    ``periods`` are ascending, in seconds, from the Nyquist period up to the
    segment length; ``power`` is the density in the unit of the series squared
    per hertz. ``segment_s`` is the segment the estimate averaged over, which is
    also the longest period it can resolve; ``n_segments`` how many.
    ``n_points`` is how many measurements a Lomb-Scargle estimate was taken
    over, and zero for Welch's, which works on the grid; ``explained`` is
    then, per period, the share of the variance a sinusoid of that period
    explains, the periodogram's own reading of the peak.
    """

    periods: np.ndarray
    power: np.ndarray
    segment_s: int
    n_segments: int
    n_points: int = 0
    explained: np.ndarray | None = None

    @property
    def lomb_scargle(self) -> bool:
        """Whether this is a periodogram of the measurements at their own instants."""
        return self.n_points > 0

    def dominant(self) -> tuple[float, float]:
        """The period carrying the most power, and that power's share of the total.

        Only periods the segment holds ``MIN_CYCLES`` of are candidates; the
        share is of the power over every period, so a normal instance, whose
        power is spread thin, scores a few percent where an oscillating one
        scores half or more. For a Lomb-Scargle estimate the share is the
        variance a sinusoid of the period explains, which is what its
        periodogram measures and does not depend on how finely the periods
        were laid out.
        """
        total = float(self.power.sum())
        if total <= 0 or not len(self.periods):
            return (np.nan, 0.0)
        candidates = self.periods <= self.segment_s / MIN_CYCLES
        if not candidates.any():
            return (np.nan, 0.0)
        masked = np.where(candidates, self.power, -np.inf)
        k = int(np.argmax(masked))
        if self.explained is not None and len(self.explained) == len(self.power):
            return (float(self.periods[k]), float(self.explained[k]))
        return (float(self.periods[k]), float(self.power[k] / total))

    def binned(self, n_bins: int = 160) -> tuple[np.ndarray, np.ndarray]:
        """The density averaged into ``n_bins`` bins equally spaced in log period, for drawing.

        The estimate has one value per frequency, so the short periods, where
        nothing of interest lives, own tens of thousands of points and the
        long ones a handful; drawn against a logarithmic period axis, that is
        a fuzz of noise at one end. Averaging inside log bins gives every
        stretch of the axis the same number of points, and the mean of the
        density inside a bin is the density of that band. Returns the bin
        centers, in seconds, and the mean power of each bin that holds a
        value; empty bins are left out.
        """
        if len(self.periods) < 2:
            return self.periods, self.power
        log = np.log10(self.periods)
        edges = np.linspace(log[0], log[-1], n_bins + 1)
        which = np.clip(np.searchsorted(edges, log, side="right") - 1, 0, n_bins - 1)
        sums = np.bincount(which, weights=self.power, minlength=n_bins)
        counts = np.bincount(which, minlength=n_bins)
        filled = counts > 0
        centers = 10.0 ** (0.5 * (edges[:-1] + edges[1:]))
        return centers[filled], sums[filled] / counts[filled]


@dataclass(frozen=True)
class Histogram:
    """Counts per bin, stacked by group: the label period each sample was in.

    ``edges`` has one more entry than there are bins. ``stacks`` maps a group
    key (whatever the caller passed, kept in first-seen order) to its counts;
    ``left_out`` is how many readings fell outside the plausible range and were
    not counted.
    """

    edges: np.ndarray
    stacks: dict = field(default_factory=dict)
    left_out: int = 0
    mean: float = np.nan  # of the readings counted
    median: float = np.nan

    @property
    def counts(self) -> np.ndarray:
        """Every group folded: the plain histogram."""
        total = np.zeros(len(self.edges) - 1, dtype=int)
        for counts in self.stacks.values():
            total += counts
        return total

    @property
    def total(self) -> int:
        return int(self.counts.sum())

    @property
    def peak(self) -> tuple[float, int]:
        """The middle of the fullest bin and how many readings fell in it.

        The value the stretch spends most of its time at, which is what a
        reader looks for first and what the mean and the median both miss when
        the distribution is skewed or has two humps, and a fault moving the
        readings makes both. ``(nan, 0)`` when nothing was counted; a tie goes
        to the lower bin, so the answer does not depend on how the counts were
        summed.
        """
        counts = self.counts
        if not len(counts) or counts.max() == 0:
            return (np.nan, 0)
        k = int(np.argmax(counts))
        return (float(0.5 * (self.edges[k] + self.edges[k + 1])), int(counts[k]))


# -- preparing a series


def uniform_series(index, values: np.ndarray, step_s: float = 1.0) -> tuple[np.ndarray, int]:
    """``values`` laid on the fixed grid its timestamps imply, missing rows as NaN.

    The transforms assume one sample per second; a recording whose index skips
    a row would otherwise shift everything after the hole. Returns the values
    on the grid and the whole number of seconds a sample position stands for
    (``step_s``), so a caller can place sample ``k`` at ``k * step_s`` from the
    first timestamp.
    """
    stamps = np.asarray(index, dtype="datetime64[ns]")
    values = np.asarray(values, dtype=float)
    if len(stamps) < 2:
        return values, int(step_s)
    step = np.timedelta64(round(step_s * 1e9), "ns")
    positions = ((stamps - stamps[0]) // step).astype(np.int64)
    n = int(positions[-1]) + 1
    if n == len(values) and positions[-1] == len(values) - 1:
        return values, int(step_s)
    grid = np.full(n, np.nan)
    grid[positions] = values
    return grid, int(step_s)


def prepare(values: np.ndarray, bounds: tuple[float, float] | None = None) -> np.ndarray | None:
    """A copy of ``values`` fit for a transform, or ``None`` when there is not enough to transform.

    Readings outside ``bounds`` are treated as missing; the missing samples are
    filled by linear interpolation between their neighbours (the ends by the
    nearest reading); the mean and the linear trend are removed. ``None`` when
    fewer than ``MIN_COVERAGE`` of the samples, or fewer than ``MIN_SAMPLES``,
    carry a reading, or when the readings never move, which is a frozen sensor
    and has no spectrum worth the name.
    """
    y = np.asarray(values, dtype=float).copy()
    if bounds is not None:
        y[(y < bounds[0]) | (y > bounds[1])] = np.nan
    valid = ~np.isnan(y)
    n = len(y)
    if n < MIN_SAMPLES or valid.sum() < MIN_SAMPLES or valid.mean() < MIN_COVERAGE:
        return None
    kept = y[valid]
    if is_flat(float(kept.min()), float(kept.max())):
        return None
    t = np.arange(n, dtype=float)
    if not valid.all():
        y = np.interp(t, t[valid], kept)
    slope, intercept = np.polyfit(t, y, 1)
    return y - (slope * t + intercept)


def _segment_length(n: int, segment_s: int) -> int:
    """The segment actually used: the one asked for, capped at the series, or the whole series."""
    if segment_s <= 0 or segment_s >= n:
        return n
    return max(int(segment_s), MIN_SAMPLES)


def _hop(segment: int, overlap: float) -> int:
    return max(1, round(segment * (1.0 - overlap)))


def _segments(x: np.ndarray, segment: int, hop: int) -> np.ndarray:
    """The segments of ``x`` as rows, the last one ending at or before the end of ``x``."""
    n = len(x)
    if segment >= n:
        return x[np.newaxis, :]
    starts = np.arange(0, n - segment + 1, hop)
    return np.lib.stride_tricks.sliding_window_view(x, segment)[starts]


def _densities(segments: np.ndarray, window: str, fs: float = 1.0) -> tuple[np.ndarray, np.ndarray]:
    """One-sided power spectral densities of the rows of ``segments``, and their frequencies."""
    length = segments.shape[1]
    taper = WINDOWS[window](length).astype(float)
    spectra = np.fft.rfft(segments * taper, axis=1)
    scale = 1.0 / (fs * float((taper**2).sum()))
    density = (np.abs(spectra) ** 2) * scale
    # One-sided: every bin but DC and, for an even length, Nyquist, stands for two.
    if length % 2 == 0:
        density[:, 1:-1] *= 2.0
    else:
        density[:, 1:] *= 2.0
    freqs = np.fft.rfftfreq(length, d=1.0 / fs)
    return freqs, density


# -- the spectrum


def welch(prepared: np.ndarray, params: TransformParams, fs: float = 1.0) -> Spectrum:
    """Welch's estimate of the power spectral density of a prepared series, against period.

    With ``params.segment_s`` at zero, or longer than the series, this is the
    periodogram of the whole series under the window chosen; otherwise the
    segments overlap by ``params.overlap`` and their densities are averaged.
    The zero-frequency bin, which the detrending emptied, is dropped, and the
    result runs from the shortest period up to the segment length.
    """
    x = np.asarray(prepared, dtype=float)
    segment = _segment_length(len(x), params.segment_s)
    hop = _hop(segment, params.overlap)
    rows = _segments(x, segment, hop)
    freqs, density = _densities(rows, params.window, fs)
    power = density.mean(axis=0)[1:]
    periods = 1.0 / freqs[1:]
    order = np.argsort(periods)
    return Spectrum(periods[order], power[order], int(segment), len(rows))


def average_spectra(spectra: list[Spectrum], n_bins: int = 160) -> Spectrum | None:
    """One density from several, averaged band by band on a shared logarithmic grid.

    This is how the spectra of a set of instances are pooled, and it is what
    Welch's method already does one level down: average the densities of
    several stretches of the same process rather than transform their
    concatenation. Concatenating is not an option here: the instances are cut
    from different months, and a transform reads consecutive samples as one
    second apart, so every gap between two of them would become a step and the
    seams would spread power across the whole axis.

    The instances have different lengths, so their estimates land on different
    frequencies and cannot be averaged point by point. Each is binned onto the
    shared grid first (``Spectrum.binned``, the same binning a plot draws
    with), and a band is the mean of the estimates that reach it, so the long
    periods only the longest instances resolve are still theirs to say. The
    result carries the longest segment of the set, which is the longest period
    any of them could resolve.

    ``None`` when there is nothing to average.
    """
    usable = [s for s in spectra if len(s.periods)]
    if not usable:
        return None
    if len(usable) == 1:
        return usable[0]
    lows = [np.log10(s.periods[0]) for s in usable]
    highs = [np.log10(s.periods[-1]) for s in usable]
    grid = np.linspace(min(lows), max(highs), n_bins)
    total = np.zeros(n_bins)
    counts = np.zeros(n_bins)
    for spectrum in usable:
        periods, power = spectrum.binned(n_bins)
        if not len(periods):
            continue
        log = np.log10(periods)
        # Only the stretch of the axis this estimate actually covers: reading
        # its ends across the rest would invent power at periods it never saw.
        inside = (grid >= log[0]) & (grid <= log[-1])
        if not inside.any():
            continue
        total[inside] += np.interp(grid[inside], log, power)
        counts[inside] += 1
    filled = counts > 0
    if not filled.any():
        return None
    return Spectrum(
        10.0 ** grid[filled],
        total[filled] / counts[filled],
        max(s.segment_s for s in usable),
        sum(s.n_segments for s in usable),
        sum(s.n_points for s in usable),
    )


# -- the spectrum of the measurements alone


def prepare_irregular(
    times_s: np.ndarray, values: np.ndarray, bounds: tuple[float, float] | None = None
) -> tuple[np.ndarray, np.ndarray] | None:
    """The instants and the readings of the measurements, fit for a Lomb-Scargle transform.

    Readings outside ``bounds`` and missing ones are dropped with their
    instants; the mean and the linear trend are removed, as ``prepare`` does
    on the grid. ``None`` with fewer than ``MIN_SAMPLES`` measurements or a
    flat series. More than ``LOMB_SCARGLE_MAX_POINTS`` measurements are
    thinned evenly, which keeps the sampling irregular and the periods of
    interest, minutes to hours, as well covered as before.
    """
    t = np.asarray(times_s, dtype=float)
    y = np.asarray(values, dtype=float)
    keep = ~np.isnan(y) & ~np.isnan(t)
    if bounds is not None:
        keep &= (y >= bounds[0]) & (y <= bounds[1])
    t, y = t[keep], y[keep]
    if len(y) < MIN_SAMPLES or is_flat(float(y.min()), float(y.max())):
        return None
    if len(y) > LOMB_SCARGLE_MAX_POINTS:
        stride = int(np.ceil(len(y) / LOMB_SCARGLE_MAX_POINTS))
        t, y = t[::stride], y[::stride]
    if t[-1] <= t[0]:
        return None
    slope, intercept = np.polyfit(t, y, 1)
    return t, y - (slope * t + intercept)


def lomb_scargle_power(times_s: np.ndarray, values: np.ndarray, periods: np.ndarray) -> np.ndarray:
    """The generalised Lomb-Scargle periodogram at each period: the share of the variance a sinusoid explains.

    Zechmeister and Kürster's floating-mean form, with equal weights: at each
    frequency the sinusoid ``a × cos + b × sin + c`` is fitted by least squares to
    the readings at their own instants, and the power is one minus the
    residual variance over the total, so it lies in [0, 1]. Evaluated a few
    periods at a time, since each needs a cosine and a sine of every instant.
    """
    t = np.asarray(times_s, dtype=float)
    y = np.asarray(values, dtype=float)
    y = y - y.mean()
    yy = float(np.dot(y, y)) / len(y)
    omegas = 2.0 * np.pi / np.asarray(periods, dtype=float)
    power = np.zeros(len(omegas))
    if yy <= 0:
        return power
    for start in range(0, len(omegas), LOMB_SCARGLE_CHUNK):
        w = omegas[start : start + LOMB_SCARGLE_CHUNK, None]
        phase = w * t[None, :]
        c, s = np.cos(phase), np.sin(phase)
        cm, sm = c.mean(axis=1), s.mean(axis=1)
        yc = (c @ y) / len(y)
        ys = (s @ y) / len(y)
        cc = (c * c).mean(axis=1) - cm * cm
        ss = (s * s).mean(axis=1) - sm * sm
        cs = (c * s).mean(axis=1) - cm * sm
        det = cc * ss - cs * cs
        with np.errstate(divide="ignore", invalid="ignore"):
            p = (ss * yc * yc + cc * ys * ys - 2.0 * cs * yc * ys) / (yy * det)
        power[start : start + LOMB_SCARGLE_CHUNK] = np.where(np.isfinite(p), np.clip(p, 0, 1), 0)
    return power


def lomb_scargle(
    times_s: np.ndarray,
    prepared: np.ndarray,
    n_periods: int = LOMB_SCARGLE_PERIODS,
) -> Spectrum:
    """The spectrum of measurements at their own instants, against period, as a density.

    The periods run from twice the median interval between measurements (the
    shortest cycle they could resolve, the counterpart of the Nyquist period)
    up to the span of the stretch, equally spaced in log period. The
    periodogram's power is a share of the variance; it is scaled so that its
    integral over frequency is the variance of the readings, which is what a
    density's integral is, so the curve sits on the axis Welch's estimate of
    the same series would, and pools with it band by band.
    """
    t = np.asarray(times_s, dtype=float)
    y = np.asarray(prepared, dtype=float)
    span = float(t[-1] - t[0])
    shortest = max(2.0 * float(np.median(np.diff(t))), 2.0)
    if span <= shortest:
        span = shortest * 2.0
    periods = np.logspace(np.log10(shortest), np.log10(span), n_periods)
    power = lomb_scargle_power(t, y, periods)
    freqs = 1.0 / periods  # descending
    # The integral over frequency, by the trapezoid rule on the descending frequencies.
    area = float(np.sum(0.5 * (power[1:] + power[:-1]) * (freqs[:-1] - freqs[1:])))
    variance = float(y.var())
    density = power * (variance / area) if area > 0 else power
    return Spectrum(periods, density, round(span), 1, len(y), power)


# -- the distribution


def histogram(
    values: np.ndarray,
    groups: np.ndarray | None,
    bins: int,
    bounds: tuple[float, float] | None = None,
    edges: np.ndarray | None = None,
    keys: list | None = None,
) -> Histogram | None:
    """Counts of ``values`` per bin, stacked by the group each sample belongs to.

    ``groups`` is an array of integer codes, one per sample, naming a position
    in ``keys``, which names the stacks and fixes their order (a stack nothing
    falls in is left out); a negative code is a sample in no group. With
    ``groups`` ``None`` there is a single stack under the key ``None``.
    Readings outside ``bounds`` are left out and counted in ``left_out``;
    missing values are neither. ``edges`` fixes the bins (for several
    histograms on one axis); otherwise ``bins`` equal bins span the readings.
    ``None`` when nothing is left to count.
    """
    y = np.asarray(values, dtype=float)
    valid = ~np.isnan(y)
    left_out = 0
    if bounds is not None:
        outside = valid & ((y < bounds[0]) | (y > bounds[1]))
        left_out = int(outside.sum())
        valid &= ~outside
    if not valid.any():
        return None
    kept = y[valid]
    if edges is None:
        low, high = float(kept.min()), float(kept.max())
        if is_flat(low, high):
            center = 0.5 * (low + high)
            margin = max(abs(center) * 0.01, 0.5)
            low, high = center - margin, center + margin
        edges = np.linspace(low, high, bins + 1)
    result = Histogram(
        np.asarray(edges, dtype=float),
        {},
        left_out,
        float(kept.mean()),
        float(np.median(kept)),
    )
    if groups is None:
        result.stacks[None] = np.histogram(kept, bins=result.edges)[0]
        return result
    codes = np.asarray(groups, dtype=np.int64)[valid]
    if keys is None:
        raise ValueError("keys must name the groups when groups are given")
    for code, key in enumerate(keys):
        chosen = kept[codes == code]
        if len(chosen):
            result.stacks[key] = np.histogram(chosen, bins=result.edges)[0]
    return result


# -- reading the axes


def format_period(seconds: float) -> str:
    """``30 s``, ``5 min``, ``1.5 h``, ``2 d``: a period as a person would say it."""
    if not np.isfinite(seconds):
        return "-"
    if seconds < 60:
        return f"{seconds:.3g} s"
    if seconds < 3600:
        return f"{seconds / 60:.3g} min"
    if seconds < 86400:
        return f"{seconds / 3600:.3g} h"
    return f"{seconds / 86400:.3g} d"
