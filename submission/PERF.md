# The report that times out

`starter/report_query.sql` builds the "Tenant Match Health" report: one row per tenant, channel and day, 8,666 rows over 1 May to 30 June 2026. It runs against `data/perf.sqlite` (120,000 order lines, 1,119,139 match events, built with `starter/make_perf_db.py`).

All timings were taken on one Windows laptop with Python 3.12 and SQLite 3.50.4. Slices are built and timed with `submission/perf/slices.py`, which takes the original query and only narrows the dates, picks one tenant or one channel, or removes columns. Every full-column slice was compared with the same rows of `data/report_reference.json.gz`, and all of them matched.

```bash
uv run python submission/perf/slices.py --from 2026-05-14 --to 2026-05-14 --tenant T040
uv run python submission/perf/slices.py --from 2026-05-14 --to 2026-05-14 --tenant T040 --channel whatsapp
uv run python submission/perf/slices.py --from 2026-05-14 --to 2026-05-18 --tenant T001 --drop repeat_items_prev_day --repeat 3
```

## 1. Estimated baseline

### Method

The full report was not run. Slices of it were measured instead: one tenant on one day, one tenant on a few days, or one tenant on one day in one channel. A one-day slice for all 40 tenants (14 May) was stopped after 40 minutes without finishing, so whole days were too big to measure.

Each slice was timed once, except where a median of 3 runs is given. To see how much a single timing can be trusted, three slices were timed 3 more times: T040 on 14 May (28.1, 33.2 and 27.1 s, against 27.8 s the first time), the same in one channel (9.0 s three times, against 9.3 s) and T010 in one channel with `repeat_items_prev_day` only (median 22.5 s, against 26.4 s). Single timings are within about 20% of each other, much less than the differences the conclusions below rest on (4 times between one and four channels, 20 times between tenants).

To scale a slice up to the full report, it has to be multiplied by whatever the cost grows with. The README names four candidates:

| Candidate | What is counted | In the full report |
|---|---|---|
| Days | the days the report covers | 61 (1 May to 30 June) |
| Tenants | the customer companies | 40 |
| Rows in the window | the `match_event` rows (events) between 1 May and 30 June | 567,887 |
| Output groups | the rows the report produces, one per tenant, channel and day | 8,666 |

An output group is one pile of the `GROUP BY`: all order lines with the same tenant, channel and day. For example, on 14 May tenant T001 had 256 order lines, which form 4 output groups, one per channel (64 by email_pdf, 58 by portal_csv, 66 by voice_note and 68 by whatsapp), so 4 rows of the report.

**Answer: the cost follows output groups.** Every column after `lines_total` is a sub-query in the SELECT list, so SQLite runs it again for every output group, with that group's tenant, channel and day plugged in. With only one index (`match_event(line_id)`) and dates compared through `substr(created_at, 1, 10)`, each run scans the whole table (`EXPLAIN QUERY PLAN` shows a full `SCAN` in almost every sub-query), however small the group is. The measurements below show why it is not days, tenants or rows in the window, and why it is output groups.

### Not days, not tenants

If the cost followed days or tenants, one tenant on one day would cost the same whether the report shows all of its channels or only one. It does not. The same tenant on the same day, with the report narrowed to one channel (`--channel whatsapp`), costs about a quarter as much:

| Tenant, 14 May | Days | Tenants | Output groups | Time | Time per output group |
|---|---|---|---|---|---|
| T040, all channels | 1 | 1 | 3 | 27.8 s | 9.3 s |
| T040, one channel | 1 | 1 | 1 | 9.3 s | 9.3 s |
| T010, all channels (`repeat_items_prev_day` only) | 1 | 1 | 4 | 91.3 s | 22.8 s |
| T010, one channel (`repeat_items_prev_day` only) | 1 | 1 | 1 | 26.4 s | 26.4 s |
| T003, all channels (`repeat_items_prev_day` only) | 1 | 1 | 4 | 477.1 s | 119.3 s |
| T003, one channel (`repeat_items_prev_day` only) | 1 | 1 | 1 | 125.2 s | 125.2 s |

The days and tenants did not change, but the time fell together with the output groups. Tenants do not cost the same either: on the same day, T040 took 27.8 s and T001 more than 550 s (stopped).

The README does not say which two candidates give answers that differ by 4×. The closest pair in these measurements is the tenant-day (the README's tenants and days taken together) against the output group. `repeat_items_prev_day` gives the same value on every channel row of a tenant-day, so it is tempting to count it once per tenant-day (2,439 in the window). The table shows it is computed once per output group (8,666), 3.5 times as often: the full report comes to 75 h, not 21 h. The one-channel measurements are what decide between the two.

### Not rows in the window

If the cost followed the rows (events) in the window, the time per event would be the same for every tenant. `repeat_items_prev_day` was timed alone on 14 May for five tenants of different sizes:

| Tenant | Events | Distinct items | Output groups | Time | Time per event and group | Time per distinct item and group |
|---|---|---|---|---|---|---|
| T040 | 48 | 47 | 3 | 25.3 s | 0.176 s | 0.179 s |
| T010 | 144 | 132 | 4 | 91.3 s | 0.158 s | 0.173 s |
| T003 | 1,006 | 667 | 4 | 477.1 s | 0.119 s | 0.179 s |
| T002 | 1,667 | 912 | 4 | 578.3 s | 0.087 s | 0.159 s |
| T001 | 2,352 | 1,036 | 4 | 665.7 s | 0.071 s | 0.161 s |

The time per event falls by more than half as the tenant grows, so it is not the events. What stays the same is the time per distinct item and output group, 0.16 to 0.18 s. A tenant has only 1,200 items, so a big tenant repeats items more, and the cost follows the different items, not every event.

### Output groups

For the other seven columns, the time per output group stays about the same whatever the tenant's size, because each run scans the whole table:

| Slice, without `repeat_items_prev_day` | Events | Output groups | Time | Time per output group |
|---|---|---|---|---|
| T040, 14 May | 48 | 3 | 2.75 s | 0.92 s |
| T001, 14 May | 2,352 | 4 | 4.14 s | 1.03 s |
| T001, 14 to 18 May (median of 3 runs) | 11,417 | 20 | 24.11 s | 1.21 s |

On 14 May, T001 has 49 times the events of T040, but each output group costs about the same.

**Cost model:** per output group, about 0.17 s × the distinct items of its tenant-day (for `repeat_items_prev_day`), plus about 1 s for the other columns.

### Validating the model

The model was used to predict four slices it was not built from, before they were run:

| Slice | Predicted | Measured | Difference | Matches reference |
|---|---|---|---|---|
| T005, 10 June (168 items × 4 output groups) | 118 s | 119.2 s | +1% | yes |
| T025, 27 May (6 items × 2 output groups) | 4 s | 4.1 s | +2% | yes |
| T003, 20 June (748 items × 4 output groups) | 513 s | 476.2 s | −7% | yes |
| T040, 1 to 7 June (7 days, 23 output groups, 40 to 73 items a day) | 258 s | 251.6 s | −2% | yes |

The last slice checks that the model also holds when several days are added together. It also agrees with the stopped one-day run: it predicts 72 minutes for all of 14 May, and that run was still going at 40.

### The estimate

The full report is the number of output groups times the cost of one output group:

| Step | Value |
|---|---|
| Output groups in the full report | 8,666 |
| Distinct items of an output group's tenant-day, on average | 178 |
| Cost of one output group: `repeat_items_prev_day` (0.17 s × 178) | 30.2 s |
| Cost of one output group: the other columns | 1 s |
| Cost of one output group, in total | 31.2 s |
| **Full report: 8,666 output groups × 31.2 s** | **about 270,000 s, or 75 hours** |

Of the 75 hours, `repeat_items_prev_day` is 72.7 h (8,666 × 30.2 s) and the other columns 2.4 h (8,666 × 1 s). The average hides how different the output groups are: one of T001's groups (about 1,000 items) costs about 170 s, one of T040's (about 47 items) about 9 s. Adding every output group with its own item count, instead of the average, gives the same total, because the 178 is the average of exactly those counts (1,540,441 items over 8,666 output groups).

## 2. Diagnosis, ranked by cost

### Ablation

The full query was run on one slice (T040 on 14 May, 3 output groups, all columns), then again with each of the eight sub-query columns removed on its own, and once with all eight removed. The ten versions were run round-robin for 7 rounds, so a slow moment of the machine affected every version alike, and the median of the 7 runs is used. The runs of each version stayed within about 1 s of each other.

```bash
uv run python submission/perf/ablate.py --from 2026-05-14 --to 2026-05-14 --tenant T040 --rounds 7
```

| Version | Median | Saved | Share of the full query |
|---|---|---|---|
| full query | 26.76 s | | |
| without `repeat_items_prev_day` | 2.64 s | 24.11 s | 90.1% |
| without `lines_accepted` | 26.15 s | 0.61 s | 2.3% |
| without `avg_latency_ms` | 26.42 s | 0.34 s | 1.3% |
| without `max_latency_ms` | 26.45 s | 0.31 s | 1.2% |
| without `avg_accept_score` | 26.46 s | 0.30 s | 1.1% |
| without `accepted_disabled` | 26.55 s | 0.21 s | 0.8% |
| without `distinct_customers` | 26.75 s | 0.01 s | 0.0% |
| without `candidates_considered` | 26.96 s | −0.21 s | within the noise |
| without all eight (only the grouping and `lines_total` left) | 0.03 s | 26.73 s | 99.9% |

T040 is the smallest tenant. `repeat_items_prev_day` costs 0.17 s per distinct item and output group (section 1), so on a big tenant its share is even larger: alone, it takes 665.7 s of T001's 14 May, against 4.14 s for all the other columns together.

| Slice, 14 May | All columns | Without `repeat_items_prev_day` | `repeat_items_prev_day` alone |
|---|---|---|---|
| T040 (3 groups) | 27.8 s | 2.75 s | 25.3 s |
| T001 (4 groups) | more than 550 s (stopped) | 4.14 s | 665.7 s |

The seven smaller columns save between 0.6 s and nothing on this slice, close to the noise: removing `candidates_considered` even came out 0.21 s slower. As a second check of their order on a bigger tenant, they were also removed one at a time from T001 over 14 to 18 May (20 output groups, median of 3 runs), on a slice without `repeat_items_prev_day`, where their differences are larger than the noise:

| Removed (T001, 14 to 18 May, without `repeat_items_prev_day`) | Time | Saved | Saved per output group |
|---|---|---|---|
| (none) | 24.11 s | | |
| `lines_accepted` | 17.67 s | 6.44 s | 0.32 s |
| `max_latency_ms` | 18.48 s | 5.63 s | 0.28 s |
| `avg_latency_ms` | 18.91 s | 5.20 s | 0.26 s |
| `avg_accept_score` | 18.99 s | 5.12 s | 0.26 s |
| `accepted_disabled` | 19.31 s | 4.80 s | 0.24 s |
| `candidates_considered` | 22.92 s | 1.19 s | 0.06 s |
| `distinct_customers` | 24.06 s | 0.05 s | 0.00 s |
| all seven | 0.03 s | 24.08 s | 1.20 s |

Both slices give the same order.

### Ranking

| Rank | Column | Share of the full query (T040, 14 May) | Share of the estimated 75 h |
|---|---|---|---|
| 1 | `repeat_items_prev_day` | 90.1% | about 97% |
| 2 | `lines_accepted` | 2.3% | about 1% each for ranks 2 to 6 |
| 3 to 5 (tied) | `avg_latency_ms`, `max_latency_ms`, `avg_accept_score` | 1.1 to 1.3% each | |
| 6 | `accepted_disabled` | 0.8% | |
| 7 | `candidates_considered` | within the noise (0.06 s per output group on T001) | |
| 8 | `distinct_customers` | 0.0% | |

Ranks 3 to 5 differ by less than the noise, so they are counted as tied.

### What surprised us

- **`repeat_items_prev_day` dominates, and its cost follows distinct items, not events.** It is 90% of the full query even on the smallest tenant, and about 97% of the estimated report. It counts, for one tenant and day, how many different items the matcher considered (any candidate, not only the accepted answer) that it also considered the previous day. Its inner `EXISTS` looks for the item on the previous day for every event, inside a sub-query that already runs for every group, and the work done for a tenant-day is repeated on each of its channel groups.
- **Among the other seven, no single column dominates.** Five of them cost almost the same (1 to 2% each of the full query on T040, 0.24 to 0.32 s per output group on T001), because each one scans `match_event` again for every output group. What makes them expensive is not what they compute but that each one re-reads the same table for every output group. So the fix cannot be to drop or rewrite one of them: it has to change the structure, so that `match_event` is read once for all output groups. The last row of each ablation shows where the cost is: with all the sub-queries removed, the grouping alone takes 0.03 s (T040's full query: 26.76 s; T001's 20 output groups without `repeat_items_prev_day`: 24.11 s). Grouping the order lines costs nothing; running the sub-queries again for every output group costs everything.
- **`distinct_customers` costs nothing,** although it is a sub-query too. It scans `order_line` (120,000 rows), a table almost ten times smaller than `match_event` (1.1 million).
- **`candidates_considered` costs almost nothing, but `lines_accepted` is the most expensive of the seven,** although both join `match_event` with `order_line`. The plan for `candidates_considered` scans `order_line` and looks up each line's events, while `lines_accepted` scans the whole of `match_event` and looks up each event's line.
- **The savings do not add up.** On T001 without `repeat_items_prev_day`, removing the seven one at a time saves 28.4 s in total, more than the 24.1 s they cost together. In T040's full query it goes the other way: the seven save 1.6 s one at a time, but 2.6 s together. The most likely reason is that the scans of `match_event` share the same pages in memory, so removing one changes how fast the others run. The columns are not independent, so a one-at-a-time ranking of the small ones is only approximate, which is one more reason to fix the structure rather than one column.

## 3. The fix

To be written.

## 4. `p95_latency_ms`

To be written.

## 5. What was not fixed

To be written.

## 6. Trade-offs

To be written.

## 7. The honest ceiling

To be written.
