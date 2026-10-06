"""Task 5: checks that every test isolates its own defect (SYNC.md section 1).

Starting from the fixed adapter, each fix is undone on its own, and the sync tests are run against
that version. Only the test of the undone defect should fail.

Run from the repo root:  uv run python submission/sync/check_isolation.py
"""
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXED = (ROOT / "submission" / "sync" / "sync_adapter.py").read_text(encoding="utf-8")

# defect number -> (what undoing its fix means, old text, new text)
UNDO = {
    1: ("take full pages whole, even when they end inside a second",
        "            page = [r for r in page if r.updated_at < last_second]\n"
        "            if not page or (store.cursor and page[-1].updated_at <= store.cursor):\n"
        "                limit *= 2                        # no new whole second fits: ask for a bigger page\n"
        "                continue\n",
        "            pass\n"),
    2: ("move the cursor before the page is applied",
        "        for rec in page:\n            pulled += apply_remote(store, rec)\n        if page:\n"
        "            # Defect 2: the cursor moves only after every record of the page is saved.\n"
        "            store.set_cursor(page[-1].updated_at)\n",
        "        if page:\n            store.set_cursor(page[-1].updated_at)\n"
        "        for rec in page:\n            pulled += apply_remote(store, rec)\n"),
    3: ("a new idempotency key for every attempt",
        "                remote = erp.write(rec.external_id, rec.payload,\n"
        "                                   base_version=rec.remote_version, idempotency_key=key)\n",
        "                remote = erp.write(rec.external_id, rec.payload,\n"
        "                                   base_version=rec.remote_version, idempotency_key=key + str(_attempt))\n"),
    4: ("on a 409, write our payload over the ERP's version",
        "                    store.add_conflict(Conflict(rec.external_id, dict(rec.payload),\n"
        "                                                dict(current.payload), current.version))\n"
        "                    save_remote(store, current)\n"
        "                    break\n",
        "                    remote = erp.write(rec.external_id, rec.payload,\n"
        "                                       base_version=current.version, idempotency_key=key + 'retry')\n"),
    5: ("pull drops an unpushed local edit without keeping it",
        "            store.add_conflict(Conflict(rec.external_id, dict(local.payload), dict(rec.payload), rec.version))\n",
        "            pass\n"),
    6: ("on a 409, do not check whether our own write already landed",
        "                if current is not None and current.payload == rec.payload:\n",
        "                if False:\n"),
    7: ("read from the cursor's second onwards, not from the second before it",
        "        since = one_second_before(store.cursor) if store.cursor else None\n",
        "        since = store.cursor\n"),
}


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        for defect, (what, old, new) in UNDO.items():
            assert FIXED.count(old) == 1, f"defect {defect}: text to undo not found"
            path = Path(tmp) / f"undo_{defect}.py"
            path.write_text(FIXED.replace(old, new), encoding="utf-8")
            env = dict(os.environ, SYNC_ADAPTER=str(path))
            try:
                out = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                                      str(ROOT / "submission" / "tests" / "test_sync.py")],
                                     capture_output=True, text=True, env=env, timeout=60).stdout
                failed = re.findall(r"FAILED \S+::(\w+)", out) or ["(none)"]
            except subprocess.TimeoutExpired:
                failed = ["(the tests hang)"]
            print(f"defect {defect} undone ({what}):")
            for name in failed:
                print(f"    fails: {name}")


if __name__ == "__main__":
    main()
