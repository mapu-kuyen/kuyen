"""0.1.3 deterministic coverage inventory and acceptance rules."""
from __future__ import annotations

import asyncio
import hashlib
import tempfile
import unittest
from pathlib import Path

from kuyen.config import KuyenConfig
from kuyen.coverage import inventory_sections
from kuyen.engine import KuyenEngine
from kuyen.models import ActorContext, CandidateBundle, Mapu

import kuyen as _kuyen


def _package_root() -> Path:
    """Directory of the installed package (assets ship as package data)."""
    return Path(_kuyen.__file__).resolve().parent



ROOT = _package_root()
ONTO = ROOT / "config/ontologies/generic-v1.yaml"
SKILL = ROOT / "skills/knowledge-graph"
SOURCE = (
    "## Alpha\n"
    "La organización Alpha está en Beta.\n"
    "## Gamma\n"
    "La organización Alpha tiene 3 socios.\n"
)
URI = "viking://resources/test/MAPU-COV/source.md"


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def mapu() -> Mapu:
    return Mapu(mapu_id="MAPU-COV", version="1.0.0", source_uri=URI, content=SOURCE, sha256=sha(SOURCE))


def actor() -> ActorContext:
    return ActorContext(
        leftraru_id="LR-COV", authenticated_account="cov", authenticated_user="cov",
        service_identity="svc-cov", antu_author="agent-design", candidate_producer="controlled",
    )


def antu(**overrides):
    value = {
        "antu_id": "ANTU-COV", "version": "1.0.0", "purpose": "coverage test",
        "author": "agent-design", "scope": {"include": ["test"], "exclude": []},
        "language": "es", "ontology_profile": "generic-v1",
        "entity_types": ["organization", "place"],
        "relation_types": ["located_in"],
        "coverage_policy": "complete", "evidence_policy": "strict",
        "scalar_policy": "literal", "conflict_policy": "preserve_unresolved",
        "output_profile": "kuyen-native-v1",
    }
    value.update(overrides)
    return value


def evidence(quote: str, ev_id: str) -> dict:
    start = SOURCE.index(quote)
    return {
        "evidence_id": ev_id, "mapu_id": "MAPU-COV", "source_uri": URI,
        "source_sha256": sha(SOURCE), "quote": quote, "char_start": start,
        "char_end": start + len(quote), "offset_unit": "unicode_codepoint",
        "extraction_method": "test",
    }


def candidate(coverage: list[dict] | None = None) -> dict:
    return {
        "entities": [
            {"id": "alpha", "name": "Alpha", "entity_type": "organization", "sources": [URI],
             "evidence_refs": ["ev-1", "ev-2"]},
            {"id": "beta", "name": "Beta", "entity_type": "place", "sources": [URI],
             "evidence_refs": ["ev-1"]},
        ],
        "relations": [
            {"from": "alpha", "relation": "located_in", "to": "beta", "label": "se ubica en",
             "polarity": "POSITIVE", "sources": [URI], "evidence_refs": ["ev-1"]},
        ],
        "assertions": [
            {"subject": "alpha", "predicate": "has_member_count",
             "value": {"value_type": "integer", "value": 3, "unit": "socios"},
             "polarity": "POSITIVE", "sources": [URI], "evidence_refs": ["ev-2"]},
        ],
        "evidence": [
            evidence("La organización Alpha está en Beta.", "ev-1"),
            evidence("La organización Alpha tiene 3 socios.", "ev-2"),
        ],
        "coverage": coverage if coverage is not None else [
            {"source_uri": URI, "mapu_id": "MAPU-COV", "unit_id": "u01", "section": "Alpha",
             "state": "PROCESSED_WITH_OUTPUT", "entity_ids": ["alpha", "beta"], "relation_ids": []},
            {"source_uri": URI, "mapu_id": "MAPU-COV", "unit_id": "u02", "section": "Gamma",
             "state": "PROCESSED_WITH_OUTPUT", "entity_ids": ["alpha"], "relation_ids": []},
        ],
    }


def evaluate(coverage=None, *, antu_overrides=None, profile="document-sections-v1"):
    with tempfile.TemporaryDirectory() as directory:
        engine = KuyenEngine(KuyenConfig(
            data_dir=Path(directory) / "data", ontology_path=ONTO, skill_dir=SKILL,
            coverage_profile=profile,
        ))
        return asyncio.run(engine.build_from_candidate_async(
            antu=antu(**(antu_overrides or {})), mapu_sources=[mapu()],
            actor=actor(), candidate=CandidateBundle.from_dict(candidate(coverage)),
        ))


class InventoryTests(unittest.TestCase):
    def test_inventory_is_deterministic_and_covers_the_source(self):
        units = inventory_sections(SOURCE, mapu_id="MAPU-COV")
        self.assertEqual([unit.unit_id for unit in units], ["u01", "u02"])
        self.assertEqual([unit.section for unit in units], ["Alpha", "Gamma"])
        self.assertEqual(units[0].char_start, 0)
        self.assertEqual(units[-1].char_end, len(SOURCE))
        self.assertEqual(units[0].content_sha256, sha(SOURCE[units[0].char_start:units[0].char_end]))
        self.assertEqual(units, inventory_sections(SOURCE, mapu_id="MAPU-COV"))

    def test_preamble_and_body_units(self):
        with_prelude = inventory_sections("intro\n## Uno\ncuerpo\n", mapu_id="M")
        self.assertEqual([u.unit_id for u in with_prelude], ["u00", "u01"])
        self.assertEqual(with_prelude[0].section, "preamble")
        body = inventory_sections("sin encabezados\n", mapu_id="M")
        self.assertEqual([(u.unit_id, u.section) for u in body], [("u00", "body")])

    def test_micro10_inventory_shape(self):
        path = Path(__file__).resolve().parents[1] / "fixtures" / "MAPU-10.txt"
        if not path.is_file():
            self.skipTest("research fixture MAPU-10.txt is not distributed with the product")
        if not path.is_file():
            self.skipTest("MAPU-10 experiment source not present")
        text = path.read_text(encoding="utf-8")
        units = inventory_sections(text, mapu_id="MAPU-10")
        self.assertGreaterEqual(len(units), 20)
        self.assertEqual(units[0].unit_id, "u00")
        self.assertEqual(units[0].section, "preamble")
        self.assertEqual(units[-1].char_end, len(text))
        for previous, current in zip(units, units[1:]):
            self.assertEqual(previous.char_end, current.char_start)


class CoverageAcceptanceTests(unittest.TestCase):
    def test_complete_ledger_is_accepted(self):
        result = evaluate()
        self.assertEqual(result.status, "ACCEPTED", result.validation.to_dict())
        self.assertEqual(result.coverage["unit_count"], 2)

    def test_missing_expected_unit_is_rejected(self):
        ledger = candidate()["coverage"][:1]
        result = evaluate(ledger)
        self.assertEqual(result.status, "REJECTED")
        codes = {issue.code for issue in result.validation.issues}
        self.assertIn("COVERAGE_EXPECTED_UNIT_MISSING", codes)

    def test_unexpected_unit_is_rejected(self):
        ledger = candidate()["coverage"] + [{
            "source_uri": URI, "mapu_id": "MAPU-COV", "unit_id": "u99", "section": "invented",
            "state": "PROCESSED_NO_GRAPH_FACTS", "entity_ids": [], "relation_ids": [],
        }]
        result = evaluate(ledger)
        self.assertEqual(result.status, "REJECTED")
        self.assertIn("COVERAGE_UNIT_UNEXPECTED", {issue.code for issue in result.validation.issues})

    def test_output_state_without_output_is_rejected(self):
        ledger = candidate()["coverage"]
        ledger[0]["entity_ids"] = []
        ledger[0]["relation_ids"] = []
        result = evaluate(ledger)
        self.assertEqual(result.status, "REJECTED")
        self.assertIn("COVERAGE_OUTPUT_EMPTY", {issue.code for issue in result.validation.issues})

    def test_complete_with_reasons_requires_a_reason(self):
        ledger = candidate()["coverage"]
        ledger[1] = {
            "source_uri": URI, "mapu_id": "MAPU-COV", "unit_id": "u02", "section": "Gamma",
            "state": "SKIPPED_WITH_REASON", "entity_ids": [], "relation_ids": [], "reason": None,
        }
        rejected = evaluate(ledger, antu_overrides={"coverage_policy": "complete_with_reasons"})
        self.assertIn("COVERAGE_SKIP_REASON_MISSING", {issue.code for issue in rejected.validation.issues})
        ledger[1]["reason"] = "section is a duplicate of Alpha"
        accepted = evaluate(ledger, antu_overrides={"coverage_policy": "complete_with_reasons"})
        self.assertEqual(accepted.status, "ACCEPTED", accepted.validation.to_dict())

    def test_require_terminal_rejects_not_attempted(self):
        ledger = candidate()["coverage"]
        ledger[1]["state"] = "NOT_ATTEMPTED"
        result = evaluate(ledger, antu_overrides={"coverage_policy": "require_terminal"})
        self.assertEqual(result.status, "REJECTED")
        self.assertIn("COVERAGE_UNIT_NOT_ATTEMPTED", {issue.code for issue in result.validation.issues})


if __name__ == "__main__":
    unittest.main()
