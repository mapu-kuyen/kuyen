"""0.1.8 generalization path: predicate preservation and scalar text fallback."""
from __future__ import annotations

import unittest
from pathlib import Path

from kuyen.models import CandidateBundle, CandidateEntity, CandidateRelation
from kuyen.ontology import Ontology
from kuyen.semantics import preserve_incompatible_relations

import kuyen as _kuyen


def _package_root() -> Path:
    """Directory of the installed package (assets ship as package data)."""
    return Path(_kuyen.__file__).resolve().parent



ROOT = _package_root()


class GeneralizationTests(unittest.TestCase):
    def test_direction_incompatible_predicate_is_preserved_not_rewritten(self):
        ontology = Ontology.load(ROOT / "config/ontologies/generic-v1.yaml")
        bundle = CandidateBundle(
            entities=[
                CandidateEntity(id="e1", name="Organization", entity_type="organization"),
                CandidateEntity(id="e2", name="Idea", entity_type="concept"),
            ],
            relations=[
                CandidateRelation(from_entity="e1", relation="supports", to_entity="e2", label="respalda"),
            ],
        )
        result = preserve_incompatible_relations(bundle, ontology)
        relation = bundle.relations[0]
        self.assertEqual(result["direction_incompatible_preserved"], 1)
        self.assertEqual(relation.canonical_predicate, "supports")
        self.assertEqual(relation.provider_predicate, "related_to")
        self.assertEqual(relation.mapping_status, "UNMAPPED")
        self.assertEqual(relation.provider_projection_status, "LOSSY_PROJECTION")


if __name__ == "__main__":
    unittest.main()
