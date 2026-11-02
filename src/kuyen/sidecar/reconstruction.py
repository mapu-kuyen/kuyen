"""Canonical Sidecar Reconstructor.

Its only authority is persisted, recovered information: the sidecar, the
correspondence manifest, the integrity manifest and (when available) the native
artifacts needed to cross-check correspondences. It never reads the original
graph, the original MAPU, the fixtures or any exporter state, never infers, never
repairs and never promotes a native projection to a canonical assertion.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..canonical import canonical_json, digest, read_json, sha256_text
from ..contracts import RECONSTRUCTOR_VERSION, SUPPORTED_KUYEN_SCHEMA_VERSIONS, SUPPORTED_SIDECAR_SCHEMA_VERSIONS
from ..projection.mapping import verify_mapping
from ..projection.openviking import verify_integrity
from . import verify_sidecar

STATUS_VALID = "VALID"
STATUS_VALID_LOSSY = "VALID_WITH_LOSSY_PROJECTION"
STATUS_MISSING_SIDECAR = "MISSING_SIDECAR"
STATUS_SIDECAR_HASH = "SIDECAR_HASH_MISMATCH"
STATUS_PROJECTION_HASH = "PROJECTION_HASH_MISMATCH"
STATUS_MANIFEST_MISMATCH = "MANIFEST_MISMATCH"
STATUS_CANONICAL_VERSION = "CANONICAL_VERSION_UNSUPPORTED"
STATUS_ADAPTER_VERSION = "ADAPTER_VERSION_UNSUPPORTED"
STATUS_OPENVIKING_MISMATCH = "OPENVIKING_VERSION_MISMATCH"
STATUS_IDENTITY = "IDENTITY_MISMATCH"
STATUS_MISSING_CANONICAL = "MISSING_CANONICAL_OBJECT"
STATUS_MISSING_NATIVE = "MISSING_NATIVE_OBJECT"
STATUS_AMBIGUOUS = "AMBIGUOUS_MAPPING"
STATUS_BROKEN_REFERENCE = "BROKEN_REFERENCE"
STATUS_SCHEMA_INVALID = "SCHEMA_INVALID"
STATUS_FAILED = "RECONSTRUCTION_FAILED"

GRAPH_KEYS = ("kuyen_id", "version", "antu_id", "mapu_ids", "schema_version", "status",
              "entities", "relations", "assertions", "evidence", "coverage", "provenance",
              "content_digest", "provenance_digest")


@dataclass
class ReconstructionResult:
    status: str
    accepted: bool
    graph: dict[str, Any] | None = None
    reconstructed_hash: str | None = None
    declared_hash: str | None = None
    hashes_match: bool = False
    projection_available: bool = True
    canonical_integrity: bool = False
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    checks: dict[str, Any] = field(default_factory=dict)
    invalid_correspondences: list[str] = field(default_factory=list)
    missing_objects: list[str] = field(default_factory=list)
    extra_objects: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status, "accepted": self.accepted,
            "reconstructed_hash": self.reconstructed_hash, "declared_hash": self.declared_hash,
            "hashes_match": self.hashes_match, "projection_available": self.projection_available,
            "canonical_integrity": self.canonical_integrity,
            "errors": self.errors, "warnings": self.warnings, "checks": self.checks,
            "invalid_correspondences": self.invalid_correspondences,
            "missing_objects": self.missing_objects, "extra_objects": self.extra_objects,
            "graph": self.graph,
        }


def reconstruct(
    recovered_dir: str | Path,
    *,
    expected_kuyen_id: str | None = None,
    expected_canonical_hash: str | None = None,
    expected_openviking_version: str | None = None,
    require_native_artifacts: bool = False,
    contract_snapshot_path: Path | None = None,
    contract_src: Path | None = None,
) -> ReconstructionResult:
    recovered_dir = Path(recovered_dir)
    checks: dict[str, Any] = {}
    warnings: list[str] = []

    sidecar_path = recovered_dir / "sidecar/KUYEN_CANONICAL_SIDECAR.json"
    mapping_path = recovered_dir / "mapping/CORRESPONDENCE_MANIFEST.json"
    integrity_path = recovered_dir / "manifests/INTEGRITY.json"
    if not sidecar_path.is_file():
        return ReconstructionResult(status=STATUS_MISSING_SIDECAR, accepted=False,
                                    errors=[f"sidecar not found at {sidecar_path.name}"], checks=checks)
    try:
        sidecar = read_json(sidecar_path)
        mapping = read_json(mapping_path) if mapping_path.is_file() else None
        integrity = read_json(integrity_path) if integrity_path.is_file() else None
    except Exception as exc:  # noqa: BLE001
        return ReconstructionResult(status=STATUS_SCHEMA_INVALID, accepted=False,
                                    errors=[f"unreadable persisted artifact: {exc}"], checks=checks)

    # 1. integrity manifest over the recovered bytes
    files: dict[str, bytes] = {}
    for path in sorted(p for p in recovered_dir.rglob("*") if p.is_file()):
        relative = path.relative_to(recovered_dir).as_posix()
        files[relative] = path.read_bytes()
    if integrity is None:
        warnings.append("integrity manifest missing: cannot verify bundle-level hashes")
        checks["integrity"] = {"ok": False, "problems": ["missing integrity manifest"]}
    else:
        checks["integrity"] = verify_integrity(integrity, files)
    if integrity is not None and not checks["integrity"]["ok"]:
        # the bundle seal is part of the sidecar mechanism: a broken seal fails closed
        return ReconstructionResult(status=STATUS_MANIFEST_MISMATCH, accepted=False,
                                    errors=checks["integrity"]["problems"], checks=checks,
                                    declared_hash=sidecar.get("canonical_graph_hash") if isinstance(sidecar, dict) else None)

    # 2. sidecar verification
    checks["sidecar"] = verify_sidecar(sidecar)
    if not checks["sidecar"]["ok"]:
        status = checks["sidecar"]["status"]
        return ReconstructionResult(status=status, accepted=False,
                                    errors=checks["sidecar"]["problems"], checks=checks,
                                    declared_hash=sidecar.get("canonical_graph_hash"))

    # 3. identity / version gates
    if expected_kuyen_id and sidecar.get("kuyen_id") != expected_kuyen_id:
        return ReconstructionResult(status=STATUS_IDENTITY, accepted=False, checks=checks,
                                    declared_hash=sidecar.get("canonical_graph_hash"),
                                    errors=[f"sidecar belongs to {sidecar.get('kuyen_id')}, expected {expected_kuyen_id}"])
    if sidecar.get("schema_version") not in SUPPORTED_SIDECAR_SCHEMA_VERSIONS:
        return ReconstructionResult(status=STATUS_CANONICAL_VERSION, accepted=False, checks=checks,
                                    errors=[f"unsupported sidecar schema_version {sidecar.get('schema_version')}"])
    if (sidecar.get("kuyen_contract") or {}).get("graph_schema_version") not in SUPPORTED_KUYEN_SCHEMA_VERSIONS:
        return ReconstructionResult(status=STATUS_CANONICAL_VERSION, accepted=False, checks=checks,
                                    errors=[f"unsupported graph schema_version "
                                            f"{(sidecar.get('kuyen_contract') or {}).get('graph_schema_version')}"])
    if expected_openviking_version and sidecar.get("openviking_version") != expected_openviking_version:
        warnings.append(f"openviking_version mismatch: sidecar={sidecar.get('openviking_version')} "
                        f"expected={expected_openviking_version}")
        checks["openviking_version"] = {"ok": False, "sidecar": sidecar.get("openviking_version"),
                                        "expected": expected_openviking_version}

    # 4. correspondence manifest
    projection_block = sidecar.get("projection") or {}
    pseudo_manifest = {"projection_id": projection_block.get("projection_id"),
                       "collision_groups": projection_block.get("collision_groups") or [],
                       "artifacts": projection_block.get("artifacts") or {}}
    if mapping is None:
        checks["mapping"] = {"ok": False, "problems": ["mapping manifest missing"]}
        return ReconstructionResult(status=STATUS_MANIFEST_MISMATCH, accepted=False, checks=checks,
                                    errors=["correspondence manifest missing"])
    native_artifacts = {name.replace("native/", "native/"): payload.decode("utf-8")
                        for name, payload in files.items() if name.startswith("native/") and name.endswith((".md", ".jsonl"))}
    checks["mapping"] = verify_mapping(mapping, {"kuyen": sidecar["kuyen"], "canonical": sidecar["canonical"]},
                                       pseudo_manifest, native_artifacts)
    if not checks["mapping"]["ok"]:
        status = STATUS_AMBIGUOUS if any("MANY_TO_ONE" in item for item in checks["mapping"]["problems"]) \
            else STATUS_MANIFEST_MISMATCH
        return ReconstructionResult(status=status, accepted=False, checks=checks,
                                    errors=checks["mapping"]["problems"],
                                    invalid_correspondences=checks["mapping"]["problems"],
                                    declared_hash=sidecar.get("canonical_graph_hash"))

    # 5. native artifact availability (degrades the projection, not the canonical record)
    declared_artifacts = projection_block.get("artifacts") or {}
    missing_native, mismatched_native = [], []
    for relative, expected in sorted(declared_artifacts.items()):
        payload = files.get(relative)
        if payload is None:
            missing_native.append(relative)
        elif sha256_text(payload.decode("utf-8")) != expected:
            mismatched_native.append(relative)
    projection_available = not missing_native and not mismatched_native
    checks["native_artifacts"] = {"declared": len(declared_artifacts), "missing": missing_native,
                                  "mismatched": mismatched_native, "available": projection_available}
    if mismatched_native:
        warnings.append(f"native artifacts changed: {mismatched_native}")
    if missing_native:
        warnings.append(f"native artifacts missing: {missing_native}")
    if require_native_artifacts and not projection_available:
        return ReconstructionResult(status=STATUS_MISSING_NATIVE, accepted=False, checks=checks,
                                    projection_available=False,
                                    errors=[f"native artifacts unavailable: {missing_native + mismatched_native}"])

    # 6. rebuild the canonical graph from the sidecar only
    canonical = sidecar.get("canonical") or {}
    kuyen = sidecar.get("kuyen") or {}
    graph = {
        "kuyen_id": kuyen.get("kuyen_id"),
        "version": kuyen.get("version"),
        "antu_id": kuyen.get("antu_id"),
        "mapu_ids": list(kuyen.get("mapu_ids") or []),
        "schema_version": kuyen.get("schema_version"),
        "status": kuyen.get("status"),
        "entities": list(canonical.get("entities") or []),
        "relations": list(canonical.get("relations") or []),
        "assertions": list(canonical.get("assertions") or []),
        "evidence": list(canonical.get("evidence") or []),
        "coverage": list(canonical.get("coverage") or []),
        "provenance": kuyen.get("provenance") or {},
        "content_digest": kuyen.get("content_digest"),
        "provenance_digest": kuyen.get("provenance_digest"),
    }
    missing_keys = [key for key in GRAPH_KEYS if key not in graph]
    if missing_keys:
        return ReconstructionResult(status=STATUS_FAILED, accepted=False, checks=checks,
                                    errors=[f"reconstructed graph is missing {missing_keys}"])

    checks["contract"] = _validate_contract(graph, sidecar, contract_snapshot_path, contract_src)
    if not checks["contract"]["ok"]:
        return ReconstructionResult(status=checks["contract"]["status"], accepted=False, checks=checks,
                                    errors=checks["contract"]["problems"],
                                    missing_objects=checks["contract"].get("missing_objects") or [],
                                    declared_hash=sidecar.get("canonical_graph_hash"))

    reconstructed_hash = digest(graph)
    declared_hash = sidecar.get("canonical_graph_hash")
    reference_hash = expected_canonical_hash or declared_hash
    hashes_match = reconstructed_hash == reference_hash
    if not hashes_match:
        return ReconstructionResult(status=STATUS_FAILED, accepted=False, graph=graph, checks=checks,
                                    reconstructed_hash=reconstructed_hash, declared_hash=declared_hash,
                                    errors=["reconstructed canonical hash does not match the declared hash"],
                                    projection_available=projection_available)

    status = STATUS_VALID_LOSSY if (not projection_available or sidecar.get("projection", {}).get("classification") == "LOSSY_NATIVE_PROJECTION") else STATUS_VALID
    return ReconstructionResult(
        status=status, accepted=True, graph=graph, reconstructed_hash=reconstructed_hash,
        declared_hash=declared_hash, hashes_match=True, projection_available=projection_available,
        canonical_integrity=True, warnings=warnings, checks=checks,
    )


def _validate_contract(graph: dict[str, Any], sidecar: dict[str, Any],
                      contract_snapshot_path: Path | None,
                      contract_src: Path | None = None) -> dict[str, Any]:
    problems: list[str] = []
    status = STATUS_VALID
    snapshot = None
    if contract_snapshot_path and Path(contract_snapshot_path).is_file():
        snapshot = read_json(Path(contract_snapshot_path))
    required_graph = (snapshot or {}).get("graph_schema", {}).get("required") or list(GRAPH_KEYS)
    for key in required_graph:
        if key not in graph:
            problems.append(f"graph missing required key {key}")
    entity_ids = {item.get("entity_id") for item in graph["entities"]}
    evidence_ids = {item.get("evidence_id") for item in graph["evidence"]}
    missing_objects = []
    for relation in graph["relations"]:
        if relation.get("from_entity") not in entity_ids or relation.get("to_entity") not in entity_ids:
            problems.append(f"relation {relation.get('relation_id')} has an unresolved endpoint")
            missing_objects.append(relation.get("relation_id"))
    for group in ("entities", "relations", "assertions"):
        for item in graph[group]:
            for ref in item.get("evidence_ids") or []:
                if ref not in evidence_ids:
                    problems.append(f"{group} object {item.get('entity_id') or item.get('relation_id') or item.get('assertion_id')} references unknown evidence {ref}")
    if problems:
        status = STATUS_BROKEN_REFERENCE

    round_trip = {"engine": None, "ok": None}
    try:  # productive dataclasses, read-only
        repo_src = Path(contract_src) if contract_src else Path(__file__).resolve().parents[4] / "src"
        if str(repo_src) not in sys.path:
            sys.path.insert(0, str(repo_src))
        from kuyen.models.domain import Assertion, Entity, Relation  # noqa: PLC0415

        for entity in graph["entities"]:
            Entity.from_dict(entity)
        for relation in graph["relations"]:
            Relation.from_dict(relation)
        for assertion in graph["assertions"]:
            Assertion.from_dict(assertion)
        round_trip = {"engine": "kuyen.models.domain dataclasses (read-only import)", "ok": True}
    except Exception as exc:  # noqa: BLE001
        round_trip = {"engine": "kuyen.models.domain dataclasses (read-only import)", "ok": False,
                      "error": str(exc)}
        if status == STATUS_VALID:
            status = STATUS_SCHEMA_INVALID
        problems.append(f"productive contract round-trip failed: {exc}")

    return {"ok": not problems, "status": status, "problems": problems, "missing_objects": missing_objects,
            "round_trip": round_trip, "contract_snapshot_used": bool(snapshot),
            "contract_snapshot_sha256": digest(snapshot) if snapshot else None,
            "counts": {group: len(graph[group]) for group in ("entities", "relations", "assertions", "evidence")}}
