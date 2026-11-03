"""0.1.4 materialization: provider proposal -> canonical candidate."""
from __future__ import annotations

import asyncio
import hashlib
import tempfile
import unittest
from pathlib import Path

from kuyen.config import KuyenConfig
from kuyen.coverage import inventory_sections
from kuyen.engine import KuyenEngine
from kuyen.errors import CandidateMaterializationError
from kuyen.materialization import CandidateMaterializer, PathOwnershipRegistry
from kuyen.models import ActorContext, CandidateBundle, Mapu

import kuyen as _kuyen


def _package_root() -> Path:
    """Directory of the installed package (assets ship as package data)."""
    return Path(_kuyen.__file__).resolve().parent



ROOT = _package_root()
ONTO = ROOT / "config/ontologies/generic-v1.yaml"
SKILL = ROOT / "skills/knowledge-graph"
SOURCE = "La organización Alpha está en Beta. Alpha tiene 47 socios.\n"
URI = "viking://resources/test/MAPU-MAT/source.md"
SHA = hashlib.sha256(SOURCE.encode("utf-8")).hexdigest()
Q1 = "La organización Alpha está en Beta."
Q2 = "Alpha tiene 47 socios."


def mapu() -> Mapu:
    return Mapu(mapu_id="MAPU-MAT", version="1.0.0", source_uri=URI, content=SOURCE, sha256=SHA)


def actor() -> ActorContext:
    return ActorContext(
        leftraru_id="LR-MAT", authenticated_account="mat", authenticated_user="mat",
        service_identity="svc-mat", antu_author="agent-design", candidate_producer="provider",
    )


def antu(**overrides):
    value = {
        "antu_id": "ANTU-MAT", "version": "1.0.0", "purpose": "materialization test",
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


def ev(quote: str, *, offsets: bool = True, uri: str | None = URI) -> dict:
    item = {"quote": quote}
    if offsets:
        start = SOURCE.index(quote)
        item.update({"char_start": start, "char_end": start + len(quote), "offset_unit": "unicode_codepoint"})
    if uri:
        item["source_uri"] = uri
        item["source_sha256"] = SHA
        item["mapu_id"] = "MAPU-MAT"
    return item


def provider_result(*, offsets: bool = True, uri_only: bool = False, coverage=None, entity_quote: str = Q1) -> dict:
    evidence = [{"source_uri": URI}] if uri_only else [ev(entity_quote, offsets=offsets)]
    return {
        "schema_version": "kuyen-provider-result-v1",
        "provider": {"name": "test"},
        "entities": [
            {"provider_id": "alpha", "name": "Alpha", "entity_type": "organization", "evidence": evidence},
            {"provider_id": "beta", "name": "Beta", "entity_type": "place",
             "evidence": [{"source_uri": URI}] if uri_only else [ev(Q1, offsets=offsets)]},
        ],
        "relations": [
            {"from": "alpha", "to": "beta", "predicate": "located_in", "label": "se ubica en",
             "polarity": "POSITIVE",
             "evidence": [{"source_uri": URI}] if uri_only else [ev(Q1, offsets=offsets)]},
        ],
        "assertions": [
            {"subject": "alpha", "predicate": "has_member_count",
             "value": {"value_type": "integer", "value": 47, "unit": "socios"},
             "polarity": "POSITIVE",
             "evidence": [{"source_uri": URI}] if uri_only else [ev(Q2, offsets=offsets)]},
        ],
        "coverage": coverage if coverage is not None else [
            {"unit_id": "u00", "state": "PROCESSED_WITH_OUTPUT"},
        ],
    }


def materialize(result: dict):
    m = mapu()
    inventory = {"MAPU-MAT": inventory_sections(SOURCE, mapu_id="MAPU-MAT")}
    materializer = CandidateMaterializer(mapus=[m], antu=_antu_obj(), coverage_inventory=inventory)
    return m, materializer.materialize({"kuyen_result.json": __import__("json").dumps(result)}, provider={"task_id": "cmp_test"})


def _antu_obj():
    from kuyen.models import Antu

    return Antu.from_dict(antu())


def evaluate(bundle: CandidateBundle, *, antu_overrides=None, profile="document-sections-v1"):
    with tempfile.TemporaryDirectory() as directory:
        engine = KuyenEngine(KuyenConfig(
            data_dir=Path(directory) / "data", ontology_path=ONTO, skill_dir=SKILL,
            coverage_profile=profile,
        ))
        return asyncio.run(engine.build_from_candidate_async(
            antu=antu(**(antu_overrides or {})), mapu_sources=[mapu()],
            actor=actor(), candidate=bundle,
        ))


class MaterializerTests(unittest.TestCase):
    def test_exact_evidence_materializes_and_is_accepted(self):
        _, materialized = materialize(provider_result())
        self.assertEqual(len(materialized.bundle.entities), 2)
        self.assertEqual(len(materialized.bundle.relations), 1)
        self.assertEqual(len(materialized.bundle.assertions), 1)
        self.assertEqual(materialized.manifest["evidence"].get("EXACT_SPAN"), 4)
        result = evaluate(materialized.bundle)
        self.assertEqual(result.status, "ACCEPTED", result.validation.to_dict())

    def test_unique_quote_without_offsets_is_resolved(self):
        _, materialized = materialize(provider_result(offsets=False))
        self.assertGreaterEqual(materialized.manifest["evidence"].get("OFFSET_RESOLVED_UNIQUE", 0), 4)
        self.assertTrue(all(item.char_start is not None for item in materialized.bundle.evidence))
        result = evaluate(materialized.bundle)
        self.assertEqual(result.status, "ACCEPTED", result.validation.to_dict())

    def test_ambiguous_quote_is_not_resolved(self):
        _, materialized = materialize(provider_result(offsets=False, entity_quote="Alpha"))
        self.assertIn("AMBIGUOUS_QUOTE", materialized.manifest["evidence"])
        result = evaluate(materialized.bundle)
        self.assertEqual(result.status, "REJECTED")
        self.assertIn("ENTITY_EVIDENCE_MISSING", {x.code for x in result.validation.issues})

    def test_uri_only_is_a_document_reference_not_a_quote(self):
        _, materialized = materialize(provider_result(uri_only=True))
        self.assertEqual(len(materialized.bundle.evidence), 0)
        self.assertIn("DOCUMENT_REFERENCE", materialized.manifest["evidence"])
        strict = evaluate(materialized.bundle)
        self.assertEqual(strict.status, "REJECTED")
        document = evaluate(materialized.bundle, antu_overrides={"evidence_policy": "document", "coverage_policy": "not_required"})
        self.assertEqual(document.status, "ACCEPTED", document.validation.to_dict())

    def test_duplicate_provider_entity_id_is_rejected(self):
        result = provider_result()
        result["entities"].append(dict(result["entities"][0]))
        with self.assertRaises(CandidateMaterializationError) as ctx:
            materialize(result)
        self.assertIn("duplicated", ctx.exception.message)

    def test_path_traversal_and_absolute_are_rejected(self):
        m = mapu()
        materializer = CandidateMaterializer(mapus=[m], antu=_antu_obj())
        with self.assertRaises(CandidateMaterializationError):
            materializer.materialize({"../evil.json": "{}"})
        materializer = CandidateMaterializer(mapus=[m], antu=_antu_obj())
        with self.assertRaises(CandidateMaterializationError):
            materializer.materialize({"/etc/passwd": "{}"})

    def test_duplicate_paths_registry(self):
        with self.assertRaises(CandidateMaterializationError):
            PathOwnershipRegistry().assert_unique(["entities/a.md", "entities/a.md"])

    def test_declared_offsets_never_override_the_quote(self):
        """The quote is the authority; a declared offset that disagrees is recorded, not obeyed.

        This is the documented policy change of KUYEN_PRODUCTIVE_GRAPH_11 §5.2: the model's
        offsets are a hint. A verifiable exact quote is never discarded because the hint is
        wrong, and the disagreement is never silent — it is a recorded decision and the
        declared values are kept as auxiliary information.
        """
        result = provider_result()
        result["entities"][0]["evidence"][0]["char_end"] = 1
        _, materialized = materialize(result)
        self.assertIn("QUOTE_AUTHORITATIVE", materialized.manifest["evidence"])
        ignored = next(item for item in materialized.manifest["decisions"]
                       if item["classification"] == "QUOTE_AUTHORITATIVE")
        self.assertEqual(ignored["char_start"], SOURCE.index(Q1))
        self.assertEqual(ignored["char_end"], SOURCE.index(Q1) + len(Q1))
        preserved = next(item for item in materialized.bundle.evidence if item.quote == Q1)
        self.assertEqual(preserved.char_start, SOURCE.index(Q1))
        self.assertEqual(preserved.declared_offsets, {"char_start": 0, "char_end": 1})
        accepted = evaluate(materialized.bundle)
        self.assertEqual(accepted.status, "ACCEPTED", accepted.validation.to_dict())

    def test_a_quote_that_does_not_exist_is_still_rejected(self):
        result = provider_result()
        result["entities"][0]["evidence"][0]["quote"] = "esta frase no está en la fuente"
        result["entities"][0]["evidence"][0]["char_start"] = 0
        result["entities"][0]["evidence"][0]["char_end"] = 32
        _, materialized = materialize(result)
        self.assertIn("INVALID_QUOTE", materialized.manifest["evidence"])
        rejected = evaluate(materialized.bundle)
        self.assertEqual(rejected.status, "REJECTED")

    def test_coverage_is_derived_not_trusted(self):
        _, materialized = materialize(provider_result(uri_only=True, coverage=[{"unit_id": "u00", "state": "PROCESSED_WITH_OUTPUT"}]))
        unit = materialized.bundle.coverage[0]
        self.assertEqual(unit.state.value, "PROCESSED_NO_GRAPH_FACTS")
        self.assertIn("no verified evidence", unit.reason or "")

    def test_unknown_provider_unit_is_ignored(self):
        _, materialized = materialize(provider_result(coverage=[{"unit_id": "u99", "state": "PROCESSED_WITH_OUTPUT"}]))
        self.assertEqual(materialized.bundle.coverage[0].unit_id, "u00")
        self.assertIn("u99", materialized.manifest["coverage"]["unknown_provider_units"])
        self.assertEqual(materialized.bundle.coverage[0].state.value, "PROCESSED_WITH_OUTPUT")
        result = evaluate(materialized.bundle)
        self.assertEqual(result.status, "ACCEPTED", result.validation.to_dict())

    def test_self_relation_and_unknown_predicate_reach_the_validators(self):
        result = provider_result()
        result["relations"] = [
            {"from": "alpha", "to": "alpha", "predicate": "headquartered_in", "label": "tiene sede en",
             "polarity": "POSITIVE", "evidence": [ev(Q1)]},
            {"from": "alpha", "to": "beta", "predicate": "celebrated_in", "label": "celebra en",
             "polarity": "POSITIVE", "evidence": [ev(Q1)]},
        ]
        _, materialized = materialize(result)
        evaluated = evaluate(materialized.bundle)
        codes = {x.code for x in evaluated.validation.issues}
        self.assertIn("SELF_RELATION", codes)
        self.assertIn("PREDICATE_NOT_ALLOWED", codes)

    def test_legacy_sidecar_is_still_read(self):
        m = mapu()
        legacy = {
            "entities": [{"id": "alpha", "name": "Alpha", "entity_type": "organization", "sources": [URI]}],
            "relations": [], "assertions": [], "evidence": [],
            "coverage": [{"source_uri": URI, "mapu_id": "MAPU-MAT", "unit_id": "u00",
                          "state": "PROCESSED_NO_GRAPH_FACTS"}],
        }
        materializer = CandidateMaterializer(mapus=[m], antu=_antu_obj(), coverage_inventory={"MAPU-MAT": inventory_sections(SOURCE, mapu_id="MAPU-MAT")})
        materialized = materializer.materialize({"kuyen_candidates.json": __import__("json").dumps(legacy)})
        self.assertEqual(materialized.manifest["mode"], "legacy_sidecar")
        self.assertEqual(len(materialized.bundle.entities), 1)

    def test_json_fence_is_tolerated_without_changing_content(self):
        import json as jsonlib

        result = provider_result()
        text = "```json\n" + jsonlib.dumps(result, ensure_ascii=False) + "\n```\n"
        m = mapu()
        materializer = CandidateMaterializer(mapus=[m], antu=_antu_obj(), coverage_inventory={"MAPU-MAT": inventory_sections(SOURCE, mapu_id="MAPU-MAT")})
        materialized = materializer.materialize({"kuyen_result.json": text})
        self.assertIn("stripped a Markdown fence", " ".join(materialized.manifest["warnings"]))
        self.assertEqual(len(materialized.bundle.evidence), 2)

    def test_native_fallback_has_no_assertions(self):
        m = mapu()
        artifacts = {
            "entities/alpha.md": "---\nid: alpha\ntitle: Alpha\nentity_type: organization\nsources:\n  - " + URI + "\n---\n\nAlpha.\n",
            "relations.jsonl": __import__("json").dumps({"from": "alpha", "relation": "located_in", "to": "beta", "label": "se ubica en", "evidence": [URI]}) + "\n",
        }
        materializer = CandidateMaterializer(mapus=[m], antu=_antu_obj(), coverage_inventory={"MAPU-MAT": inventory_sections(SOURCE, mapu_id="MAPU-MAT")})
        materialized = materializer.materialize(artifacts)
        self.assertEqual(materialized.manifest["mode"], "native_structured")
        self.assertEqual(len(materialized.bundle.entities), 1)
        self.assertEqual(len(materialized.bundle.assertions), 0)
        self.assertEqual(len(materialized.bundle.evidence), 0)


def materialize_tree(artifacts: dict):
    m = mapu()
    inventory = {"MAPU-MAT": inventory_sections(SOURCE, mapu_id="MAPU-MAT")}
    return m, CandidateMaterializer(mapus=[m], antu=_antu_obj(),
                                   coverage_inventory=inventory).materialize(artifacts)


class NativePredicatePreservationTests(unittest.TestCase):
    """A predicate the producer declares is preserved, never turned into a generic one."""

    def _native_tree(self):
        import json

        return {
            "entities/municipalidad.md": (
                "---\nid: municipalidad\nname: Municipalidad\nentity_type: organization\n"
                f"sources:\n  - {URI}\n"
                f"evidence:\n  - quote: \"{Q1}\"\n    source_uri: {URI}\n    mapu_id: MAPU-MAT\n"
                "---\n\nCuerpo.\n"),
            "entities/alpha.md": (
                "---\nid: alpha\nname: Alpha\nentity_type: organization\n"
                f"sources:\n  - {URI}\n"
                f"evidence:\n  - quote: \"{Q2}\"\n    source_uri: {URI}\n    mapu_id: MAPU-MAT\n"
                "---\n\nCuerpo.\n"),
            "assertions.jsonl": json.dumps({
                "subject": "alpha", "predicate": "installed_lights",
                "value": {"value_type": "integer", "value": "47"},
                "polarity": "POSITIVE", "modality": "FACT",
                "evidence": [{"quote": Q2, "source_uri": URI, "mapu_id": "MAPU-MAT"}],
            }) + "\n",
        }

    def test_a_declared_native_scalar_predicate_is_preserved_with_a_warning(self):
        _, materialized = materialize_tree(self._native_tree())
        self.assertEqual(materialized.bundle.assertions[0].source_predicate, "installed_lights")
        result = evaluate(materialized.bundle)
        codes = {item.code: item.severity for item in result.validation.issues}
        self.assertEqual(codes.get("SCALAR_PREDICATE_PRESERVED_UNMAPPED"), "WARNING")
        self.assertNotIn("SCALAR_PREDICATE_UNKNOWN", codes)
        self.assertEqual(result.status, "ACCEPTED", result.validation.to_dict())

    def test_an_undeclared_unknown_predicate_stays_an_error(self):
        bundle = CandidateBundle.from_dict({
            "entities": [{"id": "a", "name": "A", "entity_type": "organization",
                          "sources": [URI], "evidence_refs": ["ev-1"]}],
            "relations": [], "coverage": [],
            "assertions": [{"subject": "a", "predicate": "invented_scalar",
                            "value": {"value_type": "integer", "value": 1},
                            "polarity": "POSITIVE", "sources": [URI],
                            "evidence_refs": ["ev-1"]}],
            "evidence": [{"evidence_id": "ev-1", "mapu_id": "MAPU-MAT",
                          "source_uri": URI, "source_sha256": SHA, "quote": Q1,
                          "char_start": SOURCE.index(Q1),
                          "char_end": SOURCE.index(Q1) + len(Q1),
                          "offset_unit": "unicode_codepoint", "extraction_method": "test"}],
        })
        result = evaluate(bundle)
        self.assertEqual(result.status, "REJECTED")
        self.assertIn("SCALAR_PREDICATE_UNKNOWN", {item.code for item in result.validation.errors})


if __name__ == "__main__":
    unittest.main()


class ProviderArtifactTests(unittest.IsolatedAsyncioTestCase):
    async def test_adapter_skips_directories_and_hidden_summaries(self):
        from types import SimpleNamespace

        from kuyen.adapters.openviking import SdkOpenVikingAdapter

        class Client:
            async def initialize(self):
                return None

            async def ls(self, uri, recursive=True, simple=True):
                return ["viking://out/a.md", "viking://out/.abstract.md", "viking://out/sub", "viking://out/sub/b.md"]

            async def stat(self, uri):
                return {"result": {"isDir": uri.endswith("/sub")}}

            async def read(self, uri):
                return "content-" + uri.rsplit("/", 1)[-1]

        adapter = SdkOpenVikingAdapter(url="http://127.0.0.1:1", client=Client())
        artifacts = await adapter.read_provider_artifacts("viking://out")
        self.assertEqual(sorted(artifacts), ["a.md", "sub/b.md"])
        self.assertEqual(artifacts["a.md"], "content-a.md")
        self.assertEqual(adapter.last_provider_artifacts["count"], 2)

    async def test_adapter_rejects_duplicate_listing_paths(self):
        from kuyen.adapters.openviking import SdkOpenVikingAdapter
        from kuyen.errors import CandidateMaterializationError

        class Client:
            async def initialize(self):
                return None

            async def ls(self, uri, recursive=True, simple=True):
                return ["viking://out/a.md", "viking://out/a.md"]

            async def stat(self, uri):
                return {"result": {"isDir": False}}

            async def read(self, uri):
                return "x"

        adapter = SdkOpenVikingAdapter(url="http://127.0.0.1:1", client=Client())
        with self.assertRaises(CandidateMaterializationError):
            await adapter.read_provider_artifacts("viking://out")


class EngineMaterializationIntegrationTests(unittest.TestCase):
    def test_engine_materializes_provider_result_and_persists_manifest(self):
        from types import SimpleNamespace

        class Adapter:
            async def health(self):
                return {"status_code": 200}

            async def ensure_source(self, mapu, container_uri):
                return URI

            async def wait_processed(self, timeout_s):
                return {}

            async def ensure_skill(self, skill_dir, target_uri):
                return "viking://agent/skills/knowledge-graph"

            async def compile(self, *, from_uris, to_uri, skill_uri, instruction):
                return "cmp_test"

            async def wait_task(self, task_id, timeout_s):
                return SimpleNamespace(status="completed", raw={"task_id": task_id})

            async def read_provider_artifacts(self, output_uri):
                return {"kuyen_result.json": __import__("json").dumps(provider_result())}

            async def close(self):
                return None

        with tempfile.TemporaryDirectory() as directory:
            engine = KuyenEngine(KuyenConfig(
                data_dir=Path(directory) / "data", ontology_path=ONTO, skill_dir=SKILL,
                coverage_profile="document-sections-v1",
            ))
            result = asyncio.run(engine.build_async(
                antu=antu(), mapu_sources=[mapu()], actor=actor(), adapter=Adapter(),
            ))
            self.assertEqual(result.status, "ACCEPTED", result.validation.to_dict())
            version_dir = engine.registry.versions / result.kuyen_id / result.version
            graph = __import__("json").loads((version_dir / "graph.json").read_text(encoding="utf-8"))
            self.assertEqual(graph["provenance"]["materialization"]["mode"], "structured_provider_result")
            self.assertEqual(graph["provenance"]["materialization"]["evidence"].get("EXACT_SPAN"), 4)


if __name__ == "__main__":
    unittest.main()


class NativeStructuredTests(unittest.TestCase):
    def artifacts(self):
        alpha = (
            "---\nid: alpha\nname: Alpha\nentity_type: organization\nsources:\n  - " + URI + "\n"
            "evidence:\n  - quote: " + __import__("json").dumps(Q1) + "\n    char_start: " + str(SOURCE.index(Q1)) + "\n"
            "    char_end: " + str(SOURCE.index(Q1) + len(Q1)) + "\n    source_uri: " + URI + "\n"
            "    source_sha256: " + SHA + "\n    mapu_id: MAPU-MAT\n---\n\nAlpha.\n"
        )
        beta = (
            "---\nid: beta\nname: Beta\nentity_type: place\nsources:\n  - " + URI + "\n"
            "evidence:\n  - quote: " + __import__("json").dumps(Q1) + "\n    char_start: " + str(SOURCE.index(Q1)) + "\n"
            "    char_end: " + str(SOURCE.index(Q1) + len(Q1)) + "\n    source_uri: " + URI + "\n"
            "    source_sha256: " + SHA + "\n    mapu_id: MAPU-MAT\n---\n\nBeta.\n"
        )
        relation = {
            "from": "alpha", "to": "beta", "relation": "located_in", "label": "se ubica en",
            "polarity": "POSITIVE", "scope": "document",
            "evidence": [ev(Q1)],
        }
        assertion = {
            "subject": "alpha", "predicate": "has_member_count",
            "value": {"value_type": "integer", "value": 47, "unit": "socios"},
            "polarity": "POSITIVE", "scope": "document", "evidence": [ev(Q2)],
        }
        return {
            "entities/alpha.md": alpha, "entities/beta.md": beta,
            "relations.jsonl": __import__("json").dumps(relation) + "\n",
            "assertions.jsonl": __import__("json").dumps(assertion) + "\n",
            "coverage.json": __import__("json").dumps([{"unit_id": "u00", "state": "PROCESSED_WITH_OUTPUT"}]),
        }

    def test_native_structured_materializes_and_is_accepted(self):
        m = mapu()
        materializer = CandidateMaterializer(mapus=[m], antu=_antu_obj(), coverage_inventory={"MAPU-MAT": inventory_sections(SOURCE, mapu_id="MAPU-MAT")})
        materialized = materializer.materialize(self.artifacts())
        self.assertEqual(materialized.manifest["mode"], "native_structured")
        self.assertEqual(len(materialized.bundle.entities), 2)
        self.assertEqual(len(materialized.bundle.relations), 1)
        self.assertEqual(len(materialized.bundle.assertions), 1)
        result = evaluate(materialized.bundle)
        self.assertEqual(result.status, "ACCEPTED", result.validation.to_dict())

    def test_native_structured_missing_opening_delimiter_is_tolerated(self):
        artifacts = self.artifacts()
        artifacts["entities/alpha.md"] = artifacts["entities/alpha.md"][4:]
        m = mapu()
        materializer = CandidateMaterializer(mapus=[m], antu=_antu_obj(), coverage_inventory={"MAPU-MAT": inventory_sections(SOURCE, mapu_id="MAPU-MAT")})
        materialized = materializer.materialize(artifacts)
        self.assertEqual(len(materialized.bundle.entities), 2)
        self.assertIn("opening frontmatter delimiter missing", " ".join(materialized.manifest["warnings"]))

    def test_native_structured_duplicate_entity_id_is_rejected(self):
        artifacts = self.artifacts()
        artifacts["entities/alpha-copy.md"] = artifacts["entities/alpha.md"]
        m = mapu()
        materializer = CandidateMaterializer(mapus=[m], antu=_antu_obj())
        with self.assertRaises(CandidateMaterializationError):
            materializer.materialize(artifacts)

    def test_native_structured_malformed_jsonl_is_rejected(self):
        artifacts = self.artifacts()
        artifacts["relations.jsonl"] = "not json\n"
        m = mapu()
        materializer = CandidateMaterializer(mapus=[m], antu=_antu_obj())
        with self.assertRaises(CandidateMaterializationError):
            materializer.materialize(artifacts)


if __name__ == "__main__":
    unittest.main()
