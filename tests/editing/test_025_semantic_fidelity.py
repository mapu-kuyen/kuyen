"""Semantic fidelity of partial Antü updates (KUYEN_ANTU_SEMANTIC_FIDELITY_HARDENING_14).

These tests reproduce the defects measured with a real model in experiment 13 and pin the
corrected contract: an update changes exactly what the Antü names, inherits every other
property from the target, keeps the previous statement and only reports an operation as
confirmed after the canonical commit.
"""
from __future__ import annotations

import copy

from kuyen import KuyenMemory, build_document
from tests.editing import helpers as h


def edit(memory: KuyenMemory, instruction: str, operations, **overrides):
    return memory.apply_antu(instruction, editor=h.ScriptedEditor(h.proposal(operations,
                                                                             **overrides)))


def lights(memory: KuyenMemory, version: str | None = None) -> list[dict]:
    return [item for item in memory.graph(version)["assertions"]
            if item["predicate"] == "installed_lights"]


class TestValueCorrectionPreservesSemantics:
    def test_changing_the_value_keeps_modality_polarity_unit_and_context(self, tmp_path) -> None:
        memory = h.memory_at(tmp_path)
        identifiers = h.ids(memory)
        base = memory.current().version_id
        result = edit(memory, "Corrige la cantidad de luminarias a 18", [{
            "operation_id": "op-1", "op": "UPDATE_ASSERTION",
            "target": {"assertion_id": identifiers["assertions"]["installed_lights"]},
            # the model sends only the number it was asked to change
            "expected": {"value": {"value_type": "integer", "value": 12,
                                   "unit": "luminarias", "context": None}},
            "value": {"value": {"value": 18}},
            "reason": "la instrucción corrige la cantidad instalada",
            "antu_ref": "a 18",
        }])
        assert result.status == "COMMITTED", result.to_dict()
        current = {item["value"]["value"]: item for item in lights(memory)}
        new = current[18]
        old = current[12]
        # every property the Antü did not name survives the correction
        assert new["modality"] == "FACT"
        assert new["polarity"] == "POSITIVE"
        assert new["scope"] == "document"
        assert new["value"]["value_type"] == "integer"
        assert new["value"]["unit"] == "luminarias"
        assert new["value"]["context"] is None
        # the new value is instructed, not documentary; the previous evidence stays as history
        assert new["evidence_ids"] == []
        assert new["previous_evidence_ids"] == old["evidence_ids"]
        assert old["status"] == "SUPERSEDED"
        assert old["evidence_ids"]  # the superseded statement keeps its own support
        assert old["modality"] == "FACT"
        # the previous version still says 12
        assert [item["value"]["value"] for item in lights(memory, base)] == [12]

    def test_the_correction_reports_itself_as_committed_only_after_the_commit(self, tmp_path) -> None:
        memory = h.memory_at(tmp_path)
        identifiers = h.ids(memory)
        result = edit(memory, "Corrige la cantidad de luminarias a 18", [{
            "operation_id": "op-1", "op": "UPDATE_ASSERTION",
            "target": {"assertion_id": identifiers["assertions"]["installed_lights"]},
            "expected": {"value": {"value": 12}},
            "value": {"value": {"value": 18}},
            "reason": "corrección", "antu_ref": "a 18"}])
        assert result.status == "COMMITTED"
        assert result.operations[0]["status"] == "COMMITTED"
        assert result.applied[0]["status"] == "COMMITTED"
        assert result.applied[0]["effect"] == "REPLACED"
        assert result.applied[0]["previous"]["value"]["value"] == 12

    def test_a_rejected_antu_never_reports_an_operation_as_committed(self, tmp_path) -> None:
        memory = h.memory_at(tmp_path)
        identifiers = h.ids(memory)
        base = memory.current().version_id
        result = edit(memory, "Corrige la cantidad de luminarias a 18", [
            {"operation_id": "op-1", "op": "UPDATE_ASSERTION",
             "target": {"assertion_id": identifiers["assertions"]["installed_lights"]},
             "expected": {"value": {"value": 12}}, "value": {"value": {"value": 18}},
             "reason": "corrección", "antu_ref": "a 18"},
            {"operation_id": "op-2", "op": "UPDATE_ASSERTION",
             "target": {"assertion_id": "asrt_does_not_exist"},
             "expected": {"value": {"value": 1}}, "value": {"value": {"value": 2}},
             "reason": "objetivo inventado", "antu_ref": "a 18"}])
        assert result.status == "REJECTED"
        assert result.version_id is None
        assert memory.current().version_id == base
        assert [item["status"] for item in result.operations] == ["VALIDATED"]
        assert result.applied == []
        assert result.committed is False


class TestIndependentProperties:
    def test_modality_changes_alone_and_keeps_the_statement_identity(self, tmp_path) -> None:
        memory = h.memory_at(tmp_path)
        identifiers = h.ids(memory)
        target = identifiers["assertions"]["installed_lights"]
        result = edit(memory, "Esta afirmación es una estimación, no un hecho confirmado", [{
            "operation_id": "op-1", "op": "UPDATE_ASSERTION",
            "target": {"assertion_id": target}, "expected": {"modality": "FACT"},
            "value": {"modality": "ESTIMATE"},
            "reason": "la instrucción cambia la modalidad", "antu_ref": "una estimación"}])
        assert result.status == "COMMITTED", result.to_dict()
        statements = lights(memory)
        assert len(statements) == 1
        assert statements[0]["assertion_id"] == target
        assert statements[0]["modality"] == "ESTIMATE"
        assert statements[0]["value"]["value"] == 12
        assert statements[0]["evidence_ids"]
        assert result.applied[0]["effect"] == "UPDATED"

    def test_attribution_changes_without_destroying_evidence(self, tmp_path) -> None:
        memory = h.memory_at(tmp_path)
        identifiers = h.ids(memory)
        target = identifiers["assertions"]["installed_lights"]
        result = edit(memory, "Atribuye la cifra al municipio", [{
            "operation_id": "op-1", "op": "UPDATE_ASSERTION",
            "target": {"assertion_id": target}, "expected": {"attribution": None},
            "value": {"attribution": "el municipio"},
            "reason": "la instrucción atribuye la cifra", "antu_ref": "al municipio"}])
        assert result.status == "COMMITTED", result.to_dict()
        statement = lights(memory)[0]
        assert statement["attribution"] == "el municipio"
        assert statement["modality"] == "FACT"
        assert statement["evidence_ids"]

    def test_polarity_is_changed_only_when_the_antu_asks_for_it(self, tmp_path) -> None:
        memory = h.memory_at(tmp_path)
        identifiers = h.ids(memory)
        target = identifiers["assertions"]["installed_lights"]
        result = edit(memory, "La cooperativa no instaló las luminarias", [{
            "operation_id": "op-1", "op": "UPDATE_ASSERTION",
            "target": {"assertion_id": target}, "expected": {"polarity": "POSITIVE"},
            "value": {"polarity": "NEGATIVE"},
            "reason": "la instrucción niega el hecho", "antu_ref": "no instaló"}])
        assert result.status == "COMMITTED", result.to_dict()
        statements = {item["polarity"]: item for item in lights(memory)}
        assert statements["NEGATIVE"]["modality"] == "FACT"
        assert statements["POSITIVE"]["status"] == "SUPERSEDED"

    def test_an_explicit_unknown_modality_is_respected(self, tmp_path) -> None:
        memory = h.memory_at(tmp_path)
        identifiers = h.ids(memory)
        target = identifiers["assertions"]["installed_lights"]
        result = edit(memory, "No consta si la cifra es un hecho o una previsión", [{
            "operation_id": "op-1", "op": "UPDATE_ASSERTION",
            "target": {"assertion_id": target}, "expected": {"modality": "FACT"},
            "value": {"modality": "UNKNOWN"},
            "reason": "la instrucción retira la certeza", "antu_ref": "No consta"}])
        assert result.status == "COMMITTED", result.to_dict()
        assert lights(memory)[0]["modality"] == "UNKNOWN"

    def test_an_update_without_the_expected_value_is_refused(self, tmp_path) -> None:
        memory = h.memory_at(tmp_path)
        identifiers = h.ids(memory)
        base = memory.current().version_id
        result = edit(memory, "Corrige la cantidad de luminarias a 18", [{
            "operation_id": "op-1", "op": "UPDATE_ASSERTION",
            "target": {"assertion_id": identifiers["assertions"]["installed_lights"]},
            "value": {"value": {"value": 18}},
            "reason": "sin valor anterior", "antu_ref": "a 18"}])
        assert result.status == "REJECTED"
        assert [item["code"] for item in result.rejected] == ["EXPECTED_VALUE_REQUIRED"]
        assert memory.current().version_id == base


class TestRelationCorrection:
    def _memory_with_three_relations(self, tmp_path) -> tuple[KuyenMemory, dict]:
        """One legitimate relation and two that share the same wrong reading."""
        from kuyen.canonical import stable_id

        value = copy.deepcopy(h.graph())
        base = value["relations"][0]
        extra: dict[str, str] = {}
        for predicate, label in (("located_in", "se ubica en"), ("works_for", "trabaja en")):
            relation = copy.deepcopy(base)
            relation["relation_id"] = stable_id("rel", {"fixture": predicate})
            relation["predicate"] = predicate
            relation["source_predicate"] = predicate
            relation["canonical_predicate"] = predicate
            relation["label"] = label
            relation["display_label"] = label
            value["relations"].append(relation)
            extra[predicate] = relation["relation_id"]
        document = build_document(value, {h.MAPU_ID: h.TEXT},
                                  mapu_versions={h.MAPU_ID: "1.0.0"},
                                  source_uris={h.MAPU_ID: h.SOURCE_URI})
        memory = KuyenMemory.create(tmp_path / "relations", leftraru_id="LR-REL")
        memory.import_canonical(document, antu_id="ANTU-FIXTURE-RELATIONS")
        return memory, extra

    def test_two_related_retractions_are_one_atomic_version_and_keep_the_valid_one(
            self, tmp_path) -> None:
        memory, extra = self._memory_with_three_relations(tmp_path)
        identifiers = h.ids(memory)
        base = memory.current().version_id
        valid = identifiers["relations"]["supervises"]
        result = edit(memory, "Retira las dos relaciones geográficas incorrectas", [
            {"operation_id": "op-1", "op": "RETRACT_RELATION",
             "target": {"relation_id": extra["located_in"]},
             "expected": {"predicate": "located_in"}, "value": {"retracted": True},
             "reason": "la relación no está respaldada", "antu_ref": "incorrectas"},
            {"operation_id": "op-2", "op": "RETRACT_RELATION",
             "target": {"relation_id": extra["works_for"]},
             "expected": {"predicate": "works_for"}, "value": {"retracted": True},
             "reason": "la relación no está respaldada", "antu_ref": "incorrectas"},
        ])
        assert result.status == "COMMITTED", result.to_dict()
        assert result.applied[0]["status"] == "COMMITTED"
        assert len(result.applied) == 2
        graph = memory.graph()
        status = {item["relation_id"]: item.get("status") for item in graph["relations"]}
        assert status[extra["located_in"]] == "RETRACTED"
        assert status[extra["works_for"]] == "RETRACTED"
        assert status[valid] != "RETRACTED"
        assert len(memory.versions()) == 2
        # the previous version still holds both relations
        previous = memory.graph(base)
        assert {item["relation_id"] for item in previous["relations"]} >= {
            extra["located_in"], extra["works_for"], valid}

    def test_a_retraction_without_a_target_is_refused(self, tmp_path) -> None:
        memory = h.memory_at(tmp_path)
        base = memory.current().version_id
        result = edit(memory, "Retira la relación incorrecta", [{
            "operation_id": "op-1", "op": "RETRACT_RELATION",
            "target": {"relation_id": "rel_inventada"},
            "expected": {"predicate": "supervises"}, "value": {"retracted": True},
            "reason": "sin objetivo real", "antu_ref": "incorrecta"}])
        assert result.status == "REJECTED"
        assert [item["code"] for item in result.rejected] == ["TARGET_NOT_FOUND"]
        assert memory.current().version_id == base
        assert result.applied == []

    def test_a_relation_label_changes_in_place_and_keeps_its_evidence(self, tmp_path) -> None:
        memory = h.memory_at(tmp_path)
        identifiers = h.ids(memory)
        target = identifiers["relations"]["supervises"]
        result = edit(memory, "Cambia la etiqueta de la relación a inspecciona", [{
            "operation_id": "op-1", "op": "UPDATE_RELATION",
            "target": {"relation_id": target}, "expected": {"label": "supervisa"},
            "value": {"label": "inspecciona"},
            "reason": "la instrucción corrige la etiqueta", "antu_ref": "inspecciona"}])
        assert result.status == "COMMITTED", result.to_dict()
        relations = [item for item in memory.graph()["relations"]
                     if item["predicate"] == "supervises"]
        assert len(relations) == 1
        assert relations[0]["relation_id"] == target
        assert relations[0]["label"] == "inspecciona"
        assert relations[0]["polarity"] == "POSITIVE"
        assert relations[0]["evidence_ids"]


class TestSchemaOperations:
    def test_adding_a_field_changes_the_schema_and_leaves_the_records_untouched(self, tmp_path) -> None:
        memory = h.schema_memory_at(tmp_path)
        base = memory.current().version_id
        before = memory.graph()["entities"]
        result = edit(memory, "Añade el campo rut al tipo de entidad person", [{
            "operation_id": "op-1", "op": "ADD_FIELD",
            "value": {"entity_type": "person",
                      "field": {"name": "rut", "value_type": "text", "label": "RUT"}},
            "reason": "la instrucción declara el campo", "antu_ref": "campo rut"}])
        assert result.status == "COMMITTED", result.to_dict()
        assert result.schema_changes and result.schema_changes[0]["entity_type"] == "person"
        schema = memory.graph()["schema"]["entity_types"]["person"]["attributes"]
        assert schema["rut"]["declared_by"] == "ANTU_INSTRUCTION"
        # no record receives an invented value and nothing else changes
        assert memory.graph()["entities"] == before
        # the previous version is still readable and has no field
        previous = memory.graph(base)["schema"]["entity_types"]["person"]["attributes"]
        assert "rut" not in previous
        assert memory.verify()["ok"]
        assert result.applied[0]["effect"] == "ADDED"

    def test_declaring_an_existing_field_is_refused_without_a_version(self, tmp_path) -> None:
        memory = h.schema_memory_at(tmp_path)
        base = memory.current().version_id
        result = edit(memory, "Añade el campo description al tipo person", [{
            "operation_id": "op-1", "op": "ADD_FIELD",
            "value": {"entity_type": "person",
                      "field": {"name": "description", "value_type": "text"}},
            "reason": "ya existe", "antu_ref": "campo description"}])
        assert result.status == "REJECTED"
        assert [item["code"] for item in result.rejected] == ["FIELD_ALREADY_DECLARED"]
        assert memory.current().version_id == base

    def test_a_field_on_an_unknown_entity_type_is_refused(self, tmp_path) -> None:
        memory = h.schema_memory_at(tmp_path)
        base = memory.current().version_id
        result = edit(memory, "Añade el campo rut al tipo de entidad supplier", [{
            "operation_id": "op-1", "op": "ADD_FIELD",
            "value": {"entity_type": "supplier", "field": {"name": "rut"}},
            "reason": "el tipo no existe", "antu_ref": "tipo de entidad supplier"}])
        assert result.status == "REJECTED"
        assert [item["code"] for item in result.rejected] == ["ENTITY_TYPE_NOT_IN_SCHEMA"]
        assert memory.current().version_id == base

    def test_updating_a_field_requires_the_current_declaration(self, tmp_path) -> None:
        memory = h.schema_memory_at(tmp_path)
        result = edit(memory, "Cambia el tipo del campo description a integer", [{
            "operation_id": "op-1", "op": "UPDATE_FIELD",
            "value": {"entity_type": "person",
                      "field": {"name": "description", "value_type": "integer"}},
            "reason": "cambio incompatible", "antu_ref": "tipo del campo description"}])
        assert result.status == "REJECTED"
        assert [item["code"] for item in result.rejected] == ["EXPECTED_VALUE_REQUIRED"]


class TestExecutionTruthAndIdempotency:
    def test_repeating_the_same_antu_creates_no_second_version(self, tmp_path) -> None:
        memory = h.memory_at(tmp_path)
        identifiers = h.ids(memory)
        operation = {
            "operation_id": "op-1", "op": "UPDATE_ASSERTION",
            "target": {"assertion_id": identifiers["assertions"]["installed_lights"]},
            "expected": {"value": {"value": 12}},
            "value": {"value": {"value": 18}},
            "reason": "corrección", "antu_ref": "a 18"}
        first = edit(memory, "Cambia la cantidad de luminarias a 18", [operation])
        assert first.status == "COMMITTED"
        versions = len(memory.versions())
        second = edit(memory, "Cambia la cantidad de luminarias a 18", [operation])
        assert second.status == "REPLAYED", second.to_dict()
        assert second.version_id == first.version_id
        assert len(memory.versions()) == versions
        assert second.operations == [] or all(item["status"] != "COMMITTED"
                                               for item in second.operations)

    def test_every_result_carries_the_lifecycle_of_its_operations(self, tmp_path) -> None:
        memory = h.memory_at(tmp_path)
        identifiers = h.ids(memory)
        result = edit(memory, "Cambia la cantidad de luminarias a 18", [{
            "operation_id": "op-1", "op": "UPDATE_ASSERTION",
            "target": {"assertion_id": identifiers["assertions"]["installed_lights"]},
            "expected": {"value": {"value": 12}},
            "value": {"value": {"value": 18}},
            "reason": "corrección", "antu_ref": "a 18"}])
        payload = result.to_dict()
        assert payload["operations"][0]["status"] == "COMMITTED"
        assert payload["applied"][0]["status"] == "COMMITTED"
        assert payload["committed"] is True
        # the ledger records the exact previous value, not a summary
        assert payload["applied"][0]["previous"]["value"]["value"] == 12


class TestOriginAndFailureTruth:
    def test_an_in_place_patch_keeps_a_documentary_origin_and_records_the_edit(self, tmp_path) -> None:
        """K006 real case: changing the modality of a documentary statement must not turn it
        into an instruction without evidence, which the canonical validator refuses."""
        memory = h.memory_at(tmp_path)
        identifiers = h.ids(memory)
        target = identifiers["assertions"]["installed_lights"]
        result = edit(memory, "La cifra es una estimación, no un hecho", [{
            "operation_id": "op-1", "op": "UPDATE_ASSERTION",
            "target": {"assertion_id": target}, "expected": {"modality": "FACT"},
            "value": {"modality": "ESTIMATE"},
            "reason": "la instrucción cambia la modalidad", "antu_ref": "una estimación"}])
        assert result.status == "COMMITTED", result.to_dict()
        statement = lights(memory)[0]
        assert statement["modality"] == "ESTIMATE"
        assert statement["origin"]["kind"] == "DOCUMENT_EVIDENCE"
        assert statement["evidence_ids"]
        assert statement["amended"] is True
        edit_record = statement["instruction_edits"][-1]
        assert edit_record["antu_id"] == result.antu_id
        assert "modality" in edit_record["changed"]
        assert edit_record["previous"]["modality"] == "FACT"
        assert memory.verify()["ok"]

    def test_a_malformed_add_field_is_a_rejection_not_a_crash(self, tmp_path) -> None:
        memory = h.schema_memory_at(tmp_path)
        base = memory.current().version_id
        result = edit(memory, "Añade el campo rut al tipo person", [{
            "operation_id": "op-1", "op": "ADD_FIELD",
            "value": {"entity_type": "person"},
            "reason": "propuesta incompleta", "antu_ref": "campo rut"}])
        assert result.status == "REJECTED"
        assert [item["code"] for item in result.rejected] in (["VALUE_INCOMPLETE"],
                                                                ["SCHEMA_FIELD_INVALID"])
        assert memory.current().version_id == base

    def test_a_rejection_after_application_marks_the_change_as_discarded(
            self, tmp_path, monkeypatch) -> None:
        import kuyen.api.memory as memory_module
        from kuyen.errors import CommitError

        memory = h.memory_at(tmp_path)
        identifiers = h.ids(memory)
        base = memory.current().version_id

        def failing(*args, **kwargs):
            raise CommitError("injected failure after application")

        monkeypatch.setattr(memory_module, "prepare_commit_artifacts", failing)
        result = edit(memory, "Cambia la cantidad de luminarias a 18", [{
            "operation_id": "op-1", "op": "UPDATE_ASSERTION",
            "target": {"assertion_id": identifiers["assertions"]["installed_lights"]},
            "expected": {"value": {"value": 12}},
            "value": {"value": {"value": 18}},
            "reason": "corrección", "antu_ref": "a 18"}])
        assert result.status == "REJECTED"
        assert result.committed is False
        assert [item["status"] for item in result.applied] == ["DISCARDED"]
        assert memory.current().version_id == base
        assert [item["value"]["value"] for item in lights(memory)] == [12]
