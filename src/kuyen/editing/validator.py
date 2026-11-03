"""Deterministic validation of a proposed graph edit (§6.3).

The model proposes; KÜYEN decides. Every operation is checked against the version, the
authorised context, the canonical contracts and the instruction itself. One refused
operation refuses the whole Antü: a single instruction is never committed partially.

The codes returned here are part of the public contract of the API.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from .context import EditContext, _normalize
from .identity import assertion_id_for, coercer_value, normalized, relation_id_for
from .operations import MODALITIES, OPERATION_TYPES, POLARITIES, GraphEditOperation

_WORD = re.compile(r"[0-9A-Za-zÁÉÍÓÚÜÑáéíóúüñ_]{3,}")
ENTITY_UPDATE_FIELDS = ("name", "entity_type", "description", "aliases")
_ASSERTION_UPDATE_FIELDS = ("value", "object_entity", "predicate", "temporal_scope")
_RELATION_UPDATE_FIELDS = ("predicate", "label", "polarity", "temporal_scope")


@dataclass
class OperationRejection:
    operation_id: str
    op: str
    code: str
    message: str
    target: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"operation_id": self.operation_id, "op": self.op, "code": self.code,
                "message": self.message, "target": self.target}


@dataclass
class ValidationOutcome:
    accepted: list[GraphEditOperation] = field(default_factory=list)
    rejected: list[OperationRejection] = field(default_factory=list)
    pending: list[dict[str, Any]] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.rejected and not self.problems

    def to_dict(self) -> dict[str, Any]:
        return {"status": "ACCEPTED" if self.ok else "REJECTED",
                "accepted": [item.to_dict() for item in self.accepted],
                "rejected": [item.to_dict() for item in self.rejected],
                "pending": list(self.pending), "problems": list(self.problems)}


def _words(text: str) -> list[str]:
    return [match.group(0) for match in _WORD.finditer(_normalize(text))]


def supported_by_instruction(ref: str, instruction: str) -> bool:
    """True when `ref` is a literal fragment of the instruction or a faithful paraphrase.

    A literal substring is always accepted. Otherwise at least 80% of the reference words
    (and never fewer than two) must appear in the instruction, so a paraphrase passes and
    an invented justification does not.
    """
    reference = " ".join(str(ref or "").split())
    if not reference:
        return False
    if reference in " ".join(instruction.split()):
        return True
    reference_words = set(_words(reference))
    if len(reference_words) < 2:
        return False
    instruction_words = set(_words(instruction))
    matched = reference_words & instruction_words
    return len(matched) / len(reference_words) >= 0.8


class EditValidator:
    """Validate a parsed proposal against one version and its authorised context."""

    def __init__(self, context: EditContext, *, instruction: str, antu_id: str,
                 version_ids: Mapping[str, Iterable[str]] | None = None) -> None:
        self.context = context
        self.instruction = instruction
        self.antu_id = antu_id
        self.entities = {str(item.get("entity_id")): item for item in context.entities}
        self.relations = {str(item.get("relation_id")): item for item in context.relations}
        self.assertions = {str(item.get("assertion_id")): item for item in context.assertions}
        self.proposed_refs: dict[str, GraphEditOperation] = {}
        # Every identity of the version, including the objects outside the authorised
        # context: this is what tells "does not exist" apart from "not in this Antü".
        self.version_ids = {key: set(value) for key, value in (version_ids or {}).items()}

    # ---------- helpers ----------
    def _existing(self, kind: str, identifier: str) -> dict[str, Any] | None:
        pool = {"entity": self.entities, "relation": self.relations,
                "assertion": self.assertions}.get(kind, {})
        return pool.get(identifier)

    def _exists_in_version(self, kind: str, identifier: str) -> bool:
        """True when the identifier exists in the version, inside the context or not."""
        if self._existing(kind, identifier) is not None:
            return True
        pool = self.version_ids.get(kind)
        return bool(pool and identifier in pool)

    def _reject(self, operation: GraphEditOperation, code: str,
                message: str) -> OperationRejection:
        return OperationRejection(operation_id=operation.operation_id, op=operation.op,
                                  code=code, message=message, target=operation.target_id)

    def _check_support(self, operation: GraphEditOperation,
                       rejected: list[OperationRejection]) -> bool:
        if not supported_by_instruction(operation.antu_ref, self.instruction):
            rejected.append(self._reject(
                operation, "OPERATION_NOT_SUPPORTED_BY_INSTRUCTION",
                "the operation does not cite the instruction it comes from"))
            return False
        if not operation.reason.strip():
            rejected.append(self._reject(
                operation, "OPERATION_REASON_MISSING",
                "the operation does not explain why the knowledge changes"))
            return False
        return True

    def _resolve_target(self, operation: GraphEditOperation, kind: str,
                        rejected: list[OperationRejection]) -> dict[str, Any] | None:
        identifier = operation.target_id
        if not identifier:
            reference = operation.reference
            if reference and reference in self.proposed_refs:
                return {"entity_id": f"proposed:{reference}"}
            rejected.append(self._reject(operation, "OPERATION_TARGET_MISSING",
                                        "the operation does not identify its target"))
            return None
        if not self.context.is_authorized(identifier):
            if self._exists_in_version(kind, identifier):
                rejected.append(self._reject(
                    operation, "TARGET_NOT_IN_CONTEXT",
                    f"{kind} {identifier} exists but is outside the authorised context "
                    "of this Antü"))
            else:
                rejected.append(self._reject(
                    operation, "TARGET_NOT_FOUND",
                    f"{kind} {identifier} does not exist in this version"))
            return None
        target = self._existing(kind, identifier)
        if target is None:
            rejected.append(self._reject(operation, "TARGET_NOT_FOUND",
                                        f"{kind} {identifier} does not exist"))
        return target

    def _check_expected(self, operation: GraphEditOperation, current: Mapping[str, Any],
                        rejected: list[OperationRejection], *, fields: Iterable[str]) -> bool:
        """Check that the knowledge the operation is based on still holds.

        For scalar fields the comparison is exact. For an object-valued field (`value`,
        `temporal`) every key the operation declares must match the current object with the
        same value: a partial declaration is accepted — the model is not forced to copy a
        record byte for byte — but a declared field that already changed is a stale base and
        the operation is refused (measured with a real model, see the experiment report).
        """
        if operation.expected is None:
            rejected.append(self._reject(
                operation, "EXPECTED_VALUE_REQUIRED",
                "an operation that changes or retracts knowledge must declare the value it "
                "expects to find"))
            return False
        for name in fields:
            if name not in operation.expected:
                continue
            expected = operation.expected[name]
            actual = current.get(name)
            if isinstance(expected, Mapping) or isinstance(actual, Mapping):
                declared = {key: value for key, value in dict(expected or {}).items()
                            if not str(key).startswith("_")}
                if not declared:
                    rejected.append(self._reject(
                        operation, "EXPECTED_VALUE_REQUIRED",
                        f"expected.{name} must declare at least one field of the current value"))
                    return False
                if not isinstance(actual, Mapping):
                    rejected.append(self._reject(
                        operation, "EXPECTED_VALUE_MISMATCH",
                        f"{name} is {actual!r} in this version, not {dict(expected)}"))
                    return False
                for key, value in declared.items():
                    if actual.get(key) != value:
                        rejected.append(self._reject(
                            operation, "EXPECTED_VALUE_MISMATCH",
                            f"{name}.{key} is {actual.get(key)!r} in this version, not {value!r}"))
                        return False
            elif expected != actual:
                rejected.append(self._reject(
                    operation, "EXPECTED_VALUE_MISMATCH",
                    f"{name} is {actual!r} in this version, not {expected!r}"))
                return False
        return True


    @staticmethod
    def _polarity(operation: GraphEditOperation,
                  rejected: list[OperationRejection]) -> str | None:
        declared = str(operation.value.get("polarity") or "").strip().upper()
        if not declared:
            rejected.append(OperationRejection(
                operation.operation_id, operation.op, "POLARITY_REQUIRED",
                "an assertion or relation must declare POSITIVE or NEGATIVE polarity"))
            return None
        if declared not in POLARITIES:
            rejected.append(OperationRejection(
                operation.operation_id, operation.op, "POLARITY_NOT_ADMITTED",
                f"polarity {declared!r} cannot be stored in the canonical set"))
            return None
        return declared

    @staticmethod
    def _modality(operation: GraphEditOperation,
                  rejected: list[OperationRejection]) -> str:
        declared = str(operation.value.get("modality") or "").strip().upper()
        if not declared:
            return "UNKNOWN"
        if declared not in MODALITIES:
            rejected.append(OperationRejection(
                operation.operation_id, operation.op, "MODALITY_INVALID",
                f"modality {declared!r} is not part of the contract"))
            return "UNKNOWN"
        return declared

    def _endpoint(self, raw: Any, operation: GraphEditOperation,
                  rejected: list[OperationRejection]) -> str | None:
        """Resolve a relation/assertion endpoint to an authorised id or a proposed ref."""
        value = str(raw or "").strip()
        if not value:
            rejected.append(self._reject(operation, "ENDPOINT_MISSING",
                                        "the operation does not name the endpoint"))
            return None
        if value in self.proposed_refs:
            return value
        if self.context.is_authorized(value):
            return value
        rejected.append(self._reject(
            operation,
            "TARGET_NOT_FOUND" if not self.entities.get(value) else "TARGET_NOT_IN_CONTEXT",
            f"entity {value} is not available for this Antü"))
        return None

    # ---------- dispatch ----------
    def validate(self, proposal) -> ValidationOutcome:
        outcome = ValidationOutcome()
        if proposal.base_version_id and proposal.base_version_id != self.context.version_id:
            outcome.problems.append(
                f"STALE_BASE: the proposal declares base {proposal.base_version_id}, "
                f"the context is {self.context.version_id}")
            return outcome
        for operation in proposal.operations:
            if operation.op not in OPERATION_TYPES:
                outcome.rejected.append(self._reject(
                    operation, "OPERATION_UNKNOWN",
                    f"{operation.op!r} is not a graph-edit operation"))
                continue
            if not self._check_support(operation, outcome.rejected):
                continue
            handler = getattr(self, f"_validate_{operation.op.lower()}", None)
            if handler is None:  # pragma: no cover - OPERATION_TYPES and handlers agree
                outcome.rejected.append(self._reject(
                    operation, "OPERATION_NOT_IMPLEMENTED",
                    f"{operation.op} has no deterministic implementation"))
                continue
            handler(operation, outcome)
        return outcome



    def _validate_add_entity(self, operation: GraphEditOperation,
                             outcome: ValidationOutcome) -> None:
        name = str(operation.value.get("name") or "").strip()
        entity_type = str(operation.value.get("entity_type") or "").strip()
        reference = operation.reference
        if not name or not entity_type:
            outcome.rejected.append(self._reject(
                operation, "VALUE_INCOMPLETE", "ADD_ENTITY requires name and entity_type"))
            return
        if not reference:
            outcome.rejected.append(self._reject(
                operation, "VALUE_INCOMPLETE",
                "ADD_ENTITY requires value.ref so later operations can name the new entity"))
            return
        if reference in self.proposed_refs:
            outcome.rejected.append(self._reject(
                operation, "DUPLICATE_REFERENCE",
                f"the local reference {reference!r} is repeated"))
            return
        for entity in self.context.entities:
            if normalized(entity.get("name")) == normalized(name) \
                    and str(entity.get("entity_type")) == entity_type:
                outcome.rejected.append(self._reject(
                    operation, "ENTITY_ALREADY_EXISTS",
                    f"an entity with the same name and type already exists "
                    f"({entity.get('entity_id')}); update it instead of adding a duplicate"))
                return
        self.proposed_refs[reference] = operation
        outcome.accepted.append(operation)

    def _validate_update_entity(self, operation: GraphEditOperation,
                                outcome: ValidationOutcome) -> None:
        target = self._resolve_target(operation, "entity", outcome.rejected)
        if target is None:
            return
        changed = [key for key in ENTITY_UPDATE_FIELDS if key in operation.value]
        if not changed:
            outcome.rejected.append(self._reject(
                operation, "VALUE_INCOMPLETE",
                f"UPDATE_ENTITY requires one of {list(ENTITY_UPDATE_FIELDS)}"))
            return
        if not self._check_expected(operation, target, outcome.rejected, fields=changed):
            return
        if operation.value.get("name") is not None and not str(operation.value["name"]).strip():
            outcome.rejected.append(self._reject(
                operation, "VALUE_INCOMPLETE", "an entity name cannot become empty"))
            return
        operation.value = {**operation.value, "_target_id": target.get("entity_id")}
        outcome.accepted.append(operation)

    def _validate_update_attribute(self, operation: GraphEditOperation,
                                  outcome: ValidationOutcome) -> None:
        target = self._resolve_target(operation, "entity", outcome.rejected)
        if target is None:
            return
        attribute = str(operation.value.get("attribute") or "").strip()
        if not attribute or "value" not in operation.value:
            outcome.rejected.append(self._reject(
                operation, "VALUE_INCOMPLETE",
                "UPDATE_ATTRIBUTE requires value.attribute and value.value"))
            return
        metadata = target.get("metadata") or {}
        current = metadata.get(attribute) if isinstance(metadata, Mapping) else None
        expected = operation.expected or {}
        if expected.get("attribute") != attribute:
            outcome.rejected.append(self._reject(
                operation, "EXPECTED_VALUE_REQUIRED",
                f"UPDATE_ATTRIBUTE must declare expected.attribute={attribute!r}"))
            return
        if expected.get("value") != current:
            outcome.rejected.append(self._reject(
                operation, "EXPECTED_VALUE_MISMATCH",
                f"attribute {attribute!r} is {current!r} in this version, "
                f"not {expected.get('value')!r}"))
            return
        operation.value = {**operation.value, "_target_id": target.get("entity_id"),
                           "_attribute": attribute, "_previous": current}
        outcome.accepted.append(operation)

    def _validate_add_assertion(self, operation: GraphEditOperation,
                                outcome: ValidationOutcome) -> None:
        subject = self._endpoint(operation.value.get("subject"), operation, outcome.rejected)
        if subject is None:
            return
        predicate = str(operation.value.get("predicate") or "").strip()
        if not predicate:
            outcome.rejected.append(self._reject(
                operation, "VALUE_INCOMPLETE", "ADD_ASSERTION requires a predicate"))
            return
        payload = coercer_value(operation.value.get("value"))
        object_entity = str(operation.value.get("object_entity") or "").strip() or None
        if object_entity is not None:
            object_entity = self._endpoint(object_entity, operation, outcome.rejected)
            if object_entity is None:
                return
        if (payload is None) == (object_entity is None):
            outcome.rejected.append(self._reject(
                operation, "ASSERTION_SHAPE",
                "an assertion carries exactly one of value or object_entity"))
            return
        polarity = self._polarity(operation, outcome.rejected)
        if polarity is None:
            return
        modality = self._modality(operation, outcome.rejected)
        temporal = operation.value.get("temporal_scope")
        candidate_id = assertion_id_for(
            subject=subject, predicate=predicate, object_entity=object_entity, value=payload,
            polarity=polarity, temporal_scope=temporal)
        if candidate_id in self.assertions:
            outcome.rejected.append(self._reject(
                operation, "DUPLICATE_OBJECT",
                f"assertion {candidate_id} already states exactly this in this version"))
            return
        operation.value = {**operation.value, "_canonical_id": candidate_id,
                           "_polarity": polarity, "_modality": modality,
                           "_value_payload": payload, "_subject": subject,
                           "_object_entity": object_entity, "_predicate": predicate}
        outcome.accepted.append(operation)

    def _validate_retract_assertion(self, operation: GraphEditOperation,
                                   outcome: ValidationOutcome) -> None:
        target = self._resolve_target(operation, "assertion", outcome.rejected)
        if target is None:
            return
        if target.get("retracted") or str(target.get("status") or "") == "RETRACTED":
            outcome.rejected.append(self._reject(
                operation, "ALREADY_RETRACTED",
                f"assertion {target.get('assertion_id')} is already retracted"))
            return
        if not self._check_expected(operation, target, outcome.rejected,
                                    fields=[key for key in (operation.expected or {})
                                            if key in ("status", "evidence_status", "retracted")]):
            return
        operation.value = {**operation.value, "_target_id": target.get("assertion_id")}
        outcome.accepted.append(operation)



    def _validate_update_assertion(self, operation: GraphEditOperation,
                                   outcome: ValidationOutcome) -> None:
        target = self._resolve_target(operation, "assertion", outcome.rejected)
        if target is None:
            return
        if target.get("retracted") or str(target.get("status") or "") == "RETRACTED":
            outcome.rejected.append(self._reject(
                operation, "TARGET_RETRACTED",
                f"assertion {target.get('assertion_id')} is retracted; add a new statement"))
            return
        changed = [key for key in _ASSERTION_UPDATE_FIELDS if key in operation.value]
        if not changed:
            outcome.rejected.append(self._reject(
                operation, "VALUE_INCOMPLETE",
                f"UPDATE_ASSERTION requires one of {list(_ASSERTION_UPDATE_FIELDS)}"))
            return
        expected_fields = [key for key in changed if key in (operation.expected or {})]
        if not expected_fields:
            outcome.rejected.append(self._reject(
                operation, "EXPECTED_VALUE_REQUIRED",
                f"UPDATE_ASSERTION must declare the current value of {changed}"))
            return
        if not self._check_expected(operation, target, outcome.rejected, fields=expected_fields):
            return
        payload = coercer_value(operation.value["value"]) if "value" in operation.value else None
        object_entity = str(operation.value.get("object_entity") or "").strip() or None
        polarity = str(operation.value.get("polarity") or target.get("polarity") or "").upper()
        if polarity not in POLARITIES:
            outcome.rejected.append(self._reject(
                operation, "POLARITY_NOT_ADMITTED",
                f"polarity {polarity!r} cannot be stored in the canonical set"))
            return
        if payload is not None:
            final_object = None
        elif object_entity is not None:
            final_object = object_entity
        else:
            final_object = target.get("object_entity")
        final_value = payload if payload is not None else (
            None if "object_entity" in operation.value else target.get("value"))
        if (final_value is None) == (final_object is None):
            outcome.rejected.append(self._reject(
                operation, "ASSERTION_SHAPE",
                "an assertion carries exactly one of value or object_entity"))
            return
        candidate_id = assertion_id_for(
            subject=str(target.get("subject_entity") or ""),
            predicate=str(operation.value.get("predicate") or target.get("predicate") or ""),
            object_entity=final_object, value=final_value, polarity=polarity,
            temporal_scope=str(operation.value.get("temporal_scope")
                               or target.get("temporal_scope") or "") or None)
        if candidate_id in self.assertions and candidate_id != target.get("assertion_id"):
            outcome.rejected.append(self._reject(
                operation, "DUPLICATE_OBJECT",
                f"assertion {candidate_id} already exists in this version"))
            return
        operation.value = {**operation.value, "_canonical_id": candidate_id,
                           "_polarity": polarity,
                           "_modality": self._modality(operation, outcome.rejected),
                           "_value_payload": final_value, "_object_entity": final_object,
                           "_target_id": target.get("assertion_id")}
        outcome.accepted.append(operation)

    def _validate_add_relation(self, operation: GraphEditOperation,
                               outcome: ValidationOutcome) -> None:
        source = self._endpoint(operation.value.get("from"), operation, outcome.rejected)
        target = self._endpoint(operation.value.get("to"), operation, outcome.rejected)
        if source is None or target is None:
            return
        predicate = str(operation.value.get("predicate") or "").strip()
        if not predicate:
            outcome.rejected.append(self._reject(
                operation, "VALUE_INCOMPLETE", "ADD_RELATION requires a predicate"))
            return
        if source == target:
            outcome.rejected.append(self._reject(
                operation, "SELF_RELATION", "a relation cannot have the same entity twice"))
            return
        polarity = self._polarity(operation, outcome.rejected)
        if polarity is None:
            return
        temporal = operation.value.get("temporal_scope")
        candidate_id = relation_id_for(from_entity=source, predicate=predicate, to_entity=target,
                                       polarity=polarity, temporal_scope=temporal)
        if candidate_id in self.relations:
            outcome.rejected.append(self._reject(
                operation, "DUPLICATE_OBJECT",
                f"relation {candidate_id} already exists in this version"))
            return
        operation.value = {**operation.value, "_canonical_id": candidate_id,
                           "_polarity": polarity,
                           "_modality": self._modality(operation, outcome.rejected),
                           "_from": source, "_to": target}
        outcome.accepted.append(operation)

    def _validate_retract_relation(self, operation: GraphEditOperation,
                                  outcome: ValidationOutcome) -> None:
        target = self._resolve_target(operation, "relation", outcome.rejected)
        if target is None:
            return
        if target.get("retracted") or str(target.get("status") or "") == "RETRACTED":
            outcome.rejected.append(self._reject(
                operation, "ALREADY_RETRACTED",
                f"relation {target.get('relation_id')} is already retracted"))
            return
        if not self._check_expected(operation, target, outcome.rejected,
                                    fields=[key for key in (operation.expected or {})
                                            if key in ("status", "evidence_status", "retracted")]):
            return
        operation.value = {**operation.value, "_target_id": target.get("relation_id")}
        outcome.accepted.append(operation)

    def _validate_update_relation(self, operation: GraphEditOperation,
                                  outcome: ValidationOutcome) -> None:
        target = self._resolve_target(operation, "relation", outcome.rejected)
        if target is None:
            return
        changed = [key for key in _RELATION_UPDATE_FIELDS if key in operation.value]
        if not changed:
            outcome.rejected.append(self._reject(
                operation, "VALUE_INCOMPLETE",
                f"UPDATE_RELATION requires one of {list(_RELATION_UPDATE_FIELDS)}"))
            return
        expected_fields = [key for key in changed if key in (operation.expected or {})]
        if not expected_fields:
            outcome.rejected.append(self._reject(
                operation, "EXPECTED_VALUE_REQUIRED",
                f"UPDATE_RELATION must declare the current value of {changed}"))
            return
        if not self._check_expected(operation, target, outcome.rejected, fields=expected_fields):
            return
        polarity = str(operation.value.get("polarity") or target.get("polarity") or "").upper()
        if polarity not in POLARITIES:
            outcome.rejected.append(self._reject(
                operation, "POLARITY_NOT_ADMITTED",
                f"polarity {polarity!r} cannot be stored in the canonical set"))
            return
        candidate_id = relation_id_for(
            from_entity=str(target.get("from_entity") or ""),
            predicate=str(operation.value.get("predicate") or target.get("predicate") or ""),
            to_entity=str(target.get("to_entity") or ""), polarity=polarity,
            temporal_scope=str(operation.value.get("temporal_scope")
                               or target.get("temporal_scope") or "") or None)
        if candidate_id in self.relations and candidate_id != target.get("relation_id"):
            outcome.rejected.append(self._reject(
                operation, "DUPLICATE_OBJECT",
                f"relation {candidate_id} already exists in this version"))
            return
        operation.value = {**operation.value, "_canonical_id": candidate_id,
                           "_polarity": polarity,
                           "_modality": self._modality(operation, outcome.rejected),
                           "_target_id": target.get("relation_id")}
        outcome.accepted.append(operation)

