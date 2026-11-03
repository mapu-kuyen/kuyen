"""Operational coverage of the Antü editor (KUYEN_ANTU_OPERATIONAL_COVERAGE_15).

Experiment 14 proved that partial updates preserve semantics. This module pins the operations
that experiment never exercised: adding a relation, updating an entity, updating a typed
attribute of an entity, a long instruction with several changes, and the classification of a
run whose editor produced nothing. Every test starts from a real canonical version committed
through `import_canonical`, and every assertion reads the version that was actually committed.
"""
from __future__ import annotations

from typing import Any

from kuyen import KuyenMemory, build_document
from kuyen.canonical import stable_id
from tests.editing import helpers as h

EXTRA_ENTITY = stable_id("ent", {"fixture": "faro-norte"})


def edit(memory: KuyenMemory, instruction: str, operations: list[dict[str, Any]],
         **overrides: Any):
    """Run one Antü against the current version with a deterministic editor."""
    return memory.apply_antu(instruction,
                             editor=h.ScriptedEditor(h.proposal(operations, **overrides)))


def two_organizations(tmp_path) -> KuyenMemory:
    """A real version with two organizations of the same type (identity ambiguity)."""
    value = h.graph()
    value["entities"].append(h.entity(
        EXTRA_ENTITY, "Cooperativa Faro Norte", "organization",
        "Segunda cooperativa del pasaje", h._id("ev_", "installed-12")))
    memory = KuyenMemory.create(tmp_path / "two", leftraru_id="LR-TWO")
    memory.import_canonical(build_document(value, {h.MAPU_ID: h.TEXT},
                                           mapu_versions={h.MAPU_ID: "1.0.0"},
                                           source_uris={h.MAPU_ID: h.SOURCE_URI}),
                            antu_id="ANTU-FIXTURE-TWO")
    return memory


def entities(memory: KuyenMemory, version: str | None = None) -> dict[str, dict[str, Any]]:
    return {item["name"]: item for item in memory.graph(version)["entities"]}


def by_id(memory: KuyenMemory, entity_id: str, version: str | None = None) -> dict[str, Any]:
    return next(item for item in memory.graph(version)["entities"]
                if item["entity_id"] == entity_id)


def relation(memory: KuyenMemory, predicate: str, version: str | None = None) -> dict[str, Any]:
    return next(item for item in memory.graph(version)["relations"]
                if item["predicate"] == predicate)



class TestRelationIncorporation:
    """ADD_RELATION reached the graph with a canonical identity, a direction and no evidence."""

    def test_a_new_relation_is_added_with_the_direction_the_instruction_states(
            self, tmp_path) -> None:
        memory = h.memory_at(tmp_path)
        identifiers = h.ids(memory)
        base = memory.current().version_id
        result = edit(memory, "La Cooperativa Faro Sur depende administrativamente de Camila "
                              "Soto: incorpora esa relación entre ambas entidades.", [{
            "operation_id": "op-1", "op": "ADD_RELATION",
            "value": {"from": identifiers["entities"]["Cooperativa Faro Sur"],
                      "to": identifiers["entities"]["Camila Soto"],
                      "predicate": "reports_to", "label": "depende de",
                      "polarity": "POSITIVE", "modality": "FACT"},
            "reason": "la instrucción declara la dependencia entre las dos entidades",
            "antu_ref": "depende administrativamente de Camila Soto",
        }])
        assert result.status == "COMMITTED", result.to_dict()
        assert result.outcome == "COMMITTED"
        added = relation(memory, "reports_to")
        assert added["from_entity"] == identifiers["entities"]["Cooperativa Faro Sur"]
        assert added["to_entity"] == identifiers["entities"]["Camila Soto"]
        assert added["relation_id"].startswith("rel_")
        assert added["polarity"] == "POSITIVE" and added["modality"] == "FACT"
        # an introduced relation has no documentary support and does not pretend to have any
        assert added["evidence_ids"] == [] and added["sources"] == []
        assert added["status"] == "INSTRUCTED"
        assert added["origin"]["kind"] == "ANTU_INSTRUCTION"
        # the previous version does not contain it
        assert all(item["predicate"] != "reports_to" for item in memory.graph(base)["relations"])
        assert result.version_id in [item.version_id for item in memory.versions()]

    def test_an_equivalent_relation_reported_as_already_satisfied_creates_no_version(
            self, tmp_path) -> None:
        memory = h.memory_at(tmp_path)
        identifiers = h.ids(memory)
        base = memory.current().version_id
        existing = identifiers["relations"]["supervises"]
        result = edit(memory, "La relación de supervisión entre Camila Soto y la cooperativa "
                              "ya está registrada.", [{
            "operation_id": "op-1", "op": "ADD_RELATION",
            "applicability": "ALREADY_SATISFIED",
            "target": {"relation_id": existing},
            "expected": {"predicate": "supervises"},
            "explanation": "supervises ya existe entre las dos entidades en esta versión",
            "value": {"from": identifiers["entities"]["Camila Soto"],
                      "to": identifiers["entities"]["Cooperativa Faro Sur"],
                      "predicate": "supervises", "polarity": "POSITIVE"},
            "reason": "la instrucción pide algo que ya está", "antu_ref": "ya está registrada",
        }])
        assert result.status == "NO_CHANGES", result.to_dict()
        assert result.outcome == "ALREADY_SATISFIED"
        assert result.committed is False
        assert memory.current().version_id == base
        assert len(memory.versions()) == 1

    def test_a_duplicate_relation_is_refused_even_when_the_model_adds_it(self, tmp_path) -> None:
        memory = h.memory_at(tmp_path)
        identifiers = h.ids(memory)
        base = memory.current().version_id
        result = edit(memory, "Camila Soto supervisa a la cooperativa: agrega esa relación.", [{
            "operation_id": "op-1", "op": "ADD_RELATION",
            "value": {"from": identifiers["entities"]["Camila Soto"],
                      "to": identifiers["entities"]["Cooperativa Faro Sur"],
                      "predicate": "supervises", "polarity": "POSITIVE"},
            "reason": "la instrucción declara la supervisión", "antu_ref": "Camila Soto supervisa",
        }])
        assert result.status == "REJECTED", result.to_dict()
        assert [item["code"] for item in result.rejected] == ["DUPLICATE_OBJECT"]
        assert result.outcome == "INVALID_PROPOSAL"
        assert memory.current().version_id == base

    def test_an_inverted_relation_is_ambiguous_and_is_not_added(self, tmp_path) -> None:
        memory = h.memory_at(tmp_path)
        identifiers = h.ids(memory)
        base = memory.current().version_id
        result = edit(memory, "La cooperativa supervisa a Camila Soto: incorpora esa relación.",
                      [{
            "operation_id": "op-1", "op": "ADD_RELATION",
            "value": {"from": identifiers["entities"]["Cooperativa Faro Sur"],
                      "to": identifiers["entities"]["Camila Soto"],
                      "predicate": "supervises", "polarity": "POSITIVE"},
            "reason": "la instrucción declara la supervisión en el otro sentido",
            "antu_ref": "La cooperativa supervisa a Camila Soto",
        }])
        assert result.status == "REJECTED", result.to_dict()
        assert [item["code"] for item in result.rejected] == ["RELATION_DIRECTION_CONFLICT"]
        assert memory.current().version_id == base


    def test_a_relation_with_a_missing_endpoint_is_refused(self, tmp_path) -> None:
        memory = h.memory_at(tmp_path)
        identifiers = h.ids(memory)
        result = edit(memory, "La cooperativa depende de la Junta de Vecinos: agrega esa "
                              "relación.", [{
            "operation_id": "op-1", "op": "ADD_RELATION",
            "value": {"from": identifiers["entities"]["Cooperativa Faro Sur"],
                      "to": "ent_" + "f" * 20, "predicate": "depends_on",
                      "polarity": "POSITIVE"},
            "reason": "la instrucción declara la dependencia", "antu_ref": "depende de la Junta",
        }])
        assert result.status == "REJECTED", result.to_dict()
        assert [item["code"] for item in result.rejected] == ["TARGET_NOT_FOUND"]

    def test_a_self_relation_is_refused(self, tmp_path) -> None:
        memory = h.memory_at(tmp_path)
        identifiers = h.ids(memory)
        target = identifiers["entities"]["Cooperativa Faro Sur"]
        result = edit(memory, "La cooperativa se supervisa a sí misma: agrega esa relación.", [{
            "operation_id": "op-1", "op": "ADD_RELATION",
            "value": {"from": target, "to": target, "predicate": "supervises",
                      "polarity": "POSITIVE"},
            "reason": "la instrucción lo declara", "antu_ref": "se supervisa a sí misma",
        }])
        assert result.status == "REJECTED", result.to_dict()
        assert [item["code"] for item in result.rejected] == ["SELF_RELATION"]

    def test_a_relation_is_patched_in_place_without_losing_its_support(self, tmp_path) -> None:
        memory = h.memory_at(tmp_path)
        identifiers = h.ids(memory)
        existing = identifiers["relations"]["supervises"]
        result = edit(memory, "La relación de supervisión debe decir «supervisa la instalación», "
                              "no «supervisa».", [{
            "operation_id": "op-1", "op": "UPDATE_RELATION",
            "target": {"relation_id": existing},
            "expected": {"label": "supervisa"},
            "value": {"label": "supervisa la instalación"},
            "reason": "la instrucción corrige la etiqueta de la relación",
            "antu_ref": "debe decir «supervisa la instalación»",
        }])
        assert result.status == "COMMITTED", result.to_dict()
        patched = relation(memory, "supervises")
        # same identity, same endpoints, same evidence: only the label changed
        assert patched["relation_id"] == existing
        assert patched["label"] == "supervisa la instalación"
        assert patched["display_label"] == "supervisa la instalación"
        # `source_label` stays the label the source gave: the Antü amended it, it did not
        # become the source of the statement.
        assert patched["source_label"] == "supervisa"
        assert patched["predicate"] == "supervises" and patched["polarity"] == "POSITIVE"
        assert patched["evidence_ids"] and patched["origin"]["kind"] == "DOCUMENT_EVIDENCE"
        assert patched["instruction_edits"][-1]["changed"] == ["label"]
        assert patched["instruction_edits"][-1]["previous"]["label"] == "supervisa"



class TestEntityUpdate:
    """UPDATE_ENTITY changes a property and nothing else: identity, relations and history stay."""

    def test_a_renamed_entity_keeps_its_identity_relations_and_attributes(self, tmp_path) -> None:
        memory = h.memory_at(tmp_path)
        identifiers = h.ids(memory)
        base = memory.current().version_id
        target = identifiers["entities"]["Cooperativa Faro Sur"]
        before = by_id(memory, target)
        result = edit(memory, "Actualiza la denominación de esta organización a su nombre "
                              "oficial completo: Cooperativa Faro Sur de Los Aromos.", [{
            "operation_id": "op-1", "op": "UPDATE_ENTITY",
            "target": {"entity_id": target},
            "expected": {"name": "Cooperativa Faro Sur"},
            "value": {"name": "Cooperativa Faro Sur de Los Aromos"},
            "reason": "la instrucción corrige la denominación de la organización",
            "antu_ref": "Actualiza la denominación de esta organización",
        }])
        assert result.status == "COMMITTED", result.to_dict()
        after = by_id(memory, target)
        assert after["entity_id"] == target
        assert after["name"] == "Cooperativa Faro Sur de Los Aromos"
        # nothing else on the entity changed
        assert after["entity_type"] == before["entity_type"]
        assert after["description"] == before["description"]
        assert after["aliases"] == before["aliases"]
        assert after["metadata"] == before["metadata"]
        assert after["evidence_ids"] == before["evidence_ids"]
        # a documentary entity keeps its documentary origin; the Antü amended a property
        assert after["origin"]["kind"] == "DOCUMENT_EVIDENCE"
        assert after["amended"] is True
        assert after["instruction_edits"][-1]["changed"] == ["name"]
        assert after["instruction_edits"][-1]["previous"]["name"] == "Cooperativa Faro Sur"
        # the history of the change is on the entity and in the previous version
        revision = after["revisions"][-1]
        assert revision["operation_id"] == "op-1" and revision["changed"] == ["name"]
        assert revision["previous"]["name"] == "Cooperativa Faro Sur"
        assert revision["previous_origin"]["kind"] == "DOCUMENT_EVIDENCE"
        assert by_id(memory, target, base)["name"] == "Cooperativa Faro Sur"
        # the relation that points at it still points at it, and no entity was created
        assert relation(memory, "supervises")["to_entity"] == target
        assert len(memory.graph()["entities"]) == len(memory.graph(base)["entities"])

    def test_renaming_to_a_name_already_taken_by_the_same_type_is_refused(self, tmp_path) -> None:
        memory = two_organizations(tmp_path)
        identifiers = h.ids(memory)
        base = memory.current().version_id
        result = edit(memory, "Renombra la Cooperativa Faro Sur como Cooperativa Faro Norte.",
                      [{
            "operation_id": "op-1", "op": "UPDATE_ENTITY",
            "target": {"entity_id": identifiers["entities"]["Cooperativa Faro Sur"]},
            "expected": {"name": "Cooperativa Faro Sur"},
            "value": {"name": "Cooperativa Faro Norte"},
            "reason": "la instrucción cambia una denominación",
            "antu_ref": "Renombra la Cooperativa Faro Sur como Cooperativa Faro Norte",
        }])
        assert result.status == "REJECTED", result.to_dict()
        assert [item["code"] for item in result.rejected] == ["ENTITY_NAME_COLLISION"]
        # no implicit merge: both organizations still exist, unchanged
        assert memory.current().version_id == base
        assert len(memory.graph()["entities"]) == 3


def attribute_operation(attribute: str, value: Any, expected_value: Any, **overrides: Any):
    operation = {"operation_id": "op-1", "op": "UPDATE_ATTRIBUTE",
                 "target": {"entity_id": overrides.pop("target")},
                 "expected": {"attribute": attribute, "value": expected_value},
                 "value": {"attribute": attribute, "value": value},
                 "reason": "la instrucción corrige el valor del atributo",
                 "antu_ref": "estado operativo"}
    operation.update(overrides)
    return operation


class TestAttributeUpdate:
    """UPDATE_ATTRIBUTE patches one typed attribute: not a statement, not the whole entity."""

    def test_a_declared_attribute_is_set_without_touching_the_rest_of_the_entity(
            self, tmp_path) -> None:
        memory = h.schema_memory_at(tmp_path, extra_fields={
            "organization": {"estado_operativo": {"name": "estado_operativo",
                                                  "value_type": "text"}}})
        identifiers = h.ids(memory)
        base = memory.current().version_id
        target = identifiers["entities"]["Cooperativa Faro Sur"]
        before = by_id(memory, target)
        result = edit(memory, "Corrige el estado operativo de esta instalación a operativo.", [
            attribute_operation("estado_operativo", "operativo", None, target=target,
                                antu_ref="Corrige el estado operativo")])
        assert result.status == "COMMITTED", result.to_dict()
        after = by_id(memory, target)
        assert after["metadata"]["estado_operativo"] == "operativo"
        # §5: the entity is patched, not replaced
        assert after["metadata"] == {**before["metadata"], "estado_operativo": "operativo"}
        assert after["name"] == before["name"]
        assert after["description"] == before["description"]
        assert after["evidence_ids"] == before["evidence_ids"]
        assert after["origin"]["kind"] == "DOCUMENT_EVIDENCE"
        revision = after["revisions"][-1]
        assert revision["attribute"] == "estado_operativo"
        assert revision["previous"] is None and revision["current"] == "operativo"
        # an attribute is not a statement: no assertion was invented
        assert len(memory.graph()["assertions"]) == len(memory.graph(base)["assertions"])
        assert relation(memory, "supervises")["to_entity"] == target
        assert "estado_operativo" not in by_id(memory, target, base).get("metadata", {})

    def test_an_undeclared_attribute_is_refused(self, tmp_path) -> None:
        memory = h.memory_at(tmp_path)
        target = h.ids(memory)["entities"]["Cooperativa Faro Sur"]
        base = memory.current().version_id
        result = edit(memory, "Corrige el estado operativo de esta instalación a operativo.", [
            attribute_operation("estado_operativo", "operativo", None, target=target,
                                antu_ref="Corrige el estado operativo")])
        assert result.status == "REJECTED", result.to_dict()
        assert [item["code"] for item in result.rejected] == ["ATTRIBUTE_NOT_DECLARED"]
        assert memory.current().version_id == base

    def test_a_value_of_the_wrong_type_is_refused(self, tmp_path) -> None:
        memory = h.schema_memory_at(tmp_path, extra_fields={
            "organization": {"plantilla": {"name": "plantilla", "value_type": "integer"}}})
        target = h.ids(memory)["entities"]["Cooperativa Faro Sur"]
        result = edit(memory, "Corrige la plantilla de la cooperativa a «doce personas».", [
            attribute_operation("plantilla", "doce personas", None, target=target,
                                antu_ref="plantilla de la cooperativa")])
        assert result.status == "REJECTED", result.to_dict()
        assert [item["code"] for item in result.rejected] == ["ATTRIBUTE_TYPE_MISMATCH"]

    def test_the_expected_value_is_mandatory(self, tmp_path) -> None:
        memory = h.schema_memory_at(tmp_path, extra_fields={
            "organization": {"estado_operativo": {"name": "estado_operativo",
                                                  "value_type": "text"}}})
        target = h.ids(memory)["entities"]["Cooperativa Faro Sur"]
        missing = edit(memory, "Corrige el estado operativo de la instalación a operativo.", [{
            "operation_id": "op-1", "op": "UPDATE_ATTRIBUTE", "target": {"entity_id": target},
            "expected": {"attribute": "otra_cosa", "value": None},
            "value": {"attribute": "estado_operativo", "value": "operativo"},
            "reason": "la instrucción corrige el atributo", "antu_ref": "estado operativo"}])
        assert [item["code"] for item in missing.rejected] == ["EXPECTED_VALUE_REQUIRED"]
        wrong = edit(memory, "El estado operativo de la instalación debe quedar en operativo.", [{
            "operation_id": "op-1", "op": "UPDATE_ATTRIBUTE", "target": {"entity_id": target},
            "expected": {"attribute": "estado_operativo", "value": "inactivo"},
            "value": {"attribute": "estado_operativo", "value": "operativo"},
            "reason": "la instrucción corrige el atributo", "antu_ref": "debe quedar en operativo"}])
        assert [item["code"] for item in wrong.rejected] == ["EXPECTED_VALUE_MISMATCH"]

    def test_declaring_the_attribute_and_setting_it_in_the_same_antu(self, tmp_path) -> None:
        memory = h.schema_memory_at(tmp_path)
        target = h.ids(memory)["entities"]["Cooperativa Faro Sur"]
        result = edit(memory, "Declara el atributo estado_operativo de tipo texto para las "
                              "organizaciones y ponlo en operativo para esta cooperativa.", [{
            "operation_id": "op-1", "op": "ADD_FIELD",
            "value": {"entity_type": "organization",
                      "field": {"name": "estado_operativo", "value_type": "text"}},
            "reason": "la instrucción declara el atributo",
            "antu_ref": "Declara el atributo estado_operativo de tipo texto"}, {
            "operation_id": "op-2", "op": "UPDATE_ATTRIBUTE", "depends_on": ["op-1"],
            "target": {"entity_id": target},
            "expected": {"attribute": "estado_operativo", "value": None},
            "value": {"attribute": "estado_operativo", "value": "operativo"},
            "reason": "la instrucción fija el valor para esta cooperativa",
            "antu_ref": "ponlo en operativo para esta cooperativa"}])
        assert result.status == "COMMITTED", result.to_dict()
        assert [item["outcome"] for item in result.outcomes] == ["COMMITTED", "COMMITTED"]
        declared = memory.graph()["schema"]["entity_types"]["organization"]["attributes"]
        assert "estado_operativo" in declared
        assert by_id(memory, target)["metadata"]["estado_operativo"] == "operativo"
        assert len(result.schema_changes) == 1

    def test_an_existing_attribute_value_is_corrected_and_the_previous_one_is_kept(
            self, tmp_path) -> None:
        memory = h.schema_memory_at(tmp_path, extra_fields={
            "organization": {"estado_operativo": {"name": "estado_operativo",
                                                  "value_type": "text"}}})
        target = h.ids(memory)["entities"]["Cooperativa Faro Sur"]
        first = edit(memory, "Corrige el estado operativo de esta instalación a operativo.", [
            attribute_operation("estado_operativo", "operativo", None, target=target,
                                antu_ref="Corrige el estado operativo")])
        assert first.status == "COMMITTED", first.to_dict()
        second = memory.apply_antu(
            "El estado operativo de la instalación es fuera de servicio, no operativo.",
            editor=h.ScriptedEditor(h.proposal([attribute_operation(
                "estado_operativo", "fuera de servicio", "operativo", target=target,
                antu_ref="fuera de servicio, no operativo")])))
        assert second.status == "COMMITTED", second.to_dict()
        assert second.version_id != first.version_id
        after = by_id(memory, target)
        assert after["metadata"]["estado_operativo"] == "fuera de servicio"
        assert after["revisions"][-1]["previous"] == "operativo"
        assert after["revisions"][-1]["current"] == "fuera de servicio"
        # the previous version still says "operativo" and is still verifiable
        assert by_id(memory, target, first.version_id)["metadata"]["estado_operativo"] == \
            "operativo"
        assert memory.verify()["ok"] is True

    def test_an_empty_name_or_a_missing_expected_value_is_refused(self, tmp_path) -> None:
        memory = h.memory_at(tmp_path)
        identifiers = h.ids(memory)
        target = identifiers["entities"]["Cooperativa Faro Sur"]
        empty = edit(memory, "Deja la denominación de la cooperativa vacía.", [{
            "operation_id": "op-1", "op": "UPDATE_ENTITY", "target": {"entity_id": target},
            "expected": {"name": "Cooperativa Faro Sur"}, "value": {"name": "  "},
            "reason": "la instrucción pide vaciar el nombre", "antu_ref": "la denominación vacía",
        }])
        assert [item["code"] for item in empty.rejected] == ["VALUE_INCOMPLETE"]
        unchecked = edit(memory, "Cambia la denominación de la cooperativa.", [{
            "operation_id": "op-1", "op": "UPDATE_ENTITY", "target": {"entity_id": target},
            "value": {"name": "Otra cosa"},
            "reason": "la instrucción cambia el nombre", "antu_ref": "Cambia la denominación",
        }])
        assert [item["code"] for item in unchecked.rejected] == ["EXPECTED_VALUE_REQUIRED"]

    def test_an_ambiguous_entity_instruction_asks_for_clarification(self, tmp_path) -> None:
        memory = two_organizations(tmp_path)
        base = memory.current().version_id
        payload = h.proposal([], status="CLARIFICATION_REQUIRED",
                             clarification={"question": "¿Cuál de las dos cooperativas?",
                                            "candidates": ["Cooperativa Faro Sur",
                                                           "Cooperativa Faro Norte"]})
        result = memory.apply_antu("Actualiza la denominación de la cooperativa",
                                   editor=h.ScriptedEditor(payload))
        assert result.status == "CLARIFICATION_REQUIRED"
        assert result.outcome == "NEEDS_CLARIFICATION"
        assert result.committed is False and memory.current().version_id == base
        assert len(memory.versions()) == 1


LONG_INSTRUCTION = (
    "Revisando la ficha de la Cooperativa Faro Sur con el acta de la asamblea, queda claro que "
    "hay tres cosas que corregir en este KÜYEN. Primero, la denominación oficial de la "
    "organización es «Cooperativa Faro Sur de Los Aromos» y así debe figurar en la ficha, "
    "manteniendo la identidad que ya tiene. Segundo, la cooperativa depende administrativamente "
    "de Camila Soto, una relación que todavía no está registrada y que hay que incorporar entre "
    "las dos entidades existentes. Tercero, el estado operativo que arrastra la ficha es "
    "«inactivo» cuando la asamblea aprobó que la instalación está «operativa», así que corrige "
    "ese atributo. Son tres cambios distintos: no los mezcles ni omitas ninguno."
)


class TestLongAndMultipleInstructions:
    """A long instruction with several changes must produce every change, not a summary."""

    def test_a_long_instruction_with_three_changes_produces_three_committed_operations(
            self, tmp_path) -> None:
        memory = h.schema_memory_at(tmp_path, extra_fields={
            "organization": {"estado_operativo": {"name": "estado_operativo",
                                                  "value_type": "text"}}})
        identifiers = h.ids(memory)
        target = identifiers["entities"]["Cooperativa Faro Sur"]
        # the ficha already carries the attribute the long instruction corrects
        seeded = edit(memory, "Registra el estado operativo de la instalación como inactivo.", [
            attribute_operation("estado_operativo", "inactivo", None, target=target,
                                antu_ref="estado operativo de la instalación")])
        assert seeded.status == "COMMITTED", seeded.to_dict()
        base = seeded.version_id
        result = edit(memory, LONG_INSTRUCTION, [{
            "operation_id": "op-1", "op": "UPDATE_ENTITY", "target": {"entity_id": target},
            "expected": {"name": "Cooperativa Faro Sur"},
            "value": {"name": "Cooperativa Faro Sur de Los Aromos"},
            "reason": "la instrucción da la denominación oficial",
            "antu_ref": "la denominación oficial de la organización es «Cooperativa Faro Sur "
                        "de Los Aromos»",
        }, {
            "operation_id": "op-2", "op": "ADD_RELATION",
            "value": {"from": target, "to": identifiers["entities"]["Camila Soto"],
                      "predicate": "reports_to", "label": "depende de", "polarity": "POSITIVE"},
            "reason": "la instrucción incorpora la dependencia",
            "antu_ref": "la cooperativa depende administrativamente de Camila Soto",
        }, {
            "operation_id": "op-3", "op": "UPDATE_ATTRIBUTE", "target": {"entity_id": target},
            "expected": {"attribute": "estado_operativo", "value": "inactivo"},
            "value": {"attribute": "estado_operativo", "value": "operativa"},
            "reason": "la instrucción corrige el atributo de la ficha",
            "antu_ref": "el estado operativo que arrastra la ficha es «inactivo»",
        }])
        # the stored attribute has to be there for the third operation to be possible
        assert result.status == "COMMITTED", result.to_dict()
        assert [item["outcome"] for item in result.outcomes] == ["COMMITTED"] * 3
        assert result.committed is True
        versions = [item.version_id for item in memory.versions()]
        assert versions[-1] == result.version_id and len(versions) == 3
        graph = memory.graph()
        assert by_id(memory, target)["name"] == "Cooperativa Faro Sur de Los Aromos"
        assert by_id(memory, target)["metadata"]["estado_operativo"] == "operativa"
        assert any(item["predicate"] == "reports_to" for item in graph["relations"])
        # one version carries all three changes and the previous one carries none
        assert graph["version"] != memory.graph(base)["version"]
        assert by_id(memory, target, base)["name"] == "Cooperativa Faro Sur"
        assert by_id(memory, target, base)["metadata"]["estado_operativo"] == "inactivo"
        assert all(item["predicate"] != "reports_to"
                   for item in memory.graph(base)["relations"])
        assert memory.verify()["ok"] is True

    def test_a_clear_part_is_committed_while_an_ambiguous_part_asks_for_clarification(
            self, tmp_path) -> None:
        memory = h.schema_memory_at(tmp_path)
        identifiers = h.ids(memory)
        target = identifiers["entities"]["Cooperativa Faro Sur"]
        instruction = ("Corrige la denominación de la cooperativa a Cooperativa Faro Sur de Los "
                       "Aromos y, además, ajusta la fecha de la instalación que no sé a cuál de "
                       "las dos afirmaciones se refiere.")
        result = edit(memory, instruction, [{
            "operation_id": "op-1", "op": "UPDATE_ENTITY", "target": {"entity_id": target},
            "expected": {"name": "Cooperativa Faro Sur"},
            "value": {"name": "Cooperativa Faro Sur de Los Aromos"},
            "reason": "la instrucción da la denominación correcta",
            "antu_ref": "Corrige la denominación de la cooperativa a Cooperativa Faro Sur de "
                        "Los Aromos",
        }, {
            "operation_id": "op-2", "op": "UPDATE_ASSERTION",
            "applicability": "NEEDS_CLARIFICATION",
            "target": {"assertion_id": identifiers["assertions"]["started_at"]},
            "explanation": "hay dos afirmaciones de fecha y la instrucción no dice cuál",
            "antu_ref": "ajusta la fecha de la instalación",
        }])
        assert result.status == "COMMITTED", result.to_dict()
        assert result.outcome == "COMMITTED"
        # a mixed Antü keeps one state per operation instead of one uniform result
        assert result.applicability == {"APPLICABLE": 1, "NEEDS_CLARIFICATION": 1}
        assert result.declined[0]["verified"] is False
        assert [item["outcome"] for item in result.outcomes] == ["COMMITTED",
                                                                "NEEDS_CLARIFICATION"]
        assert by_id(memory, target)["name"] == "Cooperativa Faro Sur de Los Aromos"


class TestOutcomeClassification:
    """A limitation of the interpretation is never reported as an absence of change."""

    def test_a_justified_no_changes_creates_no_version(self, tmp_path) -> None:
        memory = h.memory_at(tmp_path)
        base = memory.current().version_id
        payload = h.proposal([], status="NO_CHANGES",
                             interpretation="la afirmación ya dice 12 luminarias")
        result = memory.apply_antu("Confirma que son 12 luminarias",
                                   editor=h.ScriptedEditor(payload))
        assert result.status == "NO_CHANGES"
        assert result.outcome == "NO_CHANGES"
        assert result.committed is False and memory.current().version_id == base
        assert any("nothing to change" in reason for reason in result.reasons)

    def test_no_changes_without_an_explanation_is_an_incomplete_interpretation(
            self, tmp_path) -> None:
        memory = h.memory_at(tmp_path)
        base = memory.current().version_id
        payload = {"schema_version": "kuyen-graph-edit-v2", "status": "NO_CHANGES",
                   "operations": []}
        result = memory.apply_antu("Revisa el acta y corrige lo que haga falta",
                                   editor=h.ScriptedEditor(payload))
        # §6: an editor that produced nothing and explained nothing has not interpreted the
        # instruction; recording NO_CHANGES would turn a limitation into a fact.
        assert result.status == "INTERPRETATION_INCOMPLETE", result.to_dict()
        assert result.outcome == "EXECUTION_FAILED"
        assert result.committed is False and memory.current().version_id == base
        assert any("NO_OPERATION_WITHOUT_EXPLANATION" in reason for reason in result.reasons)
        events = [event for event in memory.ledger() if event.get("antu_id") == result.antu_id]
        rejected = [event for event in events if event["event_type"] == "ANTU_REJECTED"]
        assert rejected[-1]["status"] == "INTERPRETATION_INCOMPLETE"
        assert rejected[-1]["code"] == "NO_OPERATION_WITHOUT_EXPLANATION"

    def test_a_proposal_that_says_no_changes_and_declares_operations_is_validated(
            self, tmp_path) -> None:
        memory = h.memory_at(tmp_path)
        identifiers = h.ids(memory)
        payload = h.proposal([{
            "operation_id": "op-1", "op": "ADD_RELATION",
            "value": {"from": identifiers["entities"]["Cooperativa Faro Sur"],
                      "to": identifiers["entities"]["Camila Soto"],
                      "predicate": "reports_to", "polarity": "POSITIVE"},
            "reason": "la instrucción declara la dependencia", "antu_ref": "depende de Camila",
        }], status="NO_CHANGES", interpretation="")
        result = memory.apply_antu("La cooperativa depende de Camila Soto: agrega esa relación.",
                                   editor=h.ScriptedEditor(payload))
        # the operations are the substance: they are validated instead of being discarded
        assert result.status == "COMMITTED", result.to_dict()
        assert result.outcome == "COMMITTED"
        assert any("PROPOSAL_STATUS_CONTRADICTED" in reason for reason in result.reasons)
        assert any(item["predicate"] == "reports_to" for item in memory.graph()["relations"])

    def test_an_unreadable_response_is_an_execution_failure(self, tmp_path) -> None:
        memory = h.memory_at(tmp_path)
        base = memory.current().version_id
        result = memory.apply_antu("Corrige la cantidad a 18",
                                   editor=h.ScriptedEditor("```no json```"))
        assert result.status == "INTERPRETATION_FAILED"
        assert result.outcome == "EXECUTION_FAILED"
        assert memory.current().version_id == base
        assert len(memory.versions()) == 1


    def test_declines_with_different_reasons_do_not_invent_one_result(self, tmp_path) -> None:
        memory = h.schema_memory_at(tmp_path)
        base = memory.current().version_id
        result = edit(memory, "Asegura que las personas tengan un RUT y documenta el "
                              "procedimiento", [{
            "operation_id": "op-1", "op": "ADD_FIELD",
            "applicability": "ALREADY_SATISFIED",
            "value": {"entity_type": "person", "field": {"name": "description"}},
            "explanation": "person ya declara el campo description en el esquema visible",
            "antu_ref": "las personas tengan un RUT"}, {
            "operation_id": "op-2", "op": "ADD_FIELD",
            "applicability": "OUT_OF_SCOPE",
            "value": {"entity_type": "person", "field": {"name": "rut"}},
            "explanation": "documentar un procedimiento es lógica de aplicación, no memoria",
            "antu_ref": "documenta el procedimiento"}])
        assert result.status == "NO_CHANGES", result.to_dict()
        # two different declarative reasons are not one state
        assert result.outcome == "NO_CHANGES"
        assert result.applicability == {"ALREADY_SATISFIED": 1, "OUT_OF_SCOPE": 1}
        assert memory.current().version_id == base

    def test_a_uniform_decline_reports_its_own_outcome(self, tmp_path) -> None:
        memory = h.schema_memory_at(tmp_path)
        result = edit(memory, "Documenta el procedimiento de ingreso de las personas", [{
            "operation_id": "op-1", "op": "ADD_FIELD",
            "applicability": "OUT_OF_SCOPE",
            "value": {"entity_type": "person", "field": {"name": "rut"}},
            "explanation": "un procedimiento es comportamiento, no estructura de la memoria",
            "antu_ref": "Documenta el procedimiento"}])
        assert result.status == "NO_CHANGES"
        assert result.outcome == "OUT_OF_SCOPE"
        assert [item["outcome"] for item in result.outcomes] == ["OUT_OF_SCOPE"]

    def test_a_dry_run_is_not_reported_as_committed(self, tmp_path) -> None:
        memory = h.memory_at(tmp_path)
        identifiers = h.ids(memory)
        base = memory.current().version_id
        payload = h.proposal([{
            "operation_id": "op-1", "op": "UPDATE_ENTITY",
            "target": {"entity_id": identifiers["entities"]["Cooperativa Faro Sur"]},
            "expected": {"name": "Cooperativa Faro Sur"},
            "value": {"name": "Cooperativa Faro Sur de Los Aromos"},
            "reason": "la instrucción corrige la denominación",
            "antu_ref": "corrige la denominación"}])
        result = memory.apply_antu("Corrige la denominación de la cooperativa",
                                   editor=h.ScriptedEditor(payload), dry_run=True)
        assert result.status == "VALIDATED", result.to_dict()
        assert result.outcome == "NOT_EVALUATED"
        assert result.committed is False
        assert memory.current().version_id == base
        assert len(memory.versions()) == 1
        assert [item["outcome"] for item in result.outcomes] == ["NOT_EVALUATED"]

    def test_a_replayed_antu_reports_the_history_instead_of_a_new_change(self, tmp_path) -> None:
        memory = h.memory_at(tmp_path)
        identifiers = h.ids(memory)
        payload = h.proposal([{
            "operation_id": "op-1", "op": "UPDATE_ENTITY",
            "target": {"entity_id": identifiers["entities"]["Cooperativa Faro Sur"]},
            "expected": {"name": "Cooperativa Faro Sur"},
            "value": {"name": "Cooperativa Faro Sur de Los Aromos"},
            "reason": "la instrucción corrige la denominación",
            "antu_ref": "corrige la denominación"}])
        first = memory.apply_antu("Corrige la denominación de la cooperativa",
                                  editor=h.ScriptedEditor(payload))
        assert first.committed is True and first.outcome == "COMMITTED"
        second = memory.apply_antu("Corrige la denominación de la cooperativa",
                                   editor=h.ScriptedEditor(payload))
        assert second.status == "REPLAYED"
        assert second.outcome == "ALREADY_SATISFIED"
        assert len(memory.versions()) == 2

    def test_one_refused_operation_discards_the_whole_proposal(self, tmp_path) -> None:
        memory = h.memory_at(tmp_path)
        identifiers = h.ids(memory)
        base = memory.current().version_id
        result = edit(memory, "Agrega la dependencia de la cooperativa y cambia el nombre de una "
                              "entidad que no existe", [{
            "operation_id": "op-1", "op": "ADD_RELATION",
            "value": {"from": identifiers["entities"]["Cooperativa Faro Sur"],
                      "to": identifiers["entities"]["Camila Soto"],
                      "predicate": "reports_to", "polarity": "POSITIVE"},
            "reason": "la instrucción declara la dependencia", "antu_ref": "Agrega la dependencia",
        }, {
            "operation_id": "op-2", "op": "UPDATE_ENTITY",
            "target": {"entity_id": "ent_" + "e" * 20},
            "expected": {"name": "Nadie"}, "value": {"name": "Otra"},
            "reason": "la instrucción cambia un nombre", "antu_ref": "cambia el nombre",
        }])
        assert result.status == "REJECTED", result.to_dict()
        assert [item["code"] for item in result.rejected] == ["TARGET_NOT_FOUND"]
        # nothing was applied: a rejected Antü never reaches the applier, and the operation
        # that would have been valid is never reported as confirmed
        assert result.applied == []
        assert [item["status"] for item in result.operations] == ["VALIDATED"]
        assert [item["outcome"] for item in result.outcomes] == ["NOT_EVALUATED",
                                                                "INVALID_PROPOSAL"]
        assert memory.current().version_id == base
        assert all(item["predicate"] != "reports_to" for item in memory.graph()["relations"])



class TestNormalisation:
    """A valid proposal nested in the wrong object is read, not discarded (experiment 15 §6)."""

    def test_operations_nested_inside_the_reference_envelope_are_read(self, tmp_path) -> None:
        memory = h.memory_at(tmp_path)
        identifiers = h.ids(memory)
        operation = {
            "operation_id": "op-1", "op": "ADD_RELATION",
            "value": {"from": identifiers["entities"]["Cooperativa Faro Sur"],
                      "to": identifiers["entities"]["Camila Soto"],
                      "predicate": "reports_to", "polarity": "POSITIVE"},
            "reason": "la instrucción declara la dependencia", "antu_ref": "depende de Camila"}
        # the shape a real model returned: the operations live inside `contract`
        payload = {"status": "PROPOSED", "contract": {
            "schema_version": "kuyen-graph-edit-v2", "operations": [operation]}}
        result = memory.apply_antu("La cooperativa depende de Camila Soto: agrega esa relación.",
                                   editor=h.ScriptedEditor(payload))
        assert result.status == "COMMITTED", result.to_dict()
        assert result.run.proposal.warnings
        assert any("nested inside `contract`" in warning
                   for warning in result.run.proposal.warnings)
        assert any(item["predicate"] == "reports_to" for item in memory.graph()["relations"])

    def test_a_nested_status_is_read_when_the_root_declares_none(self, tmp_path) -> None:
        memory = h.memory_at(tmp_path)
        payload = {"proposal": {"status": "CLARIFICATION_REQUIRED",
                                "clarification": {"question": "¿Qué fecha?"},
                                "operations": []}}
        result = memory.apply_antu("Corrige la fecha", editor=h.ScriptedEditor(payload))
        assert result.status == "CLARIFICATION_REQUIRED"
        assert result.outcome == "NEEDS_CLARIFICATION"
        assert result.clarification["question"] == "¿Qué fecha?"

    def test_root_operations_take_precedence_over_a_nested_copy(self, tmp_path) -> None:
        memory = h.memory_at(tmp_path)
        identifiers = h.ids(memory)
        operation = {
            "operation_id": "op-1", "op": "ADD_RELATION",
            "value": {"from": identifiers["entities"]["Cooperativa Faro Sur"],
                      "to": identifiers["entities"]["Camila Soto"],
                      "predicate": "reports_to", "polarity": "POSITIVE"},
            "reason": "la instrucción declara la dependencia", "antu_ref": "depende de Camila"}
        payload = h.proposal([operation], contract={"operations": [operation, operation]})
        result = memory.apply_antu("La cooperativa depende de Camila Soto: agrega esa relación.",
                                   editor=h.ScriptedEditor(payload))
        assert result.status == "COMMITTED", result.to_dict()
        assert len(result.applied) == 1


class TestVerifiableDeclines:
    """An ALREADY_SATISFIED claim is accepted only when KÜYEN can verify it (experiment 15)."""

    def test_a_relation_claim_is_verified_from_the_statement_itself(self, tmp_path) -> None:
        memory = h.memory_at(tmp_path)
        identifiers = h.ids(memory)
        base = memory.current().version_id
        result = edit(memory, "Confirma que Camila Soto supervisa a la cooperativa.", [{
            "operation_id": "op-1", "op": "ADD_RELATION",
            "applicability": "ALREADY_SATISFIED",
            "value": {"from": identifiers["entities"]["Camila Soto"],
                      "to": identifiers["entities"]["Cooperativa Faro Sur"],
                      "predicate": "supervises", "polarity": "POSITIVE"},
            "explanation": "la relación supervises ya existe entre las dos entidades",
            "reason": "la instrucción sólo pide confirmar", "antu_ref": "Camila Soto supervisa",
        }])
        assert result.status == "NO_CHANGES", result.to_dict()
        assert result.outcome == "ALREADY_SATISFIED"
        assert result.declined[0]["verified"] is True
        assert memory.current().version_id == base

    def test_a_claim_the_graph_contradicts_is_refused(self, tmp_path) -> None:
        memory = h.memory_at(tmp_path)
        identifiers = h.ids(memory)
        result = edit(memory, "Confirma que la cooperativa financia a Camila Soto.", [{
            "operation_id": "op-1", "op": "ADD_RELATION",
            "applicability": "ALREADY_SATISFIED",
            "value": {"from": identifiers["entities"]["Cooperativa Faro Sur"],
                      "to": identifiers["entities"]["Camila Soto"],
                      "predicate": "funds", "polarity": "POSITIVE"},
            "explanation": "esa relación ya existe",
            "reason": "la instrucción sólo pide confirmar", "antu_ref": "la cooperativa financia",
        }])
        assert result.status == "REJECTED", result.to_dict()
        assert [item["code"] for item in result.rejected] == [
            "APPLICABILITY_CLAIM_UNSUPPORTED"]

    def test_a_claim_of_not_retracted_is_verifiable_when_the_key_is_absent(self, tmp_path) -> None:
        memory = h.memory_at(tmp_path)
        identifiers = h.ids(memory)
        existing = identifiers["relations"]["supervises"]
        result = edit(memory, "La relación de supervisión sigue vigente: confírmalo.", [{
            "operation_id": "op-1", "op": "UPDATE_RELATION",
            "applicability": "ALREADY_SATISFIED",
            "target": {"relation_id": existing},
            "expected": {"predicate": "supervises", "retracted": False},
            "explanation": "la relación sigue vigente y no está retirada",
            "reason": "la instrucción sólo pide confirmar", "antu_ref": "sigue vigente",
        }])
        assert result.status == "NO_CHANGES", result.to_dict()
        assert result.outcome == "ALREADY_SATISFIED"
        assert result.declined[0]["verified"] is True

        assert not result.run.proposal.warnings


    def test_an_entity_without_an_origin_gets_its_documentary_support_named(self, tmp_path) -> None:
        """Compiled records carry no per-object origin; a patch says where the entity comes from.

        The entity keeps the evidence it already had, and the applier names that support instead
        of leaving the origin empty or claiming the instruction as the source (experiment 15).
        """
        value = h.graph()
        for item in value["entities"]:
            item.pop("origin", None)
        memory = KuyenMemory.create(tmp_path / "no-origin", leftraru_id="LR-NO-ORIGIN")
        memory.import_canonical(
            build_document(value, {h.MAPU_ID: h.TEXT}, mapu_versions={h.MAPU_ID: "1.0.0"},
                           source_uris={h.MAPU_ID: h.SOURCE_URI}),
            antu_id="ANTU-FIXTURE-NO-ORIGIN")
        target = h.ids(memory)["entities"]["Cooperativa Faro Sur"]
        result = edit(memory, "Actualiza la denominación de la organización a Cooperativa Faro "
                              "Sur de Los Aromos.", [{
            "operation_id": "op-1", "op": "UPDATE_ENTITY", "target": {"entity_id": target},
            "expected": {"name": "Cooperativa Faro Sur"},
            "value": {"name": "Cooperativa Faro Sur de Los Aromos"},
            "reason": "la instrucción corrige la denominación",
            "antu_ref": "Actualiza la denominación de la organización"}])
        assert result.status == "COMMITTED", result.to_dict()
        after = by_id(memory, target)
        assert after["origin"]["kind"] == "DOCUMENT_EVIDENCE"
        assert after["origin"]["evidence_ids"] == after["evidence_ids"]
        assert after["origin"]["evidence_ids"]

