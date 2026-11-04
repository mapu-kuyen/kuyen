from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path

from kuyen.config import KuyenConfig
from kuyen.engine import KuyenEngine
from kuyen.errors import InvalidRequestError
from kuyen.execution import ExecutionState
from kuyen.models import CandidateBundle
from kuyen.normalization import normalize_bundle
from tests.helpers import SOURCE_URI, actor, antu, bundle, candidate, mapu

import kuyen as _kuyen


def _package_root() -> Path:
    """Directory of the installed package (assets ship as package data)."""
    return Path(_kuyen.__file__).resolve().parent




def engine_for(tmp: str) -> KuyenEngine:
    root = _package_root()
    return KuyenEngine(KuyenConfig(
        data_dir=Path(tmp) / "data",
        ontology_path=root / "config" / "ontologies" / "generic-v1.yaml",
        skill_dir=root / "skills" / "knowledge-graph",
    ))


class Contract011Tests(unittest.IsolatedAsyncioTestCase):
    async def test_config_has_no_public_credential_resolver(self) -> None:
        config = KuyenConfig(
            data_dir=Path("/tmp/kuyen-011-unit"),
            ontology_path=Path("/tmp/ontology.yaml"), skill_dir=Path("/tmp/skill"),
        )
        self.assertFalse(hasattr(config, "openviking_api_key"))
        self.assertNotIn("api_key", config.public_dict())

    async def test_strict_antu_rejects_unknown_scope_field(self) -> None:
        value = antu(scope={"include": ["x"], "exclude": [], "unexpected": True})
        with self.assertRaises(InvalidRequestError) as context:
            from kuyen.models import Antu
            Antu.from_dict(value)
        self.assertEqual(context.exception.details["code"], "ANTU_UNKNOWN_FIELD")
        self.assertEqual(context.exception.details["path"], "scope.unexpected")

    async def test_orphan_endpoint_keeps_original_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = await engine_for(tmp).build_from_candidate_async(
                antu=antu(), mapu_sources=[mapu()], actor=actor(), candidate=bundle(valid=False)
            )
            self.assertEqual(result.status, "REJECTED")
            self.assertTrue(any(item.code == "ORPHAN_ENDPOINT" and item.message == "missing-entity" for item in result.validation.issues))

    async def test_source_identity_separates_same_name(self) -> None:
        value = candidate()
        value["entities"] = [
            {"id": "9", "name": "Nueve integrantes", "entity_type": "organization", "sources": [SOURCE_URI], "evidence_refs": ["ev-1"]},
            {"id": "nueve-integrantes", "name": "Nueve integrantes", "entity_type": "organization", "sources": [SOURCE_URI], "evidence_refs": ["ev-1"]},
        ]
        value["relations"] = []
        value["coverage"][0]["entity_ids"] = ["9", "nueve-integrantes"]
        graph = normalize_bundle(
            bundle=CandidateBundle.from_dict(value), antu_id="ANTU-KUYEN-TEST-001",
            mapus=[mapu()], version="1.0.0", provenance={"test": "identity"},
        )
        self.assertEqual(len({item.entity_id for item in graph.entities}), 2)
        self.assertEqual({item.source_entity_id for item in graph.entities}, {"9", "nueve-integrantes"})

    async def test_epistemic_input_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            value = candidate()
            value["assertions"] = [{
                "subject": "asociacion-rio-claro", "predicate": "has_member_count",
                "value": {"value_type": "integer", "value": 9},
                "polarity": "POSITIVE",
                "sources": [SOURCE_URI], "evidence_refs": ["ev-2"], "epistemic_status": "UNRESOLVED",
            }]
            result = await engine_for(tmp).build_from_candidate_async(
                antu=antu(relation_types=["coordinates", "located_in", "has_member", "has_member_count"]),
                mapu_sources=[mapu()], actor=actor(), candidate=CandidateBundle.from_dict(value)
            )
            self.assertEqual(result.status, "ACCEPTED")
            graph = json.loads((Path(result.provenance_manifest).parent / "graph.json").read_text(encoding="utf-8"))
            self.assertEqual(graph["assertions"][0]["proposed_status"], "UNRESOLVED")
            self.assertEqual(graph["assertions"][0]["status"], "UNRESOLVED")

    async def test_submit_is_recoverable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine = engine_for(tmp)
            handle = engine.submit(antu=antu(), mapu_sources=[mapu()], actor=actor(), candidate=bundle())
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if engine.get_status(handle.execution_id).state is ExecutionState.ACCEPTED:
                    break
                time.sleep(0.01)
            result = engine.get_result(handle.execution_id)
            restarted = engine_for(tmp)
            self.assertEqual(result.status, "ACCEPTED")
            self.assertEqual(restarted.get_status(handle.execution_id).state, ExecutionState.ACCEPTED)
