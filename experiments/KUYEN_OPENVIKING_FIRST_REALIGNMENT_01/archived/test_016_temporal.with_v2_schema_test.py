from __future__ import annotations

import kuyen as _kuyen
import unittest
from types import SimpleNamespace

from kuyen.extraction import EXTRACTION_SCHEMA_VERSION_V2, build_extraction_schema_v2, validate_strict_schema
from kuyen.models import Antu, CandidateRelation, TemporalScope
from kuyen.ontology import Ontology
from kuyen.validation.validators import TemporalValidator
from pathlib import Path


class TemporalScopeTests(unittest.TestCase):
    def test_recurrence_roundtrip_and_validation(self):
        value = TemporalScope.from_dict({
            "kind": "RECURRENCE", "expression": "cada abril", "frequency": "annual",
            "month": 4, "day": None, "start": None, "end": None, "timezone": None, "precision": "month",
        })
        self.assertEqual(value.to_dict()["kind"], "RECURRENCE")
        self.assertEqual(value.month, 4)
        graph = SimpleNamespace(
            relations=[SimpleNamespace(relation_id="r1", temporal=value, temporal_scope="cada abril")],
            assertions=[],
        )
        self.assertEqual(TemporalValidator().validate(graph, None), [])

    def test_unbounded_interval_is_rejected(self):
        value = TemporalScope(kind="INTERVAL", expression="durante el período", start="1990", end=None)
        graph = SimpleNamespace(relations=[SimpleNamespace(relation_id="r1", temporal=value, temporal_scope=None)], assertions=[])
        codes = [item.code for item in TemporalValidator().validate(graph, None)]
        self.assertIn("TEMPORAL_INTERVAL_BOUNDS_MISSING", codes)

    def test_candidate_relation_parses_temporal(self):
        item = CandidateRelation.from_dict({
            "from": "e1", "to": "e2", "relation": "located_in", "temporal_scope": "cada abril",
            "temporal": {"kind": "RECURRENCE", "expression": "cada abril", "frequency": "annual", "month": 4},
        })
        self.assertIsNotNone(item.temporal)
        self.assertEqual(item.temporal.month, 4)

    def test_v2_schema_is_strict_and_has_temporal(self):
        antu = Antu.from_dict({
            "antu_id": "ANTU-T-016", "version": "1.1.0", "purpose": "test", "author": "test",
            "scope": {"include": ["x"], "exclude": []}, "language": "es", "ontology_profile": "generic-v1",
            "entity_types": ["place", "event"], "relation_types": ["located_in"],
            "coverage_policy": "complete", "evidence_policy": "strict", "scalar_policy": "literal",
            "conflict_policy": "preserve_unresolved", "output_profile": "kuyen-native-v1",
        })
        ontology = Ontology.load(str(Path(_kuyen.__file__).resolve().parent / "config" / "ontologies" / "generic-v1.yaml"))
        schema = build_extraction_schema_v2(
            antu=antu, ontology=ontology, mapu_ids=["MAPU-T"], unit_ids=["u00", "u01"],
            source_uris=["viking://resources/t"], source_sha256="a" * 64,
            source_characters=10, sections=[{"unit_id": "u00", "section": "A", "order": 0}],
        )
        self.assertEqual(schema["properties"]["document"]["properties"]["source_sha256"]["description"], "a" * 64)
        self.assertIn("temporal", schema["properties"]["relations"]["items"]["properties"])
        self.assertEqual(validate_strict_schema(schema), [])
        self.assertEqual(EXTRACTION_SCHEMA_VERSION_V2, "kuyen-extraction-candidate-v2")


if __name__ == "__main__":
    unittest.main()
