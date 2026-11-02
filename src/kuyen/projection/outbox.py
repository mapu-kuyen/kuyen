"""Durable outbox for projection operations.

A projection is never part of canonical acceptance. Each accepted version produces one
outbox operation keyed by (version_id, projector_version, openviking_version) so a retry
is idempotent and a re-projection with a different adapter or engine is a new operation.
"""
from __future__ import annotations

from typing import Any

from ..storage.store import CanonicalStore
from ..canonical import digest, read_json, write_atomic, canonical_json_pretty
from ..contracts import OUTBOX_FORMAT_VERSION

STATUS_PENDING = "PENDING"
STATUS_IN_PROGRESS = "IN_PROGRESS"
STATUS_DONE = "DONE"
STATUS_FAILED = "FAILED"
STATUS_SUPERSEDED = "SUPERSEDED"


def operation_key(version_id: str, projector_version: str, openviking_version: str | None,
                  instance_tag: str | None = None) -> str:
    return "proj-" + digest({"version_id": version_id, "projector_version": projector_version,
                              "openviking_version": openviking_version,
                              "instance_tag": instance_tag})[:16]


def enqueue(store: CanonicalStore, *, version_id: str, kuyen_id: str, kuyen_version: str,
            canonical_graph_hash: str, projector_version: str, openviking_version: str | None,
            created_at: str, antu_id: str, instance_tag: str | None = None) -> dict[str, Any]:
    key = operation_key(version_id, projector_version, openviking_version, instance_tag)
    path = store.outbox_dir / f"{key}.json"
    if path.is_file():
        return read_json(path)
    operation = {
        "schema_name": "KUYEN_PROJECTION_OUTBOX",
        "schema_version": OUTBOX_FORMAT_VERSION,
        "operation_key": key,
        "version_id": version_id, "kuyen_id": kuyen_id, "kuyen_version": kuyen_version,
        "canonical_graph_hash": canonical_graph_hash,
        "projector_version": projector_version,
        "openviking_version": openviking_version,
        "instance_tag": instance_tag,
        "status": STATUS_PENDING,
        "created_at": created_at, "created_by_antu": antu_id,
        "attempts": [], "projection_id": None, "last_error": None,
    }
    write_atomic(path, canonical_json_pretty(operation))
    return operation


def list_operations(store: CanonicalStore) -> list[dict[str, Any]]:
    return [read_json(path) for path in sorted(store.outbox_dir.glob("*.json"))]


def get(store: CanonicalStore, key: str) -> dict[str, Any] | None:
    path = store.outbox_dir / f"{key}.json"
    return read_json(path) if path.is_file() else None


def update(store: CanonicalStore, key: str, **changes: Any) -> dict[str, Any]:
    operation = get(store, key)
    if operation is None:
        raise KeyError(key)
    operation.update(changes)
    write_atomic(store.outbox_dir / f"{key}.json", canonical_json_pretty(operation))
    return operation


def record_attempt(store: CanonicalStore, key: str, attempt: dict[str, Any], *,
                   status: str, projection_id: str | None = None, error: str | None = None) -> dict[str, Any]:
    operation = get(store, key)
    if operation is None:
        raise KeyError(key)
    attempts = list(operation.get("attempts") or [])
    attempts.append(attempt)
    return update(store, key, attempts=attempts, status=status,
                  projection_id=projection_id if projection_id is not None else operation.get("projection_id"),
                  last_error=error)


def pending(store: CanonicalStore) -> list[dict[str, Any]]:
    return [operation for operation in list_operations(store)
            if operation["status"] in {STATUS_PENDING, STATUS_IN_PROGRESS, STATUS_FAILED}]


def stats(store: CanonicalStore) -> dict[str, int]:
    counts: dict[str, int] = {}
    for operation in list_operations(store):
        counts[operation["status"]] = counts.get(operation["status"], 0) + 1
    return dict(sorted(counts.items()))
