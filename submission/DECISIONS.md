# Decision log

Every number below was measured; where it comes from is in DESIGN.md, EVAL.md, PERF.md or SYNC.md. Matcher numbers are on the 420 training lines.

## D-01 — Maximise net time saved, subject to a precision floor of 92.7%
**Context:** §1 cost table: correct auto +20 s, abstain −40 s, wrong auto −800 s.
**Options:** (a) maximise coverage, (b) maximise net value Z = 20x − 40y − 800z with x, y, z ≥ 0 and x + y + z = total, (c) pick a point on an ROC curve by eye.
**Chose:** (b), with the constraint x ≥ 12.67·z.
**Evidence:** auto-answering a line with probability p of being right is worth 820p − 800 against −40 for abstaining. Break-even is p = 0.9268, which in counts is x ≥ 12.67·z (760 / 60).
**Who moves it:** the project manager decides the coverage after reaching consensus with the customer's manager and the engineer; the engineer sets the point.
**Reversal trigger:** the cost table changes, e.g. a wrong match becomes cheaper to fix.

## D-02 — No LLM
**Context:** the role is AI/LLM-focused, and an LLM was my first idea.
**Options:** (a) an LLM picking from retrieved catalogue items, (b) no LLM.
**Chose:** (b).
**Evidence:** the stages already cover codes, typos and meaning; the design needs a confidence that can be compared with 92.7%, which an LLM does not give; even a local LLM needs far more computation than embeddings; an LLM can invent an item code. See DESIGN.md §3.
**Reversal trigger:** lines that need reasoning beyond matching become common, and reviewer data shows an LLM's answers clear 92.7%.

## D-03 — Correct 23 training labels, and report both label sets
**Context:** 31 lines whose text is exactly an item name disagreed with their labels.
**Options:** (a) trust the labels, (b) correct the ones that are clearly wrong in a separate file and score only on that, (c) correct them in a separate file, report results on both label sets, and use the corrected labels as the benchmark.
**Chose:** (c). 9 of the 31 were (Bulk) twins and are now sent to review. The other 22 are labelled blank although the text names one item exactly; together with `ACM-T-0114` they are corrected in `submission/data/order_lines_train_corrected.csv`. The original file is untouched.
**Evidence:** the same matcher with the same answers has 23 wrong autos, 92.6% precision and a net value of −17,120 s on the original labels, below the all-human baseline of −16,800 s; on the corrected labels it has 0 wrong autos (309 of 309) and +1,740 s. Showing both lets a reader see the label problem instead of trusting it.
**Reversal trigger:** Mindhive confirms the blank labels were intended.

## D-04 — Fuzzy: plain ratio score, success line at 70, gap and word checks
**Context:** fuzzy needs a scorer, a raw score that delivers 92.7% precision, and a way to catch look-alikes that score high.
**Options:** four rapidfuzz scorers; any cut-off from 60 to 100; a gap check, a word check, a whole-number check, a price check.
**Chose:** `fuzz.ratio`; the lowest score whose one-sided 95% lower bound on precision still clears 92.7%; the gap check (second-best within 1 point → review) and the word check (two or more items contain every word of the line → review).
**Evidence:** ratio picked the right item most often and gave the fewest high scores to lines that should be abstained; scorers that ignore extra words gave "kanto" a perfect score against any Kanto item. At 70: 67 answers, 66 right on the original labels, lower bound 93.6%. "3700mm" ties the 300mm and 370mm cable ties; "Tolsen Hex Bolt M8x50" fits four finishes. The number check caught nothing the gap check didn't and sent 7 correct answers to review. The line is not overfitted: anywhere from 60 to 80 gives the same answers, and re-chosen in 5-fold it was right on 66 of 66 unseen answers (EVAL.md §1).
**Reversal trigger:** re-measurement puts the lower bound under 92.7%, or review data shows wrong fuzzy answers a number or price would have caught.

## D-05 — Keep embeddings (MiniLM), but suggestion-only until they prove 92.7%
**Context:** README: report the marginal gain of embeddings, or delete the lane.
**Options:** (a) delete the lane, (b) auto-answer above a hand-picked similarity, (c) always suggest the top 3, and auto-answer only once labelled answers show the same 92.7% lower bound as fuzzy; and for the model, paraphrase-multilingual-MiniLM-L12-v2 or LaBSE.
**Chose:** (c), with MiniLM pinned to revision `e8f8c211`, and fuzzy's word check added to stage 3.
**Evidence:** all 54 lines that reach stage 3 are labelled blank, so the measured gain is 0: with and without the stage (`evaluate.py --no-embeddings`) every precision, coverage, net value and recall@3 number is identical. Raw similarity is misleading: MiniLM scores "Cadbury Dairy Milk 165g" 77.6 against a full cream milk. It takes 35 right answers in a row before the lower bound clears 92.7%, so on this data the stage never auto-answers. MiniLM let no line through every check, at p95 26 ms per line; LaBSE let one wrong line through ("40mm class", one of 23 matching pipes) at p95 54 ms, and the word check catches that line for both.
**Reversal trigger:** shadow-mode results (DESIGN.md §5) show embeddings above 92.7%, or below it for good, in which case delete the lane.

## D-06 — Do not patch the 9 missed chances
**Context:** on the corrected labels the matcher never answers wrongly, but 9 lines that do have a right answer were sent to a person instead of answered: the missed chances. These are not the blank-label lines of D-03 (those were answered correctly and only counted as wrong because of their labels). These 9 do not say enough to pick one item: a size with a typo ("3700mm" fits both 300mm and 370mm), a missing digit ("M6x0" fits M6x30 and M6x50), no colour, no brand, plain or Bulk, or a buyer SKU linked with only 55% confidence.
**Options:** (a) add rules that guess the item for them, (b) leave them with a person and use them in the error analysis.
**Chose:** (b).
**Evidence:** fixing all 9 would gain at most 9 × 60 = 540 s, while one wrong guess costs 760 s more than asking a human. Most of them need a guess about a size or a variant ("3700mm", "M6x0", no colour, no brand). Rules written for these 9 lines would be overfitting.
**Reversal trigger:** production review data shows the same kind of miss often enough to measure a rule's precision.

## D-07 — Regression gates
**Context:** README: what breaks the build, and how the benchmark is kept from rotting.
**Options:** gates on precision, wrong autos, cross-tenant answers, net value, p95 time per line and the tests.
**Chose:** a change is blocked when there is any cross-tenant answer, precision on auto falls below 92.7%, there are more wrong autos than in the last accepted run, or a pytest test fails. Net value and p95 time are reported but do not block. `evaluate.py` exits with code 1 on a failed gate.
**Evidence:** wrong autos have their own gate because precision can stay above 92.7% while new −800 answers appear. A simulated bad change fails all three harness gates; today's run passes.
**Reversal trigger:** a change that should have been blocked passes, or a good change is blocked by noise.

## D-08 — Extrapolate the Task 4 baseline along output groups, weighted by distinct items
**Context:** the full report cannot be run; slices must be scaled up.
**Options:** days, tenants, rows in the window, output groups (the README's four), tenant-days.
**Chose:** output groups, each weighted by its tenant-day's distinct items: about 75 hours.
**Evidence:** the same tenant and day narrowed to one channel cost about a quarter (output groups, not days or tenants); the cost per event falls from 0.176 to 0.071 s as tenants grow (not rows in the window); the cost per distinct item and output group stays at 0.16 to 0.18 s. The model predicted four unseen slices within −7% to +2%. Counting per tenant-day instead gives 21 h, 3.5 times less.
**Reversal trigger:** a different SQLite version or machine where the automatic index is not rebuilt per item.

## D-09 — Fix the report by rewriting the query only
**Context:** README: indexes cost write throughput (about 40 writes per order line at peak), materialisation costs freshness, schema changes cost a migration on a hot table. `repeat_items_prev_day` is 97% of the original's cost.
**Options:** (a) indexes, (b) a materialised summary, (c) a schema change, (d) a rewrite that reads each table once; and for the previous-day column, joining today's item list with yesterday's, or comparing every item with the previous day it appeared (`LAG`).
**Chose:** (d), with `LAG`, and one read of `match_event` feeding both the matcher's numbers and the item lists.
**Evidence:** the rewrite runs the full window in 4.3 s (8.0 s with `p95_latency_ms`), passing `check` on all 8,666 rows, with no extra cost on writes, freshness or the schema. Joining the two item lists alone took about 8.7 s (SQLite builds a lookup index over about 410,000 items); the full report went from 15.8 s (join) to 11.2 s (`LAG`) to 4.3 s (one read). Its own cost: every run reads and groups the whole of `match_event` (one tenant's page 0.5 to 1.9 s).
**Reversal trigger:** the data grows until the report no longer fits in 10 seconds. It fits today (8.0 s); measured, that happens at about 1.3 times today's volume (D-10).

## D-10 — Plan summary tables before about 1.3 times today's volume
**Context:** README: at 50 times today's volume, does the fix hold?
**Options:** (a) build summary tables kept up to date as events are written now, (b) keep the rewrite and plan the summary tables.
**Chose:** (b).
**Evidence:** measured at 1, 2, 4 and 8 times the volume, the rewrite takes about 12 to 13 s per million events in the window (7.7, 14.6, 29.6, 52.4 s). The 10-second budget breaks at about 1.3 times today's volume; 50 times would take about 6 minutes. Summary tables cost what D-09 avoided (write work, freshness, a migration), which today's volume does not need.
**Reversal trigger:** the window passes about 750,000 events, or the report gets close to 10 s.

## D-11 — Sync conflicts: apply the ERP's version, keep our edit for a person
**Context:** MAIA-844; an item edited in our UI and in the ERP between two syncs.
**Options:** (a) last writer wins, by timestamp, (b) our edit wins (what the adapter did on a 409), (c) the ERP's version is applied and our edit is kept as a conflict, (d) merge field by field.
**Chose:** (c).
**Evidence:** (a) needs two clocks to agree, and the ERP stamps +08:00 while we stamp UTC; (b) is MAIA-844. (d) needs the version both edits started from, which the store does not keep, and a wrong merge is a wrong price. With (c) neither edit is lost, and the test for defect 4 shows the ERP's "Box" survives.
**Reversal trigger:** the conflict queue grows faster than people resolve it.

## D-12 — One idempotency key per edit, and read back after the window
**Context:** MAIA-830; 504s come after the commit, and keys are honoured for 60 seconds only.
**Options:** (a) a new key per attempt (as before), (b) one key per edit (record, base version, payload), (c) (b), plus on a 409, check whether the ERP already holds our payload and adopt it.
**Chose:** (c).
**Evidence:** (b) stops the second write within 60 seconds (defect 3); the sync runs every 5 minutes, so an unconfirmed write is always retried after the window, and only the read-back stops it then (defect 6). Each has its own test, and undoing either fix fails only its own test.
**Reversal trigger:** the vendor keeps keys for longer than the sync interval.
