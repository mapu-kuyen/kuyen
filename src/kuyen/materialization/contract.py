"""Versioned provider-result contract for KÜYEN 0.1.4.

The provider contract is deliberately small and separate from KÜYEN's canonical
candidate model. It describes what the agent may propose; KÜYEN decides what can be
materialized as evidence.
"""
from __future__ import annotations

from typing import Any

from ..errors import CandidateMaterializationError

CONTRACT_ID = "kuyen-provider-result-v1"
NATIVE_CONTRACT_ID = "kuyen-native-files-v1"
RESULT_FILENAME = "kuyen_result.json"
LEGACY_SIDECAR = "kuyen_candidates.json"

TOP_LEVEL_KEYS = {"schema_version", "provider", "entities", "relations", "assertions", "coverage"}
ENTITY_KEYS = {"provider_id", "id", "name", "title", "entity_type", "type", "aliases", "description", "sources", "evidence"}
# `predicate` is the carrier field. The nine predicate-layer fields below make the
# provider able to declare the three dimensions (source / canonical / provider
# projection) and the correspondence state, so the contract no longer drops them.
RELATION_KEYS = {
    "from", "to", "predicate", "relation", "label", "polarity", "scope",
    "temporal_scope", "temporal", "sources", "evidence",
    "source_predicate", "canonical_predicate", "provider_predicate",
    "display_label", "provider_label", "mapping_status",
    "mapping_rule_id", "mapping_version", "provider_projection_status",
}
ASSERTION_KEYS = {
    "subject", "predicate", "object_entity", "value", "polarity", "scope",
    "temporal_scope", "temporal", "sources", "evidence", "epistemic_status", "proposed_status",
}
EVIDENCE_KEYS = {
    "quote", "char_start", "char_end", "source_uri", "source_sha256", "mapu_id",
    "evidence_id", "extraction_method", "offset_unit",
}


def _require_list(data: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = data.get(key, [])
    if value is None:
        return []
    if not isinstance(value, list):
        raise CandidateMaterializationError(f"provider result field {key} must be a list")
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise CandidateMaterializationError(f"provider result {key}[{index}] must be an object")
    return value


def _unknown_keys(items: list[dict[str, Any]], allowed: set[str], label: str) -> list[str]:
    unknown: list[str] = []
    for index, item in enumerate(items):
        for key in item:
            if key not in allowed:
                unknown.append(f"{label}[{index}].{key}")
    return unknown


def normalize_provider_result(data: Any) -> dict[str, Any]:
    """Validate the top-level contract and normalize aliases.

    Unknown top-level fields are rejected: a wrapped payload or a different schema
    must not be guessed. Unknown item-level fields are recorded and ignored.
    """
    if not isinstance(data, dict):
        raise CandidateMaterializationError(
            f"provider result must be a JSON object, got {type(data).__name__}"
        )
    unknown_top = sorted(set(data) - TOP_LEVEL_KEYS)
    if unknown_top:
        raise CandidateMaterializationError(
            f"provider result has unknown top-level fields: {unknown_top}",
            details={"unknown_fields": unknown_top},
        )
    version = str(data.get("schema_version") or "")
    if version != CONTRACT_ID:
        raise CandidateMaterializationError(
            f"provider result schema_version must be {CONTRACT_ID}, got {version or '<empty>'}",
            details={"schema_version": version},
        )
    entities = _require_list(data, "entities")
    relations = _require_list(data, "relations")
    assertions = _require_list(data, "assertions")
    coverage = _require_list(data, "coverage")
    warnings: list[str] = []
    warnings.extend(f"ignored unknown field {item}" for item in _unknown_keys(entities, ENTITY_KEYS, "entities"))
    warnings.extend(f"ignored unknown field {item}" for item in _unknown_keys(relations, RELATION_KEYS, "relations"))
    warnings.extend(f"ignored unknown field {item}" for item in _unknown_keys(assertions, ASSERTION_KEYS, "assertions"))
    for collection, label in ((entities, "entities"), (relations, "relations"), (assertions, "assertions")):
        for index, item in enumerate(collection):
            evidence = item.get("evidence")
            if evidence is None:
                continue
            if not isinstance(evidence, list):
                raise CandidateMaterializationError(f"{label}[{index}].evidence must be a list")
            for evidence_index, entry in enumerate(evidence):
                if not isinstance(entry, dict):
                    raise CandidateMaterializationError(
                        f"{label}[{index}].evidence[{evidence_index}] must be an object"
                    )
                warnings.extend(
                    f"ignored unknown field {label}[{index}].evidence[{evidence_index}].{key}"
                    for key in entry if key not in EVIDENCE_KEYS
                )
    return {
        "schema_version": version,
        "provider": dict(data.get("provider") or {}),
        "entities": entities,
        "relations": relations,
        "assertions": assertions,
        "coverage": coverage,
        "warnings": warnings,
    }
