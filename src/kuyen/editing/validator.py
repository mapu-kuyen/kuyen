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

from ..semantics.scope import (AntuScope, DATA_READ, SCHEMA_READ, permissions_for)
from ..semantics.schema import GraphSchema, SchemaError, normalize_field, normalize_field_name
from .context import EditContext, _normalize
from .identity import assertion_id_for, coercer_value, normalized, relation_id_for
from .operations import (ADD_FIELD, ALREADY_SATISFIED, APPLICABILITY_STATES, APPLICABLE,
                        BLOCKED_BY_PERMISSION, MODALITIES, NEEDS_CLARIFICATION,
                        NOT_APPLICABLE, OPERATION_TYPES, OUT_OF_SCOPE, POLARITIES,
                        REQUIRES_DATA_ACCESS, RETRACT_FIELD, RETRACT_RELATION, SCHEMA_OPERATIONS,
                        UPDATE_FIELD, GraphEditOperation)

_WORD = re.compile(r"[0-9A-Za-zÁÉÍÓÚÜÑáéíóúüñ_]{3,}")
ENTITY_UPDATE_FIELDS = ("name", "entity_type", "description", "aliases")

#: `UPDATE_ASSERTION` is a *patch*: only the properties the Antü names are changed and every
#: other one is inherited from the target (KUYEN_ANTU_SEMANTIC_FIDELITY_HARDENING_14, §3).
_ASSERTION_UPDATE_FIELDS = ("value", "object_entity", "predicate", "temporal_scope",
                            "modality", "polarity", "scope", "attribution")
#: Fields that take part in the identity of an assertion. Changing one of them produces a new
#: statement that supersedes the old one; changing modality or attribution does not.
_ASSERTION_IDENTITY_FIELDS = ("value", "object_entity", "predicate", "polarity",
                              "temporal_scope", "scope")
_RELATION_UPDATE_FIELDS = ("predicate", "label", "polarity", "temporal_scope",
                           "modality", "attribution", "scope")
_RELATION_IDENTITY_FIELDS = ("predicate", "polarity", "temporal_scope", "scope")


def attribute_value_problem(value_type: Any, value: Any) -> str | None:
    """Why `value` cannot be stored as an attribute of the declared type, or None.

    An attribute is a typed property of an entity, not a statement: the schema declares its
    type and KÜYEN refuses a value of another type instead of guessing a coercion. `None` is
    never a value — removing an attribute is not an update, and no operation invents one.
    """
    if value is None:
        return "an attribute value cannot be null; nothing in the contract removes an attribute"
    kind = str(value_type or "any")
    if kind == "text":
        return None if isinstance(value, str) else f"text requires a string, not {value!r}"
    if kind == "integer":
        return (None if isinstance(value, int) and not isinstance(value, bool)
                else f"integer requires an integer, not {value!r}")
    if kind == "number":
        return (None if isinstance(value, (int, float)) and not isinstance(value, bool)
                else f"number requires a number, not {value!r}")
    if kind == "boolean":
        return None if isinstance(value, bool) else f"boolean requires true or false, not {value!r}"
    if kind == "date":
        return (None if isinstance(value, str) and value.strip()
                else f"date requires an ISO 8601 string, not {value!r}")
    return None



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
class OperationDecline:
    """An operation the model classified as not applicable, kept as a verifiable record.

    A decline is not a rejection: nothing was wrong with the Antü, this KÜYEN simply has
    nothing to do for that operation. `verified` says whether KÜYEN could confirm the claim
    against its own state (`ALREADY_SATISFIED`, `BLOCKED_BY_PERMISSION`, ...) or whether the
    claim is a judgement only the model can make (`OUT_OF_SCOPE`, `NEEDS_CLARIFICATION`).
    """

    operation_id: str
    op: str
    applicability: str
    explanation: str
    verified: bool
    target: str | None = None
    detail: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"operation_id": self.operation_id, "op": self.op,
                "applicability": self.applicability, "explanation": self.explanation,
                "verified": self.verified, "target": self.target, "detail": self.detail}


@dataclass
class ValidationOutcome:
    accepted: list[GraphEditOperation] = field(default_factory=list)
    rejected: list[OperationRejection] = field(default_factory=list)
    pending: list[dict[str, Any]] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    declined: list[OperationDecline] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.rejected and not self.problems

    @property
    def changed(self) -> bool:
        return bool(self.accepted)

    def applicability_summary(self) -> dict[str, int]:
        summary: dict[str, int] = {}
        for operation in self.accepted:
            summary[APPLICABLE] = summary.get(APPLICABLE, 0) + 1
        for item in self.declined:
            summary[item.applicability] = summary.get(item.applicability, 0) + 1
        return dict(sorted(summary.items()))

    def to_dict(self) -> dict[str, Any]:
        return {"status": "ACCEPTED" if self.ok else "REJECTED",
                "accepted": [item.to_dict() for item in self.accepted],
                "rejected": [item.to_dict() for item in self.rejected],
                "declined": [item.to_dict() for item in self.declined],
                "applicability": self.applicability_summary(),
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
                 version_ids: Mapping[str, Iterable[str]] | None = None,
                 scope: AntuScope | Mapping[str, Any] | Iterable[str] | None = None,
                 schema: GraphSchema | Mapping[str, Any] | None = None) -> None:
        self.context = context
        self.instruction = instruction
        self.antu_id = antu_id
        # The scope is the authority of this KÜYEN, enforced here as well as in the context:
        # a proposal cannot reach what this scope does not allow, whatever the model says.
        self.scope = AntuScope.from_dict(scope)
        self.schema = schema if isinstance(schema, GraphSchema) else GraphSchema.from_dict(schema)
        self.entities = {str(item.get("entity_id")): item for item in context.entities}
        self.relations = {str(item.get("relation_id")): item for item in context.relations}
        self.assertions = {str(item.get("assertion_id")): item for item in context.assertions}
        self.proposed_refs: dict[str, GraphEditOperation] = {}
        # Every identity of the version, including the objects outside the authorised
        # context: this is what tells "does not exist" apart from "not in this Antü".
        self.version_ids = {key: set(value) for key, value in (version_ids or {}).items()}
        # Relations this same Antü retracts: a relation that is being withdrawn cannot make
        # the opposite statement "already present" (a deliberate direction correction).
        self.retraction_targets: set[str] = set()
        # Fields this same Antü declares: an Antü may declare an attribute and set it in the
        # same answer (`ADD_FIELD`, then `UPDATE_ATTRIBUTE` with `depends_on`), so a
        # declaration proposed here counts as a declaration for the operations that follow it.
        self.declared_fields: dict[tuple[str, str], dict[str, Any]] = {}



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
                    f"{name} is {actual!r} in this version, not {expected!r}"
                    + ("; KÜYEN validates every operation against the base version, so a second "
                       "patch of the same object cannot expect the result of the first one: send "
                       "one operation per object"
                       if operation.depends_on else "")))
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
    def _modality(operation: GraphEditOperation, rejected: list[OperationRejection],
                  *, default: str = "UNKNOWN") -> str:
        """Declared modality, or `default` when the operation does not name one.

        `default` is `UNKNOWN` when a statement is created from scratch and the target's
        current modality when an existing statement is patched: an omitted property is never
        read as "this stopped being a fact" (KUYEN_ANTU_SEMANTIC_FIDELITY_HARDENING_14, §4).
        """
        declared = str(operation.value.get("modality") or "").strip().upper()
        if not declared:
            return default
        if declared not in MODALITIES:
            rejected.append(OperationRejection(
                operation.operation_id, operation.op, "MODALITY_INVALID",
                f"modality {declared!r} is not part of the contract"))
            return default
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
        self.retraction_targets = {operation.target_id for operation in proposal.operations
                                   if operation.op == RETRACT_RELATION and operation.target_id}

        for operation in proposal.operations:
            if operation.op not in OPERATION_TYPES:
                outcome.rejected.append(self._reject(
                    operation, "OPERATION_UNKNOWN",
                    f"{operation.op!r} is not a graph-edit operation"))
                continue
            if operation.applicability not in APPLICABILITY_STATES:
                outcome.rejected.append(self._reject(
                    operation, "APPLICABILITY_UNKNOWN",
                    f"{operation.applicability!r} is not an applicability state"))
                continue
            if operation.applicability != APPLICABLE:
                self._record_decline(operation, outcome)
                continue
            missing = self.scope.missing(permissions_for(operation.op))
            if missing:
                outcome.rejected.append(self._reject(
                    operation, "PERMISSION_REQUIRED",
                    f"{operation.op} needs {', '.join(missing)}, which this KÜYEN does not "
                    "grant to this Antü"))
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



    def _record_decline(self, operation: GraphEditOperation,
                        outcome: ValidationOutcome) -> None:
        """Verify a declining claim against this KÜYEN's own state and record it (§5).

        A claim that KÜYEN can check is checked; a claim that contradicts the local state is
        refused (`APPLICABILITY_CLAIM_UNSUPPORTED`) instead of being accepted as an excuse.
        A judgement KÜYEN cannot check (`OUT_OF_SCOPE`, `NEEDS_CLARIFICATION`) is recorded as
        unverified. Either way the Antü is not converted into a generic rejection.
        """
        explanation = " ".join(str(operation.explanation or "").split())
        if not explanation:
            outcome.rejected.append(self._reject(
                operation, "APPLICABILITY_EXPLANATION_MISSING",
                f"{operation.applicability} requires an explanation of the decision"))
            return
        state = operation.applicability
        verified = False
        detail: str | None = None
        if state == ALREADY_SATISFIED:
            verified, detail = self._verify_already_satisfied(operation)
            if not verified:
                outcome.rejected.append(self._reject(
                    operation, "APPLICABILITY_CLAIM_UNSUPPORTED",
                    f"this KÜYEN cannot confirm that the request is already satisfied: {detail}"))
                return
        elif state == BLOCKED_BY_PERMISSION:
            required = permissions_for(operation.op) or tuple(operation.requires)
            missing = self.scope.missing(required)
            if not missing:
                outcome.rejected.append(self._reject(
                    operation, "APPLICABILITY_CLAIM_UNSUPPORTED",
                    f"{operation.op} needs {', '.join(required) or 'no permission'} and this "
                    "KÜYEN grants it, so it is not blocked by permission"))
                return
            verified, detail = True, f"missing {', '.join(missing)}"
        elif state == REQUIRES_DATA_ACCESS:
            if self.scope.data_read:
                outcome.rejected.append(self._reject(
                    operation, "APPLICABILITY_CLAIM_UNSUPPORTED",
                    "this KÜYEN grants DATA_READ: the operation does not lack data access"))
                return
            verified, detail = True, "DATA_READ is not granted to this Antü"
        elif state == NOT_APPLICABLE:
            verified, detail = self._verify_not_applicable(operation)
            if not verified:
                outcome.rejected.append(self._reject(
                    operation, "APPLICABILITY_CLAIM_UNSUPPORTED",
                    f"this KÜYEN does contain the elements the operation needs: {detail}"))
                return
        else:  # OUT_OF_SCOPE, NEEDS_CLARIFICATION
            detail = "judgement of the model; KÜYEN records it without execution"
        outcome.declined.append(OperationDecline(
            operation_id=operation.operation_id, op=operation.op, applicability=state,
            explanation=explanation, verified=verified, target=operation.target_id,
            detail=detail))

    def _verify_already_satisfied(self, operation: GraphEditOperation) -> tuple[bool, str]:
        """True when this version already contains what the operation would have added."""
        if operation.op in SCHEMA_OPERATIONS:
            if self.schema is None:
                return False, "this version carries no schema"
            entity_type = str(operation.value.get("entity_type") or "").strip()
            declaration = operation.value.get("field") or operation.value.get("name")
            try:
                name = normalize_field_name(
                    declaration.get("name") if isinstance(declaration, Mapping) else declaration)
            except SchemaError as exc:
                return False, f"the field name cannot be read: {exc}"
            current = self.schema.field(entity_type, name)
            if current is None:
                return False, f"field {name!r} is not declared on {entity_type!r}"
            return True, f"field {name!r} already declared on {entity_type!r}"
        identifier = operation.target_id
        if not identifier:
            # A decline does not need a canonical id if KÜYEN can verify the claim on the
            # statement itself: "this relation already exists" is checkable from the endpoints
            # and the predicate, and a real model phrases it exactly that way (experiment 15).
            if operation.op == "ADD_RELATION":
                stored = self._stored_relation(
                    from_entity=str(operation.value.get("from") or ""),
                    to_entity=str(operation.value.get("to") or ""),
                    predicate=str(operation.value.get("predicate") or ""),
                    polarity=str(operation.value.get("polarity") or "POSITIVE").strip().upper(),
                    temporal=operation.value.get("temporal_scope"))
                if stored is not None:
                    return True, (f"relation {stored.get('relation_id')} already states it "
                                  f"between those entities")
                return False, "no relation in this version states what it claims is already there"
            if operation.op == "ADD_ENTITY":
                name = normalized(operation.value.get("name"))
                entity_type = str(operation.value.get("entity_type") or "")
                for entity in self.context.entities:
                    if normalized(entity.get("name")) == name \
                            and str(entity.get("entity_type")) == entity_type:
                        return True, (f"{entity.get('entity_id')} already is a "
                                      f"{entity_type!r} with that name")
                return False, "no entity of that type has that name in this version"
            return False, "the operation does not identify what is already satisfied"

        if not self._exists_in_version(operation.target_kind or "", identifier):
            return False, f"{identifier} does not exist in this version"
        target = self._existing(operation.target_kind or "", identifier)
        if target is None:
            return True, f"{identifier} exists (outside the authorised context)"
        expected = operation.expected or {}
        for key, value in expected.items():
            if str(key).startswith("_"):
                continue
            if not self._claim_matches(target.get(key), value):
                return False, f"{identifier}.{key} is {target.get(key)!r}, not {value!r}"
        return True, f"{identifier} already matches the request"

    @staticmethod
    def _claim_matches(actual: Any, expected: Any) -> bool:
        """Compare a claimed value with the stored one without inventing a difference.

        A model that claims "this relation is not retracted" writes `retracted: false`; the
        stored object simply has no `retracted` key, which means the same thing. Statuses are
        compared case-insensitively. Any other difference is a real one and the claim fails.
        """
        if actual == expected:
            return True
        if isinstance(expected, bool):
            return expected is False and actual is None
        if isinstance(expected, str) and isinstance(actual, str):
            return actual.strip().upper() == expected.strip().upper()
        return False


    @staticmethod
    def _verify_not_applicable(operation: GraphEditOperation) -> tuple[bool, str]:
        """The model claims the elements do not exist; a declared target contradicts it."""
        if operation.target_id:
            return False, f"it targets {operation.target_id}, which it says does not exist"
        return True, "no local element is required by the claim"

    # ---------- schema operations (§6, §7) ----------
    def _schema_or_reject(self, operation: GraphEditOperation,
                          outcome: ValidationOutcome) -> GraphSchema | None:
        if self.schema is None:
            outcome.rejected.append(self._reject(
                operation, "SCHEMA_UNAVAILABLE",
                "this version carries no schema, so it cannot be changed structurally"))
            return None
        if not self.scope.schema_read:
            outcome.rejected.append(self._reject(
                operation, "PERMISSION_REQUIRED", "the schema is not readable in this scope"))
            return None
        return self.schema

    def _field_declaration(self, operation: GraphEditOperation, outcome: ValidationOutcome,
                           *, entity_type: str) -> dict[str, Any] | None:
        raw = operation.value.get("field")
        if raw is None:
            raw = {key: operation.value.get(key)
                   for key in ("name", "value_type", "required", "label", "description")
                   if operation.value.get(key) is not None}
        try:
            declaration = normalize_field(raw or {})
        except SchemaError as exc:
            outcome.rejected.append(self._reject(operation, "SCHEMA_FIELD_INVALID", str(exc)))
            return None
        if not isinstance(declaration, Mapping) or not declaration.get("name"):
            # A malformed proposal is a rejection, never a crash (experiment 14: a real model
            # sent `value.entity_type` without the field and the engine raised KeyError).
            outcome.rejected.append(self._reject(
                operation, "VALUE_INCOMPLETE",
                "the operation must declare value.field.name"))
            return None
        declared_type = str(operation.value.get("entity_type") or "").strip()
        if declared_type and entity_type and declared_type != entity_type:
            outcome.rejected.append(self._reject(
                operation, "SCHEMA_FIELD_INVALID",
                f"the operation names two entity types: {declared_type!r} and {entity_type!r}"))
            return None
        return declaration

    def _validate_add_field(self, operation: GraphEditOperation,
                            outcome: ValidationOutcome) -> None:
        schema = self._schema_or_reject(operation, outcome)
        if schema is None:
            return
        entity_type = str(operation.value.get("entity_type") or "").strip()
        if not entity_type:
            outcome.rejected.append(self._reject(
                operation, "VALUE_INCOMPLETE", "ADD_FIELD requires value.entity_type"))
            return
        if not schema.has_entity_type(entity_type):
            outcome.rejected.append(self._reject(
                operation, "ENTITY_TYPE_NOT_IN_SCHEMA",
                f"this KÜYEN has no entity type {entity_type!r}: the Antü does not apply here"))
            return
        declaration = self._field_declaration(operation, outcome, entity_type=entity_type)
        if declaration is None:
            return
        current = schema.field(entity_type, declaration["name"])
        if current is not None:
            outcome.rejected.append(self._reject(
                operation, "FIELD_ALREADY_DECLARED",
                f"{entity_type}.{declaration['name']} already exists with value_type "
                f"{current.get('value_type')!r}: report ALREADY_SATISFIED instead of "
                "declaring it twice"))
            return
        operation.value = {**operation.value, "_entity_type": entity_type,
                           "_field": declaration, "_previous": None}
        self.declared_fields[(entity_type, str(declaration.get("name") or ""))] = dict(declaration)
        outcome.accepted.append(operation)


    def _validate_update_field(self, operation: GraphEditOperation,
                               outcome: ValidationOutcome) -> None:
        schema = self._schema_or_reject(operation, outcome)
        if schema is None:
            return
        entity_type = str(operation.value.get("entity_type") or "").strip()
        declaration = self._field_declaration(operation, outcome, entity_type=entity_type)
        if declaration is None:
            return
        current = schema.field(entity_type, declaration["name"])
        if current is None:
            outcome.rejected.append(self._reject(
                operation, "FIELD_NOT_DECLARED",
                f"{entity_type}.{declaration['name']} is not declared in this version"))
            return
        if not self._check_expected(operation, current, outcome.rejected,
                                    fields=("value_type", "required", "label", "description")):
            return
        operation.value = {**operation.value, "_entity_type": entity_type,
                           "_field": declaration, "_previous": dict(current)}
        outcome.accepted.append(operation)

    def _validate_retract_field(self, operation: GraphEditOperation,
                                outcome: ValidationOutcome) -> None:
        schema = self._schema_or_reject(operation, outcome)
        if schema is None:
            return
        entity_type = str(operation.value.get("entity_type") or "").strip()
        raw = operation.value.get("field") or operation.value.get("name")
        try:
            name = normalize_field_name(raw.get("name") if isinstance(raw, Mapping) else raw)
        except SchemaError as exc:
            outcome.rejected.append(self._reject(operation, "SCHEMA_FIELD_INVALID", str(exc)))
            return
        current = schema.field(entity_type, name)
        if current is None:
            outcome.rejected.append(self._reject(
                operation, "FIELD_NOT_DECLARED",
                f"{entity_type}.{name} is not declared in this version"))
            return
        if not self._check_expected(operation, current, outcome.rejected,
                                    fields=("value_type", "required", "label", "description")):
            return
        operation.value = {**operation.value, "_entity_type": entity_type,
                           "_field_name": name, "_previous": dict(current)}
        outcome.accepted.append(operation)

    def _validate_retract_entity(self, operation: GraphEditOperation,
                                 outcome: ValidationOutcome) -> None:
        target = self._resolve_target(operation, "entity", outcome.rejected)
        if target is None:
            return
        if not self._check_expected(operation, target, outcome.rejected,
                                    fields=("status", "name", "entity_type")):
            return
        operation.value = {**operation.value, "_target_id": target.get("entity_id"),
                           "_previous": {"status": target.get("status")}}
        outcome.accepted.append(operation)

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
        new_name = str(operation.value.get("name") or "").strip()
        if new_name:
            # §4: renaming keeps the identity. It never creates a second entity and it never
            # merges two similar ones: a name already taken by the same type is a collision
            # the Antü has to resolve, not a silent merge.
            for entity in self.context.entities:
                if entity.get("entity_id") == target.get("entity_id"):
                    continue
                if normalized(entity.get("name")) != normalized(new_name):
                    continue
                if str(entity.get("entity_type")) != str(target.get("entity_type")):
                    continue
                outcome.rejected.append(self._reject(
                    operation, "ENTITY_NAME_COLLISION",
                    f"{new_name!r} is already the name of {entity.get('entity_id')} "
                    f"({entity.get('entity_type')}): renaming this entity would merge two "
                    "identities; ask for clarification instead"))
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
        declared = (self.schema.field(target.get("entity_type"), attribute)
                    if self.schema is not None else None)
        if declared is None:
            # A field this same Antü declares counts: `ADD_FIELD` plus `UPDATE_ATTRIBUTE` in
            # one answer is how an Antü introduces a typed attribute and gives it a value.
            declared = self.declared_fields.get((str(target.get("entity_type") or ""), attribute))
        exists = isinstance(metadata, Mapping) and attribute in metadata

        if declared is None and not exists:
            # §5: an attribute is either already there or declared in the schema of this very
            # version. Creating one silently would be inventing structure behind the Antü.
            outcome.rejected.append(self._reject(
                operation, "ATTRIBUTE_NOT_DECLARED",
                f"{target.get('entity_type')}.{attribute} is neither declared in the schema "
                "nor present on this entity: declare it with ADD_FIELD first (ADD_FIELD, then "
                "UPDATE_ATTRIBUTE with depends_on) or update an existing attribute"))
            return
        new_value = operation.value.get("value")
        if declared is not None:
            problem = attribute_value_problem(declared.get("value_type"), new_value)
            if problem is not None:
                outcome.rejected.append(self._reject(
                    operation, "ATTRIBUTE_TYPE_MISMATCH",
                    f"{attribute} is declared as {declared.get('value_type')}: {problem}"))
                return
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
                           "_attribution": operation.value.get("attribution"),
                           "_scope": str(operation.value.get("scope") or "instruction"),
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
        if not self._partial_update(operation, target, outcome, kind="assertion"):
            return
        outcome.accepted.append(operation)

    # ---------- partial updates (§3, §4) ----------
    def _partial_update(self, operation: GraphEditOperation, target: Mapping[str, Any],
                        outcome: ValidationOutcome, *, kind: str) -> bool:
        """Validate a patched statement without destroying the properties it does not name.

        The operation declares only the properties it changes. Everything else is inherited
        from the target: value type, unit and context inside `value`, modality, polarity,
        scope, temporal scope and attribution. A property that takes part in the identity of
        the statement produces a new object that supersedes the old one; a property that does
        not (modality, attribution) keeps the same identity and is recorded in place.
        """
        fields = _ASSERTION_UPDATE_FIELDS if kind == "assertion" else _RELATION_UPDATE_FIELDS
        identity_fields = (_ASSERTION_IDENTITY_FIELDS if kind == "assertion"
                           else _RELATION_IDENTITY_FIELDS)
        changed = [key for key in fields if key in operation.value]
        if not changed:
            outcome.rejected.append(self._reject(
                operation, "VALUE_INCOMPLETE",
                f"UPDATE_{kind.upper()} requires one of {list(fields)}"))
            return False
        expected_fields = [key for key in changed if key in (operation.expected or {})]
        if not expected_fields:
            outcome.rejected.append(self._reject(
                operation, "EXPECTED_VALUE_REQUIRED",
                f"UPDATE_{kind.upper()} must declare the current value of {changed}"))
            return False
        if not self._check_expected(operation, target, outcome.rejected, fields=expected_fields):
            return False
        identity_changed = any(key in operation.value for key in identity_fields)
        if kind == "assertion":
            return self._assertion_patch(operation, target, outcome, identity_changed)
        return self._relation_patch(operation, target, outcome, identity_changed)

    def _assertion_patch(self, operation: GraphEditOperation, target: Mapping[str, Any],
                         outcome: ValidationOutcome, identity_changed: bool) -> bool:
        target_value = target.get("value") if isinstance(target.get("value"), Mapping) else None
        if "value" in operation.value:
            patch_value = operation.value["value"]
            if isinstance(patch_value, Mapping) and target_value is not None:
                # A patch changes the number, not the unit or the context it did not name.
                payload = coercer_value({**dict(target_value), **dict(patch_value)})
            else:
                payload = coercer_value(patch_value)
        else:
            payload = None
        object_entity = str(operation.value.get("object_entity") or "").strip() or None
        polarity = str(operation.value.get("polarity") or target.get("polarity") or "").upper()
        if polarity not in POLARITIES:
            outcome.rejected.append(self._reject(
                operation, "POLARITY_NOT_ADMITTED",
                f"polarity {polarity!r} cannot be stored in the canonical set"))
            return False
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
            return False
        scope = str(operation.value.get("scope") or target.get("scope") or "instruction")
        modality = self._modality(operation, outcome.rejected,
                                  default=str(target.get("modality") or "UNKNOWN"))
        attribution = (operation.value["attribution"] if "attribution" in operation.value
                       else (target.get("attribution") if not identity_changed else None))
        predicate = str(operation.value.get("predicate") or target.get("predicate") or "")
        temporal_scope = str(operation.value.get("temporal_scope")
                             or target.get("temporal_scope") or "") or None
        candidate_id = assertion_id_for(
            subject=str(target.get("subject_entity") or ""), predicate=predicate,
            object_entity=final_object, value=final_value, polarity=polarity, scope=scope,
            temporal_scope=temporal_scope) if identity_changed else str(target.get("assertion_id"))
        if candidate_id in self.assertions and candidate_id != target.get("assertion_id"):
            outcome.rejected.append(self._reject(
                operation, "DUPLICATE_OBJECT",
                f"assertion {candidate_id} already exists in this version"))
            return False
        operation.value = {**operation.value, "_canonical_id": candidate_id,
                           "_polarity": polarity, "_modality": modality,
                           "_attribution": attribution, "_scope": scope,
                           "_value_payload": final_value, "_object_entity": final_object,
                           "_predicate": predicate, "_identity_changed": identity_changed,
                           "_target_id": target.get("assertion_id")}
        return True

    def _relation_patch(self, operation: GraphEditOperation, target: Mapping[str, Any],
                        outcome: ValidationOutcome, identity_changed: bool) -> bool:
        polarity = (self._polarity(operation, outcome.rejected) if "polarity" in operation.value
                    else str(target.get("polarity") or "").upper())
        if polarity not in POLARITIES:
            outcome.rejected.append(self._reject(
                operation, "POLARITY_NOT_ADMITTED",
                f"polarity {polarity!r} cannot be stored in the canonical set"))
            return False
        predicate = str(operation.value.get("predicate") or target.get("predicate") or "")
        label = str(operation.value.get("label") or target.get("label") or predicate)
        scope = str(operation.value.get("scope") or target.get("scope") or "instruction")
        modality = self._modality(operation, outcome.rejected,
                                  default=str(target.get("modality") or "UNKNOWN"))
        attribution = (operation.value["attribution"] if "attribution" in operation.value
                       else (target.get("attribution") if not identity_changed else None))
        temporal_scope = (operation.value.get("temporal_scope") if "temporal_scope"
                          in operation.value else target.get("temporal_scope"))
        candidate_id = relation_id_for(
            from_entity=str(target.get("from_entity") or ""), predicate=predicate,
            to_entity=str(target.get("to_entity") or ""), polarity=polarity,
            temporal_scope=temporal_scope) if identity_changed else str(target.get("relation_id"))
        if candidate_id in self.relations and candidate_id != target.get("relation_id"):
            outcome.rejected.append(self._reject(
                operation, "DUPLICATE_OBJECT",
                f"relation {candidate_id} already exists in this version"))
            return False
        operation.value = {**operation.value, "_canonical_id": candidate_id,
                           "_polarity": polarity, "_modality": modality,
                           "_attribution": attribution, "_scope": scope,
                           "_predicate": predicate, "_label": label,
                           "_identity_changed": identity_changed,
                           "_target_id": target.get("relation_id")}
        return True


    def _same_relation(self, relation: Mapping[str, Any], *, from_entity: str, to_entity: str,
                       predicate: str, polarity: str, temporal: Any) -> bool:
        """True when a stored relation states exactly the same thing, whatever its id.

        Relation identifiers are produced by the projection and are not reproducible from the
        statement, so duplication is decided on what the relation says: endpoints, predicate,
        polarity and temporal scope. A retracted relation does not make a new one a duplicate.
        """
        if relation.get("retracted") or str(relation.get("status") or "") == "RETRACTED":
            return False
        return (str(relation.get("from_entity") or "") == from_entity
                and str(relation.get("to_entity") or "") == to_entity
                and str(relation.get("predicate") or "") == predicate
                and str(relation.get("polarity") or "").upper() == polarity
                and (str(relation.get("temporal_scope") or "") == str(temporal or "")))

    def _stored_relation(self, *, from_entity: str, to_entity: str, predicate: str,
                         polarity: str, temporal: Any) -> dict[str, Any] | None:
        for relation in self.context.relations:
            if self._same_relation(relation, from_entity=from_entity, to_entity=to_entity,
                                   predicate=predicate, polarity=polarity, temporal=temporal):
                return relation
        return None

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
        # §3: no duplication. A relation is compared by what it says, not only by its id (ids
        # come from the projection), and the check covers the whole authorised context: a
        # relation that already exists must not be asserted twice.
        stored = self._stored_relation(from_entity=source, to_entity=target, predicate=predicate,
                                       polarity=polarity, temporal=temporal)
        if stored is not None or self._exists_in_version("relation", candidate_id):
            outcome.rejected.append(self._reject(
                operation, "DUPLICATE_OBJECT",
                f"relation {predicate!r} from {source} to {target} already exists"
                f" ({stored.get('relation_id') if stored else candidate_id}): report "
                "ALREADY_SATISFIED instead of adding it twice"))
            return
        reversed_stored = self._stored_relation(from_entity=target, to_entity=source,
                                                predicate=predicate, polarity=polarity,
                                                temporal=temporal)
        reversed_id = relation_id_for(from_entity=target, predicate=predicate,
                                      to_entity=source, polarity=polarity,
                                      temporal_scope=temporal)
        if ((reversed_stored is not None or (reversed_id != candidate_id
                                             and self._exists_in_version("relation", reversed_id)))
                and reversed_id not in self.retraction_targets
                and (reversed_stored or {}).get("relation_id") not in self.retraction_targets):
            # The same predicate already holds in the opposite direction and this Antü is not
            # withdrawing it. Adding it would assert both directions, which is almost always a
            # misread instruction: KÜYEN does not choose for the user.
            existing = (reversed_stored or {}).get("relation_id") or reversed_id
            outcome.rejected.append(self._reject(
                operation, "RELATION_DIRECTION_CONFLICT",
                f"{predicate!r} already holds from {target} to {source} ({existing}); the "
                "opposite direction is ambiguous unless the existing relation is retracted in "
                "the same Antü"))
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
        if target.get("retracted") or str(target.get("status") or "") == "RETRACTED":
            outcome.rejected.append(self._reject(
                operation, "TARGET_RETRACTED",
                f"relation {target.get('relation_id')} is retracted; add a new statement"))
            return
        if not self._partial_update(operation, target, outcome, kind="relation"):
            return
        outcome.accepted.append(operation)

