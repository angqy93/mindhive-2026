# Scale and rollout

500 tenants, 4 million catalogue rows, about 150,000 order lines a day, and an alias table that grows from every confirmed order.

## The first thing to break: the Task 4 report

Evidence from PERF.md section 7: the rewritten report takes about 12 to 13 seconds per million match events in its window, measured at 1, 2, 4 and 8 times the test data, and its 10-second budget breaks at about 1.3 times today's volume. The test data has about 1,000 order lines a day. At 150,000 a day, a 61-day window holds about 9 million order lines and, at about 9 candidates each, about 85 million match events: roughly 18 minutes per run, for a dashboard ops believe is live. The summary tables kept up to date as events are written (PERF.md section 7) have to exist before this volume, not after.

The matcher itself is not the first to break. Its p95 is about 20 ms per line (EVAL.md), and 150,000 lines a day is under 2 lines a second on average. Its catalogue work is per tenant: about 8,000 rows each, against 1,148 today.

## Re-indexing embeddings

MiniLM encoded the two test catalogues (1,616 items) in 6.7 seconds on one laptop, about 4 ms per item. When a tenant edits 40,000 items at 2am, re-encoding them takes about 3 minutes of one process; all 4 million rows would take about 4.5 hours. The vectors take 1.5 KB per item (384 numbers), about 6 GB for 4 million rows, so they are loaded per tenant, not all at once.

Re-indexing runs per tenant, in the background, from a queue, and the new index replaces the old one in one step when it is complete. In the meantime the tenant runs on its old index, and that is safe by design: the embedding stage never answers on its own (DECISIONS.md D-05), it only adds suggestions to lines that already go to a human. A stale index can only give a reviewer an outdated suggestion. Regex and fuzzy matching read the catalogue itself, so an edited name, barcode or disabled item takes effect as soon as the catalogue is reloaded, which is cheap.

## Stopping the alias feedback loop

An alias that auto-answers wrongly costs 800 seconds every time it fires, 20 times an abstention, and an operator mistake confirmed into the alias table would fire on every later order of that customer. So a confirmation never becomes a trusted alias by itself:

- **A new alias starts untrusted,** as an `inferred_match` below 1.0 (DESIGN.md failure mode 5): its description helps fuzzy matching, but it does not answer on its own.
- **It is trusted only after independent evidence:** confirmed on several separate orders, by more than one operator, with no return or credit note against it. A small number of confirmations is not enough to show 92.7% precision (the same lower-bound rule as fuzzy matching, DESIGN.md section 2).
- **One strike removes trust:** a return, a credit note or a reviewer correcting an auto-answer from that alias demotes it at once (DESIGN.md failure mode 5).
- **Trusted aliases are sampled:** a small share of their auto-answers still goes to review, so a wrong alias is caught by a person instead of by a customer.

## Shipping a matcher change

Both: shadow first, then canary.

1. **The harness first** (EVAL.md section 5): the change must pass the gates on the labelled lines: no cross-tenant answer, precision on auto at least 92.7%, no more wrong autos than the last accepted run, all tests green.
2. **Shadow:** the new matcher runs on live traffic next to the current one, and only the current one's answers are used. Every line where the two disagree is logged.
3. **Canary:** the new matcher answers for a few tenants, chosen across both small and large ones, before all 500.

**Deciding it worked when the truth arrives days later.** Reviewer decisions arrive the same day for every line that goes to review, so a disagreement that touches the review queue gets its answer quickly. For automatic answers, returns and credit notes arrive days later, so the canary runs for at least that long. Most lines get the same answer from both matchers, so the comparison only needs the lines where they disagree: a sample of those goes to review in the shadow phase, which gives a labelled precision for the change within days. The change is rolled out further only if that precision clears 92.7% with the same lower bound, and rolled back on the first rise in returns or credit notes for canary tenants.
