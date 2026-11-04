"""Review of the previous experiment: a consumer must be able to tell a repair apart.

KUYEN_SEMANTIC_SECURITY_HARDENING_04, section 8. `recover()` can synthesise the unit revision
of a version that was published before an interruption. That revision and its
`RECONCILIATION` event must be distinguishable from an ordinary commit by the declared
metadata alone, without guessing from ordering or from a diff of the history.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from kuyen import KuyenMemory
from test_operation_boundary import interrupt_the_revision, validate_second_antu


def test_a_reconciled_revision_is_self_describing(live_memory: KuyenMemory, tmp_path: Path,
                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    interrupt_the_revision(live_memory, tmp_path, monkeypatch)
    published = KuyenMemory.open(live_memory.path).current()

    live_memory.recover()
    memory = KuyenMemory.open(live_memory.path)
    ordinary, repaired = memory.history()[0], memory.history()[-1]

    assert "recovered" not in (ordinary.get("detail") or {}), ordinary["detail"]
    detail = repaired["detail"]
    assert detail["recovered"] is True
    assert detail["reason"] == "PUBLISHED_VERSION_WITHOUT_REVISION"
    assert detail["recovered_from"] == f"versions/{published.version_id}/manifest.json"
    assert detail["assigned_unit_revision"] == repaired["unit_revision"]
    assert "manifest_unit_revision" in detail
    assert detail["reconciled_at"]


def test_the_event_stream_separates_a_repair_from_an_ordinary_commit(
        live_memory: KuyenMemory, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    interrupted = interrupt_the_revision(live_memory, tmp_path, monkeypatch)
    published = KuyenMemory.open(live_memory.path).current()
    live_memory.recover()

    memory = KuyenMemory.open(live_memory.path)
    events = memory.ledger()
    repairs = [event for event in events if event["event_type"] == "RECONCILIATION"]
    completions = [event for event in events if event["event_type"] == "ANTU_COMPLETED"]

    # the repaired version never completed an Antü: only the repair event mentions it
    assert [event["version_id"] for event in repairs] == [published.version_id]
    assert repairs[0]["reason"] == "PUBLISHED_VERSION_WITHOUT_REVISION"
    assert repairs[0]["antu_id"], "the repair names the Antu it repairs"
    imported_version = memory.lineage()[0].version_id
    assert all(event["version_id"] != imported_version for event in repairs), \
        "an ordinary commit is never reported as a repair"
    imported = [event for event in events if event["event_type"] == "ANTU_RECEIVED"][0]
    assert imported["kind"] == "IMPORT" and imported["antu_id"] == "ANTU-IMPORT"
    assert "recovered" not in (memory.history()[0].get("detail") or {})
