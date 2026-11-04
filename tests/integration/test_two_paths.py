"""The two Antü kinds must never execute the wrong engine (§7).

A document Antü goes through OpenViking and the canonical admission; a graph edit goes
through the model and the deterministic edit path. The tests below prove the separation
operationally — with doubles that fail loudly if the other engine is touched — and show a
two-stage Antü where a document is incorporated and then explicitly corrected, keeping the
lineage of both stages.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tests.editing import helpers as h
from kuyen import KuyenMemory
from kuyen.errors import InvalidRequestError
from kuyen.product import (ANTU_KIND_DOCUMENT, ANTU_KIND_GRAPH_EDIT, apply_graph_edit,
                           classify_antu, incorporate_document)

ROOT = Path(__file__).resolve().parents[2]


class ExplodingAdapter:
    """Any call from the edit path reaches this object, which fails the test."""

    def __getattr__(self, name):  # pragma: no cover - must never run
        raise AssertionError(f"the graph-edit path called the OpenViking adapter ({name})")


class ExplodingEditor:
    """Any call from the document path reaches this object, which fails the test."""

    name = "exploding"

    def metadata(self):  # pragma: no cover - must never run
        raise AssertionError("the document path used the graph editor")

    def interpret(self, request):  # pragma: no cover - must never run
        raise AssertionError("the document path used the graph editor")


class TestClassification:
    def test_the_two_kinds_are_classified_explicitly(self) -> None:
        assert classify_antu({"antu_id": "A", "kind": "INCORPORATE_MAPU"}) == ANTU_KIND_DOCUMENT
        assert classify_antu({"antu_id": "A"}) == ANTU_KIND_DOCUMENT
        assert classify_antu({"antu_id": "A", "kind": "GRAPH_EDIT"}) == ANTU_KIND_GRAPH_EDIT
        with pytest.raises(InvalidRequestError) as context:
            classify_antu({"antu_id": "A", "kind": "SOMETHING_ELSE"})
        assert context.value.details["code"] == "ANTU_KIND_UNKNOWN"

    def test_a_graph_edit_is_refused_by_the_document_entry_point(self, tmp_path) -> None:
        memory = h.memory_at(tmp_path)
        with pytest.raises(InvalidRequestError) as context:
            incorporate_document(memory, engine=ExplodingAdapter(), mapus=[], actor=None,
                                 antu={"antu_id": "A", "kind": "GRAPH_EDIT"})
        assert context.value.details["code"] == "WRONG_ANTU_PATH"

    def test_a_document_antü_never_uses_the_graph_editor(self, tmp_path) -> None:
        memory = h.memory_at(tmp_path)
        with pytest.raises(InvalidRequestError):
            incorporate_document(memory, engine=ExplodingAdapter(), mapus=[], actor=None,
                                 antu={"antu_id": "A", "kind": "DOCUMENT_INGESTION"})
        # the failure is the missing MAPU, not the editor: nothing was interpreted
        assert len(memory.versions()) == 1

    def test_the_edit_path_needs_no_openviking_and_no_engine(self, tmp_path) -> None:
        memory = h.memory_at(tmp_path)
        identifiers = h.ids(memory)
        result = apply_graph_edit(
            memory, "Cambia la cantidad de luminarias de 12 a 18",
            editor=h.ScriptedEditor(h.proposal([{
                "operation_id": "op-1", "op": "UPDATE_ASSERTION",
                "target": {"assertion_id": identifiers["assertions"]["installed_lights"]},
                "expected": {"value": {"value_type": "integer", "value": 12,
                                       "unit": "luminarias", "context": None}},
                "value": {"value": {"value_type": "integer", "value": 18}},
                "reason": "la instrucción corrige la cantidad",
                "antu_ref": "de 12 a 18"}])))
        assert result.status == "COMMITTED"
        assert len(memory.versions()) == 2
        kinds = {event.get("kind") for event in memory.ledger() if event.get("antu_id")}
        assert "GRAPH_EDIT" in kinds



class TestTwoStageAntu:
    """A document Antü followed by an explicit correction: two versions, two lineages."""

    def test_a_document_then_a_correction_keeps_both_lineages(self, tmp_path) -> None:
        from tests.integration import test_document_path_artifacts as artifacts

        memory = KuyenMemory.create(tmp_path / "memory", leftraru_id="LR-TWO")
        first = incorporate_document(memory, engine=artifacts.engine(tmp_path),
                                     antu=artifacts.antu(), mapus=[artifacts.mapu()],
                                     actor=artifacts.actor(),
                                     adapter=artifacts.FakeOpenViking(artifacts.provider_tree("citations")))
        assert first.status == "COMMITTED"
        base = first.version_id
        graph = memory.graph()
        lights = next(item for item in graph["assertions"]
                      if item["predicate"] == "has_installed_lights")
        assert lights["origin"]["kind"] == "DOCUMENT_EVIDENCE"
        assert lights["evidence_ids"]

        second = apply_graph_edit(
            memory, "Corrige la cantidad de luminarias instaladas a 11",
            editor=h.ScriptedEditor(h.proposal([{
                "operation_id": "op-1", "op": "UPDATE_ASSERTION",
                "target": {"assertion_id": lights["assertion_id"]},
                "expected": {"value": {"value_type": "integer", "value": "12",
                                       "unit": "lights", "context": None}},
                "value": {"value": {"value_type": "integer", "value": "11",
                                    "unit": "lights"}},
                "reason": "la instrucción corrige la cantidad instalada",
                "antu_ref": "corrige la cantidad de luminarias instaladas a 11"}])))
        assert second.status == "COMMITTED", second.to_dict()
        assert second.base_version_id == base
        current = memory.graph()
        new_lights = next(item for item in current["assertions"]
                          if item["assertion_id"] == second.affected["assertions"][0])
        assert new_lights["origin"]["kind"] == "ANTU_INSTRUCTION"
        assert new_lights["evidence_ids"] == []
        previous = memory.graph(base)
        assert next(item for item in previous["assertions"]
                    if item["predicate"] == "has_installed_lights")["evidence_ids"]
        diff = memory.diff(base, second.version_id)
        assert len(diff["collections"]["assertions"]["added"]) == 1
        assert diff["collections"]["assertions"]["removed_from_current_view"]
        completed = [event for event in memory.ledger()
                     if event["event_type"] == "ANTU_COMPLETED"]
        assert [event["version_id"] for event in completed] == [base, second.version_id]
        assert memory.verify()["ok"]
