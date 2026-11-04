"""0.1.9 candidate: canonical predicate contract.

Regression cover for the predicate layer through the normal flow:

    provider payload -> contract -> CandidateMaterializer -> CandidateRelation
    -> annotate_predicate_provenance -> normalize_bundle -> OntologyValidator
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from kuyen.config import KuyenConfig
from kuyen.engine import KuyenEngine
from kuyen.materialization import CandidateMaterializer
from kuyen.materialization.contract import RELATION_KEYS, normalize_provider_result
from kuyen.models import ActorContext, Antu, CandidateBundle, CandidateEntity, CandidateRelation, Mapu
from kuyen.normalization.normalizer import normalize_bundle
from kuyen.ontology import Ontology
from kuyen.semantics import annotate_predicate_provenance, preserve_incompatible_relations

import kuyen as _kuyen


def _package_root() -> Path:
    """Directory of the installed package (assets ship as package data)."""
    return Path(_kuyen.__file__).resolve().parent



ROOT = _package_root()
PREDICATE_FIELDS = (
    "source_predicate", "canonical_predicate", "provider_predicate", "display_label",
    "provider_label", "mapping_status", "mapping_rule_id", "mapping_version",
    "provider_projection_status",
)
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
SOURCE = (FIXTURES / "source.txt").read_text(encoding="utf-8")


def ontology() -> Ontology:
    return Ontology.load(ROOT / "config/ontologies/generic-v1.yaml")


def provider_payload(relations: list[dict], entities: list[dict] | None = None) -> dict:
    return {
        "schema_version": "kuyen-provider-result-v1",
        "provider": {"name": "test", "model": None},
        "entities": entities or [
            {"provider_id": "p1", "name": "Organization", "entity_type": "organization",
             "evidence": [{"quote": SOURCE.splitlines()[0], "source_uri": "viking://test",
                           "mapu_id": "MAPU-TEST"}]},
            {"provider_id": "p2", "name": "Idea", "entity_type": "concept",
             "evidence": [{"quote": SOURCE.splitlines()[0], "source_uri": "viking://test",
                           "mapu_id": "MAPU-TEST"}]},
        ],
        "relations": relations,
        "assertions": [],
        "coverage": [],
    }


def mapu() -> Mapu:
    return Mapu(
        mapu_id="MAPU-TEST", version="1.0.0", source_uri="viking://test", content=SOURCE,
        sha256=__import__("hashlib").sha256(SOURCE.encode("utf-8")).hexdigest(),
        media_type="text/plain", source_type="synthetic", source_identity="fixture",
        ingestion_timestamp="2026-10-30T00:00:00+00:00", trust_level="VERIFIED",
        access_policy="experimental", metadata={},
    )


def antu_obj() -> Antu:
    return Antu.from_dict({
        "antu_id": "ANTU-CCP-001", "version": "1.0.0", "purpose": "predicate contract",
        "author": "agent-design", "scope": {"include": ["fixture"], "exclude": []},
        "language": "es", "ontology_profile": "generic-v1",
        "entity_types": ["organization", "concept", "place"],
        "relation_types": ["located_in", "related_to", "coordinates"],
        "coverage_policy": "not_required", "evidence_policy": "strict",
        "scalar_policy": "literal", "conflict_policy": "preserve_unresolved",
        "output_profile": "kuyen-native-v1",
    })


def materialize(relations: list[dict]):
    return CandidateMaterializer(mapus=[mapu()], antu=antu_obj()).materialize(
        {"kuyen_result.json": json.dumps(provider_payload(relations))},
        provider={"name": "test", "model": None},
    )


class ContractFieldTests(unittest.TestCase):
    def test_nine_predicate_fields_are_contract_keys(self):
        self.assertTrue(set(PREDICATE_FIELDS).issubset(RELATION_KEYS))

    def test_payload_fields_no_longer_produce_warnings(self):
        relation = {"from": "p1", "to": "p2", "predicate": "related_to",
                    "source_predicate": "coordina a", "canonical_predicate": "coordina a",
                    "provider_predicate": "related_to", "display_label": "coordina a",
                    "provider_label": "se relaciona con", "mapping_status": "UNMAPPED",
                    "mapping_rule_id": "test-v1", "mapping_version": "1.0.0",
                    "provider_projection_status": "LOSSY_PROJECTION"}
        normalized = normalize_provider_result(provider_payload([relation]))
        self.assertEqual(normalized["warnings"], [])

    def test_candidate_relation_receives_the_predicate_layer(self):
        relation = {"from": "p1", "to": "p2", "predicate": "related_to",
                    "source_predicate": "coordina a", "canonical_predicate": "coordina a",
                    "polarity": "POSITIVE",
                    "mapping_status": "UNMAPPED", "mapping_rule_id": "test-v1"}
        bundle = materialize([relation]).bundle
        item = bundle.relations[0]
        self.assertEqual(item.source_predicate, "coordina a")
        self.assertEqual(item.canonical_predicate, "coordina a")
        self.assertEqual(item.mapping_status, "UNMAPPED")
        self.assertEqual(item.mapping_rule_id, "test-v1")

    def test_candidate_relation_defaults_do_not_claim_exact(self):
        relation = CandidateRelation(from_entity="p1", relation="related_to", to_entity="p2")
        self.assertEqual(relation.mapping_status, "UNRESOLVED")
        self.assertIsNone(relation.mapping_rule_id)



class PolicyTests(unittest.TestCase):
    def _bundle(self, relation: CandidateRelation) -> CandidateBundle:
        return CandidateBundle(
            entities=[CandidateEntity(id="p1", name="Organization", entity_type="organization"),
                      CandidateEntity(id="p2", name="Idea", entity_type="concept")],
            relations=[relation],
        )

    def _graph(self, relation: CandidateRelation):
        bundle = self._bundle(relation)
        annotate_predicate_provenance(bundle, ontology())
        return normalize_bundle(bundle=bundle, antu_id="ANTU-T", mapus=[mapu()],
                                version="1.0.0", provenance={}).relations[0]

    def test_normalizer_does_not_invent_a_source_predicate(self):
        item = self._graph(CandidateRelation(from_entity="p1", relation="related_to",
                                             to_entity="p2", label="se relaciona con",
                                             polarity="POSITIVE"))
        self.assertIsNone(item.source_predicate)
        self.assertEqual(item.mapping_status, "UNRESOLVED")

    def test_preserved_native_predicate_survives_and_is_flagged(self):
        item = self._graph(CandidateRelation(
            from_entity="p1", relation="related_to", to_entity="p2", label="se relaciona con",
            polarity="POSITIVE",
            source_predicate="coordina a", canonical_predicate="coordina a",
            mapping_status="UNMAPPED", mapping_rule_id="test-v1"))
        self.assertEqual(item.predicate, "coordina a")
        self.assertEqual(item.canonical_predicate, "coordina a")
        self.assertEqual(item.mapping_status, "UNMAPPED")
        self.assertEqual(item.provider_predicate, "related_to")
        self.assertEqual(item.provider_projection_status, "LOSSY_PROJECTION")

    def test_legacy_related_to_is_unresolved_not_exact(self):
        bundle = self._bundle(CandidateRelation(from_entity="p1", relation="related_to",
                                                to_entity="p2", label="se relaciona con"))
        annotate_predicate_provenance(bundle, ontology())
        self.assertEqual(bundle.relations[0].mapping_status, "UNRESOLVED")
        self.assertEqual(bundle.relations[0].mapping_rule_id, "legacy-generic-unverified-v1")

    def test_legacy_ontology_term_is_mapped_not_exact(self):
        bundle = CandidateBundle(
            entities=[CandidateEntity(id="p1", name="Organization", entity_type="organization"),
                      CandidateEntity(id="p3", name="Place", entity_type="place")],
            relations=[CandidateRelation(from_entity="p1", relation="located_in",
                                         to_entity="p3", label="se ubica en")],
        )
        annotate_predicate_provenance(bundle, ontology())
        self.assertEqual(bundle.relations[0].mapping_status, "MAPPED")
        self.assertIsNone(bundle.relations[0].source_predicate)

    def test_generic_source_relation_can_stay_exact(self):
        bundle = self._bundle(CandidateRelation(
            from_entity="p1", relation="related_to", to_entity="p2", label="se relaciona con",
            mapping_status="EXACT", mapping_rule_id="source-generic-v1"))
        annotate_predicate_provenance(bundle, ontology())
        self.assertEqual(bundle.relations[0].mapping_status, "EXACT")

    def test_policy_is_idempotent(self):
        bundle = self._bundle(CandidateRelation(
            from_entity="p1", relation="related_to", to_entity="p2", label="se relaciona con",
            source_predicate="coordina a", canonical_predicate="related_to",
            mapping_status="UNMAPPED", mapping_rule_id="test-v1"))
        annotate_predicate_provenance(bundle, ontology())
        first = (bundle.relations[0].mapping_rule_id, bundle.relations[0].canonical_predicate)
        annotate_predicate_provenance(bundle, ontology())
        second = (bundle.relations[0].mapping_rule_id, bundle.relations[0].canonical_predicate)
        self.assertEqual(first, second)

    def test_unknown_term_without_provenance_is_not_preserved(self):
        bundle = self._bundle(CandidateRelation(from_entity="p1", relation="invented_predicate",
                                                to_entity="p2", label="inventado"))
        annotate_predicate_provenance(bundle, ontology())
        self.assertIsNone(bundle.relations[0].source_predicate)
        self.assertIsNone(bundle.relations[0].mapping_rule_id)



class PipelineTests(unittest.IsolatedAsyncioTestCase):
    async def _build(self, relation: dict):
        with tempfile.TemporaryDirectory() as tmp:
            engine = KuyenEngine(KuyenConfig(
                data_dir=Path(tmp) / "data",
                ontology_path=ROOT / "config/ontologies/generic-v1.yaml",
                skill_dir=ROOT / "skills/knowledge-graph",
                coverage_profile="none",
            ))
            actor = ActorContext(
                leftraru_id="LR-T", authenticated_account="t", authenticated_user="t",
                service_identity="svc", antu_author="agent-design", candidate_producer="test",
            )
            materialized = materialize([relation])
            result = await engine.build_from_candidate_async(
                antu=antu_obj(), mapu_sources=[mapu()], actor=actor,
                candidate=materialized.bundle,
            )
            graph_path = Path(result.provenance_manifest).parent / "graph.json" \
                if result.provenance_manifest else None
            graph = json.loads(graph_path.read_text(encoding="utf-8")) if graph_path else None
            return result, graph

    async def test_unmapped_predicate_accepted_with_warning(self):
        result, graph = await self._build({
            "from": "p1", "to": "p2", "predicate": "related_to",
            "source_predicate": "coordina a", "canonical_predicate": "coordina a",
            "polarity": "POSITIVE",
            "mapping_status": "UNMAPPED", "mapping_rule_id": "test-v1",
            "provider_projection_status": "LOSSY_PROJECTION",
            "evidence": [{"quote": SOURCE.splitlines()[0], "source_uri": "viking://test",
                          "mapu_id": "MAPU-TEST"}],
            "sources": ["viking://test"],
        })
        self.assertEqual(result.status, "ACCEPTED", result.error)
        codes = {issue.code for issue in result.validation.issues}
        self.assertIn("NATIVE_PREDICATE_PRESERVED_UNMAPPED", codes)
        self.assertNotIn("PREDICATE_NOT_ALLOWED", codes)
        self.assertEqual(graph["relations"][0]["predicate"], "coordina a")

    async def test_unknown_predicate_without_provenance_still_rejected(self):
        result, _ = await self._build({"from": "p1", "to": "p2",
                                       "predicate": "invented_predicate",
                                       "polarity": "POSITIVE",
                                       "evidence": [{"quote": SOURCE.splitlines()[0],
                                                     "source_uri": "viking://test",
                                                     "mapu_id": "MAPU-TEST"}],
                                       "sources": ["viking://test"]})
        self.assertEqual(result.status, "REJECTED")
        codes = {issue.code for issue in result.validation.issues}
        self.assertIn("PREDICATE_NOT_ALLOWED", codes)

    async def test_historical_graph_relation_is_still_readable(self):
        from kuyen.models import Relation

        historical = {
            "relation_id": "rel_historical", "from_entity": "ent_a", "to_entity": "ent_b",
            "predicate": "related_to", "label": "se relaciona con",
            "source_predicate": "related_to", "canonical_predicate": "related_to",
            "provider_predicate": "related_to", "mapping_status": "EXACT",
            "mapping_rule_id": "normalizer-exact-v1", "mapping_version": "1.0.0",
            "provider_projection_status": "EXACT", "polarity": "POSITIVE",
            "scope": "document", "status": "UNRESOLVED",
        }
        relation = Relation.from_dict(historical)
        self.assertEqual(relation.predicate, "related_to")
        self.assertEqual(relation.mapping_status, "EXACT")


if __name__ == "__main__":
    unittest.main()

