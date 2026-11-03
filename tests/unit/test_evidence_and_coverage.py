from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from kuyen.config import KuyenConfig
from kuyen.engine import KuyenEngine
from kuyen.models import CandidateBundle
from kuyen.serialization import read_native_relations
from tests.helpers import SOURCE_URI, actor, antu, candidate, mapu

import kuyen as _kuyen


def _package_root() -> Path:
    """Directory of the installed package (assets ship as package data)."""
    return Path(_kuyen.__file__).resolve().parent



ROOT = _package_root()


def engine_for(tmp: str) -> KuyenEngine:
    return KuyenEngine(KuyenConfig(
        data_dir=Path(tmp) / "data",
        ontology_path=ROOT / "config" / "ontologies" / "generic-v1.yaml",
        skill_dir=ROOT / "skills" / "knowledge-graph",
    ))


class EvidenceAndCoverageTests(unittest.IsolatedAsyncioTestCase):
    async def test_assertion_scalar_and_polarity_are_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            candidate_data = copy.deepcopy(candidate())
            candidate_data["assertions"] = [{
                "subject": "asociacion-rio-claro",
                "predicate": "has_member_count",
                "value": {"value_type": "integer", "value": 9, "unit": None, "context": "document"},
                "polarity": "POSITIVE",
                "scope": "document",
                "sources": [SOURCE_URI],
                "evidence_refs": ["ev-1"],
            }]
            candidate_data["relations"][0]["polarity"] = "NEGATIVE"
            candidate_data["relations"][0]["temporal_scope"] = "2021"
            result = await engine_for(tmp).build_from_candidate_async(
                antu=antu(), mapu_sources=[mapu()], actor=actor(),
                candidate=CandidateBundle.from_dict(candidate_data),
            )
            self.assertEqual(result.status, "ACCEPTED", result.error)
            graph = json.loads((Path(result.provenance_manifest).parent / "graph.json").read_text(encoding="utf-8"))
            self.assertEqual(graph["relations"][0]["polarity"], "NEGATIVE")
            self.assertEqual(graph["relations"][0]["temporal_scope"], "2021")
            self.assertEqual(graph["assertions"][0]["value"]["value"], 9)
            self.assertNotIn("ent_", json.dumps(graph["assertions"][0]["value"]))

    async def test_conflicting_values_preserve_status_or_reject(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data = copy.deepcopy(candidate())
            data["assertions"] = [
                {
                    "subject": "asociacion-rio-claro", "predicate": "has_member_count",
                    "value": {"value_type": "integer", "value": 9},
                    "polarity": "POSITIVE",
                    "sources": [SOURCE_URI], "evidence_refs": ["ev-1"],
                },
                {
                    "subject": "asociacion-rio-claro", "predicate": "has_member_count",
                    "value": {"value_type": "integer", "value": 10},
                    "polarity": "POSITIVE",
                    "sources": [SOURCE_URI], "evidence_refs": ["ev-1"],
                },
            ]
            preserved = await engine_for(tmp).build_from_candidate_async(
                antu=antu(), mapu_sources=[mapu()], actor=actor(),
                candidate=CandidateBundle.from_dict(data),
            )
            self.assertEqual(preserved.status, "ACCEPTED", preserved.error)
            graph = json.loads((Path(preserved.provenance_manifest).parent / "graph.json").read_text())
            self.assertEqual({item["status"] for item in graph["assertions"]}, {"CONTRADICTED"})
            rejected = await engine_for(tmp + "/other").build_from_candidate_async(
                antu=antu(conflict_policy="reject_conflict"), mapu_sources=[mapu()], actor=actor(),
                candidate=CandidateBundle.from_dict(data),
            )
            self.assertEqual(rejected.status, "REJECTED")
            self.assertTrue(any(issue.code == "CONFLICT_DETECTED" for issue in rejected.validation.errors))

    async def test_evidence_hash_mismatch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bad = copy.deepcopy(candidate())
            bad["evidence"][0]["source_sha256"] = "0" * 64
            result = await engine_for(tmp).build_from_candidate_async(
                antu=antu(), mapu_sources=[mapu()], actor=actor(),
                candidate=CandidateBundle.from_dict(bad),
            )
            self.assertEqual(result.status, "REJECTED")
            self.assertTrue(any(issue.code == "EVIDENCE_HASH_MISMATCH" for issue in result.validation.errors))

    async def test_evidence_uri_mismatch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bad = copy.deepcopy(candidate())
            bad["evidence"][0]["source_uri"] = "viking://resources/other/nope.md"
            result = await engine_for(tmp).build_from_candidate_async(
                antu=antu(), mapu_sources=[mapu()], actor=actor(),
                candidate=CandidateBundle.from_dict(bad),
            )
            self.assertEqual(result.status, "REJECTED")
            self.assertTrue(any(issue.code == "EVIDENCE_URI_MISMATCH" for issue in result.validation.errors))

    async def test_evidence_out_of_range_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bad = copy.deepcopy(candidate())
            bad["evidence"][0]["char_start"] = 999999
            bad["evidence"][0]["char_end"] = 1000000
            result = await engine_for(tmp).build_from_candidate_async(
                antu=antu(), mapu_sources=[mapu()], actor=actor(),
                candidate=CandidateBundle.from_dict(bad),
            )
            self.assertEqual(result.status, "REJECTED")
            self.assertTrue(any(issue.code == "EVIDENCE_OFFSET_OUT_OF_RANGE" for issue in result.validation.errors))

    async def test_duplicate_evidence_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bad = copy.deepcopy(candidate())
            bad["evidence"].append(copy.deepcopy(bad["evidence"][0]))
            result = await engine_for(tmp).build_from_candidate_async(
                antu=antu(), mapu_sources=[mapu()], actor=actor(),
                candidate=CandidateBundle.from_dict(bad),
            )
            self.assertEqual(result.status, "REJECTED")
            self.assertTrue(any(issue.code == "EVIDENCE_DUPLICATE" for issue in result.validation.errors))

    async def test_coverage_failed_and_skipped_are_rejected(self) -> None:
        for state in ("FAILED", "SKIPPED_WITH_REASON", "NOT_ATTEMPTED"):
            with tempfile.TemporaryDirectory() as tmp:
                bad = copy.deepcopy(candidate())
                bad["coverage"][0]["state"] = state
                result = await engine_for(tmp).build_from_candidate_async(
                    antu=antu(), mapu_sources=[mapu()], actor=actor(),
                    candidate=CandidateBundle.from_dict(bad),
                )
                self.assertEqual(result.status, "REJECTED", state)
                self.assertTrue(any(issue.code == "COVERAGE_UNIT_INCOMPLETE" for issue in result.validation.errors))

    async def test_coverage_no_facts_is_terminal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            empty = {
                "entities": [], "relations": [], "assertions": [], "evidence": [],
                "coverage": [{
                    "source_uri": SOURCE_URI, "mapu_id": mapu().mapu_id,
                    "unit_id": "whole-source", "state": "PROCESSED_NO_GRAPH_FACTS",
                }],
            }
            result = await engine_for(tmp).build_from_candidate_async(
                antu=antu(), mapu_sources=[mapu()], actor=actor(),
                candidate=CandidateBundle.from_dict(empty),
            )
            self.assertEqual(result.status, "ACCEPTED", result.error)
            self.assertTrue(result.coverage["complete"])

    async def test_malformed_jsonl_is_rejected_by_reader(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "relations.jsonl").write_text('{"from":"a",\n', encoding="utf-8")
            with self.assertRaises(ValueError):
                read_native_relations(root)
