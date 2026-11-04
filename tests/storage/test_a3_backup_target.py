"""A3 — backup must refuse a target that would destroy the store.

KUYEN_PACKAGE_HARDENING_01, finding A3. `create_backup` removes the target before
copying; when the target is the store, lives inside it or is an ancestor of it, the
store (or its parent) is destroyed before any copy happens. The operation must be
rejected before touching any file, and a safe target must keep working.

Every destructive case runs inside a disposable sandbox created by this test and is
verified to belong to pytest's temporary tree before the call.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import fixtures_produc as fixtures
from kuyen import KuyenMemory, build_document
from kuyen.errors import BackupError


def disposable(path: Path, tmp_path: Path) -> Path:
    """Refuse to run any destructive case outside the pytest temporary tree."""
    resolved = path.resolve()
    root = tmp_path.resolve()
    assert resolved == root or root in resolved.parents, f"{resolved} is not inside {root}"
    assert root.name.startswith("test_") or "pytest-" in str(root), root
    return resolved


def snapshot(path: Path) -> dict[str, int]:
    return {item.relative_to(path).as_posix(): item.stat().st_size
            for item in sorted(path.rglob("*")) if item.is_file()}


def make_memory(root: Path) -> KuyenMemory:
    memory = KuyenMemory.create(root, leftraru_id="LR-TEST", purpose="backup guard")
    document = build_document(fixtures.make_graph(), {fixtures.MAPU_ID: fixtures.make_mapu_text()},
                              mapu_versions={fixtures.MAPU_ID: "1.0.0"},
                              source_uris={fixtures.MAPU_ID: fixtures.SOURCE_URI})
    memory.import_canonical(document)
    assert memory.verify()["ok"] is True
    return memory


class TestDangerousTargets:
    def test_rejects_target_equal_to_the_store(self, tmp_path: Path) -> None:
        store_path = disposable(tmp_path / "store", tmp_path)
        memory = make_memory(store_path)
        before = snapshot(store_path)

        with pytest.raises(BackupError):
            memory.backup(store_path)

        assert snapshot(store_path) == before, "the store must be intact after a rejected backup"
        assert KuyenMemory.open(store_path).verify()["ok"] is True
        assert len(KuyenMemory.open(store_path).versions()) == 1

    def test_rejects_target_inside_the_store(self, tmp_path: Path) -> None:
        store_path = disposable(tmp_path / "store", tmp_path)
        memory = make_memory(store_path)
        target = disposable(store_path / "backup-inside", tmp_path)
        before = snapshot(store_path)

        with pytest.raises(BackupError):
            memory.backup(target)

        assert not target.exists(), "a rejected backup must not create anything inside the store"
        assert snapshot(store_path) == before
        assert KuyenMemory.open(store_path).verify()["ok"] is True

    def test_rejects_target_that_is_an_ancestor_of_the_store(self, tmp_path: Path) -> None:
        sandbox = disposable(tmp_path / "sandbox", tmp_path)
        sandbox.mkdir()
        store_path = disposable(sandbox / "store", tmp_path)
        memory = make_memory(store_path)
        before = snapshot(store_path)

        with pytest.raises(BackupError):
            memory.backup(sandbox)

        assert store_path.is_dir(), "the store must survive a rejected ancestor target"
        assert snapshot(store_path) == before
        assert KuyenMemory.open(store_path).verify()["ok"] is True

    def test_rejects_a_symlink_that_resolves_to_the_store(self, tmp_path: Path) -> None:
        store_path = disposable(tmp_path / "store", tmp_path)
        memory = make_memory(store_path)
        link = disposable(tmp_path / "link-to-store", tmp_path)
        link.symlink_to(store_path, target_is_directory=True)
        before = snapshot(store_path)

        with pytest.raises(BackupError):
            memory.backup(link)

        assert link.is_symlink()
        assert snapshot(store_path) == before
        assert KuyenMemory.open(store_path).verify()["ok"] is True


class TestSafeTarget:
    def test_backup_to_a_sibling_directory_still_works(self, tmp_path: Path) -> None:
        store_path = disposable(tmp_path / "store", tmp_path)
        memory = make_memory(store_path)
        target = disposable(tmp_path / "backup-safe", tmp_path)

        result = memory.backup(target)

        assert target.is_dir()
        assert result["versions"] == 1
        assert memory.verify_backup(target)["ok"] is True
        assert KuyenMemory.open(store_path).verify()["ok"] is True

    def test_repeated_backup_replaces_only_the_target(self, tmp_path: Path) -> None:
        store_path = disposable(tmp_path / "store", tmp_path)
        memory = make_memory(store_path)
        target = disposable(tmp_path / "backup-repeat", tmp_path)
        memory.backup(target)
        (target / "stale-file.txt").write_text("obsoleto", encoding="utf-8")

        memory.backup(target)

        assert not (target / "stale-file.txt").exists()
        assert memory.verify_backup(target)["ok"] is True
        assert KuyenMemory.open(store_path).verify()["ok"] is True
