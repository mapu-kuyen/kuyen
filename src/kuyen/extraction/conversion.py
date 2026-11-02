"""Deterministic conversion from the OpenAI extraction contract to the provider
result consumed by CandidateMaterializer.

The conversion preserves source references, evidence references and scalar
values. It never invents an entity, endpoint or quote; unknown references are a
hard contract error.
"""
from __future__ import annotations

from typing import Any

from ..errors import OpenAIExtractionError
from ..models import Value


def _evidence_index(candidate: dict[str, Any]) -> dict[str, dict[str, Any]]:
    evidence: dict[str, dict[str, Any]] = {}
    for item in candidate.get("evidence") or []:
        ref = str(item.get("evidence_ref") or "").strip()
        if not ref:
            raise OpenAIExtractionError("evidence entry without evidence_ref")
        if ref in evidence:
            raise OpenAIExtractionError(f"duplicate evidence_ref: {ref}")
        if not str(item.get("quote") or "").strip():
            raise OpenAIExtractionError(f"evidence {ref} has an empty quote")
        evidence[ref] = item
    return evidence


def _refs(value: Any, *, label: str) -> list[str]:
    refs = [str(item) for item in (value or [])]
    if not refs:
        raise OpenAIExtractionError(f"{label} has no evidence_refs")
    return list(dict.fromkeys(refs))


def _inline_evidence(refs: list[str], evidence: dict[str, dict[str, Any]], *, source_uri: str, mapu_id: str) -> list[dict[str, Any]]:
    inline = []
    for ref in refs:
        item = evidence.get(ref)
        if item is None:
            raise OpenAIExtractionError(f"unknown evidence_ref: {ref}")
        inline.append({
            "quote": item["quote"],
            "source_uri": item.get("source_uri") or source_uri,
            "mapu_id": item.get("mapu_id") or mapu_id,
        })
    return inline


def _scalar_value(raw: dict[str, Any]) -> Value | None:
    value_type = str(raw.get("value_type") or "string")
    number = raw.get("number_value")
    text = raw.get("text_value")
    if value_type in {"integer", "year"}:
        if number is None and text is None:
            return None
        try:
            return Value(value_type=value_type, value=int(number if number is not None else text))
        except (TypeError, ValueError):
            # The model may attach several literals to one field. Preserve the
            # original text rather than inventing a numeric value.
            return Value(value_type="string", value=str(text), unit=raw.get("unit"), context=raw.get("context"))
    if value_type in {"number", "percentage", "quantity"}:
        if number is None and text is None:
            return None
        try:
            return Value(value_type=value_type, value=float(number if number is not None else text),
                         unit=raw.get("unit"), context=raw.get("context"))
        except (TypeError, ValueError):
            return Value(value_type="string", value=str(text), unit=raw.get("unit"), context=raw.get("context"))
    if value_type == "boolean":
        if isinstance(text, str):
            return Value(value_type="boolean", value=text.strip().lower() in {"true", "1", "si", "sí"})
        return Value(value_type="boolean", value=bool(number))
    if text is None and number is None:
        return None
    return Value(value_type=value_type, value=text if text is not None else number,
                 unit=raw.get("unit"), context=raw.get("context"))


def _coverage(raw: Any, candidate: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    if not isinstance(raw, dict):
        return []
    units = [str(x) for x in (raw.get("units_used") or []) if str(x).strip()]
    notes = raw.get("notes")
    return [{"unit_id": unit_id, "state": "PROCESSED_WITH_OUTPUT", "reason": notes} for unit_id in units]


def extraction_to_provider_result(
    candidate: dict[str, Any],
    *,
    source_uri: str,
    mapu_id: str,
    model: str | None = None,
    response_id: str | None = None,
) -> dict[str, Any]:
    evidence = _evidence_index(candidate)
    entities: list[dict[str, Any]] = []
    entity_refs: set[str] = set()
    for item in candidate.get("entities") or []:
        ref = str(item.get("source_ref") or "").strip()
        if not ref:
            raise OpenAIExtractionError("entity without source_ref")
        if ref in entity_refs:
            raise OpenAIExtractionError(f"duplicate source_ref: {ref}")
        entity_refs.add(ref)
        refs = _refs(item.get("evidence_refs"), label=f"entity {ref}")
        entities.append({
            "provider_id": ref,
            "source_entity_id": item.get("source_entity_id"),
            "name": item.get("name") or ref,
            "entity_type": item.get("entity_type"),
            "aliases": [str(x) for x in (item.get("aliases") or [])],
            "description": item.get("description") or "",
            "sources": [source_uri],
            "evidence": _inline_evidence(refs, evidence, source_uri=source_uri, mapu_id=mapu_id),
        })
    relations: list[dict[str, Any]] = []
    relation_refs: set[str] = set()
    for item in candidate.get("relations") or []:
        ref = str(item.get("source_relation_ref") or "").strip()
        source = str(item.get("from_source_ref") or "").strip()
        target = str(item.get("to_source_ref") or "").strip()
        predicate = str(item.get("predicate") or "").strip()
        if not ref or not source or not target or not predicate:
            raise OpenAIExtractionError("relation requires source_relation_ref, endpoints and predicate")
        if ref in relation_refs:
            raise OpenAIExtractionError(f"duplicate source_relation_ref: {ref}")
        relation_refs.add(ref)
        if source not in entity_refs or target not in entity_refs:
            raise OpenAIExtractionError(
                f"relation {ref} references undeclared entity: {source if source not in entity_refs else target}"
            )
        refs = _refs(item.get("evidence_refs"), label=f"relation {ref}")
        relations.append({
            "from": source, "to": target, "predicate": predicate,
            "label": item.get("label") or predicate,
            "polarity": item.get("polarity") or "POSITIVE",
            "scope": "document",
            "temporal_scope": item.get("temporal_scope") or (item.get("temporal") or {}).get("expression"),
            "temporal": item.get("temporal"),
            "sources": [source_uri],
            "evidence": _inline_evidence(refs, evidence, source_uri=source_uri, mapu_id=mapu_id),
        })
    assertions: list[dict[str, Any]] = []
    assertion_refs: set[str] = set()
    for item in candidate.get("assertions") or []:
        ref = str(item.get("assertion_ref") or "").strip()
        subject = str(item.get("subject_ref") or "").strip()
        predicate = str(item.get("predicate") or "").strip()
        if not ref or not subject or not predicate:
            raise OpenAIExtractionError("assertion requires assertion_ref, subject_ref and predicate")
        if ref in assertion_refs:
            raise OpenAIExtractionError(f"duplicate assertion_ref: {ref}")
        assertion_refs.add(ref)
        if subject not in entity_refs:
            raise OpenAIExtractionError(f"assertion {ref} references undeclared subject: {subject}")
        object_ref = str(item.get("object_ref") or "").strip() or None
        if object_ref is not None and object_ref not in entity_refs:
            raise OpenAIExtractionError(f"assertion {ref} references undeclared object: {object_ref}")
        value = _scalar_value(item.get("value") or {})
        if value is None and object_ref is None:
            raise OpenAIExtractionError(f"assertion {ref} has neither value nor object_ref")
        refs = _refs(item.get("evidence_refs"), label=f"assertion {ref}")
        payload: dict[str, Any] = {
            "subject": subject, "predicate": predicate, "polarity": item.get("polarity") or "POSITIVE",
            "scope": "document",
            "temporal_scope": item.get("temporal_scope") or (item.get("temporal") or {}).get("expression"),
            "temporal": item.get("temporal"),
            "sources": [source_uri],
            "evidence": _inline_evidence(refs, evidence, source_uri=source_uri, mapu_id=mapu_id),
            "proposed_status": item.get("epistemic_status") or "UNRESOLVED",
        }
        if object_ref is not None:
            payload["object_entity"] = object_ref
        if value is not None:
            payload["value"] = value.to_dict()
        assertions.append(payload)
    return {
        "schema_version": "kuyen-provider-result-v1",
        "provider": {"name": "openai", "model": model, "response_id": response_id},
        "entities": entities,
        "relations": relations,
        "assertions": assertions,
        "coverage": _coverage(candidate.get("coverage"), candidate),
    }
