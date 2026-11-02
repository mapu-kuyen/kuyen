"""The single canonical commit protocol.

Stages (the manifest publish in stage 8 is the commit point):

 1 validate incoming graph (contract + references)
 2 build the canonical companion (sidecar) and the deterministic projection record
 3 compute and verify hashes
 4 prepare the persistent objects in staging
 5 write immutable blobs into the content-addressed store
 6 verify every written blob
 7 publish the immutable version manifest        <-- COMMIT POINT (single atomic rename)
 8 index the version
 9 record the Antu outcome in the ledger
10 enqueue the pending projection (outbox)
11 confirm the version in the ledger
12 update CURRENT with compare-and-swap

Nothing before stage 7 is authoritative; everything after it is idempotent and can be
replayed by `recover_pending`, so an interruption never yields a half-accepted version
and never loses an already accepted one.
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from typing import Any

from ..lifecycle.ledger import append_event
from .store import CanonicalStore
from ..canonical import canonical_json_pretty, digest, read_json, sha256_text, write_atomic
from ..errors import CommitError, ConflictError, InjectedFailure, StoreError
from ..contracts import ANTU_PROCESSOR_VERSION, BACKUP_ADAPTER_VERSION, EXPORTER_VERSION, PROJECTOR_VERSION, RECONSTRUCTOR_VERSION, SIDECAR_SCHEMA_VERSION, STORE_ADAPTER_VERSION
from .versions import build_manifest, read_version, version_id_for, write_version
from ..projection.outbox import enqueue
from .registry import index_version, set_current
from ..sidecar import exporter as upstream_exporter
from ..projection import mapping as upstream_mapping
from ..projection import projector as upstream_projector
from .. import sidecar as upstream_sidecar

FAILPOINTS = (
    "before_write_objects", "during_write_objects", "after_write_objects", "before_manifest",
    "during_manifest_write", "after_manifest", "before_commit", "during_current_update",
    "after_commit", "before_projection_event", "after_projection_event",
)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Failpoint:
    """Deterministic interruption injector; only used against disposable store copies."""

    def __init__(self, name: str | None = None) -> None:
        self.name = name
        self.hits: list[str] = []

    def __call__(self, point: str, context: dict[str, Any] | None = None) -> None:
        if self.name is not None and point == self.name:
            self.hits.append(point)
            raise InjectedFailure(f"injected failure at {point}")


REQUIRED_DOCUMENT_KEYS = ("kuyen", "mapus", "canonical", "counts")


def adapter_versions() -> dict[str, str]:
    return {"exporter": EXPORTER_VERSION, "projector": PROJECTOR_VERSION,
            "reconstructor": RECONSTRUCTOR_VERSION, "store": STORE_ADAPTER_VERSION,
            "backup": BACKUP_ADAPTER_VERSION, "antu_processor": ANTU_PROCESSOR_VERSION}


def _validate(document: dict[str, Any]) -> dict[str, Any]:
    missing = [key for key in REQUIRED_DOCUMENT_KEYS if key not in document]
    if missing:
        raise CommitError(f"candidate document is missing {missing}")
    graph = {
        "kuyen_id": document["kuyen"]["kuyen_id"],
        "version": document["kuyen"]["version"],
        "antu_id": document["kuyen"]["antu_id"],
        "mapu_ids": document["kuyen"]["mapu_ids"],
        "schema_version": document["kuyen"]["schema_version"],
        "status": document["kuyen"]["status"],
        "entities": document["canonical"]["entities"],
        "relations": document["canonical"]["relations"],
        "assertions": document["canonical"]["assertions"],
        "evidence": document["canonical"]["evidence"],
        "coverage": document["canonical"]["coverage"],
        "provenance": document["kuyen"]["provenance"],
        "content_digest": document["kuyen"].get("content_digest"),
        "provenance_digest": document["kuyen"].get("provenance_digest"),
    }
    schema = upstream_exporter.validate_against_productive_schema(graph)
    if schema["status"] != "VALID":
        raise CommitError(f"candidate graph violates the productive schema: {schema.get('message')}")
    entity_ids = {item["entity_id"] for item in graph["entities"]}
    evidence_ids = {item["evidence_id"] for item in graph["evidence"]}
    problems = []
    for relation in graph["relations"]:
        if relation["from_entity"] not in entity_ids or relation["to_entity"] not in entity_ids:
            problems.append(f"relation {relation['relation_id']} has an unresolved endpoint")
        for reference in relation.get("evidence_ids") or []:
            if reference not in evidence_ids:
                problems.append(f"relation {relation['relation_id']} references unknown evidence {reference}")
    for assertion in graph["assertions"]:
        for reference in assertion.get("evidence_ids") or []:
            if reference not in evidence_ids:
                problems.append(f"assertion {assertion['assertion_id']} references unknown evidence {reference}")
        if assertion.get("object_entity") and assertion["object_entity"] not in entity_ids:
            problems.append(f"assertion {assertion['assertion_id']} references an unknown object entity")
    if problems:
        raise CommitError("; ".join(problems))
    return {"schema": schema, "entity_ids": len(entity_ids), "evidence_ids": len(evidence_ids)}


def _object_hashes(store: CanonicalStore, document: dict[str, Any]) -> dict[str, str]:
    """Every canonical object becomes its own content-addressed blob.

    Objects shared between versions therefore share a single physical blob while keeping
their logical identity: deduplication is measured, never assumed.
    """
    from ..canonical import canonical_json

    hashes = {}
    for group in ("entities", "relations", "assertions", "evidence", "coverage"):
        for item in document["canonical"][group]:
            identifier = item.get("entity_id") or item.get("relation_id") or item.get("assertion_id") \
                or item.get("evidence_id") or item.get("unit_id") or digest(item)[:12]
            hashes[f"{group}/{identifier}"] = store.put_blob(canonical_json(item))
    for unit in document["canonical"].get("source_units") or []:
        hashes[f"source_units/{unit['unit_id']}"] = store.put_blob(canonical_json(unit))
    return hashes


def commit_version(
    store: CanonicalStore,
    *,
    document: dict[str, Any],
    identity: dict[str, Any],
    antu_id: str,
    unit_revision: str,
    created_at: str | None = None,
    projector_version: str = PROJECTOR_VERSION,
    openviking_version: str | None,
    expected_parent_version_id: str | None,
    failpoint: Failpoint | None = None,
) -> dict[str, Any]:
    created_at = created_at or now()
    failpoint = failpoint or Failpoint()
    # the canonical document is the authority for the memory version; identity may only
    # disagree by mistake, so the document wins and the divergence is recorded
    if identity.get("kuyen_version") != document["kuyen"]["version"]:
        identity = {**identity, "kuyen_version": document["kuyen"]["version"],
                    "identity_version_override": identity.get("kuyen_version")}

    # 1 validate
    validation = _validate(document)

    # 2 canonical companion + deterministic projection record
    projector = upstream_projector.NativeProjector()
    projector.version = projector_version
    projection = projector.project(document)
    mapping = upstream_mapping.build_mapping(document, projection.manifest)
    sidecar = upstream_sidecar.build_sidecar(document, projection.manifest, mapping,
                            openviking_version=openviking_version or "",
                            contract_snapshot_sha256="", created_at=created_at)
    sidecar_check = upstream_sidecar.verify_sidecar(sidecar)
    if not sidecar_check["ok"]:
        raise CommitError(f"sidecar failed verification: {sidecar_check['problems'][:3]}")

    # 3 hashes
    canonical_graph_hash = document["kuyen"]["canonical_graph_hash"]
    sidecar_text = canonical_json_pretty(sidecar)
    mapping_text = canonical_json_pretty(mapping)
    projection_text = canonical_json_pretty(projection.manifest)
    object_hashes = _object_hashes(store, document)
    integrity = {
        "schema_name": "KUYEN_CANONICAL_VERSION_INTEGRITY",
        "schema_version": "1.0.0",
        "kuyen_id": identity["kuyen_id"], "kuyen_version": identity["kuyen_version"],
        "canonical_graph_hash": canonical_graph_hash,
        "sidecar_sha256": sha256_text(sidecar_text),
        "mapping_sha256": sha256_text(mapping_text),
        "projection_manifest_sha256": sha256_text(projection_text),
        "object_count": len(object_hashes),
        "objects": object_hashes,
    }
    integrity["integrity_id"] = digest({key: value for key, value in integrity.items() if key != "integrity_id"})

    commit_id = digest({"domain": "KUYEN_CANONICAL_COMMIT", "kuyen_id": identity["kuyen_id"],
                        "kuyen_version": identity["kuyen_version"],
                        "canonical_graph_hash": canonical_graph_hash,
                        "parent": expected_parent_version_id, "antu_id": antu_id,
                        "revision": unit_revision})[:20]
    staging = store.staging_dir / commit_id

    with store.writer_lock():
        # 4 staging intent
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(parents=True)
        write_atomic(staging / "INTENT.json", canonical_json_pretty({
            "commit_id": commit_id, "kuyen_id": identity["kuyen_id"],
            "kuyen_version": identity["kuyen_version"],
            "canonical_graph_hash": canonical_graph_hash, "parent_version_id": expected_parent_version_id,
            "antu_id": antu_id, "unit_revision": unit_revision, "created_at": created_at,
            "stages_completed": ["validate", "prepare"],
        }))

        failpoint("before_write_objects", {"commit_id": commit_id})
        # 5 write blobs
        blob_inventory = []
        failpoint("during_write_objects", {"commit_id": commit_id, "written": 0})
        sidecar_blob = store.put_blob(sidecar_text)
        blob_inventory.append(sidecar_blob)
        mapping_blob = store.put_blob(mapping_text)
        blob_inventory.append(mapping_blob)
        projection_blob = store.put_blob(projection_text)
        blob_inventory.append(projection_blob)
        integrity_blob = store.put_blob(canonical_json_pretty(integrity))
        blob_inventory.append(integrity_blob)
        native_blobs = {}
        for name, text in sorted(projection.artifacts.items()):
            native_blobs[name] = store.put_blob(text)
            blob_inventory.append(native_blobs[name])
        failpoint("after_write_objects", {"commit_id": commit_id, "blobs": len(blob_inventory)})

        # 6 verify blobs
        for content_hash in blob_inventory:
            store.get_blob(content_hash)

        # 7 publish the immutable manifest (COMMIT POINT)
        manifest = build_manifest(
            identity=identity, sidecar=sidecar, canonical_graph_hash=canonical_graph_hash,
            parent_version_id=expected_parent_version_id, antu_id=antu_id, unit_revision=unit_revision,
            mapu_revisions=[{"mapu_id": mapu["mapu_id"], "version": mapu.get("version"),
                             "sha256": mapu["content_sha256"], "source_uri": mapu["source_uri"]}
                            for mapu in document["mapus"]],
            object_hashes=object_hashes, counts=document["counts"],
            adapter_versions=adapter_versions(), created_at=created_at)
        manifest.update({"sidecar_blob": sidecar_blob, "mapping_blob": mapping_blob,
                         "projection_manifest_blob": projection_blob, "integrity_blob": integrity_blob,
                         "native_projection_blobs": native_blobs,
                         "sidecar_schema_version": SIDECAR_SCHEMA_VERSION,
                         "validation": validation, "commit_id": commit_id})
        failpoint("before_manifest", {"version_id": manifest["version_id"]})
        failpoint("before_commit", {"version_id": manifest["version_id"]})
        failpoint("during_manifest_write", {"version_id": manifest["version_id"]})
        written = write_version(store, manifest, blob_inventory=blob_inventory)
        failpoint("after_manifest", {"version_id": manifest["version_id"]})

        # 8 index (idempotent)
        index_version(store, written)

        # 9 Antu outcome in the ledger
        append_event(store, "ANTU_COMPLETED", {
            "antu_id": antu_id, "leftraru_id": identity["leftraru_id"],
            "unit_revision": unit_revision, "version_id": written["version_id"],
            "kuyen_id": written["kuyen_id"], "kuyen_version": written["kuyen_version"],
            "canonical_graph_hash": written["canonical_graph_hash"],
            "parent_version_id": written["parent_version_id"], "recorded_at": created_at,
        })

        # 10 pending projection
        failpoint("before_projection_event", {"version_id": written["version_id"]})
        operation = enqueue(store, version_id=written["version_id"], kuyen_id=written["kuyen_id"],
                            kuyen_version=written["kuyen_version"],
                            canonical_graph_hash=written["canonical_graph_hash"],
                            projector_version=projector_version, openviking_version=openviking_version,
                            created_at=created_at, antu_id=antu_id)
        append_event(store, "PROJECTION_ENQUEUED", {
            "antu_id": antu_id, "version_id": written["version_id"],
            "operation_key": operation["operation_key"], "recorded_at": created_at})
        failpoint("after_projection_event", {"operation_key": operation["operation_key"]})

        # 11 confirm
        append_event(store, "VERSION_COMMITTED", {
            "antu_id": antu_id, "version_id": written["version_id"],
            "canonical_graph_hash": written["canonical_graph_hash"], "recorded_at": created_at})
        failpoint("after_commit", {"version_id": written["version_id"]})

        # 12 CURRENT (compare-and-swap)
        pointer = set_current(store, written, expected_previous=expected_parent_version_id,
                              antu_id=antu_id, created_at=created_at, failpoint=failpoint)
        shutil.rmtree(staging, ignore_errors=True)
    return {"version": written, "pointer": pointer, "operation": operation,
            "sidecar": sidecar, "projection": projection.manifest, "mapping": mapping,
            "commit_id": commit_id}


def pending_commits(store: CanonicalStore) -> dict[str, Any]:
    """Versions that exist (manifest published) but whose post-commit bookkeeping is incomplete."""
    from ..lifecycle.ledger import events_of_type
    from ..projection.outbox import list_operations
    from .registry import index_entries

    manifests = [path.parent.name for path in store.versions_dir.glob("*/manifest.json")]
    indexed = {entry["version_id"] for entry in index_entries(store)}
    committed = {event.get("version_id") for event in events_of_type(store, "VERSION_COMMITTED")}
    enqueued = {operation["version_id"] for operation in list_operations(store)}
    current = (store.read_current() or {}).get("version_id")
    return {
        "versions": sorted(manifests),
        "missing_index": sorted(set(manifests) - indexed),
        "missing_ledger": sorted(set(manifests) - committed),
        "missing_outbox": sorted(set(manifests) - enqueued),
        "current": current,
        "incomplete": sorted(set(manifests) - indexed) + sorted(set(manifests) - committed)
                      + sorted(set(manifests) - enqueued),
        "staging": sorted(path.name for path in store.staging_dir.iterdir() if path.is_dir()),
    }


def recover_pending(store: CanonicalStore, *, created_at: str | None = None) -> dict[str, Any]:
    """Deterministically finish every published-but-unconfirmed commit; drop staging only."""
    created_at = created_at or now()
    from ..lifecycle.ledger import events_of_type
    from ..projection.outbox import list_operations
    from .registry import index_entries

    completed, discarded = [], []
    advanced = None
    with store.writer_lock():
        for path in sorted(store.staging_dir.iterdir()):
            if not path.is_dir():
                continue
            intent = path / "INTENT.json"
            version_id = None
            if intent.is_file():
                try:
                    version_id = version_id_for(read_json(intent)["identity_core"]) \
                        if "identity_core" in read_json(intent) else None
                except Exception:  # noqa: BLE001
                    version_id = None
            discarded.append({"staging": path.name, "version_id": version_id,
                              "reason": "STAGING_WITHOUT_PUBLISHED_MANIFEST" if version_id is None
                                        else "STAGING_ALREADY_PUBLISHED"})
            shutil.rmtree(path, ignore_errors=True)

        manifests = [path.parent.name for path in store.versions_dir.glob("*/manifest.json")]
        indexed = {entry["version_id"] for entry in index_entries(store)}
        committed = {event.get("version_id") for event in events_of_type(store, "VERSION_COMMITTED")}
        enqueued = {operation["version_id"] for operation in list_operations(store)}
        for version_id in manifests:
            manifest = read_version(store, version_id).manifest
            actions = []
            if version_id not in indexed:
                index_version(store, manifest)
                actions.append("indexed")
            if version_id not in committed:
                append_event(store, "VERSION_COMMITTED", {
                    "antu_id": manifest["antu_id"], "version_id": version_id,
                    "canonical_graph_hash": manifest["canonical_graph_hash"],
                    "recorded_at": created_at, "recovered": True})
                actions.append("ledger_recorded")
            if version_id not in enqueued:
                enqueue(store, version_id=version_id, kuyen_id=manifest["kuyen_id"],
                        kuyen_version=manifest["kuyen_version"],
                        canonical_graph_hash=manifest["canonical_graph_hash"],
                        projector_version=PROJECTOR_VERSION, openviking_version=None,
                        created_at=created_at, antu_id=manifest["antu_id"])
                actions.append("outbox_enqueued")
            if actions:
                completed.append({"version_id": version_id, "actions": actions})
        pointer = store.read_current()
        advanced = None
        if pointer is not None:
            manifests = [path.parent.name for path in store.versions_dir.glob("*/manifest.json")]
            tip = pointer["version_id"]
            while True:
                children = [version_id for version_id in manifests
                            if read_version(store, version_id).parent_version_id == tip]
                if len(children) != 1:
                    break
                tip = children[0]
            if tip != pointer["version_id"]:
                manifest = read_version(store, tip).manifest
                set_current(store, manifest, expected_previous=pointer["version_id"],
                            antu_id=manifest["antu_id"], created_at=created_at)
                append_event(store, "RECONCILIATION", {
                    "action": "CURRENT_ADVANCED_TO_ACCEPTED_TIP", "from": pointer["version_id"],
                    "to": tip, "recorded_at": created_at})
                advanced = {"from": pointer["version_id"], "to": tip}
    return {"completed": completed, "staging_discarded": discarded, "current_advanced": advanced,
            "pending_after": pending_commits(store)}


def verify_commit(store: CanonicalStore, version_id: str) -> dict[str, Any]:
    """Every stage of an accepted version must be verifiable from the store alone."""
    from ..lifecycle.ledger import events_of_type
    from ..projection.outbox import list_operations
    from .registry import index_entries
    from .versions import verify_version

    problems: list[str] = []
    verification = verify_version(store, version_id)
    if not verification["ok"]:
        problems.extend(verification["problems"])
    if version_id not in {entry["version_id"] for entry in index_entries(store)}:
        problems.append("version is not indexed")
    if version_id not in {event.get("version_id") for event in events_of_type(store, "VERSION_COMMITTED")}:
        problems.append("version has no VERSION_COMMITTED ledger event")
    if version_id not in {operation["version_id"] for operation in list_operations(store)}:
        problems.append("version has no outbox operation")
    pointer = store.read_current()
    if pointer and pointer.get("version_id") == version_id:
        manifest = read_version(store, version_id).manifest
        if pointer.get("canonical_graph_hash") != manifest["canonical_graph_hash"]:
            problems.append("CURRENT pointer hash mismatch")
    return {"version_id": version_id, "ok": not problems, "problems": problems,
            "blobs_verified": verification["blobs"]}
