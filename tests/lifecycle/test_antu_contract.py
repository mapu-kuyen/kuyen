"""M5 — the Antü contract: an invalid Antü can never reach VALIDATED.

KUYEN_SEMANTIC_SECURITY_HARDENING_04. Two defects were reported: a malformed Antü raised an
accidental `KeyError`, and `VALIDATED` did not guarantee that the commit could satisfy its
own structural preconditions. The contract tested here:

* a structural defect raises `ValidationRejected` (a KÜYEN error, never `KeyError`/`TypeError`);
* a semantic or contract defect returns `REJECTED` with reasons and is recorded in the ledger;
* `VALIDATED` means "the candidate would pass the commit validation now", not "the commit
  will succeed": a concurrent move of CURRENT or an I/O failure can still abort it, and that
  state is represented, never reported as completed.
"""
from __future__ import annotations

import copy
from pathlib import Path

import pytest

import fixtures_produc as fixtures
import kuyen.api.memory as memory_module
from kuyen import KuyenMemory
from kuyen.errors import KuyenError, StoreError, ValidationRejected


def antu_for(memory: KuyenMemory) -> dict:
    return fixtures.make_antu(antu_id="ANTU-CONTRACT", base_version_id=memory.current().version_id)


def rejected(memory: KuyenMemory, antu: dict) -> None:
    """A structural defect must be a controlled error, never an accidental exception."""
    with pytest.raises(ValidationRejected) as caught:
        memory.execute_antu(antu)
    assert isinstance(caught.value, KuyenError)
    assert caught.value.details, "the rejection must carry traceable details"
    assert memory.current() is not None
    assert memory.verify()["ok"] is True


STRUCTURAL = {
    "empty": {},
    "only the identifier": {"antu_id": "ANTU-S-01"},
    "no unit": {"antu_id": "ANTU-S-02", "kind": "INCORPORATE_MAPU"},
    "no proposal": {"antu_id": "ANTU-S-03", "kind": "INCORPORATE_MAPU", "mapu": {},
                     "unit": {}, "coverage": {}},
    "mapu is not an object": {"antu_id": "ANTU-S-04", "kind": "INCORPORATE_MAPU", "mapu": "MAPU",
                              "unit": {}, "coverage": {}, "proposal": {}},
    "proposal is not an object": {"antu_id": "ANTU-S-05", "kind": "INCORPORATE_MAPU", "mapu": {},
                                   "unit": {}, "coverage": {}, "proposal": []},
    "entities is not a list": {"antu_id": "ANTU-S-06", "kind": "INCORPORATE_MAPU", "mapu": {},
                                "unit": {}, "coverage": {},
                                "proposal": {"entities": {"a": 1}, "relations": [],
                                             "assertions": [], "evidence": []}},
    "antu_id is not a string": {"antu_id": 7, "kind": "INCORPORATE_MAPU", "mapu": {},
                                "unit": {}, "coverage": {}, "proposal": {}},
    "unknown kind": {"antu_id": "ANTU-S-08", "kind": "SOMETHING_ELSE", "mapu": {},
                     "unit": {}, "coverage": {}, "proposal": {}},
    "base is not a string": {"antu_id": "ANTU-S-09", "kind": "INCORPORATE_MAPU", "mapu": {},
                             "unit": {}, "coverage": {}, "proposal": {},
                             "base_version_id": {"x": 1}},
}


class TestStructuralContract:
    @pytest.mark.parametrize("label", sorted(STRUCTURAL))
    def test_malformed_antu_is_a_controlled_rejection(self, live_memory: KuyenMemory,
                                                     label: str) -> None:
        rejected(live_memory, copy.deepcopy(STRUCTURAL[label]))

    def test_a_rejection_with_a_valid_identifier_is_recorded_in_the_ledger(
            self, live_memory: KuyenMemory) -> None:
        antu = {"antu_id": "ANTU-RECORDED", "kind": "INCORPORATE_MAPU"}
        with pytest.raises(ValidationRejected):
            live_memory.execute_antu(antu)

        memory = KuyenMemory.open(live_memory.path)
        rejections = [event for event in memory.ledger()
                      if event["event_type"] == "ANTU_REJECTED" and event["antu_id"] == "ANTU-RECORDED"]
        assert rejections, [event["event_type"] for event in memory.ledger()]
        assert rejections[-1]["reasons"]
        assert len(memory.versions()) == 1
        assert len(memory.history()) == 1


class TestValidatedContract:
    def test_invalid_object_identifiers_never_reach_validated(self, live_memory: KuyenMemory,
                                                             tmp_path: Path) -> None:
        antu = antu_for(live_memory)
        antu["proposal"]["entities"][0]["entity_id"] = "ent_short"
        antu["proposal"]["entities"][0]["canonical_entity_id"] = "ent_short"
        antu["proposal"]["relations"][0]["from_entity"] = "ent_short"
        antu["proposal"]["assertions"][0]["subject_entity"] = "ent_short"
        antu["coverage"]["entity_ids"] = ["ent_short"]
        source = tmp_path / "MAPU-CONTRACT.txt"
        source.write_text(antu["unit"]["content"], encoding="utf-8")

        execution = live_memory.execute_antu(antu, mapu_source=source)

        assert execution.status == "REJECTED", execution.to_dict()
        assert any("ent_short" in reason for reason in execution.detail["reasons"]), execution.detail
        assert live_memory.pending()["unreconciled"] == []
        assert live_memory.verify()["ok"] is True

    def test_a_valid_antu_is_validated_and_commits(self, live_memory: KuyenMemory,
                                                  tmp_path: Path) -> None:
        antu = antu_for(live_memory)
        source = tmp_path / "MAPU-VALID.txt"
        source.write_text(antu["unit"]["content"], encoding="utf-8")
        execution = live_memory.execute_antu(antu, mapu_source=source)
        assert execution.status == "VALIDATED"
        live_memory.commit(execution)
        assert execution.status == "COMMITTED"
        assert len(live_memory.versions()) == 2
        assert live_memory.verify()["ok"] is True

    def test_validated_does_not_mean_committed(self, live_memory: KuyenMemory,
                                              tmp_path: Path) -> None:
        base = live_memory.current().version_id
        first, second = antu_for(live_memory), antu_for(live_memory)
        first["antu_id"], second["antu_id"] = "ANTU-RACE-A", "ANTU-RACE-B"
        second["proposal"]["entities"][0]["entity_id"] = fixtures._hex("ent_", "contract-second")
        second["proposal"]["entities"][0]["canonical_entity_id"] = \
            second["proposal"]["entities"][0]["entity_id"]
        second["proposal"]["relations"][0]["from_entity"] = \
            second["proposal"]["entities"][0]["entity_id"]
        second["proposal"]["assertions"][0]["subject_entity"] = \
            second["proposal"]["entities"][0]["entity_id"]
        second["coverage"]["entity_ids"] = [second["proposal"]["entities"][0]["entity_id"]]
        for name, antu in (("a", first), ("b", second)):
            (tmp_path / f"MAPU-{name}.txt").write_text(antu["unit"]["content"], encoding="utf-8")
        execution_a = live_memory.execute_antu(first, mapu_source=tmp_path / "MAPU-a.txt")
        execution_b = live_memory.execute_antu(second, mapu_source=tmp_path / "MAPU-b.txt")
        assert execution_a.status == execution_b.status == "VALIDATED"

        live_memory.commit(execution_a)
        with pytest.raises(StoreError):
            live_memory.commit(execution_b)

        memory = KuyenMemory.open(live_memory.path)
        assert execution_b.status == "VALIDATED", "a failed commit must not look completed"
        assert memory.pending()["unreconciled"] == []
        assert memory.verify()["ok"] is True
        assert len(memory.versions()) == 2, "the rejected commit published nothing"
        assert [item["input_version_id"] for item in memory.history()][-1] == base

    def test_a_transient_failure_after_validation_is_not_a_completion(
            self, live_memory: KuyenMemory, tmp_path: Path,
            monkeypatch: pytest.MonkeyPatch) -> None:
        antu = antu_for(live_memory)
        source = tmp_path / "MAPU-TRANSIENT.txt"
        source.write_text(antu["unit"]["content"], encoding="utf-8")
        execution = live_memory.execute_antu(antu, mapu_source=source)
        assert execution.status == "VALIDATED"
        versions_before = [version.version_id for version in live_memory.versions()]
        revisions_before = live_memory.history()

        def failing_commit(*args, **kwargs):
            raise OSError("simulated disk failure during commit")

        monkeypatch.setattr(memory_module, "commit_version", failing_commit)
        with pytest.raises(OSError):
            live_memory.commit(execution)
        monkeypatch.undo()

        memory = KuyenMemory.open(live_memory.path)
        assert [version.version_id for version in memory.versions()] == versions_before
        assert memory.history() == revisions_before
        assert memory.pending()["unreconciled"] == []
        assert memory.verify()["ok"] is True
        assert execution.status == "VALIDATED"

        live_memory.commit(execution)
        assert live_memory.verify()["ok"] is True
        assert len(live_memory.versions()) == len(versions_before) + 1

    def test_a_unit_whose_hash_does_not_match_its_content_is_rejected(
            self, live_memory: KuyenMemory, tmp_path: Path) -> None:
        """Reported symptom: `VALIDATED` followed by a commit-time sidecar failure."""
        antu = antu_for(live_memory)
        source = tmp_path / "MAPU-UNIT-HASH.txt"
        source.write_text(antu["unit"]["content"], encoding="utf-8")
        antu["unit"]["content_sha256"] = "0" * 64

        execution = live_memory.execute_antu(antu, mapu_source=source)

        assert execution.status == "REJECTED", execution.to_dict()
        assert any("hash" in reason.lower() for reason in execution.detail["reasons"])
        assert len(live_memory.versions()) == 1
        assert live_memory.verify()["ok"] is True
