"""B2 — restore into an existing empty directory, and never into anything else.

Audited defect (KUYEN_RELEASE_CANDIDATE_05, B2): `restore_backup` accepted an existing
*empty* destination in its own validation and then passed it to `shutil.copytree`, which
refuses to write into an existing directory, so the documented case failed while the store
was already open for writing.

Contract:
  * a non-existent destination is created;
  * an existing *empty* destination is used;
  * an existing non-empty destination is refused and left byte-for-byte intact;
  * a destination that is a file, a symbolic link, the backup, inside the backup or
    containing the backup is refused before anything is touched;
  * a failed copy leaves no half store behind;
  * the restored store verifies, accepts new writes, and the backup stays intact.
"""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import pytest

from kuyen import KuyenMemory
from kuyen.backup.archive import restore_backup
from kuyen.errors import BackupError

STAMP = "2026-11-02T00:00:00+00:00"


def snapshot(root) -> dict[str, str]:
    root = Path(root)
    return {path.relative_to(root).as_posix(): sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob("*")) if path.is_file()}


@pytest.fixture()
def backup(live_memory: KuyenMemory, tmp_path) -> Path:
    path = tmp_path / "backup"
    live_memory.backup(path)
    return path


class TestAcceptedDestinations:
    def test_a_missing_directory_is_created(self, backup: Path, tmp_path) -> None:
        target = tmp_path / "restored" / "store"

        outcome = restore_backup(backup, target, created_at=STAMP)

        assert outcome["ok"] is True
        assert (target / "versions").is_dir()
        assert (target / "FORMAT.json").is_file()

    def test_an_existing_empty_directory_is_used(self, backup: Path, tmp_path) -> None:
        target = tmp_path / "empty"
        target.mkdir()
        assert list(target.iterdir()) == []

        outcome = restore_backup(backup, target, created_at=STAMP)

        assert outcome["ok"] is True
        assert outcome["registry"]["ok"] is True
        assert outcome["ledger"]["ok"] is True
        assert outcome["objects"]["ok"] is True
        assert outcome["versions"]
        assert (target / "versions").is_dir()

    def test_the_restored_store_verifies_and_accepts_new_writes(
            self, backup: Path, tmp_path, document: dict) -> None:
        target = tmp_path / "restored-live"
        target.mkdir()
        restore_backup(backup, target, created_at=STAMP)

        restored = KuyenMemory.open(target)
        assert restored.verify()["ok"] is True
        before = len(restored.versions())

        commit = restored.import_canonical(document)

        assert commit.version.parent_version_id is not None
        assert len(restored.versions()) == before + 1
        assert restored.verify()["ok"] is True


class TestRejectedDestinations:
    def test_a_non_empty_directory_is_refused_and_left_intact(self, backup: Path,
                                                              tmp_path) -> None:
        target = tmp_path / "occupied"
        (target / "sub").mkdir(parents=True)
        (target / "decoy.txt").write_text("do not touch", encoding="utf-8")
        (target / "sub" / "other.bin").write_bytes(b"\x00\x01\x02")
        before = snapshot(target)

        with pytest.raises(BackupError, match="not empty"):
            restore_backup(backup, target, created_at=STAMP)

        assert snapshot(target) == before

    def test_a_file_destination_is_refused(self, backup: Path, tmp_path) -> None:
        target = tmp_path / "a-file"
        target.write_text("keep", encoding="utf-8")

        with pytest.raises(BackupError, match="not a directory"):
            restore_backup(backup, target, created_at=STAMP)

        assert target.read_text(encoding="utf-8") == "keep"

    def test_a_symbolic_link_destination_is_refused(self, backup: Path, tmp_path) -> None:
        real = tmp_path / "real-empty"
        real.mkdir()
        link = tmp_path / "link"
        link.symlink_to(real, target_is_directory=True)

        with pytest.raises(BackupError, match="symbolic link"):
            restore_backup(backup, link, created_at=STAMP)

        assert list(real.iterdir()) == []

    def test_the_backup_itself_is_refused(self, backup: Path) -> None:
        before = snapshot(backup)
        with pytest.raises(BackupError, match="backup itself"):
            restore_backup(backup, backup, created_at=STAMP)
        assert snapshot(backup) == before

    def test_a_destination_inside_the_backup_is_refused(self, backup: Path) -> None:
        before = snapshot(backup)
        with pytest.raises(BackupError, match="inside the backup"):
            restore_backup(backup, backup / "objects", created_at=STAMP)
        assert snapshot(backup) == before

    def test_a_destination_that_contains_the_backup_is_refused(self, backup: Path) -> None:
        before = snapshot(backup)
        with pytest.raises(BackupError, match="contains the backup"):
            restore_backup(backup, backup.parent, created_at=STAMP)
        assert snapshot(backup) == before


class TestRepetitionAndPreservation:
    def test_restoring_twice_is_refused_and_the_first_restore_survives(
            self, backup: Path, tmp_path) -> None:
        target = tmp_path / "twice"
        target.mkdir()
        restore_backup(backup, target, created_at=STAMP)
        after_first = snapshot(target)

        with pytest.raises(BackupError, match="not empty"):
            restore_backup(backup, target, created_at=STAMP)

        assert snapshot(target) == after_first
        assert KuyenMemory.open(target).verify()["ok"] is True

    def test_the_backup_is_byte_identical_after_a_restore(self, backup: Path, tmp_path) -> None:
        before = snapshot(backup)
        target = tmp_path / "preserve"
        target.mkdir()

        restore_backup(backup, target, created_at=STAMP)

        assert snapshot(backup) == before
        assert backup.is_dir()

    def test_api_restore_returns_a_usable_memory(self, backup: Path, tmp_path) -> None:
        target = tmp_path / "api"
        target.mkdir()

        memory = KuyenMemory.restore(backup, target)

        assert memory.verify()["ok"] is True
        assert memory.current() is not None
