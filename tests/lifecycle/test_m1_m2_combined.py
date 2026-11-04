"""Combined M1 + M2 — concurrency, an interrupted write and recovery in one history.

KUYEN_LEDGER_RECOVERY_HARDENING_02, section 7: the two defects are not independent, so the
chain must survive concurrent writers, a cut in the middle of an append and a recovery,
keeping its identity, its sequence and its provenance.
"""
from __future__ import annotations

import os
import threading
from pathlib import Path

import pytest

from kuyen import KuyenMemory

WRITERS = 4


def run_concurrent(memory: KuyenMemory, tag: str) -> None:
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


def cut_the_tail(memory: KuyenMemory, monkeypatch: pytest.MonkeyPatch) -> None:
    import kuyen.lifecycle.ledger as ledger_module

    def interrupted(path, line: str) -> None:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(line[: max(1, len(line) // 2)])
            handle.flush()
            os.fsync(handle.fileno())
        raise OSError("simulated interruption")

    monkeypatch.setattr(ledger_module, "append_line", interrupted)
    with pytest.raises(OSError):
        memory.record_failed_antu({"antu_id": "ANTU-CUT"}, reason="cut")
    monkeypatch.undo()


def assert_sound(memory: KuyenMemory) -> list[dict]:
    report = memory.verify()
    assert report["ok"] is True, report["problems"]
    ledger = memory.ledger()
    assert [event["seq"] for event in ledger] == list(range(1, len(ledger) + 1))
    previous = "0" * 64
    for event in ledger:
        assert event["prev_event_hash"] == previous
        previous = event["event_hash"]
        assert event["seq"] == event["seq"]
    return ledger


def test_concurrency_then_interruption_then_recovery(tmp_path: Path,
                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    memory = KuyenMemory.create(tmp_path / "store", leftraru_id="LR-COMBINED", purpose="combined")
    initial = memory.current()
    assert initial is None

    run_concurrent(memory, "first")
    before_cut = assert_sound(memory)
    assert len(before_cut) == WRITERS

    cut_the_tail(memory, monkeypatch)
    assert memory.ledger_state()["state"] == "TRUNCATED_TAIL"
    assert memory.verify()["ok"] is False
    assert memory.ledger() == before_cut, "the valid prefix must stay readable and unchanged"

    recovery = memory.recover()
    assert recovery["ledger"]["repaired"] is True
    assert memory.ledger() == before_cut
    assert memory.verify()["ok"] is True

    run_concurrent(memory, "second")
    after_second = assert_sound(memory)
    assert len(after_second) == 2 * WRITERS
    assert {event["antu_id"] for event in before_cut}.issubset({event["antu_id"] for event in after_second})

    backup = tmp_path / "backup"
    memory.backup(backup)
    restored = KuyenMemory.restore(backup, tmp_path / "restored")
    assert_sound(restored)
    assert [(event["seq"], event["event_hash"]) for event in restored.ledger()] == \
           [(event["seq"], event["event_hash"]) for event in after_second]
    assert restored.verify()["ledger"]["recovery"]["repaired"] is True

    # the backup above is itself an audited event (BACKUP_CREATED), so the next sequence
    # number is whatever the ledger holds now, plus one
    baseline = len(memory.ledger())
    memory.record_failed_antu({"antu_id": "ANTU-FINAL"}, reason="after everything")
    final = assert_sound(memory)
    assert final[-1]["antu_id"] == "ANTU-FINAL"
    assert final[-1]["seq"] == baseline + 1
    assert len(final) == baseline + 1

    snapshot = sorted(path.name for path in (Path(memory.path) / "ledger/recovery").glob("*.json"))
    second_recovery = memory.recover()
    assert second_recovery["ledger"]["repaired"] is False
    assert sorted(path.name for path in (Path(memory.path) / "ledger/recovery").glob("*.json")) == snapshot
    assert memory.ledger() == final
    assert len({event["event_hash"] for event in final}) == len(final)


def test_recovery_between_concurrent_rounds_keeps_history_contiguous(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    memory = KuyenMemory.create(tmp_path / "store2", leftraru_id="LR-COMBINED2")
    run_concurrent(memory, "a")
    cut_the_tail(memory, monkeypatch)
    memory.recover()
    run_concurrent(memory, "b")

    ledger = assert_sound(memory)
    assert len(ledger) == 2 * WRITERS
    revisions = [item["unit_revision"] for item in memory.history()]
    assert revisions == [f"R{index:04d}" for index in range(len(revisions))]
    assert len(set(revisions)) == len(revisions)
