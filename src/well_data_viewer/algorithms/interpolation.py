"""Which samples of a 3W series are measurements, and which the historian drew. Numpy only.

The dataset is sampled once a second, but the sensors were not read once a
second. Melo (doctoral thesis, section 4.2.5) shows it on the normal instances
of the first well: the readings sit on straight lines between a few extremes,
the plant's Osisoft PI historian having interpolated linearly between the
values it archived, and the scatter plot of two such series shows trajectories
that are nothing but the ups and downs of the two interpolations. He tried to
recover the instants of measurement with a peak finder, found the rate
irregular and different from sensor to sensor, and left it there. This module
takes the direct route: a straight line is a run of samples whose first
difference is constant.

Three kinds of sample come out of it. A **genuine** sample is where the
historian had an archived value: the ends of every straight stretch, and the
first sample of every stretch that holds one value. An **interpolated** sample
sits strictly inside a straight stretch with a non-zero slope, and carries no
information the two ends do not. A **held** sample repeats the sample before
it: a value the historian carried forward until the next archived one (or a
sensor that reported the same number again, which no test can tell apart).
Held and interpolated together are the **filled** samples.

The test is run on the values, not on the timestamps, and works at any
sampling step. A tolerance is needed: on 3W 2.0.0 the interpolation was
evidently done in single precision and stored in double, so the first
differences of a ramp agree to about seven digits and not to sixteen. The
tolerance is relative to the largest reading of the series, which is far
below the quantum of any sensor here and far above that rounding.

What the test cannot decide, it counts as filled: a quantized sensor climbing
one step a second draws the very same line an interpolation does. A sensor
that never moves is one held run, and shows as frozen elsewhere in the viewer.
"""

from dataclasses import dataclass

import numpy as np

# The kinds of sample, as ``sample_kinds`` codes them.
MISSING, GENUINE, INTERPOLATED, HELD = -1, 0, 1, 2

# How closely two consecutive first differences must agree, as a share of the
# largest reading, for the sample between them to lie on a straight line.
# Single-precision rounding is 6e-8 of the value; the quantum of the coarsest
# sensor is far above 1e-6 of its level.
RELATIVE_TOLERANCE = 1e-6


def sample_kinds(values: np.ndarray, rel_tol: float = RELATIVE_TOLERANCE) -> np.ndarray:
    """Code every sample as ``GENUINE``, ``INTERPOLATED``, ``HELD`` or ``MISSING``.

    A sample is held when it equals the one before it; interpolated when it
    is neither held nor missing and the difference to the sample before
    equals the difference to the sample after (within the tolerance), the
    slope being non-zero; genuine otherwise. The first sample of a held run
    is genuine, so every archived value is counted once; the ends of a ramp
    are genuine for the same reason.
    """
    y = np.asarray(values, dtype=float)
    n = len(y)
    kinds = np.full(n, MISSING, dtype=np.int8)
    valid = ~np.isnan(y)
    kinds[valid] = GENUINE
    if n < 2 or valid.sum() < 2:
        return kinds
    scale = float(np.max(np.abs(y[valid])))
    tol = rel_tol * max(scale, 1e-12)
    d = np.diff(y)  # NaN wherever either neighbour is missing
    with np.errstate(invalid="ignore"):
        repeats = np.abs(d) <= tol  # sample i+1 equals sample i
        kinds[1:][repeats] = HELD
        if n >= 3:
            straight = np.abs(d[1:] - d[:-1]) <= tol  # i+1 is collinear with i and i+2
            sloped = ~repeats[:-1] & ~repeats[1:]
            inside = straight & sloped
            kinds[1:-1][inside] = INTERPOLATED
    return kinds


def genuine_mask(values: np.ndarray, rel_tol: float = RELATIVE_TOLERANCE) -> np.ndarray:
    """``True`` for every sample that is a measurement rather than a filled one."""
    return sample_kinds(values, rel_tol) == GENUINE


@dataclass(frozen=True)
class Sampling:
    """How one series was measured, as far as its values say.

    Attributes
    ----------
    n_valid : int
        Samples carrying a reading.
    n_genuine, n_interpolated, n_held : int
        Samples of each kind; they add up to ``n_valid``.
    spacing_s : float
        Mean interval between two measurements, in seconds: the span from the
        first genuine sample to the last, over the intervals between them. NaN
        with fewer than two.
    """

    n_valid: int
    n_genuine: int
    n_interpolated: int
    n_held: int
    spacing_s: float

    @property
    def n_filled(self) -> int:
        """Samples the historian filled in: interpolated or held."""
        return self.n_interpolated + self.n_held

    @property
    def genuine_share(self) -> float:
        """Share of the readings that are measurements, zero with no readings."""
        return self.n_genuine / self.n_valid if self.n_valid else 0.0

    @property
    def filled_share(self) -> float:
        return self.n_filled / self.n_valid if self.n_valid else 0.0


EMPTY_SAMPLING = Sampling(0, 0, 0, 0, np.nan)


def sampling_of(kinds: np.ndarray, step_s: float = 1.0) -> Sampling:
    """Count the kinds of one series and measure the spacing of its measurements.

    ``kinds`` is what ``sample_kinds`` returned; ``step_s`` is the sampling
    step of the series, one second for a 3W file.
    """
    kinds = np.asarray(kinds)
    genuine = np.flatnonzero(kinds == GENUINE)
    n_genuine = len(genuine)
    spacing = (
        float(genuine[-1] - genuine[0]) * step_s / (n_genuine - 1) if n_genuine > 1 else np.nan
    )
    return Sampling(
        int((kinds != MISSING).sum()),
        n_genuine,
        int((kinds == INTERPOLATED).sum()),
        int((kinds == HELD).sum()),
        spacing,
    )


def describe_sampling(sampling: Sampling) -> str:
    """One clause about how a series was measured, for a status bar or a caption.

    ``measured 12 % (one every 33 s), interpolated 80 %, held 8 %``, the
    parts that are zero left out.
    """
    if sampling.n_valid == 0:
        return "no readings"
    parts = [f"measured {sampling.genuine_share:.0%}"]
    if np.isfinite(sampling.spacing_s):
        parts[0] += f" (one every {format_spacing(sampling.spacing_s)})"
    if sampling.n_interpolated:
        parts.append(f"interpolated {sampling.n_interpolated / sampling.n_valid:.0%}")
    if sampling.n_held:
        parts.append(f"held {sampling.n_held / sampling.n_valid:.0%}")
    return ", ".join(parts)


def format_spacing(seconds: float) -> str:
    """``1 s``, ``33 s``, ``2.5 min``, ``1.2 h``: the interval between two measurements."""
    if not np.isfinite(seconds):
        return "-"
    if seconds < 90:
        return f"{seconds:.0f} s" if seconds >= 9.5 else f"{seconds:.1f} s"
    if seconds < 5400:
        return f"{seconds / 60:.1f} min"
    return f"{seconds / 3600:.1f} h"
