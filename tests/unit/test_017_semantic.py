"""0.1.7 semantic integrity: predicates, identities, support and read-only querying."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from kuyen.query import GraphQuery
from kuyen.semantics import (
    ClaimSupportStatus,
    DeterministicClaimSupportEvaluator,
    EvidenceIntegrityStatus,
    IdentityResolutionPolicy,
    IdentityStatus,
    PredicateMappingRegistry,
    ResolutionStatus,
    build_identity_groups,
    classify_identity,
)
from kuyen.semantics.identity import IdentityCandidate


class PredicateMappingTests(unittest.TestCase):
    def test_unmapped_predicate_keeps_its_name_and_has_lossy_projection(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rules.json"
            path.write_text(json.dumps({
                "contract": "test",
                "rules": [{
                    "rule_id": "r1", "version": "1.0.0", "source_predicate": "created_by",
                    "canonical_predicate": "created_by", "provider_predicate": "related_to",
                    "mapping_status": "UNMAPPED", "provider_projection_status": "LOSSY_PROJECTION",
                    "conditions": {"source_relation_ref": "u04_r1"},
                }],
            }), encoding="utf-8")
            registry = PredicateMappingRegistry.load(path)
            rule = registry.find(source_predicate="created_by", source_relation_ref="u04_r1")
            self.assertEqual(rule.canonical_predicate, "created_by")
            self.assertEqual(rule.provider_predicate, "related_to")
            self.assertEqual(rule.mapping_status, "UNMAPPED")
            self.assertEqual(rule.provider_projection_status, "LOSSY_PROJECTION")


class IdentityTests(unittest.TestCase):
    def _candidate(self, entity_id, name, source_id, external=None, aliases=None):
        return IdentityCandidate(
            candidate_id="c-" + entity_id, entity_id=entity_id, entity_type="place",
            name=name, normalized_name=name.casefold(), namespace="provider",
            source_entity_id=source_id, aliases=aliases or [], external_id=external,
        )

    def test_same_name_does_not_confirm_identity(self):
        left = self._candidate("e1", "Chile", "s1")
        right = self._candidate("e2", "Chile", "s2")
        status, resolution, _ = classify_identity(left, right)
        self.assertEqual(status, IdentityStatus.POSSIBLE_DUPLICATE)
        self.assertEqual(resolution, ResolutionStatus.UNRESOLVED)

    def test_external_identifier_can_confirm_same_entity(self):
        left = self._candidate("e1", "Chile", "s1", external="Q298")
        right = self._candidate("e2", "Chile", "s2", external="Q298")
        status, resolution, _ = classify_identity(left, right)
        self.assertEqual(status, IdentityStatus.SAME_STABLE_ID)
        self.assertEqual(resolution, ResolutionStatus.CONFIRMED_SAME_ENTITY)

    def test_groups_never_merge_records(self):
        entities = [
            {"entity_id": "e1", "name": "Aconcagua", "entity_type": "place", "source_entity_id": "s1", "evidence_ids": []},
            {"entity_id": "e2", "name": "Aconcagua", "entity_type": "place", "source_entity_id": "s2", "evidence_ids": []},
        ]
        groups = build_identity_groups(entities, policy=IdentityResolutionPolicy())
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].automatic_merges, 0)
        self.assertEqual(len(groups[0].candidates), 2)


class ClaimSupportTests(unittest.TestCase):
    def test_exact_quote_is_not_semantic_support(self):
        source = "Chile produce vino."
        evidence = {
            "ev1": {
                "evidence_id": "ev1", "mapu_id": "MAPU-X", "source_uri": "viking://x",
                "source_sha256": __import__("hashlib").sha256(source.encode()).hexdigest(),
                "quote": "Chile produce vino", "char_start": 0, "char_end": 18,
            },
        }
        evaluator = DeterministicClaimSupportEvaluator(sources={"MAPU-X": source}, evidence=evidence)
        result = evaluator.assess(claim_id="c1", claim_kind="relation", evidence_ids=["ev1"])
        self.assertEqual(result.status, ClaimSupportStatus.NOT_ASSESSED)
        self.assertFalse(result.semantic_entailment_established)
        self.assertTrue(result.mechanically_supported)

    def test_invalid_quote_is_insufficient(self):
        source = "Chile produce vino."
        evidence = {
            "ev1": {
                "evidence_id": "ev1", "mapu_id": "MAPU-X", "source_uri": "viking://x",
                "source_sha256": __import__("hashlib").sha256(source.encode()).hexdigest(),
                "quote": "texto falso", "char_start": 0, "char_end": 11,
            },
        }
        evaluator = DeterministicClaimSupportEvaluator(sources={"MAPU-X": source}, evidence=evidence)
        result = evaluator.assess(claim_id="c1", claim_kind="relation", evidence_ids=["ev1"])
        self.assertEqual(result.status, ClaimSupportStatus.INSUFFICIENT)
        self.assertEqual(result.evidence_integrity[0].status, EvidenceIntegrityStatus.QUOTE_MISMATCH)


class QueryTests(unittest.TestCase):
    def _graph(self):
        return {
            "kuyen_id": "KUY-000000000000", "version": "1.0.0", "content_digest": "0" * 20,
            "entities": [
                {"entity_id": "e1", "entity_type": "place", "name": "Chile", "aliases": [],
                 "source_namespace": "provider", "source_entity_id": "s1", "evidence_ids": []},
                {"entity_id": "e2", "entity_type": "product", "name": "vino", "aliases": ["wine"],
                 "source_namespace": "provider", "source_entity_id": "s2", "evidence_ids": []},
            ],
            "relations": [{
                "relation_id": "r1", "from_entity": "e1", "to_entity": "e2",
                "predicate": "created_by", "source_predicate": "created_by",
                "canonical_predicate": "created_by", "provider_predicate": "related_to",
                "mapping_status": "UNMAPPED", "provider_projection_status": "LOSSY_PROJECTION",
                "label": "fue creado por", "polarity": "POSITIVE", "scope": "document",
                "temporal_scope": None, "temporal": {"kind": "UNKNOWN"}, "evidence_ids": ["ev1"],
                "sources": ["viking://x"], "status": "UNRESOLVED", "semantic_status": "NOT_ASSESSED",
            }],
            "assertions": [], "evidence": [{
                "evidence_id": "ev1", "mapu_id": "MAPU-X", "source_uri": "viking://x",
                "source_sha256": "a" * 64, "quote": "Chile produce vino", "char_start": 0, "char_end": 18,
            }],
        }

    def test_query_separates_source_canonical_and_provider_predicates(self):
        q = GraphQuery(self._graph())
        self.assertEqual(len(q.get_relations(source_predicate="created_by")), 1)
        self.assertEqual(len(q.get_relations(canonical_predicate="created_by")), 1)
        self.assertEqual(len(q.get_relations(provider_predicate="related_to")), 1)
        self.assertEqual(q.get_relations(source_predicate="created_by")[0]["mapping_status"], "UNMAPPED")

    def test_query_is_read_only_and_explains_claim(self):
        graph = self._graph()
        q = GraphQuery(graph)
        q.get_relations(source_predicate="created_by")[0]["predicate"] = "mutated"
        self.assertEqual(graph["relations"][0]["predicate"], "created_by")
        explanation = q.explain_claim("r1")
        self.assertEqual(explanation["source_predicate"], "created_by")
        self.assertEqual(explanation["provider_predicate"], "related_to")
        self.assertEqual(explanation["evidence"][0]["evidence_id"], "ev1")


if __name__ == "__main__":
    unittest.main()
