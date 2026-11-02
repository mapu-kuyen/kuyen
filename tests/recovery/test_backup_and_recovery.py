"""Backup, restore and store-only recovery: the memory survives without OpenViking."""
from __future__ import annotations

import json

import pytest

from kuyen import KuyenMemory
from kuyen.errors import BackupError


class TestBackupRestore:
    def test_backup_and_restore_preserve_every_version(self, live_memory: KuyenMemory, tmp_path,
                                                       antu_file) -> None:
        antu, path = antu_file
        live_memory.commit(live_memory.execute_antu(antu, mapu_source=path))
        hashes = {version.version_id: version.canonical_graph_hash for version in live_memory.versions()}
        backup = live_memory.backup(tmp_path / "backup")
        assert backup["integrity_status"] == "SEALED"
        restored = KuyenMemory.restore(tmp_path / "backup", tmp_path / "restored")
        assert {v.version_id: v.canonical_graph_hash for v in restored.versions()} == hashes
        assert restored.current().version_id == live_memory.current().version_id
        assert restored.verify()["ok"] is True

    def test_restored_memory_can_keep_growing(self, live_memory: KuyenMemory, tmp_path) -> None:
        live_memory.backup(tmp_path / "b")
        restored = KuyenMemory.restore(tmp_path / "b", tmp_path / "r")
        antu = {"antu_id": "ANTU-VERIFY-9", "kind": "VERIFY_ONLY", "leftraru_id": "LR-TEST"}
        assert restored.execute_antu(antu).status == "NO_SEMANTIC_CHANGE"

    def test_a_corrupted_backup_is_refused(self, live_memory: KuyenMemory, tmp_path) -> None:
        live_memory.backup(tmp_path / "backup")
        target = next(path for path in (tmp_path / "backup" / "objects").rglob("*")
                      if path.is_file() and len(path.name) == 64)
        target.chmod(0o644)
        target.write_text("{}", encoding="utf-8")
        with pytest.raises(BackupError):
            KuyenMemory.verify_backup(tmp_path / "backup")
        with pytest.raises(BackupError):
            KuyenMemory.restore(tmp_path / "backup", tmp_path / "restored")

    def test_backup_manifest_is_versioned(self, live_memory: KuyenMemory, tmp_path) -> None:
        live_memory.backup(tmp_path / "backup")
        manifest = json.loads((tmp_path / "backup" / "BACKUP_MANIFEST.json").read_text(encoding="utf-8"))
        assert manifest["format_version"] == "1.0.0"
        assert manifest["version_count"] == 1


class TestStoreOnlyRecovery:
    def test_every_version_is_reconstructed_from_the_store(self, live_memory: KuyenMemory, tmp_path,
                                                           antu_file) -> None:
        antu, path = antu_file
        live_memory.commit(live_memory.execute_antu(antu, mapu_source=path))
        report = KuyenMemory.recover_from_store(live_memory.path, workdir=tmp_path / "recovery")
        assert report["registry"]["ok"] is True
        assert report["objects"]["ok"] is True
        assert len(report["versions"]) == 2
        for version in report["versions"]:
            assert version["reconstruction"]["accepted"] is True
            assert version["reconstruction"]["hashes_match"] is True

    def test_recovery_needs_no_projection_directory(self, live_memory: KuyenMemory, tmp_path) -> None:
        import shutil

        shutil.rmtree(live_memory.path / "projections", ignore_errors=True)
        report = KuyenMemory.recover_from_store(live_memory.path, workdir=tmp_path / "rec")
        assert report["versions"][0]["reconstruction"]["accepted"] is True

    def test_projection_is_regenerable_after_recovery(self, live_memory: KuyenMemory) -> None:
        version = live_memory.current()
        entry = live_memory.enqueue_projection(version.version_id, openviking_version="0.5.0",
                                               instance_tag="test")
        assert entry["status"] == "PENDING"
        assert live_memory.pending_projections()
