"""Immutable canonical versions.

A version is a manifest plus content-addressed blobs. The manifest is written once and
never rewritten; `write_version` refuses to replace a different manifest and is
idempotent for an identical one. `version_id` is derived from the identity core, so two
versions with identical graph content but different lineage share physical blobs while
keeping distinct logical identities.
"""
from __future__ import annotations

import re
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .store import CanonicalStore
from ..canonical import canonical_json, digest, read_json, sha256_bytes, write_atomic
from ..errors import ImmutableViolation, StoreError

VERSION_PREFIX = "VER-"
VERSION_ID_RE = re.compile(r"^VER-[0-9a-f]{12}$")


def validate_version_id(version_id: Any) -> str:
    """Reject any identifier that is not a canonical `VER-<12 hex>` value.

    The identifier is used to build a filesystem path, so it is validated **before** any
    path exists: no separators, no relative components, no absolute path and no type other
    than `str` can reach the filesystem (KUYEN_SEMANTIC_SECURITY_HARDENING_04, B3).
    """
    if not isinstance(version_id, str):
        raise StoreError(f"version identifier must be a string, not {type(version_id).__name__}")
    if not VERSION_ID_RE.match(version_id):
        raise StoreError(f"invalid version identifier: {version_id!r}")
    return version_id


def version_manifest_path(store: CanonicalStore, version_id: Any) -> Path:
    """The manifest path of a version, proven to stay inside the canonical version root.

    The resolved path must remain under `<store>/versions`: this rejects `..`, absolute
    paths and a version directory that is a symbolic link pointing outside the store.
    """
    validate_version_id(version_id)
    root = store.versions_dir.resolve()
    path = (store.versions_dir / version_id / "manifest.json").resolve()
    if root not in path.parents:
        raise StoreError(f"version {version_id!r} resolves outside the version directory")
    return path


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
    version_id = validate_version_id(manifest["version_id"])
    target = version_manifest_path(store, version_id)
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
    path = version_manifest_path(store, version_id)
    if not path.is_file():
        raise StoreError(f"unknown version: {version_id}")
    return VersionRecord(read_json(path))


def list_versions(store: CanonicalStore) -> list[VersionRecord]:
    records = []
    for directory in sorted(p for p in store.versions_dir.iterdir() if p.is_dir()):
        manifest = directory / "manifest.json"
        if manifest.is_file():
            records.append(VersionRecord(read_json(manifest)))
    # The directory name is a content hash: it says nothing about when a version was
    # created. Order by the manifest, which is the authority (KUYEN_ANTU_SEMANTIC_
    # FIDELITY_HARDENING_14: a test assumed name order and only passed by luck).
    records.sort(key=lambda item: (str(item.manifest.get("created_at") or ""),
                                    item.version_id))
    return records


def _integrity_problems(manifest: dict[str, Any], integrity: dict[str, Any]) -> list[str]:
    """The integrity record is content-addressed, so it can vouch for the manifest fields."""
    problems: list[str] = []
    for field in ("kuyen_id", "kuyen_version", "canonical_graph_hash"):
        if integrity.get(field) != manifest.get(field):
            problems.append(f"integrity {field} disagrees with the manifest")
    objects = manifest.get("object_hashes") or {}
    if integrity.get("objects") != objects:
        problems.append("integrity object inventory disagrees with the manifest")
    if integrity.get("object_count") != len(objects):
        problems.append("integrity object count disagrees with the manifest")
    for field, reference in (("sidecar_sha256", "sidecar_blob"), ("mapping_sha256", "mapping_blob"),
                             ("projection_manifest_sha256", "projection_manifest_blob")):
        if integrity.get(field) != manifest.get(reference):
            problems.append(f"integrity {field} disagrees with {reference}")
    payload = {key: value for key, value in integrity.items() if key != "integrity_id"}
    if integrity.get("integrity_id") != digest(payload):
        problems.append("integrity_id does not match the integrity record")
    return problems


def _identity_problems(manifest: dict[str, Any]) -> list[str]:
    """`version_id` is derived from the identity core: a manifest cannot move between versions."""
    problems: list[str] = []
    core = manifest.get("identity_core")
    if not isinstance(core, dict) or not core:
        return ["manifest has no identity_core"]
    if version_id_for(core) != manifest.get("version_id"):
        problems.append("version_id does not derive from identity_core")
    for field in ("kuyen_id", "kuyen_version", "canonical_graph_hash", "parent_version_id",
                  "antu_id", "unit_revision"):
        if core.get(field) != manifest.get(field):
            problems.append(f"{field} disagrees with identity_core")
    return problems


def verify_version(store: CanonicalStore, version_id: str) -> dict[str, Any]:
    """Every artifact a version references must exist, match its hash and agree with it.

    Tamper detection is only as strong as the number of independent records that have to be
    rewritten together: the manifest is checked against its identity core (which fixes
    `version_id`), against the content-addressed integrity record (object inventory, counts
    and the other three references) and against the sidecar. A change in one file is always
    inconsistent with the others; a change that rewrites every one of them consistently is
    out of reach without an external root of trust, and `SECURITY.md` says so.
    """
    manifest = read_version(store, version_id).manifest
    problems: list[str] = _identity_problems(manifest)
    if manifest.get("version_id") != version_id:
        problems.append("manifest version_id does not match its directory")
    payloads: dict[str, bytes] = {}
    for name in ("sidecar_blob", "integrity_blob", "mapping_blob", "projection_manifest_blob"):
        blob = manifest.get(name)
        if not blob:
            problems.append(f"missing reference {name}")
            continue
        try:
            payloads[name] = store.get_blob(blob)
        except StoreError as exc:
            problems.append(f"{name}: {exc}")
    for relative, content_hash in (manifest.get("object_hashes") or {}).items():
        try:
            store.get_blob(content_hash)
        except StoreError as exc:
            problems.append(f"object {relative}: {exc}")
    if "integrity_blob" in payloads:
        try:
            integrity = json.loads(payloads["integrity_blob"].decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            problems.append(f"integrity_blob is not valid JSON: {exc}")
        else:
            problems.extend(_integrity_problems(manifest, integrity))
    if "sidecar_blob" in payloads:
        try:
            sidecar = json.loads(payloads["sidecar_blob"].decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            problems.append(f"sidecar_blob is not valid JSON: {exc}")
        else:
            if sidecar.get("canonical_graph_hash") != manifest.get("canonical_graph_hash"):
                problems.append("sidecar canonical_graph_hash does not match the version manifest")
            if (sidecar.get("integrity") or {}).get("sidecar_content_hash") != manifest.get("sidecar_content_hash"):
                problems.append("sidecar content hash does not match the version manifest")
            if sidecar.get("kuyen_id") != manifest.get("kuyen_id"):
                problems.append("sidecar kuyen_id does not match the version manifest")
            if sidecar.get("kuyen_version") != manifest.get("kuyen_version"):
                problems.append("sidecar kuyen_version does not match the version manifest")
            if (sidecar.get("object_counts") or {}) != (manifest.get("counts") or {}):
                problems.append("sidecar object counts do not match the version manifest")
    return {"version_id": version_id, "ok": not problems, "problems": problems,
            "blobs": len(manifest.get("object_hashes") or {}) + 4}
