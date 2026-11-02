"""0.1.5 OpenAI extraction schema, budget, conversion and factual gate."""
from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from kuyen.config import KuyenConfig
from kuyen.coverage import inventory_sections
from kuyen.engine import KuyenEngine
from kuyen.errors import OpenAIBudgetExceededError
from kuyen.extraction import (
    BudgetLedger, OpenAIExtractionConfig, OpenAIExtractionProvider, PricingSnapshot,
    build_extraction_schema, evaluate_fact_coverage, extraction_to_provider_result,
    schema_hash, validate_strict_schema,
)
from kuyen.materialization import CandidateMaterializer
from kuyen.models import ActorContext, Antu, Mapu
from kuyen.ontology import Ontology

import kuyen as _kuyen


def _package_root() -> Path:
    """Directory of the installed package (assets ship as package data)."""
    return Path(_kuyen.__file__).resolve().parent



ROOT = _package_root()
SOURCE = "La Cooperativa Agrícola Los Aromos es una organización de productores del valle de Quillota.\nMarta Fuentes coordina la Cooperativa Agrícola Los Aromos.\nLa cooperativa tiene 47 socios y su sede está en el valle de Quillota.\nLa cooperativa comenzó a operar en 2019.\nEn 2023 la cooperativa produjo 12.500 litros de vino.\nLa cooperativa no exporta vino a Asia.\nLa Fiesta de la Vendimia de Quillota se celebra cada abril en el valle de Quillota.\n"
URI = "viking://resources/test/MAPU-K02"
MAPU_ID = "MAPU-SYN-01"
QUOTES = [line.strip() for line in SOURCE.splitlines() if line.strip()]
SHA = __import__("hashlib").sha256(SOURCE.encode()).hexdigest()


def antu_data(extensions=None):
    return {
        "antu_id": "ANTU-K02-SYN-01", "version": "1.0.0", "purpose": "0.1.5 test",
        "author": "agent-design", "scope": {"include": ["K02"], "exclude": []},
        "language": "es", "ontology_profile": "generic-v1",
        "entity_types": ["organization", "place", "person", "event", "concept"],
        "relation_types": ["located_in", "headquartered_in", "coordinates", "related_to"],
        "coverage_policy": "complete", "evidence_policy": "strict", "scalar_policy": "literal",
        "conflict_policy": "preserve_unresolved", "output_profile": "kuyen-native-v1",
        "extensions": extensions or {},
    }


def mapu() -> Mapu:
    return Mapu(mapu_id=MAPU_ID, version="1.0.0", source_uri=URI, content=SOURCE, sha256=SHA)


def extraction_candidate():
    evidence = [
        {"evidence_ref": f"E{index:02d}", "mapu_id": MAPU_ID, "unit_id": "u00",
         "quote": quote, "source_uri": URI, "context_ref": None}
        for index, quote in enumerate(QUOTES, 1)
    ]
    return {
        "entities": [
            {"source_ref": "coop", "source_entity_id": "coop-native", "entity_type": "organization",
             "name": "Cooperativa Agrícola Los Aromos", "description": "Organización de productores.",
             "aliases": [], "source_mapu_id": MAPU_ID, "source_unit_id": "u00", "evidence_refs": ["E01"]},
            {"source_ref": "marta", "source_entity_id": "marta-native", "entity_type": "person",
             "name": "Marta Fuentes", "description": "Persona que coordina.", "aliases": [],
             "source_mapu_id": MAPU_ID, "source_unit_id": "u00", "evidence_refs": ["E02"]},
            {"source_ref": "valle", "source_entity_id": "valle-native", "entity_type": "place",
             "name": "valle de Quillota", "description": "Valle.", "aliases": [],
             "source_mapu_id": MAPU_ID, "source_unit_id": "u00", "evidence_refs": ["E01"]},
            {"source_ref": "fiesta", "source_entity_id": "fiesta-native", "entity_type": "event",
             "name": "Fiesta de la Vendimia de Quillota", "description": "Fiesta anual.", "aliases": [],
             "source_mapu_id": MAPU_ID, "source_unit_id": "u00", "evidence_refs": ["E07"]},
        ],
        "relations": [
            {"source_relation_ref": "r1", "from_source_ref": "marta", "to_source_ref": "coop",
             "predicate": "coordinates", "label": "coordina", "polarity": "POSITIVE",
             "temporal_scope": None, "epistemic_status": "UNRESOLVED", "evidence_refs": ["E02"]},
            {"source_relation_ref": "r2", "from_source_ref": "coop", "to_source_ref": "valle",
             "predicate": "headquartered_in", "label": "tiene sede en", "polarity": "POSITIVE",
             "temporal_scope": None, "epistemic_status": "UNRESOLVED", "evidence_refs": ["E03"]},
            {"source_relation_ref": "r3", "from_source_ref": "fiesta", "to_source_ref": "valle",
             "predicate": "located_in", "label": "se ubica en", "polarity": "POSITIVE",
             "temporal_scope": "cada abril", "epistemic_status": "UNRESOLVED", "evidence_refs": ["E07"]},
        ],
        "assertions": [
            {"assertion_ref": "a1", "subject_ref": "coop", "predicate": "has_member_count",
             "object_ref": None, "value": {"value_type": "integer", "text_value": None, "number_value": 47,
             "unit": "socios", "context": None}, "polarity": "POSITIVE", "temporal_scope": None,
             "epistemic_status": "UNRESOLVED", "evidence_refs": ["E03"]},
            {"assertion_ref": "a2", "subject_ref": "coop", "predicate": "started_operation_in",
             "object_ref": None, "value": {"value_type": "year", "text_value": None, "number_value": 2019,
             "unit": None, "context": None}, "polarity": "POSITIVE", "temporal_scope": "2019",
             "epistemic_status": "UNRESOLVED", "evidence_refs": ["E04"]},
            {"assertion_ref": "a3", "subject_ref": "coop", "predicate": "has_value",
             "object_ref": None, "value": {"value_type": "quantity", "text_value": None, "number_value": 12500,
             "unit": "litros", "context": "2023"}, "polarity": "POSITIVE", "temporal_scope": "2023",
             "epistemic_status": "UNRESOLVED", "evidence_refs": ["E05"]},
            {"assertion_ref": "a4", "subject_ref": "coop", "predicate": "has_value",
             "object_ref": None, "value": {"value_type": "string", "text_value": "no exporta vino a Asia",
             "number_value": None, "unit": None, "context": None}, "polarity": "NEGATIVE",
             "temporal_scope": None, "epistemic_status": "UNRESOLVED", "evidence_refs": ["E06"]},
        ],
        "evidence": evidence,
        "coverage": {"units_used": ["u00"], "notes": None},
    }


def ground_truth():
    return {
        "expected_total": 7, "absent_control": "F00",
        "facts": [
            {"id": "F01", "type": "entity", "name_contains": ["cooperativa", "aromos"],
             "entity_type": "organization", "evidence_quote": QUOTES[0], "critical": True},
            {"id": "F02", "type": "relation", "predicate": "coordinates", "from_contains": ["marta"],
             "to_contains": ["cooperativa", "aromos"], "evidence_quote": QUOTES[1], "critical": True},
            {"id": "F03", "type": "assertion", "subject_contains": ["cooperativa", "aromos"],
             "predicate": "has_member_count", "number": 47, "evidence_quote": QUOTES[2], "critical": True},
            {"id": "F04", "type": "assertion", "subject_contains": ["cooperativa", "aromos"],
             "predicate": "started_operation_in", "number": 2019, "evidence_quote": QUOTES[3], "critical": True},
            {"id": "F05", "type": "assertion", "subject_contains": ["cooperativa", "aromos"],
             "predicate": "has_value", "number": 12500, "unit": "litros", "evidence_quote": QUOTES[4], "critical": True},
            {"id": "F06", "type": "assertion", "subject_contains": ["cooperativa", "aromos"],
             "predicate": "has_value", "text_contains": ["no exporta", "asia"], "polarity": "NEGATIVE",
             "evidence_quote": QUOTES[5], "critical": True},
            {"id": "F07", "type": "entity_relation_or_assertion", "entity_name_contains": ["fiesta", "vendimia"],
             "entity_type": "event", "target_contains": ["quillota"],
             "relation_predicates": ["located_in", "related_to"], "assertion_text_contains": ["abril", "se celebra"],
             "evidence_quote": QUOTES[6], "critical": True},
            {"id": "F00", "type": "absent_control", "text_contains": ["exporta", "asia"],
             "polarity": "POSITIVE", "critical": False},
        ],
    }


class FakeResponse:
    def __init__(self, candidate, *, status="completed", refusal=None):
        self.id = "resp_test_015"
        self.model = "gpt-6-luna"
        self.status = status
        self.created_at = 1760000000.0
        self.incomplete_details = SimpleNamespace(reason="max_output_tokens") if status == "incomplete" else None
        content_type = "refusal" if refusal else "output_text"
        content = SimpleNamespace(type=content_type, text=json.dumps(candidate), refusal=refusal)
        self.output = [SimpleNamespace(type="message", content=[content])]
        self.usage = SimpleNamespace(
            input_tokens=1200, output_tokens=350, total_tokens=1550,
            output_tokens_details=SimpleNamespace(reasoning_tokens=40),
        )
        self._candidate = candidate

    def model_dump(self, mode="json"):
        return {"id": self.id, "model": self.model, "status": self.status,
                "usage": {"input_tokens": 1200, "output_tokens": 350, "total_tokens": 1550},
                "output": []}


class FakeClient:
    def __init__(self, response):
        self.response = response
        self.calls = []
        self.models = SimpleNamespace(retrieve=self._retrieve)
        self.responses = SimpleNamespace(create=self._create)

    def _retrieve(self, model):
        return SimpleNamespace(id=model, owned_by="system", created=1)

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


def pricing():
    return PricingSnapshot(
        model="gpt-6-luna", input_usd_per_million=0.10, output_usd_per_million=0.50,
        embedding_usd_per_million=0.02, source_url="https://platform.openai.com/docs/pricing.md",
        retrieved_at="2026-10-30T00:00:00+00:00",
    )


def evaluate_bundle(bundle):
    with tempfile.TemporaryDirectory() as directory:
        engine = KuyenEngine(KuyenConfig(
            data_dir=Path(directory) / "data",
            ontology_path=(ROOT / "config/ontologies/generic-v1.yaml").resolve(),
            skill_dir=(ROOT / "skills/knowledge-graph").resolve(),
            coverage_profile="document-sections-v1",
        ))
        actor = ActorContext(
            leftraru_id="LR-015", authenticated_account="kuyen015", authenticated_user="svc015",
            service_identity="svc015", antu_author="agent-design", candidate_producer="openai",
        )
        return asyncio.run(engine.build_from_candidate_async(
            antu=antu_data({"x-kuyen-fact-coverage": {"minimum_supported": 7}}),
            mapu_sources=[mapu()], actor=actor, candidate=bundle,
        ))


class ExtractionTests(unittest.TestCase):
    def antu(self):
        return Antu.from_dict(antu_data())

    def ontology(self):
        return Ontology.load(ROOT / "config/ontologies/generic-v1.yaml")

    def test_schema_is_strict_and_versioned(self):
        schema = build_extraction_schema(
            antu=self.antu(), ontology=self.ontology(), mapu_ids=[MAPU_ID],
            unit_ids=["u00"], source_uris=[URI],
        )
        self.assertEqual(validate_strict_schema(schema), [])
        self.assertIn("entities", schema["properties"])
        self.assertEqual(schema_hash(schema), schema_hash(schema))
        import jsonschema

        jsonschema.validate(extraction_candidate(), schema)
        broken = json.loads(json.dumps(schema))
        broken["properties"]["entities"]["items"]["minItems"] = 1
        self.assertTrue(any("minItems" in error for error in validate_strict_schema(broken)))

    def test_antu_accepts_fact_coverage_extension(self):
        antu = Antu.from_dict(antu_data({"x-kuyen-fact-coverage": {"minimum_supported": 7}}))
        self.assertEqual(antu.extensions["x-kuyen-fact-coverage"]["minimum_supported"], 7)

    def test_provider_records_usage_and_preserves_request(self):
        candidate = extraction_candidate()
        fake = FakeClient(FakeResponse(candidate))
        ledger = BudgetLedger(total_usd=0.50, phase_caps={"extraction": 0.15})
        provider = OpenAIExtractionProvider(
            config=OpenAIExtractionConfig(max_output_tokens=1000),
            ledger=ledger, pricing=pricing(), client=fake,
        )
        result = provider.extract(
            antu=self.antu(), ontology=self.ontology(), source_text=SOURCE,
            source_uri=URI, mapu_id=MAPU_ID, unit_ids=["u00"],
        )
        self.assertEqual(result.response_id, "resp_test_015")
        self.assertEqual(result.model, "gpt-6-luna")
        self.assertEqual(result.usage.input_tokens, 1200)
        self.assertEqual(result.usage.reasoning_tokens, 40)
        self.assertGreater(result.cost_usd, 0)
        self.assertEqual(ledger.entries[0].response_id, "resp_test_015")
        self.assertIn("format", result.request["text"])
        self.assertNotIn("OPENAI_API_KEY", json.dumps(result.request))
        self.assertEqual(len(fake.calls), 1)
        self.assertFalse(fake.calls[0]["store"])
        self.assertEqual(fake.calls[0]["model"], "gpt-6-luna")

    def test_budget_rejects_before_call(self):
        fake = FakeClient(FakeResponse(extraction_candidate()))
        ledger = BudgetLedger(total_usd=0.000001)
        provider = OpenAIExtractionProvider(ledger=ledger, pricing=pricing(), client=fake)
        with self.assertRaises(OpenAIBudgetExceededError):
            provider.extract(
                antu=self.antu(), ontology=self.ontology(), source_text=SOURCE,
                source_uri=URI, mapu_id=MAPU_ID, unit_ids=["u00"],
            )
        self.assertEqual(fake.calls, [])

    def test_incomplete_and_refusal_are_classified(self):
        provider = OpenAIExtractionProvider(
            ledger=BudgetLedger(total_usd=0.50), pricing=pricing(),
            client=FakeClient(FakeResponse(extraction_candidate(), status="incomplete")),
        )
        from kuyen.errors import OpenAIExtractionError

        with self.assertRaises(OpenAIExtractionError):
            provider.extract(
                antu=self.antu(), ontology=self.ontology(), source_text=SOURCE,
                source_uri=URI, mapu_id=MAPU_ID, unit_ids=["u00"],
            )
        provider = OpenAIExtractionProvider(
            ledger=BudgetLedger(total_usd=0.50), pricing=pricing(),
            client=FakeClient(FakeResponse(extraction_candidate(), refusal="cannot extract")),
        )
        with self.assertRaises(OpenAIExtractionError):
            provider.extract(
                antu=self.antu(), ontology=self.ontology(), source_text=SOURCE,
                source_uri=URI, mapu_id=MAPU_ID, unit_ids=["u00"],
            )

    def materialize(self, candidate):
        provider_result = extraction_to_provider_result(
            candidate, source_uri=URI, mapu_id=MAPU_ID, model="gpt-6-luna", response_id="resp_test_015",
        )
        materializer = CandidateMaterializer(
            mapus=[mapu()], antu=self.antu(),
            coverage_inventory={MAPU_ID: inventory_sections(SOURCE, mapu_id=MAPU_ID)},
        )
        return materializer.materialize({"kuyen_result.json": json.dumps(provider_result)})

    def test_conversion_materializes_and_kuyen_accepts(self):
        materialized = self.materialize(extraction_candidate())
        self.assertEqual(len(materialized.bundle.entities), 4)
        self.assertEqual(len(materialized.bundle.relations), 3)
        self.assertEqual(len(materialized.bundle.assertions), 4)
        self.assertGreaterEqual(materialized.manifest["evidence"].get("EXACT_SPAN", 0) + materialized.manifest["evidence"].get("OFFSET_RESOLVED_UNIQUE", 0), 7)
        result = evaluate_bundle(materialized.bundle)
        self.assertEqual(result.status, "ACCEPTED", result.validation.to_dict())

    def test_factual_gate_accepts_all_seven_and_absent_control(self):
        materialized = self.materialize(extraction_candidate())
        coverage = evaluate_fact_coverage(materialized.bundle, ground_truth())
        self.assertEqual(coverage["supported"], 7)
        self.assertEqual(coverage["fact_coverage"], 1.0)
        self.assertTrue(coverage["absent_control_ok"])
        self.assertTrue(coverage["accepted"])

    def test_minimal_graph_is_not_fact_complete(self):
        candidate = extraction_candidate()
        candidate["entities"] = candidate["entities"][:1]
        candidate["relations"] = []
        candidate["assertions"] = []
        candidate["evidence"] = candidate["evidence"][:1]
        materialized = self.materialize(candidate)
        coverage = evaluate_fact_coverage(materialized.bundle, ground_truth())
        self.assertEqual(coverage["supported"], 1)
        self.assertFalse(coverage["accepted"])
        self.assertEqual(coverage["fact_coverage"], round(1 / 7, 4))

    def test_conversion_rejects_orphan_endpoint(self):
        candidate = extraction_candidate()
        candidate["relations"][0]["to_source_ref"] = "missing"
        with self.assertRaises(Exception):
            extraction_to_provider_result(candidate, source_uri=URI, mapu_id=MAPU_ID)


if __name__ == "__main__":
    unittest.main()
