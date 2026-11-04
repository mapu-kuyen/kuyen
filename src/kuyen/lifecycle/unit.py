"""Leftraru unit state and revision history (append-only).

The unit identity never changes; every Antu execution produces a revision record that
links the instruction, its result and the canonical version it produced (if any).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ..canonical import append_line, canonical_json, read_json, write_atomic, canonical_json_pretty
from .ledger import append_event  # no cycle: ledger does not import unit


def _state_path(store) -> Path:
    return Path(store.root) / "unit/STATE.json"


def _revisions_path(store) -> Path:
    return Path(store.root) / "unit/revisions.jsonl"


def ensure_unit(store, *, leftraru_id: str, purpose: str, created_at: str) -> dict[str, Any]:
    path = _state_path(store)
    if path.is_file():
        return read_json(path)
    state = {
        "leftraru_id": leftraru_id, "purpose": purpose, "status": "ACTIVE",
        "created_at": created_at, "current_unit_revision": None,
        "current_version_id": None, "revision_count": 0,
        "responsibilities": ["hold canonical memory", "execute Antu instructions",
                            "keep a verifiable history"],
    }
    write_atomic(path, canonical_json_pretty(state))
    return state


def read_state(store) -> dict[str, Any] | None:
    path = _state_path(store)
    return read_json(path) if path.is_file() else None


def revisions(store) -> list[dict[str, Any]]:
    path = _revisions_path(store)
    if not path.is_file():
        return []
    import json
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def next_revision(store) -> str:
    return f"R{len(revisions(store)):04d}"


def record_revision(store, *, leftraru_id: str, antu_id: str, revision: str, status: str,
                    input_version_id: str | None, output_version_id: str | None,
                    canonical_graph_hash: str | None, semantic_change: bool,
                    created_at: str, detail: dict[str, Any] | None = None) -> dict[str, Any]:
    # The revision append and the STATE.json update are one operation: the writer lock is
    # re-entrant, so this is free when the caller already holds it (M1).
    with store.writer_lock():
        return _record_revision_locked(
            store, leftraru_id=leftraru_id, antu_id=antu_id, revision=revision, status=status,
            input_version_id=input_version_id, output_version_id=output_version_id,
            canonical_graph_hash=canonical_graph_hash, semantic_change=semantic_change,
            created_at=created_at, detail=detail)


def _record_revision_locked(store, *, leftraru_id: str, antu_id: str, revision: str, status: str,
                            input_version_id: str | None, output_version_id: str | None,
                            canonical_graph_hash: str | None, semantic_change: bool,
                            created_at: str, detail: dict[str, Any] | None = None) -> dict[str, Any]:
    existing = next((item for item in revisions(store) if item["unit_revision"] == revision), None)
    if existing is not None:
        return existing
    record = {
        "schema_name": "KUYEN_UNIT_REVISION",
        "schema_version": "1.0.0",
        "leftraru_id": leftraru_id, "unit_revision": revision, "antu_id": antu_id,
        "status": status, "input_version_id": input_version_id,
        "output_version_id": output_version_id, "canonical_graph_hash": canonical_graph_hash,
        "semantic_change": semantic_change, "created_at": created_at,
        "detail": detail or {},
    }
    append_line(_revisions_path(store), canonical_json(record))
    state = read_json(_state_path(store))
    state.update({"current_unit_revision": revision, "revision_count": len(revisions(store)),
                  "current_version_id": output_version_id or state.get("current_version_id"),
                  "last_antu_id": antu_id, "updated_at": created_at})
    write_atomic(_state_path(store), canonical_json_pretty(state))
    return record


def published_versions(store) -> list[dict[str, Any]]:
    """Every published version manifest, oldest first (read-only, no side effects)."""
    manifests = []
    versions_dir = Path(store.root) / "versions"
    for path in sorted(versions_dir.glob("*/manifest.json")):
        manifests.append(read_json(path))
    manifests.sort(key=lambda item: (item.get("created_at") or "", item.get("version_id") or ""))
    return manifests


def uncovered_versions(store) -> list[dict[str, Any]]:
    """Published versions that the unit history does not record.

    A publication and its revision are two writes; a process that dies between them leaves
    a canonical version that no revision covers. That state is not an error of the data, it
    is an *incomplete operation*, and it must be visible instead of looking finished
    (KUYEN_TRANSACTION_BOUNDARY_HARDENING_03, front 3).
    """
    covered = {item.get("output_version_id") for item in revisions(store)}
    return [manifest for manifest in published_versions(store)
            if manifest.get("version_id") not in covered]


def verify_unit_history(store) -> dict[str, Any]:
    problems: list[str] = []
    history = revisions(store)
    state = read_state(store)
    if state is None:
        problems.append("unit state is missing")
    expected = [f"R{index:04d}" for index in range(len(history))]
    actual = [item["unit_revision"] for item in history]
    if actual != expected:
        problems.append(f"revision sequence is not contiguous: {actual[:5]}...")
    if state and history and state.get("current_unit_revision") != history[-1]["unit_revision"]:
        problems.append("unit state does not point at the last revision")
    for item in history:
        if item["status"] not in {"COMPLETED", "NO_SEMANTIC_CHANGE", "REJECTED", "REPLAYED"}:
            problems.append(f"revision {item['unit_revision']} has an unknown status {item['status']}")
    uncovered = uncovered_versions(store)
    for manifest in uncovered:
        problems.append(f"published version {manifest['version_id']} has no unit revision "
                        "(interrupted operation)")
    return {"ok": not problems, "problems": problems, "revisions": len(history),
            "current": (state or {}).get("current_unit_revision"),
            "unreconciled": [manifest["version_id"] for manifest in uncovered]}


def reconcile_unit_history(store, *, created_at: str | None = None) -> dict[str, Any]:
    """Record the unit revision of every published version the history does not cover.

    The revision is derived entirely from the published manifest (the canonical authority),
    never from memory of the interrupted process, and it is recorded with explicit
    provenance: `detail.recovered = True`, the origin manifest and the revision id that the
    manifest had reserved. Nothing already recorded is modified or rewritten; the new
    revision is appended and a `RECONCILIATION` event documents the repair. The operation is
    idempotent because a covered version is no longer uncovered.
    """
    recorded: list[dict[str, Any]] = []
    with store.writer_lock():
        for manifest in uncovered_versions(store):
            state = read_state(store) or {}
            revision = next_revision(store)
            entry = record_revision(
                store, leftraru_id=state.get("leftraru_id", ""), antu_id=manifest["antu_id"],
                revision=revision, status="COMPLETED",
                input_version_id=manifest.get("parent_version_id"),
                output_version_id=manifest["version_id"],
                canonical_graph_hash=manifest["canonical_graph_hash"], semantic_change=True,
                created_at=created_at or "",
                detail={"recovered": True, "reason": "PUBLISHED_VERSION_WITHOUT_REVISION",
                        "manifest_unit_revision": manifest.get("unit_revision"),
                        "assigned_unit_revision": revision,
                        "recovered_from": f"versions/{manifest['version_id']}/manifest.json",
                        "reconciled_at": created_at})
            append_event(store, "RECONCILIATION", {
                "antu_id": manifest["antu_id"], "version_id": manifest["version_id"],
                "unit_revision": entry["unit_revision"],
                "reason": "PUBLISHED_VERSION_WITHOUT_REVISION", "recorded_at": created_at})
            recorded.append({"version_id": manifest["version_id"],
                             "unit_revision": entry["unit_revision"],
                             "manifest_unit_revision": manifest.get("unit_revision")})
    return {"recorded": [item["version_id"] for item in recorded], "revisions": recorded}
