"""Component C - KUYEN Canonical Sidecar.

Self-contained, deterministic JSON that preserves every canonical object the
native projection cannot represent, plus the correspondence and integrity links.
The sidecar never depends on OpenViking: it can be read, verified and
reconstructed with the engine switched off.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..canonical import digest, read_json, referenced_digest, sha256_file, sha256_text, write_canonical
from ..errors import SidecarError
from ..contracts import EXPORTER_VERSION, PROJECTOR_VERSION, RECONSTRUCTOR_VERSION, SCHEMA_NAME, SCHEMA_VERSION, SUPPORTED_KUYEN_SCHEMA_VERSIONS, SUPPORTED_SIDECAR_SCHEMA_VERSIONS

UNREPRESENTED_FIELDS = {
    "relation": ["relation_id", "polarity", "scope", "temporal_scope", "temporal", "evidence_ids",
                 "status", "semantic_status", "mapping_status", "mapping_rule_id", "mapping_version",
                 "provider_projection_status", "source_predicate", "canonical_predicate",
                 "provider_predicate", "provider_label", "source_label", "source_relation_ref",
                 "source_from_entity", "source_to_entity", "from_normalization_status",
                 "to_normalization_status", "normalization_reason"],
    "entity": ["evidence_ids", "source_entity_id", "source_namespace", "identity_basis",
               "normalization_status", "normalization_reason", "status", "metadata",
               "origin_entity_id", "canonical_entity_id", "identity_status", "identity_group_id"],
    "assertion": ["*"],
    "evidence": ["*"],
    "source_unit": ["*"],
    "coverage": ["*"],
    "mapu": ["content", "metadata", "trust_level", "access_policy", "license", "source_timestamp"],
}


def build_sidecar(
    document: dict[str, Any],
    projection_manifest: dict[str, Any],
    mapping: dict[str, Any],
    *,
    openviking_version: str,
    contract_snapshot_sha256: str,
    created_at: str | None = None,
    export_diagnostics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    kuyen = document["kuyen"]
    sidecar: dict[str, Any] = {
        "schema_name": SCHEMA_NAME,
        "schema_version": SCHEMA_VERSION,
        "created_at": created_at or datetime.now(timezone.utc).isoformat(),
        "kuyen_id": kuyen["kuyen_id"],
        "kuyen_version": kuyen["version"],
        "mapu_id": (document["mapus"][0]["mapu_id"] if document["mapus"] else None),
        "mapu_ids": list(kuyen["mapu_ids"]),
        "canonical_graph_hash": kuyen["canonical_graph_hash"],
        "source_hashes": {
            "graph_file_sha256": kuyen["source_graph_sha256"],
            "canonical_serialization_sha256": kuyen["canonical_serialization_sha256"],
            "mapu": {item["mapu_id"]: item["content_sha256"] for item in document["mapus"]},
            "source_units": {item["unit_id"]: item["content_sha256"] for item in document["canonical"]["source_units"]},
        },
        "exporter_version": EXPORTER_VERSION,
        "projector_version": PROJECTOR_VERSION,
        "reconstructor_version": RECONSTRUCTOR_VERSION,
        "openviking_version": openviking_version,
        "kuyen_contract": {
            "snapshot_sha256": contract_snapshot_sha256,
            "graph_schema_version": kuyen["schema_version"],
            "supported_graph_schema_versions": list(SUPPORTED_KUYEN_SCHEMA_VERSIONS),
        },
        "object_counts": dict(document["counts"]),
        "projection_manifest_hash": projection_manifest["projection_id"],
        "mapping_manifest_hash": mapping["mapping_id"],
        "kuyen": kuyen,
        "canonical": document["canonical"],
        "mapus": document["mapus"],
        "projection": {
            "projection_id": projection_manifest["projection_id"],
            "classification": projection_manifest["classification"],
            "artifacts": projection_manifest["artifacts"],
            "counts": projection_manifest["counts"],
            "collision_groups": projection_manifest["collision_groups"],
            "transformations": projection_manifest["transformations"],
            "unprojectable": projection_manifest["unprojectable"],
        },
        "mapping": {
            "mapping_id": mapping["mapping_id"],
            "schema_name": mapping["schema_name"],
            "schema_version": mapping["schema_version"],
            "counts": mapping["counts"],
        },
        "unrepresented_fields": UNREPRESENTED_FIELDS,
        "export_diagnostics": export_diagnostics or {},
        "integrity": {
            "integrity_status": "VALID_WITH_LOSSY_PROJECTION",
            "hash_algorithm": "sha256",
            "hash_scope": "all top-level keys except integrity.sidecar_content_hash, serialized as canonical JSON",
            "sidecar_content_hash": None,
        },
    }
    sidecar["integrity"]["sidecar_content_hash"] = referenced_digest(sidecar)
    return sidecar


def materialize_sidecar(sidecar: dict[str, Any], root: str | Path) -> dict[str, str]:
    root = Path(root)
    files = {}
    for name, payload in (("sidecar/KUYEN_CANONICAL_SIDECAR.json", sidecar),):
        files[name] = write_canonical(root / name, payload)
    return files


def verify_sidecar(sidecar: dict[str, Any], *, strict: bool = True) -> dict[str, Any]:
    """Fail-closed structural verification. Never repairs anything."""
    problems: list[str] = []
    status = "VALID"

    def fail(code: str, message: str) -> None:
        problems.append(f"{code}: {message}")

    if sidecar.get("schema_name") != SCHEMA_NAME:
        fail("SCHEMA_INVALID", f"schema_name={sidecar.get('schema_name')!r}")
        status = "SCHEMA_INVALID"
    if sidecar.get("schema_version") not in SUPPORTED_SIDECAR_SCHEMA_VERSIONS:
        fail("CANONICAL_VERSION_UNSUPPORTED", f"sidecar schema_version={sidecar.get('schema_version')!r}")
        status = "CANONICAL_VERSION_UNSUPPORTED"
    required = ("kuyen_id", "kuyen_version", "canonical_graph_hash", "object_counts",
                "source_hashes", "exporter_version", "projector_version", "kuyen", "canonical", "mapus",
                "projection_manifest_hash", "mapping_manifest_hash", "integrity")
    missing = [key for key in required if key not in sidecar]
    if missing:
        fail("SCHEMA_INVALID", f"missing required keys {missing}")
        status = status if status != "VALID" else "SCHEMA_INVALID"

    integrity = sidecar.get("integrity") or {}
    stamped = integrity.get("sidecar_content_hash")
    recomputed = referenced_digest(sidecar)
    if stamped != recomputed:
        fail("SIDECAR_HASH_MISMATCH", "sidecar_content_hash does not match the recomputed digest")
        status = "SIDECAR_HASH_MISMATCH"

    kuyen = sidecar.get("kuyen") or {}
    if kuyen.get("kuyen_id") != sidecar.get("kuyen_id"):
        fail("IDENTITY_MISMATCH", "kuyen.kuyen_id differs from the top-level kuyen_id")
        status = status if status != "VALID" else "IDENTITY_MISMATCH"
    if kuyen.get("canonical_graph_hash") != sidecar.get("canonical_graph_hash"):
        fail("IDENTITY_MISMATCH", "kuyen.canonical_graph_hash differs from the top-level hash")
        status = status if status != "VALID" else "IDENTITY_MISMATCH"
    graph_schema = ((sidecar.get("kuyen_contract") or {}).get("graph_schema_version"))
    if graph_schema not in SUPPORTED_KUYEN_SCHEMA_VERSIONS:
        fail("CANONICAL_VERSION_UNSUPPORTED", f"graph schema_version={graph_schema!r}")
        status = status if status not in {"VALID"} else "CANONICAL_VERSION_UNSUPPORTED"

    for version_key, expected in (("exporter_version", EXPORTER_VERSION), ("projector_version", PROJECTOR_VERSION)):
        if not sidecar.get(version_key):
            fail("ADAPTER_VERSION_UNSUPPORTED", f"{version_key} is missing")
            status = status if status != "VALID" else "ADAPTER_VERSION_UNSUPPORTED"

    canonical = sidecar.get("canonical") or {}
    for group in ("entities", "relations", "assertions", "evidence", "coverage", "source_units"):
        if not isinstance(canonical.get(group), list):
            fail("SCHEMA_INVALID", f"canonical.{group} is not a list")
            status = status if status != "VALID" else "SCHEMA_INVALID"
    counts = sidecar.get("object_counts") or {}
    for group, key in (("entities", "entities"), ("relations", "relations"), ("assertions", "assertions"),
                       ("evidence", "evidence"), ("source_units", "source_units")):
        if isinstance(canonical.get(group), list) and counts.get(key) is not None \
                and len(canonical[group]) != counts[key]:
            fail("MANIFEST_MISMATCH", f"object_counts.{key}={counts[key]} but canonical.{group} has {len(canonical[group])}")
            status = status if status != "VALID" else "MANIFEST_MISMATCH"

    entity_ids = {item.get("entity_id") for item in canonical.get("entities") or []}
    evidence_ids = {item.get("evidence_id") for item in canonical.get("evidence") or []}
    for relation in canonical.get("relations") or []:
        if relation.get("from_entity") not in entity_ids or relation.get("to_entity") not in entity_ids:
            fail("BROKEN_REFERENCE", f"relation {relation.get('relation_id')} has an unresolved endpoint")
            status = status if status != "VALID" else "BROKEN_REFERENCE"
    for group in ("entities", "relations", "assertions"):
        for item in canonical.get(group) or []:
            for ref in item.get("evidence_ids") or []:
                if ref not in evidence_ids:
                    fail("BROKEN_REFERENCE", f"{group[:-1]} {item.get('id') or item.get('relation_id') or item.get('assertion_id')} references unknown evidence {ref}")
                    status = status if status != "VALID" else "BROKEN_REFERENCE"
    for unit in canonical.get("source_units") or []:
        if unit.get("content") is None:
            fail("MISSING_CANONICAL_OBJECT", f"source unit {unit.get('unit_id')} has no content")
            status = status if status != "VALID" else "MISSING_CANONICAL_OBJECT"
        elif unit.get("content_sha256") and sha256_text(unit["content"]) != unit["content_sha256"]:
            fail("SIDECAR_HASH_MISMATCH", f"source unit {unit.get('unit_id')} content hash mismatch")
            status = status if status != "VALID" else "SIDECAR_HASH_MISMATCH"

    if status == "VALID" and (sidecar.get("projection") or {}).get("classification") == "LOSSY_NATIVE_PROJECTION":
        status = "VALID_WITH_LOSSY_PROJECTION"
    return {
        "ok": not problems,
        "status": status,
        "problems": problems,
        "sidecar_content_hash": stamped,
        "recomputed_content_hash": recomputed,
        "counts": counts,
    }


def load_sidecar(path: Path) -> dict[str, Any]:
    try:
        return read_json(path)
    except Exception as exc:  # noqa: BLE001
        raise SidecarError(str(exc)) from exc
