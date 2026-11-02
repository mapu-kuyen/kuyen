"""0.1.8 generalization path: predicate preservation and scalar text fallback."""
from __future__ import annotations

import unittest
from pathlib import Path

from kuyen.extraction import extraction_to_provider_result
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

    def test_non_numeric_quantity_text_is_preserved_as_string(self):
        candidate = {
            "entities": [{"source_ref": "e1", "source_entity_id": "e1", "entity_type": "place", "name": "Chile", "evidence_refs": ["ev"]}],
            "relations": [], "coverage": {"units_used": ["u00"]},
            "assertions": [{
                "assertion_ref": "a1", "subject_ref": "e1", "predicate": "has_value",
                "object_ref": None, "value": {"value_type": "quantity", "text_value": "2 millones de toneladas", "number_value": None},
                "polarity": "POSITIVE", "temporal_scope": None, "epistemic_status": "UNRESOLVED",
                "evidence_refs": ["ev"],
            }],
            "evidence": [{"evidence_ref": "ev", "quote": "Chile", "source_uri": "viking://x", "mapu_id": "MAPU-X"}],
        }
        result = extraction_to_provider_result(candidate, source_uri="viking://x", mapu_id="MAPU-X")
        self.assertEqual(result["assertions"][0]["value"]["value_type"], "string")
        self.assertEqual(result["assertions"][0]["value"]["value"], "2 millones de toneladas")


if __name__ == "__main__":
    unittest.main()
