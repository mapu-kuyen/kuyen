"""A1 — the public ingestion path must reject invalid canonical memory.

KUYEN_PACKAGE_HARDENING_01, finding A1. Each test states the contract taken from
DATA_MODEL.md ("a quote that does not appear at its offsets is rejected") and from
`validation/validators.py` (`EvidenceValidator`, `GraphStructuralValidator`), which the
canonical path did not apply. The tests fail against 5fd8777 and must pass after the fix.
"""
from __future__ import annotations

import copy

import pytest

import fixtures_produc as fixtures
from kuyen import KuyenMemory, build_document
from kuyen.errors import CommitError


def canonical(graph: dict) -> dict:
    """The documented public path: build the canonical document, then import it."""
    return build_document(graph, {fixtures.MAPU_ID: fixtures.make_mapu_text()},
                          mapu_versions={fixtures.MAPU_ID: "1.0.0"},
                          source_uris={fixtures.MAPU_ID: fixtures.SOURCE_URI})


def assert_nothing_persisted(memory: KuyenMemory) -> None:
    assert memory.current() is None
    assert memory.versions() == []
    assert memory.verify()["ok"] is True


class TestFakeEvidence:
    """DATA_MODEL.md: offsets address the source text; a quote that does not appear at
    its offsets is rejected, and the declared source hash must match the MAPU."""

    def test_import_rejects_quote_that_does_not_match_its_offsets(self, memory: KuyenMemory) -> None:
        graph = fixtures.make_graph()
        graph["evidence"][0]["quote"] = "una cita que no aparece en la fuente"
        with pytest.raises(CommitError):
            memory.import_canonical(canonical(graph))
        assert_nothing_persisted(memory)

    def test_import_rejects_evidence_from_an_unknown_mapu(self, memory: KuyenMemory) -> None:
        graph = fixtures.make_graph()
        graph["evidence"][0]["mapu_id"] = "MAPU-QUE-NO-EXISTE"
        with pytest.raises(CommitError):
            memory.import_canonical(canonical(graph))
        assert_nothing_persisted(memory)

    def test_import_rejects_declared_source_hash_mismatch(self, memory: KuyenMemory) -> None:
        graph = fixtures.make_graph()
        graph["evidence"][0]["source_sha256"] = "0" * 64
        with pytest.raises(CommitError):
            memory.import_canonical(canonical(graph))
        assert_nothing_persisted(memory)


class TestVerifiedWithoutEvidence:
    """An object that declares SOURCE_VERIFIED support must carry evidence."""

    def test_import_rejects_source_verified_assertion_without_evidence(self, memory: KuyenMemory) -> None:
        graph = fixtures.make_graph()
        graph["assertions"][0]["evidence_ids"] = []
        with pytest.raises(CommitError):
            memory.import_canonical(canonical(graph))
        assert_nothing_persisted(memory)

    def test_import_rejects_source_verified_entity_without_evidence(self, memory: KuyenMemory) -> None:
        graph = fixtures.make_graph()
        graph["entities"][0]["evidence_ids"] = []
        with pytest.raises(CommitError):
            memory.import_canonical(canonical(graph))
        assert_nothing_persisted(memory)


class TestDuplicateIdentity:
    """GraphStructuralValidator rejects repeated ids; the canonical path must too."""

    def test_import_rejects_duplicate_entity_id(self, memory: KuyenMemory) -> None:
        graph = fixtures.make_graph()
        graph["entities"].append(copy.deepcopy(graph["entities"][0]))
        with pytest.raises(CommitError):
            memory.import_canonical(canonical(graph))
        assert_nothing_persisted(memory)

    def test_import_rejects_duplicate_evidence_id(self, memory: KuyenMemory) -> None:
        graph = fixtures.make_graph()
        graph["evidence"].append(copy.deepcopy(graph["evidence"][0]))
        with pytest.raises(CommitError):
            memory.import_canonical(canonical(graph))
        assert_nothing_persisted(memory)

    def test_import_rejects_duplicate_assertion_id(self, memory: KuyenMemory) -> None:
        graph = fixtures.make_graph()
        graph["assertions"].append(copy.deepcopy(graph["assertions"][0]))
        with pytest.raises(CommitError):
            memory.import_canonical(canonical(graph))
        assert_nothing_persisted(memory)


class TestValidMemoryStillAccepted:
    """The correction must not reject data that the contract accepts."""

    def test_valid_document_is_still_imported(self, memory: KuyenMemory) -> None:
        result = memory.import_canonical(canonical(fixtures.make_graph()))
        assert result.version.version_id
        assert memory.current() is not None
        assert memory.verify()["ok"] is True
        graph = memory.graph()
        assert len(graph["entities"]) == 2
        assert len(graph["evidence"]) == 1


class TestAntuProposalValidation:
    """The validated path (`execute_antu`) must reject the same defects before commit."""

    def test_antu_rejects_an_identity_that_already_exists_in_the_base(
            self, live_memory: KuyenMemory, antu_file) -> None:
        antu, path = antu_file
        base_entity = live_memory.graph()["entities"][0]["entity_id"]
        antu["proposal"]["entities"][0]["entity_id"] = base_entity
        antu["proposal"]["entities"][0]["canonical_entity_id"] = base_entity
        antu["proposal"]["relations"][0]["from_entity"] = base_entity
        antu["proposal"]["assertions"][0]["subject_entity"] = base_entity

        execution = live_memory.execute_antu(antu, mapu_source=path)

        assert execution.status == "REJECTED"
        assert any("DUPLICATE_ID" in reason for reason in execution.detail["reasons"])
        assert live_memory.current().parent_version_id is None

    def test_antu_rejects_a_source_verified_assertion_without_evidence(
            self, live_memory: KuyenMemory, antu_file) -> None:
        antu, path = antu_file
        antu["proposal"]["assertions"][0]["evidence_ids"] = []

        execution = live_memory.execute_antu(antu, mapu_source=path)

        assert execution.status == "REJECTED"
        assert any("EVIDENCE_MISSING" in reason for reason in execution.detail["reasons"])

    def test_antu_rejects_fake_evidence(self, live_memory: KuyenMemory, antu_file) -> None:
        antu, path = antu_file
        antu["proposal"]["evidence"][0]["quote"] = "una cita que no aparece en la fuente"

        execution = live_memory.execute_antu(antu, mapu_source=path)

        assert execution.status == "REJECTED"
        assert any("EVIDENCE_QUOTE_MISMATCH" in reason for reason in execution.detail["reasons"])

    def test_a_valid_antu_is_still_validated(self, live_memory: KuyenMemory, antu_file) -> None:
        antu, path = antu_file
        execution = live_memory.execute_antu(antu, mapu_source=path)
        assert execution.status == "VALIDATED"
        live_memory.commit(execution)
        assert len(live_memory.versions()) == 2
        assert live_memory.verify()["ok"] is True
