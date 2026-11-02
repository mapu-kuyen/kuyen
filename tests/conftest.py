"""Shared fixtures for the KUYEN product suite.

The suite protects the *public* contracts of the installed package: every fixture
opens a real canonical memory on disk and goes through the product API only.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

import kuyen as _kuyen
from kuyen import KuyenMemory, build_document

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fixtures_produc as fixtures  # noqa: E402  (fixture builder of this suite)


@pytest.fixture()
def memory(tmp_path: Path) -> KuyenMemory:
    """An empty canonical memory owned by a Leftraru unit."""
    return KuyenMemory.create(tmp_path / "memory", leftraru_id="LR-TEST", purpose="pytest")


@pytest.fixture()
def document() -> dict:
    return build_document(fixtures.make_graph(), {fixtures.MAPU_ID: fixtures.make_mapu_text()},
                          mapu_versions={fixtures.MAPU_ID: "1.0.0"},
                          source_uris={fixtures.MAPU_ID: fixtures.SOURCE_URI})


@pytest.fixture()
def live_memory(tmp_path: Path, document: dict) -> KuyenMemory:
    """A memory with one accepted version already committed."""
    memory = KuyenMemory.create(tmp_path / "live", leftraru_id="LR-TEST")
    memory.import_canonical(document)
    return memory


@pytest.fixture()
def antu_file(tmp_path: Path, live_memory: KuyenMemory) -> tuple[dict, Path]:
    """A deterministic Antu plus the MAPU file it declares."""
    antu = fixtures.make_antu(base_version_id=live_memory.current().version_id)
    path = tmp_path / "MAPU-TEST-02.txt"
    path.write_text(antu["mapu_text"], encoding="utf-8")
    return antu, path


@pytest.fixture(scope="session")
def package_root() -> Path:
    return Path(_kuyen.__file__).resolve().parent
