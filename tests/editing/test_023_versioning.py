"""Versioning of the direct-edit path (§3 and §8.3).

The brief's core requirement: every Antü must be an identifiable, justified, versioned
operation, the previous state must survive, and the difference between two versions must be
reproducible. These tests exercise the real store: manifests, ledger, sidecars and the
integrity report.
"""
from __future__ import annotations

import helpers as h
from kuyen import KuyenMemory
from kuyen.editing import derive_antu_id
from kuyen.errors import InjectedFailure
from kuyen.storage.commit import Failpoint, recover_pending


def _lights_operation(identifiers, new_value: int, reference: str = "de 12 a 18") -> dict:
    return {
        "operation_id": "op-1", "op": "UPDATE_ASSERTION",
        "target": {"assertion_id": identifiers["assertions"]["installed_lights"]},
        "expected": {"value": {"value_type": "integer", "value": 12,
                               "unit": "luminarias", "context": None}},
        "value": {"value": {"value_type": "integer", "value": new_value,
                            "unit": "luminarias"}},
        "reason": "la instrucción corrige la cantidad instalada",
        "antu_ref": reference,
    }


def _three_versions(tmp_path) -> tuple[KuyenMemory, list[str]]:
    memory = h.memory_at(tmp_path)
    versions = [memory.current().version_id]
    identifiers = h.ids(memory)
    first = memory.apply_antu("Cambia la cantidad de luminarias de 12 a 18",
                              editor=h.ScriptedEditor(h.proposal(
                                  [_lights_operation(identifiers, 18)])))
    assert first.status == "COMMITTED", first.to_dict()
    versions.append(first.version_id)
    second = memory.apply_antu(
        "Retira la afirmación sobre la fecha de inicio",
        editor=h.ScriptedEditor(h.proposal([{
            "operation_id": "op-1", "op": "RETRACT_ASSERTION",
            "target": {"assertion_id": identifiers["assertions"]["started_at"]},
            "expected": {"status": "UNRESOLVED"}, "value": {"retracted": True},
            "reason": "la instrucción retira la afirmación",
            "antu_ref": "retira la afirmación sobre la fecha de inicio"}])))
    assert second.status == "COMMITTED", second.to_dict()
    versions.append(second.version_id)
    return memory, versions


class TestReconstruction:
    def test_every_version_is_independently_reconstructible(self, tmp_path) -> None:
        memory, versions = _three_versions(tmp_path)
        assert len(set(versions)) == 3
        lineage = [item.version_id for item in memory.lineage()]
        assert lineage == versions
        for version_id in versions:
            sidecar = memory.sidecar(version_id)
            assert sidecar["kuyen_version"] in ("1.0.0", "1.1.0", "1.2.0")
            # `graph()` recomputes the canonical hash and compares it with the manifest
            graph = memory.graph(version_id)
            assert graph["content_digest"] and graph["provenance_digest"]
            assert sidecar["canonical_graph_hash"] == memory.sidecar()["canonical_graph_hash"] \
                if version_id == versions[-1] else True
        report = memory.verify()
        assert report["ok"], report["problems"][:5]
        assert len(memory.versions()) == 3

    def test_the_versions_have_the_expected_content(self, tmp_path) -> None:
        memory, versions = _three_versions(tmp_path)
        first, second, third = versions
        v1 = memory.graph(first)
        v2 = memory.graph(second)
        v3 = memory.graph(third)
        values = lambda graph: sorted(
            item["value"]["value"] for item in graph["assertions"]
            if item["predicate"] == "installed_lights")
        assert values(v1) == [12]
        assert values(v2) == [12, 18]
        assert values(v3) == [12, 18]
        dates = lambda graph: [item["status"] for item in graph["assertions"]
                               if item["predicate"] == "started_at"]
        assert dates(v1) == ["UNRESOLVED"]
        assert dates(v2) == ["UNRESOLVED"]
        assert dates(v3) == ["RETRACTED"]
        # the latest version still carries the original documentary evidence untouched
        assert len(v3["evidence"]) == len(v1["evidence"]) == 3
        assert {item["evidence_id"] for item in v1["evidence"]} == {
            item["evidence_id"] for item in v3["evidence"]}

    def test_antus_and_versions_are_mapped_one_to_one(self, tmp_path) -> None:
        memory, versions = _three_versions(tmp_path)
        completed = [event for event in memory.ledger()
                     if event["event_type"] == "ANTU_COMPLETED"]
        assert [event["version_id"] for event in completed] == versions
        assert [event["parent_version_id"] for event in completed] == [None, *versions[:-1]]
        assert len({event["antu_id"] for event in completed}) == 3
        # each version names the Antü that produced it
        assert memory.graph(versions[1])["provenance"]["edits"][-1]["antu_id"] == \
            completed[1]["antu_id"]
        assert memory.graph(versions[2])["provenance"]["edits"][-1]["antu_id"] == \
            completed[2]["antu_id"]



class TestDifferences:
    def test_the_diff_between_two_versions_is_reproducible(self, tmp_path) -> None:
        memory, versions = _three_versions(tmp_path)
        first, second, third = versions
        first_diff = memory.diff(first, second)
        again = memory.diff(first, second)
        assert first_diff["collections"] == again["collections"]
        assertions = first_diff["collections"]["assertions"]
        assert len(assertions["added"]) == 1
        assert len(assertions["modified"]) == 1
        assert assertions["removed_from_current_view"] == list(assertions["modified"])
        assert assertions["deleted"] == []
        assert first_diff["versions"]["before"]["version"] == "1.0.0"
        assert first_diff["versions"]["after"]["version"] == "1.1.0"
        second_diff = memory.diff(second, third)
        retracted = second_diff["collections"]["assertions"]["removed_from_current_view"]
        assert retracted == [h.ids(memory, second)["assertions"]["started_at"]]
        assert second_diff["collections"]["assertions"]["added"] == []
        # the default compares the last two versions
        assert memory.diff()["versions"]["after"]["version"] == "1.2.0"

    def test_a_correction_never_deletes_the_previous_statement(self, tmp_path) -> None:
        memory, versions = _three_versions(tmp_path)
        diff = memory.diff(versions[0], versions[1])
        assert diff["collections"]["assertions"]["deleted"] == []
        assert diff["collections"]["relations"]["deleted"] == []


class TestConcurrency:
    def test_an_edit_computed_on_a_moving_version_is_refused(self, tmp_path) -> None:
        memory = h.memory_at(tmp_path)
        identifiers = h.ids(memory)

        class ConcurrentEditor(h.ScriptedEditor):
            """Applies another Antü while the first one is being interpreted."""

            def interpret(self, request):
                payload = super().interpret(request)
                other = memory.apply_antu(
                    "Retira la afirmación sobre la fecha de inicio",
                    editor=h.ScriptedEditor(h.proposal([{
                        "operation_id": "op-1", "op": "RETRACT_ASSERTION",
                        "target": {"assertion_id": identifiers["assertions"]["started_at"]},
                        "expected": {"status": "UNRESOLVED"},
                        "value": {"retracted": True},
                        "reason": "otra instrucción llegó primero",
                        "antu_ref": "retira la afirmación sobre la fecha de inicio"}])))
                assert other.status == "COMMITTED"
                return payload

        editor = ConcurrentEditor(h.proposal([_lights_operation(identifiers, 18)]))
        result = memory.apply_antu("Cambia la cantidad de luminarias de 12 a 18",
                                   editor=editor)
        assert result.status == "CONFLICT"
        assert result.conflict["code"] == "STALE_BASE"
        assert result.committed is False
        # only the concurrent Antü produced a version; the stale one wrote nothing
        assert len(memory.versions()) == 2
        current = [item["value"]["value"] for item in memory.current_objects("assertions")
                   if item["predicate"] == "installed_lights"]
        assert current == [12]
        assert any(event["event_type"] == "ANTU_REJECTED" and
                   event.get("code") == "STALE_BASE" for event in memory.ledger())

    def test_an_interrupted_edit_never_leaves_a_partial_version(self, tmp_path, monkeypatch) -> None:
        import pytest

        memory = h.memory_at(tmp_path)
        identifiers = h.ids(memory)
        import kuyen.api.memory as memory_module

        real_commit = memory_module.commit_version

        def interrupted(*args, **kwargs):
            kwargs["failpoint"] = Failpoint("after_manifest")
            return real_commit(*args, **kwargs)

        monkeypatch.setattr(memory_module, "commit_version", interrupted)
        with pytest.raises(InjectedFailure):
            memory.apply_antu("Cambia la cantidad de luminarias de 12 a 18",
                              editor=h.ScriptedEditor(h.proposal(
                                  [_lights_operation(identifiers, 18)])))
        # The manifest is the commit point: the version exists, and the operation is
        # visibly incomplete (no unit revision) instead of looking finished.
        assert memory.pending()["unreconciled"]
        recovered = memory.recover()
        assert recovered["unit_history"]["recorded"]
        report = memory.verify()
        assert report["ok"], report["problems"][:5]
        assert len(memory.versions()) == 2
        assert memory.current().version_id == memory.versions()[-1].version_id
        committed = [event for event in memory.ledger()
                     if event["event_type"] == "VERSION_COMMITTED"]
        assert len(committed) == len(memory.versions()) == 2
        # exactly one revision per version after the repair
        assert len(memory.history()) == 2
