"""Deterministic product fixture: a small, schema-conformant KUYEN graph + MAPU."""
from __future__ import annotations

import hashlib
import json
from typing import Any

ENTITY_TEXT = "La cooperativa del valle produce vino desde 1990. El valle de Colchagua es reconocido por su vino."
MAPU_ID = "MAPU-TEST-01"
SOURCE_URI = "viking://resources/tests/MAPU-TEST-01.txt"


def _hex(prefix: str, label: str) -> str:
    return prefix + hashlib.sha256(label.encode("utf-8")).hexdigest()[:20]


def make_graph(*, version: str = "1.0.0", kuyen_id: str = "KUY-a1b2c3d4e5f6") -> dict[str, Any]:
    text = ENTITY_TEXT
    source_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    quote = "El valle de Colchagua es reconocido por su vino"
    start = text.index(quote)
    evidence_id = _hex("ev_", "test:evidence:1")
    cooperative = _hex("ent_", "test:cooperative")
    valley = _hex("ent_", "test:valley")
    relation_id = _hex("rel_", "test:located-in")
    assertion_id = _hex("asrt_", "test:production")
    unit_id = "u00"
    evidence = [{"evidence_id": evidence_id, "mapu_id": MAPU_ID, "source_uri": SOURCE_URI,
                 "quote": quote, "char_start": start, "char_end": start + len(quote),
                 "offset_unit": "unicode_codepoint", "extraction_method": "manual_fixture",
                 "validation_status": "SOURCE_VERIFIED", "source_sha256": source_sha}]
    entities = [
        {"entity_id": cooperative, "entity_type": "organization", "name": "Cooperativa del valle",
         "aliases": ["La cooperativa"], "description": "Cooperativa vitivinicola del valle.",
         "evidence_ids": [evidence_id], "sources": [SOURCE_URI], "source_entity_id": "e1",
         "source_namespace": "test", "identity_basis": "source_id", "normalization_status": "RESOLVED",
         "normalization_reason": None, "status": "SOURCE_VERIFIED", "metadata": {},
         "origin_entity_id": "e1", "canonical_entity_id": cooperative,
         "identity_status": "SAME_STABLE_ID", "identity_group_id": None},
        {"entity_id": valley, "entity_type": "place", "name": "Valle de Colchagua",
         "aliases": [], "description": "Valle vitivinicola.", "evidence_ids": [evidence_id],
         "sources": [SOURCE_URI], "source_entity_id": "e2", "source_namespace": "test",
         "identity_basis": "source_id", "normalization_status": "RESOLVED",
         "normalization_reason": None, "status": "SOURCE_VERIFIED", "metadata": {},
         "origin_entity_id": "e2", "canonical_entity_id": valley,
         "identity_status": "SAME_STABLE_ID", "identity_group_id": None},
    ]
    relations = [{"relation_id": relation_id, "from_entity": cooperative, "to_entity": valley,
                  "predicate": "produccion en el valle", "source_predicate": "produccion en el valle",
                  "canonical_predicate": "produccion en el valle", "provider_predicate": "related_to",
                  "display_label": "produce en el valle", "provider_label": "se relaciona con",
                  "label": "produce en el valle", "source_label": "produce en el valle",
                  "polarity": "POSITIVE", "scope": "document", "temporal_scope": "desde 1990",
                  "temporal": {"kind": "INTERVAL", "expression": "desde 1990", "start": "1990",
                               "end": None, "frequency": None, "month": None, "day": None,
                               "timezone": None, "precision": "year"},
                  "evidence_ids": [evidence_id], "sources": [SOURCE_URI],
                  "source_from_entity": "e1", "source_to_entity": "e2",
                  "from_normalization_status": "RESOLVED", "to_normalization_status": "RESOLVED",
                  "normalization_reason": None, "status": "SOURCE_VERIFIED",
                  "semantic_status": "NOT_ASSESSED", "mapping_status": "UNMAPPED",
                  "mapping_rule_id": "source-preserved-v1", "mapping_version": "1.0.0",
                  "provider_projection_status": "LOSSY_PROJECTION", "source_relation_ref": None}]
    assertions = [{"assertion_id": assertion_id, "subject_entity": cooperative, "predicate": "has_named_value",
                   "object_entity": None,
                   "value": {"value_type": "string", "value": "vino", "unit": None, "context": "produccion"},
                   "polarity": "POSITIVE", "scope": "document", "temporal_scope": "desde 1990",
                   "temporal": None, "evidence_ids": [evidence_id], "sources": [SOURCE_URI],
                   "proposed_status": "SOURCE_VERIFIED", "proposed_status_raw": "SOURCE_VERIFIED",
                   "evidence_status": "SOURCE_VERIFIED", "status": "SOURCE_VERIFIED",
                   "semantic_status": "NOT_ASSESSED", "support_method": None, "support_rationale": None}]
    units = [{"unit_id": unit_id, "mapu_id": MAPU_ID, "section": "preamble", "order": 0,
              "char_start": 0, "char_end": len(text), "chars": len(text),
              "content_sha256": source_sha, "source_uri": SOURCE_URI}]
    graph = {"kuyen_id": kuyen_id, "version": version, "antu_id": "ANTU-FIXTURE-0001",
             "mapu_ids": [MAPU_ID], "schema_version": "kuyen-native-v1", "status": "ACCEPTED",
             "entities": entities, "relations": relations, "assertions": assertions,
             "evidence": evidence,
             "coverage": [{"source_uri": SOURCE_URI, "mapu_id": MAPU_ID, "unit_id": unit_id,
                           "state": "PROCESSED_WITH_OUTPUT", "section": "preamble",
                           "content_sha256": source_sha, "entity_ids": [cooperative, valley],
                           "relation_ids": [relation_id], "reason": None}],
             "provenance": {"antu_id": "ANTU-FIXTURE-0001", "antu_version": "1.0.0",
                            "actor": {"antu_author": "tests", "authenticated_account": "local",
                                      "authenticated_user": "local", "candidate_producer": "fixture",
                                      "leftraru_id": "LR-TEST", "request_id": None,
                                      "service_identity": "local"},
                            "candidate": {}, "candidate_uri": None,
                            "coverage_inventory": {MAPU_ID: units}},
             "content_digest": None, "provenance_digest": None}
    compact = json.dumps({"entities": entities, "relations": relations, "assertions": assertions,
                          "evidence": evidence}, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    graph["content_digest"] = hashlib.sha256(compact.encode()).hexdigest()[:20]
    provenance_compact = json.dumps(graph["provenance"], sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    graph["provenance_digest"] = hashlib.sha256(provenance_compact.encode()).hexdigest()[:20]
    return graph


def make_mapu_text() -> str:
    return ENTITY_TEXT


def make_antu(*, antu_id: str = "ANTU-TEST-0002", base_version_id: str) -> dict[str, Any]:
    """A deterministic Antu proposal: one new entity, one relation, one assertion, one evidence."""
    text = "La bodega del valle exporto 1.200 cajas en 2024."
    source_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    quote = "exporto 1.200 cajas en 2024"
    start = text.index(quote)
    evidence_id = _hex("ev_", "test:evidence:2")
    entity_id = _hex("ent_", "test:bodega")
    relation_id = _hex("rel_", "test:exporta")
    assertion_id = _hex("asrt_", "test:cajas")
    return {
        "antu_id": antu_id, "idempotency_key": antu_id, "leftraru_id": "LR-TEST",
        "base_version_id": base_version_id, "purpose": "incorporate a second MAPU",
        "kind": "INCORPORATE_MAPU", "description": "Adds the winery and its export volume.",
        "mapu": {"mapu_id": "MAPU-TEST-02", "version": "1.0.0", "revision": "r1",
                 "source_uri": "viking://resources/tests/MAPU-TEST-02.txt", "sha256": source_sha,
                 "source_file": "MAPU-TEST-02.txt", "source_identity": "test fixture"},
        "unit": {"unit_id": "u00", "mapu_id": "MAPU-TEST-02", "section": "preamble", "order": 0,
                 "char_start": 0, "char_end": len(text), "chars": len(text),
                 "content_sha256": source_sha, "source_uri": "viking://resources/tests/MAPU-TEST-02.txt",
                 "content": text, "content_verified": True},
        "coverage": {"source_uri": "viking://resources/tests/MAPU-TEST-02.txt", "mapu_id": "MAPU-TEST-02",
                     "unit_id": "u00", "state": "PROCESSED_WITH_OUTPUT", "section": "preamble",
                     "content_sha256": source_sha, "entity_ids": [entity_id],
                     "relation_ids": [relation_id], "reason": None},
        "proposal": {
            "entities": [{"entity_id": entity_id, "entity_type": "organization", "name": "Bodega del valle",
                          "aliases": [], "description": "Bodega exportadora.", "evidence_ids": [evidence_id],
                          "sources": ["viking://resources/tests/MAPU-TEST-02.txt"], "source_entity_id": "e3",
                          "source_namespace": "test", "identity_basis": "source_id",
                          "normalization_status": "RESOLVED", "normalization_reason": None,
                          "status": "SOURCE_VERIFIED", "metadata": {}, "origin_entity_id": "e3",
                          "canonical_entity_id": entity_id, "identity_status": "SAME_STABLE_ID",
                          "identity_group_id": None}],
            "relations": [{"relation_id": relation_id, "from_entity": entity_id,
                           "to_entity": _hex("ent_", "test:valley"), "predicate": "exporta desde",
                           "source_predicate": "exporta desde", "canonical_predicate": "exporta desde",
                           "provider_predicate": "related_to", "display_label": "exporta desde",
                           "provider_label": "se relaciona con", "label": "exporta desde",
                           "source_label": "exporta desde", "polarity": "POSITIVE", "scope": "document",
                           "temporal_scope": "2024", "temporal": None, "evidence_ids": [evidence_id],
                           "sources": ["viking://resources/tests/MAPU-TEST-02.txt"],
                           "source_from_entity": "e3", "source_to_entity": "e2",
                           "from_normalization_status": "RESOLVED", "to_normalization_status": "RESOLVED",
                           "normalization_reason": None, "status": "SOURCE_VERIFIED",
                           "semantic_status": "NOT_ASSESSED", "mapping_status": "UNMAPPED",
                           "mapping_rule_id": "source-preserved-v1", "mapping_version": "1.0.0",
                           "provider_projection_status": "LOSSY_PROJECTION", "source_relation_ref": None}],
            "assertions": [{"assertion_id": assertion_id, "subject_entity": entity_id,
                            "predicate": "has_quantity", "object_entity": None,
                            "value": {"value_type": "quantity", "value": 1200, "unit": "cajas",
                                      "context": "exportaciones 2024"},
                            "polarity": "POSITIVE", "scope": "document", "temporal_scope": "2024",
                            "temporal": None, "evidence_ids": [evidence_id],
                            "sources": ["viking://resources/tests/MAPU-TEST-02.txt"],
                            "proposed_status": "SOURCE_VERIFIED", "proposed_status_raw": "SOURCE_VERIFIED",
                            "evidence_status": "SOURCE_VERIFIED", "status": "SOURCE_VERIFIED",
                            "semantic_status": "NOT_ASSESSED", "support_method": None,
                            "support_rationale": None}],
            "evidence": [{"evidence_id": evidence_id, "mapu_id": "MAPU-TEST-02",
                          "source_uri": "viking://resources/tests/MAPU-TEST-02.txt", "quote": quote,
                          "char_start": start, "char_end": start + len(quote),
                          "offset_unit": "unicode_codepoint", "extraction_method": "manual_fixture",
                          "validation_status": "SOURCE_VERIFIED", "source_sha256": source_sha}],
        },
        "mapu_text": text,
    }
