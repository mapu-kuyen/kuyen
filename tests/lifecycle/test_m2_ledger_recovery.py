"""M2 — a damaged ledger is classified, never guessed, and only a final truncation is repaired.

Contract (KUYEN_LEDGER_RECOVERY_HARDENING_02):
  * a final incomplete record does not block reads or recovery, but it is reported;
  * corruption in the middle fails closed and is never auto-repaired;
  * repairing preserves the original bytes in `ledger/quarantine/`, records the operation in
    `ledger/recovery/`, never discards valid events and is idempotent.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from kuyen import KuyenMemory
from kuyen.errors import StoreError


def seed(memory: KuyenMemory, count: int = 3) -> list[dict]:
    for index in range(count):
        memory.record_failed_antu({"antu_id": f"ANTU-SEED-{index}"}, reason="seed")
    return memory.ledger()


def truncate_tail(memory: KuyenMemory, payload: str = '{"schema_name": "KUYEN_ANTU_EVENT", "seq": 99') -> Path:
    path = Path(memory.path) / "ledger/antu.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(payload)
        handle.flush()
    return path


def corrupt_middle(memory: KuyenMemory, line_number: int = 2) -> Path:
    path = Path(memory.path) / "ledger/antu.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    lines[line_number - 1] = "{not-json"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


class TestTruncatedTail:
    """Pruebas A, C and D — classified, readable and recoverable."""

    def test_classification_reports_the_incomplete_record(self, memory: KuyenMemory) -> None:
        ledger = seed(memory)
        truncate_tail(memory)

        state = memory.ledger_state()
        assert state["state"] == "TRUNCATED_TAIL"
        assert state["events"] == len(ledger)
        assert state["tail"]["parsable"] is False
        assert state["tail"]["bytes"] > 0
        assert state["problems"] == []

        report = memory.verify()
        assert report["ok"] is False
        assert report["ledger"]["state"] == "TRUNCATED_TAIL"
        assert any("incomplete record" in problem for problem in report["problems"])

    def test_queries_still_work_without_claiming_integrity(self, live_memory: KuyenMemory) -> None:
        ledger = seed(live_memory)
        truncate_tail(live_memory)

        assert live_memory.ledger() == ledger
        assert live_memory.pending()["incomplete"] == []
        assert live_memory.history() != []
        assert live_memory.current() is not None
        assert live_memory.graph()["entities"]
        assert live_memory.status()["integrity"]["ok"] is False

    def test_recover_repairs_and_preserves_the_original_bytes(self, memory: KuyenMemory) -> None:
        ledger = seed(memory)
        path = truncate_tail(memory)
        damaged_bytes = path.read_bytes()

        outcome = memory.recover()

        assert outcome["ledger"]["repaired"] is True
        assert outcome["ledger"]["action"] == "DROPPED_INCOMPLETE_RECORD"
        assert memory.ledger_state()["state"] == "INTACT"
        assert memory.ledger() == ledger
        assert memory.verify()["ok"] is True

        quarantine = sorted((Path(memory.path) / "ledger/quarantine").glob("*.jsonl"))
        assert len(quarantine) == 1
        assert quarantine[0].read_bytes() == damaged_bytes
        records = list((Path(memory.path) / "ledger/recovery").glob("*.json"))
        assert len(records) == 1
        record = json.loads(records[0].read_text(encoding="utf-8"))
        assert record["state"] == "COMPLETED"
        assert record["events_before"] == len(ledger)
        assert record["events_after"] == len(ledger)
        assert record["incomplete_parsable"] is False
        assert record["quarantine_file"].startswith("ledger/quarantine/")


class TestIntermediateCorruption:
    """Prueba B — corruption in the middle is detected and never auto-repaired."""

    def test_middle_corruption_fails_closed_without_touching_the_file(self, memory: KuyenMemory) -> None:
        seed(memory)
        path = corrupt_middle(memory, line_number=2)
        damaged = path.read_bytes()

        state = memory.ledger_state()
        assert state["state"] == "CORRUPT"
        assert any("line 2" in problem for problem in state["problems"])
        assert state["tail"] is None

        with pytest.raises(StoreError):
            memory.ledger()
        with pytest.raises(StoreError):
            memory.recover()

        assert path.read_bytes() == damaged
        assert not (Path(memory.path) / "ledger/quarantine").exists()
        assert not (Path(memory.path) / "ledger/recovery").exists()

        report = memory.verify()
        assert report["ok"] is False
        assert report["ledger"]["state"] == "CORRUPT"
        assert any("line 2" in problem for problem in report["problems"])

    def test_truncated_tail_after_middle_corruption_is_not_a_repairable_case(
            self, memory: KuyenMemory) -> None:
        seed(memory)
        path = corrupt_middle(memory, line_number=2)
        with path.open("a", encoding="utf-8") as handle:
            handle.write('{"seq": 99')
        damaged = path.read_bytes()

        assert memory.ledger_state()["state"] == "CORRUPT"
        with pytest.raises(StoreError):
            memory.recover()
        assert path.read_bytes() == damaged


class TestWriteAfterRecovery:
    """Prueba E — the chain continues, the head links and the repair is traceable."""

    def test_new_event_links_to_the_repaired_head(self, memory: KuyenMemory) -> None:
        ledger = seed(memory)
        truncate_tail(memory)
        memory.recover()

        memory.record_failed_antu({"antu_id": "ANTU-AFTER"}, reason="after recovery")

        after = memory.ledger()
        assert len(after) == len(ledger) + 1
        assert after[-1]["seq"] == len(ledger) + 1
        assert after[-1]["prev_event_hash"] == ledger[-1]["event_hash"]
        assert after[: len(ledger)] == ledger
        assert memory.verify()["ok"] is True
        assert memory.verify()["ledger"]["recovery"]["repaired"] is True
        assert memory.verify()["ledger"]["state"] == "INTACT"
        assert len({event["event_hash"] for event in after}) == len(after)

    def test_parsable_final_record_without_newline_is_kept(self, memory: KuyenMemory) -> None:
        ledger = seed(memory)
        path = Path(memory.path) / "ledger/antu.jsonl"
        raw = path.read_bytes()
        path.write_bytes(raw.rstrip(b"\n"))

        state = memory.ledger_state()
        assert state["state"] == "TRUNCATED_TAIL"
        assert state["tail"]["parsable"] is True

        outcome = memory.recover()
        assert outcome["ledger"]["action"] == "COMPLETED_FINAL_NEWLINE"
        assert memory.ledger() == ledger, "a complete record must not be dropped"
        assert memory.verify()["ok"] is True


class TestIdempotency:
    """Prueba F — recovering twice is a no-op the second time."""

    def test_second_recovery_writes_nothing_new(self, memory: KuyenMemory) -> None:
        ledger = seed(memory)
        truncate_tail(memory)

        first = memory.recover()
        assert first["ledger"]["repaired"] is True
        quarantine = sorted((Path(memory.path) / "ledger/quarantine").glob("*.jsonl"))
        records = sorted((Path(memory.path) / "ledger/recovery").glob("*.json"))
        snapshot = ([(path.name, path.read_bytes()) for path in quarantine],
                    [(path.name, path.read_bytes()) for path in records],
                    Path(memory.path).joinpath("ledger/antu.jsonl").read_bytes())

        second = memory.recover()

        assert second["ledger"]["repaired"] is False
        assert second["ledger"]["state"] == "INTACT"
        after = ([(path.name, path.read_bytes()) for path in sorted(
                    (Path(memory.path) / "ledger/quarantine").glob("*.jsonl"))],
                 [(path.name, path.read_bytes()) for path in sorted(
                    (Path(memory.path) / "ledger/recovery").glob("*.json"))],
                 Path(memory.path).joinpath("ledger/antu.jsonl").read_bytes())
        assert after == snapshot
        assert memory.ledger() == ledger
        assert memory.verify()["ok"] is True

    def test_recovery_does_not_duplicate_events(self, memory: KuyenMemory) -> None:
        ledger = seed(memory)
        truncate_tail(memory)
        for _ in range(3):
            memory.recover()
        assert memory.ledger() == ledger
        assert [event["seq"] for event in memory.ledger()] == list(range(1, len(ledger) + 1))
        assert len(memory.history()) == len(ledger)

    def test_intact_ledger_is_never_rewritten(self, memory: KuyenMemory) -> None:
        seed(memory)
        path = Path(memory.path) / "ledger/antu.jsonl"
        before = path.stat().st_mtime_ns, path.read_bytes()
        outcome = memory.recover()
        assert outcome["ledger"]["repaired"] is False
        assert (path.stat().st_mtime_ns, path.read_bytes()) == before
        assert not (Path(memory.path) / "ledger/recovery").exists()
