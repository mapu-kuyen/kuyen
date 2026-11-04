"""B3 — a version identifier must never resolve outside the canonical store.

KUYEN_SEMANTIC_SECURITY_HARDENING_04. `read_version` built `<store>/versions/<version_id>/
manifest.json` from an unvalidated string, so `../../decoy` and an absolute path both read a
manifest from outside the store. Every public read path goes through that function.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from kuyen import KuyenMemory
from kuyen.errors import StoreError
from kuyen.storage.registry import lineage
from kuyen.storage.versions import read_version, verify_version

DECOY = {"schema_name": "KUYEN_CANONICAL_VERSION", "version_id": "VER-decoydecoy01",
         "marker": "DECOY-MANIFEST-MUST-NOT-BE-READ"}


def decoy_tree(tmp_path: Path) -> Path:
    """A manifest-shaped decoy outside the store, at several distances."""
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "manifest.json").write_text(json.dumps(DECOY), encoding="utf-8")
    return outside


def assert_rejected(memory: KuyenMemory, value: str) -> None:
    with pytest.raises(StoreError):
        read_version(memory.store, value)
    with pytest.raises(StoreError):
        verify_version(memory.store, value)
    with pytest.raises(StoreError):
        lineage(memory.store, value)
    with pytest.raises(StoreError):
        memory.graph(value)
    with pytest.raises(StoreError):
        memory.sidecar(value)
    with pytest.raises(StoreError):
        memory.lineage(value)


class TestTraversal:
    def test_relative_traversal_is_rejected(self, live_memory: KuyenMemory, tmp_path: Path) -> None:
        outside = decoy_tree(tmp_path)
        relative = "../" * (len(live_memory.path.relative_to(tmp_path).parts) + 1) + "outside/manifest.json"
        for candidate in ("..", "../", "../../", "../..", ".../.../", relative,
                          str(outside), str(outside / "manifest.json")):
            assert_rejected(live_memory, candidate)

    def test_absolute_path_is_rejected(self, live_memory: KuyenMemory, tmp_path: Path) -> None:
        outside = decoy_tree(tmp_path)
        for candidate in (str(outside), "/etc", "/etc/passwd", str(outside / "manifest.json")):
            assert_rejected(live_memory, candidate)

    def test_separators_and_empty_components_are_rejected(self, live_memory: KuyenMemory) -> None:
        for candidate in ("", " ", "a/b", "a\\b", "VER-0123456789ab/", ".", "~", "VER-0123456789ab\n"):
            with pytest.raises(StoreError):
                read_version(live_memory.store, candidate)
            with pytest.raises(StoreError):
                verify_version(live_memory.store, candidate)
            with pytest.raises(StoreError):
                lineage(live_memory.store, candidate)

    def test_an_empty_value_means_current_and_never_builds_a_path(self,
                                                                 live_memory: KuyenMemory) -> None:
        """`graph("")`/`sidecar("")` fall back to CURRENT by design; no path is built."""
        current = live_memory.current().version_id
        assert live_memory.graph("") == live_memory.graph(current)
        assert live_memory.sidecar("") == live_memory.sidecar(current)

    def test_a_symlink_that_points_outside_is_rejected(self, live_memory: KuyenMemory,
                                                       tmp_path: Path) -> None:
        outside = decoy_tree(tmp_path)
        version = live_memory.current().version_id
        link = Path(live_memory.path) / "versions" / "VER-aaaaaaaaaaaa"
        link.symlink_to(outside, target_is_directory=True)

        assert_rejected(live_memory, "VER-aaaaaaaaaaaa")
        assert live_memory.current().version_id == version

    def test_a_valid_identifier_still_works(self, live_memory: KuyenMemory) -> None:
        version = live_memory.current().version_id
        assert read_version(live_memory.store, version).manifest["version_id"] == version
        assert verify_version(live_memory.store, version)["ok"] is True
        assert live_memory.graph(version)["entities"]
        assert live_memory.lineage(version)

    def test_a_well_formed_but_unknown_identifier_is_rejected(self, live_memory: KuyenMemory) -> None:
        assert_rejected(live_memory, "VER-ffffffffffff")
