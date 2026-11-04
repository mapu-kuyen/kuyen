"""M1 — the ledger tail and the unit history are written under exclusion.

KUYEN_LEDGER_RECOVERY_HARDENING_02. The contract: `append_event` assigns `seq` and
`prev_event_hash` from the observed tail and appends; `record_revision` appends a revision
and updates `unit/STATE.json`. Both must be one indivisible operation, so two writers can
never publish the same sequence or an incompatible link.

These tests are deterministic: writers start from a common state released by a barrier,
and every write goes through the public API (`record_failed_antu`).
"""
from __future__ import annotations

import os
import threading
from pathlib import Path

import pytest

from kuyen import KuyenMemory
from kuyen.errors import StoreError

WRITERS = 6
ROUNDS = 5


def writer(memory: KuyenMemory, name: str) -> None:
    """One write operation: one ledger event plus one unit revision."""
    memory.record_failed_antu({"antu_id": f"ANTU-M1-{name}",
                               "base_version_id": None}, reason=f"concurrent writer {name}")


def chain_links(ledger: list[dict]) -> list[str]:
    return [event["prev_event_hash"] for event in ledger]


def assert_chain_is_sound(memory: KuyenMemory) -> list[dict]:
    report = memory.verify()
    assert report["ok"] is True, report["problems"]
    ledger = memory.ledger()
    assert [event["seq"] for event in ledger] == list(range(1, len(ledger) + 1))
    previous = "0" * 64
    for event in ledger:
        assert event["prev_event_hash"] == previous
        previous = event["event_hash"]
    revisions = [item["unit_revision"] for item in memory.history()]
    assert revisions == [f"R{index:04d}" for index in range(len(revisions))]
    assert len(set(revisions)) == len(revisions)
    return ledger


class TestThreads:
    """Prueba A — concurrent threads start from a common state and must not collide."""

    @pytest.mark.parametrize("round_index", range(ROUNDS))
    def test_sequences_and_links_survive_concurrent_writers(self, tmp_path: Path,
                                                            round_index: int) -> None:
        path = tmp_path / f"store-{round_index}"
        memory = KuyenMemory.create(path, leftraru_id="LR-M1", purpose="m1 threads")
        baseline = len(memory.ledger())
        barrier = threading.Barrier(WRITERS)
        failures: list[str] = []

        def run(name: str) -> None:
            try:
                own = KuyenMemory.open(path)
                barrier.wait(timeout=20)
                writer(own, name)
            except Exception as exc:  # noqa: BLE001 - a writer must not fail silently
                failures.append(f"{type(exc).__name__}: {exc}")

        threads = [threading.Thread(target=run, args=(f"{round_index}-{index}",))
                   for index in range(WRITERS)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)

        assert not any(thread.is_alive() for thread in threads)
        assert failures == [], failures
        ledger = assert_chain_is_sound(memory)
        assert len(ledger) == baseline + WRITERS
        assert len(memory.history()) == WRITERS
        assert len({event["antu_id"] for event in ledger}) == WRITERS

    def test_nested_lock_does_not_deadlock_the_same_thread(self, memory: KuyenMemory) -> None:
        """The API wraps the whole operation; primitives re-enter the same lock."""
        with memory.store.writer_lock():
            with memory.store.writer_lock():
                memory.record_failed_antu({"antu_id": "ANTU-NESTED"}, reason="nested")
        assert memory.verify()["ok"] is True
        assert [event["seq"] for event in memory.ledger()] == [1]


class TestIntegrityAfterConcurrency:
    """Prueba C — verify, then back up and restore; the restored chain is the same chain."""

    def test_backup_and_restore_preserve_the_concurrent_chain(self, tmp_path: Path) -> None:
        path = tmp_path / "store"
        memory = KuyenMemory.create(path, leftraru_id="LR-M1", purpose="m1 backup")
        barrier = threading.Barrier(4)

        def run(name: str) -> None:
            own = KuyenMemory.open(path)
            barrier.wait(timeout=20)
            writer(own, name)

        threads = [threading.Thread(target=run, args=(f"b{index}",)) for index in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)

        ledger = assert_chain_is_sound(memory)
        backup = tmp_path / "backup"
        memory.backup(backup)
        assert KuyenMemory.verify_backup(backup)["ok"] is True

        restored_path = tmp_path / "restored"
        restored = KuyenMemory.restore(backup, restored_path)
        restored_ledger = restored.ledger()

        assert [(event["seq"], event["event_hash"], event["prev_event_hash"])
                for event in restored_ledger] == [(event["seq"], event["event_hash"],
                                                   event["prev_event_hash"]) for event in ledger]
        assert restored.verify()["ok"] is True
        assert restored.verify()["ledger"]["state"] == "INTACT"
        assert [item["unit_revision"] for item in restored.history()] == \
               [item["unit_revision"] for item in memory.history()]


class TestInterruptedWrite:
    """Prueba D — a controlled interruption leaves an incomplete record, never a silent gap."""

    def test_partial_line_is_reported_and_recovered(self, memory: KuyenMemory,
                                                    monkeypatch: pytest.MonkeyPatch) -> None:
        import kuyen.lifecycle.ledger as ledger_module

        memory.record_failed_antu({"antu_id": "ANTU-BEFORE"}, reason="before the cut")
        expected_events = len(memory.ledger())
        expected_head = memory.ledger()[-1]["event_hash"]

        def interrupted_append(path, line: str) -> None:
            with open(path, "a", encoding="utf-8") as handle:
                handle.write(line[: max(1, len(line) // 3)])
                handle.flush()
                os.fsync(handle.fileno())
            raise OSError("simulated interruption while appending")

        monkeypatch.setattr(ledger_module, "append_line", interrupted_append)
        with pytest.raises(OSError):
            memory.record_failed_antu({"antu_id": "ANTU-CUT"}, reason="cut in the middle")
        monkeypatch.undo()

        state = memory.ledger_state()
        assert state["state"] == "TRUNCATED_TAIL"
        assert state["events"] == expected_events
        assert state["tail"]["parsable"] is False
        assert memory.verify()["ok"] is False
        assert memory.ledger()[-1]["event_hash"] == expected_head
        assert [item["antu_id"] for item in memory.history()] == ["ANTU-BEFORE"]

        outcome = memory.recover()
        assert outcome["ledger"]["repaired"] is True
        assert memory.ledger_state()["state"] == "INTACT"
        assert memory.verify()["ok"] is True
        assert len(memory.ledger()) == expected_events
        quarantine = list((path_of(memory) / "ledger/quarantine").glob("*.jsonl"))
        assert len(quarantine) == 1
        assert len(quarantine[0].read_bytes()) > 0

        memory.record_failed_antu({"antu_id": "ANTU-AFTER"}, reason="after recovery")
        ledger = assert_chain_is_sound(memory)
        assert ledger[-1]["antu_id"] == "ANTU-AFTER"
        assert ledger[-1]["seq"] == expected_events + 1
        assert ledger[-1]["prev_event_hash"] == expected_head


def path_of(memory: KuyenMemory) -> Path:
    return Path(memory.path)
