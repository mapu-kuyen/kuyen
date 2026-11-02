"""Versioned extraction schema for OpenAI Structured Outputs.

The schema is generated from the frozen Antü and ontology so the model cannot
emit an entity type, relation predicate or scalar predicate outside the request.
It deliberately uses only the strict Structured Outputs subset: every object has
`additionalProperties: false`, every property is required, and optional values
are nullable.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from ..models import Antu
from ..ontology import Ontology

EXTRACTION_SCHEMA_VERSION = "kuyen-extraction-candidate-v1"
SUPPORTED_KEYWORDS = {
    "type", "properties", "required", "additionalProperties", "items", "enum",
    "description", "title",
}
UNSUPPORTED_KEYWORDS = {
    "oneOf", "allOf", "not", "if", "then", "else", "patternProperties",
    "minLength", "maxLength", "pattern", "format", "minimum", "maximum",
    "multipleOf", "minItems", "maxItems", "uniqueItems", "default", "$ref",
}


def _obj(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def _array(items: dict[str, Any]) -> dict[str, Any]:
    return {"type": "array", "items": items}


def _nullable(value_type: str) -> dict[str, Any]:
    return {"type": [value_type, "null"]}


def _enum(values: list[str]) -> dict[str, Any]:
    return {"type": "string", "enum": list(dict.fromkeys(values))}


def build_extraction_schema(
    *,
    antu: Antu,
    ontology: Ontology,
    mapu_ids: list[str],
    unit_ids: list[str],
    source_uris: list[str],
) -> dict[str, Any]:
    if not antu.entity_types:
        raise ValueError("Antü must declare entity_types")
    if not antu.relation_types:
        raise ValueError("Antü must declare relation_types")
    scalar_predicates = sorted(ontology.scalar_predicates)
    relation_labels = sorted({
        ontology.relation_types[predicate].label
        for predicate in antu.relation_types
        if predicate in ontology.relation_types
    })
    if not relation_labels:
        raise ValueError("no ontology labels for the Antü relation_types")

    evidence = _obj({
        "evidence_ref": {"type": "string"},
        "mapu_id": _enum(mapu_ids),
        "unit_id": _enum(unit_ids),
        "quote": {"type": "string"},
        "source_uri": _enum(source_uris),
        "context_ref": _nullable("string"),
    })
    entity = _obj({
        "source_ref": {"type": "string"},
        "source_entity_id": {"type": "string"},
        "entity_type": _enum(list(antu.entity_types)),
        "name": {"type": "string"},
        "description": {"type": "string"},
        "aliases": _array({"type": "string"}),
        "source_mapu_id": _enum(mapu_ids),
        "source_unit_id": _enum(unit_ids),
        "evidence_refs": _array({"type": "string"}),
    })
    relation = _obj({
        "source_relation_ref": {"type": "string"},
        "from_source_ref": {"type": "string"},
        "to_source_ref": {"type": "string"},
        "predicate": _enum(list(antu.relation_types)),
        "label": _enum(relation_labels),
        "polarity": _enum(["POSITIVE", "NEGATIVE"]),
        "temporal_scope": _nullable("string"),
        "epistemic_status": _enum(["UNRESOLVED", "NOT_EVALUATED"]),
        "evidence_refs": _array({"type": "string"}),
    })
    assertion_value = _obj({
        "value_type": _enum([
            "string", "integer", "number", "year", "date", "quantity",
            "percentage", "boolean",
        ]),
        "text_value": _nullable("string"),
        "number_value": _nullable("number"),
        "unit": _nullable("string"),
        "context": _nullable("string"),
    })
    assertion = _obj({
        "assertion_ref": {"type": "string"},
        "subject_ref": {"type": "string"},
        "predicate": _enum(scalar_predicates),
        "object_ref": _nullable("string"),
        "value": assertion_value,
        "polarity": _enum(["POSITIVE", "NEGATIVE"]),
        "temporal_scope": _nullable("string"),
        "epistemic_status": _enum(["UNRESOLVED", "NOT_EVALUATED"]),
        "evidence_refs": _array({"type": "string"}),
    })
    coverage = _obj({
        "units_used": _array(_enum(unit_ids)),
        "notes": _nullable("string"),
    })
    schema = _obj({
        "entities": _array(entity),
        "relations": _array(relation),
        "assertions": _array(assertion),
        "evidence": _array(evidence),
        "coverage": coverage,
    })
    return schema


def validate_strict_schema(schema: dict[str, Any]) -> list[str]:
    errors: list[str] = []

    def walk(node: Any, path: str = "$") -> None:
        if not isinstance(node, dict):
            return
        for keyword in UNSUPPORTED_KEYWORDS:
            if keyword in node:
                errors.append(f"{path}: unsupported keyword {keyword}")
        unknown = sorted(set(node) - SUPPORTED_KEYWORDS - {"$schema"})
        if unknown:
            errors.append(f"{path}: unknown keywords {unknown}")
        node_type = node.get("type")
        if node_type == "object" or (isinstance(node_type, list) and "object" in node_type):
            properties = node.get("properties")
            if not isinstance(properties, dict):
                errors.append(f"{path}: object without properties")
            else:
                if node.get("additionalProperties") is not False:
                    errors.append(f"{path}: additionalProperties must be false")
                required = node.get("required")
                if not isinstance(required, list) or sorted(required) != sorted(properties):
                    errors.append(f"{path}: required must list every property")
                for key, value in properties.items():
                    walk(value, f"{path}.{key}")
        if isinstance(node_type, list):
            if len(node_type) != 2 or "null" not in node_type:
                errors.append(f"{path}: nullable type must be [type, null]")
        if node_type == "array":
            items = node.get("items")
            if not isinstance(items, dict):
                errors.append(f"{path}: array without items")
            else:
                walk(items, f"{path}[]")
        if "enum" in node and not isinstance(node["enum"], list):
            errors.append(f"{path}: enum must be a list")

    walk(schema)
    return errors


def schema_hash(schema: dict[str, Any]) -> str:
    payload = json.dumps(schema, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()

EXTRACTION_SCHEMA_VERSION_V2 = "kuyen-extraction-candidate-v2"


def _temporal_schema() -> dict[str, Any]:
    return _obj({
        "kind": _enum(["POINT", "INTERVAL", "RECURRENCE", "SEASON", "APPROXIMATE", "UNKNOWN"]),
        "expression": _nullable("string"),
        "start": _nullable("string"),
        "end": _nullable("string"),
        "frequency": _nullable("string"),
        "month": _nullable("integer"),
        "day": _nullable("integer"),
        "timezone": _nullable("string"),
        "precision": _nullable("string"),
    })


def build_extraction_schema_v2(
    *,
    antu: Antu,
    ontology: Ontology,
    mapu_ids: list[str],
    unit_ids: list[str],
    source_uris: list[str],
    source_sha256: str,
    source_characters: int,
    sections: list[dict[str, Any]],
) -> dict[str, Any]:
    """Eight/multi-unit document contract with structured temporal scopes.

    v1 is preserved unchanged. v2 adds document/sections metadata and a temporal
    object; every object still follows the strict Structured Outputs subset.
    """
    schema = build_extraction_schema(
        antu=antu, ontology=ontology, mapu_ids=mapu_ids,
        unit_ids=unit_ids, source_uris=source_uris,
    )
    schema["properties"]["document"] = _obj({
        "mapu_id": _enum(mapu_ids),
        "source_uri": _enum(source_uris),
        "source_sha256": {"type": "string"},
        "characters": {"type": "integer"},
        "section_count": {"type": "integer"},
    })
    schema["properties"]["sections"] = _array(_obj({
        "unit_id": _enum(unit_ids),
        "section": {"type": "string"},
        "order": {"type": "integer"},
    }))
    schema["required"] = list(schema["properties"])
    for collection in ("relations", "assertions"):
        item = schema["properties"][collection]["items"]
        item["properties"]["temporal"] = _temporal_schema()
        item["required"] = list(item["properties"])
    # Make the exact source identity visible to the model via descriptions.
    schema["properties"]["document"]["properties"]["source_sha256"]["description"] = source_sha256
    schema["properties"]["document"]["properties"]["characters"]["description"] = str(source_characters)
    schema["properties"]["sections"]["items"]["properties"]["section"]["description"] = "; ".join(
        f"{item['unit_id']}={item['section']}" for item in sections
    )
    return schema
