"""Projection and outbox boundaries (front 1).

KUYEN_TRANSACTION_BOUNDARY_HARDENING_03. Publishing a canonical version, recording that
it must be projected, executing the projection and confirming it are four different facts.
A projection must never modify canonical truth, two runners must never execute the same
outbox operation, and a completion must not be published before the registry entry and the
ledger event it implies exist.
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import pytest

from kuyen import KuyenMemory
from kuyen.projection import native as native_projection
from kuyen.projection.outbox import list_operations

from projection_helpers import FakeEngine


def events_of(memory: KuyenMemory, event_type: str) -> list[dict]:
    return [event for event in memory.ledger() if event["event_type"] == event_type]


class TestSingleRunner:
    def test_two_concurrent_runners_execute_the_operation_once(self, live_memory: KuyenMemory) -> None:
        engine = FakeEngine()
        barrier = threading.Barrier(2)
        errors: list[str] = []

        def run() -> None:
            memory = KuyenMemory.open(live_memory.path)
            try:
                barrier.wait(timeout=20)
                memory.project(client=engine, openviking_version="fake-1.0")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{type(exc).__name__}: {exc}")

        threads = [threading.Thread(target=run) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)

        memory = KuyenMemory.open(live_memory.path)
        operation = list_operations(memory.store)[0]
        assert errors == [], errors
        assert len(memory.projections()) == 1, "the same operation produced several projections"
        assert len(events_of(memory, "PROJECTION_COMPLETED")) == 1, \
            "the completion was recorded more than once"
        assert len(operation["attempts"]) == 1, operation["attempts"]
        assert operation["status"] == "DONE"

    def test_an_in_progress_operation_is_not_stolen_by_another_runner(
            self, live_memory: KuyenMemory) -> None:
        operation = list_operations(live_memory.store)[0]
        from kuyen.projection import outbox

        outbox.update(live_memory.store, operation["operation_key"], status="IN_PROGRESS")
        engine = FakeEngine(delay=0.0)

        KuyenMemory.open(live_memory.path).project(client=engine, openviking_version="fake-1.0")

        after = list_operations(live_memory.store)[0]
        assert after["status"] == "IN_PROGRESS", "a runner took over an operation it did not own"
        assert engine.writes == 0
        assert events_of(KuyenMemory.open(live_memory.path), "PROJECTION_COMPLETED") == []


class TestRecovery:
    def test_recover_releases_an_interrupted_projection_and_the_retry_completes_once(
            self, live_memory: KuyenMemory) -> None:
        from kuyen.projection import outbox

        operation = list_operations(live_memory.store)[0]
        outbox.update(live_memory.store, operation["operation_key"], status="IN_PROGRESS")

        recovered = live_memory.recover()

        assert operation["operation_key"] in recovered["projections"]["released"], recovered.get("projections")
        assert list_operations(live_memory.store)[0]["status"] == "PENDING"

        engine = FakeEngine(delay=0.0)
        live_memory.project(client=engine, openviking_version="fake-1.0")
        memory = KuyenMemory.open(live_memory.path)
        assert len(memory.projections()) == 1
        assert len(events_of(memory, "PROJECTION_COMPLETED")) == 1
        assert list_operations(memory.store)[0]["status"] == "DONE"

    def test_second_recovery_is_idempotent(self, live_memory: KuyenMemory) -> None:
        from kuyen.projection import outbox

        operation = list_operations(live_memory.store)[0]
        outbox.update(live_memory.store, operation["operation_key"], status="IN_PROGRESS")
        first = live_memory.recover()
        second = live_memory.recover()
        assert first["projections"]["released"] == [operation["operation_key"]]
        assert second["projections"]["released"] == []
        assert len(list_operations(live_memory.store)[0]["attempts"]) == 1


class TestBoundaryOfTheFacts:
    def test_completion_implies_registry_entry_and_event(self, live_memory: KuyenMemory) -> None:
        engine = FakeEngine(delay=0.0)
        live_memory.project(client=engine, openviking_version="fake-1.0")

        memory = KuyenMemory.open(live_memory.path)
        operation = list_operations(memory.store)[0]
        entries = memory.projections()
        events = events_of(memory, "PROJECTION_COMPLETED")

        assert operation["status"] == "DONE"
        assert operation["projection_id"] == entries[0]["projection_id"]
        assert [event["projection_id"] for event in events] == [entries[0]["projection_id"]]
        assert entries[0]["version_id"] == memory.current().version_id

    def test_projection_never_modifies_canonical_truth(self, live_memory: KuyenMemory) -> None:
        before = {"current": live_memory.current().to_dict(),
                  "versions": [version.version_id for version in live_memory.versions()],
                  "graph": live_memory.graph(),
                  "history": live_memory.history()}

        live_memory.project(client=FakeEngine(delay=0.0), openviking_version="fake-1.0")

        after = KuyenMemory.open(live_memory.path)
        assert after.current().to_dict() == before["current"]
        assert [version.version_id for version in after.versions()] == before["versions"]
        assert after.graph() == before["graph"]
        assert after.history() == before["history"]

    def test_a_failed_projection_is_recorded_and_retryable(self, live_memory: KuyenMemory) -> None:
        failing = FakeEngine(delay=0.0, fail_after=2)
        with pytest.raises(RuntimeError):
            live_memory.project(client=failing, openviking_version="fake-1.0")

        memory = KuyenMemory.open(live_memory.path)
        assert list_operations(memory.store)[0]["status"] == "FAILED"
        assert memory.projections() == []
        assert events_of(memory, "PROJECTION_COMPLETED") == []

        memory.project(client=FakeEngine(delay=0.0), openviking_version="fake-1.0")
        assert len(memory.projections()) == 1
        assert len(events_of(memory, "PROJECTION_COMPLETED")) == 1
