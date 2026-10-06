# The sync that double-wrote

`starter/sync/sync_adapter.py` is a two-way sync between our item store and the ERP. The fixed version is `submission/sync/sync_adapter.py`, with the same functions and records. The tests are in `submission/tests/test_sync.py`. `starter/sync/fake_erp.py`, the vendor's system, is not modified.

```bash
uv run pytest submission/tests/test_sync.py
```

```bash
SYNC_ADAPTER=original uv run pytest submission/tests/test_sync.py
```

The first command runs the tests against the fixed adapter: all 9 pass. The second runs the same tests against the original: all 9 fail. The starter's `run_sync.py` reproduces all three tickets on the original: `EXT-0050` never arrives (MAIA-812), `EXT-0042` is written twice (MAIA-830), and `EXT-0011`'s ERP edit to "Box" is overwritten (MAIA-844).

Where a test needs the ERP to time out, or the process to be killed, at an exact moment, it uses a subclass of `FakeErp` that keeps all of its semantics and only chooses when the documented failures happen. It also honours an idempotency key for 60 seconds only, as the vendor documents; the fake itself keeps keys forever.

## 1. Defects

Seven defects, three of them behind the tickets.

| # | Ticket | Mechanism | Test |
|---|---|---|---|
| 1 | MAIA-812 | The cursor asks for changes after the last timestamp of a page, at second resolution. When a page ends partway through a second, the rest of that second is never read. | `test_records_sharing_a_second_across_a_page_boundary_are_all_pulled` |
| 2 | latent | The cursor is saved before the page's records are. A crash in between moves the cursor past records that were never saved. | `test_a_crash_while_applying_a_page_loses_no_records` |
| 3 | MAIA-830 | The idempotency key includes the attempt number and the current time, so every retry has a new key. After a 504 that came after the commit, the retry is a second write. | `test_a_retry_after_a_504_reuses_the_idempotency_key_and_writes_once` |
| 4 | MAIA-844 | On a 409, the adapter reads the current version and writes our payload over it. A newer ERP edit is overwritten by our older value. | `test_a_newer_erp_edit_is_not_overwritten_by_our_older_value` |
| 5 | latent | Pull decides whether to keep an unsent local edit by comparing our timestamp with the ERP's: two clocks, two time zones (UTC and +08:00), and a UI edit does not even update our timestamp. When the ERP record has changed, the local edit is replaced and lost without a trace. | `test_pull_does_not_silently_drop_an_unpushed_local_edit` |
| 6 | latent, and MAIA-830 | A write that landed but was never confirmed (every attempt got a 504, or the process died right after the commit) is still dirty on the next run. With the sync every 5 minutes, that run is always after the 60-second idempotency window, so the write is sent again (and, through defect 4, over the ERP's version). | `test_a_write_that_landed_before_a_crash_is_adopted_not_repeated` |
| 7 | latent, and MAIA-812 | An ERP write stamped in the same second as the cursor, after the pull read that second, is never read: the next pull asks for changes after that second. | `test_a_remote_write_in_the_same_second_as_the_cursor_is_pulled` |

A further test checks the fix for defect 1 when more records share one second than fit in a page (`test_more_records_in_one_second_than_a_page_holds`), and one test runs the starter's `run_sync.py` scenario and checks its three invariants (`test_the_run_sync_scenario_holds_all_three_invariants`).

**One test per defect.** `submission/sync/check_isolation.py` undoes each fix on its own, starting from the fixed adapter, and runs the tests:

| Fix undone | Tests that fail |
|---|---|
| 2 | only defect 2's |
| 3 | only defect 3's |
| 4 | defect 4's, and the `run_sync` scenario (which contains MAIA-844) |
| 5 | only defect 5's |
| 6 | only defect 6's |
| 7 | only defect 7's |
| 1 | the tests hang |

Fixes 1 and 7 depend on each other. Fix 7 re-reads the cursor's second on every pull; that is only safe because fix 1 never leaves the cursor partway through a second. Without fix 1, a pull re-reads the same full page forever. The two have to ship together.

Defect 3's test checks the key itself, not only the number of writes. Fix 6 alone also stops the second write (the retry gets a 409, sees our payload already in the ERP and adopts it), so a test of the write count alone would pass without fix 3.

### When the latent defects would surface

- **Defect 2:** the process is killed (a deploy, an out-of-memory kill, a node restart) after the cursor is saved and before the page's records are. Those records then never arrive until someone edits them in the ERP, which looks exactly like MAIA-812.
- **Defect 5:** the same item is edited in our UI and in the ERP between two syncs, which with a 5-minute schedule only needs two people working on one item in the same few minutes. Our edit disappears silently. There is no ticket yet because a lost edit leaves nothing behind to notice.
- **Defect 6:** a write gets a 504 on all three attempts, or the process dies between the ERP's commit and our save. The next run, 5 minutes later, sends it again. At a 504 rate like the fake's (15% to 25%), three 504s in a row happen on about 0.3% to 1.6% of writes.
- **Defect 7:** an ERP user or job writes during a pull, in the same second as the last record the pull read. The busier the tenant, the more often it happens.

## 2. Fixes and the invariants they restore

| # | Fix | Invariant |
|---|---|---|
| 1 | From a full page, only the seconds it contains completely are applied; the last second is left for the next page. If one second holds more records than a page, the page size is doubled. | The cursor only ever points at a second that has been read completely. |
| 2 | The cursor is saved after every record of the page is saved. | The cursor never points past a record that has not been saved locally. |
| 3 | The idempotency key is the record, the base version and the payload: the same on every attempt and every run of one edit. | One logical edit is one idempotency key. |
| 4 | On a 409 with a payload that is not ours, nothing is written. The ERP's version is applied locally and our edit is kept as a conflict for a person to resolve. | We only write on top of the version our edit was based on. |
| 5 | Pull compares versions, not timestamps. If the ERP's version is newer than the one our unsent edit was based on, the ERP's version is applied and our edit is kept as a conflict. | An unsent local edit is never discarded without being kept. |
| 6 | On a 409, the adapter first checks whether the ERP already holds our payload. If it does, our earlier write landed: it is adopted, not sent again. Pull does the same when it meets our own landed edit. | A write that has already landed is recognised and adopted, never repeated. |
| 7 | Every pull starts one second before the cursor, so the cursor's own second is read again. Records already held at that version are skipped. | Every ERP change at or after the cursor's second is read, including ones stamped in that second after it was read. |

Two smaller changes came with these. `updated_at_utc` now holds UTC, converted from the ERP's +08:00, instead of the ERP's local time under a UTC name. And re-reading is harmless: a record is only applied when its version is newer than the one held locally.

**Crash safety.** With these fixes, the process can be killed at any point and the next run repairs the state. A crash during a pull leaves the cursor before the page, so the page is read again and records already saved are skipped by version. A crash during a push, after the ERP's commit and before our save, is recognised by fix 6. One gap remains in this in-memory store: a crash between recording a conflict and saving the ERP's version would record the same conflict twice on the next run. In Postgres, the page's records and the cursor, and a conflict and its record, would each be written in one transaction.

## 3. The contract we would ask the vendor for

In priority order:

1. **A change feed with a unique, increasing cursor:** a sequence number, or (updated_at, external_id) to break ties. Defects 1 and 7 come from ties on a second-resolution timestamp.
2. **Idempotency keys kept for at least a day, returning the original response.** The 60-second window is shorter than our 5-minute schedule, so a retry after any unconfirmed write is a new write (defect 6).
3. **A 409 that returns the current version and payload, and per-record results for batch writes.** Today a conflict costs another read, and a failed batch says nothing about which records landed.
4. **Timestamps with an offset, or in UTC.**
5. **Deletions in the change feed.** A record deleted in the ERP is never seen by the sync today.

**Staying correct while they say no:** read whole seconds only and re-read the cursor's second, deduplicating by version (fixes 1 and 7); use one idempotency key per edit, and after the window, read the record back and recognise our own payload (fixes 3 and 6); decide conflicts by version, never by comparing clocks (fixes 4 and 5); and never write over a version we have not seen.

## 4. What breaks at scale

The sync runs per tenant every 5 minutes for 500 tenants: about 100 runs a minute against the ERP. These are expectations, not measurements: the fake ERP has no latency to measure.

- **First to fall over: a tenant's run outlasting its 5-minute slot.** Push writes one record at a time, with up to 3 attempts each, and a bulk edit in the ERP (an import stamping thousands of records within a few seconds) makes pull double its page size until a whole second fits. A slow run then overlaps the next one for the same tenant. Two runs at once push the same dirty records and move the same cursor, so a per-tenant lock (a lease that expires) has to come before anything else.
- **The ERP's rate limits,** shared by 500 tenants, and its 504 rate rising under load, which multiplies attempts.
- **Unresolved conflicts piling up,** because nobody owns the queue.

**Knowing before a customer does:**

- **Lag per tenant:** the time between now and the ERP time of the cursor. Alert when it passes two intervals (10 minutes).
- **Run time per tenant against the 5-minute slot,** and any run that starts while the previous one still holds the lock.
- **504 and 409 rates,** and the number of writes adopted by fix 6, which counts how often a confirmation was lost.
- **The size and age of the conflict queue.**
- **A nightly drift check:** compare every record's version in the ERP with ours for each tenant. Any missing record or version difference is a lost change of the MAIA-812 kind, found before anyone notices it.
