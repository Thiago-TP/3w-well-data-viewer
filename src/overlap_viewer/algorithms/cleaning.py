"""The 3W Toolkit's ``CleanSignals`` rule, applied to the figures the viewer already holds. Numpy only.

The Toolkit's preprocessing step ``CleanSignals`` (``ThreeWToolkit.preprocessing.
clean_signals``) decides, per event and per sensor, whether a signal is to be
believed. It is fitted on the dataset: for every sensor it takes the mean and
the standard deviation of the signal in every event, and puts bounds at the
quartiles of those figures plus or minus a multiple of the interquartile
range (three by default). In an event whose mean or whose standard deviation
falls outside the bounds, the sensor is discarded (set to missing): the
signal is frozen, or stuck at a level no other event shows. The lower bound
on the standard deviation is floored at an absolute 1e-6, so that a signal
that never moves is discarded whatever the others do. A sensor that is
entirely missing in 60 % or more of the events is dropped altogether, from
every event. The valve states (the ``ESTADO`` variables) are exempt.

The rule needs only the mean, the standard deviation and the emptiness of
every sensor in every event, which the profile pass provides for every
instance and for every bar of the joined view, so it costs nothing to apply
and its thresholds can be moved. One difference is kept on purpose: the
profiles describe the plausible readings, so a sensor whose readings are
instrument garbage is not discarded here by a mean of 1e42; it wears the
amber mark of an implausible reading instead, which says more.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field, replace

import numpy as np

from overlap_viewer.backend.dataset import DatasetInfo
from overlap_viewer.backend.profiles import Profiles

DEFAULT_IQR_FACTOR = 3.0
DEFAULT_STD_FLOOR = 1e-6
DEFAULT_MISSING_SHARE = 0.6


@dataclass(frozen=True)
class CleanRule:
    """The thresholds of the rule, as ``CleanSignalsConfig`` names them.

    ``iqr_factor`` multiplies the interquartile range on both sides of the
    quartiles, for the means and for the standard deviations alike (the
    Toolkit has one factor for each; the viewer moves them together);
    ``std_floor`` is the absolute floor of the lower bound on the standard
    deviation, ``None`` for no floor; ``missing_share`` is the share of the
    events a sensor must be entirely missing in to be dropped.
    """

    iqr_factor: float = DEFAULT_IQR_FACTOR
    std_floor: float | None = DEFAULT_STD_FLOOR
    missing_share: float = DEFAULT_MISSING_SHARE

    def describe(self) -> str:
        floor = f", spread floored at {self.std_floor:g}" if self.std_floor is not None else ""
        return (
            f"quartiles ± {self.iqr_factor:g} IQR of the means and of the spreads{floor}; a sensor "
            f"missing in ≥ {self.missing_share:.0%} of the events is dropped"
        )


@dataclass(frozen=True)
class Cleaning:
    """What the rule decides for a set of events.

    ``discarded`` is ``(events, sensors)``: the sensor is set to missing in
    that event; ``dropped`` is ``(sensors,)``: the column goes from every
    event; ``by_mean`` and ``by_std`` say which test discarded a cell (both
    can). ``mean_bounds`` and ``std_bounds`` are the fitted bounds per
    sensor, NaN for a sensor no event recorded; ``exempt`` marks the sensors
    the rule leaves alone. ``shown`` gives, per sensor, the unit ``why``
    states a bound in and the factor that converts it there (a pressure to
    MPa); empty, the bounds are stated as fitted, without a unit.
    """

    sensors: list[str]
    discarded: np.ndarray
    by_mean: np.ndarray
    by_std: np.ndarray
    dropped: np.ndarray
    missing_shares: np.ndarray
    mean_bounds: tuple[np.ndarray, np.ndarray]
    std_bounds: tuple[np.ndarray, np.ndarray]
    exempt: np.ndarray
    rule: CleanRule
    shown: tuple[tuple[str, float], ...] = ()

    @property
    def n_events(self) -> int:
        return self.discarded.shape[0]

    def discarded_sensors(self, event: int) -> list[str]:
        """The sensors the rule sets to missing in one event, in sensor order."""
        return [name for name, flag in zip(self.sensors, self.discarded[event]) if flag]

    def dropped_sensors(self) -> list[str]:
        return [name for name, flag in zip(self.sensors, self.dropped) if flag]

    def kept_share(self, event: int, live: np.ndarray) -> float:
        """Of the sensors live in one event and not exempt, the share the rule keeps; NaN with none."""
        live = np.asarray(live, dtype=bool) & ~self.exempt
        n = int(live.sum())
        if n == 0:
            return float("nan")
        kept = live & ~self.discarded[event] & ~self.dropped
        return float(kept.sum()) / n

    def why(self, event: int, sensor: int) -> str:
        """One clause saying which test discarded a cell, with the bound it failed."""
        unit, scale = self.shown[sensor] if self.shown else ("", 1.0)
        parts = []
        if self.by_mean[event, sensor]:
            lo, hi = self.mean_bounds[0][sensor] * scale, self.mean_bounds[1][sensor] * scale
            parts.append(f"mean outside {lo:.4g} to {hi:.4g} {unit}".rstrip())
        if self.by_std[event, sensor]:
            lo, hi = self.std_bounds[0][sensor] * scale, self.std_bounds[1][sensor] * scale
            parts.append(f"spread outside {lo:.4g} to {hi:.4g} {unit}".rstrip())
        return " and ".join(parts)


def clean_signals(
    means: np.ndarray,
    stds: np.ndarray,
    missing: np.ndarray,
    sensors: Sequence[str],
    exempt: Sequence[str] = (),
    rule: CleanRule | None = None,
) -> Cleaning:
    """Fit the Toolkit's rule on a set of events and apply it to every one of them.

    ``means`` and ``stds`` are ``(events, sensors)``, NaN where the sensor
    has no readings in the event; ``missing`` is ``(events, sensors)``,
    ``True`` where the sensor is entirely missing there. The quartiles are
    taken over the events that have the sensor, as pandas does.
    """
    rule = rule or CleanRule()
    means = np.asarray(means, dtype=float)
    stds = np.asarray(stds, dtype=float)
    missing = np.asarray(missing, dtype=bool)
    sensors = list(sensors)
    n, s = means.shape
    exempt_mask = np.array([name in set(exempt) for name in sensors], dtype=bool)
    lo_m = np.full(s, np.nan)
    hi_m = np.full(s, np.nan)
    lo_s = np.full(s, np.nan)
    hi_s = np.full(s, np.nan)
    for j in range(s):
        m = means[:, j]
        d = stds[:, j]
        if np.isfinite(m).any():
            q1, q3 = np.nanquantile(m, [0.25, 0.75])
            iqr = q3 - q1
            lo_m[j], hi_m[j] = q1 - rule.iqr_factor * iqr, q3 + rule.iqr_factor * iqr
        if np.isfinite(d).any():
            q1, q3 = np.nanquantile(d, [0.25, 0.75])
            iqr = q3 - q1
            lo_s[j] = q1 - rule.iqr_factor * iqr
            if rule.std_floor is not None:
                lo_s[j] = max(lo_s[j], rule.std_floor)
            hi_s[j] = q3 + rule.iqr_factor * iqr
    with np.errstate(invalid="ignore"):
        by_mean = (means < lo_m) | (means > hi_m)
        by_std = (stds < lo_s) | (stds > hi_s)
    by_mean &= ~exempt_mask
    by_std &= ~exempt_mask
    discarded = by_mean | by_std
    shares = missing.mean(axis=0) if n else np.zeros(s)
    dropped = (shares >= rule.missing_share) & ~exempt_mask
    return Cleaning(
        sensors,
        discarded,
        by_mean,
        by_std,
        dropped,
        shares,
        (lo_m, hi_m),
        (lo_s, hi_s),
        exempt_mask,
        rule,
    )


@dataclass
class Cleaned:
    """The rule applied to the instances, or to the bars of the joined view, and looked up by key.

    ``keys`` name the events as the profile table does (``(fault_class,
    file)`` or ``(well, bar)``) and ``live`` is ``(events, sensors)``: where
    the sensor has readings that move, which is what ``kept_share`` counts
    over.
    """

    cleaning: Cleaning
    keys: list
    joined: bool
    live: np.ndarray
    _index: dict = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        self._index = {key: i for i, key in enumerate(self.keys)}

    def event(self, key) -> int | None:
        return self._index.get(key)

    def discarded(self, key) -> list[str]:
        """The sensors the rule sets to missing in one event; empty when the key is unknown."""
        i = self.event(key)
        return [] if i is None else self.cleaning.discarded_sensors(i)

    def kept_share(self, key) -> float:
        i = self.event(key)
        return float("nan") if i is None else self.cleaning.kept_share(i, self.live[i])

    def why(self, key, sensor: str) -> str:
        i = self.event(key)
        if i is None or sensor not in self.cleaning.sensors:
            return ""
        return self.cleaning.why(i, self.cleaning.sensors.index(sensor))

    def describe(self, key) -> str:
        """One clause per event: what the rule would discard there, and why."""
        i = self.event(key)
        if i is None:
            return "not among the events the rule was fitted on"
        names = self.cleaning.discarded_sensors(i)
        if not names:
            return "CleanSignals keeps every sensor here"
        reasons = ", ".join(
            f"{name} ({self.cleaning.why(i, self.cleaning.sensors.index(name))})" for name in names
        )
        return f"CleanSignals would discard {reasons}"


def clean_profiles(
    profiles: Profiles,
    keys: Sequence,
    joined: bool,
    info: DatasetInfo,
    rule: CleanRule | None = None,
) -> Cleaned:
    """Fit and apply the rule to the events ``keys`` name, from their profiles.

    The events are the instances (``(fault_class, file)`` keys) or the bars
    of the joined view (``(well, bar)`` keys); the enumerated variables are
    exempt, as the Toolkit exempts them.
    """
    keys = list(keys)
    sensors = list(profiles.sensors)
    means = profiles.matrix(keys, joined, "mean", sensors)
    stds = profiles.matrix(keys, joined, "std", sensors)
    n_valid = np.nan_to_num(profiles.matrix(keys, joined, "n_valid", sensors))
    missing = n_valid <= 0
    # A sensor with no plausible reading has no mean to judge: the rule does
    # not see it, as the Toolkit does not see an all-missing column.
    means = np.where(missing, np.nan, means)
    stds = np.where(missing, np.nan, stds)
    live = (n_valid > 0) & (np.nan_to_num(stds) > 0)
    exempt = [name for name in sensors if info.is_enumerated(name)]
    cleaning = replace(
        clean_signals(means, stds, missing, sensors, exempt, rule),
        shown=tuple((info.shown_unit(name), info.shown_scale(name)) for name in sensors),
    )
    return Cleaned(cleaning, keys, joined, live)
