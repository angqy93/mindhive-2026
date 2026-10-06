#!/usr/bin/env python3
"""Two-way sync between our local item store and the ERP (starter/sync/fake_erp.py), fixed.

Same functions and records as starter/sync/sync_adapter.py. Each fix is marked with the defect it
closes; SYNC.md lists the defects, the invariant each fix restores, and the test for each.

Run with starter/sync on the import path (fake_erp.py lives there and is not modified).
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from fake_erp import ErpConflict, ErpTimeout, FakeErp, Record

ERP_FORMAT = "%Y-%m-%d %H:%M:%S"
ERP_UTC_OFFSET = timedelta(hours=8)          # the ERP stamps updated_at in its local zone, +08:00


@dataclass
class LocalRecord:
    external_id: str
    payload: dict
    remote_version: int
    updated_at_utc: str          # "YYYY-MM-DD HH:MM:SS", UTC
    dirty: bool = False


@dataclass
class Conflict:
    """A local edit that met a different ERP edit. Neither is lost: the ERP's is applied, ours is kept here."""
    external_id: str
    local_payload: dict
    remote_payload: dict
    remote_version: int


@dataclass
class LocalStore:
    """Stands in for our Postgres tables. Committed writes only."""
    records: dict = field(default_factory=dict)
    cursor: str | None = None
    applied_log: list = field(default_factory=list)
    conflicts: list = field(default_factory=list)

    def upsert(self, rec: LocalRecord) -> None:
        self.records[rec.external_id] = rec
        self.applied_log.append((rec.external_id, rec.remote_version))

    def set_cursor(self, cursor: str) -> None:
        self.cursor = cursor

    def add_conflict(self, conflict: Conflict) -> None:
        self.conflicts.append(conflict)


def now_utc() -> str:
    return time.strftime(ERP_FORMAT, time.gmtime())


def erp_time_to_utc(erp_time: str) -> str:
    """The ERP's local time (+08:00, no offset written) as UTC."""
    return (datetime.strptime(erp_time, ERP_FORMAT) - ERP_UTC_OFFSET).strftime(ERP_FORMAT)


def one_second_before(erp_time: str) -> str:
    return (datetime.strptime(erp_time, ERP_FORMAT) - timedelta(seconds=1)).strftime(ERP_FORMAT)


def idempotency_key(external_id: str, payload: dict, base_version: int) -> str:
    # Defect 3: the key is the same for every attempt and every run of one logical edit (this
    # record, from this base version, to this payload), so a retry after a 504 is recognised.
    blob = json.dumps({"id": external_id, "payload": payload, "base": base_version}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:32]


def save_remote(store: LocalStore, rec: Record) -> None:
    store.upsert(LocalRecord(
        external_id=rec.external_id,
        payload=dict(rec.payload),
        remote_version=rec.version,
        updated_at_utc=erp_time_to_utc(rec.updated_at),
        dirty=False,
    ))


def apply_remote(store: LocalStore, rec: Record) -> int:
    """Applies one ERP record to the local store. Returns 1 if anything changed locally."""
    local = store.records.get(rec.external_id)
    if local and rec.version <= local.remote_version:
        return 0                                  # already have it (a re-read second, or our own write)
    if local and local.dirty:
        # Defect 5: decide by version, not by comparing two clocks. The ERP moved past the version
        # our unsent edit was based on.
        if rec.payload == local.payload:
            pass                                  # it is our own edit, landed earlier (defect 6)
        else:
            store.add_conflict(Conflict(rec.external_id, dict(local.payload), dict(rec.payload), rec.version))
    save_remote(store, rec)
    return 1


def pull(erp: FakeErp, store: LocalStore, page_size: int = 50) -> int:
    """Pull remote changes since the stored cursor into the local store."""
    pulled = 0
    limit = page_size
    while True:
        # Defect 7: re-read the cursor's own second; a write can land in it after we read it.
        since = one_second_before(store.cursor) if store.cursor else None
        page = erp.list_changes(since=since, limit=limit)
        full = len(page) == limit
        if full:
            # Defect 1: the last second of a full page may continue on the next page, so only
            # whole seconds are taken from it.
            last_second = page[-1].updated_at
            page = [r for r in page if r.updated_at < last_second]
            if not page or (store.cursor and page[-1].updated_at <= store.cursor):
                limit *= 2                        # no new whole second fits: ask for a bigger page
                continue
        for rec in page:
            pulled += apply_remote(store, rec)
        if page:
            # Defect 2: the cursor moves only after every record of the page is saved.
            store.set_cursor(page[-1].updated_at)
        if not full:
            return pulled
        limit = page_size


def push(erp: FakeErp, store: LocalStore, max_attempts: int = 3) -> int:
    """Push locally-dirty records to the ERP."""
    pushed = 0
    for rec in list(store.records.values()):
        if not rec.dirty:
            continue
        key = idempotency_key(rec.external_id, rec.payload, rec.remote_version)
        for _attempt in range(max_attempts):
            try:
                remote = erp.write(rec.external_id, rec.payload,
                                   base_version=rec.remote_version, idempotency_key=key)
            except ErpTimeout:
                continue                          # may or may not have landed; the same key covers both
            except ErpConflict:
                current = erp.get(rec.external_id)
                if current is not None and current.payload == rec.payload:
                    # Defect 6: our own earlier write landed (a 504 after commit, or a crash before we
                    # saved it) and the idempotency window has passed. Adopt it; do not write again.
                    remote = current
                else:
                    # Defect 4: someone else changed the record. Never write over a version we have
                    # not seen: apply theirs, keep ours as a conflict for a person to resolve.
                    store.add_conflict(Conflict(rec.external_id, dict(rec.payload),
                                                dict(current.payload), current.version))
                    save_remote(store, current)
                    break
            save_remote(store, remote)
            pushed += 1
            break
        # if every attempt timed out the record stays dirty; the same key (or defect 6's check)
        # makes the next run safe
    return pushed


def sync(erp: FakeErp, store: LocalStore) -> dict:
    return {"pulled": pull(erp, store), "pushed": push(erp, store)}
