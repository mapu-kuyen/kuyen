"""Antu lifecycle: proposed, validated, accepted, rejected, replayed, conflicting."""
from __future__ import annotations

from pathlib import Path

from kuyen import KuyenMemory
from kuyen.errors import CommitError

import fixtures_produc as fixtures


class TestAcceptedAntu:
    def test_execution_validates_without_committing(self, live_memory: KuyenMemory, antu_file) -> None:
        antu, path = antu_file
        before = live_memory.current().version_id
        execution = live_memory.execute_antu(antu, mapu_source=path)
        assert execution.status == "VALIDATED"
        assert execution.committable is True
        assert live_memory.current().version_id == before
        assert len(live_memory.versions()) == 1

    def test_commit_creates_a_new_immutable_version(self, live_memory: KuyenMemory, antu_file) -> None:
        antu, path = antu_file
        execution = live_memory.execute_antu(antu, mapu_source=path)
        parent = live_memory.current().version_id
        result = live_memory.commit(execution)
        assert result.version.parent_version_id == parent
        assert result.version.kuyen_version == "1.1.0"
        assert len(live_memory.versions()) == 2
        assert live_memory.current().version_id == result.version.version_id

    def test_previous_version_stays_readable(self, live_memory: KuyenMemory, antu_file) -> None:
        antu, path = antu_file
        first = live_memory.current().version_id
        live_memory.commit(live_memory.execute_antu(antu, mapu_source=path))
        assert len(live_memory.graph(first)["relations"]) == 1
        assert len(live_memory.graph()["relations"]) == 2

    def test_history_is_append_only(self, live_memory: KuyenMemory, antu_file) -> None:
        antu, path = antu_file
        live_memory.commit(live_memory.execute_antu(antu, mapu_source=path))
        history = live_memory.history()
        assert [item["status"] for item in history] == ["COMPLETED", "COMPLETED"]
        assert [item["unit_revision"] for item in history] == ["R0000", "R0001"]


class TestRefusedAntu:
    def test_tampered_mapu_is_rejected_and_not_committed(self, live_memory: KuyenMemory, antu_file):
        antu, pattern = antu_file
        tampered = pattern.parent / "tampered.txt"
        tampered.write_text(antu["mapu_text"] + " texto añadido", encoding="utf-8")
        execution = live_memory.execute_antu(antu, mapu_source=tampered)
        assert execution.status == "REJECTED"
        assert any("hash" in reason.lower() for reason in execution.detail["reasons"])
        assert len(live_memory.versions()) == 1

    def test_committing_a_rejected_antu_is_impossible(self, live_memory: KuyenMemory, antu_file):
        import pytest

        antu, pattern = antu_file
        tampered = pattern.parent / "tampered2.txt"
        tampered.write_text("otro texto", encoding="utf-8")
        execution = live_memory.execute_antu(antu, mapu_source=tampered)
        with pytest.raises(CommitError):
            live_memory.commit(execution)

    def test_stale_base_is_a_conflict(self, live_memory: KuyenMemory, antu_file) -> None:
        antu, path = antu_file
        stale = dict(antu, antu_id="ANTU-TEST-STALE", base_version_id="VER-000000000000")
        execution = live_memory.execute_antu(stale, mapu_source=path)
        assert execution.status == "CONFLICT"
        assert "STALE_BASE" in execution.detail["reason"]
        assert len(live_memory.versions()) == 1

    def test_repeated_antu_is_replayed_not_duplicated(self, live_memory: KuyenMemory, antu_file) -> None:
        antu, path = antu_file
        first = live_memory.commit(live_memory.execute_antu(antu, mapu_source=path))
        replay = live_memory.execute_antu(antu, mapu_source=path)
        assert replay.status == "REPLAYED"
        assert replay.committed_version_id == first.version.version_id
        result = live_memory.commit(replay)
        assert result.version.version_id == first.version.version_id
        assert len(live_memory.versions()) == 2

    def test_verify_only_produces_no_new_version(self, live_memory: KuyenMemory) -> None:
        antu = {"antu_id": "ANTU-VERIFY-1", "kind": "VERIFY_ONLY", "leftraru_id": "LR-TEST"}
        execution = live_memory.execute_antu(antu)
        assert execution.status == "NO_SEMANTIC_CHANGE"
        assert len(live_memory.versions()) == 1

    def test_failed_execution_is_recorded_without_a_version(self, live_memory: KuyenMemory) -> None:
        record = live_memory.record_failed_antu({"antu_id": "ANTU-FAIL-1"}, reason="provider timeout")
        assert record["status"] == "REJECTED"
        assert record["output_version_id"] is None
        assert len(live_memory.versions()) == 1
        assert any(event["event_type"] == "ANTU_REJECTED" for event in live_memory.ledger())
