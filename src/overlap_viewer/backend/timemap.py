"""The time axis of a plot: real timestamps mapped onto a position in hours.

A well is recorded in bursts: well 2 spans nearly four years but holds only
4 % of them as samples, so on a true calendar axis every instance shrinks to an
invisible sliver. ``TimeMap`` lays the recording blocks side by side and
collapses each silence between them to a fixed narrow blank, keeping the time
scale uniform inside and across blocks: a bar length is still a duration, and
two bars overlap on the axis exactly when the instances overlap in time. The
same class with ``compressed=False`` (or with a single block, as for the time
series of one group of instances) is a plain linear axis, so every plot of the
viewer speaks the same coordinates.
"""

from dataclasses import dataclass
from itertools import pairwise

import numpy as np
import pandas as pd

from overlap_viewer.backend.config import DEFAULT_GAP_HOURS, GAP_SHARE

HOUR = np.timedelta64(3_600_000_000_000, "ns")


@dataclass(frozen=True)
class TimeMap:
    """Piecewise-linear map between timestamps and a position in hours.

    Attributes
    ----------
    blocks : pd.DataFrame
        One row per recording block, chronological, with its ``start`` and
        ``end`` timestamps, its ``hours`` of real duration and ``x0``, the
        position of its start on the axis (in hours).
    compressed : bool
        Whether the silences between blocks were collapsed.
    """

    blocks: pd.DataFrame
    compressed: bool

    @classmethod
    def build(
        cls,
        starts,
        ends,
        gap_hours: float = DEFAULT_GAP_HOURS,
        gap_share: float = GAP_SHARE,
        compressed: bool = True,
    ) -> "TimeMap":
        """Group the instances into recording blocks and lay them on the axis.

        Parameters
        ----------
        starts, ends : array-like of datetime64
            First and last timestamp of every instance.
        gap_hours : float
            A silence this long or longer breaks the recording into two
            blocks (compressed mode only).
        gap_share : float
            Fraction of the drawn width given to the collapsed silences in
            total, split evenly between them, so a well recorded in many bursts
            does not spend the axis on blanks.
        compressed : bool
            ``False`` builds a single block from the first start to the last
            end, i.e. a calendar axis.
        """
        starts = np.asarray(starts, dtype="datetime64[ns]")
        ends = np.asarray(ends, dtype="datetime64[ns]")
        if len(starts) == 0:
            raise ValueError("A TimeMap needs at least one instance")

        if not compressed:
            spans = [[starts.min(), ends.max()]]
        else:
            limit = np.timedelta64(int(gap_hours * 3600), "s")
            spans = []
            for i in np.argsort(starts, kind="stable"):
                if spans and starts[i] - spans[-1][1] < limit:
                    spans[-1][1] = max(spans[-1][1], ends[i])
                else:
                    spans.append([starts[i], ends[i]])

        blocks = pd.DataFrame(spans, columns=["start", "end"])
        hours = (blocks["end"] - blocks["start"]).to_numpy() / HOUR
        gap = gap_share * max(float(hours.sum()), 1.0) / max(len(blocks) - 1, 1)
        blocks["hours"] = hours
        blocks["x0"] = np.concatenate(([0.0], np.cumsum(hours + gap)[:-1]))
        return cls(blocks, compressed)

    @property
    def span(self) -> float:
        """Position of the end of the last block, in hours (at least a minute)."""
        return max(float(self.blocks["x0"].iloc[-1] + self.blocks["hours"].iloc[-1]), 1 / 60)

    @property
    def origin(self) -> pd.Timestamp:
        """Timestamp at position zero."""
        return pd.Timestamp(self.blocks["start"].iloc[0])

    def to_x(self, timestamps) -> np.ndarray:
        """Place timestamps on the axis.

        A timestamp inside a collapsed silence is measured from the start of
        the block before it, so it lands in the blank; the viewer never has to
        place one, since every drawn span lies inside a block by construction.
        """
        stamps = np.asarray(pd.to_datetime(np.asarray(timestamps)), dtype="datetime64[ns]")
        block_starts = self.blocks["start"].to_numpy(dtype="datetime64[ns]")
        index = np.clip(
            np.searchsorted(block_starts, stamps, side="right") - 1, 0, len(self.blocks) - 1
        )
        offsets = (stamps - block_starts[index]) / HOUR
        return self.blocks["x0"].to_numpy()[index] + offsets

    def to_time(self, x: float) -> pd.Timestamp | None:
        """Read the timestamp at one position; ``None`` inside a collapsed silence.

        A linear axis (a single block) extrapolates beyond its ends, so the
        ticks of a zoomed-out view still carry dates.
        """
        x0 = self.blocks["x0"].to_numpy()
        hours = self.blocks["hours"].to_numpy()
        i = int(np.clip(np.searchsorted(x0, x, side="right") - 1, 0, len(x0) - 1))
        offset = x - x0[i]
        if len(x0) > 1 and (offset < -1e-9 or offset > hours[i] + 1e-9):
            return None
        return pd.Timestamp(self.blocks["start"].iloc[i]) + pd.Timedelta(hours=float(offset))

    def block_spans(self) -> list[tuple[float, float]]:
        """Position of the start and end of every block."""
        return [
            (float(x0), float(x0 + hours))
            for x0, hours in zip(self.blocks["x0"], self.blocks["hours"])
        ]

    def gap_centers(self) -> list[float]:
        """Middle of every collapsed silence, where a separator is drawn."""
        return [0.5 * (a[1] + b[0]) for a, b in pairwise(self.block_spans())]

    @property
    def calendar_days(self) -> float:
        """Real calendar span from the first start to the last end, in days."""
        first = self.blocks["start"].iloc[0]
        last = self.blocks["end"].iloc[-1]
        return float((last - first) / pd.Timedelta(days=1))

    @property
    def recorded_hours(self) -> float:
        """Hours covered by the blocks, silences shorter than the gap included."""
        return float(self.blocks["hours"].sum())
