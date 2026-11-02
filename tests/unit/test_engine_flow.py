from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from kuyen.config import KuyenConfig
from kuyen.engine import KuyenEngine
from kuyen.ports.openviking import TaskSnapshot
from tests.helpers import SOURCE_URI, actor, antu, bundle, mapu

import kuyen as _kuyen


def _package_root() -> Path:
    """Directory of the installed package (assets ship as package data)."""
    return Path(_kuyen.__file__).resolve().parent



ROOT = _package_root()


class FakePort:
    def __init__(self):
        self.calls: list[tuple] = []

    async def health(self):
        self.calls.append(("health",))
        return {"status_code": 200}

    async def ensure_source(self, mapu, container_uri):
        self.calls.append(("ensure_source", mapu.mapu_id, container_uri))
        return SOURCE_URI

    async def verify_source(self, mapu, uri):
        self.calls.append(("verify_source", uri))

    async def wait_processed(self, timeout_s):
        self.calls.append(("wait_processed", timeout_s))
        return {"pending": 0}

    async def ensure_skill(self, skill_dir, target_uri):
        self.calls.append(("ensure_skill", target_uri))
        return "viking://agent/skills/knowledge-graph"

    async def compile(self, *, from_uris, to_uri, skill_uri, instruction):
        self.calls.append(("compile", tuple(from_uris), to_uri, skill_uri, instruction))
        return "cmp_fake"

    async def wait_task(self, task_id, timeout_s):
        self.calls.append(("wait_task", task_id, timeout_s))
        return TaskSnapshot(task_id=task_id, status="completed", raw={"status": "completed"})

    async def read_candidate(self, output_uri):
        self.calls.append(("read_candidate", output_uri))
        return bundle()

    async def close(self):
        self.calls.append(("close",))


class FlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_engine_uses_adapter_boundary_and_accepts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            port = FakePort()
            engine = KuyenEngine(
                KuyenConfig(
                    data_dir=Path(tmp) / "data",
                    ontology_path=ROOT / "config" / "ontologies" / "generic-v1.yaml",
                    skill_dir=ROOT / "skills" / "knowledge-graph",
                    source_container_uri="viking://resources/kuyen-test/source",
                    candidate_container_uri="viking://resources/kuyen-test/candidates",
                ),
                adapter=port,
            )
            result = await engine.build_async(
                antu=antu(), mapu_sources=[mapu()], actor=actor()
            )
            self.assertEqual(result.status, "ACCEPTED", result.error)
            calls = dict((item[0], item) for item in port.calls)
            self.assertIn("health", calls)
            self.assertIn("ensure_source", calls)
            self.assertIn("compile", calls)
            self.assertEqual(calls["compile"][1], ("viking://resources/kuyen-test/source",))
            self.assertTrue(calls["compile"][2].startswith("viking://resources/kuyen-test/candidates/"))
            self.assertIn("read_candidate", calls)
