"""Canonical storage: content addressing, immutability, verification, single writer."""
from __future__ import annotations

import json

import pytest

from kuyen import KuyenMemory
from kuyen.errors import StoreError


def _blob_count(memory: KuyenMemory) -> int:
    return sum(1 for path in memory.path.glob("objects/sha256/*/*") if path.is_file())


class TestContentAddressing:
    def test_identical_content_is_stored_once(self, live_memory: KuyenMemory, document: dict) -> None:
        before = {path.name for path in live_memory.path.glob("objects/sha256/*/*") if path.is_file()}
        live_memory.import_canonical(document, antu_id="ANTU-IMPORT-2")
        after = {path.name for path in live_memory.path.glob("objects/sha256/*/*") if path.is_file()}
        assert before <= after, "re-committing identical content must reuse every existing object"
        assert len(after - before) <= 4, "only the new version's own artifacts may be added"
        assert len(live_memory.versions()) == 2

    def test_blob_names_are_their_hashes(self, live_memory: KuyenMemory) -> None:
        import hashlib

        for path in live_memory.path.glob("objects/sha256/*/*"):
            if path.is_file():
                assert hashlib.sha256(path.read_bytes()).hexdigest() == path.name

    def test_objects_are_read_only(self, live_memory: KuyenMemory) -> None:
        modes = {oct(path.stat().st_mode & 0o777) for path in live_memory.path.glob("objects/sha256/*/*")
                 if path.is_file()}
        assert modes == {"0o444"}


class TestImmutability:
    def test_a_second_commit_never_overwrites_an_accepted_version(self, live_memory: KuyenMemory,
                                                                  antu_file) -> None:
        antu, path = antu_file
        first = live_memory.current().version_id
        live_memory.commit(live_memory.execute_antu(antu, mapu_source=path))
        assert first in {version.version_id for version in live_memory.versions()}
        assert live_memory.graph(first)["relations"][0]["relation_id"]

    def test_a_tampered_manifest_is_detected(self, live_memory: KuyenMemory) -> None:
        manifest_path = live_memory.path / "versions" / live_memory.current().version_id / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["canonical_graph_hash"] = "0" * 64
        manifest_path.chmod(0o644)
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        report = live_memory.verify()
        assert report["ok"] is False
        assert any("manifest" in problem.lower() or "version" in problem.lower()
                   for problem in report["problems"])

    def test_a_tampered_blob_is_detected(self, live_memory: KuyenMemory) -> None:
        blob = next(path for path in live_memory.path.glob("objects/sha256/*/*") if path.is_file())
        blob.chmod(0o644)
        blob.write_text("tampered", encoding="utf-8")
        report = live_memory.verify()
        assert report["ok"] is False
        assert any("HASH_MISMATCH" in problem for problem in report["problems"])


class TestCommitProtocol:
    def test_current_only_moves_on_commit(self, live_memory: KuyenMemory, antu_file) -> None:
        antu, path = antu_file
        before = live_memory.current().version_id
        live_memory.execute_antu(antu, mapu_source=path)
        assert live_memory.current().version_id == before

    def test_a_clean_store_has_no_pending_commit(self, live_memory: KuyenMemory) -> None:
        pending = live_memory.pending()
        assert pending["incomplete"] == []
        assert live_memory.recover()["completed"] == []

    def test_opening_a_non_store_fails_closed(self, tmp_path) -> None:
        (tmp_path / "not-a-store").mkdir()
        with pytest.raises(StoreError):
            KuyenMemory.open(tmp_path / "not-a-store")

    def test_two_versions_keep_separate_lineage(self, live_memory: KuyenMemory, antu_file) -> None:
        antu, path = antu_file
        live_memory.commit(live_memory.execute_antu(antu, mapu_source=path))
        lineage = live_memory.lineage()
        assert len(lineage) == 2
        assert lineage[-1].parent_version_id == lineage[0].version_id
