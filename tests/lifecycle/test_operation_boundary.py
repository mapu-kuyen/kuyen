"""Operation boundary: a published version must be covered by the unit history (front 3).

KUYEN_TRANSACTION_BOUNDARY_HARDENING_03. `commit()` publishes the version (manifest,
index, ledger) and then records the unit revision. An interruption between both steps
leaves a version that is canonical and verifiable while the history never recorded the
operation. The contract must make that state explicit and recoverable, never silent.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import kuyen.api.memory as memory_module
import fixtures_produc as fixtures
from kuyen import KuyenMemory
from kuyen.errors import CommitError, StoreError


def validate_second_antu(memory: KuyenMemory, tmp_path: Path) -> object:
    antu = fixtures.make_antu(antu_id="ANTU-BOUNDARY", base_version_id=memory.current().version_id)
    path = tmp_path / "MAPU-BOUNDARY.txt"
    path.write_text(antu["unit"]["content"], encoding="utf-8")
    return memory.execute_antu(antu, mapu_source=path)


def interrupt_the_revision(memory: KuyenMemory, tmp_path: Path,
                           monkeypatch: pytest.MonkeyPatch) -> str:
    """Publish the version and cut the process before the revision is recorded."""
    execution = validate_second_antu(memory, tmp_path)
    assert execution.status == "VALIDATED"

    def interrupted(*args, **kwargs):
        raise OSError("simulated interruption before the unit revision")

    monkeypatch.setattr(memory_module, "record_revision", interrupted)
    with pytest.raises(OSError):
        memory.commit(execution)
    monkeypatch.undo()
    return execution.antu_id


class TestInterruptedOperation:
    def test_the_published_version_is_reported_as_incomplete(
            self, live_memory: KuyenMemory, tmp_path: Path,
            monkeypatch: pytest.MonkeyPatch) -> None:
        base = live_memory.current().version_id
        interrupt_the_revision(live_memory, tmp_path, monkeypatch)

        memory = KuyenMemory.open(live_memory.path)
        published = memory.current()
        assert published.version_id != base, "the version was published before the interruption"

        pending = memory.pending()
        assert published.version_id in pending["unreconciled"], pending

        report = memory.verify()
        assert report["ok"] is False, "an operation without its revision must not look complete"
        assert any(published.version_id in problem for problem in report["problems"]), report["problems"]
        assert report["unit_history"]["unreconciled"] == [published.version_id]

    def test_a_complete_operation_is_not_reported_as_incomplete(self, live_memory: KuyenMemory,
                                                               tmp_path: Path) -> None:
        execution = validate_second_antu(live_memory, tmp_path)
        live_memory.commit(execution)

        memory = KuyenMemory.open(live_memory.path)
        assert memory.pending()["unreconciled"] == []
        assert memory.verify()["ok"] is True
        assert memory.verify()["unit_history"]["unreconciled"] == []

    def test_recover_records_the_missing_revision_with_provenance(
            self, live_memory: KuyenMemory, tmp_path: Path,
            monkeypatch: pytest.MonkeyPatch) -> None:
        interrupt_the_revision(live_memory, tmp_path, monkeypatch)
        published = KuyenMemory.open(live_memory.path).current()

        outcome = live_memory.recover()
        assert outcome["unit_history"]["recorded"] == [published.version_id]

        memory = KuyenMemory.open(live_memory.path)
        last = memory.history()[-1]
        assert last["output_version_id"] == published.version_id
        assert last["status"] == "COMPLETED"
        assert last["detail"]["recovered"] is True
        assert last["detail"]["manifest_unit_revision"] == published.unit_revision
        assert memory.pending()["unreconciled"] == []
        assert memory.verify()["ok"] is True
        reconciliation = [event for event in memory.ledger() if event["event_type"] == "RECONCILIATION"]
        assert [event["version_id"] for event in reconciliation] == [published.version_id]
        assert len(memory.history()) == 2, "the reconstruction must not duplicate revisions"
        assert len(set(item["unit_revision"] for item in memory.history())) == 2

    def test_recovery_is_idempotent(self, live_memory: KuyenMemory, tmp_path: Path,
                                    monkeypatch: pytest.MonkeyPatch) -> None:
        interrupt_the_revision(live_memory, tmp_path, monkeypatch)
        first = live_memory.recover()
        before = live_memory.history()
        events_before = len(live_memory.ledger())

        second = live_memory.recover()

        assert first["unit_history"]["recorded"] != []
        assert second["unit_history"]["recorded"] == []
        assert live_memory.history() == before
        assert len(live_memory.ledger()) == events_before
        assert live_memory.verify()["ok"] is True

    def test_a_new_operation_after_recovery_keeps_the_history_contiguous(
            self, live_memory: KuyenMemory, tmp_path: Path,
            monkeypatch: pytest.MonkeyPatch) -> None:
        interrupt_the_revision(live_memory, tmp_path, monkeypatch)
        live_memory.recover()

        # the recovered revision covers the version that moved CURRENT, so a new operation
        # is validated against the real current version and commits normally
        execution = validate_second_antu(live_memory, tmp_path)
        live_memory.commit(execution)

        memory = KuyenMemory.open(live_memory.path)
        revisions = [item["unit_revision"] for item in memory.history()]
        assert revisions == [f"R{index:04d}" for index in range(len(revisions))]
        assert len(set(revisions)) == len(revisions)
        assert memory.verify()["ok"] is True

    def test_a_query_from_a_new_instance_sees_the_incomplete_state(
            self, live_memory: KuyenMemory, tmp_path: Path,
            monkeypatch: pytest.MonkeyPatch) -> None:
        interrupt_the_revision(live_memory, tmp_path, monkeypatch)

        fresh = KuyenMemory.open(live_memory.path)
        status = fresh.status()
        assert status["integrity"]["ok"] is False
        assert status["integrity"]["unit_history"]["unreconciled"] != []
        assert fresh.current() is not None
        assert fresh.ledger() != []
