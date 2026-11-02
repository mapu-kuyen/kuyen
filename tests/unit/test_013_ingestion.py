"""0.1.3 ingestion: bounded wait, honest diagnostics, chunk-aware verification."""
from __future__ import annotations

import asyncio
import hashlib
import unittest

from kuyen.adapters.openviking import SdkOpenVikingAdapter
from kuyen.errors import AdapterError, IngestionTimeoutError
from kuyen.models import Mapu

SOURCE = "La cooperativa tiene 47 socios.\nLa fiesta se celebra en abril.\n"
URI = "viking://resources/test/MAPU-013/source.txt"


def mapu() -> Mapu:
    return Mapu(
        mapu_id="MAPU-013", version="1.0.0", source_uri=URI, content=SOURCE,
        sha256=hashlib.sha256(SOURCE.encode("utf-8")).hexdigest(),
    )


class EmptyError(Exception):
    pass


class FakeClient:
    def __init__(self, *, add=None, read=None, ls=None):
        self._add = add
        self._read = read
        self._ls = ls
        self.initialized = False

    async def initialize(self):
        self.initialized = True

    async def add_resource(self, path, to=None, wait=False):
        if self._add is None:
            return {"uri": URI}
        value = self._add
        if isinstance(value, Exception):
            raise value
        if callable(value):
            return await value()
        return value

    async def read(self, uri):
        if self._read is None:
            return SOURCE
        value = self._read(uri) if callable(self._read) else self._read
        if isinstance(value, Exception):
            raise value
        return value

    async def ls(self, uri, recursive=True, simple=True):
        value = self._ls(uri) if callable(self._ls) else (self._ls or [])
        if isinstance(value, Exception):
            raise value
        return value

    async def stat(self, uri):
        return {"result": {"isDir": False}}

    async def close(self):
        return None


class IngestionTests(unittest.IsolatedAsyncioTestCase):
    async def test_hanging_ingestion_is_bounded_and_typed(self):
        async def never():
            await asyncio.sleep(30)
            return {"uri": URI}

        adapter = SdkOpenVikingAdapter(url="http://127.0.0.1:1", client=FakeClient(add=never), ingestion_timeout_s=0.05)
        with self.assertRaises(IngestionTimeoutError) as ctx:
            await adapter.ensure_source(mapu(), "viking://resources/test")
        self.assertEqual(ctx.exception.code, "OPENVIKING_INGESTION_TIMEOUT")
        self.assertIn("timed out", ctx.exception.message)
        self.assertIn("MAPU-013", ctx.exception.message)
        self.assertEqual(ctx.exception.details["timeout_s"], 0.05)

    async def test_empty_provider_message_keeps_the_exception_class(self):
        adapter = SdkOpenVikingAdapter(url="http://127.0.0.1:1", client=FakeClient(add=EmptyError()), ingestion_timeout_s=5)
        with self.assertRaises(AdapterError) as ctx:
            await adapter.ensure_source(mapu(), "viking://resources/test")
        self.assertIn("EmptyError", ctx.exception.message)
        self.assertIn("(empty message)", ctx.exception.message)
        self.assertTrue(ctx.exception.message.strip().endswith("(empty message)"))

    async def test_add_resource_errors_are_not_silently_accepted(self):
        adapter = SdkOpenVikingAdapter(
            url="http://127.0.0.1:1",
            client=FakeClient(add={"status": "failed", "errors": [{"code": "PARSE", "message": "bad"}]}),
        )
        with self.assertRaises(AdapterError) as ctx:
            await adapter.ensure_source(mapu(), "viking://resources/test")
        self.assertIn("reported errors", ctx.exception.message)
        self.assertIn("PARSE", ctx.exception.message)

    async def test_chunked_resource_is_verified_as_exact_covering_slices(self):
        chunks = {
            "viking://resources/test/MAPU-013/part-1.md": SOURCE[:24],
            "viking://resources/test/MAPU-013/part-2.md": SOURCE[24:],
        }

        def read(uri):
            if uri == URI:
                raise ValueError("is a directory")
            return chunks[uri]

        adapter = SdkOpenVikingAdapter(
            url="http://127.0.0.1:1",
            client=FakeClient(read=read, ls=list(chunks)),
        )
        await adapter.verify_source(mapu(), URI)
        self.assertEqual(adapter.last_source_verification["mode"], "CHUNKED_EXACT_SLICES")
        self.assertEqual(adapter.last_source_verification["chunks"], 2)
        self.assertEqual(adapter.last_source_verification["covered_chars"], len("".join(SOURCE.split())))

    async def test_whitespace_inserted_by_markdown_renderer_is_equivalent(self):
        source = "## Historia\nRodrigo de Araya fue el primer viticultor.\n"
        chunks = {"viking://resources/test/MAPU-W/part-1.md": "## Historia\n\nRodrigo de Araya fue el primer viticultor.\n"}

        def read(uri):
            if uri == URI:
                raise ValueError("is a directory")
            return chunks[uri]

        mapu_w = Mapu(
            mapu_id="MAPU-013", version="1.0.0", source_uri=URI, content=source,
            sha256=hashlib.sha256(source.encode("utf-8")).hexdigest(),
        )
        client = FakeClient(read=read, ls=list(chunks))
        adapter = SdkOpenVikingAdapter(url="http://127.0.0.1:1", client=client)
        await adapter.verify_source(mapu_w, URI)
        self.assertEqual(adapter.last_source_verification["mode"], "CHUNKED_WHITESPACE_EQUIVALENT")
        self.assertEqual(adapter.last_source_verification["normalization"], "whitespace-insensitive")

    async def test_chunk_gap_is_a_hard_failure(self):
        chunks = {
            "viking://resources/test/MAPU-013/part-1.md": SOURCE[:10],
            "viking://resources/test/MAPU-013/part-2.md": SOURCE[20:],
        }

        def read(uri):
            if uri == URI:
                raise ValueError("is a directory")
            return chunks[uri]

        adapter = SdkOpenVikingAdapter(
            url="http://127.0.0.1:1",
            client=FakeClient(read=read, ls=list(chunks)),
        )
        with self.assertRaises(AdapterError) as ctx:
            await adapter.verify_source(mapu(), URI)
        self.assertIn("do not cover", ctx.exception.message)

    async def test_chunk_not_in_source_is_a_hard_failure(self):
        chunks = {
            "viking://resources/test/MAPU-013/part-1.md": "texto inventado por el proveedor",
        }

        def read(uri):
            if uri == URI:
                raise ValueError("is a directory")
            return chunks[uri]

        adapter = SdkOpenVikingAdapter(
            url="http://127.0.0.1:1",
            client=FakeClient(read=read, ls=list(chunks)),
        )
        with self.assertRaises(AdapterError) as ctx:
            await adapter.verify_source(mapu(), URI)
        self.assertIn("not a source slice", ctx.exception.message)

    async def test_exact_single_resource_still_verifies(self):
        adapter = SdkOpenVikingAdapter(url="http://127.0.0.1:1", client=FakeClient())
        await adapter.verify_source(mapu(), URI)
        self.assertEqual(adapter.last_source_verification["mode"], "EXACT_RESOURCE")


class SkillClient(FakeClient):
    def __init__(self, content: str = "old skill"):
        super().__init__()
        self.content = content
        self.updated = False

    async def get_skill(self, name, **kwargs):
        return {"result": {"name": name, "content": self.content}}

    async def update_skill(self, name, data, wait=False, options=None):
        from pathlib import Path

        self.content = (Path(data) / "SKILL.md").read_text(encoding="utf-8")
        self.updated = True
        return {"result": {"name": name}}

    async def add_skill(self, path, wait=False, options=None):
        from pathlib import Path

        self.content = (Path(path) / "SKILL.md").read_text(encoding="utf-8")
        return {"result": {"name": "knowledge-graph"}}


class SkillTests(unittest.IsolatedAsyncioTestCase):
    async def test_stale_skill_is_updated_not_silently_kept(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as directory:
            skill = Path(directory) / "knowledge-graph"
            skill.mkdir()
            (skill / "SKILL.md").write_text("# new skill content\n", encoding="utf-8")
            client = SkillClient("old skill")
            adapter = SdkOpenVikingAdapter(url="http://127.0.0.1:1", client=client)
            uri = await adapter.ensure_skill(str(skill), "viking://agent/skills")
            self.assertEqual(uri, "viking://agent/skills/knowledge-graph")
            self.assertTrue(client.updated)
            self.assertEqual(client.content, "# new skill content\n")

    async def test_provider_yaml_rewrap_is_not_a_different_skill(self):
        import tempfile
        from pathlib import Path

        local = (
            "---\nname: k\ndescription: a long description that wraps in the provider\n---\n\n"
            "# body\n\ntext\n"
        )
        provider = (
            "---\nname: k\ndescription: a long description that wraps in the\n"
            "  provider\n---\n\n# body\n\ntext"
        )
        with tempfile.TemporaryDirectory() as directory:
            skill = Path(directory) / "knowledge-graph"
            skill.mkdir()
            (skill / "SKILL.md").write_text(local, encoding="utf-8")
            client = SkillClient(provider)
            adapter = SdkOpenVikingAdapter(url="http://127.0.0.1:1", client=client)
            await adapter.ensure_skill(str(skill), "viking://agent/skills")
            self.assertFalse(client.updated)

    async def test_provider_copy_that_cannot_be_updated_is_an_error(self):
        import tempfile
        from pathlib import Path

        class Stubborn(SkillClient):
            async def update_skill(self, name, data, wait=False, options=None):
                return {"result": {"name": name}}  # does not change content

        with tempfile.TemporaryDirectory() as directory:
            skill = Path(directory) / "knowledge-graph"
            skill.mkdir()
            (skill / "SKILL.md").write_text("# new skill content\n", encoding="utf-8")
            adapter = SdkOpenVikingAdapter(url="http://127.0.0.1:1", client=Stubborn("old skill"))
            with self.assertRaises(AdapterError) as ctx:
                await adapter.ensure_skill(str(skill), "viking://agent/skills")
            self.assertIn("does not match the local version", ctx.exception.message)


class CompileModeTests(unittest.IsolatedAsyncioTestCase):
    async def test_default_compile_is_full(self):
        class Client(FakeClient):
            options = None

            async def compile(self, from_uris, to, skill, options=None):
                self.options = options
                return {"result": {"task_id": "cmp_full"}}

        client = Client()
        adapter = SdkOpenVikingAdapter(url="http://127.0.0.1:1", client=client)
        task = await adapter.compile(
            from_uris=["viking://resources/source"], to_uri="viking://resources/out",
            skill_uri="viking://agent/skills/knowledge-graph", instruction="extract",
        )
        self.assertEqual(task, "cmp_full")
        self.assertEqual(client.options["args"]["mode"], "full")
        self.assertEqual(client.options["instruction"], "extract")

    async def test_incremental_mode_is_explicit_and_validated(self):
        class Client(FakeClient):
            options = None

            async def compile(self, from_uris, to, skill, options=None):
                self.options = options
                return {"result": {"task_id": "cmp_inc"}}

        client = Client()
        adapter = SdkOpenVikingAdapter(url="http://127.0.0.1:1", client=client, compile_mode="incremental")
        await adapter.compile(
            from_uris=["viking://resources/source"], to_uri="viking://resources/out",
            skill_uri="viking://agent/skills/knowledge-graph", instruction="extract",
        )
        self.assertEqual(client.options["args"]["mode"], "incremental")
        with self.assertRaises(ValueError):
            SdkOpenVikingAdapter(url="http://127.0.0.1:1", client=client, compile_mode="partial")


if __name__ == "__main__":
    unittest.main()
