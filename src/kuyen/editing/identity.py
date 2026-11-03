"""Deterministic canonical identities for objects created by an Antü instruction.

KÜYEN owns identity (§6.1). The model proposes a *local* reference; these functions turn
it into the same style of canonical identifier the document path produces, and they are
deterministic, so replaying the same instruction yields the same identities and cannot
create a duplicate object.

The formulas match `kuyen.normalization.normalizer` on purpose: the same relation
proposed by a document and by an instruction must resolve to the same `rel_...` identity.
"""
from __future__ import annotations

from typing import Any, Mapping

from ..canonical import normalized_name, stable_id
from ..models import Value

ANTU_NAMESPACE = "antu-instruction"


def entity_id_for(*, antu_id: str, ref: str, entity_type: str) -> str:
    """Canonical identity of an entity proposed by an instruction."""
    return stable_id("ent", {"namespace": ANTU_NAMESPACE,
                             "source_id": f"{antu_id}:{ref}",
                             "type": str(entity_type or "")})


def relation_id_for(*, from_entity: str, predicate: str, to_entity: str, polarity: str,
                    scope: str = "instruction", temporal_scope: str | None = None) -> str:
    return stable_id("rel", {"from": from_entity, "predicate": predicate, "to": to_entity,
                             "polarity": polarity, "scope": scope,
                             "temporal": temporal_scope})


def assertion_id_for(*, subject: str, predicate: str, object_entity: str | None,
                     value: Mapping[str, Any] | None, polarity: str,
                     scope: str = "instruction", temporal_scope: str | None = None) -> str:
    return stable_id("asrt", {"subject": subject, "predicate": predicate,
                              "object_entity": object_entity,
                              "value": dict(value) if value else None,
                              "polarity": polarity, "scope": scope,
                              "temporal": temporal_scope})


def coercer_value(raw: Any) -> dict[str, Any] | None:
    """Normalise the `value` payload of an operation into a canonical `Value` record."""
    if raw is None:
        return None
    if isinstance(raw, Value):
        return raw.to_dict()
    if isinstance(raw, Mapping):
        return {"value_type": str(raw.get("value_type") or raw.get("type") or "string"),
                "value": raw.get("value"),
                "unit": raw.get("unit"),
                "context": raw.get("context")}
    if isinstance(raw, bool):
        return {"value_type": "boolean", "value": raw, "unit": None, "context": None}
    if isinstance(raw, int):
        return {"value_type": "integer", "value": raw, "unit": None, "context": None}
    if isinstance(raw, float):
        return {"value_type": "number", "value": raw, "unit": None, "context": None}
    return {"value_type": "string", "value": str(raw), "unit": None, "context": None}


def entity_identity_block(*, entity_id: str, ref: str, antu_id: str) -> dict[str, Any]:
    """Identity fields every Antü-created entity carries."""
    return {"entity_id": entity_id, "source_entity_id": f"{antu_id}:{ref}",
            "source_namespace": ANTU_NAMESPACE, "identity_basis": "antu_instruction",
            "normalization_status": "RESOLVED", "normalization_reason": None,
            "origin_entity_id": f"{antu_id}:{ref}", "canonical_entity_id": entity_id,
            "identity_status": "INSTRUCTED", "identity_group_id": None}


def normalized(value: Any) -> str:
    return normalized_name(str(value or ""))
