"""0.1.9 packaging: single-source version and no silent fallback.

Regression cover for the G11 defect: an installed KÜYEN 0.1.9 reported ``0.1.2``
because ``_implementation_version`` could not find ``VERSION`` outside the source
tree and fell back to a hardcoded literal. These tests pin the invariants:

* the declared version, ``kuyen.__version__`` and the engine version agree;
* the version materially affects the deterministic request-key provenance;
* the resolver fails loudly instead of guessing when nothing is available.
"""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from kuyen._version import resolve_version, version_source
from kuyen.canonical import request_key as make_request_key
from kuyen.engine import _implementation_version

import kuyen as _kuyen


def _package_root() -> Path:
    """Directory of the installed package (assets ship as package data)."""
    return Path(_kuyen.__file__).resolve().parent



ROOT = _package_root()
EXPECTED = _kuyen.__version__


class VersionSingleSourceTest(unittest.TestCase):
    def test_version_file_matches_package_version(self) -> None:
        import kuyen

        self.assertEqual(kuyen.__version__, EXPECTED)

    def test_engine_version_matches_declared_version(self) -> None:
        self.assertEqual(_implementation_version(), EXPECTED)
        self.assertEqual(resolve_version(), EXPECTED)

    def test_version_source_is_explicit(self) -> None:
        # Running from the checkout must report the source-tree mechanism, never a
        # guess.
        self.assertIn(version_source(), {"source_tree_version_file", "distribution_metadata"})

    def test_no_hardcoded_012_fallback_remains(self) -> None:
        source = (ROOT / "engine.py").read_text(encoding="utf-8")
        self.assertNotIn('return "0.1.2"', source)
        self.assertNotIn("0.1.2", source)


class VersionProvenanceTest(unittest.TestCase):
    def _key(self, version: str) -> str:
        return make_request_key(
            antu={"antu_id": "probe"},
            mapus=[],
            implementation_version=version,
            ontology_version="generic-v1",
            skill_sha256="0" * 64,
            openviking_version="0.5.2.1",
            actor={},
        )

    def test_provenance_uses_declared_version(self) -> None:
        self.assertEqual(self._key(EXPECTED), self._key(_implementation_version()))

    def test_stale_version_changes_provenance(self) -> None:
        self.assertNotEqual(self._key(EXPECTED), self._key("0.1.2"))


class VersionResolverFailureTest(unittest.TestCase):
    def test_resolver_raises_instead_of_guessing(self) -> None:
        with mock.patch("kuyen._version.version_file_path", return_value=Path("/nonexistent/VERSION")):
            with mock.patch("importlib.metadata.version", side_effect=__import__(
                "importlib.metadata", fromlist=["PackageNotFoundError"]
            ).PackageNotFoundError("kuyen")):
                with self.assertRaises(RuntimeError):
                    resolve_version()


if __name__ == "__main__":
    unittest.main()
