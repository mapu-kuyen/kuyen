"""A2 — a commit whose base version is stale must not leave an orphan version.

KUYEN_PACKAGE_HARDENING_01, finding A2. The contract: `commit_version` publishes an
immutable manifest and then moves CURRENT with compare-and-swap; a rejected commit must
not publish a version that no lineage can reach and that `verify()` reports as healthy.
"""
from __future__ import annotations

import copy
import threading
from pathlib import Path

import pytest

import fixtures_produc as fixtures
from kuyen import KuyenMemory
from kuyen.errors import StoreError


def variant(base_version_id: str, *, antu_id: str, label: str) -> dict:
    """A distinct Antu from the same base: different entity identity, same shape."""
    antu = fixtures.make_antu(antu_id=antu_id, base_version_id=base_version_id)
    entity_id = fixtures._hex("ent_", label)
    antu["proposal"]["entities"][0]["entity_id"] = entity_id
    antu["proposal"]["entities"][0]["canonical_entity_id"] = entity_id
    antu["proposal"]["relations"][0]["from_entity"] = entity_id
    antu["proposal"]["assertions"][0]["subject_entity"] = entity_id
    antu["coverage"]["entity_ids"] = [entity_id]
    return antu


def prepare(memory: KuyenMemory, tmp_path: Path, antu: dict, name: str):
    path = tmp_path / f"MAPU-{name}.txt"
    path.write_text(antu["unit"]["content"], encoding="utf-8")
    return memory.execute_antu(antu, mapu_source=path)


class TestSequentialStaleBase:
    def test_stale_base_commit_is_rejected_and_leaves_no_orphan(self, live_memory: KuyenMemory,
                                                                tmp_path: Path) -> None:
        base = live_memory.current().version_id
        first = prepare(live_memory, tmp_path, variant(base, antu_id="ANTU-A", label="variant-a"), "a")
        second = prepare(live_memory, tmp_path, variant(base, antu_id="ANTU-B", label="variant-b"), "b")
        assert first.status == "VALIDATED" and second.status == "VALIDATED"

        live_memory.commit(first)
        with pytest.raises(StoreError):
            live_memory.commit(second)

        reopened = KuyenMemory.open(live_memory.path)
        assert len(reopened.versions()) == 2, "a rejected commit must not publish a version"
        assert reopened.current().parent_version_id == base
        assert reopened.verify()["ok"] is True
        assert reopened.pending()["incomplete"] == []
        assert reopened.pending()["staging"] == []
        assert [v.version_id for v in reopened.versions()][-1] == reopened.current().version_id

    def test_rejected_commit_does_not_touch_the_ledger_outcome(self, live_memory: KuyenMemory,
                                                              tmp_path: Path) -> None:
        base = live_memory.current().version_id
        first = prepare(live_memory, tmp_path, variant(base, antu_id="ANTU-C", label="c"), "c")
        second = prepare(live_memory, tmp_path, variant(base, antu_id="ANTU-D", label="d"), "d")
        live_memory.commit(first)
        before = len(live_memory.ledger())
        with pytest.raises(StoreError):
            live_memory.commit(second)
        after = live_memory.ledger()
        assert len(after) == before, "a rejected commit must not append ledger events"
        commit_events = {"ANTU_COMPLETED", "VERSION_COMMITTED", "PROJECTION_ENQUEUED"}
        assert not any(event.get("antu_id") == "ANTU-D" and event.get("event_type") in commit_events
                       for event in after), "a rejected commit must not record an outcome"


class TestConcurrentCommit:
    """Two writers prepared from the same base, released together by a barrier."""

    def test_exactly_one_version_is_published(self, live_memory: KuyenMemory,
                                              tmp_path: Path) -> None:
        base = live_memory.current().version_id
        barrier = threading.Barrier(2)
        results: dict[str, dict] = {}

        def worker(name: str, antu_id: str, label: str) -> None:
            memory = KuyenMemory.open(live_memory.path)
            execution = prepare(memory, tmp_path, variant(base, antu_id=antu_id, label=label), name)
            results[name] = {"status": execution.status}
            barrier.wait(timeout=10)
            try:
                memory.commit(execution)
                results[name]["committed"] = True
            except StoreError as exc:  # the loser: lock contention or stale base
                results[name]["committed"] = False
                results[name]["error"] = str(exc)

        threads = [threading.Thread(target=worker, args=("a", "ANTU-E", "variant-e")),
                   threading.Thread(target=worker, args=("b", "ANTU-F", "variant-f"))]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        assert not any(thread.is_alive() for thread in threads)
        assert all(results[name]["status"] == "VALIDATED" for name in results)
        assert sum(1 for name in results if results[name]["committed"]) == 1, results

        reopened = KuyenMemory.open(live_memory.path)
        assert len(reopened.versions()) == 2, results
        assert reopened.pending()["incomplete"] == []
        assert reopened.pending()["staging"] == []
        # A2 is satisfied: one version, no orphan. The ledger chain is a different defect
        # (M1, "ledger e historial sin lock", out of scope in this run): two concurrent
        # `execute_antu` calls append events without exclusion. When `verify()` is not ok,
        # every problem must be that documented signature and nothing else.
        report = reopened.verify()
        if not report["ok"]:
            assert all("prev_event_hash" in problem or "unexpected seq" in problem
                       for problem in report["problems"]), report["problems"]
        assert reopened.pending()["staging"] == []

    def test_losing_writer_does_not_publish_a_manifest(self, live_memory: KuyenMemory,
                                                       tmp_path: Path) -> None:
        base = live_memory.current().version_id
        winner = prepare(live_memory, tmp_path, variant(base, antu_id="ANTU-G", label="g"), "g")
        loser = prepare(live_memory, tmp_path, variant(base, antu_id="ANTU-H", label="h"), "h")
        live_memory.commit(winner)
        versions_before = {version.version_id for version in live_memory.versions()}
        with pytest.raises(StoreError):
            live_memory.commit(loser)
        versions_after = {version.version_id for version in live_memory.versions()}
        assert versions_after == versions_before
        assert not any((live_memory.store.staging_dir / path.name).exists()
                       for path in live_memory.store.staging_dir.glob("*"))
