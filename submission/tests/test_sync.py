"""Task 5: one test per sync defect (SYNC.md).

By default the tests run against the fixed adapter (submission/sync/sync_adapter.py). To see each
one fail on the original, run them against starter/sync/sync_adapter.py:

    SYNC_ADAPTER=original uv run pytest submission/tests/test_sync.py

fake_erp.py is the vendor's system and is not modified. Where a test needs the ERP to time out or
the process to die at an exact moment, it uses a subclass of FakeErp that keeps every one of its
semantics and only chooses when the documented failures happen.
"""
import importlib.util
import os
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "starter" / "sync"))           # fake_erp.py

from fake_erp import ErpTimeout, FakeErp, Record  # noqa: E402

ADAPTERS = {
    "fixed": ROOT / "submission" / "sync" / "sync_adapter.py",
    "original": ROOT / "starter" / "sync" / "sync_adapter.py",
}
_choice = os.environ.get("SYNC_ADAPTER", "fixed")
_spec = importlib.util.spec_from_file_location("sync_adapter_under_test", ADAPTERS.get(_choice, Path(_choice)))
adapter = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = adapter                              # dataclasses look their module up by name
_spec.loader.exec_module(adapter)

EDIT = {"name": "item A", "price": 999.0, "uom": "Nos"}       # the local edit used by the tests


class Crash(BaseException):
    """The process is killed. BaseException, so no `except` in the adapter can swallow it."""


class ScriptedErp(FakeErp):
    """FakeErp that times out or kills the caller after chosen write calls (counted from 0), and
    honours an idempotency key for 60 seconds only, as the vendor documents."""

    def __init__(self, timeouts=(), crash_after=()):
        super().__init__(timeout_rate=0.0)
        self.timeouts, self.crash_after, self.calls, self.key_time = set(timeouts), set(crash_after), 0, {}
        self.keys = []                                          # (external_id, idempotency key) per write call

    def write(self, external_id, payload, base_version, idempotency_key=None):
        if idempotency_key in self.key_time and self.clock - self.key_time[idempotency_key] >= 60:
            self._idem.pop(idempotency_key, None)              # the 60-second window has passed
        self.key_time.setdefault(idempotency_key, self.clock)
        call, self.calls = self.calls, self.calls + 1
        self.keys.append((external_id, idempotency_key))
        rec = super().write(external_id, payload, base_version, idempotency_key)
        if call in self.crash_after:
            raise Crash(f"killed after write call {call}")
        if call in self.timeouts:
            raise ErpTimeout(f"504 after commit of {external_id}")
        return rec


@dataclass
class CrashingStore(adapter.LocalStore):
    """A store whose process is killed while saving its n-th record (counted from 1)."""
    crash_on_upsert: int = 0
    upserts: int = 0

    def upsert(self, rec):
        self.upserts += 1
        if self.upserts == self.crash_on_upsert:
            raise Crash(f"killed while saving record {self.upserts}")
        super().upsert(rec)


def add_remote(erp, external_id, second=0, payload=None):
    erp.records[external_id] = Record(external_id, payload or {"name": external_id, "price": 10.0, "uom": "Nos"},
                                      1, f"2026-08-01 00:00:{second:02d}")


def edit_locally(store, external_id):
    rec = store.records[external_id]
    rec.payload = dict(EDIT)
    rec.dirty = True


def writes_of_edit(erp, external_id):
    return sum(1 for eid, _version, payload in erp.write_log if eid == external_id and payload == EDIT)


def conflicts(store):
    return getattr(store, "conflicts", [])


# Defect 1 (MAIA-812): a page that ends inside a second skips the rest of that second.
def test_records_sharing_a_second_across_a_page_boundary_are_all_pulled():
    erp = FakeErp(timeout_rate=0.0)
    for eid in ("EXT-A", "EXT-B", "EXT-C"):
        add_remote(erp, eid, second=0)
    store = adapter.LocalStore()
    adapter.pull(erp, store, page_size=2)
    assert sorted(store.records) == ["EXT-A", "EXT-B", "EXT-C"]


# Guard for the fix of defect 1: more records in one second than fit in a page.
def test_more_records_in_one_second_than_a_page_holds():
    erp = FakeErp(timeout_rate=0.0)
    for i in range(5):
        add_remote(erp, f"EXT-{i}", second=0)
    store = adapter.LocalStore()
    adapter.pull(erp, store, page_size=2)
    assert len(store.records) == 5


# Defect 2 (latent): the cursor is saved before the page is applied.
def test_a_crash_while_applying_a_page_loses_no_records():
    erp = FakeErp(timeout_rate=0.0)
    for second, eid in enumerate(("EXT-A", "EXT-B", "EXT-C")):
        add_remote(erp, eid, second=second)
    store = CrashingStore(crash_on_upsert=2)
    with pytest.raises(Crash):
        adapter.pull(erp, store)
    store.crash_on_upsert = 0                                   # the process restarts
    adapter.pull(erp, store)
    assert sorted(store.records) == ["EXT-A", "EXT-B", "EXT-C"]


# Defect 3 (MAIA-830): every retry has a new idempotency key.
def test_a_retry_after_a_504_reuses_the_idempotency_key_and_writes_once():
    erp = ScriptedErp(timeouts={0})
    add_remote(erp, "EXT-A")
    store = adapter.LocalStore()
    adapter.pull(erp, store)
    edit_locally(store, "EXT-A")
    adapter.push(erp, store)
    keys = [key for eid, key in erp.keys if eid == "EXT-A"]
    assert len(keys) == 2 and len(set(keys)) == 1               # one retry, with the same key
    assert writes_of_edit(erp, "EXT-A") == 1


# Defect 4 (MAIA-844): on a 409 our payload is written over the newer ERP version.
def test_a_newer_erp_edit_is_not_overwritten_by_our_older_value():
    erp = ScriptedErp()
    add_remote(erp, "EXT-A")
    store = adapter.LocalStore()
    adapter.pull(erp, store)
    edit_locally(store, "EXT-A")
    erp.tick(120)
    erp.write("EXT-A", {"name": "item A", "price": 10.0, "uom": "Box"}, base_version=1)   # edited in the ERP
    adapter.push(erp, store)
    assert erp.records["EXT-A"].payload["uom"] == "Box"


# Defect 5 (latent): pull replaces an unpushed local edit when the ERP record has changed.
def test_pull_does_not_silently_drop_an_unpushed_local_edit():
    erp = ScriptedErp()
    add_remote(erp, "EXT-A")
    store = adapter.LocalStore()
    adapter.pull(erp, store)
    edit_locally(store, "EXT-A")
    erp.tick(120)
    erp.write("EXT-A", {"name": "item A", "price": 10.0, "uom": "Box"}, base_version=1)
    adapter.pull(erp, store)
    local = store.records["EXT-A"]
    kept = (local.dirty and local.payload == EDIT) or any(c.local_payload == EDIT for c in conflicts(store))
    assert kept


# Defect 6 (latent): a write that landed but was never confirmed is sent again after 60 seconds.
def test_a_write_that_landed_before_a_crash_is_adopted_not_repeated():
    erp = ScriptedErp(crash_after={0})
    add_remote(erp, "EXT-A")
    store = adapter.LocalStore()
    adapter.pull(erp, store)
    edit_locally(store, "EXT-A")
    with pytest.raises(Crash):
        adapter.push(erp, store)                                # committed in the ERP, never saved here
    erp.tick(61)                                                # restarted after the idempotency window
    adapter.push(erp, store)
    local = store.records["EXT-A"]
    assert writes_of_edit(erp, "EXT-A") == 1
    assert not local.dirty and local.remote_version == erp.records["EXT-A"].version
    assert not conflicts(store)


# Defect 7 (latent): an ERP write stamped in the cursor's own second, after the pull read it.
def test_a_remote_write_in_the_same_second_as_the_cursor_is_pulled():
    erp = FakeErp(timeout_rate=0.0)
    erp.write("EXT-A", {"name": "item A", "price": 10.0, "uom": "Nos"}, base_version=None)
    store = adapter.LocalStore()
    adapter.pull(erp, store)
    erp.write("EXT-B", {"name": "item B", "price": 11.0, "uom": "Nos"}, base_version=None)   # same second
    adapter.pull(erp, store)
    assert "EXT-B" in store.records


# End to end: the starter's run_sync.py scenario, with its three invariants.
def test_the_run_sync_scenario_holds_all_three_invariants():
    erp = FakeErp(seed=11, timeout_rate=0.25)
    erp.seed_records(60)
    store = adapter.LocalStore()
    adapter.pull(erp, store)
    for eid in ("EXT-0003", "EXT-0011", "EXT-0042"):
        rec = store.records[eid]
        rec.payload = dict(rec.payload, price=999.0)
        rec.dirty = True
    erp.tick(120)
    erp.write("EXT-0011", {"name": "item 11", "price": 55.5, "uom": "Box"}, base_version=1)
    adapter.push(erp, store)
    adapter.pull(erp, store)
    assert all(eid in store.records and store.records[eid].remote_version == r.version
               for eid, r in erp.records.items())                                          # INV1
    writes = [eid for eid, _v, payload in erp.write_log if payload.get("price") == 999.0]
    assert len(writes) == len(set(writes))                                                 # INV2
    assert erp.records["EXT-0011"].payload["uom"] == "Box"                                 # INV3
