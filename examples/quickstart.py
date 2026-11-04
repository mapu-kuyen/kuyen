"""KÜYEN quickstart: governed memory with verifiable provenance.

Run it from any directory outside the source tree, with the package installed::

    python examples/quickstart.py /tmp/kuyen-demo

The walkthrough is linear and uses only the public API:

  1. create a canonical memory;
  2. ingest a MAPU (a source document) and declare its source URI;
  3. register structured knowledge (entities, a relation, an assertion);
  4. attach evidence that points at the exact characters of that document;
  5. validate an Antü that proposes a second document;
  6. commit it as a new, immutable version;
  7. read the current graph;
  8. locate a claim;
  9. recover its evidence and provenance down to the source text;
 10. verify the integrity of the memory, then back up and restore it.

No network, no model, no OpenViking: the core is self-contained.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from kuyen import KuyenMemory, build_document

# ---------------------------------------------------------------------------
# Two small source documents (MAPU).
#
# The URI is part of the provenance contract: it identifies the document, and
# every evidence record must cite exactly the URI its MAPU declares. It is
# therefore written once here and reused everywhere (`source_uris=` below).
# ---------------------------------------------------------------------------
MAPU_1 = "MAPU-DEMO-01"
URI_1 = "viking://resources/demo/MAPU-DEMO-01.txt"
TEXT_1 = ("La cooperativa del valle produce vino desde 1990. "
          "El valle de Colchagua es reconocido por su vino.")
QUOTE_1 = "El valle de Colchagua es reconocido por su vino"

MAPU_2 = "MAPU-DEMO-02"
URI_2 = "viking://resources/demo/MAPU-DEMO-02.txt"
TEXT_2 = "En 2024 la bodega del valle exporto 1.200 cajas a Brasil."
QUOTE_2 = "exporto 1.200 cajas a Brasil"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _id(prefix: str, label: str) -> str:
    """A deterministic identifier, derived the way a producer would derive it."""
    return prefix + hashlib.sha256(label.encode("utf-8")).hexdigest()[:20]


def _evidence(evidence_id: str, mapu_id: str, uri: str, text: str, quote: str) -> dict:
    """Evidence = a quote plus the offsets where it really appears in the source."""
    start = text.index(quote)
    return {"evidence_id": evidence_id, "mapu_id": mapu_id, "source_uri": uri,
            "quote": quote, "char_start": start, "char_end": start + len(quote),
            "offset_unit": "unicode_codepoint", "extraction_method": "manual",
            "validation_status": "SOURCE_VERIFIED", "source_sha256": _sha(text)}


def _entity(entity_id: str, name: str, entity_type: str, description: str,
            uri: str, evidence_id: str, source_ref: str) -> dict:
    return {"entity_id": entity_id, "entity_type": entity_type, "name": name,
            "aliases": [], "description": description, "evidence_ids": [evidence_id],
            "sources": [uri], "source_entity_id": source_ref, "source_namespace": "demo",
            "identity_basis": "source_id", "normalization_status": "RESOLVED",
            "normalization_reason": None, "status": "SOURCE_VERIFIED", "metadata": {},
            "origin_entity_id": source_ref, "canonical_entity_id": entity_id,
            "identity_status": "SAME_STABLE_ID", "identity_group_id": None}


def _relation(relation_id: str, from_entity: str, to_entity: str, predicate: str,
              temporal_scope: str, uri: str, evidence_id: str,
              from_ref: str, to_ref: str) -> dict:
    return {"relation_id": relation_id, "from_entity": from_entity, "to_entity": to_entity,
            "predicate": predicate, "source_predicate": predicate,
            "canonical_predicate": predicate, "provider_predicate": "related_to",
            "display_label": predicate, "provider_label": "se relaciona con",
            "label": predicate, "source_label": predicate, "polarity": "POSITIVE",
            "scope": "document", "temporal_scope": temporal_scope, "temporal": None,
            "evidence_ids": [evidence_id], "sources": [uri],
            "source_from_entity": from_ref, "source_to_entity": to_ref,
            "from_normalization_status": "RESOLVED", "to_normalization_status": "RESOLVED",
            "normalization_reason": None, "status": "SOURCE_VERIFIED",
            "semantic_status": "NOT_ASSESSED", "mapping_status": "UNMAPPED",
            "mapping_rule_id": "source-preserved-v1", "mapping_version": "1.0.0",
            "provider_projection_status": "LOSSY_PROJECTION", "source_relation_ref": None}


def _assertion(assertion_id: str, subject_entity: str, predicate: str, value: dict,
               temporal_scope: str, uri: str, evidence_id: str) -> dict:
    return {"assertion_id": assertion_id, "subject_entity": subject_entity,
            "predicate": predicate, "object_entity": None, "value": value,
            "polarity": "POSITIVE", "scope": "document", "temporal_scope": temporal_scope,
            "temporal": None, "evidence_ids": [evidence_id], "sources": [uri],
            "proposed_status": "SOURCE_VERIFIED", "proposed_status_raw": "SOURCE_VERIFIED",
            "evidence_status": "SOURCE_VERIFIED", "status": "SOURCE_VERIFIED",
            "semantic_status": "NOT_ASSESSED", "support_method": None,
            "support_rationale": None}


def first_document() -> dict:
    """The canonical document of MAPU-01: two entities, one relation, one evidence.

    `build_document` verifies every quote against its offsets and records the
    content hash of each MAPU. `source_uris` is what makes the evidence URI and
    the MAPU URI the same identity; without it the MAPU would get the default
    URI and the evidence would cite a document that the memory does not hold.
    """
    evidence = _evidence(_id("ev_", "demo:valley"), MAPU_1, URI_1, TEXT_1, QUOTE_1)
    cooperative = _id("ent_", "demo:cooperative")
    valley = _id("ent_", "demo:valley")
    relation = _id("rel_", "demo:produces-in")
    entities = [
        _entity(cooperative, "Cooperativa del valle", "organization",
                "Cooperativa vitivinicola del valle.", URI_1, evidence["evidence_id"], "e1"),
        _entity(valley, "Valle de Colchagua", "place", "Valle vitivinicola.", URI_1,
                evidence["evidence_id"], "e2"),
    ]
    relations = [_relation(relation, cooperative, valley, "produccion en el valle",
                           "desde 1990", URI_1, evidence["evidence_id"], "e1", "e2")]
    coverage = [{"source_uri": URI_1, "mapu_id": MAPU_1, "unit_id": "u00",
                 "state": "PROCESSED_WITH_OUTPUT", "section": "preamble",
                 "content_sha256": _sha(TEXT_1), "entity_ids": [cooperative, valley],
                 "relation_ids": [relation], "reason": None}]
    graph = {
        "kuyen_id": "KUY-a1b2c3d4e5f6", "version": "1.0.0", "antu_id": "ANTU-DEMO-0001",
        "mapu_ids": [MAPU_1], "schema_version": "kuyen-native-v1", "status": "ACCEPTED",
        "entities": entities, "relations": relations, "assertions": [],
        "evidence": [evidence], "coverage": coverage,
        "provenance": {
            "antu_id": "ANTU-DEMO-0001", "antu_version": "1.0.0",
            "actor": {"antu_author": "demo", "authenticated_account": "local",
                      "authenticated_user": "local", "candidate_producer": "demo",
                      "leftraru_id": "LR-DEMO", "request_id": None,
                      "service_identity": "local"},
            "candidate": {}, "candidate_uri": None,
            "coverage_inventory": {MAPU_1: [{"unit_id": "u00", "mapu_id": MAPU_1,
                                             "section": "preamble", "order": 0,
                                             "char_start": 0, "char_end": len(TEXT_1),
                                             "chars": len(TEXT_1),
                                             "content_sha256": _sha(TEXT_1),
                                             "source_uri": URI_1,
                                             "state": "PROCESSED_WITH_OUTPUT"}]}},
        "content_digest": None, "provenance_digest": None,
    }
    graph["content_digest"] = _digest({key: graph[key] for key in
                                       ("entities", "relations", "assertions", "evidence")})
    graph["provenance_digest"] = _digest(graph["provenance"])
    return build_document(graph, {MAPU_1: TEXT_1}, source_uris={MAPU_1: URI_1})


def _digest(value: dict) -> str:
    """Content digest of a graph fragment, over its canonical JSON form."""
    compact = json.dumps(value, sort_keys=True, ensure_ascii=False,
                         separators=(",", ":"))
    return hashlib.sha256(compact.encode("utf-8")).hexdigest()[:20]


def export_antu(base_version_id: str) -> dict:
    """An Antü: an instruction plus a proposal that adds MAPU-02 to the memory.

    The Antü declares the document it brings (`mapu`), the unit it covers
    (`unit`) and the objects it proposes (`proposal`). KÜYEN validates all of it
    before anything is written; `mapu_source` is the *path* to the bytes that
    the declared hash must match.
    """
    evidence = _evidence(_id("ev_", "demo:export"), MAPU_2, URI_2, TEXT_2, QUOTE_2)
    bodega = _id("ent_", "demo:bodega")
    assertion = _id("asrt_", "demo:export-volume")
    return {
        "antu_id": "ANTU-DEMO-0002", "idempotency_key": "ANTU-DEMO-0002",
        "leftraru_id": "LR-DEMO", "base_version_id": base_version_id,
        "purpose": "add the 2024 export volume", "kind": "INCORPORATE_MAPU",
        "description": "Adds the winery and the volume it exported in 2024.",
        "mapu": {"mapu_id": MAPU_2, "version": "1.0.0", "revision": "r1",
                 "source_uri": URI_2, "sha256": _sha(TEXT_2),
                 "source_file": f"{MAPU_2}.txt", "source_identity": "demo fixture"},
        # `unit_id` identifies a unit *inside the version* — MAPU-01 uses "u00", so this
        # document uses "u01". Keeping unit ids unique also keeps
        # `memory.source_unit(unit_id)` unambiguous when a version holds several MAPUs.
        "unit": {"unit_id": "u01", "mapu_id": MAPU_2, "section": "preamble", "order": 1,
                 "char_start": 0, "char_end": len(TEXT_2), "chars": len(TEXT_2),
                 "content_sha256": _sha(TEXT_2), "source_uri": URI_2,
                 "content": TEXT_2, "content_verified": True},
        "coverage": {"source_uri": URI_2, "mapu_id": MAPU_2, "unit_id": "u01",
                     "state": "PROCESSED_WITH_OUTPUT", "section": "preamble",
                     "content_sha256": _sha(TEXT_2), "entity_ids": [bodega],
                     "relation_ids": [], "reason": None},
        "proposal": {
            "entities": [_entity(bodega, "Bodega del valle", "organization",
                                 "Bodega exportadora del valle.", URI_2,
                                 evidence["evidence_id"], "e3")],
            "relations": [],
            "assertions": [_assertion(assertion, bodega, "has_quantity",
                                      {"value_type": "quantity", "value": 1200,
                                       "unit": "cajas", "context": "exportaciones 2024"},
                                      "2024", URI_2, evidence["evidence_id"])],
            "evidence": [evidence],
        },
    }



def main(argv: list[str]) -> int:
    root = Path(argv[1]) if len(argv) > 1 else Path("/tmp/kuyen-demo")

    # 1. create the memory (it is empty: current() is None)
    memory = KuyenMemory.create(root / "memory", leftraru_id="LR-DEMO",
                                purpose="quickstart")
    print(f"memory created at {memory.path}")

    # 2-4. ingest the first document, its URI and the evidence that cites it
    first = memory.import_canonical(first_document())
    print(f"committed {MAPU_1} as {first.version.version_id} "
          f"(kuyen {first.version.kuyen_version})")

    # 5. validate the Antü. `mapu_source` is a path: KÜYEN hashes the bytes it
    #    reads there and compares them with the hash the Antü declares.
    source = root / f"{MAPU_2}.txt"
    source.write_text(TEXT_2, encoding="utf-8")
    execution = memory.execute_antu(export_antu(first.version.version_id),
                                    mapu_source=source)
    print(f"Antü {execution.antu_id}: {execution.status} (nothing written yet)")
    if not execution.committable:
        print(f"rejected: {execution.detail}", file=sys.stderr)
        return 1

    # 6. confirm it as a new, immutable version
    second = memory.commit(execution)
    print(f"committed {second.version.version_id} "
          f"(kuyen {second.version.kuyen_version}), "
          f"parent {second.version.parent_version_id}")

    # 7. read the current graph
    graph = memory.graph()
    print(f"graph: {len(graph['entities'])} entities, {len(graph['relations'])} relations, "
          f"{len(graph['assertions'])} assertions, {len(graph['evidence'])} evidence records")

    # 8. locate the claim we care about
    claim = next(item for item in graph["assertions"]
                 if item["predicate"] == "has_quantity")
    print(f"claim {claim['assertion_id']}: {claim['value']['value']} "
          f"{claim['value']['unit']} ({claim['temporal_scope']})")

    # 9. claim -> evidence -> SOURCE_UNIT -> the exact characters of the document
    item = memory.trace(claim["assertion_id"])["evidence"][0]
    unit = memory.source_unit(item["source_unit_id"])
    quote_in_source = unit["content"][item["char_start"]:item["char_end"]]
    if quote_in_source != item["quote"]:
        print("the stored source does not contain the quote at its offsets",
              file=sys.stderr)
        return 1
    if item["mapu_content_sha256"] != _sha(TEXT_2):
        print("the MAPU hash does not match the source text", file=sys.stderr)
        return 1
    print(f"provenance: {item['quote']!r}")
    print(f"            at {item['char_start']}:{item['char_end']} of "
          f"{item['mapu_id']} <{unit['source_uri']}>")
    print(f"            sha256 {item['mapu_content_sha256']}")

    # 10. verify the integrity of the memory
    verify = memory.verify()
    print(f"verify: ok={verify['ok']} problems={verify['problems']}")

    # ...and prove it is recoverable: backup, restore, store-only reconstruction
    backup = memory.backup(root / "backup")
    print(f"backup {backup['backup_id']}: {backup['versions']} versions, "
          f"{backup['integrity_status']}")
    restored = KuyenMemory.restore(root / "backup", root / "restored")
    report = KuyenMemory.recover_from_store(root / "restored", workdir=root / "recovery")
    accepted = all(version["reconstruction"]["accepted"]
                   for version in report["versions"])
    print(f"restored: {len(restored.versions())} versions, "
          f"verify={restored.verify()['ok']}, "
          f"reconstructed={len(report['versions'])} accepted={accepted}")
    return 0 if verify["ok"] and accepted else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
