from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

from kuyen.config import KuyenConfig
from kuyen.engine import KuyenEngine
from kuyen.serialization import KuyenSerializer
from tests.helpers import actor, antu, bundle, mapu

import kuyen as _kuyen


def _package_root() -> Path:
    """Directory of the installed package (assets ship as package data)."""
    return Path(_kuyen.__file__).resolve().parent



ROOT = _package_root()
SCHEMAS = ROOT / "schemas"


def validator(name: str) -> Draft202012Validator:
    schema = json.loads((SCHEMAS / name).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


class SchemaContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_antu_and_mapu_contracts(self) -> None:
        validator("antu.schema.json").validate(antu())
        validator("mapu.schema.json").validate(mapu().to_dict())
        # Candidate sidecar is a separate, deliberately permissive contract.
        validator("coverage.schema.json").validate({
            "source_uri": mapu().source_uri,
            "mapu_id": mapu().mapu_id,
            "unit_id": "whole-source",
            "state": "PROCESSED_WITH_OUTPUT",
        })

    async def test_graph_and_result_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine = KuyenEngine(KuyenConfig(
                data_dir=Path(tmp) / "data",
                ontology_path=ROOT / "config" / "ontologies" / "generic-v1.yaml",
                skill_dir=ROOT / "skills" / "knowledge-graph",
            ))
            result = await engine.build_from_candidate_async(
                antu=antu(), mapu_sources=[mapu()], actor=actor(), candidate=bundle()
            )
            self.assertEqual(result.status, "ACCEPTED", result.error)
            validator("result.schema.json").validate(result.to_dict())
            manifest = json.loads(Path(result.provenance_manifest).read_text(encoding="utf-8"))
            graph = json.loads((Path(result.provenance_manifest).parent / "graph.json").read_text(encoding="utf-8"))
            validator("kuyen.schema.json").validate(graph)
            self.assertEqual(manifest["content_digest"], result.content_digest)

    async def test_evidence_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine = KuyenEngine(KuyenConfig(
                data_dir=Path(tmp) / "data",
                ontology_path=ROOT / "config" / "ontologies" / "generic-v1.yaml",
                skill_dir=ROOT / "skills" / "knowledge-graph",
            ))
            result = await engine.build_from_candidate_async(
                antu=antu(), mapu_sources=[mapu()], actor=actor(), candidate=bundle()
            )
            graph = json.loads((Path(result.provenance_manifest).parent / "graph.json").read_text(encoding="utf-8"))
            for item in graph["evidence"]:
                validator("evidence.schema.json").validate(item)

    async def test_native_relations_only_have_native_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine = KuyenEngine(KuyenConfig(
                data_dir=Path(tmp) / "data",
                ontology_path=ROOT / "config" / "ontologies" / "generic-v1.yaml",
                skill_dir=ROOT / "skills" / "knowledge-graph",
            ))
            result = await engine.build_from_candidate_async(
                antu=antu(), mapu_sources=[mapu()], actor=actor(), candidate=bundle()
            )
            lines = (Path(result.provenance_manifest).parent / "native" / "relations.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertTrue(lines)
            for line in lines:
                row = json.loads(line)
                self.assertEqual(set(row), {"from", "relation", "label", "to", "evidence"})
                self.assertIsInstance(row["evidence"], list)
