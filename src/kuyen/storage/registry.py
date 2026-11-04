"""Version registry: index, lineage and the CURRENT pointer.

The index is an append-only JSONL projection of accepted version manifests; the
manifests are the authority. CURRENT is changed only by compare-and-swap.
"""
from __future__ import annotations

from typing import Any

from .store import CanonicalStore
from ..canonical import append_line, canonical_json, digest, iter_lines_reverse, read_json
from ..errors import StoreError
from .versions import VersionRecord, list_versions, read_version


def index_version(store: CanonicalStore, manifest: dict[str, Any]) -> None:
    entry = {
        "version_id": manifest["version_id"],
        "kuyen_id": manifest["kuyen_id"],
        "kuyen_version": manifest["kuyen_version"],
        "canonical_graph_hash": manifest["canonical_graph_hash"],
        "parent_version_id": manifest.get("parent_version_id"),
        "antu_id": manifest["antu_id"],
        "unit_revision": manifest["unit_revision"],
        "created_at": manifest["created_at"],
        "mapu_revisions": manifest.get("mapu_revisions") or [],
    }
    # idempotent: a re-indexed version is the newest entry of a real store (the commit path
    # and `recover_pending` both re-index the tip), so the lookup walks the file from its
    # end and stops at the first match. The whole file is only read when the version is not
    # indexed at all — the case that has to append anyway (KUYEN_RELEASE_CANDIDATE_05, M6).
    for line in iter_lines_reverse(store.index_path):
        if read_json_string(line).get("version_id") == entry["version_id"]:
            return
    append_line(store.index_path, canonical_json(entry))


def read_json_string(line: str) -> Any:
    import json
    return json.loads(line)


def index_entries(store: CanonicalStore) -> list[dict[str, Any]]:
    if not store.index_path.is_file():
        return []
    return [read_json_string(line) for line in store.index_path.read_text(encoding="utf-8").splitlines() if line.strip()]


def lookup(store: CanonicalStore, version_id: str) -> dict[str, Any] | None:
    return next((entry for entry in index_entries(store) if entry["version_id"] == version_id), None)


def current(store: CanonicalStore) -> dict[str, Any] | None:
    return store.read_current()


def current_version(store: CanonicalStore) -> VersionRecord | None:
    pointer = current(store)
    return read_version(store, pointer["version_id"]) if pointer else None


def set_current(store: CanonicalStore, manifest: dict[str, Any], *, expected_previous: str | None,
                antu_id: str, created_at: str, failpoint=None) -> dict[str, Any]:
    pointer = {
        "version_id": manifest["version_id"],
        "kuyen_id": manifest["kuyen_id"],
        "kuyen_version": manifest["kuyen_version"],
        "canonical_graph_hash": manifest["canonical_graph_hash"],
        "updated_by_antu": antu_id,
        "updated_at": created_at,
        "pointer_generation": (store.read_current() or {}).get("pointer_generation", 0) + 1,
    }
    return store.write_current(pointer, expected_previous_version_id=expected_previous, failpoint=failpoint)


def lineage(store: CanonicalStore, version_id: str) -> list[dict[str, Any]]:
    chain, seen = [], set()
    cursor = read_version(store, version_id)
    while cursor is not None:
        chain.append(cursor.to_dict())
        parent = cursor.parent_version_id
        if not parent or parent in seen:
            break
        seen.add(parent)
        try:
            cursor = read_version(store, parent)
        except StoreError:  # unknown or malformed parent: the chain ends here
            cursor = None
    return list(reversed(chain))


def children(store: CanonicalStore, version_id: str) -> list[str]:
    return sorted(record.version_id for record in list_versions(store) if record.parent_version_id == version_id)


def by_antu(store: CanonicalStore, antu_id: str) -> list[str]:
    return sorted(record.version_id for record in list_versions(store) if record.manifest["antu_id"] == antu_id)


def verify_registry(store: CanonicalStore) -> dict[str, Any]:
    """Index and manifests must agree; CURRENT must point at a complete, verified version."""
    problems: list[str] = []
    manifests = {record.version_id: record for record in list_versions(store)}
    entries = {entry["version_id"]: entry for entry in index_entries(store)}
    for version_id, record in manifests.items():
        entry = entries.get(version_id)
        if entry is None:
            problems.append(f"version {version_id} is not indexed")
            continue
        if entry["canonical_graph_hash"] != record.canonical_graph_hash:
            problems.append(f"index hash mismatch for {version_id}")
    for version_id in entries:
        if version_id not in manifests:
            problems.append(f"index references a missing version {version_id}")
    for record in manifests.values():
        parent = record.parent_version_id
        if parent and parent not in manifests:
            problems.append(f"version {record.version_id} references a missing parent {parent}")
    pointer = store.read_current()
    if pointer is None:
        # A memory that has never committed has nothing to point at; that is a valid
        # empty state, not a defect. Anything committed without CURRENT is a defect.
        if manifests:
            problems.append("CURRENT pointer is missing")
    elif pointer["version_id"] not in manifests:
        problems.append("CURRENT pointer references a missing version")
    elif (manifests[pointer["version_id"]].canonical_graph_hash != pointer["canonical_graph_hash"]):
        problems.append("CURRENT pointer hash does not match its version manifest")
    return {"ok": not problems, "problems": problems, "versions": len(manifests),
            "indexed": len(entries), "current": (pointer or {}).get("version_id")}
