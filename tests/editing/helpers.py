"""Deterministic helpers for the Antü graph-edit suite.

The initial graph is controlled and small, but it is a *real* canonical document: it is
committed through the public `import_canonical` boundary with verifiable evidence, so
every edit test starts from a version whose provenance and integrity can be checked.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from kuyen import KuyenMemory, build_document
from kuyen.canonical import sha256_text, stable_id
from kuyen.semantics.schema import GraphSchema

MAPU_ID = "MAPU-EDIT-01"
SOURCE_URI = "viking://resources/tests/MAPU-EDIT-01.md"
TEXT = (
    "## Acuerdo\n"
    "La Cooperativa Faro Sur instaló 12 luminarias en el pasaje Los Aromos.\n"
    "## Responsable\n"
    "Camila Soto supervisa la instalación de las luminarias.\n"
    "## Fecha\n"
    "La instalación comenzó en marzo de 2025.\n"
)
QUOTE_INSTALLED = "La Cooperativa Faro Sur instaló 12 luminarias en el pasaje Los Aromos."
QUOTE_SUPERVISES = "Camila Soto supervisa la instalación de las luminarias."
QUOTE_DATE = "La instalación comenzó en marzo de 2025."


def _id(prefix: str, label: str) -> str:
    return stable_id(prefix.rstrip("_"), {"fixture": label})


def _evidence(evidence_id: str, quote: str) -> dict[str, Any]:
    start = TEXT.index(quote)
    return {"evidence_id": evidence_id, "mapu_id": MAPU_ID, "source_uri": SOURCE_URI,
            "source_sha256": sha256_text(TEXT), "quote": quote,
            "char_start": start, "char_end": start + len(quote),
            "offset_unit": "unicode_codepoint", "extraction_method": "fixture",
            "validation_status": "SOURCE_VERIFIED"}


def _origin(evidence_id: str) -> dict[str, Any]:
    return {"kind": "DOCUMENT_EVIDENCE", "evidence_ids": [evidence_id], "mapu_ids": [MAPU_ID]}


def entity(entity_id: str, name: str, entity_type: str, description: str,
           evidence_id: str) -> dict[str, Any]:
    return {"entity_id": entity_id, "entity_type": entity_type, "name": name, "aliases": [],
            "description": description, "evidence_ids": [evidence_id], "sources": [SOURCE_URI],
            "source_entity_id": None, "source_namespace": "fixture", "identity_basis": "content",
            "normalization_status": "RESOLVED", "normalization_reason": None,
            "status": "SOURCE_VERIFIED", "metadata": {}, "origin_entity_id": None,
            "canonical_entity_id": entity_id, "identity_status": "NOT_ASSESSED",
            "identity_group_id": None, "origin": _origin(evidence_id)}



def graph() -> dict[str, Any]:
    """The controlled initial graph: two entities, one relation, two assertions."""
    ev_installed = _id("ev_", "installed-12")
    ev_supervises = _id("ev_", "camila-supervises")
    ev_date = _id("ev_", "started-march")
    cooperative = _id("ent_", "cooperativa")
    camila = _id("ent_", "camila")
    relation = _id("rel_", "supervises")
    assertion_lights = _id("asrt_", "lights")
    assertion_date = _id("asrt_", "date")
    return {
        "kuyen_id": "KUY-0123456789ab",
        "version": "1.0.0",
        "antu_id": "ANTU-FIXTURE-01",
        "mapu_ids": [MAPU_ID],
        "schema_version": "kuyen-native-v1",
        "status": "ACCEPTED",
        "entities": [entity(cooperative, "Cooperativa Faro Sur", "organization",
                            "Cooperativa que ejecuta la instalación", ev_installed),
                     entity(camila, "Camila Soto", "person",
                            "Inspectora municipal", ev_supervises)],
        "relations": [{
            "relation_id": relation, "from_entity": camila, "to_entity": cooperative,
            "predicate": "supervises", "source_predicate": "supervises",
            "canonical_predicate": "supervises", "provider_predicate": "supervises",
            "label": "supervisa", "display_label": "supervisa", "provider_label": "supervisa",
            "source_label": "supervisa", "polarity": "POSITIVE", "scope": "document",
            "temporal_scope": None, "temporal": None, "evidence_ids": [ev_supervises],
            "sources": [SOURCE_URI], "status": "UNRESOLVED", "semantic_status": "NOT_ASSESSED",
            "mapping_status": "EXACT", "mapping_rule_id": "fixture-v1",
            "mapping_version": "1.0.0", "provider_projection_status": "EXACT",
            "normalization_reason": None, "origin": _origin(ev_supervises)}],
        "assertions": [{
            "assertion_id": assertion_lights, "subject_entity": cooperative,
            "predicate": "installed_lights", "object_entity": None,
            "value": {"value_type": "integer", "value": 12, "unit": "luminarias",
                      "context": None},
            "polarity": "POSITIVE", "scope": "document", "temporal_scope": None,
            "temporal": None, "evidence_ids": [ev_installed], "sources": [SOURCE_URI],
            "status": "UNRESOLVED", "semantic_status": "NOT_ASSESSED", "modality": "FACT",
            "attribution": None, "origin": _origin(ev_installed)},
            {"assertion_id": assertion_date, "subject_entity": cooperative,
             "predicate": "started_at", "object_entity": None,
             "value": {"value_type": "string", "value": "2025-03", "unit": None,
                       "context": None},
             "polarity": "POSITIVE", "scope": "document", "temporal_scope": "2025-03",
             "temporal": None, "evidence_ids": [ev_date], "sources": [SOURCE_URI],
             "status": "UNRESOLVED", "semantic_status": "NOT_ASSESSED", "modality": "FACT",
             "attribution": None, "origin": _origin(ev_date)}],
        "evidence": [_evidence(ev_installed, QUOTE_INSTALLED),
                     _evidence(ev_supervises, QUOTE_SUPERVISES),
                     _evidence(ev_date, QUOTE_DATE)],
        "coverage": [{"source_uri": SOURCE_URI, "mapu_id": MAPU_ID, "unit_id": "u00",
                      "section": "document", "state": "PROCESSED_WITH_OUTPUT",
                      "content_sha256": None, "entity_ids": [], "relation_ids": [],
                      "reason": None}],
        "provenance": {"implementation": "fixture", "coverage_inventory": {}},
        "content_digest": sha256_text("fixture-content")[:20],
        "provenance_digest": sha256_text("fixture-provenance")[:20],
    }


def document() -> dict[str, Any]:
    return build_document(graph(), {MAPU_ID: TEXT}, mapu_versions={MAPU_ID: "1.0.0"},
                          source_uris={MAPU_ID: SOURCE_URI})


def memory_at(tmp_path: Path) -> KuyenMemory:
    """A memory with the controlled graph committed as version 1."""
    memory = KuyenMemory.create(tmp_path / "memory", leftraru_id="LR-EDIT")
    memory.import_canonical(document(), antu_id="ANTU-FIXTURE-01")
    return memory


SCHEMA_PROFILE = {
    "profile": "fixture-v1", "profile_version": "1.0.0",
    "entity_types": {
        "organization": {"description": "Cuerpo organizado", "attributes": {}},
        "person": {"description": "Persona nombrada", "attributes": {}},
        "place": {"description": "Lugar", "attributes": {}},
    },
    "scalar_predicates": {"installed_lights": {"value_type": "integer"}},
    "relation_types": {"supervises": {"label": "supervisa"}},
}


def schema_document(extra_fields: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """The controlled document with a declared schema (entity types and fields)."""
    profile = {**SCHEMA_PROFILE, "entity_types": {
        name: {**spec, "attributes": {
            "description": {"name": "description", "value_type": "text"},
            **(extra_fields or {}).get(name, {})}}
        for name, spec in SCHEMA_PROFILE["entity_types"].items()}}
    return build_document(graph(), {MAPU_ID: TEXT}, mapu_versions={MAPU_ID: "1.0.0"},
                          source_uris={MAPU_ID: SOURCE_URI},
                          schema=GraphSchema.from_dict(profile).to_dict())


def schema_memory_at(tmp_path: Path, *,
                     extra_fields: dict[str, dict[str, Any]] | None = None,
                     scope: Any = None) -> KuyenMemory:
    """A memory whose version declares its schema, for the schema Antü tests."""
    memory = KuyenMemory.create(tmp_path / "schema-memory", leftraru_id="LR-SCHEMA")
    memory.import_canonical(schema_document(extra_fields), antu_id="ANTU-FIXTURE-SCHEMA")
    return memory


def ids(memory: KuyenMemory, version_id: str | None = None) -> dict[str, Any]:
    value = memory.graph(version_id)
    return {"entities": {item["name"]: item["entity_id"] for item in value["entities"]},
            "assertions": {item["predicate"]: item["assertion_id"]
                           for item in value["assertions"]},
            "relations": {item["predicate"]: item["relation_id"]
                          for item in value["relations"]}}


def padded_document(count: int = 260) -> dict[str, Any]:
    """A version with many filler entities, used to force keyword context selection."""
    value = graph()
    for index in range(count):
        entity_id = _id("ent_", f"filler-{index}")
        value["entities"].append({
            "entity_id": entity_id, "entity_type": "concept",
            "name": f"Relleno {index}", "aliases": [], "description": "sin datos",
            "evidence_ids": [], "sources": [], "status": "UNRESOLVED",
            "metadata": {}, "origin": {"kind": "PRIOR_VERSION"}})
    return build_document(value, {MAPU_ID: TEXT}, mapu_versions={MAPU_ID: "1.0.0"},
                          source_uris={MAPU_ID: SOURCE_URI})


def big_memory_at(tmp_path: Path) -> KuyenMemory:
    memory = KuyenMemory.create(tmp_path / "big", leftraru_id="LR-BIG")
    memory.import_canonical(padded_document(), antu_id="ANTU-FIXTURE-PADDED")
    return memory


class ScriptedEditor:
    """A deterministic editor for unit tests: returns exactly the payload it was given."""

    name = "scripted"

    def __init__(self, payload: Any) -> None:
        self.payload = payload
        self.requests: list[Any] = []

    def metadata(self) -> dict[str, Any]:
        import hashlib
        import json

        digest = hashlib.sha256(json.dumps(self.payload, sort_keys=True,
                                           ensure_ascii=False).encode("utf-8")).hexdigest()
        return {"provider": "scripted", "model": "unit-test", "payload_sha256": digest}

    def interpret(self, request):
        import json

        self.requests.append(request)
        return self.payload if isinstance(self.payload, str) else json.dumps(self.payload)


def proposal(operations: list[dict[str, Any]], **overrides: Any) -> dict[str, Any]:
    value = {"schema_version": "kuyen-graph-edit-v2", "status": "PROPOSED",
             "interpretation": "instrucción interpretada por el editor determinista",
             "operations": operations}
    value.update(overrides)
    return value

