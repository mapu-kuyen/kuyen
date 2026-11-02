"""0.1.3 ontology profiles: explicit composition, no change to generic-v1."""
from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from kuyen.errors import OntologyError
from kuyen.ontology import Ontology

import kuyen as _kuyen


def _package_root() -> Path:
    """Directory of the installed package (assets ship as package data)."""
    return Path(_kuyen.__file__).resolve().parent



ROOT = _package_root()
GENERIC = ROOT / "config/ontologies/generic-v1.yaml"
HISTORICAL = ROOT / "config/ontologies/profiles/historical-native-v1.yaml"
WINE = ROOT / "config/ontologies/profiles/wine-tourism-v1.yaml"


class OntologyProfileTests(unittest.TestCase):
    def test_generic_v1_keeps_its_scope(self):
        ontology = Ontology.load(GENERIC)
        self.assertEqual(ontology.profile, "generic-v1")
        self.assertEqual(ontology.version, "1.0.0")
        self.assertIsNone(ontology.extends)
        self.assertEqual(ontology.lineage, ("generic-v1@1.0.0",))
        self.assertTrue(ontology.has_entity_type("person"))
        self.assertFalse(ontology.has_entity_type("industry"))
        self.assertIsNone(ontology.relation("produces"))
        self.assertEqual(ontology.term_status("predicate", "coordinates"), "NATIVE_PRESERVED")
        self.assertEqual(ontology.term_status("predicate", "produces"), "UNMAPPED_NATIVE")

    def test_historical_profile_preserves_native_terms(self):
        ontology = Ontology.load(HISTORICAL)
        self.assertEqual(ontology.profile, "historical-native-v1")
        self.assertEqual(ontology.extends, "../generic-v1.yaml")
        self.assertEqual(ontology.lineage, ("generic-v1@1.0.0", "historical-native-v1@1.0.0"))
        # inherited
        self.assertTrue(ontology.has_entity_type("organization"))
        self.assertIsNotNone(ontology.relation("coordinates"))
        # native additions preserve meaning
        self.assertEqual(ontology.relation("collaborates_with").from_types, ("organization", "group"))
        self.assertIn("event", ontology.relation("operates_since").to_types)
        self.assertIn("known_native_limitations", ontology.metadata)
        self.assertEqual(ontology.metadata["evidence_policy"]["strict_acceptance"], "not_granted_by_profile")

    def test_wine_profile_adds_domain_terms_and_specializes_located_in(self):
        ontology = Ontology.load(WINE)
        self.assertEqual(ontology.profile, "wine-tourism-v1")
        for name in ("industry", "tourism", "tourism_route"):
            self.assertTrue(ontology.has_entity_type(name), name)
        self.assertEqual(ontology.relation("produces").to_types, ("product", "concept"))
        self.assertIn("tourism_route", ontology.relation("located_in").from_types)
        self.assertIsNotNone(ontology.relation("coordinates"))  # inherited

    def test_extends_cycle_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory) / "profiles"
            base.mkdir()
            (base / "a.yaml").write_text(
                "profile: a\nversion: 1.0.0\nextends: ./b.yaml\nentity_types: {}\n", encoding="utf-8"
            )
            (base / "b.yaml").write_text(
                "profile: b\nversion: 1.0.0\nextends: ./a.yaml\nentity_types: {}\n", encoding="utf-8"
            )
            with self.assertRaises(OntologyError) as ctx:
                Ontology.load(base / "a.yaml")
            self.assertIn("cycle", str(ctx.exception))

    def test_generic_v1_file_is_not_rewritten_by_profile_loading(self):
        before = hashlib.sha256(GENERIC.read_bytes()).hexdigest()
        Ontology.load(HISTORICAL)
        Ontology.load(WINE)
        after = hashlib.sha256(GENERIC.read_bytes()).hexdigest()
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
