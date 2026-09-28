"""The passes over the data, loaded once and shared by every page.

Three questions about the instances cannot be answered from the footers of
the files and take a pass over the data each: what the merged recordings of
the joined view hold, sensor by sensor and pair by pair; which sensors carry
a reading at the same instant, instance by instance; and how every sensor of
every instance and bar was measured and what it amounts to (its profile).
Each pass is cached on disk by the backend and shown behind a cancellable
progress dialog by ``loading``; this object keeps the results in memory for
the length of a catalogue, so that a page asking for a pass another page has
already paid for gets it at once, and a page whose user cancels gets ``None``
and falls back.
"""

import contextlib
from dataclasses import dataclass, field

import numpy as np
from PySide6.QtWidgets import QWidget

from overlap_viewer.algorithms.cleaning import Cleaned, CleanRule, clean_profiles
from overlap_viewer.backend.dataset import (
    DatasetInfo,
    JoinedStats,
    PairCounts,
    ScanCancelled,
    WellData,
)
from overlap_viewer.backend.labels import Segment, segments_from_json
from overlap_viewer.backend.model_outputs import Agreement, ModelOutputs
from overlap_viewer.backend.profiles import Profiles, load_profiles
from overlap_viewer.frontend.loading import (
    FrameCache,
    joined_stats_with_progress,
    pair_counts_with_progress,
    profiles_with_progress,
)


@dataclass
class ModelResults:
    """A set of model outputs, with its agreement with the labels of every instance it scored.

    ``agreements`` is keyed by ``(fault_class, file)``; an instance the model
    did not score has no entry.
    """

    outputs: ModelOutputs
    agreements: dict[tuple[int, str], Agreement] = field(default_factory=dict)

    @property
    def name(self) -> str:
        return self.outputs.spec.name

    def agreement(self, fault_class: int, file: str) -> float:
        """The share of the compared time the model agrees with the labels of one instance, NaN when unscored."""
        entry = self.agreements.get((int(fault_class), str(file)))
        return float("nan") if entry is None else entry.share

    def agreement_of_members(self, keys) -> float:
        """The agreement over several instances at once, weighted by the time compared in each."""
        compared = agreed = 0.0
        for key in keys:
            entry = self.agreements.get(key)
            if entry is not None:
                compared += entry.compared_s
                agreed += entry.agreed_s
        return agreed / compared if compared > 0 else float("nan")

    def class_runs(self, fault_class: int, file: str, offset: int) -> list[Segment]:
        """The model's verdicts on one instance as label runs in the dataset's own vocabulary.

        A detection model's *anomalous* becomes the steady label of the
        instance's own fault (its class number), its *normal* the label 0, so
        that the runs can shade a plot exactly as the experts' labels do; a
        classification model's labels are class numbers already.
        """
        runs = self.outputs.runs(fault_class, file)
        if self.outputs.spec.kind == "detection":
            fault = int(fault_class)
            return [
                Segment(run.start, run.end, float(fault if run.value else 0))
                for run in runs
                if not np.isnan(run.value)
            ]
        return [
            Segment(run.start, run.end, float(run.value)) for run in runs if not np.isnan(run.value)
        ]

    def describe(self, fault_class: int, file: str) -> str:
        entry = self.agreements.get((int(fault_class), str(file)))
        if entry is None:
            return f"not scored by {self.name}"
        if entry.compared_s <= 0:
            return f"scored by {self.name}, but over no labeled stretch"
        return (
            f"{self.name}: agrees with the labels {entry.share:.0%} of the compared time "
            f"({entry.compared_s / 3600:.1f} h compared, {entry.scored_s / 3600:.1f} h scored)"
        )


class Passes:
    """What has been read from the data so far, for the catalogue in force.

    ``frames`` is the cache of loaded instances every window reads from. The
    three ``*`` methods return what the pass found, reading the data behind a
    dialog the first time, or ``None`` when the user cancelled that reading;
    each is keyed by the sensors it was asked for, since the pair counts and
    the profiles are laid out in that order.
    """

    def __init__(self, info: DatasetInfo, frames: FrameCache | None = None):
        self.info = info
        self.frames = frames or FrameCache()
        self._wells: list[WellData] = []
        self._joined: dict[tuple[str, ...], JoinedStats] = {}
        self._pairs: dict[tuple[str, ...], PairCounts] = {}
        self._profiles: dict[tuple[str, ...], Profiles] = {}
        # The sensor lists whose cache was looked for and not found, until the catalogue changes.
        self._uncached: set[tuple[str, ...]] = set()
        self._cleaned: dict[tuple, Cleaned] = {}
        self.model: ModelResults | None = None

    def set_wells(self, wells: list[WellData]) -> None:
        """A new catalogue: what was read describes the old one and is dropped.

        A loaded set of model outputs stays, its agreements computed again
        against the new catalogue.
        """
        self._wells = list(wells)
        self._joined.clear()
        self._pairs.clear()
        self._profiles.clear()
        self._uncached.clear()
        self._cleaned.clear()
        if self.model is not None:
            self.set_model_outputs(self.model.outputs)

    def set_model_outputs(self, outputs: ModelOutputs | None) -> ModelResults | None:
        """Take a set of model outputs (or none), and measure its agreement with every instance's labels."""
        if outputs is None:
            self.model = None
            return None
        agreements = {}
        offset = self.info.transient_offset
        for well in self._wells:
            rows = well.rows
            for i in range(len(rows)):
                fault_class, file = int(rows["fault_class"].iloc[i]), str(rows["file"].iloc[i])
                if not outputs.has(fault_class, file):
                    continue
                runs = (
                    segments_from_json(str(rows["class_runs"].iloc[i]))
                    if "class_runs" in rows.columns
                    else []
                )
                entry = outputs.agreement(fault_class, file, runs, offset)
                if entry is not None:
                    agreements[(fault_class, file)] = entry
        self.model = ModelResults(outputs, agreements)
        return self.model

    @property
    def wells(self) -> list[WellData]:
        return self._wells

    def joined_stats(self, sensors: list[str], parent: QWidget | None = None) -> JoinedStats | None:
        """The merged figures of every bar of the joined view, or ``None`` if cancelled."""
        key = tuple(sensors)
        if key not in self._joined:
            try:
                self._joined[key] = joined_stats_with_progress(
                    self.info, self._wells, list(sensors), parent=parent
                )
            except ScanCancelled:
                return None
        return self._joined[key]

    def pair_counts(self, sensors: list[str], parent: QWidget | None = None) -> PairCounts | None:
        """The co-valid sample counts of every pair of sensors, per instance, or ``None`` if cancelled."""
        key = tuple(sensors)
        if key not in self._pairs:
            try:
                self._pairs[key] = pair_counts_with_progress(
                    self.info, list(sensors), parent=parent
                )
            except ScanCancelled:
                return None
        return self._pairs[key]

    def profiles(self, sensors: list[str], parent: QWidget | None = None) -> Profiles | None:
        """The profile of every sensor of every instance and bar, or ``None`` if cancelled."""
        key = tuple(sensors)
        if key not in self._profiles:
            try:
                self._profiles[key] = profiles_with_progress(
                    self.info, self._wells, list(sensors), parent=parent
                )
            except ScanCancelled:
                return None
        return self._profiles[key]

    def profiles_if_loaded(self, sensors: list[str]) -> Profiles | None:
        """The profiles, only if they have already been paid for: never reads the data.

        Paid for in this session by a page, or in an earlier one, whose pass
        left a cache still valid for the files as they are; that cache is read
        once and kept, which is what puts the marks of pressures out of order
        on the pages as soon as the pass has ever run.
        """
        key = tuple(sensors)
        if key not in self._profiles and key not in self._uncached and self._wells:
            self._uncached.add(key)
            with contextlib.suppress(Exception):
                cached = load_profiles(self.info, self._wells, list(sensors), cache_only=True)
                if cached is not None:
                    self._profiles[key] = cached
        return self._profiles.get(key)

    def event_keys(self, joined: bool) -> list:
        """Every instance as ``(fault_class, file)``, or every bar of the joined view as ``(well, bar)``."""
        keys = []
        for well in self._wells:
            if joined:
                keys += [(well.well, bar) for bar in range(well.joined().n_instances)]
            else:
                rows = well.rows
                keys += [
                    (int(rows["fault_class"].iloc[i]), str(rows["file"].iloc[i]))
                    for i in range(len(rows))
                ]
        return keys

    def cleaning(
        self, joined: bool, rule: CleanRule | None = None, parent: QWidget | None = None
    ) -> Cleaned | None:
        """The Toolkit's CleanSignals rule over the instances, or the joined bars; ``None`` if cancelled.

        Fitted on the profiles, so the first call reads the data if no page
        has yet; every later call with the same thresholds is a lookup.
        """
        rule = rule or CleanRule()
        key = (joined, rule)
        if key not in self._cleaned:
            profiles = self.profiles(self.info.sensor_names, parent=parent)
            if profiles is None:
                return None
            self._cleaned[key] = clean_profiles(
                profiles, self.event_keys(joined), joined, self.info, rule
            )
        return self._cleaned[key]

    def cleaning_if_loaded(self, joined: bool, rule: CleanRule | None = None) -> Cleaned | None:
        """The rule's verdicts, only if the profiles are already on hand: never reads the data."""
        rule = rule or CleanRule()
        key = (joined, rule)
        if key not in self._cleaned:
            profiles = self.profiles_if_loaded(self.info.sensor_names)
            if profiles is None:
                return None
            self._cleaned[key] = clean_profiles(
                profiles, self.event_keys(joined), joined, self.info, rule
            )
        return self._cleaned[key]
