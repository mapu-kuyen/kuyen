"""Projection layer: OpenViking as a regenerable, subordinate representation.

Everything here derives from a sidecar blob read out of the canonical store. No
Antu is re-executed, no fixture and no original MAPU file is read, and the canonical
version is never modified by a projection.
"""
from __future__ import annotations

import json
from typing import Any

from ..storage.store import CanonicalStore
from ..canonical import digest, read_json, sha256_text, write_atomic, canonical_json_pretty
from ..errors import StoreError
from ..contracts import PROJECTION_DOMAIN, PROJECTION_REGISTRY_FORMAT_VERSION, PROJECTOR_VERSION
from ..storage.versions import read_version
from .outbox import (STATUS_DONE, STATUS_FAILED, STATUS_IN_PROGRESS, STATUS_PENDING, claim, get,
                     record_attempt, update)
from . import mapping as upstream_mapping
from . import openviking as upstream_persistence
from . import projector as upstream_projector


def document_from_sidecar(sidecar: dict[str, Any]) -> dict[str, Any]:
    """The projector's input view, rebuilt from the canonical sidecar alone."""
    document = {
        "kuyen": sidecar["kuyen"],
        "canonical": sidecar["canonical"],
        "mapus": sidecar.get("mapus") or [],
        "counts": sidecar.get("object_counts") or {},
    }
    # The schema is part of the version when the instance declares one (KUYEN_DISTRIBUTED_ANTU_12).
    if "schema" in sidecar:
        document["schema"] = sidecar["schema"]
    return document


def load_sidecar(store: CanonicalStore, version_id: str) -> dict[str, Any]:
    manifest = read_version(store, version_id).manifest
    return json.loads(store.get_blob(manifest["sidecar_blob"]).decode("utf-8"))


def build(store: CanonicalStore, version_id: str, *, projector_version: str = PROJECTOR_VERSION,
          instance_tag: str | None = None) -> dict[str, Any]:
    """Build the projection artifacts from the canonical store only."""
    manifest = read_version(store, version_id).manifest
    sidecar = load_sidecar(store, version_id)
    document = document_from_sidecar(sidecar)
    projector = upstream_projector.NativeProjector()
    projector.version = projector_version
    projection = projector.project(document)
    mapping = upstream_mapping.build_mapping(document, projection.manifest)
    projection_id = digest({
        "domain": PROJECTION_DOMAIN,
        "version_id": version_id,
        "canonical_graph_hash": manifest["canonical_graph_hash"],
        "projector_version": projector_version,
        "projection_id": projection.manifest["projection_id"],
        "mapping_id": mapping["mapping_id"],
        "instance_tag": instance_tag,
    })
    return {"version_id": version_id, "sidecar": sidecar, "document": document,
            "artifacts": projection.artifacts, "projection_manifest": projection.manifest,
            "mapping": mapping, "projection_id": projection_id,
            "projector_version": projector_version}


def bundle_files(built: dict[str, Any]) -> dict[str, str]:
    files = dict(built["artifacts"])
    files["native/projection_manifest.json"] = canonical_json_pretty(built["projection_manifest"])
    files["mapping/CORRESPONDENCE_MANIFEST.json"] = canonical_json_pretty(built["mapping"])
    reference = {
        "schema_name": "KUYEN_PROJECTION_REFERENCE",
        "schema_version": "1.0.0",
        "projection_id": built["projection_id"],
        "version_id": built["version_id"],
        "canonical_graph_hash": built["projection_manifest"]["kuyen"]["canonical_graph_hash"],
        "sidecar_schema_version": built["sidecar"]["schema_version"],
        "projector_version": built["projector_version"],
        "note": "this file is a projection; the canonical authority is the KUYEN canonical store",
    }
    files["PROJECTION_REFERENCE.json"] = canonical_json_pretty(reference)
    return files


def integrity_of(files: dict[str, str], *, built: dict[str, Any], openviking_version: str | None) -> dict[str, Any]:
    hashes = {name: sha256_text(text) for name, text in sorted(files.items())}
    integrity = {
        "schema_name": "KUYEN_PROJECTION_INTEGRITY",
        "schema_version": "1.0.0",
        "projection_id": built["projection_id"],
        "version_id": built["version_id"],
        "canonical_graph_hash": built["projection_manifest"]["kuyen"]["canonical_graph_hash"],
        "projector_version": built["projector_version"],
        "openviking_version": openviking_version,
        "file_hashes": hashes,
        "file_count": len(hashes),
        "hash_scope": "every projected file except this integrity manifest",
    }
    integrity["integrity_id"] = digest({key: value for key, value in integrity.items() if key != "integrity_id"})
    return integrity


def uri_root(kuyen_id: str, version_id: str, projector_version: str,
             instance_tag: str | None = None) -> str:
    suffix = f"p{projector_version}" + (f"-{instance_tag}" if instance_tag else "")
    return f"viking://resources/kuyen-canonical-memory/{kuyen_id}/{version_id}/{suffix}"


def project(store: CanonicalStore, operation_key: str, *, client: upstream_persistence.OpenVikingStore,
            openviking_version: str, created_at: str, failpoint=None) -> dict[str, Any] | None:
    """Execute one outbox operation against OpenViking, at most once per claim.

    Returns the projection entry, or None when the operation was already done or is held by
    another runner: executing it twice would duplicate external work, the registry entry
    and the completion event (front 1).
    """
    if get(store, operation_key) is None:
        raise KeyError(operation_key)
    operation = claim(store, operation_key)
    if operation is None:
        return None
    attempt = {"started_at": created_at, "attempt": len(operation.get("attempts") or []) + 1}
    try:
        built = build(store, operation["version_id"], projector_version=operation["projector_version"],
                      instance_tag=operation.get("instance_tag"))
        files = bundle_files(built)
        integrity = integrity_of(files, built=built, openviking_version=openviking_version)
        files["manifests/PROJECTION_INTEGRITY.json"] = canonical_json_pretty(integrity)
        root = uri_root(operation["kuyen_id"], operation["version_id"], operation["projector_version"],
                        operation.get("instance_tag"))
        if failpoint:
            failpoint("during_openviking_write", {"files": files, "root": root})
        client.mkdir(root)
        written = []
        for name, text in sorted(files.items()):
            if failpoint:
                failpoint("after_partial_projection", {"written": len(written), "name": name})
            response = client.write(f"{root}/{name}", text)
            if not response.ok:
                raise StoreError(f"projection write failed for {name}: {response.error_message}")
            written.append(name)
        if failpoint:
            failpoint("before_mark_complete", {"written": len(written)})
        readback = {}
        for name, text in sorted(files.items()):
            response = client.read(f"{root}/{name}")
            readback[name] = bool(response.ok and isinstance(response.result, str)
                                  and sha256_text(response.result) == sha256_text(text))
        verification = {"files": len(files), "byte_exact": sum(1 for value in readback.values() if value),
                        "all_byte_exact": all(readback.values()), "uri_root": root}
        entry = {
            "schema_name": "KUYEN_PROJECTION_REGISTRY_ENTRY",
            "schema_version": PROJECTION_REGISTRY_FORMAT_VERSION,
            "projection_id": operation and built["projection_id"],
            "version_id": built["version_id"],
            "kuyen_id": operation["kuyen_id"], "kuyen_version": operation["kuyen_version"],
            "canonical_graph_hash": built["projection_manifest"]["kuyen"]["canonical_graph_hash"],
            "sidecar_schema_version": built["sidecar"]["schema_version"],
            "projector_version": built["projector_version"],
            "openviking_version": openviking_version,
            "instance_tag": operation.get("instance_tag"),
            "status": "CURRENT",
            "created_at": created_at,
            "uri_root": root,
            "artifacts": built["projection_manifest"]["artifacts"],
            "mapping_id": built["mapping"]["mapping_id"],
            "losses": {"collision_groups": len(built["projection_manifest"]["collision_groups"]),
                       "unprojectable": len(built["projection_manifest"]["unprojectable"]),
                       "transformations": len(built["projection_manifest"]["transformations"])},
            "file_hashes": integrity["file_hashes"],
            "integrity_id": integrity["integrity_id"],
            "verification": verification,
            "outbox_operation_key": operation_key,
        }
        entry["entry_hash"] = digest(entry)
        with store.writer_lock():
            write_atomic(store.projections_dir / f"{entry['projection_id']}.json",
                         canonical_json_pretty(entry))
            if failpoint:
                failpoint("after_projection_complete", {"projection_id": entry["projection_id"]})
            record_completion_event(store, entry, created_at=created_at)
            attempt.update({"finished_at": created_at, "result": "DONE",
                            "projection_id": entry["projection_id"],
                            "byte_exact": verification["byte_exact"]})
            record_attempt(store, operation_key, attempt, status=STATUS_DONE,
                           projection_id=entry["projection_id"])
        return entry
    except Exception as exc:  # noqa: BLE001 - a failed projection is data, not a crash
        attempt.update({"finished_at": created_at, "result": "FAILED", "error": str(exc)[:500]})
        record_attempt(store, operation_key, attempt, status=STATUS_FAILED, error=str(exc)[:500])
        raise


def record_completion_event(store: CanonicalStore, entry: dict[str, Any], *, created_at: str) -> bool:
    """Record the completion of a projection once, inside the finalization lock.

    The event is part of the same critical section as the registry entry and the `DONE`
    status, so `DONE` always implies both. It is written *before* `DONE` and skipped when a
    previous attempt already recorded it, so a retry after an interruption never duplicates
    the event (front 1).
    """
    from ..lifecycle.ledger import append_event, events_of_type  # local import: no cycle

    already = [event for event in events_of_type(store, "PROJECTION_COMPLETED")
               if event.get("projection_id") == entry["projection_id"]]
    if already:
        return False
    append_event(store, "PROJECTION_COMPLETED", {
        "version_id": entry["version_id"], "projection_id": entry["projection_id"],
        "recorded_at": created_at})
    return True


def list_projections(store: CanonicalStore) -> list[dict[str, Any]]:
    return [read_json(path) for path in sorted(store.projections_dir.glob("*.json"))]


def projections_for_version(store: CanonicalStore, version_id: str) -> list[dict[str, Any]]:
    return [entry for entry in list_projections(store) if entry["version_id"] == version_id]
