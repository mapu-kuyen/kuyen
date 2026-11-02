"""Immutable canonical versions.

A version is a manifest plus content-addressed blobs. The manifest is written once and
never rewritten; `write_version` refuses to replace a different manifest and is
idempotent for an identical one. `version_id` is derived from the identity core, so two
versions with identical graph content but different lineage share physical blobs while
keeping distinct logical identities.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .store import CanonicalStore
from ..canonical import canonical_json, digest, read_json, sha256_bytes, write_atomic
from ..errors import ImmutableViolation, StoreError

VERSION_PREFIX = "VER-"


def version_id_for(core: dict[str, Any]) -> str:
    return VERSION_PREFIX + digest(core)[:12]


@dataclass
class VersionRecord:
    manifest: dict[str, Any]

    @property
    def version_id(self) -> str:
        return self.manifest["version_id"]

    @property
    def canonical_graph_hash(self) -> str:
        return self.manifest["canonical_graph_hash"]

    @property
    def parent_version_id(self) -> str | None:
        return self.manifest.get("parent_version_id")

    def to_dict(self) -> dict[str, Any]:
        return dict(self.manifest)


def build_manifest(
    *,
    identity: dict[str, Any],
    sidecar: dict[str, Any],
    canonical_graph_hash: str,
    parent_version_id: str | None,
    antu_id: str,
    unit_revision: str,
    mapu_revisions: list[dict[str, Any]],
    object_hashes: dict[str, str],
    counts: dict[str, int],
    adapter_versions: dict[str, str],
    created_at: str,
) -> dict[str, Any]:
    core = {
        "kuyen_id": identity["kuyen_id"],
        "kuyen_version": identity["kuyen_version"],
        "canonical_graph_hash": canonical_graph_hash,
        "parent_version_id": parent_version_id,
        "antu_id": antu_id,
        "unit_revision": unit_revision,
    }
    return {
        "schema_name": "KUYEN_CANONICAL_VERSION",
        "schema_version": "1.0.0",
        "version_id": version_id_for(core),
        "identity_core": core,
        "leftraru_id": identity["leftraru_id"],
        "kuyen_id": identity["kuyen_id"],
        "kuyen_version": identity["kuyen_version"],
        "unit_revision": unit_revision,
        "antu_id": antu_id,
        "parent_version_id": parent_version_id,
        "canonical_graph_hash": canonical_graph_hash,
        "canonical_serialization_sha256": sidecar["kuyen"]["canonical_serialization_sha256"],
        "sidecar_content_hash": sidecar["integrity"]["sidecar_content_hash"],
        "sidecar_schema_version": sidecar["schema_version"],
        "sidecar_blob": None,
        "integrity_blob": None,
        "mapping_blob": None,
        "projection_manifest_blob": None,
        "mapu_revisions": mapu_revisions,
        "object_hashes": dict(sorted(object_hashes.items())),
        "counts": counts,
        "adapter_versions": dict(adapter_versions),
        "openviking_version_at_commit": None,
        "created_at": created_at,
        "acceptance": {"status": "ACCEPTED", "committed_by": "KUYEN_CANONICAL_COMMIT_PROTOCOL"},
        "blob_inventory": [],
    }


def write_version(store: CanonicalStore, manifest: dict[str, Any], *, blob_inventory: list[str]) -> dict[str, Any]:
    """Write the version manifest atomically; never overwrite a different manifest."""
    version_id = manifest["version_id"]
    target = store.versions_dir / version_id / "manifest.json"
    payload = canonical_json({**manifest, "blob_inventory": sorted(set(blob_inventory))})
    if target.is_file():
        existing = read_json(target)
        if canonical_json(existing) == payload:
            return existing
        raise ImmutableViolation(f"version {version_id} already exists with different content")
    target.parent.mkdir(parents=True, exist_ok=True)
    write_atomic(target, payload)
    return read_json(target)


def read_version(store: CanonicalStore, version_id: str) -> VersionRecord:
    path = store.versions_dir / version_id / "manifest.json"
    if not path.is_file():
        raise StoreError(f"unknown version: {version_id}")
    return VersionRecord(read_json(path))


def list_versions(store: CanonicalStore) -> list[VersionRecord]:
    records = []
    for directory in sorted(p for p in store.versions_dir.iterdir() if p.is_dir()):
        manifest = directory / "manifest.json"
        if manifest.is_file():
            records.append(VersionRecord(read_json(manifest)))
    return records


def verify_version(store: CanonicalStore, version_id: str) -> dict[str, Any]:
    """Every blob referenced by the version must exist and match its hash."""
    problems: list[str] = []
    record = read_version(store, version_id)
    manifest = record.manifest
    for name in ("sidecar_blob", "integrity_blob", "mapping_blob", "projection_manifest_blob"):
        blob = manifest.get(name)
        if not blob:
            problems.append(f"missing reference {name}")
            continue
        try:
            store.get_blob(blob)
        except StoreError as exc:
            problems.append(f"{name}: {exc}")
    for relative, content_hash in (manifest.get("object_hashes") or {}).items():
        try:
            store.get_blob(content_hash)
        except StoreError as exc:
            problems.append(f"object {relative}: {exc}")
    sidecar_payload = None
    if manifest.get("sidecar_blob"):
        try:
            sidecar_payload = store.get_blob(manifest["sidecar_blob"]).decode("utf-8")
        except StoreError:
            sidecar_payload = None
    if sidecar_payload is not None:
        sidecar = __import__("json").loads(sidecar_payload)
        if sidecar.get("canonical_graph_hash") != manifest["canonical_graph_hash"]:
            problems.append("sidecar canonical_graph_hash does not match the version manifest")
        if sidecar.get("integrity", {}).get("sidecar_content_hash") != manifest["sidecar_content_hash"]:
            problems.append("sidecar content hash does not match the version manifest")
    return {"version_id": version_id, "ok": not problems, "problems": problems,
            "blobs": len(manifest.get("object_hashes") or {}) + 4}
