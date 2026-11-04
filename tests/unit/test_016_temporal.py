from __future__ import annotations

import kuyen as _kuyen
import unittest
from types import SimpleNamespace

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


if __name__ == "__main__":
    unittest.main()
