"""Constants of the viewer: dataset conventions, the color ladder, layout, cache location.

Everything the dataset itself can state (event names and labels, variable
units, the transient offset) is read from the 3W ``dataset.ini`` at run time
(see ``dataset.DatasetInfo``); the values here are the fallbacks used when the
file is missing, plus everything that is a choice of this viewer rather than a
property of the data.
"""

import os
from pathlib import Path

# -- Dataset conventions (fallbacks for a dataset without ``dataset.ini``) -----

# Event descriptions of 3W 2.0.0, keyed by the label of the fault-class folder.
DEFAULT_FAULT_NAMES: dict[int, str] = {
    0: "Normal Operation",
    1: "Abrupt Increase of BSW",
    2: "Spurious Closure of DHSV",
    3: "Severe Slugging",
    4: "Flow Instability",
    5: "Rapid Productivity Loss",
    6: "Quick Restriction in PCK",
    7: "Scaling in PCK",
    8: "Hydrate in Production Line",
    9: "Hydrate in Service Line",
}

# A transient label is the fault label plus this offset (``[EVENTS]`` section).
DEFAULT_TRANSIENT_OFFSET = 100

# The events that have a transient period at all (``TRANSIENT`` in the event
# sections of the ini file): Severe Slugging and Flow Instability are labeled in
# their steady state from the first sample, and normal operation installs nothing.
DEFAULT_TRANSIENT_CAPABLE = frozenset({1, 2, 5, 6, 7, 8, 9})

# Variables an instance file may carry, in dataset order, with their units.
DEFAULT_SENSOR_UNITS: dict[str, str] = {
    "ABER-CKGL": "%",
    "ABER-CKP": "%",
    "ESTADO-DHSV": "-",
    "ESTADO-M1": "-",
    "ESTADO-M2": "-",
    "ESTADO-PXO": "-",
    "ESTADO-SDV-GL": "-",
    "ESTADO-SDV-P": "-",
    "ESTADO-W1": "-",
    "ESTADO-W2": "-",
    "ESTADO-XO": "-",
    "P-ANULAR": "Pa",
    "P-JUS-BS": "Pa",
    "P-JUS-CKGL": "Pa",
    "P-JUS-CKP": "Pa",
    "P-MON-CKGL": "Pa",
    "P-MON-CKP": "Pa",
    "P-MON-SDV-P": "Pa",
    "P-PDG": "Pa",
    "PT-P": "Pa",
    "P-TPT": "Pa",
    "QBS": "m³/s",
    "QGL": "m³/s",
    "T-JUS-CKP": "°C",
    "T-MON-CKP": "°C",
    "T-PDG": "°C",
    "T-TPT": "°C",
}

# Well operational status codes of the ``state`` column (Table 5 of the 3W
# Dataset 2.0.0 paper); the ini file does not list them.
WELL_STATES: dict[int, str] = {
    0: "Open",
    1: "Shut-In",
    2: "Flushing Diesel",
    3: "Flushing Gas",
    4: "Bullheading",
    5: "Closed With Diesel",
    6: "Closed With Gas",
    7: "Restart",
    8: "Depressurization",
}

# The two label columns of an instance; every other column is a sensor.
LABEL_COLUMNS = ("class", "state")

# Variables that carry the visual signature of an event, i.e. the ones whose
# joint behavior an expert reads to recognize it. They are documentation, which
# the help shows beside each event: they no longer choose what a page plots,
# since the sets are not agreed on and would steer an analysis toward them (the
# placements below do that instead, leaving the choice to the user). Each entry reproduces the
# variable set of the corresponding example figure of the 3W Dataset 2.0.0
# paper (https://doi.org/10.1038/s41597-026-07225-z), which is why only the
# events illustrated there (figures 3 to 7) have a signature: the remaining
# ones have no published reference set to copy.
FAULT_SIGNATURES: dict[int, tuple[str, ...]] = {
    0: ("ABER-CKP", "ESTADO-SDV-P", "ESTADO-W1", "T-TPT"),  # figure 7
    2: ("P-MON-CKP", "P-PDG", "P-TPT", "T-TPT"),  # figure 3
    3: ("P-MON-CKP", "P-PDG", "P-TPT", "T-JUS-CKP"),  # figure 6
    6: ("ABER-CKP", "P-MON-CKP", "P-PDG", "P-TPT"),  # figure 4
    8: ("P-MON-CKP", "P-PDG", "P-TPT", "T-TPT"),  # figure 5
}

# Where the paper publishes no figure, Vargas's thesis works through one
# instance of the event and names the variables it moves; those are offered
# as a best effort, in the same convention of four, read off the text of the
# section rather than copied from a figure, and marked as such wherever they
# are offered. Flow Instability is described as "the same variables as severe
# slugging". Scaling in PCK moves the same variables as a quick restriction of
# the same valve, but nothing steps the choke opening, so the opening is left
# out and the temperature downstream of the choke, which the text names, comes
# in. Hydrate in Service Line has no worked instance at all, and its own
# instruments (P-JUS-BS, QBS) are never recorded in the real instances of
# 3W 2.0.0, so the production-line hydrate's set stands in for it.
BEST_EFFORT_SIGNATURES: dict[int, tuple[str, ...]] = {
    1: ("P-MON-CKP", "P-TPT", "T-JUS-CKP", "T-TPT"),  # thesis, section 2.3.1 and figure 3
    4: ("P-MON-CKP", "P-PDG", "P-TPT", "T-JUS-CKP"),  # thesis, section 2.3.4
    5: ("P-MON-CKP", "P-TPT", "T-JUS-CKP", "T-TPT"),  # thesis, section 2.3.5 and figure 7
    7: ("P-MON-CKP", "P-TPT", "T-JUS-CKP", "T-TPT"),  # thesis, section 2.3.7 and figure 9
    9: ("P-MON-CKP", "P-PDG", "P-TPT", "T-TPT"),  # no source; the production-line set
}

# Where each best effort comes from, for the help and the tooltips to say.
BEST_EFFORT_SOURCES: dict[int, str] = {
    1: "the instance the thesis works through (section 2.3.1, figure 3)",
    4: "the thesis, which describes the event as moving the same variables as severe slugging "
    "(section 2.3.4)",
    5: "the instance the thesis works through (section 2.3.5, figure 7)",
    7: "the instance the thesis works through (section 2.3.7, figure 9)",
    9: "no source: the event has no published example, and the service line's own instruments "
    "(P-JUS-BS, QBS) are never recorded in the real instances of 3W 2.0.0, so the set of the "
    "production-line hydrate stands in",
}


# -- Placement of the sensors ------------------------------------------------------

# Where each variable is measured, in three placements: above water on the
# platform (the production choke and shutdown valve, the gas-lift and service
# lines), at the christmas tree on the seabed, and in the well below it. From
# table 2 and figure 1 of the 2.0.0 article, as the help's variable pages give
# them. The feature panels offer one box per placement, so that which part of
# the production system to look at is the user's choice rather than a
# per-fault set.
TOPSIDE, SEABED, SUBSURFACE = "Topside", "Seabed", "Subsurface"
PLACEMENTS: dict[str, tuple[str, ...]] = {
    TOPSIDE: (
        "ABER-CKGL",
        "ABER-CKP",
        "ESTADO-SDV-GL",
        "ESTADO-SDV-P",
        "P-JUS-BS",
        "P-JUS-CKGL",
        "P-JUS-CKP",
        "P-MON-CKGL",
        "P-MON-CKP",
        "P-MON-SDV-P",
        "QBS",
        "QGL",
        "T-JUS-CKP",
        "T-MON-CKP",
    ),
    SEABED: (
        "ESTADO-M1",
        "ESTADO-M2",
        "ESTADO-PXO",
        "ESTADO-W1",
        "ESTADO-W2",
        "ESTADO-XO",
        "P-ANULAR",
        "PT-P",
        "P-TPT",
        "T-TPT",
    ),
    SUBSURFACE: ("ESTADO-DHSV", "P-PDG", "T-PDG"),
}
PLACEMENT_NOTES: dict[str, str] = {
    TOPSIDE: (
        "on the production platform, above water (the production choke and shutdown valve, "
        "the gas-lift and the service lines)"
    ),
    SEABED: "at the subsea christmas tree (its valves, its transducer and the annulus)",
    SUBSURFACE: "in the well, below the seabed (the downhole gauge and safety valve)",
}

# What an instance window and the Faults page open on: the analog sensors of
# the seabed placement (the tree's valve states would add six step plots). The
# tree transducer is the reading the thesis counts as reliable and nearly every
# real instance carries, and the choice is the same for every fault.
DEFAULT_FEATURES = ("P-ANULAR", "P-TPT", "T-TPT")


def placement_of(sensor: str) -> str | None:
    """The placement a variable is measured in, ``None`` for one the viewer does not know."""
    return next((place for place, names in PLACEMENTS.items() if sensor in names), None)


# Filename prefix of the instances recorded on a physical well. Simulated and
# hand-drawn instances have no well to overlap on and are ignored.
REAL_PREFIX = "WELL-"

# -- Plausible readings -----------------------------------------------------------

# What a reading must satisfy to be a measurement rather than instrument
# garbage, by physical quantity, which the viewer tells from the unit the
# dataset declares for the variable. The limits below come from a survey of
# every instance of 3W 2.0.0:
#
# - Magnitude. Some sensors are frozen at absurd levels (one well reports
#   P-PDG = -1.2e42 Pa for whole instances) or off by orders of magnitude
#   (P-JUS-CKP around 1.4e9 Pa, i.e. 14,000 bar). The survey found a clean gap
#   around 1e8: the largest varying reading below it is 4.9e7 Pa and the
#   smallest value above it 1.3e8, so the limit removes no real signal, which
#   matters because genuine spikes are fault signatures.
# - Sign. Pressures are absolute and choke openings are percentages, so a
#   negative reading of either is impossible; 106 files carry a negative
#   pressure, usually for the whole recording, and one well a choke opening of
#   -99.99 %, a sentinel. Zero is left alone: frozen at zero is another defect.
#   A percentage has a ceiling too, so an opening is capped at 100.
# - Temperature band. The floor is below every genuine reading (T-TPT reaches
#   -33.8 °C during a blowdown, which is real) and the ceiling twice the hottest
#   one (127.7 °C); the band catches the sentinels -999 and -99.99 and T-PDG
#   readings of 30,000 °C.
# - Flow rates. A rate is a magnitude, so a negative one is impossible, and no
#   real instance records one: QGL, the only flow rate recorded, reads 0 to
#   4.31 m³/s (the simulated instances do go below zero). Zero is left alone,
#   the gas lift being closed. The ceiling is the largest reading, about
#   doubled and rounded up as for temperature: 10 m³/s, 864,000 m³/d. It also
#   holds QBS, a liquid rate that no real instance records.
#
# Everything else, the valve states, is held to the magnitude rule only.
EXTREME_VALUE_LIMIT = 1e8
PLAUSIBLE_RANGES: dict[str, tuple[float, float]] = {
    "Pa": (0.0, EXTREME_VALUE_LIMIT),
    "°C": (-50.0, 250.0),
    "%": (0.0, 100.0),
    "m³/s": (0.0, 10.0),
}
PLAUSIBLE_RANGE_DEFAULT = (-EXTREME_VALUE_LIMIT, EXTREME_VALUE_LIMIT)


def plausible_range(unit: str) -> tuple[float, float]:
    """The readings a variable measured in ``unit`` may take and still be measurements."""
    return PLAUSIBLE_RANGES.get(unit, PLAUSIBLE_RANGE_DEFAULT)


# -- Order of the pressures along a line --------------------------------------------

# Fluid flows from high pressure to low, so along one line the pressures upstream
# must read above those downstream. A survey of every real instance of 3W 2.0.0,
# comparing each pair of pressures sample by sample, found which pairs obey it:
#
# - Production line, upstream to downstream: the downhole gauge, the tree, then
#   the platform either side of the production choke. P-TPT reads above
#   P-MON-CKP in all but 6 of 585 instances (median gap 8.9 MPa), P-PDG above
#   P-TPT in all but 23 of 159. Where a sensor is missing, its neighbours are
#   compared (P-PDG above P-MON-CKP holds in all 157 instances that have both).
# - Service line, which carries the gas lift down from the platform to the
#   annulus: upstream of the gas-lift choke above downstream of it, and the
#   annulus above the line at the platform, since the gas gains the weight of
#   its own column on the way down.
# - A closed valve cuts a line in two, and the two ends may then read anything.
#   Across a choke the order is only asked while it is open: a closed gas-lift
#   choke leaves its header bled down to 3.6 MPa under a line held at 17 MPa
#   (WELL-00029). The annulus is compared with the service line only while the
#   annulus master and wing valves are not closed: with the wing valve shut the
#   annulus of WELL-00005 reads 0.3 to 1 MPa below the line, that of WELL-00022
#   10 MPa. A valve or choke whose state is not recorded counts as open.
#
# Not asked, because the survey says they do not hold: the tree against the
# gas-lift choke (with gas flowing, P-JUS-CKGL reads above P-TPT in 87 of 110
# instances, by a median of 5.5 MPa, since the gas has to enter the tubing far
# below the tree), and the annulus against the tubing (P-ANULAR against P-TPT
# or P-PDG goes either way).
#
# A pair is out of order where the downstream reading exceeds the upstream one
# by more than the tolerance, in more than the given share of the samples in
# which both are compared. Below 1 MPa the survey finds only readings about
# equal across a nearly closed choke; above it, the same instances at every
# tolerance up to 2 MPa. The share leaves out a handful of stray samples.
PRODUCTION_PRESSURES = ("P-PDG", "P-TPT", "P-MON-CKP", "P-JUS-CKP")
# (upstream, downstream, the valves and chokes that must be open between them)
SERVICE_PRESSURE_PAIRS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("P-MON-CKGL", "P-JUS-CKGL", ("ABER-CKGL",)),
    ("P-ANULAR", "P-JUS-CKGL", ("ESTADO-M2", "ESTADO-W2")),
)
# What must be open for a production pair that spans the choke, by downstream sensor.
PRODUCTION_OPEN_BETWEEN: dict[str, tuple[str, ...]] = {"P-JUS-CKP": ("ABER-CKP",)}
PRESSURE_ORDER_TOLERANCE = 1e6  # Pa
PRESSURE_ORDER_MIN_SHARE = 0.01


# -- Units on display -------------------------------------------------------------

# The unit a reading is shown in, where it is not the one the dataset records it
# in, and the factor that converts it. The files record pressures in pascals,
# which put readings of 1.2e7 on an axis, and left to itself pyqtgraph prefixed
# one axis kPa and the next MPa while the histograms, the hovers and the
# Dispersion page printed plain pascals. Every pressure the viewer shows is in
# MPa instead. Only what is shown is converted: the frames, the caches, the
# plausible ranges and the Toolkit's thresholds stay in the dataset's own unit.
DISPLAY_UNITS: dict[str, tuple[str, float]] = {"Pa": ("MPa", 1e-6)}


def display_unit(unit: str) -> tuple[str, float]:
    """The unit a reading recorded in ``unit`` is shown in, and the factor that converts it."""
    return DISPLAY_UNITS.get(unit, (unit, 1.0))


# -- The color ladder -----------------------------------------------------------

# The hues themselves are a property of the light or dark mode in force and live
# in ``theme``; what is fixed here is how far along the ladder each step sits,
# which says the same thing in either mode.

# How far the fault developed inside an instance fixes the tint of its bar:
# full hue once the steady fault state is labeled, weaker when only the
# transient is, weakest when the window never leaves normal operation.
REACH_TINTS: dict[str, float] = {"steady": 1.00, "transient": 0.55, "normal": 0.25}
REACH_LABELS: dict[str, str] = {
    "steady": "steady state reached",
    "transient": "transient state reached",
    "normal": "no fault reached",
}

# The time series plots shade their background with the same hues and the same
# three-step ladder, compressed toward the plotting ground so the trace stays
# legible; the band above each plot carries the exact bar colors.
BACKGROUND_TINTS: dict[str, float] = {"steady": 0.62, "transient": 0.38, "normal": 0.18}

# -- Layout ---------------------------------------------------------------------

# A silence at least this long splits a well's recording into two bursts, and
# the overview collapses every silence to a fixed narrow blank (see
# ``timemap.TimeMap``); in total the blanks get this share of the axis.
DEFAULT_GAP_HOURS = 12.0
GAP_SHARE = 0.12

# Plots per row of the Timelines when the viewer opens (1 to 4): one gives
# every well's timeline the full width of the window.
DEFAULT_COLUMNS = 1

# Bars taller than this share of a stack level would touch their neighbours.
BAR_HEIGHT = 0.62

# Room between two well plots of the overview grid, in pixels: enough that the
# dates under one plot are not read as the title of the next.
GRID_SPACING = (14, 20)  # (horizontal, vertical)

# Every well timeline shows at least this many stack levels, and at most this
# many before growing taller, so the grid stays comparable across wells.
MIN_LANE_SLOTS = 2
MAX_LANE_SLOTS = 8

# A signal whose range is this small relative to its own level counts as flat
# and is drawn on a padded axis instead of being autoscaled into noise.
FLAT_SPAN = 1e-4

# Loaded instances kept in memory across windows, in samples.
FRAME_CACHE_ROWS = 6_000_000

# The faults page draws every instance of a fault over the others; beyond this
# many it starts with the earliest ones ticked and leaves the rest to the user,
# since a hundred lines on one plot say nothing.
MAX_OVERLAID_INSTANCES = 24

# Laid out as small multiples instead, one plot per instance, the page draws at
# most this many: past it the plots are too small to read and too many to build.
MAX_SMALL_MULTIPLES = 48

# -- Locating the dataset ---------------------------------------------------------

# Environment variable naming the dataset root.
RAW_DIR_ENV = "OVERLAP_VIEWER_RAW_DATA_DIR"

# Where the dataset usually sits relative to the working directory: next to a
# checkout of this project (``../3W/dataset``) or inside the 3W repository.
RAW_DIR_CANDIDATES = (Path("../3W/dataset"), Path("dataset"), Path("3W/dataset"))


# Where this file sits: ``<project>/src/overlap_viewer/backend/config.py``.
PACKAGE_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = PACKAGE_DIR.parents[1]

# Illustrations the help window shows. They live in the project's docs
# directory; a copy inside the package is looked for first, so that an
# installed distribution can carry them without the docs tree.
ASSET_DIRS = (
    PACKAGE_DIR / "assets",
    PROJECT_DIR / "docs" / "assets",
)


def asset_path(name: str) -> Path | None:
    """Locate one illustration, or ``None`` when it is not shipped.

    The help degrades to text when an image is missing rather than breaking,
    so a checkout without the docs directory still opens.
    """
    for directory in ASSET_DIRS:
        candidate = directory / name
        if candidate.is_file():
            return candidate
    return None


def cache_dir() -> Path:
    """Directory of the catalogue cache, following the platform's conventions."""
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return base / "overlap-viewer"
