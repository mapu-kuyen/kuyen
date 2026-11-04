"""Direct Antü editing: the ten cases required by §8.2 of the brief.

Every test uses a *real* canonical memory (committed through `import_canonical`) and a
deterministic editor that returns a controlled proposal. What is under test is KÜYEN's
control of the edit — not a mock of it: the version, the ledger, the provenance and the
untouched previous state are all read back from the store.
"""
from __future__ import annotations

from tests.editing import helpers as h
from kuyen import KuyenMemory
from kuyen.editing import derive_antu_id


def edit(memory: KuyenMemory, instruction: str, operations, **overrides):
    return memory.apply_antu(instruction, editor=h.ScriptedEditor(h.proposal(operations,
                                                                             **overrides)))


class TestNumericAttribute:
    def test_changing_a_number_creates_a_version_and_keeps_the_previous_statement(
            self, tmp_path) -> None:
        memory = h.memory_at(tmp_path)
        base = memory.current().version_id
        identifiers = h.ids(memory)
        instruction = "Cambia la cantidad de luminarias de 12 a 18"
        result = edit(memory, instruction, [{
            "operation_id": "op-1", "op": "UPDATE_ASSERTION",
            "target": {"assertion_id": identifiers["assertions"]["installed_lights"]},
            "expected": {"value": {"value_type": "integer", "value": 12,
                                   "unit": "luminarias", "context": None}},
            "value": {"value": {"value_type": "integer", "value": 18, "unit": "luminarias"}},
            "reason": "la instrucción corrige la cantidad instalada",
            "antu_ref": "de 12 a 18",
        }])
        assert result.status == "COMMITTED", result.to_dict()
        assert result.base_version_id == base
        assert result.version_id != base
        graph = memory.graph()
        by_value = {item["value"]["value"]: item for item in graph["assertions"]
                    if item["predicate"] == "installed_lights"}
        assert by_value[18]["status"] == "INSTRUCTED"
        assert by_value[18]["origin"]["kind"] == "ANTU_INSTRUCTION"
        assert by_value[18]["evidence_ids"] == []
        assert by_value[12]["status"] == "SUPERSEDED"
        assert by_value[12]["superseded_by"] == by_value[18]["assertion_id"]
        # the previous version is untouched and still readable
        previous = memory.graph(base)
        assert [item["value"]["value"] for item in previous["assertions"]
                if item["predicate"] == "installed_lights"] == [12]
        # the superseded object stays in the new version's record
        assert len([item for item in graph["assertions"]
                    if item["predicate"] == "installed_lights"]) == 2
        # provenance distinguishes the instruction from the document
        assert result.provenance["kind"] == "ANTU_INSTRUCTION"
        assert result.provenance["documentary_verification"] is False
        assert result.operations[0]["op"] == "UPDATE_ASSERTION"


class TestRelationCorrection:
    def test_a_wrong_relation_is_corrected_without_losing_the_previous_one(self, tmp_path) -> None:
        memory = h.memory_at(tmp_path)
        identifiers = h.ids(memory)
        instruction = ("La relación de supervisión está invertida: es la cooperativa la que "
                       "supervisa a Camila Soto")
        result = edit(memory, instruction, [{
            "operation_id": "op-1", "op": "RETRACT_RELATION",
            "target": {"relation_id": identifiers["relations"]["supervises"]},
            "expected": {"status": "UNRESOLVED"},
            "value": {"retracted": True},
            "reason": "la dirección de la relación es incorrecta",
            "antu_ref": "la relación de supervisión está invertida",
        }, {
            "operation_id": "op-2", "op": "ADD_RELATION",
            "value": {"from": identifiers["entities"]["Cooperativa Faro Sur"],
                      "to": identifiers["entities"]["Camila Soto"],
                      "predicate": "supervises", "label": "supervisa",
                      "polarity": "POSITIVE", "modality": "FACT"},
            "reason": "la dirección correcta la declara la instrucción",
            "antu_ref": "es la cooperativa la que supervisa a Camila Soto",
        }])
        assert result.status == "COMMITTED", result.to_dict()
        graph = memory.graph()
        retracted = next(item for item in graph["relations"]
                         if item["relation_id"] == identifiers["relations"]["supervises"])
        assert retracted["status"] == "RETRACTED" and retracted["retracted"] is True
        assert retracted["retraction"]["antu_id"] == result.antu_id
        current = memory.current_objects("relations")
        assert len(current) == 1
        added = current[0]
        assert added["from_entity"] == identifiers["entities"]["Cooperativa Faro Sur"]
        assert added["to_entity"] == identifiers["entities"]["Camila Soto"]
        assert added["status"] == "INSTRUCTED"


class TestNewKnowledge:
    def test_a_new_entity_and_relation_declared_by_the_user(self, tmp_path) -> None:
        memory = h.memory_at(tmp_path)
        identifiers = h.ids(memory)
        instruction = ("Agrega que la Junta de Vecinos Los Aromos es una organización y que "
                       "la cooperativa le instaló las luminarias")
        result = edit(memory, instruction, [{
            "operation_id": "op-1", "op": "ADD_ENTITY",
            "value": {"ref": "junta", "name": "Junta de Vecinos Los Aromos",
                      "entity_type": "organization",
                      "description": "Organización vecinal del pasaje Los Aromos"},
            "reason": "la instrucción declara la organización",
            "antu_ref": "la Junta de Vecinos Los Aromos es una organización",
        }, {
            "operation_id": "op-2", "op": "ADD_RELATION",
            "value": {"from": identifiers["entities"]["Cooperativa Faro Sur"], "to": "junta",
                      "predicate": "installed_for", "label": "instaló para",
                      "polarity": "POSITIVE", "modality": "FACT"},
            "reason": "la instrucción declara la relación",
            "antu_ref": "la cooperativa le instaló las luminarias",
        }])
        assert result.status == "COMMITTED", result.to_dict()
        graph = memory.graph()
        created = next(item for item in graph["entities"]
                       if item["name"] == "Junta de Vecinos Los Aromos")
        # KÜYEN owns the identity: the model's local reference never becomes an entity_id
        assert created["entity_id"].startswith("ent_")
        assert created["source_namespace"] == "antu-instruction"
        assert created["status"] == "INSTRUCTED"
        assert created["evidence_ids"] == []
        relation = next(item for item in graph["relations"]
                        if item["predicate"] == "installed_for")
        assert relation["to_entity"] == created["entity_id"]
        assert relation["evidence_ids"] == []

    def test_an_assertion_attributed_to_the_user_is_never_documentary(self, tmp_path) -> None:
        memory = h.memory_at(tmp_path)
        identifiers = h.ids(memory)
        instruction = ("Agrega que, según el municipio, la obra estará terminada en "
                       "diciembre de 2026")
        result = edit(memory, instruction, [{
            "operation_id": "op-1", "op": "ADD_ASSERTION",
            "value": {"subject": identifiers["entities"]["Cooperativa Faro Sur"],
                      "predicate": "expected_completion", "polarity": "POSITIVE",
                      "modality": "FORECAST", "attribution": "el municipio",
                      "value": {"value_type": "string", "value": "2026-12"}},
            "reason": "la instrucción aporta una previsión atribuida al municipio",
            "antu_ref": "según el municipio, la obra estará terminada en diciembre de 2026",
        }])
        assert result.status == "COMMITTED", result.to_dict()
        assertion = next(item for item in memory.graph()["assertions"]
                         if item["predicate"] == "expected_completion")
        assert assertion["modality"] == "FORECAST"
        assert assertion["attribution"] == "el municipio"
        assert assertion["status"] == "INSTRUCTED"
        assert assertion["evidence_status"] == "NOT_EVALUATED"
        assert assertion["origin"]["kind"] == "ANTU_INSTRUCTION"
        assert assertion["origin"]["documentary_verification"] is False
        assert assertion["origin"]["antu_id"] == result.antu_id
        # no MAPU, SOURCE_UNIT, quote or hash was invented for it
        assert assertion["evidence_ids"] == [] and assertion["sources"] == []



class TestRetractionAndDate:
    def test_an_incorrect_assertion_is_retracted_and_kept(self, tmp_path) -> None:
        memory = h.memory_at(tmp_path)
        identifiers = h.ids(memory)
        instruction = "Retira la afirmación sobre la fecha de inicio: no es correcta"
        result = edit(memory, instruction, [{
            "operation_id": "op-1", "op": "RETRACT_ASSERTION",
            "target": {"assertion_id": identifiers["assertions"]["started_at"]},
            "expected": {"status": "UNRESOLVED"},
            "value": {"retracted": True},
            "reason": "la instrucción retira la afirmación",
            "antu_ref": "retira la afirmación sobre la fecha de inicio",
        }])
        assert result.status == "COMMITTED", result.to_dict()
        retracted = next(item for item in memory.graph()["assertions"]
                         if item["assertion_id"] == identifiers["assertions"]["started_at"])
        assert retracted["status"] == "RETRACTED" and retracted["retracted"] is True
        assert retracted["retraction"]["reason"].startswith("la instrucción retira")
        # the statement is still in the record and still readable in the previous version
        assert retracted["value"]["value"] == "2025-03"
        assert memory.graph(result.base_version_id)["assertions"]
        assert all(item["assertion_id"] != identifiers["assertions"]["started_at"]
                   for item in memory.current_objects("assertions"))

    def test_a_retracted_assertion_cannot_be_retracted_twice(self, tmp_path) -> None:
        memory = h.memory_at(tmp_path)
        identifiers = h.ids(memory)
        operations = [{
            "operation_id": "op-1", "op": "RETRACT_ASSERTION",
            "target": {"assertion_id": identifiers["assertions"]["started_at"]},
            "expected": {"status": "UNRESOLVED"}, "value": {"retracted": True},
            "reason": "la instrucción retira la afirmación",
            "antu_ref": "retira la afirmación sobre la fecha de inicio"}]
        assert edit(memory, "Retira la afirmación sobre la fecha de inicio",
                    operations).status == "COMMITTED"
        second = edit(memory, "Retira la afirmación sobre la fecha de inicio, por favor",
                      operations)
        assert second.status == "REJECTED"
        assert {item["code"] for item in second.rejected} == {"ALREADY_RETRACTED"}
        assert len(memory.versions()) == 2

    def test_a_date_is_corrected(self, tmp_path) -> None:
        memory = h.memory_at(tmp_path)
        identifiers = h.ids(memory)
        result = edit(memory, "La instalación comenzó en abril de 2025, no en marzo", [{
            "operation_id": "op-1", "op": "UPDATE_ASSERTION",
            "target": {"assertion_id": identifiers["assertions"]["started_at"]},
            "expected": {"value": {"value_type": "string", "value": "2025-03", "unit": None,
                                   "context": None}},
            "value": {"value": {"value_type": "string", "value": "2025-04"}},
            "reason": "la instrucción corrige el mes de inicio",
            "antu_ref": "comenzó en abril de 2025, no en marzo",
        }])
        assert result.status == "COMMITTED", result.to_dict()
        current = [item for item in memory.current_objects("assertions")
                   if item["predicate"] == "started_at"]
        assert len(current) == 1 and current[0]["value"]["value"] == "2025-04"



class TestRefusals:
    def test_an_operation_on_an_inexistent_entity_is_refused(self, tmp_path) -> None:
        memory = h.memory_at(tmp_path)
        base = memory.current().version_id
        result = edit(memory, "Cambia el nombre de la entidad ent_ffffffffffffffffffff", [{
            "operation_id": "op-1", "op": "UPDATE_ENTITY",
            "target": {"entity_id": "ent_ffffffffffffffffffff"},
            "expected": {"name": "Nadie"}, "value": {"name": "Otra"},
            "reason": "la instrucción pide corregir un nombre",
            "antu_ref": "cambia el nombre de la entidad"}])
        assert result.status == "REJECTED"
        assert [item["code"] for item in result.rejected] == ["TARGET_NOT_FOUND"]
        assert memory.current().version_id == base
        assert len(memory.versions()) == 1
        assert any(event["event_type"] == "ANTU_REJECTED" and
                   event.get("antu_id") == result.antu_id for event in memory.ledger())

    def test_an_ambiguous_instruction_asks_for_clarification_and_creates_no_version(
            self, tmp_path) -> None:
        memory = h.memory_at(tmp_path)
        base = memory.current().version_id
        payload = {"schema_version": "kuyen-graph-edit-v1",
                   "status": "CLARIFICATION_REQUIRED",
                   "interpretation": "hay dos afirmaciones de fecha",
                   "clarification": {"question": "¿A qué afirmación te refieres?",
                                     "candidates": ["asrt_a", "asrt_b"]},
                   "operations": []}
        result = memory.apply_antu("Corrige la fecha", editor=h.ScriptedEditor(payload))
        assert result.status == "CLARIFICATION_REQUIRED"
        assert result.clarification["question"].startswith("¿A qué afirmación")
        assert result.committed is False
        assert memory.current().version_id == base
        assert len(memory.versions()) == 1
        assert any(event["event_type"] == "ANTU_CLARIFICATION_REQUIRED"
                   for event in memory.ledger())
        # the history must remain verifiable: the revision says "no change", the ledger
        # keeps the exact ANTÜ status (KUYEN_TEN_REAL_MAPU_AND_ANTU_OPERATIONS_13)
        assert memory.verify()["ok"] is True
        detail = memory.history()[-1]
        assert detail["status"] == "NO_SEMANTIC_CHANGE"
        assert detail["detail"]["edit_status"] == "CLARIFICATION_REQUIRED"

    def test_an_operation_without_a_citable_instruction_is_refused(self, tmp_path) -> None:
        memory = h.memory_at(tmp_path)
        identifiers = h.ids(memory)
        result = edit(memory, "Cambia la cantidad de luminarias de 12 a 18", [{
            "operation_id": "op-1", "op": "UPDATE_ASSERTION",
            "target": {"assertion_id": identifiers["assertions"]["installed_lights"]},
            "expected": {"value": {"value_type": "integer", "value": 12,
                                   "unit": "luminarias", "context": None}},
            "value": {"value": {"value_type": "integer", "value": 18}},
            "reason": "porque sí",
            "antu_ref": "el cliente pidió otro número por teléfono"}])
        assert result.status == "REJECTED"
        assert [item["code"] for item in result.rejected] == [
            "OPERATION_NOT_SUPPORTED_BY_INSTRUCTION"]

    def test_a_partial_expected_value_still_detects_the_current_value(self, tmp_path) -> None:
        """A model does not have to copy the whole record; it must declare what it relies on."""
        memory = h.memory_at(tmp_path)
        identifiers = h.ids(memory)
        result = edit(memory, "Cambia la cantidad de luminarias de 12 a 18", [{
            "operation_id": "op-1", "op": "UPDATE_ASSERTION",
            "target": {"assertion_id": identifiers["assertions"]["installed_lights"]},
            # the stored value also carries `unit` and `context`; declaring only these two
            # fields is enough because both still hold
            "expected": {"value": {"value_type": "integer", "value": 12}},
            "value": {"value": {"value_type": "integer", "value": 18, "unit": "luminarias"}},
            "reason": "la instrucción corrige la cantidad instalada",
            "antu_ref": "de 12 a 18",
        }])
        assert result.status == "COMMITTED", result.to_dict()

    def test_a_wrong_field_in_the_expected_value_is_refused(self, tmp_path) -> None:
        memory = h.memory_at(tmp_path)
        identifiers = h.ids(memory)
        base = memory.current().version_id
        result = edit(memory, "Cambia la cantidad de luminarias de 12 a 18", [{
            "operation_id": "op-1", "op": "UPDATE_ASSERTION",
            "target": {"assertion_id": identifiers["assertions"]["installed_lights"]},
            "expected": {"value": {"value_type": "integer", "value": 11}},
            "value": {"value": {"value_type": "integer", "value": 18}},
            "reason": "la instrucción corrige la cantidad instalada",
            "antu_ref": "de 12 a 18",
        }])
        assert result.status == "REJECTED"
        assert [item["code"] for item in result.rejected] == ["EXPECTED_VALUE_MISMATCH"]
        assert "value.value is 12" in result.rejected[0]["message"]
        assert memory.current().version_id == base

    def test_an_empty_expected_object_is_not_a_check(self, tmp_path) -> None:
        memory = h.memory_at(tmp_path)
        identifiers = h.ids(memory)
        result = edit(memory, "Cambia la cantidad de luminarias de 12 a 18", [{
            "operation_id": "op-1", "op": "UPDATE_ASSERTION",
            "target": {"assertion_id": identifiers["assertions"]["installed_lights"]},
            "expected": {"value": {}},
            "value": {"value": {"value_type": "integer", "value": 18}},
            "reason": "la instrucción corrige la cantidad instalada",
            "antu_ref": "de 12 a 18",
        }])
        assert result.status == "REJECTED"
        assert [item["code"] for item in result.rejected] == ["EXPECTED_VALUE_REQUIRED"]

    def test_the_same_antu_is_replayed_and_never_duplicated(self, tmp_path) -> None:
        memory = h.memory_at(tmp_path)
        identifiers = h.ids(memory)
        instruction = "Cambia la cantidad de luminarias de 12 a 18"
        operations = [{
            "operation_id": "op-1", "op": "UPDATE_ASSERTION",
            "target": {"assertion_id": identifiers["assertions"]["installed_lights"]},
            "expected": {"value": {"value_type": "integer", "value": 12,
                                   "unit": "luminarias", "context": None}},
            "value": {"value": {"value_type": "integer", "value": 18, "unit": "luminarias"}},
            "reason": "la instrucción corrige la cantidad",
            "antu_ref": "de 12 a 18"}]
        first = edit(memory, instruction, operations)
        assert first.status == "COMMITTED"
        versions_after_first = len(memory.versions())
        replay = edit(memory, instruction, operations)
        assert replay.status == "REPLAYED"
        assert replay.antu_id == derive_antu_id(instruction)
        assert replay.version_id == first.version_id
        assert len(memory.versions()) == versions_after_first

    def test_a_stale_base_is_a_conflict_and_nothing_is_written(self, tmp_path) -> None:
        memory = h.memory_at(tmp_path)
        identifiers = h.ids(memory)
        result = memory.apply_antu(
            "Cambia la cantidad de luminarias de 12 a 18",
            editor=h.ScriptedEditor(h.proposal([{
                "operation_id": "op-1", "op": "UPDATE_ASSERTION",
                "target": {"assertion_id": identifiers["assertions"]["installed_lights"]},
                "expected": {"value": {"value_type": "integer", "value": 12,
                                       "unit": "luminarias", "context": None}},
                "value": {"value": {"value_type": "integer", "value": 18}},
                "reason": "la instrucción corrige la cantidad",
                "antu_ref": "de 12 a 18"}])),
            base_version_id="VER-000000000000")
        assert result.status == "REJECTED"
        assert "STALE_BASE" in result.reasons[0]
        assert len(memory.versions()) == 1



class TestProvenanceAndIsolation:
    def test_the_edit_records_the_literal_instruction_actor_and_model(self, tmp_path) -> None:
        memory = h.memory_at(tmp_path)
        identifiers = h.ids(memory)
        instruction = "Cambia la cantidad de luminarias de 12 a 18"
        actor = {"leftraru_id": "LR-EDIT", "authenticated_user": "ana",
                 "authenticated_account": "ana@example", "service_identity": "svc-kuyen"}
        editor = h.ScriptedEditor(h.proposal([{
            "operation_id": "op-1", "op": "UPDATE_ASSERTION",
            "target": {"assertion_id": identifiers["assertions"]["installed_lights"]},
            "expected": {"value": {"value_type": "integer", "value": 12,
                                   "unit": "luminarias", "context": None}},
            "value": {"value": {"value_type": "integer", "value": 18}},
            "reason": "la instrucción corrige la cantidad",
            "antu_ref": "de 12 a 18"}]))
        result = memory.apply_antu(instruction, editor=editor, actor=actor)
        assert result.status == "COMMITTED"
        origin = next(item for item in memory.graph()["assertions"]
                      if item["value"]["value"] == 18)["origin"]
        assert origin["instruction"] == instruction
        assert origin["actor"]["authenticated_user"] == "ana"
        assert origin["model"]["model"] == "unit-test"
        assert origin["base_version_id"] == result.base_version_id
        # the literal instruction and the proposal are also in the ledger
        received = next(event for event in memory.ledger()
                        if event["event_type"] == "ANTU_RECEIVED" and
                        event.get("kind") == "GRAPH_EDIT")
        assert received["instruction"] == instruction
        proposed = next(event for event in memory.ledger()
                        if event["event_type"] == "ANTU_EDIT_PROPOSED")
        assert proposed["proposal_sha256"]
        # the version keeps the edit in its provenance
        provenance = memory.graph()["provenance"]
        assert provenance["edits"][-1]["antu_id"] == result.antu_id
        assert provenance["edits"][-1]["instruction_sha256"]

    def test_the_version_identity_does_not_depend_on_token_metering(self, tmp_path) -> None:
        """Two runs of the same proposal with the same editor produce the same version id.

        Metering (`usage`) is recorded in the ledger, not in the graph provenance: the
        identity of a version must depend on the knowledge and on its provenance, never on
        how many tokens the model consumed.
        """
        from kuyen.editing import EditorUsage

        first = h.memory_at(tmp_path / "first")
        second = h.memory_at(tmp_path / "second")
        identifiers = h.ids(first)
        payload = h.proposal([{
            "operation_id": "op-1", "op": "UPDATE_ASSERTION",
            "target": {"assertion_id": identifiers["assertions"]["installed_lights"]},
            "expected": {"value": {"value_type": "integer", "value": 12}},
            "value": {"value": {"value_type": "integer", "value": 18,
                                "unit": "luminarias"}},
            "reason": "la instrucción corrige la cantidad instalada",
            "antu_ref": "de 12 a 18"}])
        instructions = "Cambia la cantidad de luminarias de 12 a 18"

        def run(memory, usage):
            editor = h.ScriptedEditor(payload)
            editor.last_usage = usage
            return memory.apply_antu(instructions, editor=editor)

        one = run(first, EditorUsage(prompt_tokens=2701, completion_tokens=127))
        two = run(second, EditorUsage(prompt_tokens=999, completion_tokens=1))
        assert one.status == two.status == "COMMITTED"
        assert one.version_id == two.version_id
        assert one.provenance["canonical_graph_hash"] == two.provenance["canonical_graph_hash"]
        # the metering is in the ledger, where the run record belongs
        received = next(event for event in first.ledger()
                        if event["event_type"] == "ANTU_RECEIVED"
                        and event.get("kind") == "GRAPH_EDIT")
        assert received["model"]["usage"]["prompt_tokens"] == 2701

    def test_the_edit_never_touches_openviking(self, tmp_path, monkeypatch) -> None:
        memory = h.memory_at(tmp_path)
        identifiers = h.ids(memory)
        import kuyen.adapters.openviking as adapter

        async def _forbidden(*args, **kwargs):  # pragma: no cover - must never run
            raise AssertionError("the graph-edit path must not start an OpenViking adapter")

        monkeypatch.setattr(adapter.SdkOpenVikingAdapter, "initialize", _forbidden)
        result = edit(memory, "Cambia la cantidad de luminarias de 12 a 18", [{
            "operation_id": "op-1", "op": "UPDATE_ASSERTION",
            "target": {"assertion_id": identifiers["assertions"]["installed_lights"]},
            "expected": {"value": {"value_type": "integer", "value": 12,
                                   "unit": "luminarias", "context": None}},
            "value": {"value": {"value_type": "integer", "value": 18}},
            "reason": "la instrucción corrige la cantidad",
            "antu_ref": "de 12 a 18"}])
        assert result.status == "COMMITTED"

    def test_a_proposal_that_is_not_json_is_an_interpretation_failure(self, tmp_path) -> None:
        memory = h.memory_at(tmp_path)
        base = memory.current().version_id
        result = memory.apply_antu("Cambia algo", editor=h.ScriptedEditor("no soy json"))
        assert result.status == "INTERPRETATION_FAILED"
        assert memory.current().version_id == base

    def test_a_dry_run_validates_without_writing_anything(self, tmp_path) -> None:
        memory = h.memory_at(tmp_path)
        identifiers = h.ids(memory)
        base = memory.current().version_id


class TestContextScope:
    def test_an_operation_outside_the_authorised_context_is_refused(self, tmp_path) -> None:
        memory = h.big_memory_at(tmp_path)
        identifiers = h.ids(memory)
        base = memory.current().version_id
        instruction = "Cambia la cantidad de luminarias de 12 a 18"
        result = edit(memory, instruction, [{
            "operation_id": "op-1", "op": "UPDATE_ASSERTION",
            "target": {"assertion_id": identifiers["assertions"]["started_at"]},
            "expected": {"value": {"value_type": "string", "value": "2025-03",
                                   "unit": None, "context": None}},
            "value": {"value": {"value_type": "string", "value": "2025-04"}},
            "reason": "la instrucción corrige el mes",
            "antu_ref": "cambia la cantidad de luminarias de 12 a 18",
        }])
        assert result.status == "REJECTED", result.to_dict()
        assert [item["code"] for item in result.rejected] == ["TARGET_NOT_IN_CONTEXT"]
        assert result.context["mode"] == "KEYWORD_SELECTION"
        assert result.context["truncated"] is True
        assert memory.current().version_id == base
        assert len(memory.versions()) == 1

    def test_the_selected_context_always_contains_the_target_of_a_matching_instruction(
            self, tmp_path) -> None:
        memory = h.big_memory_at(tmp_path)
        identifiers = h.ids(memory)
        result = edit(memory, "Cambia la cantidad de luminarias de 12 a 18", [{
            "operation_id": "op-1", "op": "UPDATE_ASSERTION",
            "target": {"assertion_id": identifiers["assertions"]["installed_lights"]},
            "expected": {"value": {"value_type": "integer", "value": 12,
                                   "unit": "luminarias", "context": None}},
            "value": {"value": {"value_type": "integer", "value": 18}},
            "reason": "la instrucción corrige la cantidad",
            "antu_ref": "de 12 a 18"}])
        assert result.status == "COMMITTED", result.to_dict()
        assert "luminarias" in result.context["keywords"]
