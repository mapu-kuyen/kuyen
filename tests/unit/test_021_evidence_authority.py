"""KUYEN_PRODUCTIVE_GRAPH_11 — authority of MAPU identity, quotes and polarity.

These tests pin the document-path hardening required by §5 of the brief:

* a MAPU declared by the producer is checked, never silently replaced (§5.1);
* in the native contract the verifiable quote is the authority for the offsets and the
  declared offsets are auxiliary information (§5.2);
* an undeclared polarity is UNKNOWN and the object is not admitted — never POSITIVE (§5.3);
* modality and attribution are first-class and absence is UNKNOWN, never FACT (§5.4);
* the compatibility reader preserves everything instead of dropping evidence (§5.5).
"""
from __future__ import annotations

import hashlib
import json
import unittest

from kuyen.coverage import inventory_sections
from kuyen.errors import InvalidRequestError
from kuyen.materialization import CandidateMaterializer
from kuyen.materialization.contract import CONTRACT_ID, CONTRACT_ID_V2, normalize_provider_result
from kuyen.models import Antu, CandidateBundle, Mapu
from kuyen.normalization import normalize_bundle

SOURCE = ("## Acuerdo\n"
          "La Municipalidad de Bahía Clara y la Cooperativa Faro Sur firmaron un acuerdo.\n"
          "## Avance\n"
          "Se instalaron 12 de las 18 luminarias previstas.\n"
          "## Previsión\n"
          "La Municipalidad comunicó que espera instalar las seis restantes antes del 10 de noviembre.\n")
URI = "viking://resources/test/MAPU-AUTH/source.txt"
MAPU_ID = "MAPU-AUTH"
DECLARED_QUOTE = "La Municipalidad de Bahía Clara y la Cooperativa Faro Sur firmaron un acuerdo."
INSTALLED_QUOTE = "Se instalaron 12 de las 18 luminarias previstas."
FORECAST_QUOTE = ("La Municipalidad comunicó que espera instalar las seis restantes "
                  "antes del 10 de noviembre.")


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def mapu(mapu_id: str = MAPU_ID, content: str = SOURCE) -> Mapu:
    return Mapu(mapu_id=mapu_id, version="1.0.0", source_uri=URI, content=content, sha256=sha(content))


def antu() -> Antu:
    return Antu.from_dict({
        "antu_id": "ANTU-AUTH", "version": "1.0.0", "purpose": "evidence authority",
        "author": "agent-design", "scope": {"include": ["test"], "exclude": []},
        "language": "es", "ontology_profile": "generic-v1",
        "entity_types": ["organization", "place"], "relation_types": ["contracted"],
        "coverage_policy": "complete", "evidence_policy": "strict",
        "scalar_policy": "literal", "conflict_policy": "preserve_unresolved",
        "output_profile": "kuyen-native-v1",
    })


def materializer(*, mapus: list[Mapu] | None = None, inventory: bool = True,
                 verify_evidence: bool = True) -> CandidateMaterializer:
    units = {"MAPU-AUTH": inventory_sections(SOURCE, mapu_id="MAPU-AUTH")} if inventory else None
    return CandidateMaterializer(mapus=mapus if mapus is not None else [mapu()], antu=antu(),
                                 coverage_inventory=units, verify_evidence=verify_evidence)


def relation(**overrides) -> dict:
    value = {"from": "municipalidad", "to": "cooperativa", "predicate": "contracted",
             "label": "firmó un acuerdo", "polarity": "POSITIVE",
             "evidence": [{"quote": DECLARED_QUOTE, "mapu_id": MAPU_ID, "source_uri": URI}]}
    value.update(overrides)
    return value


def provider_result(relations: list[dict], *, assertions: list[dict] | None = None,
                    version: str = CONTRACT_ID) -> dict:
    return {
        "schema_version": version,
        "provider": {"name": "test"},
        "entities": [
            {"provider_id": "municipalidad", "name": "Municipalidad", "entity_type": "organization",
             "evidence": [{"quote": DECLARED_QUOTE, "mapu_id": MAPU_ID, "source_uri": URI}]},
            {"provider_id": "cooperativa", "name": "Cooperativa", "entity_type": "organization",
             "evidence": [{"quote": DECLARED_QUOTE, "mapu_id": MAPU_ID, "source_uri": URI}]},
        ],
        "relations": relations,
        "assertions": assertions or [],
        "coverage": [],
    }


def materialize(result: dict, **kwargs):
    materialized = materializer(**kwargs).materialize(
        {"kuyen_result.json": json.dumps(result)}, provider={"task_id": "cmp_auth"})
    return None, materialized


class MapuIdentityTests(unittest.TestCase):
    def test_declared_mapu_that_is_not_in_context_is_refused(self):
        """§5.1 — the context MAPU is never used to cover up an invented identity."""
        result = provider_result([relation(evidence=[
            {"quote": DECLARED_QUOTE, "mapu_id": "MAPU-INVENTADO", "source_uri": URI}])])
        _, materialized = materialize(result)
        self.assertEqual(materialized.manifest["evidence"].get("MAPU_ID_NOT_IN_CONTEXT"), 1)
        self.assertEqual(materialized.bundle.relations[0].evidence_refs, [])
        decision = next(item for item in materialized.manifest["decisions"]
                        if item["classification"] == "MAPU_ID_NOT_IN_CONTEXT")
        self.assertIn("MAPU-INVENTADO", decision["reason"])
        self.assertIsNone(decision["mapu_id"])

    def test_absent_mapu_is_resolved_from_the_context_and_recorded(self):
        result = provider_result([relation(evidence=[{"quote": DECLARED_QUOTE, "source_uri": URI}])])
        _, materialized = materialize(result)
        self.assertEqual(materialized.manifest["evidence"].get("MAPU_RESOLVED_BY_CONTEXT"), 1)
        self.assertEqual(len(materialized.bundle.relations[0].evidence_refs), 1)

    def test_uri_of_another_mapu_is_still_a_mismatch(self):
        result = provider_result([relation(evidence=[
            {"quote": DECLARED_QUOTE, "mapu_id": MAPU_ID, "source_uri": "viking://other/x.txt"}])])
        _, materialized = materialize(result)
        self.assertIn("URI_MISMATCH", materialized.manifest["evidence"])

class QuoteAuthorityTests(unittest.TestCase):
    def test_native_offsets_zero_do_not_destroy_a_verifiable_quote(self):
        """§5.2 — the real OpenViking artifacts declare char_start=0/char_end=len(quote)."""
        result = provider_result([relation(evidence=[
            {"quote": INSTALLED_QUOTE, "mapu_id": MAPU_ID, "source_uri": URI,
             "char_start": 0, "char_end": len(INSTALLED_QUOTE)}])])
        _, materialized = materialize(result)
        self.assertIn("QUOTE_AUTHORITATIVE", materialized.manifest["evidence"])
        evidence = materialized.bundle.relations[0].evidence_refs
        self.assertEqual(len(evidence), 1)
        stored = next(item for item in materialized.bundle.evidence if item.quote == INSTALLED_QUOTE)
        self.assertEqual(stored.char_start, SOURCE.index(INSTALLED_QUOTE))
        self.assertEqual(stored.declared_offsets, {"char_start": 0, "char_end": len(INSTALLED_QUOTE)})

    def test_context_disambiguates_a_repeated_quote(self):
        content = SOURCE + "Contexto distinto.\n" + INSTALLED_QUOTE + "\nFin.\n"
        repeated = INSTALLED_QUOTE
        fragment = "Contexto distinto.\n" + repeated
        result = provider_result([relation(evidence=[
            {"quote": repeated, "mapu_id": MAPU_ID, "source_uri": URI, "context": fragment}])])
        _, materialized = materialize(result, mapus=[mapu(content=content)])
        stored = next(item for item in materialized.bundle.evidence
                      if item.evidence_id == materialized.bundle.relations[0].evidence_refs[0])
        self.assertEqual(stored.char_start, content.index(fragment) + len("Contexto distinto.\n"))
        self.assertEqual(stored.context, fragment)

    def test_ambiguous_quote_without_context_is_still_refused(self):
        content = SOURCE + "Repetido.\nRepetido.\n"
        result = provider_result([relation(evidence=[
            {"quote": "Repetido.", "mapu_id": MAPU_ID, "source_uri": URI}])])
        _, materialized = materialize(result, mapus=[mapu(content=content)])
        self.assertIn("AMBIGUOUS_QUOTE", materialized.manifest["evidence"])
        self.assertEqual(materialized.bundle.relations[0].evidence_refs, [])

    def test_declared_source_unit_must_contain_the_span(self):
        units = sorted(inventory_sections(SOURCE, mapu_id=MAPU_ID), key=lambda item: item.char_start)
        self.assertGreaterEqual(len(units), 2)
        result = provider_result([relation(evidence=[
            {"quote": DECLARED_QUOTE, "mapu_id": MAPU_ID, "source_uri": URI,
             "source_unit_id": units[-1].unit_id}])])
        _, materialized = materialize(result)
        self.assertIn("SOURCE_UNIT_MISMATCH", materialized.manifest["evidence"])

    def test_declared_source_unit_that_contains_the_span_is_accepted(self):
        units = sorted(inventory_sections(SOURCE, mapu_id=MAPU_ID), key=lambda item: item.char_start)
        first = next(item for item in units
                     if item.char_start <= SOURCE.index(DECLARED_QUOTE) < item.char_end)
        result = provider_result([relation(evidence=[
            {"quote": DECLARED_QUOTE, "mapu_id": MAPU_ID, "source_uri": URI,
             "source_unit_id": first.unit_id}])])
        _, materialized = materialize(result)
        self.assertEqual(len(materialized.bundle.relations[0].evidence_refs), 1)
        stored = next(item for item in materialized.bundle.evidence
                      if item.evidence_id == materialized.bundle.relations[0].evidence_refs[0])
        self.assertEqual(stored.source_unit_id, first.unit_id)


class PolarityAndModalityTests(unittest.TestCase):
    def test_missing_polarity_is_not_admitted_and_never_becomes_positive(self):
        """§5.3 — the canonical set only carries POSITIVE/NEGATIVE, so UNKNOWN stays out."""
        result = provider_result([relation()])
        del result["relations"][0]["polarity"]
        _, materialized = materialize(result)
        self.assertIn("POLARITY_UNKNOWN", materialized.manifest["evidence"])
        self.assertEqual(materialized.bundle.relations, [])

    def test_explicit_unknown_polarity_is_recorded_with_its_own_reason(self):
        result = provider_result([relation(polarity="UNKNOWN")])
        result["assertions"] = [{"subject": "municipalidad", "predicate": "has_lights",
                                 "value": {"value_type": "integer", "value": 12},
                                 "polarity": "UNKNOWN",
                                 "evidence": [{"quote": INSTALLED_QUOTE, "mapu_id": MAPU_ID,
                                               "source_uri": URI}]}]
        _, materialized = materialize(result)
        self.assertEqual(materialized.manifest["evidence"].get("POLARITY_UNKNOWN"), 2)
        self.assertEqual(materialized.bundle.relations, [])
        self.assertEqual(materialized.bundle.assertions, [])

    def test_negative_polarity_survives(self):
        result = provider_result([relation(polarity="NEGATIVE")])
        _, materialized = materialize(result)
        self.assertEqual(materialized.bundle.relations[0].polarity, "NEGATIVE")

    def test_absent_modality_is_unknown_and_a_forecast_stays_a_forecast(self):
        """§5.4 — a forecast is not a fact, and silence is not a fact either."""
        result = provider_result([], assertions=[
            {"subject": "municipalidad", "predicate": "expected_installation_date",
             "value": {"value_type": "string", "value": "2026-11-10"},
             "polarity": "POSITIVE", "modality": "FORECAST",
             "attribution": "la Municipalidad",
             "evidence": [{"quote": FORECAST_QUOTE, "mapu_id": MAPU_ID, "source_uri": URI}]},
            {"subject": "municipalidad", "predicate": "has_installed_lights",
             "value": {"value_type": "integer", "value": 12},
             "polarity": "POSITIVE",
             "evidence": [{"quote": INSTALLED_QUOTE, "mapu_id": MAPU_ID, "source_uri": URI}]},
        ])
        _, materialized = materialize(result)
        by_predicate = {item.predicate: item for item in materialized.bundle.assertions}
        self.assertEqual(by_predicate["expected_installation_date"].modality, "FORECAST")
        self.assertEqual(by_predicate["expected_installation_date"].attribution, "la Municipalidad")
        self.assertEqual(by_predicate["has_installed_lights"].modality, "UNKNOWN")
        self.assertIsNone(by_predicate["has_installed_lights"].attribution)

    def test_unknown_modality_is_recorded_instead_of_guessed(self):
        result = provider_result([], assertions=[
            {"subject": "municipalidad", "predicate": "has_installed_lights",
             "value": {"value_type": "integer", "value": 12}, "polarity": "POSITIVE",
             "modality": "RUMOUR",
             "evidence": [{"quote": INSTALLED_QUOTE, "mapu_id": MAPU_ID, "source_uri": URI}]}])
        _, materialized = materialize(result)
        self.assertIn("MODALITY_UNRECOGNIZED", materialized.manifest["evidence"])
        self.assertEqual(materialized.bundle.assertions[0].modality, "UNKNOWN")



class ContractVersionTests(unittest.TestCase):
    def test_v1_is_still_accepted(self):
        data = normalize_provider_result(provider_result([relation()], version=CONTRACT_ID))
        self.assertEqual(data["schema_version"], CONTRACT_ID)

    def test_v2_is_accepted_and_carries_modality_attribution_and_evidence_context(self):
        result = provider_result([relation(modality="FACT", attribution="el municipio",
                                          evidence=[{"quote": DECLARED_QUOTE, "mapu_id": MAPU_ID,
                                                     "source_uri": URI,
                                                     "context": "firmaron un acuerdo"}])],
                                 version=CONTRACT_ID_V2)
        data = normalize_provider_result(result)
        self.assertEqual(data["schema_version"], CONTRACT_ID_V2)
        _, materialized = materialize(result)
        self.assertEqual(materialized.manifest["provider_schema"], CONTRACT_ID_V2)
        self.assertEqual(materialized.bundle.relations[0].modality, "FACT")
        self.assertEqual(materialized.bundle.relations[0].attribution, "el municipio")

    def test_an_unknown_contract_version_is_refused(self):
        with self.assertRaises(Exception) as context:
            normalize_provider_result(provider_result([relation()], version="kuyen-provider-result-v9"))
        self.assertIn("schema_version", str(context.exception))


class NormalizerStrictnessTests(unittest.TestCase):
    def test_unknown_polarity_cannot_enter_the_canonical_graph(self):
        bundle = CandidateBundle.from_dict({
            "entities": [{"id": "a", "name": "A", "entity_type": "organization"}],
            "relations": [{"from": "a", "relation": "contracted", "to": "a",
                           "label": "x", "polarity": "UNKNOWN"}],
            "assertions": [], "evidence": [], "coverage": [],
        })
        with self.assertRaises(InvalidRequestError) as context:
            normalize_bundle(bundle=bundle, antu_id="ANTU-AUTH", mapus=[mapu()],
                             version="1.0.0", provenance={})
        self.assertEqual(context.exception.details["code"], "POLARITY_UNKNOWN_NOT_ADMITTED")

    def test_modality_and_attribution_reach_the_canonical_object(self):
        bundle = CandidateBundle.from_dict({
            "entities": [{"id": "a", "name": "A", "entity_type": "organization"}],
            "relations": [], "evidence": [], "coverage": [],
            "assertions": [{"subject": "a", "predicate": "has_lights",
                            "value": {"value_type": "integer", "value": 12},
                            "polarity": "POSITIVE", "modality": "FORECAST",
                            "attribution": "el municipio"}],
        })
        graph = normalize_bundle(bundle=bundle, antu_id="ANTU-AUTH", mapus=[mapu()],
                                 version="1.0.0", provenance={})
        self.assertEqual(graph.assertions[0].modality, "FORECAST")
        self.assertEqual(graph.assertions[0].attribution, "el municipio")
        self.assertEqual(graph.assertions[0].to_dict()["polarity"], "POSITIVE")


class CompatibilityReaderTests(unittest.TestCase):
    """§5.5 — the deprecated reader keeps everything and claims nothing."""

    def test_assertions_and_evidence_are_preserved_without_mapu_context(self):
        artifacts = {
            "entities/municipalidad.md": (
                "---\nid: municipalidad\nname: Municipalidad\nentity_type: organization\n"
                f"description: una municipalidad\nsources:\n  - {URI}\n"
                f"evidence:\n  - quote: \"{DECLARED_QUOTE}\"\n    char_start: 0\n"
                f"    mapu_id: {MAPU_ID}\n---\n\nCuerpo.\n"),
            "relations.jsonl": json.dumps(relation()) + "\n",
            "assertions.jsonl": json.dumps({
                "subject": "municipalidad", "predicate": "has_installed_lights",
                "value": {"value_type": "integer", "value": 12}, "polarity": "POSITIVE",
                "evidence": [{"quote": INSTALLED_QUOTE, "mapu_id": MAPU_ID, "source_uri": URI}],
            }) + "\n",
        }
        materialized = materializer(mapus=None, inventory=False,
                                   verify_evidence=False).materialize(artifacts)
        bundle = materialized.bundle
        self.assertEqual(len(bundle.entities), 1)
        self.assertEqual(len(bundle.relations), 1)
        self.assertEqual(len(bundle.assertions), 1)
        # Every declared evidence entry is preserved (entity, relation and assertion).
        self.assertGreaterEqual(len(bundle.evidence), 2)
        self.assertEqual({item.quote for item in bundle.evidence},
                         {DECLARED_QUOTE, INSTALLED_QUOTE})
        self.assertTrue(all(item.validation_status == "NOT_EVALUATED" for item in bundle.evidence))
        self.assertIn("DECLARED_UNVERIFIED", materialized.manifest["evidence"])
        self.assertNotIn("SOURCE_VERIFIED", json.dumps(materialized.manifest))

    def test_missing_polarity_is_preserved_as_unknown_not_invented(self):
        artifacts = {
            "entities/municipalidad.md": (
                "---\nid: municipalidad\nname: Municipalidad\nentity_type: organization\n---\n\nCuerpo.\n"),
            "relations.jsonl": json.dumps({"from": "municipalidad", "to": "municipalidad",
                                           "relation": "contracted", "label": "x"}) + "\n",
        }
        materialized = materializer(mapus=None, inventory=False,
                                   verify_evidence=False).materialize(artifacts)
        self.assertEqual(materialized.bundle.relations[0].polarity, "UNKNOWN")


class MalformedStructuredResultTests(unittest.TestCase):
    """A broken aggregate file must not destroy a valid native tree (§8.1, measured)."""

    def _tree(self, malformed: str | None):
        tree = {
            "entities/municipalidad.md": (
                "---\nid: municipalidad\nname: Municipalidad\nentity_type: organization\n"
                f"sources:\n  - {URI}\n"
                f"evidence:\n  - quote: \"{DECLARED_QUOTE}\"\n    source_uri: {URI}\n"
                f"    mapu_id: {MAPU_ID}\n---\n\nCuerpo.\n"),
            "relations.jsonl": json.dumps(relation()) + "\n",
        }
        if malformed is not None:
            tree["kuyen_result.json"] = malformed
        return tree

    def test_the_tree_is_materialized_and_the_defect_is_recorded(self):
        materialized = materializer().materialize(self._tree('{"entities": [oops'))
        self.assertEqual(materialized.manifest["mode"],
                         "native_structured_after_invalid_structured_result")
        self.assertEqual(materialized.manifest["provider_schema"], "kuyen-native-files-v1")
        self.assertEqual(len(materialized.bundle.entities), 1)
        self.assertEqual(len(materialized.bundle.relations), 1)
        self.assertIn("ignored", materialized.manifest["warnings"][-1])
        self.assertIn("kuyen_result.json",
                      materialized.manifest["structured_result_ignored"]["artifact"])

    def test_a_malformed_result_without_a_tree_is_still_fatal(self):
        from kuyen.errors import CandidateMaterializationError

        with self.assertRaises(CandidateMaterializationError):
            materializer().materialize({"kuyen_result.json": "not json at all"})


class StatementOriginTests(unittest.TestCase):
    """Documentary provenance without documentary verification is its own kind."""

    def test_a_reference_origin_is_documentary_but_not_verified(self):
        from kuyen.semantics.origin import (ORIGIN_DOCUMENT_REFERENCE, comes_from_document,
                                            document_reference_origin, is_documentary, problems)

        record = document_reference_origin(mapu_ids=["MAPU-1"])
        self.assertEqual(record["kind"], ORIGIN_DOCUMENT_REFERENCE)
        self.assertTrue(comes_from_document(record))
        self.assertFalse(is_documentary(record))
        self.assertFalse(record["documentary_verification"])
        self.assertEqual(record["evidence_ids"], [])
        self.assertEqual(problems(record, label="assertion", identifier="a-1"), [])

    def test_a_reference_origin_must_name_its_document(self):
        from kuyen.semantics.origin import document_reference_origin, problems

        record = document_reference_origin(mapu_ids=[])
        found = problems(record, label="assertion", identifier="a-1")
        self.assertEqual(len(found), 1)
        self.assertIn("ORIGIN_DOCUMENT_REFERENCE_WITHOUT_MAPU", found[0])

    def test_a_document_origin_without_evidence_stays_refused(self):
        from kuyen.semantics.origin import document_origin, problems

        found = problems(document_origin(evidence_ids=[], mapu_ids=["MAPU-1"]),
                         label="relation", identifier="r-1")
        self.assertIn("ORIGIN_DOCUMENT_WITHOUT_EVIDENCE", " ".join(found))

    def test_an_instruction_can_never_declare_source_verified(self):
        from kuyen.semantics.origin import antu_origin, problems

        record = antu_origin(antu_id="ANTU-1", instruction="cambia 12 por 18",
                             instruction_sha256=sha("cambia 12 por 18"),
                             base_version_id="VER-000000000000")
        found = problems(record, label="assertion", identifier="a-1",
                         status="SOURCE_VERIFIED")
        self.assertIn("ORIGIN_ANTU_CANNOT_BE_SOURCE_VERIFIED", " ".join(found))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

