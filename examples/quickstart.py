"""Runnable quickstart: create a memory, commit an Antu, trace a claim, back up.

Run it from a directory outside the source tree, with the package installed::

    python examples/quickstart.py /tmp/kuyen-demo
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

from kuyen import KuyenMemory, build_document

SOURCE = "La cooperativa del valle produce vino desde 1990."
QUOTE = "La cooperativa del valle produce vino desde 1990"
MAPU_ID = "MAPU-DEMO-01"


def demo_graph() -> dict:
    source_sha = hashlib.sha256(SOURCE.encode("utf-8")).hexdigest()
    start = SOURCE.index(QUOTE)
    entity = "ent_" + hashlib.sha256(b"cooperativa").hexdigest()[:20]
    evidence = "ev_" + hashlib.sha256(b"evidence").hexdigest()[:20]
    relation = "rel_" + hashlib.sha256(b"relation").hexdigest()[:20]
    uri = f"viking://resources/demo/{MAPU_ID}.txt"
    return {
        "kuyen_id": "KUY-a1b2c3d4e5f6", "version": "1.0.0", "antu_id": "ANTU-DEMO",
        "mapu_ids": [MAPU_ID], "schema_version": "kuyen-native-v1", "status": "ACCEPTED",
        "entities": [{"entity_id": entity, "entity_type": "organization",
                      "name": "Cooperativa del valle", "aliases": [],
                      "description": "Cooperativa vitivinicola del valle.",
                      "evidence_ids": [evidence], "sources": [uri], "source_entity_id": "e1",
                      "source_namespace": "demo", "identity_basis": "source_id",
                      "normalization_status": "RESOLVED", "normalization_reason": None,
                      "status": "SOURCE_VERIFIED", "metadata": {}, "origin_entity_id": "e1",
                      "canonical_entity_id": entity, "identity_status": "SAME_STABLE_ID",
                      "identity_group_id": None}],
        "relations": [{"relation_id": relation, "from_entity": entity, "to_entity": entity,
                       "predicate": "produce vino", "source_predicate": "produce vino",
                       "canonical_predicate": "produce vino", "provider_predicate": "related_to",
                       "display_label": "produce vino", "provider_label": "se relaciona con",
                       "label": "produce vino", "source_label": "produce vino",
                       "polarity": "POSITIVE", "scope": "document", "temporal_scope": "desde 1990",
                       "temporal": None, "evidence_ids": [evidence], "sources": [uri],
                       "source_from_entity": "e1", "source_to_entity": "e1",
                       "from_normalization_status": "RESOLVED", "to_normalization_status": "RESOLVED",
                       "normalization_reason": None, "status": "SOURCE_VERIFIED",
                       "semantic_status": "NOT_ASSESSED", "mapping_status": "UNMAPPED",
                       "mapping_rule_id": "source-preserved-v1", "mapping_version": "1.0.0",
                       "provider_projection_status": "LOSSY_PROJECTION", "source_relation_ref": None}],
        "assertions": [],
        "evidence": [{"evidence_id": evidence, "mapu_id": MAPU_ID, "source_uri": uri,
                      "quote": QUOTE, "char_start": start, "char_end": start + len(QUOTE),
                      "offset_unit": "unicode_codepoint", "extraction_method": "manual",
                      "validation_status": "SOURCE_VERIFIED", "source_sha256": source_sha}],
        "coverage": [{"source_uri": uri, "mapu_id": MAPU_ID, "unit_id": "u00",
                      "state": "PROCESSED_WITH_OUTPUT", "section": "preamble",
                      "content_sha256": source_sha, "entity_ids": [entity],
                      "relation_ids": [relation], "reason": None}],
        "provenance": {"antu_id": "ANTU-DEMO", "antu_version": "1.0.0",
                       "actor": {"antu_author": "demo", "authenticated_account": "local",
                                 "authenticated_user": "local", "candidate_producer": "demo",
                                 "leftraru_id": "LR-DEMO", "request_id": None,
                                 "service_identity": "local"},
                       "candidate": {}, "candidate_uri": None,
                       "coverage_inventory": {MAPU_ID: [{"unit_id": "u00", "mapu_id": MAPU_ID,
                                                         "section": "preamble", "order": 0,
                                                         "char_start": 0, "char_end": len(SOURCE),
                                                         "chars": len(SOURCE),
                                                         "content_sha256": source_sha,
                                                         "source_uri": uri,
                                                         "state": "PROCESSED_WITH_OUTPUT"}]}},
        "content_digest": hashlib.sha256(b"demo-content").hexdigest()[:20],
        "provenance_digest": hashlib.sha256(b"demo-provenance").hexdigest()[:20],
    }


def main(argv: list[str]) -> int:
    root = Path(argv[1]) if len(argv) > 1 else Path("/tmp/kuyen-demo")
    memory = KuyenMemory.create(root / "memory", leftraru_id="LR-DEMO", purpose="quickstart")
    result = memory.import_canonical(build_document(demo_graph(), {MAPU_ID: SOURCE}))
    print(f"committed {result.version.version_id} (kuyen {result.version.kuyen_version})")
    graph = memory.graph()
    print(f"entities={len(graph['entities'])} relations={len(graph['relations'])}")
    trace = memory.trace(graph["relations"][0]["relation_id"])
    print(f"trace: {trace['evidence'][0]['quote']!r} in {trace['evidence'][0]['source_unit_id']}")
    print(f"verify: {memory.verify()['ok']}")
    backup = memory.backup(root / "backup")
    print(f"backup {backup['backup_id']} ({backup['versions']} versions, {backup['integrity_status']})")
    restored = KuyenMemory.restore(root / "backup", root / "restored")
    print(f"restored: {len(restored.versions())} versions, verify={restored.verify()['ok']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
