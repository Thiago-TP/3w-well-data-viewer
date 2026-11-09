"""The shape of one sensor compared between instances by dynamic time warping. Needs the ``dtw`` extra.

The 3W Toolkit's clustering subpackage compares instances by the DTW distance
between their series, which lines two series up allowing one to run ahead of
or behind the other, so that two slugging cycles of different period still
match. This module is the viewer's reduced form of that comparison, on one
sensor, within one class, for the Instances map.

Two things are done to a series before the distance is taken. It is
**z-scored**, so that the levels of two wells do not swamp their shapes
(what the toolkit's scaler does). And it is **decimated** to a few hundred
blocks (each block the mean of the readings inside it) because DTW costs the
product of the two lengths and a six-hour instance has 21,600 samples: the
decimation is a matter of cost, the blocks stay proportional to the length of
the instance, and a shape a few minutes long survives it. This is not the
resampling of every instance to one common length, which changes what a shape
is and was not taken up.

The distances come from ``dtaidistance``, in C, under a Sakoe-Chiba window of
a tenth of the length, which forbids the alignment from running away.
"""

from collections.abc import Sequence

import numpy as np

N_BLOCKS = 400  # the length a series is decimated to
WINDOW_SHARE = 0.1  # the Sakoe-Chiba window, as a share of the length
MIN_READINGS = 32


def decimate(values: np.ndarray, n_blocks: int = N_BLOCKS) -> np.ndarray | None:
    """A series averaged into ``n_blocks`` blocks and z-scored; ``None`` when too little of it is there.

    Blocks without a reading are filled by linear interpolation between their
    neighbours, the ends by the nearest block; a flat series has no shape and
    declines.
    """
    y = np.asarray(values, dtype=float)
    valid = ~np.isnan(y)
    if valid.sum() < MIN_READINGS:
        return None
    n = len(y)
    n_blocks = int(min(n_blocks, n))
    edges = np.linspace(0, n, n_blocks + 1).astype(int)
    sums = np.add.reduceat(np.where(valid, y, 0.0), edges[:-1])
    counts = np.add.reduceat(valid.astype(float), edges[:-1])
    with np.errstate(invalid="ignore", divide="ignore"):
        blocks = sums / counts
    filled = counts > 0
    if not filled.all():
        positions = np.arange(n_blocks)
        blocks = np.interp(positions, positions[filled], blocks[filled])
    std = float(blocks.std())
    if not np.isfinite(std) or std <= 0:
        return None
    return (blocks - blocks.mean()) / std


def dtw_distances(series: Sequence[np.ndarray], window_share: float = WINDOW_SHARE) -> np.ndarray:
    """The full matrix of DTW distances between the decimated, z-scored series."""
    from dtaidistance import dtw

    rows = [np.ascontiguousarray(s, dtype=float) for s in series]
    n = len(rows)
    if n == 0:
        return np.zeros((0, 0))
    length = max(len(s) for s in rows)
    window = max(1, round(window_share * length))
    matrix = dtw.distance_matrix_fast(rows, window=window, compact=False)
    matrix = np.asarray(matrix, dtype=float)
    # The library fills the lower triangle with infinities; the matrix is symmetric.
    upper = np.triu(matrix, 1)
    full = upper + upper.T
    np.fill_diagonal(full, 0.0)
    return full
