"""Tests of the algorithms: what is computed from the data, on synthetic series. No Qt involved."""

import numpy as np
import pytest

from overlap_viewer.algorithms.descriptors import (
    acf_half_time,
    autocorrelation,
    describe,
    gaussianity,
    normal_quantile,
    signal_to_noise,
)
from overlap_viewer.algorithms.interpolation import (
    GENUINE,
    HELD,
    INTERPOLATED,
    MISSING,
    describe_sampling,
    format_spacing,
    genuine_mask,
    sample_kinds,
    sampling_of,
)
from overlap_viewer.algorithms.spectral import (
    TransformParams,
    average_spectra,
    lomb_scargle,
    prepare,
    prepare_irregular,
    welch,
)

RNG = np.random.default_rng(7)


def historian(n: int, every: int, period_s: float = 600.0, jitter: float = 3e4):
    """A 1 Hz series as the PI historian hands it out: measurements every ``every`` seconds, straight lines between.

    The interpolation is done in single precision, as the dataset's evidently
    was, so consecutive differences agree to seven digits and not sixteen.
    The measurements carry an alternating offset on top of the sine, so that
    no two consecutive ramps share a slope and no ramp is flat: every
    measurement is then a breakpoint the test must find, none by luck.
    """
    t_meas = np.arange(0, n, every)
    signs = np.where(np.arange(len(t_meas)) % 2 == 0, 1.0, -1.0)
    v_meas = 1e7 + 1e5 * np.sin(2 * np.pi * t_meas / period_s) + jitter * signs
    grid = np.interp(np.arange(n), t_meas, v_meas).astype(np.float32).astype(float)
    return t_meas.astype(float), v_meas, grid


def test_a_straight_line_between_two_measurements_is_the_historian_and_not_the_process():
    """Every archived value is counted once; what lies on the lines between them is filled."""
    t_meas, _v_meas, grid = historian(3600, 10)
    kinds = sample_kinds(grid)
    sampling = sampling_of(kinds)
    assert sampling.n_valid == 3600
    assert sampling.n_genuine == len(t_meas)  # 360 measurements, not one more
    assert sampling.spacing_s == pytest.approx(10.0)
    assert sampling.n_filled == 3600 - 360
    assert sampling.genuine_share == pytest.approx(0.1)
    assert kinds[0] == GENUINE and kinds[10] == GENUINE and kinds[5] == INTERPOLATED
    # The mask is the same test.
    assert genuine_mask(grid).sum() == 360
    # A value carried forward is held, and its first sample is the measurement.
    held = grid.copy()
    held[100:130] = held[100]
    kinds = sample_kinds(held)
    assert kinds[100] == GENUINE and (kinds[101:130] == HELD).all()
    # Missing samples are neither, and do not break the test around them.
    holed = grid.copy()
    holed[200:205] = np.nan
    kinds = sample_kinds(holed)
    assert (kinds[200:205] == MISSING).all() and (kinds[210:220] == INTERPOLATED).sum() >= 8
    # Noise at every second is measured at every second.
    noisy = 1e7 + RNG.normal(0, 1e4, 3600)
    assert sampling_of(sample_kinds(noisy)).genuine_share > 0.99
    # A frozen sensor is one held run; a valve is exempt at the caller's level.
    frozen = sampling_of(sample_kinds(np.full(100, 118.5)))
    assert frozen.n_genuine == 1 and frozen.n_held == 99
    assert sampling_of(sample_kinds(np.array([np.nan, np.nan]))).n_valid == 0
    assert "measured 10%" in describe_sampling(sampling) and "one every 10 s" in describe_sampling(
        sampling
    )
    assert format_spacing(33) == "33 s" and format_spacing(150) == "2.5 min"
    assert format_spacing(7200) == "2.0 h" and format_spacing(np.nan) == "-"


def test_the_descriptors_are_what_the_thesis_defines():
    """Autocorrelation time, signal-to-noise ratio and Zhang's Gaussianity test, on series with known answers."""
    # An AR(1) with coefficient 0.9 has rho_k = 0.9^k, which is 0.5 at k = 6.58.
    x = np.zeros(100_000)
    e = RNG.normal(size=len(x))
    for i in range(1, len(x)):
        x[i] = 0.9 * x[i - 1] + e[i]
    assert acf_half_time(x) == pytest.approx(6.58, abs=0.4)
    assert acf_half_time(x, step_s=10.0) == pytest.approx(65.8, abs=4.0)
    rho = autocorrelation(x, 5)
    assert rho[0] == pytest.approx(1.0) and rho[1] == pytest.approx(0.9, abs=0.02)
    # A drift never halves its autocorrelation: infinite; a flat series has none.
    assert acf_half_time(np.linspace(0, 1, 5000), max_lag_s=100) == np.inf
    assert np.isnan(acf_half_time(np.ones(100)))
    # White noise is all noise: a ratio of one.
    white = RNG.normal(size=50_000)
    assert signal_to_noise(white) == pytest.approx(1.0, abs=0.05)
    # The Gaussian passes, the uniform and the bimodal fail, on the thesis's thresholds.
    slope, offset, scatter, verdict = gaussianity(RNG.normal(size=20_000))
    assert (
        verdict and slope == pytest.approx(1.0, abs=0.05) and abs(offset) < 0.02 and scatter < 0.1
    )
    assert not gaussianity(RNG.uniform(size=20_000))[3]
    assert not gaussianity(np.concatenate([RNG.normal(-3, 1, 10_000), RNG.normal(3, 1, 10_000)]))[3]
    # The normal quantile function, to the digits a table gives.
    assert normal_quantile(np.array([0.5, 0.975, 0.01])) == pytest.approx(
        [0.0, 1.959964, -2.326348], abs=1e-6
    )
    # The whole set at once, and the caveat itself: the historian's lines make the
    # grid look far less noisy and far more autocorrelated than the measurements.
    _t, v_meas, grid = historian(3600, 10)
    on_grid, on_meas = describe(grid), describe(v_meas, step_s=10.0)
    assert on_grid.n == 3600 and on_meas.n == 360
    assert on_grid.snr > 20 * on_meas.snr
    assert on_grid.acf_half_s > on_meas.acf_half_s * 0.9  # both see the 600 s cycle
    assert on_grid.mean == pytest.approx(on_meas.mean, rel=1e-3)
    assert on_grid.median == pytest.approx(np.median(grid))
    assert describe(np.array([np.nan, np.nan])).n == 0
    assert np.isnan(describe(np.full(50, 3.0)).skew)  # flat: moments only


def test_the_spectrum_of_the_measurements_needs_no_grid():
    """Lomb-Scargle over the instants of measurement finds the cycle Welch finds on the grid, in the same units."""
    t_meas, v_meas, grid = historian(3600, 10)
    prepared = prepare_irregular(t_meas, v_meas)
    assert prepared is not None
    spectrum = lomb_scargle(*prepared)
    assert spectrum.lomb_scargle and spectrum.n_points == 360 and spectrum.n_segments == 1
    period, share = spectrum.dominant()
    assert period == pytest.approx(600.0, rel=0.03)
    assert share > 0.5  # a sinusoid of the period explains most of the variance
    # The density integrates to the variance of the measurements, as Welch's roughly does to the grid's.
    freqs = 1.0 / spectrum.periods[::-1]
    area = float(
        np.sum(0.5 * (spectrum.power[::-1][1:] + spectrum.power[::-1][:-1]) * np.diff(freqs))
    )
    assert area == pytest.approx(prepared[1].var(), rel=1e-6)
    on_grid = welch(prepare(grid), TransformParams())
    assert on_grid.dominant()[0] == pytest.approx(600.0, rel=0.05)
    # Both read on one log-period axis: the pooled estimate keeps the peak.
    pooled = average_spectra([spectrum, on_grid])
    assert pooled is not None and pooled.dominant()[0] == pytest.approx(600.0, rel=0.1)
    assert pooled.n_points == 360
    # Too few measurements, or a flat series, decline; garbage is left out first.
    assert prepare_irregular(t_meas[:5], v_meas[:5]) is None
    assert prepare_irregular(t_meas, np.full(len(t_meas), 5.0)) is None
    spiked = v_meas.copy()
    spiked[3] = 9e12
    kept = prepare_irregular(t_meas, spiked, bounds=(0.0, 1e8))
    assert kept is not None and len(kept[0]) == len(t_meas) - 1
    # The parameter that asks for it.
    assert TransformParams(genuine=True).genuine and not TransformParams().genuine
