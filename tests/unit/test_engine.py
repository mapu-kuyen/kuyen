from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from kuyen.config import KuyenConfig
from kuyen.engine import KuyenEngine
from kuyen.errors import InvalidRequestError, VersionConflictError
from kuyen.models import CandidateBundle, Mapu
from kuyen.serialization import KuyenSerializer
from tests.helpers import SOURCE_URI, actor, antu, bundle, candidate, mapu

import kuyen as _kuyen


def _package_root() -> Path:
    """Directory of the installed package (assets ship as package data)."""
    return Path(_kuyen.__file__).resolve().parent



ROOT = _package_root()


def engine_for(tmp: str) -> KuyenEngine:
    return KuyenEngine(
        KuyenConfig(
            data_dir=Path(tmp) / "data",
            ontology_path=ROOT / "config" / "ontologies" / "generic-v1.yaml",
            skill_dir=ROOT / "skills" / "knowledge-graph",
        )
    )


class EngineTests(unittest.IsolatedAsyncioTestCase):
    async def test_valid_candidate_is_accepted_and_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine = engine_for(tmp)
            result = await engine.build_from_candidate_async(
                antu=antu(), mapu_sources=[mapu()], actor=actor(), candidate=bundle()
            )
            self.assertEqual(result.status, "ACCEPTED", result.error)
            self.assertTrue(result.content_digest)
            self.assertIsNotNone(result.graph_uri)
            self.assertTrue(Path(result.provenance_manifest).is_file())
            version_dir = Path(result.provenance_manifest).parent
            self.assertTrue((version_dir / "graph.json").is_file())
            self.assertTrue((version_dir / "native" / "relations.jsonl").is_file())
            self.assertTrue((version_dir / "sources" / "MAPU-TEST.txt").is_file())
            self.assertTrue((version_dir / "sources.json").is_file())
            native = (version_dir / "native" / "relations.jsonl").read_text(encoding="utf-8").strip()
            self.assertIn('"from"', native)
            self.assertNotIn("evidence_refs", native)
            self.assertNotIn("polarity", native)

    async def test_orphan_endpoint_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine = engine_for(tmp)
            result = await engine.build_from_candidate_async(
                antu=antu(), mapu_sources=[mapu()], actor=actor(), candidate=bundle(valid=False)
            )
            self.assertEqual(result.status, "REJECTED")
            self.assertTrue(any(issue.code == "ORPHAN_ENDPOINT" for issue in result.validation.errors))

    async def test_shifted_quote_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine = engine_for(tmp)
            bad = copy.deepcopy(candidate())
            bad["evidence"][0]["char_start"] += 1
            bad["evidence"][0]["char_end"] += 1
            result = await engine.build_from_candidate_async(
                antu=antu(), mapu_sources=[mapu()], actor=actor(),
                candidate=CandidateBundle.from_dict(bad),
            )
            self.assertEqual(result.status, "REJECTED")
            self.assertTrue(any(issue.code == "EVIDENCE_QUOTE_MISMATCH" for issue in result.validation.errors))

    async def test_missing_coverage_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine = engine_for(tmp)
            bad = copy.deepcopy(candidate())
            bad["coverage"] = []
            result = await engine.build_from_candidate_async(
                antu=antu(), mapu_sources=[mapu()], actor=actor(),
                candidate=CandidateBundle.from_dict(bad),
            )
            self.assertEqual(result.status, "REJECTED")
            self.assertTrue(any(issue.code == "COVERAGE_LEDGER_MISSING" for issue in result.validation.errors))

    async def test_duplicate_entity_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine = engine_for(tmp)
            bad = copy.deepcopy(candidate())
            bad["entities"].append(dict(bad["entities"][0]))
            result = await engine.build_from_candidate_async(
                antu=antu(), mapu_sources=[mapu()], actor=actor(),
                candidate=CandidateBundle.from_dict(bad),
            )
            self.assertEqual(result.status, "REJECTED")
            self.assertTrue(any(issue.code == "DUPLICATE_ID" for issue in result.validation.errors))

    async def test_unknown_predicate_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine = engine_for(tmp)
            bad = copy.deepcopy(candidate())
            bad["relations"][0]["relation"] = "invented_predicate"
            result = await engine.build_from_candidate_async(
                antu=antu(), mapu_sources=[mapu()], actor=actor(),
                candidate=CandidateBundle.from_dict(bad),
            )
            self.assertEqual(result.status, "REJECTED")
            self.assertTrue(any(issue.code == "PREDICATE_NOT_ALLOWED" for issue in result.validation.errors))

    async def test_deterministic_content_projection(self) -> None:
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            ra = await engine_for(a).build_from_candidate_async(
                antu=antu(), mapu_sources=[mapu()], actor=actor(), candidate=bundle()
            )
            rb = await engine_for(b).build_from_candidate_async(
                antu=antu(), mapu_sources=[mapu()], actor=actor(), candidate=bundle()
            )
            self.assertEqual(ra.content_digest, rb.content_digest)
            self.assertEqual(ra.kuyen_id, rb.kuyen_id)

    async def test_invalid_antu_raises_typed_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine = engine_for(tmp)
            bad = antu()
            bad.pop("ontology_profile")
            with self.assertRaises(InvalidRequestError):
                await engine.build_from_candidate_async(
                    antu=bad, mapu_sources=[mapu()], actor=actor(), candidate=bundle()
                )

    async def test_actor_author_mismatch_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine = engine_for(tmp)
            with self.assertRaises(InvalidRequestError):
                await engine.build_from_candidate_async(
                    antu=antu(), mapu_sources=[mapu()],
                    actor=actor(antu_author="other-author"), candidate=bundle(),
                )

    async def test_mapu_hash_and_request_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine = engine_for(tmp)
            bad = Mapu(**{**mapu().__dict__, "sha256": "0" * 64})
            with self.assertRaises(InvalidRequestError):
                await engine.build_from_candidate_async(
                    antu=antu(), mapu_sources=[bad], actor=actor(), candidate=bundle()
                )

    async def test_same_request_different_content_conflicts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine = engine_for(tmp)
            first = await engine.build_from_candidate_async(
                antu=antu(), mapu_sources=[mapu()], actor=actor(), candidate=bundle(),
                request_key="req_test_fixed",
            )
            self.assertEqual(first.status, "ACCEPTED")
            different = copy.deepcopy(candidate())
            different["entities"].append({
                "id": "paihuano", "name": "Paihuano", "entity_type": "organization",
                "sources": [SOURCE_URI], "evidence_refs": ["ev-1"],
            })
            different["coverage"][0]["entity_ids"].append("paihuano")
            with self.assertRaises(VersionConflictError):
                await engine.build_from_candidate_async(
                    antu=antu(), mapu_sources=[mapu()], actor=actor(),
                    candidate=CandidateBundle.from_dict(different),
                    request_key="req_test_fixed",
                )
