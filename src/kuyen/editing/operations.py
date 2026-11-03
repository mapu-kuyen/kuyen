"""The structured operation contract an Antü graph edit must follow.

KUYEN_PRODUCTIVE_GRAPH_11, §6.2. The model does not return a graph: it returns a list of
operations with an identity, a target, the value it expects to find, the value it
proposes, a reason and the fragment of the instruction that supports it. KÜYEN validates
every operation and applies them deterministically; nothing here writes to the store.

The format is versioned (`kuyen-graph-edit-v1`) and deliberately small: an operation the
contract does not describe is refused instead of being guessed.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Mapping

from ..errors import InvalidRequestError

EDIT_CONTRACT_ID = "kuyen-graph-edit-v1"
SUPPORTED_EDIT_CONTRACTS = (EDIT_CONTRACT_ID,)

ADD_ENTITY = "ADD_ENTITY"
UPDATE_ENTITY = "UPDATE_ENTITY"
ADD_ASSERTION = "ADD_ASSERTION"
UPDATE_ASSERTION = "UPDATE_ASSERTION"
RETRACT_ASSERTION = "RETRACT_ASSERTION"
ADD_RELATION = "ADD_RELATION"
UPDATE_RELATION = "UPDATE_RELATION"
RETRACT_RELATION = "RETRACT_RELATION"
UPDATE_ATTRIBUTE = "UPDATE_ATTRIBUTE"

OPERATION_TYPES = (
    ADD_ENTITY, UPDATE_ENTITY, ADD_ASSERTION, UPDATE_ASSERTION, RETRACT_ASSERTION,
    ADD_RELATION, UPDATE_RELATION, RETRACT_RELATION, UPDATE_ATTRIBUTE,
)
ADDITIVE_OPERATIONS = (ADD_ENTITY, ADD_ASSERTION, ADD_RELATION)
REPLACING_OPERATIONS = (UPDATE_ENTITY, UPDATE_ASSERTION, UPDATE_RELATION, UPDATE_ATTRIBUTE)
RETRACTING_OPERATIONS = (RETRACT_ASSERTION, RETRACT_RELATION)
# Operations that must declare the value they expect to find (optimistic check).
OPERATIONS_REQUIRING_EXPECTED = REPLACING_OPERATIONS + RETRACTING_OPERATIONS
# Operations whose target is an existing canonical object.
OPERATIONS_TARGETING_EXISTING = (UPDATE_ENTITY, UPDATE_ASSERTION, RETRACT_ASSERTION,
                                UPDATE_RELATION, RETRACT_RELATION, UPDATE_ATTRIBUTE)

PROPOSED = "PROPOSED"
CLARIFICATION_REQUIRED = "CLARIFICATION_REQUIRED"
CONFLICT = "CONFLICT"
NO_CHANGES = "NO_CHANGES"
PROPOSAL_STATUSES = (PROPOSED, CLARIFICATION_REQUIRED, CONFLICT, NO_CHANGES)

POLARITIES = ("POSITIVE", "NEGATIVE")
MODALITIES = ("FACT", "FORECAST", "ESTIMATE", "OPINION", "CONDITIONAL", "UNKNOWN")

ENTITY_ID_RE = re.compile(r"^ent_[a-f0-9]{20}$")
RELATION_ID_RE = re.compile(r"^rel_[a-f0-9]{20}$")
ASSERTION_ID_RE = re.compile(r"^asrt_[a-f0-9]{20}$")
EVIDENCE_ID_RE = re.compile(r"^ev_[a-f0-9]{20}$")


class EditContractError(InvalidRequestError):
    """The proposal itself cannot be read as a graph-edit contract document."""


@dataclass
class GraphEditOperation:
    operation_id: str
    op: str
    target: dict[str, Any] | None = None
    expected: dict[str, Any] | None = None
    value: dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    antu_ref: str = ""
    affected: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def target_id(self) -> str | None:
        """The canonical identifier the operation points at, when it declares one."""
        target = self.target or {}
        for key in ("entity_id", "relation_id", "assertion_id", "id"):
            if isinstance(target.get(key), str) and target[key].strip():
                return target[key].strip()
        return None

    @property
    def target_kind(self) -> str | None:
        target = self.target or {}
        for key, kind in (("entity_id", "entity"), ("relation_id", "relation"),
                          ("assertion_id", "assertion")):
            if target.get(key):
                return kind
        if target.get("id"):
            return str(target.get("kind") or "") or None
        return None

    @property
    def reference(self) -> str | None:
        """A model-local handle for an object this same proposal proposes to add."""
        for container in (self.target or {}, self.value or {}):
            for key in ("entity_ref", "ref", "proposed_ref", "local_ref"):
                value = container.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        return None

    def to_dict(self) -> dict[str, Any]:
        return {"operation_id": self.operation_id, "op": self.op, "target": self.target,
                "expected": self.expected, "value": self.value, "reason": self.reason,
                "antu_ref": self.antu_ref, "affected": list(self.affected)}


@dataclass
class GraphEditProposal:
    status: str
    operations: list[GraphEditOperation]
    antu_id: str | None = None
    base_version_id: str | None = None
    interpretation: str = ""
    clarification: dict[str, Any] | None = None
    conflict: dict[str, Any] | None = None
    schema_version: str = EDIT_CONTRACT_ID
    warnings: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": self.schema_version, "status": self.status,
                "antu_id": self.antu_id, "base_version_id": self.base_version_id,
                "interpretation": self.interpretation,
                "clarification": self.clarification, "conflict": self.conflict,
                "operations": [item.to_dict() for item in self.operations],
                "warnings": list(self.warnings)}



def _strip_fence(text: str) -> str:
    """Accept a Markdown fence around the JSON object; nothing else is tolerated."""
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def parse_proposal(payload: str | Mapping[str, Any]) -> GraphEditProposal:
    """Read a proposal from the model output. Structural defects raise, content does not.

    "Content" here means an operation KÜYEN will reject with a reason (unknown type,
    missing target, unsupported claim). A document that is not even a proposal — invalid
    JSON, no `operations` list, an unsupported contract version — raises
    `EditContractError`, because there is nothing to validate.
    """
    if isinstance(payload, Mapping):
        data: Any = dict(payload)
        warnings: list[str] = []
    else:
        if not isinstance(payload, str) or not payload.strip():
            raise EditContractError("the editor returned an empty proposal",
                                    details={"code": "PROPOSAL_EMPTY"})
        text = _strip_fence(payload)
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise EditContractError(
                f"the editor did not return JSON: {exc}",
                details={"code": "PROPOSAL_NOT_JSON"}) from exc
        warnings = (["stripped a Markdown fence around the proposal"]
                    if text != payload.strip() else [])
    if not isinstance(data, Mapping):
        raise EditContractError("the proposal must be a JSON object",
                                details={"code": "PROPOSAL_NOT_OBJECT"})
    version = str(data.get("schema_version") or EDIT_CONTRACT_ID)
    if version not in SUPPORTED_EDIT_CONTRACTS:
        raise EditContractError(
            f"unsupported graph-edit contract: {version}",
            details={"code": "PROPOSAL_CONTRACT_UNSUPPORTED", "schema_version": version})
    status = str(data.get("status") or "").strip().upper() or PROPOSED
    if status not in PROPOSAL_STATUSES:
        raise EditContractError(
            f"unsupported proposal status: {status}",
            details={"code": "PROPOSAL_STATUS_INVALID", "status": status})
    raw_operations = data.get("operations")
    if raw_operations is None:
        raw_operations = []
    if not isinstance(raw_operations, list):
        raise EditContractError("operations must be a list",
                                details={"code": "PROPOSAL_OPERATIONS_INVALID"})
    operations: list[GraphEditOperation] = []
    for index, item in enumerate(raw_operations):
        if not isinstance(item, Mapping):
            raise EditContractError(f"operations[{index}] must be an object",
                                    details={"code": "PROPOSAL_OPERATION_INVALID", "index": index})
        operations.append(GraphEditOperation(
            operation_id=str(item.get("operation_id") or f"op-{index + 1}"),
            op=str(item.get("op") or item.get("type") or "").strip().upper(),
            target=dict(item["target"]) if isinstance(item.get("target"), Mapping) else (
                {"id": str(item["target"])} if isinstance(item.get("target"), str) else None),
            expected=dict(item["expected"]) if isinstance(item.get("expected"), Mapping) else None,
            value=dict(item["value"]) if isinstance(item.get("value"), Mapping) else (
                {"literal": item["value"]} if item.get("value") is not None else {}),
            reason=str(item.get("reason") or ""),
            antu_ref=str(item.get("antu_ref") or item.get("antu_span") or ""),
            affected=[str(x) for x in (item.get("affected") or [])],
            raw=dict(item),
        ))
    clarification = data.get("clarification") if isinstance(data.get("clarification"), Mapping) else None
    conflict = data.get("conflict") if isinstance(data.get("conflict"), Mapping) else None
    if status == PROPOSED and not operations:
        status = NO_CHANGES
    if status == CLARIFICATION_REQUIRED and not clarification:
        clarification = {"question": "the instruction is ambiguous", "reason": "no detail provided"}
    return GraphEditProposal(
        status=status, operations=operations,
        antu_id=(str(data.get("antu_id")) if data.get("antu_id") else None),
        base_version_id=(str(data.get("base_version_id")) if data.get("base_version_id") else None),
        interpretation=str(data.get("interpretation") or ""),
        clarification=clarification, conflict=conflict,
        schema_version=version, warnings=warnings, raw=dict(data),
    )
