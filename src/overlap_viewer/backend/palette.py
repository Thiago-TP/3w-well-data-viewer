"""Colors: fault hues tinted by reach, label shading, legend entries. No Qt here.

The hues themselves belong to the theme in force (see ``theme``); what is here
is how they combine: the ladder of tints that says how far a fault developed,
and the key that names every color drawn. The theme is read on every call rather
than captured, so switching mode and rebuilding is enough to repaint everything.

Every color is a ``#rrggbb`` string so the backend and its tests stay free of
Qt; the widgets turn them into ``QColor`` at draw time.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from overlap_viewer.backend import theme
from overlap_viewer.backend.config import (
    BACKGROUND_TINTS,
    REACH_LABELS,
    REACH_TINTS,
)


def to_rgb(color: str) -> tuple[float, float, float]:
    """Parse ``#rrggbb`` into floats in ``0..1``."""
    color = color.lstrip("#")
    return tuple(int(color[i : i + 2], 16) / 255.0 for i in (0, 2, 4))


def to_hex(rgb: tuple[float, float, float]) -> str:
    """Format floats in ``0..1`` as ``#rrggbb``."""
    return "#" + "".join(f"{round(max(0.0, min(1.0, c)) * 255):02x}" for c in rgb)


def tint(color: str, strength: float, base: str | None = None) -> str:
    """Mix one color toward the ground it is drawn on, ``strength`` 1.0 keeping it untouched.

    That ground is the plotting background of the theme in force (white in
    light mode, near-black in dark mode), so a weaker tint always means less of
    the hue and more of the background, whichever way round the two are. Mixing
    toward white regardless would make the faintest step of the ladder the
    loudest thing on a dark plot.
    """
    ground = to_rgb(base if base is not None else theme.current().plot_background)
    return to_hex(tuple(g - (g - c) * strength for g, c in zip(ground, to_rgb(color))))


def fault_color(fault_class: int) -> str:
    """Hue of one fault-class folder."""
    colors = theme.current()
    return colors.faults.get(fault_class, colors.fallback_fault)


def luminance(color: str) -> float:
    """How bright a color reads, on the usual weighting of its channels."""
    r, g, b = to_rgb(color)
    return 0.299 * r + 0.587 * g + 0.114 * b


def bar_strength(fault_class: int, reach: str) -> float:
    """Tint strength of an instance bar.

    Normal instances (folder 0) keep full strength whatever their labels say:
    they have no fault to develop, and tinting them would render the largest
    group of the dataset as near-white bars.
    """
    return 1.0 if fault_class == 0 else REACH_TINTS[reach]


def bar_color(fault_class: int, reach: str) -> str:
    """Fill color of one instance bar in the overview: its hue tinted by reach."""
    return tint(fault_color(fault_class), bar_strength(fault_class, reach))


def background_color(fault_class: int, reach: str) -> str:
    """Background of a time series stretch, on the same ladder as ``bar_color``.

    The three reach levels keep their order and their hue but are compressed
    toward the plotting ground (``BACKGROUND_TINTS``), so a full-strength fault
    hue does not swallow the trace drawn over it.
    """
    strength = BACKGROUND_TINTS["steady"] if fault_class == 0 else BACKGROUND_TINTS[reach]
    return tint(fault_color(fault_class), strength)


def unknown_background() -> str:
    """Background of an unlabeled stretch of a time series."""
    return theme.current().unknown


def state_color(state: int | None) -> str:
    """Color of one well operational status code, neutral grey when unknown."""
    states = theme.current().states
    return states.get(state, states[None])


def text_color(background: str) -> str:
    """Black or white, whichever reads better on ``background``."""
    r, g, b = to_rgb(background)
    return "#ffffff" if 0.299 * r + 0.587 * g + 0.114 * b < 0.55 else "#1a1a1a"


def blend(colors: Sequence[str]) -> str:
    """The plain average of several colors: what a bar striped with them reads as overall."""
    parts = [to_rgb(color) for color in colors]
    return to_hex(tuple(sum(part[k] for part in parts) / len(parts) for k in range(3)))


def legend_label(fault_class: int, reach: str, fault_names: dict[int, str]) -> str:
    """Name of one legend entry: the fault, and its reach unless it is normal."""
    name = fault_names.get(fault_class, f"Class {fault_class}")
    return name if fault_class == 0 else f"{name} ({REACH_LABELS[reach]})"


def legend_key(fault_class: int, reach: str) -> tuple[int, str]:
    """The legend entry one bar belongs to.

    Normal instances are never tinted (see ``bar_strength``), so their three
    reaches share the single entry the legend draws for them.
    """
    return (fault_class, reach if fault_class != 0 else "steady")


@dataclass(frozen=True)
class LegendEntry:
    """One swatch of the color key: what it means and the exact colors it carries."""

    fault_class: int
    reach: str
    label: str
    fill: str
    edge: str

    @property
    def key(self) -> tuple[int, str]:
        return (self.fault_class, self.reach)


def legend_entries(present: set[tuple[int, str]], fault_names: dict[int, str]) -> list[LegendEntry]:
    """Key every color drawn, one entry per fault and reach actually present.

    A bar carries a fault hue tinted by reach, and naming the hue and the tint
    in two separate keys would leave the reader to imagine their product, so
    every combination present gets its own swatch in the very color its bars
    carry, strongest tint of a fault first. The entries of one fault are
    therefore consecutive, and the viewer keeps such a gradient on one row.

    Parameters
    ----------
    present : set[(int, str)]
        Fault class and reach of every bar drawn.
    fault_names : dict[int, str]
        Display name per fault class.

    Returns
    -------
    list[LegendEntry]
        One entry per color, by fault and then by decreasing tint strength.
    """
    keys = sorted(
        {legend_key(fault_class, reach) for fault_class, reach in present},
        key=lambda entry: (entry[0], -REACH_TINTS[entry[1]]),
    )
    return [
        LegendEntry(
            fault_class,
            reach,
            legend_label(fault_class, reach, fault_names),
            bar_color(fault_class, reach),
            fault_color(fault_class),
        )
        for fault_class, reach in keys
    ]
