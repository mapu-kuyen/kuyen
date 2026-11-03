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
from .identity import entity_id_for, entity_identity_block
from .operations import GraphEditOperation

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

    def to_dict(self) -> dict[str, Any]:
        return {"applied": [item.to_dict() for item in self.applied],
                "affected": {key: list(value) for key, value in self.affected.items()},
                "references": dict(self.references)}


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
        key = {"entity": "entity_id", "relation": "relation_id",
               "assertion": "assertion_id"}[kind]
        return self._index(canonical[f"{kind}s"], key).get(identifier)


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
        predicate = str(operation.value.get("predicate") or "")
        label = str(operation.value.get("label") or predicate)
        return {
            "relation_id": str(operation.value.get("_canonical_id") or ""),
            "from_entity": from_entity, "to_entity": to_entity,
            "predicate": predicate,
            "source_predicate": predicate, "canonical_predicate": predicate,
            "provider_predicate": None, "display_label": label, "provider_label": None,
            "label": label, "source_label": label,
            "polarity": str(operation.value.get("_polarity") or ""),
            "scope": str(operation.value.get("scope") or "instruction"),
            "temporal_scope": operation.value.get("temporal_scope"),
            "temporal": operation.value.get("temporal"),
            "evidence_ids": [], "sources": [],
            "status": STATUS_INSTRUCTED, "semantic_status": "NOT_ASSESSED",
            "modality": str(operation.value.get("_modality") or "UNKNOWN"),
            "attribution": operation.value.get("attribution"),
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
                    ("predicate", "label", "polarity", "temporal_scope", "modality")}
        if new_id == target_id:
            # Same identity: the change is recorded on the object itself.
            for key in ("predicate", "label", "polarity", "modality", "temporal"):
                if key in operation.value:
                    relation[key] = operation.value[key]
            if "temporal_scope" in operation.value:
                relation["temporal_scope"] = operation.value["temporal_scope"]
            relation["origin"] = self._origin(operation)
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
            "scope": str(operation.value.get("scope") or "instruction"),
            "temporal_scope": operation.value.get("temporal_scope"),
            "temporal": operation.value.get("temporal"),
            "evidence_ids": [], "sources": [],
            "proposed_status": None, "proposed_status_raw": None,
            "evidence_status": "NOT_EVALUATED",
            "status": STATUS_INSTRUCTED, "semantic_status": "NOT_ASSESSED",
            "support_method": "antu_instruction",
            "support_rationale": operation.reason or None,
            "modality": str(operation.value.get("_modality") or "UNKNOWN"),
            "attribution": operation.value.get("attribution"),
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
                    for key in ("predicate", "value", "object_entity", "polarity", "modality")}
        if new_id == target_id:
            for key in ("predicate", "polarity", "modality", "temporal"):
                if key in operation.value:
                    assertion[key] = operation.value[key]
            for key in ("value", "object_entity", "temporal_scope"):
                if key in operation.value:
                    assertion[key] = copy.deepcopy(operation.value[
                        "_value_payload" if key == "value" else key])
            assertion["origin"] = self._origin(operation)
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

