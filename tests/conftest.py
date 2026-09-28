"""What every test module shares: the synthetic miniature of the 3W layout and its helpers."""

import os
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from overlap_viewer.backend import theme

T0 = pd.Timestamp("2017-02-01 01:00:00")

# Where ``config.cache_dir`` looks on the platform the tests are running on. A
# test that wants the cache inside its ``tmp_path`` sets this one rather than
# faking ``os.name`` to reach the other branch: ``os.name`` is also what tells
# ``pathlib`` which flavour of ``Path`` to build, so a Windows interpreter told
# it is POSIX hands out ``PosixPath`` objects that raise on their first join.
CACHE_HOME = "LOCALAPPDATA" if os.name == "nt" else "XDG_CACHE_HOME"


@pytest.fixture(autouse=True)
def light_theme():
    """The theme is global, so a test that switches it must not colour the next one."""
    theme.use("light")
    yield
    theme.use("light")


def hours(h: float) -> pd.Timestamp:
    return T0 + pd.Timedelta(hours=h)


def write_instance(
    folder: Path,
    well: int,
    start: pd.Timestamp,
    n: int,
    classes,
    pdg_offset: float = 0.0,
    pdg_missing: float = 0.0,
    statistics: bool = True,
) -> Path:
    """One parquet file shaped like a 3W instance: timestamp index, sensors, nullable labels.

    The sensors cover the states the availability analysis tells apart: a
    pressure that moves (``P-PDG``, shifted by ``pdg_offset`` so a file can
    carry a negative pressure, and missing for the leading ``pdg_missing``
    share of the samples so a file can carry a partly recorded sensor), a
    frozen temperature (``T-TPT``), an absent flow rate (``QGL``) and a valve
    held open throughout (``ESTADO-W1``). ``statistics=False`` writes the file
    without the footer figures the scan reads first, so the fallback that
    reads the columns gets exercised. The pressure is one straight line from
    end to end, which the interpolation test reads as two measurements.
    """
    index = pd.date_range(start, periods=n, freq="1s", name="timestamp")
    pdg = np.linspace(1.0e7, 1.1e7, n) + pdg_offset
    pdg[: round(pdg_missing * n)] = np.nan
    frame = pd.DataFrame(
        {
            "P-PDG": pdg,
            "T-TPT": np.full(n, 118.5),
            "QGL": np.full(n, np.nan),
            "ESTADO-W1": np.full(n, 1.0),
            "class": pd.array(classes, dtype="Int16"),
            "state": pd.array([0] * n, dtype="Int16"),
        },
        index=index,
    )
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"WELL-{well:05d}_{start:%Y%m%d%H%M%S}.parquet"
    if statistics:
        frame.to_parquet(path)
    else:
        pq.write_table(pa.Table.from_pandas(frame), path, write_statistics=False)
    return path


@pytest.fixture
def raw_dir(tmp_path: Path) -> Path:
    root = tmp_path / "dataset"
    (root / "dataset.ini").parent.mkdir()
    (root / "dataset.ini").write_text(
        "[VERSION]\nDATASET = 9.9.9\n"
        "[PARQUET_FILE_PROPERTIES]\ntimestamp = Instant\nP-PDG = Downhole pressure [Pa]\n"
        "T-TPT = Xmas-tree temperature [oC]\nQGL = Gas lift flow rate [m3/s]\n"
        "ESTADO-W1 = State of the PWV [0, 0.5, or 1]\nclass = Label\nstate = Status\n"
        "[EVENTS]\nNAMES = NORMAL, HYDRATE_IN_SERVICE_LINE\nTRANSIENT_OFFSET = 100\n"
        "[NORMAL]\nLABEL = 0\nDESCRIPTION = Normal Operation\n"
        "[HYDRATE_IN_SERVICE_LINE]\nLABEL = 9\nDESCRIPTION = Hydrate in Service Line\nTRANSIENT = True\n",
        encoding="utf-8",
    )
    n = 3600
    # Well 1: a chain of three windows, each overlapping the next by one hour.
    write_instance(root / "0", 1, hours(0), 2 * n, [0] * (2 * n))
    write_instance(root / "0", 1, hours(1), 2 * n, [0] * (2 * n))
    write_instance(root / "0", 1, hours(2), 2 * n, [0] * (2 * n))
    # Well 2: one hydrate instance that reaches the transient only, its downhole
    # pressure missing for the first 60 % of the recording, and one that never
    # leaves normal and reports a negative downhole pressure, written without
    # footer statistics.
    write_instance(
        root / "9", 2, hours(0), n, [pd.NA] * 600 + [0] * 1800 + [109] * 1200, pdg_missing=0.6
    )
    write_instance(root / "9", 2, hours(48), n, [0] * n, pdg_offset=-2.0e7, statistics=False)
    # A simulated file must be ignored.
    (root / "9" / "SIMULATED_00001.parquet").write_bytes(b"not parquet")
    return root
