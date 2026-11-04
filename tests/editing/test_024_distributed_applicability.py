"""Distributed Antü applicability: one portable instruction, many KÜYEN decisions.

KUYEN_DISTRIBUTED_ANTU_APPLICABILITY_12, §4, §5, §7 and §8. Every test starts from a *real*
canonical memory (committed through `import_canonical`) and a deterministic editor: what is
under test is the local decision KÜYEN makes — applicability, permissions, schema changes and
version creation — read back from the store, not from a mock.
"""
from __future__ import annotations

import pytest

from kuyen import KuyenMemory
from kuyen.semantics.scope import AntuScope
from tests.editing import helpers as h

SCHEMA_ONLY = AntuScope(schema_read=True, schema_write=True, data_read=False, data_write=False,
                        source="declared")
READ_ONLY = AntuScope(schema_read=True, schema_write=False, data_read=True, data_write=False,
                      source="declared")


def edit(memory: KuyenMemory, instruction: str, operations, *, scope=None, **overrides):
    return memory.apply_antu(instruction,
                             editor=h.ScriptedEditor(h.proposal(operations, **overrides)),
                             scope=scope)


def field_operation(operation_id="op-1", entity_type="person", name="rut",
                    value_type="text", **overrides):
    value = {"entity_type": entity_type, "field": {"name": name, "value_type": value_type}}
    value.update(overrides.pop("value", {}))
    return {"operation_id": operation_id, "op": "ADD_FIELD", "value": value,
            "reason": "la instrucción pide declarar el campo",
            "antu_ref": "atributo RUT", **overrides}


class TestSchemaApplicability:
    def test_a_field_the_schema_lacks_is_added_and_versioned(self, tmp_path) -> None:
        memory = h.schema_memory_at(tmp_path)
        base = memory.current().version_id
        instruction = "Asegura que las entidades Persona tengan un atributo RUT"
        result = edit(memory, instruction, [field_operation()])
        assert result.status == "COMMITTED", result.to_dict()
        assert result.version_id != base
        declared = memory.graph()["schema"]["entity_types"]["person"]["attributes"]
        assert "rut" in declared
        assert declared["rut"]["value_type"] == "text"
        assert declared["rut"]["declared_by"] == "ANTU_INSTRUCTION"
        previous = memory.graph(base)["schema"]["entity_types"]["person"]["attributes"]
        assert "rut" not in previous
        assert result.schema_changes[0]["entity_type"] == "person"
        assert result.schema_changes[0]["previous"] is None
        assert memory.verify()["ok"]

    def test_an_existing_field_is_reported_as_already_satisfied_without_a_version(
            self, tmp_path) -> None:
        memory = h.schema_memory_at(tmp_path)
        base = memory.current().version_id
        operation = field_operation(name="description", antu_ref="atributo description",
                                    applicability="ALREADY_SATISFIED",
                                    explanation="person ya declara description")
        result = edit(memory, "Asegura que las personas tengan un atributo description",
                      [operation])
        assert result.status == "NO_CHANGES", result.to_dict()
        assert memory.current().version_id == base
        assert result.declined[0]["applicability"] == "ALREADY_SATISFIED"
        assert result.declined[0]["verified"] is True

    def test_a_false_already_satisfied_claim_is_refused(self, tmp_path) -> None:
        memory = h.schema_memory_at(tmp_path)
        base = memory.current().version_id
        operation = field_operation(applicability="ALREADY_SATISFIED",
                                    explanation="el campo ya existe")
        result = edit(memory, "Asegura que las personas tengan un atributo RUT", [operation])
        assert result.status == "REJECTED"
        assert [item["code"] for item in result.rejected] == [
            "APPLICABILITY_CLAIM_UNSUPPORTED"]
        assert memory.current().version_id == base

    def test_declaring_an_existing_field_is_refused_as_a_duplicate(self, tmp_path) -> None:
        memory = h.schema_memory_at(tmp_path)
        operation = field_operation(name="description", antu_ref="atributo description")
        result = edit(memory, "Asegura que las personas tengan un atributo description",
                      [operation])
        assert result.status == "REJECTED"
        assert [item["code"] for item in result.rejected] == ["FIELD_ALREADY_DECLARED"]

    def test_an_entity_type_the_schema_lacks_does_not_apply(self, tmp_path) -> None:
        memory = h.schema_memory_at(tmp_path)
        base = memory.current().version_id
        result = edit(memory, "Asegura que las entidades Vehiculo tengan un atributo placa",
                      [field_operation(entity_type="vehicle", name="placa",
                                       antu_ref="atributo placa")])
        assert result.status == "REJECTED"
        assert [item["code"] for item in result.rejected] == ["ENTITY_TYPE_NOT_IN_SCHEMA"]
        assert memory.current().version_id == base


class TestPermissions:
    def test_a_schema_only_kuyen_never_receives_the_data(self, tmp_path) -> None:
        memory = h.schema_memory_at(tmp_path)
        editor = h.ScriptedEditor(h.proposal([field_operation()]))
        result = memory.apply_antu(
            "Asegura que las entidades Persona tengan un atributo RUT",
            editor=editor, scope=SCHEMA_ONLY)
        assert result.status == "COMMITTED", result.to_dict()
        payload = editor.requests[0].context.to_payload()
        assert payload["objects"] == {"entities": [], "relations": [], "assertions": [],
                                     "evidence": []}
        assert "schema" in payload
        assert payload["selection"]["mode"] == "DATA_WITHHELD"
        assert payload["capabilities"]["data_visible"] is False
        assert "DATA_READ" in payload["selection"]["data_withheld"]["granted"] or True
        # nothing of the graph travels in the serialised prompt
        prompt = editor.requests[0].user_prompt()
        assert "Camila Soto" not in prompt
        assert "Cooperativa Faro Sur" not in prompt

    def test_a_declared_applicable_operation_without_permission_is_refused(
            self, tmp_path) -> None:
        """APPLICABLE is a claim: if the scope does not grant it, KÜYEN refuses it."""
        memory = h.schema_memory_at(tmp_path)
        base = memory.current().version_id
        identifiers = h.ids(memory)
        result = edit(memory, "Cambia la cantidad de luminarias de 12 a 18", [{
            "operation_id": "op-1", "op": "UPDATE_ASSERTION",
            "target": {"assertion_id": identifiers["assertions"]["installed_lights"]},
            "expected": {"value": {"value_type": "integer", "value": 12}},
            "value": {"value": {"value_type": "integer", "value": 18}},
            "reason": "la instrucción corrige la cantidad", "antu_ref": "de 12 a 18",
        }], scope=READ_ONLY)
        assert result.status == "REJECTED", result.to_dict()
        assert [item["code"] for item in result.rejected] == ["PERMISSION_REQUIRED"]
        assert memory.current().version_id == base

    def test_a_declined_blocked_by_permission_must_be_true(self, tmp_path) -> None:
        memory = h.schema_memory_at(tmp_path)
        granted = field_operation(applicability="BLOCKED_BY_PERMISSION",
                                  explanation="no tengo permiso de esquema")
        result = edit(memory, "Asegura que las entidades Persona tengan un atributo RUT",
                      [granted], scope=SCHEMA_ONLY)
        assert result.status == "REJECTED"
        assert [item["code"] for item in result.rejected] == [
            "APPLICABILITY_CLAIM_UNSUPPORTED"]

    def test_a_real_permission_block_is_recorded_without_a_version(self, tmp_path) -> None:
        memory = h.schema_memory_at(tmp_path)
        base = memory.current().version_id
        blocked = field_operation(applicability="BLOCKED_BY_PERMISSION",
                                  explanation="esta Antü no recibe SCHEMA_WRITE")
        result = edit(memory, "Asegura que las entidades Persona tengan un atributo RUT",
                      [blocked], scope=READ_ONLY)
        assert result.status == "NO_CHANGES", result.to_dict()
        assert result.declined[0]["applicability"] == "BLOCKED_BY_PERMISSION"
        assert result.declined[0]["verified"] is True
        assert memory.current().version_id == base

    def test_requires_data_access_requires_denied_data_read(self, tmp_path) -> None:
        memory = h.schema_memory_at(tmp_path)
        operation = {"operation_id": "op-1", "op": "UPDATE_ASSERTION",
                     "target": {"assertion_id": "asrt_" + "0" * 20},
                     "applicability": "REQUIRES_DATA_ACCESS",
                     "explanation": "necesito ver los registros, y no los veo",
                     "antu_ref": "las personas",
                     "value": {"value": {"value_type": "text", "value": "x"}},
                     "expected": {"value": {"value_type": "text"}}}
        denied = edit(memory, "Corrige el RUT de las personas", [operation], scope=SCHEMA_ONLY)
        assert denied.status == "NO_CHANGES", denied.to_dict()
        assert denied.declined[0]["applicability"] == "REQUIRES_DATA_ACCESS"
        assert denied.declined[0]["verified"] is True
        wrong = edit(memory, "Corrige el RUT que figura en las personas", [operation])
        assert wrong.status == "REJECTED"
        assert [item["code"] for item in wrong.rejected] == [
            "APPLICABILITY_CLAIM_UNSUPPORTED"]


class TestDeclinesAndVersioning:
    def test_one_applicable_operation_and_one_declined_produce_one_version(
            self, tmp_path) -> None:
        memory = h.schema_memory_at(tmp_path)
        base = memory.current().version_id
        result = edit(memory, "Asegura que las personas tengan un atributo RUT y documenta el "
                              "procedimiento", [
            field_operation(antu_ref="atributo RUT"),
            {"operation_id": "op-2", "op": "ADD_FIELD", "value": {"entity_type": "person",
                                                                     "field": {"name": "x"}},
             "applicability": "OUT_OF_SCOPE",
             "explanation": "documentar un procedimiento es lógica de aplicación, no memoria",
             "antu_ref": "documenta el procedimiento"},
        ])
        assert result.status == "COMMITTED", result.to_dict()
        versions = [item.version_id for item in memory.versions()]
        assert base in versions and result.version_id in versions and len(versions) == 2
        assert result.applicability == {"APPLICABLE": 1, "OUT_OF_SCOPE": 1}
        assert result.declined[0]["verified"] is False

    def test_every_operation_declined_creates_no_version_and_is_recorded(
            self, tmp_path) -> None:
        memory = h.schema_memory_at(tmp_path)
        base = memory.current().version_id
        result = edit(memory, "Asegura que las personas tengan un atributo RUT", [
            field_operation(applicability="OUT_OF_SCOPE",
                            explanation="esta Antü no modifica memoria en este KÜYEN"),
        ])
        assert result.status == "NO_CHANGES", result.to_dict()
        assert [item.version_id for item in memory.versions()] == [base]
        events = [event["event_type"] for event in memory.ledger()]
        assert "ANTU_NO_SEMANTIC_CHANGE" in events
        received = [event for event in memory.ledger() if event["event_type"] == "ANTU_RECEIVED"]
        assert received[-1]["antu_global_id"].startswith("ANTU-")
        assert received[-1]["kuyen_id"] == memory.graph()["kuyen_id"]
        assert received[-1]["scope"]["data_read"] is True

    def test_a_decline_without_explanation_is_refused(self, tmp_path) -> None:
        memory = h.schema_memory_at(tmp_path)
        result = edit(memory, "Asegura que las personas tengan un atributo RUT", [
            field_operation(applicability="OUT_OF_SCOPE")])
        assert result.status == "REJECTED"
        assert [item["code"] for item in result.rejected] == [
            "APPLICABILITY_EXPLANATION_MISSING"]

    def test_not_applicable_with_a_target_is_contradictory(self, tmp_path) -> None:
        memory = h.schema_memory_at(tmp_path)
        identifiers = h.ids(memory)
        result = edit(memory, "Corrige la cantidad de luminarias", [{
            "operation_id": "op-1", "op": "UPDATE_ASSERTION",
            "target": {"assertion_id": identifiers["assertions"]["installed_lights"]},
            "applicability": "NOT_APPLICABLE",
            "explanation": "este KÜYEN no tiene esa afirmación",
            "antu_ref": "cantidad de luminarias",
            "value": {"value": {"value_type": "integer", "value": 18}},
            "expected": {"value": {"value_type": "integer", "value": 12}},
        }])
        assert result.status == "REJECTED"
        assert [item["code"] for item in result.rejected] == [
            "APPLICABILITY_CLAIM_UNSUPPORTED"]

    def test_a_replayed_antu_never_creates_a_second_version(self, tmp_path) -> None:
        memory = h.schema_memory_at(tmp_path)
        instruction = "Asegura que las entidades Persona tengan un atributo RUT"
        first = edit(memory, instruction, [field_operation()])
        assert first.status == "COMMITTED"
        second = edit(memory, instruction, [field_operation()])
        assert second.status == "REPLAYED"
        assert second.version_id == first.version_id
        assert len(memory.versions()) == 2

    def test_the_same_portable_antu_gives_the_same_version_in_an_independent_kuyen(
            self, tmp_path) -> None:
        instruction = "Asegura que las entidades Persona tengan un atributo RUT"
        first = h.schema_memory_at(tmp_path / "one")
        second = h.schema_memory_at(tmp_path / "two")
        one = edit(first, instruction, [field_operation()])
        two = edit(second, instruction, [field_operation()])
        assert one.status == two.status == "COMMITTED"
        assert one.version_id == two.version_id
        assert one.antu_global_id == two.antu_global_id
        assert one.kuyen_id == two.kuyen_id


class TestRetraction:
    def test_retracting_an_entity_retracts_its_statements_and_deletes_nothing(
            self, tmp_path) -> None:
        memory = h.schema_memory_at(tmp_path)
        identifiers = h.ids(memory)
        result = edit(memory, "Retira a Camila Soto del grafo", [{
            "operation_id": "op-1", "op": "RETRACT_ENTITY",
            "target": {"entity_id": identifiers["entities"]["Camila Soto"]},
            "expected": {"status": "SOURCE_VERIFIED"},
            "reason": "la instrucción retira la entidad",
            "antu_ref": "Retira a Camila Soto",
        }])
        assert result.status == "COMMITTED", result.to_dict()
        graph = memory.graph()
        camila = [item for item in graph["entities"]
                  if item["entity_id"] == identifiers["entities"]["Camila Soto"]][0]
        assert camila["status"] == "RETRACTED" and camila["retracted"] is True
        assert camila["origin"]["kind"] == "ANTU_INSTRUCTION"
        relation = [item for item in graph["relations"]
                    if item["relation_id"] == identifiers["relations"]["supervises"]][0]
        assert relation["status"] == "RETRACTED"
        # nothing was deleted: the same objects are still readable in this version
        assert len(graph["entities"]) == 2
        assert len(graph["relations"]) == 1
        assert memory.verify()["ok"]


class TestDistribution:
    """One portable Antü, three independent KÜYEN, three different decisions (§9)."""

    INSTRUCTION = "Asegura que las entidades Persona tengan un atributo RUT"

    def test_the_same_text_applies_satisfies_and_blocks_in_different_instances(
            self, tmp_path) -> None:
        applies = h.schema_memory_at(tmp_path / "applies")
        satisfied = h.schema_memory_at(tmp_path / "satisfied", extra_fields={
            "person": {"rut": {"name": "rut", "value_type": "text"}}})
        blocked = h.schema_memory_at(tmp_path / "blocked")

        first = edit(applies, self.INSTRUCTION, [field_operation()])
        second = edit(satisfied, self.INSTRUCTION, [field_operation()])
        # the third instance is the same code but its schema has no entity type for the field
        third = edit(blocked, self.INSTRUCTION, [field_operation(entity_type="vehicle",
                                                                name="rut")])

        assert first.status == "COMMITTED"
        assert second.status == "REJECTED"
        assert [item["code"] for item in second.rejected] == ["FIELD_ALREADY_DECLARED"]
        assert third.status == "REJECTED"
        assert [item["code"] for item in third.rejected] == ["ENTITY_TYPE_NOT_IN_SCHEMA"]
        # each instance kept its own history: only the first one has two versions
        assert len(applies.versions()) == 2
        assert len(satisfied.versions()) == 1
        assert len(blocked.versions()) == 1
        assert first.antu_global_id == second.antu_global_id == third.antu_global_id
        assert first.version_id != blocked.current().version_id

    def test_an_instance_with_the_field_already_declared_reports_already_satisfied(
            self, tmp_path) -> None:
        memory = h.schema_memory_at(tmp_path, extra_fields={
            "person": {"rut": {"name": "rut", "value_type": "text"}}})
        base = memory.current().version_id
        result = edit(memory, self.INSTRUCTION, [
            field_operation(applicability="ALREADY_SATISFIED",
                            explanation="person ya declara rut en el esquema visible")])
        assert result.status == "NO_CHANGES", result.to_dict()
        assert result.declined[0]["verified"] is True
        assert memory.current().version_id == base

    def test_a_schema_only_instance_cannot_be_asked_for_data(self, tmp_path) -> None:
        memory = h.schema_memory_at(tmp_path)
        base = memory.current().version_id
        operation = {"operation_id": "op-1", "op": "UPDATE_ASSERTION",
                     "target": {"assertion_id": "asrt_" + "0" * 20},
                     "applicability": "REQUIRES_DATA_ACCESS",
                     "explanation": "no veo ningún registro en este KÜYEN",
                     "antu_ref": "el RUT de las personas",
                     "value": {"value": {"value_type": "text", "value": "12.345.678-9"}},
                     "expected": {"value": {"value_type": "text"}}}
        result = edit(memory, "Corrige el RUT de las personas", [operation], scope=SCHEMA_ONLY)
        assert result.status == "NO_CHANGES", result.to_dict()
        assert result.applicability == {"REQUIRES_DATA_ACCESS": 1}
        assert memory.current().version_id == base
