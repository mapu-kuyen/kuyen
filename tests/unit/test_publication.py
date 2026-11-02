from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from kuyen.config import KuyenConfig
from kuyen.engine import KuyenEngine
from kuyen.ontology import Ontology
from kuyen.publication.coordinator import PublicationCoordinator
from kuyen.publication.planner import PublicationPlanner
from kuyen.publication.registry import PublicationRegistry
from kuyen.publication.verifier import PublicationVerifier
from tests.helpers import actor, antu, bundle, mapu

import kuyen as _kuyen


def _package_root() -> Path:
    """Directory of the installed package (assets ship as package data)."""
    return Path(_kuyen.__file__).resolve().parent



ROOT = _package_root()


class FakePublicationPort:
    def __init__(self):
        self.files: dict[str, str] = {}
        self.dirs: set[str] = set()
        self.acls: dict[str, dict] = {}

    async def health(self):
        return {"status": "ok"}

    async def stat(self, uri):
        return {"uri": uri} if uri in self.dirs or uri in self.files else None

    async def ls(self, uri, *, recursive=True):
        return list(self.files)

    async def read(self, uri):
        if uri not in self.files:
            raise FileNotFoundError(uri)
        return self.files[uri]

    async def mkdir(self, uri, *, acl=None):
        self.dirs.add(uri)
        if acl:
            self.acls[uri] = acl

    async def write(self, uri, content, *, mode="create", wait=True):
        self.dirs.add(uri.rsplit("/", 1)[0])
        self.files[uri] = content
        return {"uri": uri}

    async def batch_write(self, root_uri, operations, *, wait=True):
        for item in operations:
            await self.write(item["uri"], item["content"], mode=item.get("mode", "create"), wait=wait)
        return {"result": "ok"}

    async def acl_get(self, uri):
        acl = self.acls.get(uri) or {}
        entries = acl.get("entries") or []
        return {
            "acl_mode": acl.get("acl_mode", "restricted"),
            "effective_entries": entries,
        }

    async def wait_processed(self):
        return {"result": "ok"}

    async def close(self):
        return None


class PublicationTests(unittest.IsolatedAsyncioTestCase):
    async def test_plan_and_governed_publication(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine = KuyenEngine(KuyenConfig(
                data_dir=Path(tmp) / "data",
                ontology_path=ROOT / "config/ontologies/generic-v1.yaml",
                skill_dir=ROOT / "skills/knowledge-graph",
            ))
            result = await engine.build_from_candidate_async(
                antu=antu(), mapu_sources=[mapu()], actor=actor(), candidate=bundle()
            )
            self.assertEqual(result.status, "ACCEPTED", result.error)
            local = Path(result.provenance_manifest).parent
            ontology = Ontology.load(ROOT / "config/ontologies/generic-v1.yaml")
            plan = PublicationPlanner(
                root_uri="viking://resources/kuyen", namespace="unit",
                ontology=ontology,
            ).plan(local)
            self.assertEqual(plan.kuyen_id, result.kuyen_id)
            self.assertTrue(plan.publication_id.startswith("PUB-"))
            self.assertGreater(len(plan.artifacts), 5)
            port = FakePublicationPort()
            registry = PublicationRegistry(Path(tmp) / "data")
            record = await PublicationCoordinator(registry, PublicationVerifier()).publish(
                plan, actor=actor().to_dict(), adapter=port,
                acl={"acl_mode": "restricted", "entries": []},
            )
            self.assertEqual(record.status.value, "PUBLISHED")
            verification = await PublicationVerifier().verify_plan(plan, port, independent=True)
            self.assertEqual(verification.status.value, "VERIFIED", verification.errors)
            repeated = await PublicationCoordinator(registry, PublicationVerifier()).publish(
                plan, actor=actor().to_dict(), adapter=port,
                acl={"acl_mode": "restricted", "entries": []},
            )
            self.assertEqual(repeated.publication_id, record.publication_id)
            self.assertEqual(len([p for p in port.files if p.endswith("publication_manifest.json")]), 1)
