"""Deterministic reconciliation between canonical memory, registry and projections."""
from __future__ import annotations

from typing import Any

from ..storage.store import CanonicalStore
from ..canonical import sha256_text
from ..storage.commit import pending_commits
from ..contracts import PROJECTOR_VERSION
from ..storage.versions import list_versions
from .outbox import STATUS_DONE, STATUS_FAILED, STATUS_IN_PROGRESS, STATUS_PENDING, list_operations
from .native import list_projections

CANONICAL_PENDING = "CANONICAL_PENDING"
CANONICAL_COMMITTED = "CANONICAL_COMMITTED"
PROJECTION_PENDING = "PROJECTION_PENDING"
PROJECTION_IN_PROGRESS = "PROJECTION_IN_PROGRESS"
PROJECTION_CURRENT = "PROJECTION_CURRENT"
PROJECTION_STALE = "PROJECTION_STALE"
PROJECTION_FAILED = "PROJECTION_FAILED"
PROJECTION_CORRUPT = "PROJECTION_CORRUPT"
PROJECTION_PARTIAL = "PROJECTION_PARTIAL"
PROJECTION_DUPLICATE = "PROJECTION_DUPLICATE"
PROJECTION_MISSING = "PROJECTION_MISSING"
RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"
RECOVERY_REQUIRED = "RECOVERY_REQUIRED"


def projection_state(entry: dict[str, Any], *, current_version_id: str, current_hash: str,
                     client=None) -> tuple[str, list[str]]:
    notes: list[str] = []
    if entry["version_id"] != current_version_id:
        return PROJECTION_STALE, [f"projection targets {entry['version_id']}, current is {current_version_id}"]
    if entry["canonical_graph_hash"] != current_hash:
        return PROJECTION_CORRUPT, ["projection canonical hash does not match the current canonical hash"]
    if client is not None:
        missing, mismatched = [], []
        for name, expected in (entry.get("file_hashes") or {}).items():
            response = client.read(f"{entry['uri_root']}/{name}")
            if not response.ok or not isinstance(response.result, str):
                missing.append(name)
            elif sha256_text(response.result) != expected:
                mismatched.append(name)
        if missing:
            return PROJECTION_PARTIAL, [f"missing projected files: {missing[:3]}"]
        if mismatched:
            return PROJECTION_CORRUPT, [f"projected files changed: {mismatched[:3]}"]
        notes.append("projected files verified byte-exactly against the registry")
    return PROJECTION_CURRENT, notes


def reconcile(store: CanonicalStore, *, client=None, projector_version: str = PROJECTOR_VERSION,
              openviking_version: str | None = None) -> dict[str, Any]:
    pointer = store.read_current()
    current_version_id = (pointer or {}).get("version_id")
    current_hash = (pointer or {}).get("canonical_graph_hash")
    versions = list_versions(store)
    projections = list_projections(store)
    operations = list_operations(store)
    pending = pending_commits(store)

    rows = []
    for record in versions:
        version_id = record.version_id
        related = [entry for entry in projections if entry["version_id"] == version_id]
        related_operations = [operation for operation in operations if operation["version_id"] == version_id]
        states: list[str] = [CANONICAL_COMMITTED]
        actions: list[str] = []
        notes: list[str] = []
        same_projector = [entry for entry in related if entry["projector_version"] == projector_version]
        by_instance: dict[Any, list[dict[str, Any]]] = {}
        for entry in same_projector:
            by_instance.setdefault(entry.get("instance_tag"), []).append(entry)
        duplicates = {tag: entries for tag, entries in by_instance.items() if len(entries) > 1}
        if duplicates:
            states.append(PROJECTION_DUPLICATE)
            notes.append(f"duplicate projections for instance tag(s) {sorted(map(str, duplicates))}")
            actions.append("DEDUPLICATE")
        matching = sorted(same_projector, key=lambda entry: (entry.get("created_at") or "", entry["projection_id"]))
        if len(by_instance) > 1:
            notes.append(f"{len(by_instance)} projection instances exist; the newest is effective")
        if matching:
            state, detail = projection_state(matching[-1], current_version_id=current_version_id or "",
                                             current_hash=current_hash or "", client=client)
            states.append(state)
            notes.extend(detail)
            if state in {PROJECTION_STALE, PROJECTION_CORRUPT, PROJECTION_PARTIAL}:
                actions.append("REPROJECT")
        else:
            pending_operations = [op for op in related_operations if op["status"] in {STATUS_PENDING, STATUS_IN_PROGRESS}]
            failed = [op for op in related_operations if op["status"] == STATUS_FAILED]
            if failed:
                states.append(PROJECTION_FAILED)
                actions.append("RETRY")
            elif pending_operations:
                states.append(PROJECTION_IN_PROGRESS if any(op["status"] == STATUS_IN_PROGRESS for op in pending_operations)
                              else PROJECTION_PENDING)
                actions.append("PROJECT")
            else:
                states.append(PROJECTION_MISSING)
                actions.append("ENQUEUE")
        rows.append({"version_id": version_id, "kuyen_version": record.manifest["kuyen_version"],
                     "canonical_graph_hash": record.canonical_graph_hash,
                     "is_current": version_id == current_version_id,
                     "states": states, "actions": sorted(set(actions)), "notes": notes,
                     "projections": [entry["projection_id"] for entry in related],
                     "outbox": [{"key": operation["operation_key"], "status": operation["status"]}
                                for operation in related_operations]})

    needs_reconciliation = any(row["actions"] for row in rows) or bool(pending["staging"])
    states_summary: dict[str, int] = {}
    for row in rows:
        for state in row["states"]:
            states_summary[state] = states_summary.get(state, 0) + 1
    return {
        "current": pointer,
        "versions": len(versions),
        "rows": rows,
        "states": dict(sorted(states_summary.items())),
        "pending_commits": pending,
        "recovery_required": bool(pending["missing_index"] or pending["missing_ledger"] or pending["missing_outbox"]),
        "reconciliation_required": needs_reconciliation,
        "openviking_consulted": client is not None,
        "openviking_version": openviking_version,
    }
