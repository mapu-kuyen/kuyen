"""Deterministic backup and verified restore of the canonical store.

A backup is a complete, self-describing copy of the store (content-addressed blobs,
version manifests, index, ledger, unit history, refs, outbox and projection registry)
plus a sealed manifest. Because the store is content-addressed, the copy is
deterministic; `created_at` lives outside the hashed root.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from ..storage.store import CanonicalStore
from ..canonical import canonical_json_pretty, digest, read_json, sha256_file, write_atomic
from ..errors import BackupError
from ..contracts import BACKUP_ADAPTER_VERSION, BACKUP_DOMAIN, BACKUP_FORMAT_VERSION

MANIFEST_NAME = "BACKUP_MANIFEST.json"


def _collect_files(root: Path) -> dict[str, str]:
    files = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if relative in {MANIFEST_NAME} or relative.startswith('locks/'):
            continue
        files[relative] = sha256_file(path)
    return files


def _reject_unsafe_target(store: CanonicalStore, target: Path) -> None:
    """Refuse a target whose removal would destroy the store.

    `create_backup` removes the target before copying, so a target that is the store, lives
    inside it, contains it, or resolves to it through a symbolic link would delete the
    source before any copy happens (KUYEN_PACKAGE_HARDENING_01, A3). Paths are compared
    after `resolve()`, never as text, and nothing is touched before this check passes.
    """
    root = store.root.resolve()
    resolved = target.resolve()
    if resolved == root:
        raise BackupError(f"backup target is the store itself: {target}")
    if root in resolved.parents:
        raise BackupError(f"backup target is inside the store: {target}")
    if resolved in root.parents:
        raise BackupError(f"backup target contains the store: {target}")


def create_backup(store: CanonicalStore, target: str | Path, *, created_at: str,
                  include_ledger: bool = True) -> dict[str, Any]:
    target = Path(target)
    _reject_unsafe_target(store, target)
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(store.root, target)
    if not include_ledger:
        (target / "ledger/antu.jsonl").unlink(missing_ok=True)
    versions = sorted(path.parent.name for path in (target / "versions").glob("*/manifest.json"))
    files = _collect_files(target)
    manifest = {
        "schema_name": BACKUP_DOMAIN,
        "schema_version": BACKUP_FORMAT_VERSION,
        "backup_id": None,
        "created_at": created_at,
        "method": "filesystem copy of a content-addressed store plus a sealed manifest",
        "format_version": BACKUP_FORMAT_VERSION,
        "store_format_version": store.format.get("store_format_version"),
        "backup_adapter_version": BACKUP_ADAPTER_VERSION,
        "versions": versions,
        "version_count": len(versions),
        "current_version_id": (store.read_current() or {}).get("version_id"),
        "files": files,
        "file_count": len(files),
        "ledger_included": include_ledger,
        "root_hash": digest(files),
        "integrity_status": "SEALED",
        "physical_protection": "same device as the source store: logical backup, not protection "
                               "against physical loss of the device",
        "hash_scope": "every backup file except the backup manifest itself and the lock file",
    }
    manifest["backup_id"] = "BKP-" + digest({key: value for key, value in manifest.items()
                                              if key != "backup_id"})[:16]
    write_atomic(target / MANIFEST_NAME, canonical_json_pretty(manifest))
    return manifest


def verify_backup(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    problems: list[str] = []
    manifest_path = path / MANIFEST_NAME
    if not manifest_path.is_file():
        return {"ok": False, "problems": ["backup manifest is missing"], "checked": 0}
    manifest = read_json(manifest_path)
    if manifest.get("schema_name") != BACKUP_DOMAIN:
        problems.append(f"unexpected backup schema: {manifest.get('schema_name')}")
    if manifest.get("format_version") != BACKUP_FORMAT_VERSION:
        problems.append(f"unsupported backup format: {manifest.get('format_version')}")
    observed = _collect_files(path)
    expected = manifest.get("files") or {}
    missing = sorted(set(expected) - set(observed))
    extra = sorted(set(observed) - set(expected))
    mismatched = sorted(name for name in set(expected) & set(observed) if expected[name] != observed[name])
    if missing:
        problems.append(f"missing files: {missing[:5]}")
    if extra:
        problems.append(f"undeclared files: {extra[:5]}")
    if mismatched:
        problems.append(f"files with a wrong hash: {mismatched[:5]}")
    if digest(expected) != manifest.get("root_hash"):
        problems.append("root_hash does not match the file manifest")
    recomputed_id = "BKP-" + digest({key: value for key, value in manifest.items()
                                     if key != "backup_id"})[:16]
    if recomputed_id != manifest.get("backup_id"):
        problems.append("backup_id does not match the recomputed identifier")
    for version_id in manifest.get("versions") or []:
        if not (path / "versions" / version_id / "manifest.json").is_file():
            problems.append(f"declared version {version_id} is missing from the backup")
    if not problems:
        try:
            store = CanonicalStore(path)
            from ..lifecycle.ledger import verify_chain
            from ..storage.registry import verify_registry
            from ..lifecycle.unit import verify_unit_history
            registry = verify_registry(store)
            ledger = verify_chain(store)
            unit = verify_unit_history(store)
            objects = store.verify_objects()
            for name, report in (("registry", registry), ("ledger", ledger), ("unit", unit), ("objects", objects)):
                if not report["ok"]:
                    problems.append(f"{name}: {report['problems'][:3]}")
        except Exception as exc:  # noqa: BLE001
            problems.append(f"backup cannot be opened as a canonical store: {exc}")
    return {"ok": not problems, "problems": problems, "checked": len(observed),
            "backup_id": manifest.get("backup_id"), "versions": manifest.get("version_count"),
            "root_hash": manifest.get("root_hash"), "manifest": manifest}


def _reject_unsafe_restore_target(backup_path: Path, target: Path) -> None:
    """Refuse a destination that would write into, over or through the backup itself.

    Restore copies a whole store, so the destination is validated before anything is
    created, with resolved paths: a destination that *is* the backup, that lives inside it
    or that contains it would corrupt the backup (A3 discipline, applied to restore).
    A destination that exists and is not a directory, or that is a symbolic link, is
    refused: the operation never writes through an indirection.
    """
    if target.is_symlink():
        raise BackupError(f"restore target is a symbolic link: {target}")
    source = backup_path.resolve()
    destination = target.resolve()
    if destination == source:
        raise BackupError(f"restore target is the backup itself: {target}")
    if source in destination.parents:
        raise BackupError(f"restore target is inside the backup: {target}")
    if destination in source.parents:
        raise BackupError(f"restore target contains the backup: {target}")
    if target.exists() and not target.is_dir():
        raise BackupError(f"restore target exists and is not a directory: {target}")


def _remove_children(target: Path) -> None:
    for child in target.iterdir():
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child, ignore_errors=True)
        else:
            try:
                child.unlink()
            except OSError:
                pass


def restore_backup(backup_path: str | Path, target: str | Path, *, created_at: str) -> dict[str, Any]:
    """Restore a verified backup into a new, empty or non-existent directory.

    An existing *empty* directory is a valid destination — the previous implementation
    accepted it and then handed it to `copytree`, which refuses to write into an existing
    directory (B2, KUYEN_RELEASE_CANDIDATE_05). An existing non-empty directory is refused
    with its contents left byte-for-byte intact, and a failed copy removes only what this
    operation created.
    """
    backup_path, target = Path(backup_path), Path(target)
    verification = verify_backup(backup_path)
    if not verification["ok"]:
        raise BackupError(f"refusing to restore a corrupt backup: {verification['problems'][:3]}")
    _reject_unsafe_restore_target(backup_path, target)
    existed = target.exists()
    if existed and any(target.iterdir()):
        raise BackupError(f"restore target is not empty: {target}")
    try:
        target.mkdir(parents=True, exist_ok=True)
        shutil.copytree(backup_path, target, dirs_exist_ok=True)
    except BaseException:
        if existed:
            _remove_children(target)
        else:
            shutil.rmtree(target, ignore_errors=True)
        raise
    store = CanonicalStore(target)
    from ..lifecycle.ledger import verify_chain
    from ..storage.registry import verify_registry
    from ..lifecycle.unit import verify_unit_history
    restored = {
        "restored_at": created_at,
        "backup_id": verification["backup_id"],
        "versions": sorted(path.parent.name for path in (target / "versions").glob("*/manifest.json")),
        "registry": verify_registry(store),
        "ledger": verify_chain(store),
        "unit": verify_unit_history(store),
        "objects": store.verify_objects(),
        "current": store.read_current(),
    }
    restored["ok"] = all(restored[key]["ok"] for key in ("registry", "ledger", "unit", "objects"))
    return restored
