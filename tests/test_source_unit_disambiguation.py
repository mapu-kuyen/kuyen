"""SOURCE_UNIT resolution must stay inside the MAPU the evidence belongs to.

KUYEN_SOURCE_UNIT_DISAMBIGUATION_03. `unit_id` is local to a MAPU (DATA_MODEL.md), so a
version that holds two documents can legitimately contain two `u00` units. The public
lookup used to return the first match and therefore attributed evidence to the wrong
document. These tests fix the contract:

* a lookup scoped by `mapu_id` returns that document's unit and nothing else;
* an unscoped lookup is accepted only while the identifier is unique, and otherwise
  raises `AmbiguousSourceUnit` (enumeration order is never a tie-breaker);
* `trace()` resolves and *verifies* the whole chain (MAPU, unit span, unit hash, quote at
  its offsets), and raises instead of returning a plausible but wrong source.

They are deliberately independent of the quickstart builders: they build two documents
whose unit identifiers collide, which is the case the defect needed.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from kuyen import KuyenMemory, build_document
from kuyen.api.memory import _evidence_unit  # white-box: the verification the public trace uses
from kuyen.errors import AmbiguousSourceUnit, StoreError

REPO = Path(__file__).resolve().parents[1]

TEXT_A = "La cooperativa del valle produce vino desde 1990."
QUOTE_A = "produce vino desde 1990"
TEXT_B = "La bodega del valle exporto 1.200 cajas en 2024."
QUOTE_B = "exporto 1.200 cajas en 2024"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _id(prefix: str, label: str) -> str:
    return prefix + hashlib.sha256(label.encode("utf-8")).hexdigest()[:20]


def _evidence(mapu_id: str, uri: str, text: str, quote: str, label: str) -> dict:
    start = text.index(quote)
    return {"evidence_id": _id("ev_", label), "mapu_id": mapu_id, "source_uri": uri,
            "quote": quote, "char_start": start, "char_end": start + len(quote),
            "offset_unit": "unicode_codepoint", "extraction_method": "manual",
            "validation_status": "SOURCE_VERIFIED", "source_sha256": _sha(text)}


def _entity(mapu_id: str, uri: str, evidence_id: str, label: str) -> dict:
    return {"entity_id": _id("ent_", label), "entity_type": "organization",
            "name": f"Entity {label}", "aliases": [], "description": "test",
            "evidence_ids": [evidence_id], "sources": [uri], "source_entity_id": "e1",
            "source_namespace": "test", "identity_basis": "source_id",
            "normalization_status": "RESOLVED", "normalization_reason": None,
            "status": "SOURCE_VERIFIED", "metadata": {}, "origin_entity_id": "e1",
            "canonical_entity_id": _id("ent_", label),
            "identity_status": "SAME_STABLE_ID", "identity_group_id": None}


def _unit(mapu_id: str, uri: str, text: str, unit_id: str, *, order: int) -> dict:
    return {"unit_id": unit_id, "mapu_id": mapu_id, "section": "preamble", "order": order,
            "char_start": 0, "char_end": len(text), "chars": len(text),
            "content_sha256": _sha(text), "source_uri": uri}


def _document(mapu_id: str, uri: str, text: str, quote: str, *, unit_id: str,
              label: str) -> dict:
    """A canonical document with one entity, one evidence and one SOURCE_UNIT."""
    evidence = _evidence(mapu_id, uri, text, quote, label)
    entity = _entity(mapu_id, uri, evidence["evidence_id"], label)
    unit = _unit(mapu_id, uri, text, unit_id, order=0)
    graph = {
        "kuyen_id": "KUY-0123456789ab", "version": "1.0.0", "antu_id": f"ANTU-{label}",
        "mapu_ids": [mapu_id], "schema_version": "kuyen-native-v1", "status": "ACCEPTED",
        "entities": [entity], "relations": [], "assertions": [], "evidence": [evidence],
        "coverage": [{"source_uri": uri, "mapu_id": mapu_id, "unit_id": unit_id,
                      "state": "PROCESSED_WITH_OUTPUT", "section": "preamble",
                      "content_sha256": _sha(text), "entity_ids": [entity["entity_id"]],
                      "relation_ids": [], "reason": None}],
        "provenance": {"antu_id": f"ANTU-{label}", "antu_version": "1.0.0",
                       "actor": {"antu_author": "tests", "authenticated_account": "local",
                                 "authenticated_user": "local",
                                 "candidate_producer": "tests", "leftraru_id": "LR-TEST",
                                 "request_id": None, "service_identity": "local"},
                       "candidate": {}, "candidate_uri": None,
                       "coverage_inventory": {mapu_id: [dict(unit, content=text)]}},
        "content_digest": None, "provenance_digest": None,
    }
    compact = json.dumps({key: graph[key] for key in
                          ("entities", "relations", "assertions", "evidence")},
                         sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    graph["content_digest"] = hashlib.sha256(compact.encode()).hexdigest()[:20]
    graph["provenance_digest"] = hashlib.sha256(
        json.dumps(graph["provenance"], sort_keys=True, ensure_ascii=False,
                   separators=(",", ":")).encode()).hexdigest()[:20]
    return build_document(graph, {mapu_id: text}, source_uris={mapu_id: uri})


def _antu(base_version_id: str, mapu_id: str, uri: str, text: str, quote: str, *,
          unit_id: str, label: str) -> dict:
    """An Antü that adds one more document with the given `unit_id`."""
    evidence = _evidence(mapu_id, uri, text, quote, label)
    entity = _entity(mapu_id, uri, evidence["evidence_id"], label)
    unit = _unit(mapu_id, uri, text, unit_id, order=1)
    return {"antu_id": f"ANTU-{label}", "idempotency_key": f"ANTU-{label}",
            "leftraru_id": "LR-TEST", "base_version_id": base_version_id,
            "purpose": "add a document", "kind": "INCORPORATE_MAPU",
            "description": f"adds {mapu_id}",
            "mapu": {"mapu_id": mapu_id, "version": "1.0.0", "revision": "r1",
                     "source_uri": uri, "sha256": _sha(text),
                     "source_file": f"{mapu_id}.txt", "source_identity": "tests"},
            "unit": {**unit, "content": text, "content_verified": True},
            "coverage": {"source_uri": uri, "mapu_id": mapu_id, "unit_id": unit_id,
                         "state": "PROCESSED_WITH_OUTPUT", "section": "preamble",
                         "content_sha256": _sha(text), "entity_ids": [entity["entity_id"]],
                         "relation_ids": [], "reason": None},
            "proposal": {"entities": [entity], "relations": [], "assertions": [],
                         "evidence": [evidence]}}


def _two_document_memory(tmp_path: Path, *, first: str = "A", second_unit_id: str = "u00",
                         first_unit_id: str = "u00") -> tuple[KuyenMemory, dict[str, str]]:
    """A memory with MAPU-A and MAPU-B; `second_unit_id` may collide with the first."""
    docs = {"A": ("MAPU-A", "viking://resources/test/MAPU-A.txt", TEXT_A, QUOTE_A),
            "B": ("MAPU-B", "viking://resources/test/MAPU-B.txt", TEXT_B, QUOTE_B)}
    other = "B" if first == "A" else "A"
    mapu, uri, text, quote = docs[first]
    memory = KuyenMemory.create(tmp_path / "memory", leftraru_id="LR-TEST")
    memory.import_canonical(_document(mapu, uri, text, quote, unit_id=first_unit_id,
                                      label=f"doc{first}"))
    mapu2, uri2, text2, quote2 = docs[other]
    antu = _antu(memory.current().version_id, mapu2, uri2, text2, quote2,
                 unit_id=second_unit_id, label=f"doc{other}")
    source = tmp_path / f"{mapu2}.txt"
    source.write_text(text2, encoding="utf-8")
    memory.commit(memory.execute_antu(antu, mapu_source=source))
    return memory, {v[0]: v[2] for v in docs.values()}



class TestScopedResolution:
    """Case A — repeated local ids resolve inside their own MAPU."""

    def test_the_evidence_of_the_second_document_resolves_inside_it(self,
                                                                    tmp_path: Path) -> None:
        memory, _ = _two_document_memory(tmp_path)
        unit = memory.source_unit("u00", mapu_id="MAPU-B")
        assert unit["mapu_id"] == "MAPU-B"
        assert unit["content"] == TEXT_B

    def test_the_first_document_resolves_inside_its_own_mapu(self,
                                                             tmp_path: Path) -> None:
        memory, _ = _two_document_memory(tmp_path)
        assert memory.source_unit("u00", mapu_id="MAPU-A")["content"] == TEXT_A

    def test_trace_names_the_unit_of_the_evidence_mapu(self, tmp_path: Path) -> None:
        memory, _ = _two_document_memory(tmp_path)
        item = memory.trace(_id("ent_", "docB"))["evidence"][0]
        assert item["mapu_id"] == "MAPU-B"
        assert item["source_unit_mapu_id"] == "MAPU-B"
        assert item["source_unit_id"] == "u00"
        assert memory.source_unit(item["source_unit_id"],
                                  mapu_id=item["mapu_id"])["content"][
            item["char_start"]:item["char_end"]] == item["quote"]


class TestUnscopedLookup:
    """Case B — no context plus a collision is an explicit refusal, never a first match."""

    def test_a_colliding_identifier_is_rejected(self, tmp_path: Path) -> None:
        memory, _ = _two_document_memory(tmp_path)
        with pytest.raises(AmbiguousSourceUnit) as excinfo:
            memory.source_unit("u00")
        assert excinfo.value.code == "AMBIGUOUS_SOURCE_UNIT"
        assert "u00" in str(excinfo.value)

    def test_the_refusal_names_every_candidate(self, tmp_path: Path) -> None:
        memory, _ = _two_document_memory(tmp_path)
        with pytest.raises(AmbiguousSourceUnit) as excinfo:
            memory.source_unit("u00")
        assert excinfo.value.details["candidates"] == ["MAPU-A", "MAPU-B"]

    def test_it_stays_a_store_error_so_existing_callers_fail_closed(self,
                                                                    tmp_path: Path) -> None:
        memory, _ = _two_document_memory(tmp_path)
        with pytest.raises(StoreError):
            memory.source_unit("u00")


class TestUniqueIdentifierCompatibility:
    """Case C — a globally unique identifier keeps the old behaviour."""

    def test_a_unique_identifier_resolves_without_context(self, tmp_path: Path) -> None:
        memory, _ = _two_document_memory(tmp_path, second_unit_id="u01")
        unit = memory.source_unit("u01")
        assert unit["mapu_id"] == "MAPU-B" and unit["content"] == TEXT_B

    def test_a_unique_identifier_also_resolves_with_context(self, tmp_path: Path) -> None:
        memory, _ = _two_document_memory(tmp_path, second_unit_id="u01")
        assert memory.source_unit("u01", mapu_id="MAPU-B")["content"] == TEXT_B

    def test_a_single_document_memory_is_unchanged(self, tmp_path: Path) -> None:
        memory = KuyenMemory.create(tmp_path / "single", leftraru_id="LR-TEST")
        memory.import_canonical(_document("MAPU-A", "viking://resources/test/MAPU-A.txt",
                                          TEXT_A, QUOTE_A, unit_id="u00", label="single"))
        assert memory.source_unit("u00")["content"] == TEXT_A


class TestWrongMapu:
    """Case D — asking inside the wrong MAPU is refused, never substituted."""

    def test_a_unit_that_the_mapu_does_not_hold_is_refused(self, tmp_path: Path) -> None:
        memory, _ = _two_document_memory(tmp_path, second_unit_id="u01")
        with pytest.raises(StoreError) as excinfo:
            memory.source_unit("u01", mapu_id="MAPU-A")
        assert "no SOURCE_UNIT u01" in str(excinfo.value)

    def test_an_unknown_mapu_is_refused(self, tmp_path: Path) -> None:
        memory, _ = _two_document_memory(tmp_path)
        with pytest.raises(StoreError) as excinfo:
            memory.source_unit("u00", mapu_id="MAPU-Z")
        assert "unknown MAPU" in str(excinfo.value)

    def test_a_missing_identifier_is_refused(self, tmp_path: Path) -> None:
        memory, _ = _two_document_memory(tmp_path)
        with pytest.raises(StoreError):
            memory.source_unit("u99", mapu_id="MAPU-B")


def _sidecar(*units: dict) -> dict:
    """A minimal sidecar: two MAPUs and the units given (the only input the resolver needs)."""
    return {"mapus": [{"mapu_id": "MAPU-A", "content_sha256": _sha(TEXT_A)},
                      {"mapu_id": "MAPU-B", "content_sha256": _sha(TEXT_B)}],
            "canonical": {"source_units": list(units)}}


def _unit_with_text(mapu_id: str, text: str, *, unit_id: str = "u00",
                    content: str | None = None) -> dict:
    uri = f"viking://resources/test/{mapu_id}.txt"
    return dict(_unit(mapu_id, uri, text, unit_id, order=0),
                content=text if content is None else content)


def _evidence_record(mapu_id: str, *, quote: str, start: int, end: int,
                     source_sha256: str | None = None) -> dict:
    return {"evidence_id": "ev_chain", "mapu_id": mapu_id, "quote": quote,
            "char_start": start, "char_end": end,
            "source_sha256": source_sha256 if source_sha256 is not None else _sha(TEXT_B)}


class TestEvidenceChainVerification:
    """Case E — the chain is verified, not merely looked up (the check `trace` runs)."""

    def _mapus(self, sidecar: dict) -> dict:
        return {mapu["mapu_id"]: mapu for mapu in sidecar["mapus"]}

    def test_a_correct_evidence_resolves_to_its_own_unit(self) -> None:
        sidecar = _sidecar(_unit_with_text("MAPU-A", TEXT_A), _unit_with_text("MAPU-B", TEXT_B))
        start = TEXT_B.index(QUOTE_B)
        unit = _evidence_unit(sidecar, _evidence_record("MAPU-B", quote=QUOTE_B, start=start,
                                                        end=start + len(QUOTE_B)),
                              self._mapus(sidecar))
        assert unit["mapu_id"] == "MAPU-B" and unit["content"] == TEXT_B

    def test_a_unit_of_another_mapu_is_never_used(self) -> None:
        # only MAPU-A's unit exists; an evidence that claims MAPU-B must not fall back to it
        sidecar = _sidecar(_unit_with_text("MAPU-A", TEXT_A))
        with pytest.raises(StoreError) as excinfo:
            _evidence_unit(sidecar, _evidence_record("MAPU-B", quote=QUOTE_B, start=0,
                                                     end=len(QUOTE_B)), self._mapus(sidecar))
        assert "not covered by any SOURCE_UNIT of MAPU MAPU-B" in str(excinfo.value)

    def test_an_unknown_mapu_is_rejected(self) -> None:
        sidecar = _sidecar(_unit_with_text("MAPU-A", TEXT_A))
        with pytest.raises(StoreError) as excinfo:
            _evidence_unit(sidecar, _evidence_record("MAPU-Z", quote=QUOTE_A, start=0,
                                                     end=len(QUOTE_A)), self._mapus(sidecar))
        assert "which this version does not hold" in str(excinfo.value)

    def test_a_quote_that_does_not_match_the_offsets_is_rejected(self) -> None:
        sidecar = _sidecar(_unit_with_text("MAPU-A", TEXT_A), _unit_with_text("MAPU-B", TEXT_B))
        with pytest.raises(StoreError) as excinfo:
            _evidence_unit(sidecar, _evidence_record("MAPU-B", quote=QUOTE_A, start=0,
                                                     end=len(QUOTE_A)), self._mapus(sidecar))
        assert "does not match the source" in str(excinfo.value)

    def test_a_unit_whose_content_does_not_match_its_hash_is_rejected(self) -> None:
        tampered = _unit_with_text("MAPU-B", TEXT_B, content=TEXT_B.replace("bodega", "BODEGA"))
        sidecar = _sidecar(_unit_with_text("MAPU-A", TEXT_A), tampered)
        start = TEXT_B.index(QUOTE_B)
        with pytest.raises(StoreError) as excinfo:
            _evidence_unit(sidecar, _evidence_record("MAPU-B", quote=QUOTE_B, start=start,
                                                     end=start + len(QUOTE_B)),
                           self._mapus(sidecar))
        assert "does not match its content hash" in str(excinfo.value)

    def test_a_span_outside_every_unit_is_rejected(self) -> None:
        sidecar = _sidecar(_unit_with_text("MAPU-A", TEXT_A), _unit_with_text("MAPU-B", TEXT_B))
        with pytest.raises(StoreError):
            _evidence_unit(sidecar, _evidence_record("MAPU-B", quote="2024",
                                                     start=len(TEXT_B) + 5,
                                                     end=len(TEXT_B) + 9),
                           self._mapus(sidecar))

    def test_a_source_hash_from_another_document_is_rejected(self) -> None:
        sidecar = _sidecar(_unit_with_text("MAPU-A", TEXT_A), _unit_with_text("MAPU-B", TEXT_B))
        start = TEXT_B.index(QUOTE_B)
        with pytest.raises(StoreError) as excinfo:
            _evidence_unit(sidecar, _evidence_record("MAPU-B", quote=QUOTE_B, start=start,
                                                     end=start + len(QUOTE_B),
                                                     source_sha256=_sha(TEXT_A)),
                           self._mapus(sidecar))
        assert "source hash" in str(excinfo.value)



class TestOrderIndependence:
    """Case F — swapping the documents changes nothing but the order of the artifacts."""

    def test_both_document_orders_resolve_the_same_way(self, tmp_path: Path) -> None:
        for first in ("A", "B"):
            memory, _ = _two_document_memory(tmp_path / f"order-{first}", first=first)
            assert memory.source_unit("u00", mapu_id="MAPU-A")["content"] == TEXT_A
            assert memory.source_unit("u00", mapu_id="MAPU-B")["content"] == TEXT_B
            with pytest.raises(AmbiguousSourceUnit) as excinfo:
                memory.source_unit("u00")
            # the candidate list is sorted, so it does not depend on insertion order
            assert excinfo.value.details["candidates"] == ["MAPU-A", "MAPU-B"]


class TestQuickstartRegression:
    """Case G — the public example still works with the corrected resolution."""

    def test_the_example_runs_and_verifies(self, tmp_path: Path) -> None:
        target = tmp_path / "demo"
        target.mkdir()
        env = dict(os.environ)
        env.pop("KUYEN_RUN_OPENVIKING", None)
        env["PYTHONPATH"] = str(REPO / "src")
        result = subprocess.run([sys.executable, str(REPO / "examples" / "quickstart.py"),
                                 str(target)], cwd=str(target), env=env,
                                capture_output=True, text=True, timeout=300)
        assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        assert "verify: ok=True" in result.stdout
        memory = KuyenMemory.open(target / "memory")
        assert memory.verify()["ok"] is True
        graph = memory.graph()
        claims = ([entity["entity_id"] for entity in graph["entities"]]
                  + [assertion["assertion_id"] for assertion in graph["assertions"]])
        traced = 0
        for claim_id in claims:
            for item in memory.trace(claim_id)["evidence"]:
                assert item["source_unit_mapu_id"] == item["mapu_id"]
                unit = memory.source_unit(item["source_unit_id"], mapu_id=item["mapu_id"])
                assert unit["content"][item["char_start"]:item["char_end"]] == item["quote"]
                traced += 1
        assert traced >= 2
