from __future__ import annotations

import json
import unittest

from kuyen.adapters.openviking import SdkOpenVikingAdapter
from kuyen.errors import AdapterError
from tests.helpers import mapu
from pathlib import Path


class FakeClient:
    def __init__(self):
        self.compiled = False
        self.resources = {}
        self.skills = {}
        self.artifacts = {
            "viking://resources/kuyen/candidates/req_x/entities/alpha.md": "---\ntype: entity\nid: alpha\ntitle: Alpha\nentity_type: concept\nsources:\n  - viking://resources/source.md\n---\n\nAlpha.\n",
            "viking://resources/kuyen/candidates/req_x/relations.jsonl": '{"from":"alpha","relation":"related_to","label":"se relaciona con","to":"alpha","evidence":["viking://resources/source.md"]}\n',
        }

    async def add_resource(self, path, to=None, wait=False):
        with open(path, encoding="utf-8") as handle:
            self.resources["viking://resources/kuyen/sources/MAPU-TEST/MAPU-TEST.txt"] = handle.read()
        return {"result": {"uri": "viking://resources/kuyen/sources/MAPU-TEST/MAPU-TEST.txt"}}

    async def read(self, uri, **kwargs):
        return {"result": self.resources.get(uri, self.artifacts.get(uri, ""))}

    async def wait_processed(self):
        return {"result": {"pending": 0}}

    async def get_skill(self, name, **kwargs):
        return {"result": {"name": name}}

    async def add_skill(self, path, wait=False, options=None):
        self.skills[path] = True
        return {"result": {"name": "knowledge-graph"}}

    async def compile(self, from_uris, to, skill, options=None):
        self.compiled = True
        return {"result": {"task_id": "cmp_test"}}

    async def get_task(self, task_id):
        return {"result": {"status": "completed", "task_id": task_id}}

    async def ls(self, uri, **kwargs):
        return {"result": list(self.artifacts)}

    async def close(self):
        return None


class AdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_public_methods_and_native_read(self) -> None:
        fake = FakeClient()
        adapter = SdkOpenVikingAdapter(url="http://127.0.0.1:1", api_key="not-a-secret", client=fake)
        source_uri = await adapter.ensure_source(mapu(), "viking://resources/kuyen/sources")
        self.assertTrue(source_uri.startswith("viking://"))
        await adapter.wait_processed(1)
        import kuyen as _kuyen

        skill_dir = str(Path(_kuyen.__file__).resolve().parent / "skills" / "knowledge-graph")
        skill = await adapter.ensure_skill(skill_dir, "viking://agent/skills")
        self.assertTrue(skill.endswith("knowledge-graph"))
        task = await adapter.compile(
            from_uris=[source_uri], to_uri="viking://resources/kuyen/candidates/req_x",
            skill_uri=skill, instruction="test",
        )
        self.assertEqual(task, "cmp_test")
        snapshot = await adapter.wait_task(task, 1)
        self.assertEqual(snapshot.status, "completed")
        bundle = await adapter.read_candidate("viking://resources/kuyen/candidates/req_x")
        self.assertEqual(len(bundle.entities), 1)
        self.assertEqual(bundle.relations[0].relation, "related_to")
        await adapter.close()

    async def test_content_mismatch_is_rejected(self) -> None:
        fake = FakeClient()
        adapter = SdkOpenVikingAdapter(url="http://127.0.0.1:1", api_key="x", client=fake)
        fake.resources["viking://resources/kuyen/sources/MAPU-TEST/MAPU-TEST.txt"] = "tampered"
        with self.assertRaises(AdapterError):
            await adapter.verify_source(mapu(), "viking://resources/kuyen/sources/MAPU-TEST/MAPU-TEST.txt")
