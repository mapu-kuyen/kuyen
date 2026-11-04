"""Packaging invariants: one version source, assets as package data, clean tree."""
from __future__ import annotations

from pathlib import Path

import pytest

import kuyen


class TestVersion:
    def test_version_is_resolved_from_one_source_or_from_metadata(self) -> None:
        assert kuyen.__version__ == kuyen.resolve_version()
        assert kuyen.__version__.count(".") >= 2

    def test_engine_reports_the_same_version(self) -> None:
        from kuyen.engine import _implementation_version

        assert _implementation_version() == kuyen.__version__


class TestPackageData:
    def test_contract_schemas_ship_with_the_package(self, package_root: Path) -> None:
        assert (package_root / "schemas" / "kuyen.schema.json").is_file()
        assert (package_root / "schemas" / "evidence.schema.json").is_file()

    def test_ontology_profiles_ship_with_the_package(self, package_root: Path) -> None:
        ontologies = package_root / "config" / "ontologies"
        assert (ontologies / "generic-v1.yaml").is_file()
        assert list((ontologies / "profiles").glob("*.yaml"))

    def test_versioned_skill_ships_with_the_package(self, package_root: Path) -> None:
        assert (package_root / "skills" / "knowledge-graph" / "SKILL.md").is_file()

    def test_no_experimental_material_ships_with_the_package(self, package_root: Path) -> None:
        forbidden = {"experiments", "runs", "evidence", "reports", "fixtures"}
        present = {child.name for child in package_root.iterdir() if child.is_dir()}
        assert not (present & forbidden)
        assert not list(package_root.rglob("*.env"))
        assert not list(package_root.rglob("*.pem"))


class TestTyping:
    def test_package_declares_pep561_typing(self, package_root: Path) -> None:
        assert (package_root / "py.typed").is_file()


class TestLicence:
    CANONICAL_APACHE_2_0_SHA256 = "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30"

    def test_licence_file_is_the_unmodified_official_text(self, package_root: Path) -> None:
        import hashlib

        root_license = package_root.parents[1] / "LICENSE"
        candidate = root_license if root_license.is_file() else package_root / "LICENSE"
        data = candidate.read_bytes()
        assert hashlib.sha256(data).hexdigest() == self.CANONICAL_APACHE_2_0_SHA256, candidate
        assert data.lstrip(b"\n").startswith(b"                                 Apache License")
        assert b"Version 2.0, January 2004" in data
        assert b"APPENDIX: How to apply the Apache License to your work." in data

    def test_declared_licence_is_the_spdx_identifier(self) -> None:
        tomllib = pytest.importorskip("tomllib", reason="needs Python 3.11+ to read TOML")

        project = tomllib.loads((Path(__file__).resolve().parents[2] / "pyproject.toml").read_text()) ["project"]
        assert project["license"] == "Apache-2.0"
        assert "LICENSE" in project["license-files"]

    def test_no_placeholder_licence_remains(self, package_root: Path) -> None:
        root = Path(__file__).resolve().parents[2]
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix not in {".py", ".md", ".toml", ".json", ".yaml", ".yml"}:
                continue
            if "dist" in path.parts or "build" in path.parts:
                continue
            stale = "LicenseRef" + "-Proprietary-Pending"
            assert stale not in path.read_text(encoding="utf-8", errors="replace"), path
