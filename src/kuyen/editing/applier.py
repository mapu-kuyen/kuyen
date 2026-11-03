"""Deterministic application of validated operations to one canonical version (§6.3).

Everything here is pure: it receives the base canonical *document* and the operations
KÜYEN already accepted, and returns a new document plus the record of what happened. No
I/O, no model, no clock beyond the `recorded_at` it is given.

Invariants:

* the base document is never mutated (it is deep-copied);
* nothing is deleted: a correction keeps the previous statement marked `SUPERSEDED` and a
  removal keeps it marked `RETRACTED`, both with the Antü that caused it;
* every created or modified object carries an `origin` of kind `ANTU_INSTRUCTION` and a
  status of `INSTRUCTED` — never `SOURCE_VERIFIED`;
* no evidence, MAPU, SOURCE_UNIT, quote or hash is invented.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Mapping

from ..semantics.origin import antu_origin
from ..semantics.schema import GraphSchema, SchemaError
from ..errors import InvalidRequestError
from .identity import entity_id_for, entity_identity_block
from .operations import GraphEditOperation

class EditContractError(InvalidRequestError):
    """An accepted operation cannot be applied to this document."""


STATUS_INSTRUCTED = "INSTRUCTED"
STATUS_SUPERSEDED = "SUPERSEDED"
STATUS_RETRACTED = "RETRACTED"


@dataclass
class AppliedOperation:
    operation_id: str
    op: str
    object_kind: str
    object_id: str
    effect: str
    previous: dict[str, Any] | None = None
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"operation_id": self.operation_id, "op": self.op, "object_kind": self.object_kind,
                "object_id": self.object_id, "effect": self.effect,
                "previous": copy.deepcopy(self.previous), "reason": self.reason}


@dataclass
class ApplicationResult:
    document: dict[str, Any]
    applied: list[AppliedOperation] = field(default_factory=list)
    affected: dict[str, list[str]] = field(default_factory=dict)
    references: dict[str, str] = field(default_factory=dict)
    schema_changes: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"applied": [item.to_dict() for item in self.applied],
                "affected": {key: list(value) for key, value in self.affected.items()},
                "references": dict(self.references),
                "schema_changes": copy.deepcopy(self.schema_changes)}


class GraphEditApplier:
    """Apply accepted operations to a canonical document, preserving every prior state."""

    def __init__(self, *, antu_id: str, instruction: str, instruction_sha256: str,
                 base_version_id: str, actor: Mapping[str, Any] | None,
                 model: Mapping[str, Any] | None = None,
                 recorded_at: str | None = None) -> None:
        self.antu_id = antu_id
        self.instruction = instruction
        self.instruction_sha256 = instruction_sha256
        self.base_version_id = base_version_id
        self.actor = actor
        self.model = model
        self.recorded_at = recorded_at
        self.references: dict[str, str] = {}
        self.schema_changes: list[dict[str, Any]] = []

    # ---------- provenance ----------
    def _origin(self, operation: GraphEditOperation) -> dict[str, Any]:
        return antu_origin(
            antu_id=self.antu_id, instruction=self.instruction,
            instruction_sha256=self.instruction_sha256, base_version_id=self.base_version_id,
            reason=operation.reason or None, actor=self.actor, model=self.model,
            operation_id=operation.operation_id, recorded_at=self.recorded_at)

    def _resolve(self, value: Any) -> str:
        text = str(value or "")
        return self.references.get(text, text)

    @staticmethod
    def _index(items: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
        return {str(item.get(key)): item for item in items if item.get(key)}

    @staticmethod
    def _affected(canonical: Mapping[str, Any]) -> dict[str, list[str]]:
        return {group: sorted(str(item.get(f"{kind}_id")) for item in canonical.get(group, [])
                              if item.get(f"{kind}_id"))
                for group, kind in (("entities", "entity"), ("relations", "relation"),
                                    ("assertions", "assertion"), ("evidence", "evidence"))}

    def _record(self, result: ApplicationResult, operation: GraphEditOperation, *,
                kind: str, identifier: str, effect: str,
                previous: dict[str, Any] | None = None) -> None:
        result.applied.append(AppliedOperation(
            operation_id=operation.operation_id, op=operation.op, object_kind=kind,
            object_id=identifier, effect=effect,
            previous=copy.deepcopy(previous) if previous is not None else None,
            reason=operation.reason))
        bucket = result.affected.setdefault(f"{kind}s", [])
        if identifier not in bucket:
            bucket.append(identifier)
            bucket.sort()

    def _base_object(self, kind: str, identifier: str,
                     canonical: Mapping[str, Any]) -> dict[str, Any] | None:
        group, key = {"entity": ("entities", "entity_id"),
                      "relation": ("relations", "relation_id"),
                      "assertion": ("assertions", "assertion_id")}[kind]
        return self._index(canonical[group], key).get(identifier)


    # ---------- application ----------
    def apply(self, document: Mapping[str, Any],
              operations: list[GraphEditOperation]) -> ApplicationResult:
        result = ApplicationResult(document=copy.deepcopy(dict(document)))
        canonical = result.document["canonical"]
        for key in ("entities", "relations", "assertions", "evidence", "coverage", "source_units"):
            canonical.setdefault(key, [])
        for operation in operations:
            handler = getattr(self, f"_apply_{operation.op.lower()}", None)
            if handler is None:  # pragma: no cover - the validator refuses unknown operations
                continue
            handler(operation, canonical, result)
        result.references = dict(self.references)
        return result

    # ---------- schema operations (§6, §7) ----------
    def _apply_add_field(self, operation: GraphEditOperation, canonical: dict[str, Any],
                         result: ApplicationResult) -> None:
        self._apply_schema_field(
            operation, result, transform="add",
            entity_type=str(operation.value.get("_entity_type") or ""),
            field_spec=dict(operation.value.get("_field") or {}))

    def _apply_update_field(self, operation: GraphEditOperation, canonical: dict[str, Any],
                            result: ApplicationResult) -> None:
        self._apply_schema_field(
            operation, result, transform="update",
            entity_type=str(operation.value.get("_entity_type") or ""),
            field_spec=dict(operation.value.get("_field") or {}))

    def _apply_retract_field(self, operation: GraphEditOperation, canonical: dict[str, Any],
                             result: ApplicationResult) -> None:
        self._apply_schema_field(
            operation, result, transform="retract",
            entity_type=str(operation.value.get("_entity_type") or ""),
            field_spec={"name": str(operation.value.get("_field_name") or "")})

    def _apply_schema_field(self, operation: GraphEditOperation, result: ApplicationResult, *,
                            transform: str, entity_type: str,
                            field_spec: dict[str, Any]) -> None:
        """Apply one schema change, keeping the previous declaration in the record.

        The schema is part of the version (it is hashed with it), so a field added by an Antü
        is a real change of the memory: the next version knows the field, and a version
        without it keeps not knowing it.
        """
        document = result.document
        current = GraphSchema.from_dict(document.get("schema"))
        if current is None:  # pragma: no cover - the validator refuses an absent schema
            return
        try:
            if transform == "add":
                updated = current.with_added_field(entity_type, field_spec,
                                                   antu_id=self.antu_id)
            elif transform == "update":
                updated = current.with_updated_field(entity_type, field_spec,
                                                     antu_id=self.antu_id)
            else:
                updated = current.with_removed_field(entity_type, field_spec.get("name"),
                                                     antu_id=self.antu_id)
        except SchemaError as exc:  # pragma: no cover - the validator checked the same rules
            raise EditContractError(
                f"the schema change cannot be applied: {exc}",
                details={"code": "SCHEMA_CHANGE_FAILED", "entity_type": entity_type}) from exc
        document["schema"] = updated.to_dict()
        previous = operation.value.get("_previous")
        field_name = str(field_spec.get("name") or "")
        result.schema_changes.append({
            "operation_id": operation.operation_id, "op": operation.op,
            "entity_type": entity_type, "field": field_name,
            "previous": copy.deepcopy(previous) if previous is not None else None,
            "current": updated.field(entity_type, field_name), "antu_id": self.antu_id,
        })
        self._record(result, operation, kind="field",
                     identifier=f"{entity_type}.{field_name}",
                     effect={"add": "ADDED", "update": "UPDATED", "retract": "RETRACTED"}[transform],
                     previous=previous if isinstance(previous, dict) else None)

    def _apply_retract_entity(self, operation: GraphEditOperation, canonical: dict[str, Any],
                              result: ApplicationResult) -> None:
        """Retract an entity and, with it, the statements that only exist through it.

        Nothing is deleted: the entity stays with `status: RETRACTED`, and every relation or
        assertion that points at it is retracted by the same Antü, so a version never keeps an
        assertion about something the same version retracted.
        """
        entity_id = str(operation.value.get("_target_id") or operation.target_id)
        entity = self._base_object("entity", entity_id, canonical)
        if entity is None:  # pragma: no cover - the validator resolved the target
            return
        previous = {"status": entity.get("status")}
        entity.setdefault("revisions", []).append({
            "antu_id": self.antu_id, "operation_id": operation.operation_id,
            "recorded_at": self.recorded_at, "reason": operation.reason,
            "instruction_sha256": self.instruction_sha256, "previous": previous,
            "effect": "RETRACTED",
        })
        entity["status"] = STATUS_RETRACTED
        entity["retracted"] = True
        entity["origin"] = self._origin(operation)
        self._record(result, operation, kind="entity", identifier=entity_id,
                     effect="RETRACTED", previous=previous)
        for group, id_key in (("relations", "relation_id"), ("assertions", "assertion_id")):
            for item in canonical.get(group, []):
                touches = (item.get("from_entity") == entity_id
                           or item.get("to_entity") == entity_id
                           or item.get("subject_entity") == entity_id
                           or item.get("object_entity") == entity_id)
                if not touches or str(item.get("status")) == STATUS_RETRACTED:
                    continue
                previous_status = item.get("status")
                item["status"] = STATUS_RETRACTED
                item["retracted"] = True
                item["origin"] = self._origin(operation)
                self._record(result, operation, kind=group[:-1],
                             identifier=str(item.get(id_key)), effect="RETRACTED_CASCADE",
                             previous={"status": previous_status})

    def _apply_add_entity(self, operation: GraphEditOperation, canonical: dict[str, Any],
                          result: ApplicationResult) -> None:
        reference = operation.reference or operation.operation_id
        entity_id = entity_id_for(antu_id=self.antu_id, ref=reference,
                                 entity_type=str(operation.value.get("entity_type") or ""))
        self.references[reference] = entity_id
        entity = {
            **entity_identity_block(entity_id=entity_id, ref=reference, antu_id=self.antu_id),
            "entity_type": str(operation.value.get("entity_type") or ""),
            "name": str(operation.value.get("name") or ""),
            "aliases": [str(item) for item in (operation.value.get("aliases") or [])],
            "description": str(operation.value.get("description") or ""),
            "evidence_ids": [], "sources": [],
            "status": STATUS_INSTRUCTED,
            "metadata": {"antu_id": self.antu_id, "operation_id": operation.operation_id,
                         "declared_by": "antu_instruction"},
            "origin": self._origin(operation),
        }
        canonical["entities"].append(entity)
        self._record(result, operation, kind="entity", identifier=entity_id, effect="ADDED")

    def _apply_update_entity(self, operation: GraphEditOperation, canonical: dict[str, Any],
                             result: ApplicationResult) -> None:
        entity = self._base_object("entity", str(operation.value.get("_target_id")
                                                or operation.target_id), canonical)
        if entity is None:  # pragma: no cover - the validator resolved the target
            return
        previous = {key: copy.deepcopy(entity.get(key))
                    for key in ("name", "entity_type", "description", "aliases")}
        for key in ("name", "entity_type", "description"):
            if key in operation.value:
                entity[key] = str(operation.value[key])
        if "aliases" in operation.value:
            entity["aliases"] = [str(item) for item in (operation.value.get("aliases") or [])]
        entity.setdefault("revisions", []).append({
            "antu_id": self.antu_id, "operation_id": operation.operation_id,
            "recorded_at": self.recorded_at, "reason": operation.reason,
            "instruction_sha256": self.instruction_sha256, "previous": previous,
        })
        entity["origin"] = self._origin(operation)
        if str(entity.get("status") or "") != STATUS_INSTRUCTED:
            entity["status"] = STATUS_INSTRUCTED
        self._record(result, operation, kind="entity", identifier=str(entity["entity_id"]),
                     effect="UPDATED", previous=previous)

    def _relation_record(self, operation: GraphEditOperation, *,
                         from_entity: str, to_entity: str) -> dict[str, Any]:
        predicate = str(operation.value.get("predicate")
                        or operation.value.get("_predicate") or "")
        label = str(operation.value.get("label") or operation.value.get("_label") or predicate)
        return {
            "relation_id": str(operation.value.get("_canonical_id") or ""),
            "from_entity": from_entity, "to_entity": to_entity,
            "predicate": predicate,
            "source_predicate": predicate, "canonical_predicate": predicate,
            "provider_predicate": None, "display_label": label, "provider_label": None,
            "label": label, "source_label": label,
            "polarity": str(operation.value.get("_polarity") or ""),
            "scope": str(operation.value.get("_scope") or "instruction"),
            "temporal_scope": operation.value.get("temporal_scope"),
            "temporal": operation.value.get("temporal"),
            "evidence_ids": [], "sources": [],
            "status": STATUS_INSTRUCTED, "semantic_status": "NOT_ASSESSED",
            "modality": str(operation.value.get("_modality") or "UNKNOWN"),
            "attribution": operation.value.get("_attribution"),
            "mapping_status": "UNMAPPED", "mapping_rule_id": "antu-instruction-v1",
            "mapping_version": "1.0.0", "provider_projection_status": "NATIVE",
            "from_normalization_status": "RESOLVED", "to_normalization_status": "RESOLVED",
            "normalization_reason": None,
            "origin": self._origin(operation),
        }

    def _apply_add_relation(self, operation: GraphEditOperation, canonical: dict[str, Any],
                            result: ApplicationResult) -> None:
        from_entity = self._resolve(operation.value.get("_from"))
        to_entity = self._resolve(operation.value.get("_to"))
        relation = self._relation_record(operation, from_entity=from_entity, to_entity=to_entity)
        canonical["relations"].append(relation)
        self._record(result, operation, kind="relation",
                     identifier=relation["relation_id"], effect="ADDED")

    def _apply_update_relation(self, operation: GraphEditOperation, canonical: dict[str, Any],
                               result: ApplicationResult) -> None:
        target_id = str(operation.value.get("_target_id") or operation.target_id)
        relation = self._base_object("relation", target_id, canonical)
        if relation is None:  # pragma: no cover - the validator resolved the target
            return
        new_id = str(operation.value.get("_canonical_id") or target_id)
        previous = {key: copy.deepcopy(relation.get(key)) for key in
                    ("predicate", "label", "polarity", "scope", "temporal_scope",
                     "modality", "attribution", "evidence_ids")}
        claim_changed = bool(operation.value.get("_identity_changed"))
        if new_id == target_id:
            relation["predicate"] = str(operation.value.get("_predicate")
                                        or relation.get("predicate") or "")
            relation["source_predicate"] = relation["predicate"]
            relation["canonical_predicate"] = relation["predicate"]
            relation["label"] = str(operation.value.get("_label")
                                    or relation.get("label") or relation["predicate"])
            relation["display_label"] = relation["label"]
            relation["polarity"] = str(operation.value.get("_polarity")
                                       or relation.get("polarity") or "")
            relation["modality"] = str(operation.value.get("_modality")
                                       or relation.get("modality") or "UNKNOWN")
            if "attribution" in operation.value:
                relation["attribution"] = operation.value.get("_attribution")
            relation["scope"] = str(operation.value.get("_scope") or relation.get("scope")
                                    or "instruction")
            if "temporal_scope" in operation.value:
                relation["temporal_scope"] = operation.value["temporal_scope"]
            if "temporal" in operation.value:
                relation["temporal"] = operation.value["temporal"]
            self._amend_in_place(relation, operation, previous,
                                 changed=[key for key in operation.value
                                          if not key.startswith("_")])
            relation.setdefault("revisions", []).append({
                "antu_id": self.antu_id, "operation_id": operation.operation_id,
                "recorded_at": self.recorded_at, "reason": operation.reason,
                "instruction_sha256": self.instruction_sha256, "previous": previous})
            self._record(result, operation, kind="relation", identifier=target_id,
                         effect="UPDATED", previous=previous)
            return
        updated = self._relation_record(
            operation, from_entity=str(relation.get("from_entity") or ""),
            to_entity=str(relation.get("to_entity") or ""))
        updated["modality"] = str(operation.value.get("_modality")
                                  or relation.get("modality") or "UNKNOWN")
        updated["polarity"] = str(operation.value.get("_polarity")
                                  or relation.get("polarity") or "")
        updated["scope"] = str(operation.value.get("_scope") or relation.get("scope")
                               or "instruction")
        if claim_changed:
            updated["previous_attribution"] = relation.get("attribution")
            updated["previous_evidence_ids"] = list(relation.get("evidence_ids") or [])
        else:
            updated["attribution"] = (operation.value.get("_attribution")
                                      if "attribution" in operation.value
                                      else relation.get("attribution"))
            updated["evidence_ids"] = list(relation.get("evidence_ids") or [])
            updated["sources"] = list(relation.get("sources") or [])
        updated["supersedes"] = target_id
        relation["status"] = STATUS_SUPERSEDED
        relation["superseded_by"] = new_id
        relation["retraction"] = {
            "antu_id": self.antu_id, "reason": operation.reason,
            "recorded_at": self.recorded_at, "instruction_sha256": self.instruction_sha256}
        canonical["relations"].append(updated)
        self._record(result, operation, kind="relation", identifier=new_id,
                     effect="REPLACED", previous=previous)

    def _apply_retract_relation(self, operation: GraphEditOperation, canonical: dict[str, Any],
                                result: ApplicationResult) -> None:
        target_id = str(operation.value.get("_target_id") or operation.target_id)
        relation = self._base_object("relation", target_id, canonical)
        if relation is None:  # pragma: no cover - the validator resolved the target
            return
        previous = {key: copy.deepcopy(relation.get(key)) for key in ("status", "retracted")}
        relation["status"] = STATUS_RETRACTED
        relation["retracted"] = True
        relation["retraction"] = {
            "antu_id": self.antu_id, "reason": operation.reason,
            "recorded_at": self.recorded_at, "instruction_sha256": self.instruction_sha256}
        relation["origin"] = self._origin(operation)
        self._record(result, operation, kind="relation", identifier=target_id,
                     effect="RETRACTED", previous=previous)

    def _apply_update_attribute(self, operation: GraphEditOperation, canonical: dict[str, Any],
                                result: ApplicationResult) -> None:
        target_id = str(operation.value.get("_target_id") or operation.target_id)
        entity = self._base_object("entity", target_id, canonical)
        if entity is None:  # pragma: no cover - the validator resolved the target
            return
        attribute = str(operation.value.get("_attribute") or "")
        previous = copy.deepcopy((entity.get("metadata") or {}).get(attribute))
        metadata = dict(entity.get("metadata") or {})
        metadata[attribute] = operation.value.get("value")
        entity["metadata"] = metadata
        entity.setdefault("revisions", []).append({
            "antu_id": self.antu_id, "operation_id": operation.operation_id,
            "recorded_at": self.recorded_at, "reason": operation.reason,
            "instruction_sha256": self.instruction_sha256,
            "attribute": attribute, "previous": previous})
        entity["origin"] = self._origin(operation)
        self._record(result, operation, kind="entity", identifier=str(entity["entity_id"]),
                     effect="ATTRIBUTE_UPDATED",
                     previous={"attribute": attribute, "value": previous})

    def _amend_in_place(self, obj: dict[str, Any], operation: GraphEditOperation,
                        previous: Mapping[str, Any], *, changed) -> None:
        """Record an in-place patch without lying about where the statement comes from.

        A documentary statement that keeps its evidence remains `DOCUMENT_EVIDENCE`: the
        instruction amended a property, it did not become the source. A statement that has
        no evidence is instruction-borne and moves to the new Antü origin.
        """
        if not obj.get("evidence_ids"):
            obj["origin"] = self._origin(operation)
        obj["amended"] = True
        obj.setdefault("instruction_edits", []).append({
            "antu_id": self.antu_id, "operation_id": operation.operation_id,
            "instruction_sha256": self.instruction_sha256,
            "changed": sorted(str(key) for key in changed),
            "previous": {key: copy.deepcopy(previous.get(key)) for key in previous},
            "recorded_at": self.recorded_at})

    def _assertion_record(self, operation: GraphEditOperation, *,
                          subject: str, object_entity: str | None) -> dict[str, Any]:
        return {
            "assertion_id": str(operation.value.get("_canonical_id") or ""),
            "subject_entity": subject,
            "predicate": str(operation.value.get("predicate")
                             or operation.value.get("_predicate") or ""),
            "object_entity": object_entity,
            "value": copy.deepcopy(operation.value.get("_value_payload")),
            "polarity": str(operation.value.get("_polarity") or ""),
            "scope": str(operation.value.get("_scope") or "instruction"),
            "temporal_scope": operation.value.get("temporal_scope"),
            "temporal": operation.value.get("temporal"),
            "evidence_ids": [], "sources": [],
            "proposed_status": None, "proposed_status_raw": None,
            "evidence_status": "NOT_EVALUATED",
            "status": STATUS_INSTRUCTED, "semantic_status": "NOT_ASSESSED",
            "support_method": "antu_instruction",
            "support_rationale": operation.reason or None,
            "modality": str(operation.value.get("_modality") or "UNKNOWN"),
            "attribution": operation.value.get("_attribution"),
            "origin": self._origin(operation),
        }

    def _apply_add_assertion(self, operation: GraphEditOperation, canonical: dict[str, Any],
                             result: ApplicationResult) -> None:
        subject = self._resolve(operation.value.get("_subject"))
        object_entity = operation.value.get("_object_entity")
        object_entity = self._resolve(object_entity) if object_entity else None
        assertion = self._assertion_record(operation, subject=subject,
                                          object_entity=object_entity)
        canonical["assertions"].append(assertion)
        self._record(result, operation, kind="assertion",
                     identifier=assertion["assertion_id"], effect="ADDED")

    def _apply_update_assertion(self, operation: GraphEditOperation, canonical: dict[str, Any],
                                result: ApplicationResult) -> None:
        target_id = str(operation.value.get("_target_id") or operation.target_id)
        assertion = self._base_object("assertion", target_id, canonical)
        if assertion is None:  # pragma: no cover - the validator resolved the target
            return
        new_id = str(operation.value.get("_canonical_id") or target_id)
        previous = {key: copy.deepcopy(assertion.get(key))
                    for key in ("predicate", "value", "object_entity", "polarity", "modality",
                                "attribution", "scope", "temporal_scope", "evidence_ids")}
        claim_changed = bool(operation.value.get("_identity_changed"))
        if new_id == target_id:
            # Same identity: the patch is recorded on the object itself and every property
            # the Antü did not name stays exactly as it was.
            assertion["predicate"] = str(operation.value.get("_predicate")
                                         or assertion.get("predicate") or "")
            assertion["polarity"] = str(operation.value.get("_polarity")
                                        or assertion.get("polarity") or "")
            assertion["modality"] = str(operation.value.get("_modality")
                                        or assertion.get("modality") or "UNKNOWN")
            assertion["attribution"] = operation.value.get("_attribution")
            assertion["scope"] = str(operation.value.get("_scope") or assertion.get("scope")
                                     or "instruction")
            if "value" in operation.value:
                assertion["value"] = copy.deepcopy(operation.value.get("_value_payload"))
            if "object_entity" in operation.value:
                assertion["object_entity"] = operation.value.get("_object_entity")
            if "temporal_scope" in operation.value:
                assertion["temporal_scope"] = operation.value.get("temporal_scope")
            if "temporal" in operation.value:
                assertion["temporal"] = operation.value.get("temporal")
            self._amend_in_place(assertion, operation, previous,
                                 changed=[key for key in operation.value
                                          if not key.startswith("_")])
            assertion.setdefault("revisions", []).append({
                "antu_id": self.antu_id, "operation_id": operation.operation_id,
                "recorded_at": self.recorded_at, "reason": operation.reason,
                "instruction_sha256": self.instruction_sha256, "previous": previous})
            self._record(result, operation, kind="assertion", identifier=target_id,
                         effect="UPDATED", previous=previous)
            return
        updated = self._assertion_record(
            operation, subject=str(assertion.get("subject_entity") or ""),
            object_entity=operation.value.get("_object_entity")
            or assertion.get("object_entity"))
        if "predicate" not in operation.value:
            updated["predicate"] = str(assertion.get("predicate") or "")
        # §3: a property the Antü did not name is not destroyed. Modality, polarity, scope,
        # temporal scope and the shape of the value survive the correction; when the claim
        # itself changes (value, predicate or endpoint) the new statement keeps the previous
        # attribution and evidence only as history, because the instruction is not the source.
        updated["modality"] = str(operation.value.get("_modality")
                                  or assertion.get("modality") or "UNKNOWN")
        updated["polarity"] = str(operation.value.get("_polarity")
                                  or assertion.get("polarity") or "")
        updated["scope"] = str(operation.value.get("_scope") or assertion.get("scope")
                               or "instruction")
        updated["temporal_scope"] = (operation.value.get("temporal_scope")
                                     if "temporal_scope" in operation.value
                                     else assertion.get("temporal_scope"))
        updated["temporal"] = (operation.value.get("temporal")
                               if "temporal" in operation.value else assertion.get("temporal"))
        if claim_changed:
            updated["previous_attribution"] = assertion.get("attribution")
            updated["previous_evidence_ids"] = list(assertion.get("evidence_ids") or [])
        else:
            updated["attribution"] = (operation.value.get("_attribution")
                                      if "attribution" in operation.value
                                      else assertion.get("attribution"))
            updated["evidence_ids"] = list(assertion.get("evidence_ids") or [])
            updated["sources"] = list(assertion.get("sources") or [])
            updated["evidence_status"] = assertion.get("evidence_status")
        updated["supersedes"] = target_id
        # No evidence is inherited: the instruction corrects the statement, it does not
        # bring documentary support for the new value. The prior statement keeps its own
        # evidence and the `supersedes` link preserves the trail (§4).
        assertion["status"] = STATUS_SUPERSEDED
        assertion["superseded_by"] = new_id
        assertion["supersession"] = {
            "antu_id": self.antu_id, "reason": operation.reason,
            "recorded_at": self.recorded_at, "instruction_sha256": self.instruction_sha256}
        canonical["assertions"].append(updated)
        self._record(result, operation, kind="assertion", identifier=new_id,
                     effect="REPLACED", previous=previous)

    def _apply_retract_assertion(self, operation: GraphEditOperation, canonical: dict[str, Any],
                                 result: ApplicationResult) -> None:
        target_id = str(operation.value.get("_target_id") or operation.target_id)
        assertion = self._base_object("assertion", target_id, canonical)
        if assertion is None:  # pragma: no cover - the validator resolved the target
            return
        previous = {key: copy.deepcopy(assertion.get(key)) for key in ("status", "retracted")}
        assertion["status"] = STATUS_RETRACTED
        assertion["retracted"] = True
        assertion["retraction"] = {
            "antu_id": self.antu_id, "reason": operation.reason,
            "recorded_at": self.recorded_at, "instruction_sha256": self.instruction_sha256}
        assertion["origin"] = self._origin(operation)
        self._record(result, operation, kind="assertion", identifier=target_id,
                     effect="RETRACTED", previous=previous)

