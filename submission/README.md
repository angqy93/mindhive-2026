# Mindhive assessment: submission

The brief is the `README.md` at the repo root. Everything I built is in this `submission/` folder.

## What is here

| Path | What it is |
|---|---|
| `DESIGN.md` | Task 1: objective, pipeline, embeddings and LLM, failure modes, boundary |
| `DECISIONS.md` | Decision log |
| `predictions.csv` | Task 2 output for the 300 holdout lines |
| `matcher/` | Task 2 matcher (stages 0 to 3, decision step, calibration) |
| `run.py` | Builds the matcher, learns from the labelled lines, writes `predictions.csv` |
| `build_model.py` | One-time build step: puts the pinned embedding model in the local cache |
| `EVAL.md` | Task 3: harness, metrics, error analysis, label problem, regression safety |
| `evaluate.py` | Task 3 harness: scores the matcher on the labelled training lines (`uv run python submission/evaluate.py`) |
| `segments.py` | The noise groups used by the harness |
| `eval_baseline.json` | The last accepted run, used by the harness's regression gates |
| `PERF.md` | Task 4: estimated baseline, diagnosis, fix, `p95_latency_ms`, what was not fixed, trade-offs, ceiling |
| `perf/report_fast.sql` | Task 4 fix: the report rewritten, with the new `p95_latency_ms` column |
| `perf/check_p95.py` | Checks `p95_latency_ms` against a plain nearest-rank p95 computed in Python |
| `perf/slices.py` | Times slices of the original report query (one tenant, one channel, a date range, columns removed) |
| `perf/ablate.py` | Ablation of the original query: removes one column at a time and re-measures |
| `SYNC.md` | Task 5: the sync defects, fixes and invariants, the vendor contract we would ask for, what breaks at scale |
| `sync/sync_adapter.py` | Task 5 fix: the ERP sync adapter, same functions as `starter/sync/sync_adapter.py` |
| `sync/check_isolation.py` | Undoes each sync fix on its own and shows which test fails |
| `tests/` | pytest tests (including `test_sync.py`, one test per sync defect) |
| `data/order_lines_train_corrected.csv` | The training lines with 23 labels corrected (see below) |

## How to run

Needs [uv](https://docs.astral.sh/uv/). uv installs Python 3.12 and the pinned packages from `uv.lock`. From the repo root:

```bash
uv sync
```

```bash
uv run python submission/run.py
```

```bash
uv run pytest
```

```bash
uv run python submission/evaluate.py
```

`evaluate.py` is the Task 3 harness. It scores the matcher on the labelled training lines (original and corrected labels, 5-fold), prints the metrics per tenant and per noise group, the precision vs coverage curve and the time per line, and ends with the regression gates: it exits with code 1 if a gate fails. Add `--no-embeddings` to run it without the embedding stage.

`run.py` prints whether the embedding model was found, the number of auto / review / reject decisions, and the time per line (median, p95, max).

### Task 4

Build the database (about 120 MB, not committed; same seed, same database), then check the fix against the shipped reference result:

```bash
cd starter && uv run python make_perf_db.py --out ../data/perf.sqlite
```

```bash
cd starter && uv run python bench_report.py check --db ../data/perf.sqlite --sql ../submission/perf/report_fast.sql --repeat 5 --budget-s 10
```

```bash
uv run python submission/perf/check_p95.py
```

Do not run `starter/report_query.sql` over the full window: it is estimated at about 75 hours on the machine used here (PERF.md section 1). `perf/slices.py` times small slices of it instead.

### Task 5

The sync tests run with the rest (`uv run pytest`). To see each of them fail on the original adapter, and which test each fix is responsible for:

```bash
SYNC_ADAPTER=original uv run pytest submission/tests/test_sync.py
```

```bash
uv run python submission/sync/check_isolation.py
```

### Embedding model

Stage 3 uses `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`, pinned to revision `e8f8c211226b894fcb81acc59f3b34ba3efd5f42`. The matcher only loads it from the local Hugging Face cache and never calls the network. It has to be in the cache before running. This one-time build step is the only part that needs internet:

```bash
uv run python submission/build_model.py
```

If the model is not there, the matcher still runs, without stage 3: those lines keep fuzzy's decision (`no_candidate_above_floor`), and `run.py` says so.

## Assumptions and problems found in the brief and data

- **Training labels.** 22 training lines whose text is exactly an item name are labelled blank (abstain), and so is `ACM-T-0114`, whose text leaves out only "410" although Stallion sells one stainless #10 x 1" self drilling screw. I believe these are label errors. The original file is untouched. Corrected labels are in `data/order_lines_train_corrected.csv`, and that is what the matcher learns from. Task 3 reports results against both label sets.
- **Expired SKU mappings.** Every `valid_to` in `customer_sku_map.csv` is 2026-03-31 and every order is from 2026-04-01 on, so any mapping with an end date is skipped when the map is loaded. In production this would be a per-order date check.
- **Impossible dates in the Task 4 data.** The generated timestamps include days that do not exist, such as 2026-04-31 and 2026-06-31. The rewrite keeps the original query's behaviour for them exactly (PERF.md section 3).
- **"Assume a clean machine, `python3` only."** The matcher uses packages allowed by §5.2 (rapidfuzz, scikit-learn, numpy, sentence-transformers), so it needs uv (or pip) to install them.

## Status

- Task 1 (`DESIGN.md`): done.
- Task 2 (matcher, `predictions.csv`): done.
- Task 3 (`EVAL.md`, `evaluate.py`): done.
- Task 4 (`PERF.md`, `perf/report_fast.sql`): done.
- Task 5 (`SYNC.md`, `sync/sync_adapter.py`, `tests/test_sync.py`): done.
- Task 6: not done yet.

## Tool attribution

I used Claude Code (an AI coding assistant) throughout. The design, the thresholds and the trade-offs were decided by me in discussion with it. It critiqued my ideas, ran the measurements, wrote most of the code and drafted the documents from my decisions, and I reviewed each piece before it was committed.
