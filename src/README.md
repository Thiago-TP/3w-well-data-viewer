# Source layout

The package is laid out by focus, and the dependencies grow from one layer to the next:

- **`backend`**: what the data is: reading `dataset.ini`, the instance catalogue and its caches,
  the label runs, the availability model, and the viewer's own data (theme, palette, help text).
  Pandas, numpy and pyarrow only; no Qt, so every module here is testable without a display.
- **`algorithms`**: what is computed from the data: onsets and scaling, the signal transforms,
  and every analysis built for the later pages (interpolation, descriptors, cleaning, embedding,
  correlation, dispersion). Numpy only; anything heavier (scikit-learn, UMAP, dtaidistance) is an
  optional extra, declared in `pyproject.toml` and looked up through `backend.extras` so that a
  missing one greys a control instead of breaking the viewer.
- **`frontend`**: how it is shown: the pyqtgraph items, the pages, the instance window and the
  main window. PySide6 and pyqtgraph.

`app.py` is the command line and start-up; it is the one module of the top level that imports from
all three. `__main__.py` lets `python -m overlap_viewer` run it the same way `main.py` does from a
checkout.

```
src/overlap_viewer/
├── app.py                command line and start-up
├── __main__.py           python -m overlap_viewer
├── backend/              what the data is: pandas, numpy and pyarrow only
│   ├── config.py         dataset fallbacks, plausible ranges, the tint ladder, signatures, layout, cache
│   ├── dataset.py        dataset.ini, instance catalogue and its cache, sensor figures from the footers, from merged recordings and pair by pair, overlaps and joins per well
│   ├── profiles.py       the pass that profiles every sensor of every instance and bar: how it was measured, what it amounts to, cached
│   ├── labels.py         label kinds and names, runs, their agreement and their merge, feature statistics, coverage counts, a stamp at a frame's own resolution
│   ├── timemap.py        gap-compressed (or calendar) time axis in hours
│   ├── availability.py   the three states of a sensor in a bar, the measured/filled split of the live share, groups folded into shares of samples or of bars, the pair map of a scope
│   ├── extras.py         the optional dependency groups: what each enables, whether it is installed, how it is installed
│   ├── export.py         the Toolkit file list: a ParquetDatasetConfig of the instances on show, with its provenance
│   ├── model_outputs.py  the model-output format: model.json beside per-instance parquet files, its loader, the agreement with the labels
│   ├── theme.py          every color of the light and of the dark mode
│   ├── palette.py        fault hues tinted by reach, legend entries
│   └── help_text.py      what the help says: classes, variables, statuses, availability, usage, sources
├── algorithms/           what is computed from the data: numpy only; anything heavier is an optional extra
│   ├── faults.py         where the event begins in an instance, z-scores, the plausible extent of a series
│   ├── interpolation.py  which samples are measurements and which the historian drew: held, interpolated, genuine, the spacing of the measurements
│   ├── descriptors.py    what a series amounts to: moments, quantiles, autocorrelation time, signal-to-noise ratio, Zhang's Gaussianity test
│   ├── cleaning.py       the Toolkit's CleanSignals rule on the profiles: bounds at the quartiles, the sensors discarded and dropped
│   ├── consistency.py    whether the pressures of one recording read in the order the flow imposes, line by line
│   ├── embedding.py      the Instances map: representations, PCA and MDS in numpy, t-SNE and UMAP, the clusterings and their scores, typicality, the one-class audit
│   ├── dtw.py            the DTW distance between the decimated, z-scored series of one sensor (the `dtw` extra)
│   ├── correlation.py    how the sensors move together over a scope: Pearson exact over the pooled samples, the mutual-information and nonlinear coefficients
│   ├── dispersion.py     two sensors against each other over a scope: an even subsample of every instance with its label periods and measurements, the pair, its density
│   ├── spectral.py       the signal views: a series prepared, Welch's density and the dominant period, the Lomb-Scargle periodogram of the measurements, histograms stacked by label, with their peak
│   └── windows.py        one sensor of a well cut into windows of a fixed size: one label each, zero padding at the end of a run, each instant once; the descriptors of every window, the separation of normal from event windows
└── frontend/             how it is shown: PySide6 and pyqtgraph
    ├── styling.py            installing a theme into Qt and pyqtgraph, the saved mode
    ├── loading.py            progress dialogs, cache of loaded instances
    ├── passes.py             the passes over the data, read once behind a dialog and shared by every page
    ├── traces.py             a time series drawn as measurements (dots) and the historian's lines (faint) between them
    ├── items.py              pyqtgraph items: segments, instance bars and their marks, time axis, anchored text
    ├── spectral_items.py     the parameter widgets, the period axis and the builders of the signal views
    ├── heatmap.py            the matrix widget of the availability page, its tooltips and the keys of the states
    ├── legend.py             the clickable color key and its flow layout
    ├── help.py               the help window
    ├── overview.py           the timelines page: the grid of well timelines
    ├── availability_page.py  the availability page: its three matrices (availability, sensor pairs, sensor correlations) and what each says
    ├── series_page.py        what the faults and features pages both are: sections of instances, in a chosen domain and layout
    ├── faults_page.py        the faults page: one fault, a section per feature, its instances in the color of their well
    ├── features_page.py      the features page: one sensor, a section per fault class, the classes over one another when overlaid
    ├── map_page.py           the Instances map: the points, their colorings, the clustering scores, the label audit
    ├── dispersion_page.py    the Dispersions page: two sensors against each other over a scope, the dots, the density, the measurements alone
    ├── windows_page.py       the Windows page: one sensor of a well in windows of one label each, the table, the thumbnails, the strip, one feature of every window
    ├── placements.py         the Topside, Seabed and Subsurface boxes of a feature panel
    ├── instance_window.py    the time series of a group of overlapping instances, with their distributions and spectra
    ├── statistics_window.py  the statistics table of an instance window: mean, median, spread, quartiles, skewness, kurtosis
    └── window.py             the main window: the pages, the shared toolbar and status bar, the windows they open
```

What follows details every file: its purpose, and its public classes and functions. Names starting
with `_` are left out unless they carry logic worth knowing about; routine Qt plumbing (signal
handlers, `paintEvent`, dunder methods) is summarized rather than listed method by method.

## `backend/`

Qt-free: dataclasses and functions over numpy/pandas/pyarrow, built to be unit-tested without a
display.

### `config.py`

Constants the rest of the viewer reads: dataset fallbacks used when `dataset.ini` is missing, the
plausible-value ranges and why they are what they are, the pairs of pressures that must read in
order and the survey behind them, the fault-tint color ladder, layout numbers,
and dataset/cache path resolution. Anything the dataset itself can state is read from `dataset.ini`
at runtime (see `dataset.DatasetInfo`); this module holds only the fallbacks and the viewer's own
choices.

- `plausible_range(unit)`: the `(low, high)` a reading in `unit` must fall in to count as a
  measurement.
- `asset_path(name)`: locates one help-window illustration under `ASSET_DIRS`, `None` if not
  shipped.
- `cache_dir()`: the platform cache directory (`%LOCALAPPDATA%/overlap-viewer` on Windows,
  `$XDG_CACHE_HOME/overlap-viewer` or `~/.cache/overlap-viewer` elsewhere).

Notable constants: `DEFAULT_FAULT_NAMES`, `DEFAULT_TRANSIENT_OFFSET`, `DEFAULT_SENSOR_UNITS`,
`WELL_STATES`, `FAULT_SIGNATURES` (the sensors that reproduce the 2.0.0 paper's example figures per
fault) with `BEST_EFFORT_SIGNATURES` and `BEST_EFFORT_SOURCES` for the five events it does not
illustrate (read off the thesis), documentation the help shows and no page ticks,
`PLACEMENTS` (every variable under Topside, Seabed or Subsurface) with `PLACEMENT_NOTES`,
`placement_of(sensor)` and `DEFAULT_FEATURES` (what the instance window and the Faults page open
on), `REAL_PREFIX = "WELL-"`, `PLAUSIBLE_RANGES` and `EXTREME_VALUE_LIMIT` (the plausibility
survey's results), `REACH_TINTS`/`REACH_LABELS`/`BACKGROUND_TINTS` (the tint ladder `palette.py`
uses), layout numbers (`DEFAULT_GAP_HOURS`, `BAR_HEIGHT`, `MAX_OVERLAID_INSTANCES`, …),
`RAW_DIR_ENV = "OVERLAP_VIEWER_RAW_DATA_DIR"` and `RAW_DIR_CANDIDATES`, `PACKAGE_DIR`/`PROJECT_DIR`/
`ASSET_DIRS`.

### `dataset.py`

The dataset side of the viewer: reads `dataset.ini` metadata, discovers and catalogues real
instances (cached), computes per-well overlaps/lanes and joined (merged) views, and runs two more
cached data passes: merged sensor figures for joined bars, and sensor-pair co-validity counts.

- `DatasetInfo` (frozen dataclass): `raw_dir`, fault names, transient offset, sensor units and
  descriptions, version; classmethod `load(raw_dir)` parses `dataset.ini`, falling back to
  `config`'s defaults if absent.
- `parse_well_id(filename)` / `well_label(well)` / `filename_stamp(filename)`: well number, display
  name, and embedded timestamp of a `WELL-00026_...` filename.
- `list_real_instances(raw_dir, fault_classes)`: every real instance path, grouped by fault folder.
- `read_sensor_stats(parquet)`: per-sensor `(readings, low, high)` from the parquet footer's
  row-group statistics, falling back to a full read when a column's footer stats are missing.
- `scan_instances(entries, transient_offset, progress=None)`: the full catalogue scan: time span,
  reach, label runs, sensor stats per instance.
- `load_catalogue(info, use_cache=True, progress=None)`: the catalogue, from the disk cache when it
  validates against the current file listing, else rescanned.
- `load_instance(path)`: reads one instance parquet in full.
- `load_instance_columns(path, columns)`: reads some columns of one instance (a third of the cost of
  reading it whole), a column the file lacks coming back all missing; what the Windows page reads
  one sensor of a well with.
- `merge_instances(frames)`: combines overlapping instance frames of one well into one continuous
  recording, missing values filled from whichever frame has them.
- `stitch_instances(pieces)`: the recordings of a well laid end to end, each a group of frames
  merged as above; the index keeps the real timestamps and jumps over the silences.
- `pack_lanes(starts, ends)`: greedy interval-stacking into lanes so overlapping instances get
  distinct stack levels; the number of lanes is the well's deepest pile-up.
- `join_groups(starts, ends, runs)`: groups instances that overlap in time *and* agree on their
  labels (`labels.labels_agree`) into joinable clusters.
- `WellData` (dataclass): the bars of one well, stacked and overlap-resolved; classmethod
  `from_catalogue(catalogue, well)`; method `joined(among=None)` builds/caches the merged view via
  `join_groups`; `stitched()` builds/caches the stitched view, one bar per lane of the joined view
  with `pieces` naming the joined bars laid end to end in it (`stitched_view`,
  `piece_members(index)`, and `spans(positions)`, the recordings a time axis is built from).
- `split_wells(catalogue)`: one `WellData` per well.
- `scan_joined_stats(wells, sensors, progress=None)` / `load_joined_stats(...)`: the pass (and its
  cache) computing merged sensor stats and pair counts for every joined bar of every well.
- `scan_pair_counts(entries, sensors, progress=None)` / `load_pair_counts(...)`: the pass (and its
  cache) computing sensor-pair co-validity counts for every real instance.
- `listing_digest(listing)`: sha1 digest of a file listing, used to validate every cache in the
  package.

### `profiles.py`

The single data pass that profiles every sensor of every real instance and every bar of the joined
view: how it was measured (genuine/interpolated/held sample counts, spacing, from
`algorithms.interpolation`) and what it amounts to statistically (moments, quantiles, autocorrelation
time, SNR, Gaussianity, from `algorithms.descriptors`), computed twice, on the full 1 Hz grid and on
the measurements alone. It also checks the order of the pressures along each line
(`algorithms.consistency`), recording per sensor the samples out of order and the pressures it
contradicts. Cached as one long parquet table next to the catalogue.

- `DescriptorChoice` (frozen dataclass): one of the five descriptors offered as a coloring or sort
  option (autocorrelation time, SNR, Gaussianity slope, skewness, kurtosis); method `format(value)`.
- `profile_series(values, bounds, enumerated, step_s)`: profiles one sensor's array: strips
  implausible readings, classifies sample kinds, computes sampling and descriptors twice.
- `profile_frame(frame, sensors, info)`: one profile row per sensor of one frame.
- `scan_profiles(wells, sensors, info, progress=None)`: the full pass, over every instance and every
  joined bar.
- `Profiles` (dataclass): the loaded table, with lookup indexes; methods `row(key, sensor, joined)`,
  `descriptor(key, sensor, column, joined)`, `sampling(key, sensor, joined)`, `matrix(keys, joined,
  column, sensors=None)`, `order_partners(key, sensor, joined)`, `scope(joined)`.
- `load_profiles(info, wells, sensors, use_cache=True, progress=None, cache_only=False)`: the
  cache-aware entry point, validated by listing digest, sensor set and `PROFILE_VERSION`; with
  `cache_only` it never reads the data and returns `None` for a missing or stale cache, which is how
  `Passes.profiles_if_loaded` picks up a cache an earlier session left.

### `labels.py`

Everything derived from the `class`/`state` label columns: classifying label values, splitting into
runs, naming them, merging overlapping label tracks, checking agreement, per-sensor feature
statistics, axis padding, and JSON (de)serialization of runs/stats for the catalogue cache.

- `label_kind(value, offset)` / `label_fault(value, offset)` / `label_name(value, fault_names,
  offset)`: classifies, names the fault of, and renders a `class` value.
- `state_name(value)`: human-readable well-status name.
- `fault_reach(class_values, offset)`: the strongest reach (steady/transient/normal) present.
- `runs(values)`: splits a float array (NaN as a value) into `(start, end, value)` runs.
- `Segment` (frozen dataclass): one label run as a time span; `label_segments(df, column)` tiles a
  column's runs across the whole recording.
- `segments_to_json` / `segments_from_json` and `sensor_stats_to_json` / `sensor_stats_from_json`:
  JSON round-trips for the catalogue cache.
- `merge_label_runs(tracks, sources)`: merges several overlapping label tracks, keeping which source
  track supplied each stretch.
- `labels_agree(a, b)`: whether two tiling label tracks never contradict where both are known; the
  joinability test `dataset.join_groups` uses.
- `FeatureStats` (frozen dataclass): `n_valid`, `n_total`, `low`, `high`, with `coverage`/`flat`
  properties; `feature_stats(df, sensor)` builds one.
- `at_index_unit(frame, stamp)`: rounds a nanosecond `Timestamp` to a frame's own index resolution
  (microseconds) so pandas search does not raise.
- `padded_range(low, high, pad=0.06)`: axis limits, centered with a small margin when the range is
  flat rather than amplifying noise.
- `coverage_counts(starts, ends)`: sweep-line count of how many instances cover each stretch of
  time.

### `timemap.py`

Builds the gap-compressed (or plain calendar) time axis every plot uses: lays a well's recording
bursts side by side in hours, collapsing long silences to a fixed narrow blank so duration stays
proportional and overlaps still read correctly.

- `TimeMap` (frozen dataclass): classmethod `build(starts, ends, gap_hours, gap_share, compressed)`
  groups instances into blocks (splitting on long silences when compressed) and lays them on the
  hour axis; `to_x(timestamps)` / `to_time(x)` convert between a timestamp and its axis position
  (`None` inside a collapsed silence); `block_spans()`, `gap_centers()`; properties `span`, `origin`,
  `calendar_days`, `recorded_hours`.

### `availability.py`

Models the three availability states of a sensor within a bar (absent/frozen/live), and folds
bar-level sensor stats into group-level tables (sample-shares or bar-shares, by fault class, well or
instance), plus the sensor-pair co-occurrence map behind the "Sensor pairs" matrix. Splits the live
share further into measured-vs-filled when `profiles.Profiles` are supplied.

- `sensor_state(n_valid, n_total, low, high, enumerated, threshold)`: classifies one sensor of one
  bar into absent/frozen/live (a valve state never freezes).
- `implausible_sensors(stats, info)`: sensor names of a bar whose readings leave the plausible
  range.
- `AvailabilityTable` (frozen dataclass): one row per group of bars; properties `shares`,
  `instance_shares`, `measured`; methods `measured_share`, `spacing_s`, `coverage_order`.
- `Availability` (frozen dataclass): per-bar raw arrays; classmethods `from_wells(views, info,
  threshold, joined_stats=None, profiles=None)` (the main builder) and `from_catalogue(...)`; methods
  `index_of(well, bar)`, `measured_of`, `shares_of`, `implausible_any`, `grouped(keys, order, mask)`
  (folds bars into an `AvailabilityTable`), `total(key, mask)`.
- `PairTable` (frozen dataclass): square sensor×sensor co-validity matrix for one scope; method
  `grouped_order()`: spectral seriation (Fiedler-vector ordering) so co-recorded sensors sit
  together.
- `PairCoverage` (frozen dataclass): per-bar upper-triangle pair counts; classmethods
  `from_counts(availability, counts)` / `from_joined(availability, joined)`; method `table(...)`
  folds into a `PairTable`.

### `extras.py`

Declares the viewer's optional-dependency groups (`analysis`, `umap`, `dtw`): what each enables, its
import name, and how to detect/install it, without importing any optional package at module import
time, so the core app always starts.

- `Extra` (frozen dataclass): `name`, `modules`, `enables`; `EXTRAS` is the dict of the three
  groups.
- `install_command(name)`: `"uv sync --extra {name}"`.
- `missing(name)`: `None` if the group's modules all import, else a one-sentence message naming what
  is missing and how to install it (cached).
- `available(name)`: `missing(name) is None`.

The test suite checks `EXTRAS` agrees with `pyproject.toml`'s optional-dependency groups.

### `export.py`

Writes the 3W Toolkit's `ParquetDatasetConfig` file-list JSON format (`split="list"`) for whatever
instances a page currently shows, plus a sibling provenance JSON.

- `relative_file(fault_class, file)`: an instance's path relative to the dataset root, as the
  Toolkit lists events.
- `file_list_config(info, files)`: the `ParquetDatasetConfig`-shaped dict for a set of instances.
- `provenance(info, source, n_files)`: a dict describing where a file list came from.
- `write_file_list(path, info, files, source)`: writes the config JSON plus its
  `<name>.provenance.json`.

### `model_outputs.py`

Defines the viewer's own model-output folder format (the smallest one that ties a verdict to an
instance and an instant, which the Toolkit's own prediction export cannot do), a loader/cache for it,
and the agreement measurement between model verdicts and dataset labels.

- `ModelSpec` (frozen dataclass): `name`, `kind` (`"detection"`/`"classification"`), `labels`,
  `description`, `provenance`; classmethod `from_json(data)`.
- `Agreement` (frozen dataclass): `compared_s`, `agreed_s`, `scored_s`; property `share`.
- `agrees(model_label, dataset_label, kind, offset)`: whether one verdict agrees with one dataset
  label.
- `agreement(model_runs, class_runs, kind, offset)`: sweeps both run-lists and sums seconds
  compared/agreed/scored.
- `ModelOutputs`: a folder of outputs opened once, read lazily and cached; classmethod
  `load(folder)`; methods `frame(fault_class, file)`, `runs(fault_class, file)`,
  `agreement(fault_class, file, class_runs, offset)`, `describe()`.
- `write_outputs(folder, spec, outputs, provenance=None)`: writes a full output folder, the
  `timestamp` index delta encoded and the whole compressed with zstd: a verdict per second is
  mostly its own timestamp, which written plainly is four fifths of a file.

### `theme.py`

Defines the complete `LIGHT`/`DARK` color schemes (Qt window chrome, pyqtgraph plot colors, data and
legend colors) as one `Theme` object each, plus the "theme in force" global getter/setter so
switching mode is one call that both halves of the UI read from.

- `Theme` (frozen dataclass): window chrome, plot chrome, availability-state colors, well-line
  colors, fault/status colors; method `shared_fill(count)`: the fill a stretch shared by `count`
  instances takes.
- `LIGHT`, `DARK`: the two concrete themes; `THEMES = {"light": LIGHT, "dark": DARK}`.
- `current()`: the theme currently in force; `use(name)`: sets and returns it.

### `palette.py`

Combines the theme's raw hues with the fixed tint ladder from `config` into the actual colors drawn:
fault-bar fill/background tinting by reach, legend entries, text-contrast and blending helpers. Reads
`theme.current()` on every call, so a theme switch repaints everything correctly.

- `tint(color, strength, base=None)`: mixes a color toward the plotting background (or `base`) by
  `strength`.
- `fault_color(fault_class)` / `bar_color(fault_class, reach)` / `background_color(fault_class,
  reach)`: a fault's hue, an instance bar's fill, and a time-series stretch's background.
- `state_color(state)`: color of a well operational-status code.
- `text_color(background)`: black or white, whichever reads better on `background`.
- `LegendEntry` (frozen dataclass) and `legend_entries(present, fault_names)`: one entry per
  distinct `(fault_class, reach)` combination present, sorted by class then decreasing tint.

### `help_text.py`

All the static text and data the help modal displays, sourced from the 3W data articles, R. E. V.
Vargas's thesis, and `dataset.ini`; almost entirely data (dicts, lists and small dataclasses), not
logic. Every entry names the document it leans on.

- `Figure(file, width, caption, credit)`: one illustration reference.
- `FaultHelp(name, what, signature, figure, illustration, notes, source)`: one fault class's
  explanation.
- `VariableHelp(where, note, position, signature_of)`: one sensor's help entry.
- Key tables: `FIGURES`, `FAULTS` (the ten fault-class explanations), `VARIABLES` (per-sensor help),
  `STATES` (the nine well operational-status descriptions), `DATASET_NOTES`,
  `AVAILABILITY_INTRO`/`AVAILABILITY_STATES`/`PLAUSIBLE_RANGE_NOTES`/`AVAILABILITY_NOTES`/
  `AVAILABILITY_SOURCES`, `MAP_INTRO`/`MAP_NOTES`/`MAP_SOURCES`, `MODEL_INTRO`/`MODEL_NOTES`/
  `MODEL_SOURCES`, `DISPERSION_INTRO`/`DISPERSION_NOTES`/`DISPERSION_SOURCES`, and `USAGE` (the
  largest table: per-page usage instructions shown in the help window's "How to" tabs).

## `algorithms/`

Numpy-only; heavier optional dependencies (`dtaidistance`, scikit-learn, UMAP) are imported lazily
inside functions and gated by `backend.extras`.

### `faults.py`

Supports the Faults page: aligning and scaling every real instance of one fault so they can be
compared across wells, which differ in magnitude, onset time and baseline (Rabelo's thesis figures
2.5/2.6).

- `onset(frame, fault, offset, align)` / `onset_from_runs(runs, fault, offset, align)`: the
  timestamp where an instance's labels first reach the alignment point (`"transient"`, `"steady"` or
  `"start"`); `None` if never reached.
- `relative_hours(index, origin)`: a timestamp index as hours relative to `origin`.
- `zscore(values)`: per-series z-score, NaNs preserved, zero-variance series mapped to zeros.
- `window_mask(hours, before, after)`: boolean mask of samples within the chosen window of the
  origin.
- `plausible_extent(values, bounds)`: min/max reading restricted to inside `bounds`, so one
  frozen/garbage sensor cannot dominate a shared axis.

### `interpolation.py`

Classifies every sample of a series as a real measurement or something the plant's historian filled
in, by detecting runs of constant first difference; see the README's [Note on
sampling](../README.md#note-on-sampling) for the rule and what it found on 3W 2.0.0.

- `sample_kinds(values, rel_tol=RELATIVE_TOLERANCE)`: codes each sample genuine/interpolated/held/
  missing.
- `genuine_mask(values, rel_tol)`: boolean convenience wrapper.
- `Sampling` (frozen dataclass): counts of valid/genuine/interpolated/held samples plus mean
  spacing between genuine ones; properties `n_filled`, `genuine_share`, `filled_share`.
- `sampling_of(kinds, step_s=1.0)`: aggregates a `sample_kinds` array into a `Sampling`.
- `describe_sampling(sampling)` / `format_spacing(seconds)`: human captions.

### `descriptors.py`

Reduces one series to the numeric descriptors used throughout the viewer: moments, quantiles,
autocorrelation time, signal-to-noise ratio, and Zhang et al.'s Gaussianity test (Melo's thesis
§4.1), with no SciPy dependency; these are the per-sensor coordinates the Instances map's
descriptor representation uses.

- `Descriptors` (frozen dataclass): `n, mean, std, skew, kurtosis, q05, q25, median, q75, q95, low,
  high, acf_half_s, snr, gauss_slope, gauss_offset, gauss_scatter, gaussian`; classmethod `empty()`.
- `describe(values, step_s=1.0)`: the top-level entry point: moments and quantiles always, plus ACF
  half-time, SNR and the Gaussianity verdict given enough samples and nonzero spread.
- `SUMMARY`: the figures the instance window's statistics table shows, as `(field, header, tooltip)`
  in column order; `summary(descriptors)` reads them off a `Descriptors` in that order and
  `format_figure(value)` writes one (four significant digits, a count whole, a dash when undefined).
- `autocorrelation(values, max_lag)`: sample autocorrelation via FFT of the demeaned series.
- `acf_half_time(values, step_s, max_lag_s)`: lag at which autocorrelation first drops to 0.5;
  infinite if it never does within the cap.
- `signal_to_noise(values)`: total variance over the variance of a 2-sample window.
- `gaussianity(values)`: Zhang et al.'s regression of sorted squared z-scores against χ²(1)
  reference quantiles; returns `(slope, offset, scatter, verdict)`.

### `cleaning.py`

Reimplements the 3W Toolkit's `CleanSignals` preprocessing rule against the profile statistics the
viewer already caches, so it costs nothing to apply live and its thresholds are adjustable in the
UI.

- `CleanRule` (frozen dataclass): `iqr_factor`, `std_floor`, `missing_share`; method `describe()`.
- `Cleaning` (frozen dataclass): per-event/per-sensor verdicts (`discarded`, `dropped`,
  `missing_shares`, fitted bounds); methods `discarded_sensors(event)`, `dropped_sensors()`,
  `kept_share(event, live)`, `why(event, sensor)`.
- `clean_signals(means, stds, missing, sensors, exempt, rule)`: fits IQR-based bounds per sensor
  across the given events and applies the mean/std/missing-share tests.
- `Cleaned` (dataclass): a `Cleaning` keyed by event identity; `clean_profiles(profiles, keys,
  joined, info, rule)` is the top-level entry point.

### `consistency.py`

Checks that the pressures of one frame read in the order the flow imposes along each line, as set
in `config` (`PRODUCTION_PRESSURES`, `SERVICE_PRESSURE_PAIRS`, `PRODUCTION_OPEN_BETWEEN`, the
tolerance and minimum share). Readings outside the plausible range and frozen sensors take no
part; a sample is compared only where no gate (choke opening, valve state) of the pair reads
closed. The instance window runs it on every block it loads, and the profile pass on every
instance and joined bar, recording per sensor `n_out_of_order` and `order_partners`, which
`Availability` reads into `out_of_order` and `order_partners` for the corner marks of the pages.

- `PressureOrder` (frozen dataclass): `line`, `upstream`, `downstream`, `gates`.
- `OrderBreak` (frozen dataclass): the pair, `compared`, `broken`, `worst` (Pa), `mask`; `share`
  and `partner_of(sensor)`.
- `orders_of(present)`: the pairs asked of a recording with those pressures measured, the
  production line neighbour by neighbour.
- `pressure_order_breaks(frame, tolerance, min_share)`: the pairs out of order.

### `embedding.py`

The largest module; powers the Instances map. Turns each instance (or joined bar) into a point via a
**representation** (standardized descriptor columns, or a DTW distance matrix within a class),
projects it to 2D via an **embedding** (PCA/classical MDS in pure numpy, or t-SNE/UMAP as optional
extras), runs **clusterings** (k-means, Gaussian mixture, agglomerative, DBSCAN) scored against
ground truth, computes **typicality** (distance to the class medoid) and runs a **novelty** audit
(one-class SVM trained on normal instances).

- `Representation` (dataclass): `keys, X, columns, distances, imputed, sensors`; property `metric`.
- `feature_matrix(profiles, keys, joined, info, shape_only, measured, min_coverage)`: builds the
  standardized descriptor representation.
- `pca(X, n_components=2)` / `classical_mds(D, n_components=2)`: the two numpy-only embeddings.
- `embed(rep, method)`: dispatches to PCA/MDS, t-SNE (`analysis` extra) or UMAP (`umap` extra).
- `embedding_available(method)`: `None` if it can run, else a message naming the missing extra.
- `cluster(rep, method, k)`: runs the chosen clustering (needs the `analysis` extra except for
  `"None"`).
- `ClusterScores` (frozen dataclass): silhouette, ARI and NMI vs. class and vs. well;
  `cluster_scores(rep, labels, classes, wells)` computes them.
- `Typicality` (frozen dataclass) and `typicality(rep, classes)`: per-point distance to its class
  medoid, ranked 0-1.
- `Novelty` (frozen dataclass) and `novelty(rep, classes, normal_class=0)`: a one-class SVM fitted on
  the normal class, flagging where the label disagrees with the model's verdict.

### `dtw.py`

Computes DTW (dynamic time warping) distances between z-scored, decimated series of one sensor within
one fault class, for the Instances map's DTW representation. Requires the `dtw` extra
(`dtaidistance`).

- `decimate(values, n_blocks=400)`: averages a series into `n_blocks` blocks (gaps interpolated),
  then z-scores it; `None` if too few valid readings or the result is flat.
- `dtw_distances(series, window_share=0.1)`: the full symmetric DTW distance matrix over a list of
  decimated series, under a Sakoe-Chiba window.

### `correlation.py`

Computes how sensors move together over a scope (all instances, one class, or one well, pooled):
exact Pearson correlation via streaming sufficient statistics, plus (via the `analysis` extra) a
nonlinear mutual-information-based coefficient (Melo's thesis §4.1.5).

- `Correlations` (frozen dataclass): the Pearson, pair-count, MI and nonlinear matrices; methods
  `matrix(coefficient)`, `present()`, `global_coefficients()` (Melo's pooled figures,
  eqs. 4.15-4.16).
- `mi_coefficient(mutual_information)`: Laarne et al.'s `sqrt(1 - exp(-2I))` normalization into a
  [0,1] coefficient.
- `CorrelationPass`: streaming accumulator; `.add(frame)` folds one instance into running sums;
  `.result(mutual_information=True)` finalizes into a `Correlations`.

### `dispersion.py`

Backs the two-sensor scatter/density view: reads an even subsample of every instance's rows (all analog sensors, label period, measurement genuineness) into one `Cloud` so changing the sensor pair, coloring or filters afterward is free.

- `InstanceRef` (frozen dataclass): identifies the instance/bar a cloud row came from.
- `period_codes(class_values, offset)`: maps `class` values to period codes
  (normal/steady/transient/unlabeled).
- `Pair` (dataclass): one sensor pair's co-valid rows after filtering; methods `dots(limit)`,
  `density(bins)`, `pearson()`.
- `Cloud` (dataclass): the full scope read; method `pair(x, y, periods, genuine_only)` extracts one
  sensor pair.
- `DispersionPass`: streaming builder; `.add(frame, ref)` clips, classifies and subsamples
  one frame; `.result()` concatenates into a `Cloud`.

### `windows.py`

One sensor of a well cut into windows of a fixed size, in software, on the four rules of the
`3w_estudo` division: exact size, one label per window (every run of constant label cut into
windows of its own), zero padding at the end of a run, and each instant once (instances walked in
chronological order, each losing the samples an earlier one covered).

- `cut(labels, size, keep, bounds)`: the core: per window, its first sample, its real samples and
  its label code, never crossing a label run, a sample left out or an instance boundary.
- `InstanceRef` (frozen dataclass): the instance a stretch came from (`position` in the well's
  table, fault folder, file, title).
- `WellSeries` (dataclass): one sensor of every instance of a well end to end, with the samples an
  earlier instance repeats; `windows(size, drop_repeated=True)` cuts it into a `Windows`.
- `Windows` (dataclass): per window its instance, number, first sample, start, label, real
  samples, share missing and the `(windows, size)` matrix of readings, zero past the real ones.
- `SeriesPass`: streaming builder; `.add(frame, ref)` takes one instance's sensor and `class`,
  `.result()` sorts them chronologically and marks the repeated samples.
- `describe_windows(values, n_valid, scale, progress, chunk)`: `descriptors.describe` over the real
  samples of every window, one array per figure of `DESCRIBED` (every field of `Descriptors` but
  the Gaussianity verdict); reports progress and can be stopped.
- `auc(scores, positive)`, `separation(scores, event)`: how well a figure tells event windows from
  normal ones, `|AUC − 0.5| · 2`.

### `spectral.py`

Provides the distribution and spectral views of a series: preparation (bounds-clamping,
gap-interpolation, detrending), Welch's power spectral density expressed against period (not
frequency) with dominant-period detection, pooled/averaged spectra across instances, the
Lomb-Scargle periodogram for irregularly-sampled measurements-only data, and label-period-stacked
histograms.

- `TransformParams` (frozen dataclass): the toolbar's transform settings (segment length, overlap,
  window, bins, clamp, genuine-only).
- `Spectrum` (frozen dataclass): `periods, power, segment_s, n_segments, explained`; methods
  `dominant()` (peak period and power share), `binned(n_bins)` (log-period-binned average).
- `Histogram` (frozen dataclass): `edges, stacks, left_out, mean, median`; property `peak`.
- `prepare(values, bounds)`: clamps out-of-bounds readings, interpolates gaps, removes mean and
  trend; `None` if too little coverage or the series is flat.
- `welch(prepared, params, fs=1.0)`: Welch's PSD estimate expressed vs. period.
- `average_spectra(spectra, n_bins=160)`: pools several instances' spectra band-by-band on a shared
  log-period grid, since concatenating raw series would turn the months between instances into a
  spurious step.
- `lomb_scargle(times_s, prepared, n_periods)`: Zechmeister & Kürster's floating-mean generalized
  Lomb-Scargle periodogram, rescaled to integrate to the variance like Welch's output.
- `histogram(values, groups, bins, bounds, edges, keys)`: counts values into bins, optionally
  stacked by a label-period code.
- `format_period(seconds)`: formats a period like a person would (`"30 s"`, `"5 min"`, `"1.5 h"`).

## `frontend/`

PySide6 and pyqtgraph. Pages generally follow the same shape: a toolbar built once, properties
reading the current control state, a `set_catalogue`/data-loading step gated by a progress dialog on
first use, a redraw routine, and `status`/`summary_changed`/`open_requested` signals the main window
listens to.

### `styling.py`

Installs one visual theme into both Qt and pyqtgraph at once, and persists/reads the user's chosen
appearance mode (`light`/`dark`/`system`) via `QSettings`.

- `saved_mode(default="system")` / `save_mode(mode)`: read/write the remembered mode.
- `resolve(mode)`: tells Qt which color scheme to use, and reads back which theme name that
  resolves to (handling `"system"` by asking Qt's style hints).
- `qt_palette(colors)`: a `Theme` turned into a fully specified `QPalette`, every role stated so
  that no widget falls back to the other mode's default. There is deliberately no application
  stylesheet: the module comment says what one cost (a two-second polish of every widget on each
  switch, slower widget creation, and a palette change that did not reach the chrome).
- `apply(mode)`: the single entry point: resolves the mode, activates it in `backend.theme`,
  configures pyqtgraph, and sets the application's palette and stylesheet.

### `loading.py`

Wraps the backend's data-reading passes with cancellable Qt progress dialogs, puts one bar over
the whole start-up, and caches loaded instance frames in memory.

- `FrameCache`: an LRU-ish cache of loaded instance DataFrames capped by total row count
  (`FRAME_CACHE_ROWS`); `get(path)` returns a cached frame or loads and inserts it; `read(path)`
  returns a cached frame or loads one without keeping it, which is how a stitched well reads its
  hundreds of instances without pushing every other window's out.
- `progress_dialog(text, parent, verb="Reading", noun="instances")`: a modal, non-auto-closing
  `QProgressDialog` plus a progress callback that returns `False` once cancelled; `verb` and `noun`
  word its count (the Windows page describes *windows*).
- `LaunchProgress(steps)`: the dialog of the start-up, with no Cancel: `step(text)` announces each
  step (the catalogue, every page built, every page laid out), `scanning(done, total, name)` is the
  callback a first launch's catalogue scan reports to, `close()` takes it down before the window
  shows. `app.build_window(args, launch=True)` drives it.
- `catalogue_with_progress` / `joined_stats_with_progress` / `pair_counts_with_progress` /
  `profiles_with_progress`: the four cached passes, each gated by a progress dialog, raising
  `dataset.ScanCancelled` on cancel; the first also takes an outside `progress` callback, which the
  launch bar passes.

### `passes.py`

Holds, for one catalogue, everything read from the data so far (the four passes above plus the
Toolkit's cleaning rule and loaded model outputs), so that a page asking for something another page
already paid for gets it instantly.

- `ModelResults` (dataclass): a `ModelOutputs` plus its per-instance agreements; methods
  `agreement(fault_class, file)`, `agreement_of_members(keys)`, `class_runs(fault_class, file,
  offset)` (model verdicts translated into the dataset's label vocabulary), `describe(fault_class,
  file)`.
- `Passes`: owns a `FrameCache` plus per-sensor-set caches. `set_wells(wells)` clears the caches on a
  new catalogue; `set_model_outputs(outputs)` scores a model against the current wells;
  `joined_stats`/`pair_counts`/`profiles` read (and cache) their pass on first ask;
  `cleaning(joined, rule, parent)` fits/caches the Toolkit's rule.

### `traces.py`

Draws one time series the way the viewer wants it read: real measurement samples as dots in full
color, the historian's interpolated/held line in the same color but faint, so measurement density is
visible at any zoom.

- `Trace` (dataclass): the line and (optional) dots pyqtgraph items; method `set_state(state)`
  restyles for `"normal"`/`"front"` (highlighted)/`"faded"`.
- `add_trace(plot, x, y, color, width, kinds=None)`: builds and adds the line plus, when `kinds`
  shows a mix of measured/filled samples, a dots overlay of the genuine measurements.

### `items.py`

Custom pyqtgraph items shared by the overview and instance windows: colored time-axis spans, instance
bars with hover/overlap highlighting, a real-calendar time axis, scroll-vs-zoom wheel handling, and
anchored note text.

- `ScrollFriendlyViewBox`: zooms on Ctrl+wheel only, lets a plain wheel pass through for page
  scrolling.
- `WheelToParent`: forwards a plain wheel event up to the enclosing scroll area.
- `SegmentsItem`: full-height colored spans along x with optional labels and hatching (recording
  blocks, label shading); another texture than the unlabeled one can be given (the zero padding of
  a window).
- `SeamsItem`: dashed vertical lines marking where a merged recording passes from one instance to
  the next; with `stitch=True`, solid lines where a stitched well's axis jumps from one recording
  to the next.
- `InstanceBarsItem`: draws all instance bars of one well timeline: fault-colored fill,
  hover/overlap highlighting, implausible-reading corner marks, the timestamp label.
- `TimeAxisItem`: labels a `TimeMap`-laid axis with real dates at two tick levels.
- `AnchoredText`: a note pinned to a fixed fraction of the plot's view rect regardless of zoom/pan.

### `spectral_items.py`

Shared building blocks for the off-time-axis views (distributions, spectra) used by both the instance
window and the faults/features pages: the transform-parameter toolbar, a log-period axis, and
histogram/spectrum drawing helpers.

- `TransformControls(QWidget)`: the toolbar row of every transform parameter; method `params()`
  returns a `TransformParams`.
- `LogPeriodAxisItem(pg.AxisItem)`: an axis of log10-seconds labeled in human units.
- `add_center_lines`, `add_peak_marker`, `PeriodMarker`, `add_stacked_bars`, `add_step_outline`,
  `add_spectrum_curve`, `shade_unresolved`, `shade_implausible`: the drawing primitives every
  histogram/spectrum plot is built from.
- `caption_for(spectrum, unit, compact=False)`: the caption naming dominant period, share and
  segment count.

### `heatmap.py`

A hand-painted (not widget-per-cell) matrix widget, the workhorse of the availability page,
drawing each cell as a stacked bar of live/frozen/absent shares with hover/click/tooltip support,
plus reusable key/swatch widgets shared across pages and the help window.

- `paint_cell(p, rect, shares, mark, filled, struck)`: the core cell-painting routine, shared by the
  widget and the swatch images.
- `swatch_image(kind, size=None)`: a standalone swatch of one cell kind, for keys and the help
  window.
- `StateKey(QWidget)` / `ColorKey(QWidget)`: labeled rows of swatches.
- `HeatmapWidget(QWidget)`: the matrix itself; signals `hovered(row, column)`, `clicked(row,
  column)`; `set_matrix(...)` (shares mode) and `set_fills(...)` (single-color mode, for
  correlations); `set_tooltip_provider(provider)`.

### `legend.py`

The clickable color key of fault/severity swatches used across pages, which doubles as a filter and
mirrors hover highlighting; it retracts to a title bar to save space and pops relevant swatches into
that title bar on hover.

- `FlowLayout(QLayout)`: a left-to-right wrapping layout Qt does not ship, with a uniform-pitch mode
  so rows line up.
- `LegendSwatch(QFrame)`: one clickable color+label entry; signal `clicked(fault_class)`.
- `LegendBar(QWidget)`: the whole key; signal `fault_clicked(fault_class)`; methods
  `set_entries(entries, fault_names)`, `highlight(keys)`, `set_selected_fault(fault_class)`.

### `help.py`

The tabbed help/reference window (fault classes, variables, well status, data availability, Instances
map, dispersion, windows, model outputs, usage) rendered as rich text with embedded figures and swatches,
shared by both the main window and instance windows.

- `Figures`: loads and caches every documented figure image, attachable to a `QTextBrowser`; method
  `html(name)`.
- `fault_page`, `variable_page`, `state_page`, `availability_help_page`, `map_help_page`,
  `model_help_page`, `dispersion_help_page`, `windows_help_page`, `usage_page`: each assembles one tab's HTML from
  `backend.help_text` content.
- `HelpWindow(QDialog)`: the `QTabWidget` of `QTextBrowser`s built from the page functions above;
  method `show_tab(title)`.
- `real_instance_counts(catalogue)`: per-fault-class real instance counts, for the class table.

### `overview.py`

The Timelines page: a grid of one interactive plot per well, each showing that well's real instances
as stacked bars colored by fault (or, optionally, by sensor availability, measurement, descriptor,
cleaning, map or model figures), with hover-to-highlight-overlaps and click-to-open.

- `describe_instance(data, index, info, availability=None)`: the full status-bar/tooltip
  description of one bar; reused by `availability_page.py`.
- `WellTimelinePlot(WheelToParent, pg.PlotWidget)`: one well's timeline; signals `hovered(index)`,
  `clicked(index)`; method `set_coloring(fills, marks)`.
- `TimelinesPage(QWidget)`: the page; signals `status`, `summary_changed`, `open_requested(WellData,
  index)`. Coloring is dispatched from `_coloring_of(data)` across every mode (fault, availability,
  measurements, descriptor, cleaning, map, model). Methods `set_catalogue`, `shown_files()`,
  `shown_source()`, `reset_views()`. The wells are drawn plain, joined or stitched
  (`_shown_wells`); the stitch box ticks and locks the join, and gives it back as it found it.
  A stitched well's plot lays its recordings back to back (`TimeMap` with no gap), whatever
  *Compress silences* says, and the colorings keyed by bar (descriptor, cleaning, map) leave its
  bar empty.

### `availability_page.py`

The Availability page: three matrices over the same bars (sensor availability, sensor pairs'
co-occurrence, sensor-to-sensor correlations), grouped by fault class, well or instances of one, drawn
via `HeatmapWidget`, with progress-dialog-gated passes for joined stats, pair counts, profiles and
correlations.

- `AvailabilityPage(QWidget)`: signals `status`, `summary_changed`, `open_requested(well, bar,
  sensor, joined)`. The toolbar offers *Matrix* (availability/pairs/correlations), *Rows*, *Over*,
  *Sensors*, *Cells*, *Available from*, *Join*, plus per-matrix controls (coefficient,
  IQR × for the Toolkit rule). `_ensure_data()` dispatches which passes the current matrix needs;
  `_refresh()` redraws whichever matrix is selected. `summary()`, `shown_files()`, `shown_source()`.

### `series_page.py`

The shared machinery behind both the Faults and Features pages: sections of instances drawn in a
chosen domain (time/distribution/spectrum) and layout (small multiples/overlaid/overall-pooled), with
normalization, transforms, and hover-to-name-a-line interaction. A subclass supplies only which
instances to draw and how they group into sections.

- `Series` (dataclass): one drawn instance: well, title, frame, onset, hours, color, label and model
  runs.
- `Section` (dataclass): one heading and its member indices.
- `merge_overlapping(series, group_of)`: reads overlapping instances of one well/group as the single
  recording they were cut from, so pooled histograms do not double-count shared samples.
- `SeriesPage(QWidget)`: the base class every page below subclasses. Signals `status`,
  `summary_changed`. Owns the shared toolbar controls (Domain, Layout, Columns, Axis, hours-around-
  onset, Normalize, transform controls), the drawing pipeline (`_replot`, `_lay_out*` for the four
  layout×domain combinations), and the subclass contract: `load_series()`, `sections()`,
  `series_headline(series)`, `pool_key(series)`, `pool_headline(members)`.

### `faults_page.py`

The Faults page: one fault chosen, every real instance of it (from every well) drawn per-feature
section, colored by well, aligned on a chosen onset. Subclasses `SeriesPage`.

- `FaultsPage(SeriesPage)`: toolbar: Fault, Alignment, the shared domain/layout controls, Features/
  Instances visibility toggles. `_instances_of(fault)` lists every real instance of the fault with its
  onset; `_well_colors()` gives one stable color per well across faults; `_rebuild_features()` offers
  every sensor, ticking `config.DEFAULT_FEATURES` by default, with the placement boxes over them. Implements `load_series()`
  (per-instance frames aligned to hours-from-onset) and `sections()` (one per ticked feature).

### `features_page.py`

The Features page: one sensor chosen, a section per fault class, comparing what that sensor reads
across classes (optionally narrowed to one well). Subclasses `SeriesPage`; the mirror image of
`faults_page.py`.

- `FeaturesPage(SeriesPage)`: toolbar: Feature, Well filter, Alignment (defaults to "start", since
  normal operation has no transient/steady onset). `_best_feature()` picks the sensor most instances
  record a *moving* reading of, so the page never opens on a flat valve state. `_rebuild_classes()`
  and `_rebuild_instances()` build the class/instance lists, ticking the earliest few of each class by
  default. `sections()` is one section per class in the grid, or one section spanning all classes
  (colored by fault hue) when overlaid.

### `map_page.py`

The Instances map: every real instance (or joined bar) as a point placed by an embedding of its
representation, colored by class, well, cluster, typicality, novelty or model agreement, with
clustering scores and a "label audit" list of instances a one-class model disagrees with.

- `MapResults` (dataclass): what the map hands to other pages (joined, representation, clusters,
  typicality, novelty); methods `cluster_color(key)`, `typicality_rank(key)`, `novelty_score(key)`.
- `Point` (dataclass): one map point: key, title, fault, well, view, index.
- `MapPage(QWidget)`: signals `status`, `summary_changed`, `open_requested(WellData, index)`,
  `results_changed(MapResults)`. `_compute()` is the master pipeline: build representation → embed →
  cluster (+ score) → typicality → novelty → redraw → fill the audit panel → emit `results_changed`.
  Toolbar controls that need a missing optional extra are greyed with the install command
  (`_grey(box, index, reason)`). The audit panel sits on a `QSplitter` beside the plot and is
  toggled by the *Label audit* action; `_sync_audit_panel()` retracts it under the DTW
  representation and restores the user's choice on leaving it.

### `dispersion_page.py`

The Dispersions page: draws two chosen sensors against each other as a point cloud over a scope
(all/one class/one well, optionally joined), with density shading, coloring modes,
measurements-only filtering, label-period filters, and hover/click on individual samples.

- `DispersionPage(QWidget)`: signals `status`, `summary_changed`,
  `open_requested(WellData, index, sensors)`, a clicked dot's bar with the plot's X and Y.
  `_load_cloud()` reads every analog sensor of every instance in scope via
  `algorithms.dispersion.DispersionPass`, progress-dialog-gated and cached by scope.
  `_redraw()` draws the density image (a log-scaled 2D histogram) and, per color group, a
  `ScatterPlotItem` of the dot cloud (subsampled to `MAX_DOTS`). `_light_instance(instance)`
  brings every drawn dot of one instance forward and fades the groups while a dot of it is
  hovered. `describe(index)`, `shown_files()`.

### `windows_page.py`

The Windows page: one sensor of a well cut into windows of a fixed size by `algorithms.windows`,
every window written with its label and shaded in its color.

- `WindowsPage(QWidget)`: signals `status`, `summary_changed`, `open_requested(WellData, index,
  sensors)` (a window's instance, on the page's sensor). `_read()` reads the sensor from every
  instance of the well through `SeriesPass`, progress-dialog-gated and cached for the session by
  well and sensor (up to `SERIES_CACHE_SAMPLES`); `_rebuild_windows()` cuts it at the size chosen;
  `_ensure_feature()` describes every window once (`windows.describe_windows`) behind a progress
  dialog, cached by well, sensor, size and rule, and hands `View` the figure chosen: one of
  `FIGURES`, the statistics table's (`descriptors.SUMMARY`) and the Timelines' descriptor
  coloring's (`profiles.DESCRIPTOR_CHOICES`). `_forget_windows()` empties the table and the
  selection before a new cut replaces the windows, and the window selected is found again in it
  by its first sample (`_place_of`, `_window_at`). `_apply_filters()` chooses the windows the boxes let through and draws
  the table, the strip (`_draw_map`, only the windows in view up to `MAX_MAP_WINDOWS`), the grid of
  thumbnails (`_draw_grid`, `PER_PAGE` a page) or the statistic (`_draw_features`, a point per window
  along the well and the distribution per label period). `_draw_detail()` draws the window
  selected and the instance it was cut from. `look(i)` is how a window's label reads and is painted
  (`LabelLook`); `cell(i, column)` and `describe(i)` what the table and the status bar say.
- `WindowsModel(QAbstractTableModel)`: the table, read straight from the page's arrays, the label
  cell in the label's color.
- `Heading(pg.LabelItem)`: a heading above one plot of a grid that clips a long text rather than
  widening its column.

### `placements.py`

- `PlacementChecks(QWidget)`: one box per placement of `config.PLACEMENTS` over the feature
  checkboxes of a panel (the instance window's and the Faults page's). `set_checks(features, noun)`
  takes the panel's boxes and writes the tooltips; a click ticks every recorded sensor of the
  placement, or clears them when all are ticked, then emits `applied`; `sync()` shows each box
  ticked, half ticked or clear as the selection stands.

### `instance_window.py`

The detail window for one bar of the overview and everything it overlaps: one stacked block per
instance/merged recording, on a shared time axis, with operational-state and class-label bands,
per-feature trace plots (shared y-axis across blocks), optional marginal-histogram and spectrum
panels, a crosshair synced across all plots, and a "join overlapping instances" toggle local to the
window.

- `Blocks(NamedTuple)`: one drawing (instances-apart or merged) of the window's group; classmethod
  `of(view, positions)`.
- `InstanceWindow(QMainWindow)`: builds both the "apart" and "joined" drawings up front so toggling
  *Join* is instant. `_adopt(joined)` switches which drawing is active and reloads frames.
  `features`, a constructor argument, is what other pages open the window on in place of the
  default (one sensor from the Availability, Faults and Features pages, X and Y from the
  Dispersions page), so the window is drawn once; `select_features(names)` changes the selection
  of a window already open. `dots_shown` is the *Measurement dots* box of the Views row: unticked, a trace is drawn
  as the plain line the file holds rather than marking the samples the historian archived. `_lay_out_stack()` is the master layout builder (coverage band, per-block header, state/
  class/model bands, per-feature trace + optional histogram/spectrum row). `_refresh_stretch()`
  recomputes histograms/spectra for the on-screen time range as the user pans and zooms.
  `set_model_results(results)` adds the model band once outputs are loaded.
  `show_statistics()` opens the statistics table on the sensors ticked, fed by `_statistics_rows`
  (the readings of every block in their shown unit, the stretch on screen or the measurements
  alone when asked); `_on_range_settled()`, after every pan and zoom, recounts it when it describes
  the stretch on screen.

### `statistics_window.py`

The statistics table an instance window opens: one row per sensor ticked of every block, one
column per figure of `descriptors.SUMMARY`.

- `StatisticsRow(NamedTuple)`: `instance, sensor, values`, the readings of one sensor of one block.
- `StatisticsWindow(QDialog)`: `source(measurements_only, on_screen_only)` gives the rows;
  `refresh()` asks it again and describes them; `text()` is the table tab separated and `copy()`
  puts it on the clipboard. The *Instance* column is hidden when one block is described.

### `window.py`

The main application window: hosts the seven pages as tabs, owns what they all share (theme control,
rescan, help, status bar, the passes, model-output loading, file-list export) and opens
`InstanceWindow`s on request.

- `MainWindow(QMainWindow)`: builds all seven pages sharing one `Passes` and `FrameCache`, and wires
  each page's `status`/`summary_changed`/`open_requested` signals. `set_model_outputs(outputs)`
  loads model outputs into `Passes` and distributes `ModelResults` to every page and open instance
  window. `set_theme_mode(mode)` persists the mode and lays the page on show out again, leaving
  the other pages stale until they are next shown (`set_catalogue(lazy=True)`, `_on_page_changed`):
  pyqtgraph bakes colors in at build time, so a theme change cannot be repainted in place, and
  laying every page out at once was most of a nine-second switch. `open_instances(data, index,
  features)` constructs and tracks an `InstanceWindow`, on the sensors a page asked for when it
  asked for any (`_open_on_feature` for one). `_export_file_list()` writes the current page's
  `shown_files()` via `backend.export.write_file_list`.
