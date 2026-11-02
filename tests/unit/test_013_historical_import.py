"""0.1.3 historical import: preserve identity, terms and evidence limits."""
from __future__ import annotations

import unittest
from pathlib import Path

from kuyen.importing import import_historical_graph
from kuyen.ontology import Ontology

import kuyen as _kuyen


def _package_root() -> Path:
    """Directory of the installed package (assets ship as package data)."""
    return Path(_kuyen.__file__).resolve().parent



ROOT = _package_root()
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "kuyen013"
GENERIC = ROOT / "config/ontologies/generic-v1.yaml"
HISTORICAL = ROOT / "config/ontologies/profiles/historical-native-v1.yaml"
WINE = ROOT / "config/ontologies/profiles/wine-tourism-v1.yaml"


def load(fixture: str, profile: Path):
    root = FIXTURES / fixture
    source = root / "MAPU-08.txt" if fixture == "micro08" else None
    return import_historical_graph(
        root,
        ontology=Ontology.load(profile),
        namespace=f"native-{fixture}",
        system_version="MICROPRUEBA",
        source_text_path=source if source and source.is_file() else None,
    )


class HistoricalImportTests(unittest.TestCase):
    def test_micro08_identity_and_terms_are_preserved(self):
        result = load("micro08", HISTORICAL)
        payload = result.to_dict()
        self.assertEqual(payload["counts"], {"entities": 7, "relations": 5})
        native_ids = {item["native_id"] for item in payload["entities"]}
        self.assertEqual(
            native_ids,
            {"2021", "9", "asociacion-rio-claro", "elena-soto", "nueve-integrantes", "paihuano", "productores-de-uva-de-la-zona"},
        )
        self.assertEqual(payload["compatibility"]["entity_types"]["unmapped"], [])
        self.assertEqual(payload["compatibility"]["predicates"]["unmapped"], [])
        self.assertTrue(payload["compatibility"]["ids_preserved"])
        self.assertTrue(payload["compatibility"]["labels_preserved"])
        self.assertFalse(payload["compatibility"]["mapping_applied"])
        by_native = {item["native_id"]: item for item in payload["entities"]}
        self.assertNotEqual(by_native["9"]["kuyen_id"], by_native["nueve-integrantes"]["kuyen_id"])
        self.assertEqual(by_native["2021"]["entity_type"], "event")

    def test_micro08_keeps_the_reified_count_incompatibility_visible(self):
        payload = load("micro08", HISTORICAL).to_dict()
        self.assertIn("has_member_count", payload["compatibility"]["predicates"]["domain_range_incompatible"])
        relation = next(item for item in payload["relations"] if item["native_predicate"] == "has_member_count")
        self.assertEqual(relation["direction_status"], "DOMAIN_RANGE_INCOMPATIBLE_NATIVE")
        self.assertEqual(relation["native_to"], "9")

    def test_micro08_evidence_is_not_upgraded(self):
        payload = load("micro08", HISTORICAL).to_dict()
        self.assertEqual(payload["compatibility"]["evidence"]["relations"].get("EXACT_SPAN"), 5)
        self.assertFalse(payload["compatibility"]["evidence"]["all_entities_exact"])
        self.assertIn("entities without exact spans", payload["compatibility"]["strict_blockers"])
        self.assertFalse(payload["compatibility"]["strict_acceptance_available"])

    def test_micro10_requires_wine_profile_and_reports_document_evidence(self):
        payload = load("micro10", WINE).to_dict()
        self.assertEqual(payload["compatibility"]["entity_types"]["unmapped"], [])
        self.assertEqual(payload["compatibility"]["predicates"]["unmapped"], [])
        self.assertEqual(payload["compatibility"]["evidence"]["relations"].get("DOCUMENT_REFERENCE"), 4)
        self.assertFalse(payload["compatibility"]["evidence"]["all_relations_exact"])
        self.assertFalse(payload["compatibility"]["strict_acceptance_available"])
        self.assertEqual(payload["relations"][0]["evidence_class"], "DOCUMENT_REFERENCE")
        self.assertIsNone(payload["relations"][0]["quote"])

    def test_micro10_under_generic_v1_lists_every_unmapped_term(self):
        payload = load("micro10", GENERIC).to_dict()
        self.assertEqual(payload["compatibility"]["entity_types"]["unmapped"], ["industry", "tourism", "tourism_route"])
        self.assertEqual(payload["compatibility"]["predicates"]["unmapped"], ["hosts", "produces", "promotes"])
        # Nothing is dropped: all six entities and four relations remain present.
        self.assertEqual(payload["counts"], {"entities": 6, "relations": 4})

    def test_import_is_deterministic(self):
        first = load("micro08", HISTORICAL).to_dict()
        second = load("micro08", HISTORICAL).to_dict()
        self.assertEqual(
            [(x["native_id"], x["kuyen_id"]) for x in first["entities"]],
            [(x["native_id"], x["kuyen_id"]) for x in second["entities"]],
        )
        self.assertEqual(first["source_hashes"], second["source_hashes"])

    def test_invalid_native_span_is_reported_not_upgraded(self):
        import json
        import shutil
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "micro08"
            shutil.copytree(FIXTURES / "micro08", target)
            relations_path = target / "relations.jsonl"
            rows = [json.loads(line) for line in relations_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            rows[0]["evidence_quote"] = "cita alterada"
            relations_path.write_text(
                "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8"
            )
            result = import_historical_graph(
                target, ontology=Ontology.load(HISTORICAL), namespace="native-micro08",
                system_version="MICROPRUEBA", source_text_path=target / "MAPU-08.txt",
            )
            payload = result.to_dict()
            self.assertEqual(payload["compatibility"]["evidence"]["relations"].get("INVALID_SPAN"), 1)
            self.assertFalse(payload["compatibility"]["evidence"]["all_relations_exact"])
            self.assertIn("relations without exact spans", payload["compatibility"]["strict_blockers"])


if __name__ == "__main__":
    unittest.main()
