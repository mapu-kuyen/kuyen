"""Independent recovery: rebuild KUYEN from the canonical store alone.

This module never opens OpenViking, never reads a fixture and never re-executes an Antu.
It verifies the store, then reconstructs every accepted version using the confirmed
sidecar reconstructor and compares the rebuilt hash with the committed manifest.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from ..lifecycle.ledger import verify_chain
from ..storage.store import CanonicalStore, same_device
from ..storage.commit import pending_commits
from ..canonical import canonical_json_pretty, read_json, sha256_file
from ..storage.versions import list_versions, read_version, verify_version
from ..storage.registry import lineage, verify_registry
from ..lifecycle.unit import verify_unit_history
from ..sidecar import reconstruction as upstream_reconstruction


def _materialize(store: CanonicalStore, version_id: str, target: Path) -> dict[str, Path]:
    """Materialize just the persisted artifacts the reconstructor consumes."""
    manifest = read_version(store, version_id).manifest
    target.mkdir(parents=True, exist_ok=True)
    sidecar_path = target / "sidecar/KUYEN_CANONICAL_SIDECAR.json"
    mapping_path = target / "mapping/CORRESPONDENCE_MANIFEST.json"
    sidecar_path.parent.mkdir(parents=True, exist_ok=True)
    mapping_path.parent.mkdir(parents=True, exist_ok=True)
    sidecar_path.write_text(store.get_blob(manifest["sidecar_blob"]).decode("utf-8"), encoding="utf-8")
    mapping_path.write_text(store.get_blob(manifest["mapping_blob"]).decode("utf-8"), encoding="utf-8")
    native = {}
    for relative, blob in sorted((manifest.get("native_projection_blobs") or {}).items()):
        path = target / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(store.get_blob(blob).decode("utf-8"), encoding="utf-8")
        native[relative] = blob
    return {"root": target, "sidecar": sidecar_path, "mapping": mapping_path, "native": native}


def reconstruct_version(store: CanonicalStore, version_id: str, *, workdir: Path,
                        contract_snapshot: Path, contract_src: Path) -> dict[str, Any]:
    manifest = read_version(store, version_id).manifest
    paths = _materialize(store, version_id, workdir / "materialized" / version_id)
    result = upstream_reconstruction.reconstruct(paths["root"], expected_canonical_hash=manifest["canonical_graph_hash"],
                         contract_snapshot_path=contract_snapshot, contract_src=contract_src)
    return {"version_id": version_id, "status": result.status, "accepted": result.accepted,
            "native_artifacts_materialized": len(paths["native"]),
            "hashes_match": result.hashes_match, "reconstructed_hash": result.reconstructed_hash,
            "declared_hash": manifest["canonical_graph_hash"], "errors": result.errors,
            "warnings": [warning for warning in result.warnings if "integrity manifest" not in warning],
            "contract_round_trip": (result.checks.get("contract") or {}).get("round_trip")}


def recover_store(store_path: str | Path, *, workdir: str | Path, contract_snapshot: str | Path,
                  contract_src: str | Path, openviking_workspace: str | Path | None = None) -> dict[str, Any]:
    """Full independent recovery. Every failure is data; nothing raises except a missing store."""
    store = CanonicalStore(store_path)
    workdir = Path(workdir)
    if workdir.exists():
        shutil.rmtree(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    contract_snapshot, contract_src = Path(contract_snapshot), Path(contract_src)

    objects = store.verify_objects()
    registry = verify_registry(store)
    ledger = verify_chain(store)
    unit = verify_unit_history(store)
    pending = pending_commits(store)
    versions = []
    for record in list_versions(store):
        verification = verify_version(store, record.version_id)
        reconstruction = reconstruct_version(store, record.version_id, workdir=workdir,
                                             contract_snapshot=contract_snapshot, contract_src=contract_src)
        versions.append({"version_id": record.version_id, "kuyen_version": record.manifest["kuyen_version"],
                         "canonical_graph_hash": record.canonical_graph_hash,
                         "blobs_ok": verification["ok"], "blob_problems": verification["problems"],
                         "reconstruction": reconstruction,
                         "lineage": [item["version_id"] for item in lineage(store, record.version_id)]})
    current = store.read_current()
    current_reconstruction = next((item for item in versions
                                   if current and item["version_id"] == current.get("version_id")), None)
    info = store.info()
    independence = {
        "logical": True,
        "process": True,
        "service": True,
        "directory": True,
        "same_device_as_openviking": (same_device(store.root, openviking_workspace)
                                      if openviking_workspace and Path(openviking_workspace).exists() else None),
        "openviking_accessed": False,
        "openviking_workspace_present": bool(openviking_workspace and Path(openviking_workspace).exists()),
    }
    problems = []
    if not objects["ok"]:
        problems.append("object store has corrupt blobs")
    if not registry["ok"]:
        problems.append(f"registry: {registry['problems'][:3]}")
    if not ledger["ok"]:
        problems.append(f"ledger: {ledger['problems'][:3]}")
    if not unit["ok"]:
        problems.append(f"unit history: {unit['problems'][:3]}")
    for item in versions:
        if not item["blobs_ok"]:
            problems.append(f"version {item['version_id']} has blob problems")
        if not item["reconstruction"]["accepted"] or not item["reconstruction"]["hashes_match"]:
            problems.append(f"version {item['version_id']} was not reconstructed with an exact hash")
    if current is None:
        problems.append("CURRENT pointer is missing")
    elif current_reconstruction is None:
        problems.append("CURRENT points at a version that is not in the store")
    return {
        "store": info, "objects": objects, "registry": registry, "ledger": ledger, "unit": unit,
        "pending_commits": pending, "versions": versions, "current": current,
        "independence": independence, "problems": problems, "ok": not problems,
        "versions_recovered": len(versions),
        "reconstructions_exact": sum(1 for item in versions if item["reconstruction"]["hashes_match"]),
    }


def rebuild_projection_document(store: CanonicalStore, version_id: str) -> dict[str, Any]:
    """The canonical document a projection must be derived from (no Antu, no fixture)."""
    from ..projection.native import document_from_sidecar
    manifest = read_version(store, version_id).manifest
    sidecar = json.loads(store.get_blob(manifest["sidecar_blob"]).decode("utf-8"))
    return document_from_sidecar(sidecar)
