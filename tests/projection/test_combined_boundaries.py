"""Combined scenario across the three fronts (section 6).

Canonical writes, ledger events, unit revisions, outbox operations and projections are all
recorded in one store, then an operation is interrupted at a controlled boundary and the
whole state is recovered, backed up and restored.
"""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import threading
from pathlib import Path

import pytest

import fixtures_produc as fixtures
import kuyen.api.memory as memory_module
from kuyen import KuyenMemory, build_document
from kuyen.projection import outbox
from projection_helpers import FakeEngine

WRITERS = 4


def new_store(path: Path) -> KuyenMemory:
    memory = KuyenMemory.create(path, leftraru_id="LR-COMBINED3", purpose="combined")
    memory.import_canonical(build_document(
        fixtures.make_graph(), {fixtures.MAPU_ID: fixtures.make_mapu_text()},
        mapu_versions={fixtures.MAPU_ID: "1.0.0"},
        source_uris={fixtures.MAPU_ID: fixtures.SOURCE_URI}))
    return memory


def concurrent_writers(memory: KuyenMemory, tag: str) -> None:
    barrier = threading.Barrier(WRITERS)
    failures: list[str] = []

    def work(index: int) -> None:
        try:
            own = KuyenMemory.open(memory.path)
            barrier.wait(timeout=20)
            own.record_failed_antu({"antu_id": f"ANTU-{tag}-{index}"}, reason="concurrent")
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{type(exc).__name__}: {exc}")

    threads = [threading.Thread(target=work, args=(index,)) for index in range(WRITERS)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert not any(thread.is_alive() for thread in threads)
    assert failures == [], failures


def interrupt_a_commit(memory: KuyenMemory, tmp_path: Path,
                       monkeypatch: pytest.MonkeyPatch) -> None:
    antu = fixtures.make_antu(antu_id="ANTU-INTERRUPTED",
                              base_version_id=memory.current().version_id)
    source = tmp_path / "MAPU-INTERRUPTED.txt"
    source.write_text(antu["unit"]["content"], encoding="utf-8")
    execution = memory.execute_antu(antu, mapu_source=source)
    assert execution.status == "VALIDATED"

    def interrupted(*args, **kwargs):
        raise OSError("simulated interruption before the unit revision")

    monkeypatch.setattr(memory_module, "record_revision", interrupted)
    with pytest.raises(OSError):
        memory.commit(execution)
    monkeypatch.undo()


def test_canonical_ledger_history_outbox_and_projections_stay_coherent(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    memory = new_store(tmp_path / "store")

    # 1-3 concurrent canonical writes: ledger events and unit revisions
    concurrent_writers(memory, "first")

    # 4-5 an interrupted commit: the version is published, its revision is not
    interrupt_a_commit(memory, tmp_path, monkeypatch)
    interrupted = KuyenMemory.open(memory.path)
    published = interrupted.current()
    assert published.version_id in interrupted.pending()["unreconciled"]
    assert interrupted.verify()["ok"] is False

    # 5b an interrupted projection: a runner died holding the operation
    operation = [item for item in outbox.list_operations(memory.store)
                 if item["version_id"] == published.version_id][0]
    outbox.update(memory.store, operation["operation_key"], status="IN_PROGRESS")

    # 6 recovery: ledger, projections and unit history
    recovered = memory.recover()
    assert operation["operation_key"] in recovered["projections"]["released"]
    assert recovered["unit_history"]["recorded"] == [published.version_id]
    after_recovery = KuyenMemory.open(memory.path)
    assert after_recovery.verify()["ok"] is True
    assert after_recovery.pending()["unreconciled"] == []

    # 7 projections for every published version, then new canonical operations
    engine = FakeEngine(delay=0.0)
    first_projection = after_recovery.project(client=engine, openviking_version="fake-1.0")
    assert first_projection["skipped"] == []
    concurrent_writers(memory, "second")

    # 8-9 the ledger is sound before the backup
    memory = KuyenMemory.open(memory.path)
    ledger = memory.ledger()
    assert [event["seq"] for event in ledger] == list(range(1, len(ledger) + 1))
    previous = "0" * 64
    for event in ledger:
        assert event["prev_event_hash"] == previous
        previous = event["event_hash"]
    assert memory.verify()["ok"] is True

    # 10 backup and restore elsewhere
    backup = tmp_path / "backup"
    memory.backup(backup)
    assert KuyenMemory.verify_backup(backup)["ok"] is True
    restored = KuyenMemory.restore(backup, tmp_path / "restored")

    # 11 canonical state, history and projection relations are coherent
    assert restored.current().to_dict() == memory.current().to_dict()
    assert [version.version_id for version in restored.versions()] == \
           [version.version_id for version in memory.versions()]
    assert restored.ledger() == ledger
    assert restored.history() == memory.history()
    assert restored.verify()["ok"] is True
    assert restored.pending()["unreconciled"] == []
    assert [entry["projection_id"] for entry in restored.projections()] == \
           [entry["projection_id"] for entry in memory.projections()]
    assert outbox.stats(restored.store) == outbox.stats(memory.store)
    assert all(item["status"] == "DONE" for item in outbox.list_operations(restored.store)
               if item["version_id"] == published.version_id)

    reconciliation = restored.reconcile()
    current_row = [row for row in reconciliation["rows"] if row["is_current"]][0]
    assert "PROJECTION_PENDING" not in current_row["states"]
    assert "PROJECTION_MISSING" not in current_row["states"]


def test_two_processes_project_the_same_operation_once(tmp_path: Path) -> None:
    memory = new_store(tmp_path / "store")
    script = tmp_path / "projector.py"
    script.write_text(textwrap.dedent(
        '''
        import sys, time
        from pathlib import Path

        sys.path.insert(0, sys.argv[1])
        from kuyen import KuyenMemory

        class Engine:
            class Response:
                def __init__(self, ok, result=None):
                    self.ok, self.result, self.error_message = ok, result, None
            def mkdir(self, uri):
                return self.Response(True)
            def write(self, uri, text):
                time.sleep(0.02)
                return self.Response(True)
            def read(self, uri):
                return self.Response(True, "x")

        store, go = Path(sys.argv[2]), Path(sys.argv[3])
        deadline = time.time() + 30
        while not go.exists():
            if time.time() > deadline:
                raise SystemExit("barrier timeout")
            time.sleep(0.01)
        result = KuyenMemory.open(store).project(client=Engine(), openviking_version="proc")
        print(len(result["projections"]), len(result["skipped"]))
        '''), encoding="utf-8")
    go = tmp_path / "go"
    package_root = str(Path(__file__).resolve().parents[2] / "src")
    processes = [subprocess.Popen([sys.executable, str(script), package_root, str(memory.path), str(go)],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                 for _ in range(2)]
    go.write_text("go", encoding="utf-8")
    outputs = []
    for process in processes:
        out, err = process.communicate(timeout=180)
        outputs.append((process.returncode, out.strip(), err.strip()))

    assert all(code == 0 for code, _out, _err in outputs), outputs
    counted = [tuple(int(value) for value in out.split()) for _code, out, _err in outputs]
    assert sum(projected for projected, _skipped in counted) == 1, counted
    assert sum(skipped for _projected, skipped in counted) == 1, counted

    reopened = KuyenMemory.open(memory.path)
    assert len(reopened.projections()) == 1
    assert len([event for event in reopened.ledger()
                if event["event_type"] == "PROJECTION_COMPLETED"]) == 1
    assert len(outbox.list_operations(reopened.store)[0]["attempts"]) == 1
    assert outbox.list_operations(reopened.store)[0]["status"] == "DONE"
