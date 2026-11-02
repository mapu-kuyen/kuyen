"""The public high-level API: identity, state, history and traceability."""
from __future__ import annotations

from pathlib import Path

import pytest

import fixtures_produc as fixtures
from kuyen import KuyenMemory, MemoryVersion
from kuyen.errors import StoreError


class TestMemoryLifecycle:
    def test_create_and_open_are_equivalent(self, memory: KuyenMemory, tmp_path: Path) -> None:
        reopened = KuyenMemory.open(memory.path)
        assert reopened.path == memory.path
        assert reopened.current() is None
        assert reopened.versions() == []
        assert reopened.status()["integrity"]["ok"] is True

    def test_unit_identity_is_recorded_once(self, memory: KuyenMemory) -> None:
        unit = memory.status()["unit"]
        assert unit["leftraru_id"] == "LR-TEST"
        assert unit["purpose"] == "pytest"

    def test_import_creates_the_first_version(self, live_memory: KuyenMemory) -> None:
        current = live_memory.current()
        assert isinstance(current, MemoryVersion)
        assert current.parent_version_id is None
        assert current.kuyen_version == "1.0.0"
        assert len(live_memory.versions()) == 1

    def test_graph_returns_the_canonical_objects(self, live_memory: KuyenMemory) -> None:
        graph = live_memory.graph()
        assert len(graph["entities"]) == 2
        assert len(graph["relations"]) == 1
        assert graph["kuyen_id"] == "KUY-a1b2c3d4e5f6"

    def test_graph_of_unknown_version_fails_closed(self, live_memory: KuyenMemory) -> None:
        with pytest.raises(StoreError):
            live_memory.graph("VER-000000000000")

    def test_graph_requires_a_committed_version(self, memory: KuyenMemory) -> None:
        with pytest.raises(StoreError):
            memory.graph()


class TestTraceability:
    def test_claim_evidence_and_source_unit_are_linked(self, live_memory: KuyenMemory) -> None:
        relation_id = fixtures._hex("rel_", "test:located-in")
        trace = live_memory.trace(relation_id)
        assert len(trace["evidence"]) == 1
        assert trace["evidence"][0]["source_unit_id"] == "u00"
        assert trace["evidence"][0]["quote"] == "El valle de Colchagua es reconocido por su vino"
        assert trace["evidence"][0]["mapu_id"] == fixtures.MAPU_ID

    def test_source_unit_carries_the_verified_slice(self, live_memory: KuyenMemory) -> None:
        unit = live_memory.source_unit("u00")
        assert unit["content"] == fixtures.make_mapu_text()
        assert unit["content_verified"] is True

    def test_unknown_claim_fails_closed(self, live_memory: KuyenMemory) -> None:
        with pytest.raises(StoreError):
            live_memory.trace("ent_ffffffffffffffffffff")


class TestStatus:
    def test_status_reports_integrity_and_counts(self, live_memory: KuyenMemory) -> None:
        status = live_memory.status()
        assert status["versions"] == 1
        assert status["store_format_version"] == "1.0.0"
        assert status["integrity"]["ok"] is True
        assert status["current"]["version_id"] == live_memory.current().version_id
