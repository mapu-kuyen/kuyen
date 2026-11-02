"""Correspondence manifest between canonical objects and native objects.

Supports one-to-one, one-to-many, many-to-one (lossy), zero-to-one
(unprojectable) and explicitly unresolved correspondences, in both directions.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..canonical import digest, read_json, sha256_text
from ..errors import MappingError
from ..contracts import MAPPING_SCHEMA_NAME, MAPPING_SCHEMA_VERSION, PROJECTOR_VERSION

ONE_TO_ONE = "ONE_TO_ONE"
MANY_TO_ONE_LOSSY = "MANY_TO_ONE_LOSSY"
ZERO_TO_ONE_UNPROJECTABLE = "ZERO_TO_ONE_UNPROJECTABLE"
UNRESOLVED = "UNRESOLVED"

NATIVE_ENTITY_FIELDS = {"entity_id", "name", "entity_type", "description", "aliases", "sources"}
NATIVE_RELATION_FIELDS = {"from_entity", "to_entity", "predicate", "label", "display_label", "sources"}


def _losses(item: dict[str, Any], carried: set[str], *, aliases: dict[str, str] | None = None) -> list[str]:
    aliases = aliases or {}
    losses = []
    for key, value in item.items():
        canonical_key = aliases.get(key, key)
        if canonical_key in carried:
            continue
        if value in (None, "", [], {}):
            continue
        losses.append(key)
    return sorted(losses)


def build_mapping(document: dict[str, Any], projection_manifest: dict[str, Any]) -> dict[str, Any]:
    kuyen = document["kuyen"]
    canonical = document["canonical"]
    artifacts = projection_manifest.get("artifacts") or {}
    grouped: dict[str, list[str]] = {}
    for group in projection_manifest.get("collision_groups") or []:
        grouped[group["native_key"]] = list(group["canonical_ids"])
    unprojectable = {(item["object_type"], item["canonical_id"]): item
                     for item in projection_manifest.get("unprojectable") or []}

    entries: list[dict[str, Any]] = []

    for entity in sorted(canonical["entities"], key=lambda item: item["entity_id"]):
        entity_id = entity["entity_id"]
        artifact = f"native/entities/{entity_id}.md"
        key = ("entity", entity_id)
        if artifact in artifacts:
            entries.append({
                "object_type": "entity", "canonical_id": entity_id,
                "native_object_id": entity_id,
                "native_locator": {"artifact": artifact, "format": "markdown_frontmatter"},
                "native_key": entity_id,
                "correspondence_type": ONE_TO_ONE, "cardinality": "1:1",
                "losses": _losses(entity, NATIVE_ENTITY_FIELDS),
                "canonical_object_sha256": digest(entity),
                "native_object_sha256": artifacts.get(artifact),
            })
        else:
            entries.append(_unprojectable_entry("entity", entity_id, entity, key, unprojectable))

    for relation in sorted(canonical["relations"], key=lambda item: item["relation_id"]):
        relation_id = relation["relation_id"]
        key = ("relation", relation_id)
        native_key = f"{relation['from_entity']}|{relation.get('predicate')}|{relation['to_entity']}"
        if ("relation", relation_id) in unprojectable:
            entries.append(_unprojectable_entry("relation", relation_id, relation, key, unprojectable))
            continue
        members = grouped.get(native_key) or []
        lossy = len(members) > 1
        entries.append({
            "object_type": "relation", "canonical_id": relation_id,
            "native_object_id": f"edge:{native_key}",
            "native_locator": {"artifact": "native/relations.jsonl", "key": native_key,
                               "format": "jsonl", "keys": ["from", "relation", "label", "to", "evidence"]},
            "native_key": native_key,
            "correspondence_type": MANY_TO_ONE_LOSSY if lossy else ONE_TO_ONE,
            "cardinality": f"{len(members)}:1" if lossy else "1:1",
            "losses": _losses(relation, NATIVE_RELATION_FIELDS),
            "canonical_object_sha256": digest(relation),
            "native_object_sha256": artifacts.get("native/relations.jsonl"),
            "collision_partners": [item for item in members if item != relation_id],
        })

    for kind, collection, id_field in (("assertion", canonical["assertions"], "assertion_id"),
                                       ("evidence", canonical["evidence"], "evidence_id"),
                                       ("source_unit", canonical["source_units"], "unit_id"),
                                       ("coverage", canonical["coverage"], "unit_id")):
        for item in collection:
            canonical_id = item.get(id_field)
            if kind == "evidence":
                canonical_id = item.get("evidence_id", canonical_id)
            entries.append({
                "object_type": kind, "canonical_id": canonical_id,
                "native_object_id": None, "native_locator": None, "native_key": None,
                "correspondence_type": ZERO_TO_ONE_UNPROJECTABLE, "cardinality": "0:1",
                "losses": sorted(key for key, value in item.items() if value not in (None, "", [], {})),
                "canonical_object_sha256": digest(item), "native_object_sha256": None,
            })

    canonical_to_native: dict[str, list[dict[str, Any]]] = {}
    native_to_canonical: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        source_key = f"{entry['object_type']}:{entry['canonical_id']}"
        canonical_to_native.setdefault(source_key, []).append({
            "native_object_id": entry["native_object_id"],
            "correspondence_type": entry["correspondence_type"],
            "cardinality": entry["cardinality"],
        })
        if entry["native_object_id"]:
            native_to_canonical.setdefault(entry["native_object_id"], []).append({
                "object_type": entry["object_type"],
                "canonical_id": entry["canonical_id"],
                "correspondence_type": entry["correspondence_type"],
                "cardinality": entry["cardinality"],
            })

    counts = {
        "entries": len(entries),
        "one_to_one": sum(1 for item in entries if item["correspondence_type"] == ONE_TO_ONE),
        "many_to_one_lossy": sum(1 for item in entries if item["correspondence_type"] == MANY_TO_ONE_LOSSY),
        "zero_to_one_unprojectable": sum(1 for item in entries if item["correspondence_type"] == ZERO_TO_ONE_UNPROJECTABLE),
        "unresolved": sum(1 for item in entries if item["correspondence_type"] == UNRESOLVED),
    }
    manifest = {
        "schema_name": MAPPING_SCHEMA_NAME,
        "schema_version": MAPPING_SCHEMA_VERSION,
        "adapter_version": PROJECTOR_VERSION,
        "kuyen": {"kuyen_id": kuyen["kuyen_id"], "version": kuyen["version"],
                  "canonical_graph_hash": kuyen["canonical_graph_hash"]},
        "projection_id": projection_manifest.get("projection_id"),
        "entries": entries,
        "index": {"canonical_to_native": canonical_to_native, "native_to_canonical": native_to_canonical},
        "counts": counts,
    }
    manifest["mapping_id"] = digest({key: value for key, value in manifest.items() if key != "mapping_id"})
    return manifest


def _unprojectable_entry(kind: str, canonical_id: str, item: dict[str, Any], key: tuple[str, str],
                         unprojectable: dict[tuple[str, str], dict[str, Any]]) -> dict[str, Any]:
    return {
        "object_type": kind, "canonical_id": canonical_id,
        "native_object_id": None, "native_locator": None, "native_key": None,
        "correspondence_type": ZERO_TO_ONE_UNPROJECTABLE, "cardinality": "0:1",
        "losses": sorted(name for name, value in item.items() if value not in (None, "", [], {})),
        "canonical_object_sha256": digest(item),
        "native_object_sha256": None,
        "reason": (unprojectable.get(key) or {}).get("reason", "UNPROJECTABLE"),
    }


def verify_mapping(mapping: dict[str, Any], document: dict[str, Any],
                   projection_manifest: dict[str, Any],
                   artifacts: dict[str, str] | None = None) -> dict[str, Any]:
    problems: list[str] = []
    if mapping.get("schema_name") != MAPPING_SCHEMA_NAME:
        problems.append(f"unexpected mapping schema_name: {mapping.get('schema_name')}")
    recomputed = digest({key: value for key, value in mapping.items() if key != "mapping_id"})
    if mapping.get("mapping_id") != recomputed:
        problems.append("mapping_id does not match the recomputed digest")
    if mapping.get("projection_id") != projection_manifest.get("projection_id"):
        problems.append("mapping references a different projection_id")
    kuyen = mapping.get("kuyen") or {}
    if kuyen.get("kuyen_id") != document["kuyen"]["kuyen_id"]:
        problems.append("mapping kuyen_id mismatch")
    if kuyen.get("canonical_graph_hash") != document["kuyen"]["canonical_graph_hash"]:
        problems.append("mapping canonical_graph_hash mismatch")

    expected = {
        "entity": {item["entity_id"] for item in document["canonical"]["entities"]},
        "relation": {item["relation_id"] for item in document["canonical"]["relations"]},
        "assertion": {item["assertion_id"] for item in document["canonical"]["assertions"]},
        "evidence": {item["evidence_id"] for item in document["canonical"]["evidence"]},
        "source_unit": {item["unit_id"] for item in document["canonical"]["source_units"]},
    }
    covered = {kind: set() for kind in expected}
    for entry in mapping.get("entries") or []:
        kind = entry.get("object_type")
        if kind in covered:
            covered[kind].add(entry["canonical_id"])
    for kind, ids in expected.items():
        missing = sorted(ids - covered[kind])
        extra = sorted(covered[kind] - ids)
        if missing:
            problems.append(f"{kind}: {len(missing)} canonical object(s) without correspondence")
        if extra:
            problems.append(f"{kind}: {len(extra)} correspondence(es) for unknown object(s)")

    native_entities = set()
    if artifacts is not None:
        native_entities = {name.split("/")[-1][:-3] for name in artifacts if name.startswith("native/entities/")}
        for entry in mapping.get("entries") or []:
            if entry["object_type"] == "entity" and entry["native_object_id"]:
                if entry["native_object_id"] not in native_entities:
                    problems.append(f"entity correspondence points to a missing native artifact: {entry['canonical_id']}")
        for entry in mapping.get("entries") or []:
            if entry["object_type"] == "entity" and entry.get("native_object_sha256"):
                artifact = entry["native_locator"]["artifact"]
                if sha256_text(artifacts.get(artifact, "")) != entry["native_object_sha256"]:
                    problems.append(f"entity native hash mismatch: {entry['canonical_id']}")

    declared_keys = {group.get("native_key") for group in projection_manifest.get("collision_groups") or []}
    for entry in mapping.get("entries") or []:
        if entry.get("correspondence_type") == MANY_TO_ONE_LOSSY and entry.get("native_key") not in declared_keys:
            problems.append(f"undeclared many-to-one collision for relation {entry['canonical_id']} "
                            f"(native key {entry.get('native_key')} is not in collision_groups)")

    for group in projection_manifest.get("collision_groups") or []:
        members = group["canonical_ids"]
        for canonical_id in members:
            entry = next((item for item in mapping.get("entries") or []
                          if item["object_type"] == "relation" and item["canonical_id"] == canonical_id), None)
            if entry is None:
                problems.append(f"collision relation without correspondence: {canonical_id}")
            elif len(members) > 1 and entry["correspondence_type"] != MANY_TO_ONE_LOSSY:
                problems.append(f"collision relation not marked MANY_TO_ONE_LOSSY: {canonical_id}")
    return {"ok": not problems, "problems": problems, "counts": mapping.get("counts"),
            "mapping_id": mapping.get("mapping_id"), "recomputed_id": recomputed}


def load_mapping(path: Path) -> Any:
    return read_json(path)
