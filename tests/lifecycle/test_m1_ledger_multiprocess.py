"""M1 Prueba B — the exclusion is effective between *processes*, not only between threads.

The store declares an advisory `flock` single-writer model, so concurrent processes are a
supported (and contested) scenario. Each worker is an independent interpreter that waits
for a shared start file and then appends one event plus one revision through the public API.
"""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

from kuyen import KuyenMemory

WORKERS = 4

WORKER = textwrap.dedent(
    '''
    import sys, time
    from pathlib import Path

    from kuyen import KuyenMemory

    store, antu_id, go_file = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
    deadline = time.time() + 30
    while not go_file.exists():
        if time.time() > deadline:
            raise SystemExit("barrier timeout")
        time.sleep(0.01)
    memory = KuyenMemory.open(store)
    memory.record_failed_antu({"antu_id": antu_id}, reason="multiprocess writer")
    print("OK", antu_id)
    '''
)


def _package_root() -> Path:
    import kuyen

    return Path(kuyen.__file__).resolve().parents[1]


def test_concurrent_processes_keep_the_chain_sound(tmp_path: Path) -> None:
    store = tmp_path / "store"
    KuyenMemory.create(store, leftraru_id="LR-M1P", purpose="m1 processes")
    script = tmp_path / "worker.py"
    script.write_text(WORKER, encoding="utf-8")
    go_file = tmp_path / "go"
    env = dict(os.environ)
    env["PYTHONPATH"] = str(_package_root())
    env["PYTHONDONTWRITEBYTECODE"] = "1"

    processes = [subprocess.Popen([sys.executable, str(script), str(store), f"ANTU-PROC-{index}",
                                   str(go_file)], env=env, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True)
                 for index in range(WORKERS)]
    go_file.write_text("go", encoding="utf-8")
    outputs = []
    for process in processes:
        out, err = process.communicate(timeout=120)
        outputs.append((process.returncode, out.strip(), err.strip()))

    assert all(code == 0 for code, _out, _err in outputs), outputs
    memory = KuyenMemory.open(store)
    report = memory.verify()
    assert report["ok"] is True, report["problems"]
    ledger = memory.ledger()
    assert len(ledger) == WORKERS
    assert [event["seq"] for event in ledger] == list(range(1, WORKERS + 1))
    previous = "0" * 64
    for event in ledger:
        assert event["prev_event_hash"] == previous
        previous = event["event_hash"]
    assert len({event["antu_id"] for event in ledger}) == WORKERS
    assert len(memory.history()) == WORKERS
    assert [item["unit_revision"] for item in memory.history()] == \
           [f"R{index:04d}" for index in range(WORKERS)]
