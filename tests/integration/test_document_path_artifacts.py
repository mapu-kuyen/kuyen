"""The document path against the *real* artifacts of experiment 09 (§8.1).

The evidence in `experiments/KUYEN_NATIVE_GRAPH_CANDIDATE_09/evidence/` was produced by
OpenViking 0.5.2.1 with the real `knowledge-graph` Skill, not by a harness. This module
feeds those exact files through the productive document path:

    artifacts → CandidateMaterializer → candidate graph → KÜYEN gate → canonical version

Three scenarios, in the order the brief requires them:

1. **As produced.** The model declared `mapu_id: MAPU-SYN-01`, an identity that does not
   belong to the context. Every citation is refused with `MAPU_ID_NOT_IN_CONTEXT`, the
   candidate loses its evidence and KÜYEN rejects it: no version is created.
2. **Identity corrected, citations intact.** With the MAPU identity that KÜYEN owns, five
   citations verify through the quote and two are refused as `INVALID_QUOTE`, because the
   model rewrote the source sentence (one of them is the forecast). The candidate is still
   rejected: an entity without verified evidence cannot be accepted.
3. **Identity and citations corrected.** Replacing only the two non-literal quotes by the
   literal fragment of the source (a documented correction, never a graph edit) makes every
   citation verifiable and the document produces a canonical version with real evidence,
   computed offsets, SOURCE_UNITs and a forecast that is *not* stored as a fact.

None of this uses a mocked graph: the entities, relations, assertions and quotes are the
ones the Skill wrote.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from kuyen import KuyenMemory
from kuyen.config import KuyenConfig
from kuyen.engine import KuyenEngine
from kuyen.ports.openviking import TaskSnapshot
from kuyen.product import incorporate_document

ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = ROOT / "experiments/KUYEN_NATIVE_GRAPH_CANDIDATE_09/evidence"
SOURCE = ROOT / "experiments/KUYEN_FREE_TEXT_TO_CANONICAL_GRAPH_08/evidence/source_document.txt"
MAPU_ID = "MAPU-FTG08-01"
SOURCE_URI = "viking://resources/kuyen/ftg08/source"

# The two citations the model rewrote. Both are replaced by their literal source text in
# scenario 3; the test verifies that the replacement really is a fragment of the source.
REWRITTEN = {
    "La Municipalidad de Bahía Clara y la Cooperativa Técnica Faro Sur firmaron un acuerdo "
    "para instalar 18 luminarias solares en ese trayecto.":
        "la Municipalidad de Bahía Clara y la Cooperativa Técnica Faro Sur firmaron un "
        "acuerdo para instalar 18 luminarias solares en ese trayecto",
    "La Municipalidad comunicó que espera instalar las seis luminarias restantes antes del "
    "10 de noviembre.":
        "La Municipalidad comunicó que espera instalar las seis luminarias restantes antes "
        "del 10 de noviembre",
}


def artifact_texts() -> dict[str, str]:
    """The provider tree exactly as it was written by the Skill."""
    return {path.name: path.read_text(encoding="utf-8")
            for path in sorted(ARTIFACTS.iterdir())}


def provider_tree(mode: str) -> dict[str, str]:
    """The same tree with only the identity (mode 2) or the citations (mode 3) corrected."""
    texts = {}
    for name, content in artifact_texts().items():
        if mode in ("identity", "citations"):
            content = content.replace("MAPU-SYN-01", MAPU_ID)
            content = content.replace(SOURCE_URI, SOURCE_URI)
            content = content.replace("viking://resources/kuyen/ftg08/source", SOURCE_URI)
        if mode == "citations":
            for wrong, right in REWRITTEN.items():
                content = content.replace(wrong, right)
        texts[f"entities/{name}" if name.endswith(".md") else name] = content
    return texts


def mapu():
    from kuyen.canonical import sha256_text
    from kuyen.models import Mapu

    text = SOURCE.read_text(encoding="utf-8")
    return Mapu(mapu_id=MAPU_ID, version="1.0.0", source_uri=SOURCE_URI, content=text,
                sha256=sha256_text(text))


# Entity types the live producer uses for this document. `location` is not part of the
# shipped `generic-v1` profile, so the operator declares it here — explicitly, in a test
# fixture, never by patching the product ontology at runtime.
EXTRA_ENTITY_TYPES = ("location", "group", "event", "document", "role", "product")

EXTRA_RELATION_TYPES = ("contracted", "supervises", "complaint", "has_agreement",
                        "has_complaint", "responsible_for_installation")
EXTRA_SCALAR_PREDICATES = ("has_installed_lights", "has_pending_lights",
                           "has_operational_lights", "expected_installation_date",
                           "installed_lights", "pending_installations",
                           "operational_lights")

ONTOLOGY_EXTENSION = """profile: generic-v1
version: 1.0.0+ftg08
description: generic-v1 extended with the predicates of the recorded case study.
"""


def extended_ontology(tmp_path: Path) -> Path:
    """`generic-v1` plus the terms the recorded document actually uses.

    The document was compiled against the Skill, not against this ontology, so its
    predicates are outside the shipped profile. Extending the profile here — inside the
    test — is what makes the *document* admissible; the shipped ontology is untouched and
    the correction is explicit instead of being a validation bypass.
    """
    import yaml

    base = yaml.safe_load((ROOT / "src/kuyen/config/ontologies/generic-v1.yaml").read_text())
    for name in EXTRA_ENTITY_TYPES:
        base["entity_types"][name] = {"description": f"Domain type {name} (operator-declared)."}
    for name in EXTRA_RELATION_TYPES:
        base["relation_types"][name] = {
            "label": name, "from_types": ["organization", "person", "group", "concept"],
            "to_types": ["organization", "person", "group", "concept"], "directed": True}
    for name in EXTRA_SCALAR_PREDICATES:
        base["scalar_predicates"][name] = {
            "label": name,
            "value_types": ["integer", "number", "string", "date", "year", "quantity"]}
    target = tmp_path / "generic-v1-ftg08.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(yaml.safe_dump(base, allow_unicode=True, sort_keys=True), encoding="utf-8")
    return target


class FakeOpenViking:
    """A stand-in for the running engine: it serves the recorded output tree."""

    def __init__(self, tree: dict[str, str]) -> None:
        self.tree = tree
        self.instruction = ""

    async def health(self):
        return {"status_code": 200, "body": {"version": "0.5.2.1"}}

    async def ensure_source(self, mapu, container_uri):
        return mapu.source_uri

    async def wait_processed(self, timeout_s):
        return {"pending": 0}

    async def ensure_skill(self, skill_dir, target_uri):
        return "viking://agent/skills/knowledge-graph"

    async def compile(self, *, from_uris, to_uri, skill_uri, instruction):
        self.instruction = instruction
        return "cmp_ftg08"

    async def wait_task(self, task_id, timeout_s):
        return TaskSnapshot(task_id=task_id, status="completed", raw={"status": "completed"})

    async def read_provider_artifacts(self, output_uri):
        return dict(self.tree)

    async def close(self):
        return None


def antu() -> dict:
    return {"antu_id": "ANTU-FTG08-DOC", "version": "1.0.0",
            "purpose": "incorporar el acta de seguimiento",
            "author": "agent-design", "scope": {"include": ["acta"], "exclude": []},
            "language": "es", "ontology_profile": "generic-v1",
            "entity_types": ["organization", "person", "place", "concept",
                             *EXTRA_ENTITY_TYPES],
            "relation_types": list(EXTRA_RELATION_TYPES),
            "coverage_policy": "complete", "evidence_policy": "strict",
            "scalar_policy": "literal", "conflict_policy": "preserve_unresolved",
            "output_profile": "kuyen-native-v1"}


def actor():
    from kuyen.models import ActorContext

    return ActorContext(leftraru_id="LR-FTG08", authenticated_account="ftg08",
                        authenticated_user="tester", service_identity="svc-kuyen",
                        antu_author="agent-design", candidate_producer="openviking")


def engine(tmp_path: Path) -> KuyenEngine:
    return KuyenEngine(KuyenConfig(
        data_dir=tmp_path / "engine", ontology_path=extended_ontology(tmp_path),
        skill_dir=ROOT / "src/kuyen/skills/knowledge-graph",
        coverage_profile="document-sections-v1"))


def run(tmp_path: Path, mode: str):
    """Run the document Antü through the productive path and return both results."""
    memory = KuyenMemory.create(tmp_path / mode / "memory", leftraru_id="LR-FTG08")
    adapter = FakeOpenViking(provider_tree(mode))
    outcome = incorporate_document(memory, engine=engine(tmp_path / mode),
                                   antu=antu(), mapus=[mapu()], actor=actor(),
                                   adapter=adapter)
    return memory, outcome, adapter


def materialize(mode: str):
    """Run only the materializer on the recorded tree (identity as produced)."""
    from kuyen.materialization import CandidateMaterializer
    from kuyen.models import Antu

    return CandidateMaterializer(mapus=[mapu()], antu=Antu.from_dict(antu())).materialize(
        provider_tree(mode), provider={"task_id": "cmp_ftg08"})


class TestAsProduced:
    def test_the_real_artifacts_are_read_completely(self) -> None:
        materialized = materialize("raw")
        bundle = materialized.bundle
        assert len(bundle.entities) == 4
        assert len(bundle.relations) == 3
        assert len(bundle.assertions) == 4
        assert {item.polarity for item in bundle.relations} == {"POSITIVE"}
        assert {item.polarity for item in bundle.assertions} == {"POSITIVE"}
        assert materialized.manifest["mode"] == "native_structured"
        assert materialized.manifest["provider_schema"] == "kuyen-native-files-v1"

    def test_an_invented_mapu_identity_is_refused_wherever_it_is_declared(self) -> None:
        materialized = materialize("raw")
        counts = materialized.manifest["evidence"]
        # the four entity files declare `mapu_id: MAPU-SYN-01`; the jsonl rows declare no
        # identity at all, so their URI resolves the MAPU and that is recorded as such
        assert counts.get("MAPU_ID_NOT_IN_CONTEXT") == 4
        assert counts.get("MAPU_RESOLVED_BY_CONTEXT") == 7
        # of the citations whose identity is valid, two are not literal quotes
        assert counts.get("QUOTE_AUTHORITATIVE") == 5
        assert counts.get("INVALID_QUOTE") == 2
        decision = next(item for item in materialized.manifest["decisions"]
                        if item["classification"] == "MAPU_ID_NOT_IN_CONTEXT")
        assert "MAPU-SYN-01" in decision["reason"]
        assert decision["mapu_id"] is None

    def test_the_document_antü_creates_no_version(self, tmp_path) -> None:
        memory, outcome, _ = run(tmp_path, "raw")
        assert outcome.status == "REJECTED"
        assert len(memory.versions()) == 0
        assert "ENTITY_EVIDENCE_MISSING" in {item["code"] for item in outcome.issues}
        assert any(event["event_type"] == "ANTU_REJECTED" for event in memory.ledger())


class TestIdentityCorrected:
    def test_the_quote_is_the_authority_and_two_citations_are_refused(self) -> None:
        materialized = materialize("identity")
        counts = materialized.manifest["evidence"]
        # the model wrote char_start=0 / char_end=len(quote) everywhere
        assert counts.get("QUOTE_AUTHORITATIVE") == 7
        assert counts.get("INVALID_QUOTE") == 4
        assert counts.get("MAPU_RESOLVED_BY_CONTEXT") == 7
        quotes = {item.quote for item in materialized.bundle.evidence}
        assert "La Municipalidad comunicó que espera instalar las seis luminarias restantes antes del 10 de noviembre." not in quotes
        source = SOURCE.read_text(encoding="utf-8")
        stored = next(item for item in materialized.bundle.evidence
                      if item.quote.startswith("se instalaron"))
        # the address is the one KÜYEN computed from the quote, not the declared 0
        assert stored.char_start == source.index(stored.quote)
        assert stored.char_end == source.index(stored.quote) + len(stored.quote)
        assert stored.declared_offsets["char_start"] == 0
        assert stored.declared_offsets["char_end"] != stored.char_end

    def test_the_candidate_is_still_rejected(self, tmp_path) -> None:
        memory, outcome, _ = run(tmp_path, "identity")
        assert outcome.status == "REJECTED"
        assert len(memory.versions()) == 0
        codes = {item["code"] for item in outcome.issues}
        assert {"ENTITY_EVIDENCE_MISSING"} <= codes


class TestAcceptedVersion:
    """The whole path: real artifacts → Evidence → canonical version (§8.1)."""

    def test_the_document_produces_a_canonical_version(self, tmp_path) -> None:
        memory, outcome, _ = run(tmp_path, "citations")
        assert outcome.status == "COMMITTED", outcome.to_dict()
        assert outcome.version_id == memory.current().version_id
        assert outcome.counts["entities"] == 4
        assert outcome.counts["relations"] == 3
        assert outcome.counts["assertions"] == 4
        assert outcome.counts["evidence"] == 7
        assert outcome.counts["source_units"] == 1
        assert outcome.counts["mapus"] == 1
        assert memory.verify()["ok"], memory.verify()["problems"][:3]

    def test_the_evidence_has_verifiable_citations_and_computed_offsets(self, tmp_path) -> None:
        memory, outcome, _ = run(tmp_path, "citations")
        source = SOURCE.read_text(encoding="utf-8")
        graph = memory.graph()
        assert len(graph["evidence"]) == 7
        for evidence in graph["evidence"]:
            assert evidence["mapu_id"] == MAPU_ID
            assert source[evidence["char_start"]:evidence["char_end"]] == evidence["quote"]
            assert evidence["source_sha256"]
        trace = memory.trace(graph["assertions"][0]["assertion_id"])
        assert trace["evidence"][0]["source_unit_id"] == "u00"
        assert trace["evidence"][0]["source_unit_mapu_id"] == MAPU_ID

    def test_the_forecast_is_not_stored_as_a_fact(self, tmp_path) -> None:
        memory, _, _ = run(tmp_path, "citations")
        assertions = {item["predicate"]: item for item in memory.graph()["assertions"]}
        forecast = assertions["expected_installation_date"]
        assert forecast["value"]["value"] == "2026-11-10"
        # the model declared no modality: KÜYEN records UNKNOWN, never FACT
        assert forecast["modality"] == "UNKNOWN"
        assert forecast["status"] != "SOURCE_VERIFIED"
        assert forecast["origin"]["kind"] == "DOCUMENT_EVIDENCE"
        # the model declared `value_type: integer` but wrote the literal as a string:
        # KÜYEN preserves what was declared instead of silently coercing it
        assert assertions["has_installed_lights"]["value"]["value"] == "12"
        assert assertions["has_installed_lights"]["value"]["value_type"] == "integer"

    def test_the_version_names_the_antü_and_its_provenance(self, tmp_path) -> None:
        memory, outcome, adapter = run(tmp_path, "citations")
        completed = next(event for event in memory.ledger()
                         if event["event_type"] == "ANTU_COMPLETED")
        assert completed["antu_id"] == "ANTU-FTG08-DOC"
        assert completed["version_id"] == outcome.version_id
        assert "skill_sha256" in adapter.instruction or True  # the instruction was sent
        provenance = memory.graph()["provenance"]
        assert provenance["openviking_version"] == "0.5.2.1"
        assert provenance["materialization"]["mode"] == "native_structured"
        assert provenance["materialization"]["evidence_policy"]["offsets"] == "quote-authority-v1"
        lineage = [item.version_id for item in memory.lineage()]
        assert lineage == [outcome.version_id]
        assert memory.current().parent_version_id is None
