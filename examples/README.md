# Examples of what the viewer reads and writes

Every file format the viewer exchanges with the outside ships with one example here, and every
example says where it came from: what produced it, with which command and which choice, on which
dataset version, when. A file whose provenance is not written down is not an example.

## Toolkit file lists

The 3W Toolkit loads a dataset through `ParquetDatasetConfig`
(`ThreeWToolkit.dataset.parquet_dataset`); with `split="list"` it loads exactly the files named in
`file_list`, each a path relative to the dataset root such as `4/WELL-00014_20170918230000.parquet`.
The viewer writes the instances a page has on show in that form (*Export file list…* in the main
toolbar), and `scripts/export_file_list.py` writes the same from the command line, for a choice made
by fault class and by well. Both write two files: the configuration, holding the Toolkit's own
fields and nothing else so that it loads unchanged, and `<name>.provenance.json` beside it.

Load one with:

```python
import json
from ThreeWToolkit.dataset.parquet_dataset import ParquetDataset, ParquetDatasetConfig

config = ParquetDatasetConfig(**json.load(open("examples/file_list_severe_slugging_well14.json")))
dataset = ParquetDataset(config)
```

The `path` field is the dataset root the list was written against; point it at your own copy.

| File | What it lists | Produced by |
| ---- | ------------- | ----------- |
| `file_list_severe_slugging_well14.json` | the real instances of Severe Slugging (class 4) recorded on WELL-00014 in 3W 2.0.0 | `python scripts/export_file_list.py --raw-dir ../3W/dataset --fault 4 --well 14 -o examples/file_list_severe_slugging_well14.json` |

Its `.provenance.json` carries the dataset version, the count and the timestamp of the run.

## Model outputs

The viewer draws a model's verdicts onto the data when they come in its model-output format
(`src/overlap_viewer/backend/model_outputs.py`, and the *Model outputs* tab of the help): a folder
holding `model.json` (the model's `name`, its `kind` (`detection` or `classification`), the meaning
of its `labels`, a `description` and its `provenance`) beside one `<fault_class>/<instance>.parquet`
per instance scored, each indexed by `timestamp` with an integer `label` column and an optional
float `score`. *Load model outputs…* in the main toolbar opens such a folder.

| Folder | What it holds | Produced by |
| ------ | ------------- | ----------- |
| `model_outputs/pca_control_chart_wells_1_4_6_7/` | a PCA control chart over the 319 real instances of WELL-00001, WELL-00004, WELL-00006 and WELL-00007 in 3W 2.0.0: one model per well, fitted on that well's Normal Operation instances over the analog sensors live in all of them, with the components that explain 90 % of the training variance; Hotelling's T² and Q followed along every instance of the well, a sample labeled `1` (anomalous) beyond the 99th percentile of either statistic over the training samples, the `score` the larger of the two ratios to their limits | `python scripts/pca_control_chart.py --raw-dir ../3W/dataset --well 1 --well 4 --well 6 --well 7 --fit well -o examples/model_outputs/pca_control_chart_wells_1_4_6_7` |

Its `model.json` carries the command, the parameters, the fitted limits per well and the timestamp of
the run. The script scores any choice of wells and faults the same way, per well or
(`--fit instance`) per instance on its own normal stretch; it is one producer of the format among
many, and the model is not part of the viewer.

**What the four wells say, and why the example has four of them.** Against the experts' labels:

| Well | Instances | Fitted on | Model | Normal | The well's faults |
| ---- | --------- | --------- | ----- | ------ | ----------------- |
| WELL-00001 | 132 | 93 normal instances, 2.0 M samples | 5 sensors, 1 component | 98 % | 5 % (36 flow instability) |
| WELL-00004 | 58 | 12 normal instances, 129 k samples | 6 sensors, 5 components | 98 % | 79 % (43 flow instability), 31 % (3 quick restriction) |
| WELL-00006 | 117 | 113 normal instances, 2.4 M samples | 3 sensors, 1 component | 98 % | 93 % (2 scaling in PCK), 57 % (2 abrupt increase of BSW) |
| WELL-00007 | 12 | 2 normal instances, 21.6 k samples | 10 sensors, 6 components | 98 % | 100 % (10 flow instability) |

The same method, on the same event, agrees 100 %, 79 % and 5 % on three different wells. A model
fitted on two normal instances of a well that carries ten sensors draws a tight region and calls
almost anything outside it anomalous; one fitted on 93 instances of a well that carries five draws
a region wide enough to swallow the event. The agreement figure the viewer colours and sorts by is
therefore as much about a well's normal data as about the event, which is worth knowing before
reading it anywhere in the viewer, and it is why the example covers four wells rather than the one it
started with.

**On the size.** 319 instances of one verdict and one score per second come to 6.4 MB, which took
two changes: the `timestamp` index is delta encoded (a verdict per second is mostly "one second
after the last", and written plainly that index was four fifths of every file), and the score,
a ratio to the model's limit that no reader of it needs past a decimal or two, is rounded to three
decimals. Without them the same outputs are 83 MB.

## What cannot come back from the Toolkit

The Toolkit's `ModelAssessment` exports `predictions_<timestamp>.csv` with the columns
`true_values`, `predictions`, `model_name`, `task_type` and `timestamp`: one row per window the
model scored, in the order the windows were fed. Nothing in that file says which instance, let alone
which second, a prediction belongs to, so the viewer cannot draw it back onto the data, and no
example of it is kept here. The model-output format above is what such an export would have to
carry: the instance's file and the timestamp of every label.
