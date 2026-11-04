"""B1 — a leftover staging must be *classified*, not assumed unpublished.

Audited defect (KUYEN_RELEASE_CANDIDATE_05, B1): `recover_pending` asked `INTENT.json` for an
`identity_core` key that the writer never writes, so `version_id` was always None and every
staging was reported as `STAGING_WITHOUT_PUBLISHED_MANIFEST` — including the staging of a
commit whose manifest had already been published — and the directory was removed before the
state could be observed.

Contract after the correction:
  * the state of a staging is decided by the store (its manifest), not by the directory;
  * `NOT_PUBLISHED` → removed (nothing authoritative points at it);
  * `PUBLISHED_COMPLETE` / `PUBLISHED_PARTIAL` → completed and only then removed;
  * anything that cannot be attributed (`UNCLASSIFIED`) is kept, never destroyed;
  * recovery stays idempotent: no second version, event, index entry or outbox operation.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from kuyen import KuyenMemory
from kuyen.errors import InjectedFailure
from kuyen.storage.commit import Failpoint, classify_staging, commit_version


def interrupt(memory: KuyenMemory, document: dict, point: str) -> str:
    """Run a real commit that dies at `point`; return the commit id of the abandoned staging."""
    with pytest.raises(InjectedFailure):
        identity = {"kuyen_id": document["kuyen"]["kuyen_id"], "leftraru_id": "LR-TEST",
                    "kuyen_version": document["kuyen"]["version"]}
        commit_version(memory.store, document=document, identity=identity,
                       antu_id="ANTU-B1-" + point.upper(), unit_revision="REV-0001",
                       created_at="2026-11-02T00:00:00+00:00", openviking_version=None,
                       expected_parent_version_id=None, failpoint=Failpoint(point))
    staging = sorted((Path(memory.path) / "staging").iterdir())
    assert len(staging) == 1
    return staging[0].name


def staging_dirs(memory: KuyenMemory) -> list[Path]:
    return sorted(path for path in (Path(memory.path) / "staging").iterdir() if path.is_dir())


class TestClassification:
    def test_a_staging_without_manifest_is_not_published(self, memory: KuyenMemory,
                                                         document: dict) -> None:
        interrupt(memory, document, "before_manifest")
        classified = classify_staging(memory.store, staging_dirs(memory)[0])
        assert classified["state"] == "NOT_PUBLISHED"
        assert classified["version_id"].startswith("VER-")
        assert classified["evidence"]["manifest"] is False

    def test_a_staging_after_the_manifest_is_published(self, memory: KuyenMemory,
                                                       document: dict) -> None:
        interrupt(memory, document, "after_manifest")
        classified = classify_staging(memory.store, staging_dirs(memory)[0])
        assert classified["state"] == "PUBLISHED"
        assert classified["evidence"]["manifest"] is True
        assert classified["version_id"] == memory.versions()[0].to_dict()["version_id"]

    def test_a_staging_without_intent_cannot_be_attributed(self, memory: KuyenMemory) -> None:
        directory = Path(memory.path) / "staging" / "orphan"
        directory.mkdir(parents=True)
        (directory / "INTENT.json").write_text("{not json", encoding="utf-8")
        classified = classify_staging(memory.store, directory)
        assert classified["state"] == "UNCLASSIFIED"
        assert "not readable JSON" in classified["reason"]


class TestRecoveryUsesTheClassification:
    def test_an_unpublished_staging_is_removed_and_reported(self, memory: KuyenMemory,
                                                            document: dict) -> None:
        interrupt(memory, document, "before_manifest")
        outcome = memory.recover()

        assert [item["state"] for item in outcome["staging_discarded"]] == ["NOT_PUBLISHED"]
        assert outcome["staging_discarded"][0]["removed"] is True
        assert staging_dirs(memory) == []
        assert memory.versions() == []
        assert memory.verify()["ok"] is True

    def test_a_published_staging_is_completed_and_reported_as_partial(
            self, memory: KuyenMemory, document: dict) -> None:
        interrupt(memory, document, "after_manifest")
        outcome = memory.recover()

        record = outcome["staging_discarded"][0]
        assert record["state"] == "PUBLISHED_PARTIAL"
        assert set(record["actions_completed"]) == {"indexed", "ledger_recorded",
                                                    "outbox_enqueued"}
        assert len(memory.versions()) == 1
        assert memory.verify()["ok"] is True
        report = memory.verify()
        assert report["registry"]["ok"] is True

    def test_a_published_and_confirmed_staging_is_reported_complete(
            self, live_memory: KuyenMemory) -> None:
        version = live_memory.versions()[0]
        manifest = version.to_dict()
        staging = Path(live_memory.path) / "staging" / "replay"
        staging.mkdir(parents=True)
        (staging / "INTENT.json").write_text(json.dumps({
            "commit_id": "deadbeef",
            "kuyen_id": manifest["kuyen_id"],
            "kuyen_version": manifest["kuyen_version"],
            "canonical_graph_hash": manifest["canonical_graph_hash"],
            "parent_version_id": manifest["parent_version_id"],
            "antu_id": manifest["antu_id"],
            "unit_revision": manifest["unit_revision"],
        }), encoding="utf-8")
        events_before = len(live_memory.ledger())

        outcome = live_memory.recover()

        record = outcome["staging_discarded"][0]
        assert record["state"] == "PUBLISHED_COMPLETE"
        assert record["actions_completed"] == []
        assert record["version_id"] == version.version_id
        assert staging_dirs(live_memory) == []
        assert len(live_memory.ledger()) == events_before
        assert live_memory.verify()["ok"] is True

    def test_an_unattributable_staging_is_kept(self, memory: KuyenMemory) -> None:
        directory = Path(memory.path) / "staging" / "orphan"
        directory.mkdir(parents=True)
        (directory / "payload.txt").write_text("evidence", encoding="utf-8")

        outcome = memory.recover()

        assert outcome["staging_discarded"] == []
        assert [item["staging"] for item in outcome["staging_kept"]] == ["orphan"]
        assert (directory / "payload.txt").read_text(encoding="utf-8") == "evidence"
        assert memory.verify()["ok"] is True

    def test_recovery_duplicates_nothing_and_is_idempotent(self, memory: KuyenMemory,
                                                           document: dict) -> None:
        interrupt(memory, document, "after_manifest")
        first = memory.recover()
        versions = [record.version_id for record in memory.versions()]
        events = len(memory.ledger())
        operations = len(memory.pending_projections())

        for _ in range(2):
            again = memory.recover()
            assert again["completed"] == []
            assert again["staging_discarded"] == []
            assert [record.version_id for record in memory.versions()] == versions
            assert len(memory.ledger()) == events
            assert len(memory.pending_projections()) == operations

        assert first["completed"], "the first recovery must have finished the commit"
        assert memory.verify()["ok"] is True
