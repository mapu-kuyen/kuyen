"""Deterministic Antu processor.

An Antu instruction is executed by verification and merge only: the proposal is declared
in the instruction (hand-authored fixture), the processor validates it against the MAPU,
merges it into the base version and commits. It never invents objects, never edits an
accepted version and never touches OpenViking.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .ledger import append_event, events_for_antu
from ..storage.store import CanonicalStore
from ..storage.commit import Failpoint, commit_version
from ..canonical import canonical_json, digest, sha256_text
from ..errors import ConflictError
from ..contracts import PROJECTOR_VERSION
from ..projection.native import load_sidecar
from ..storage.registry import current as registry_current
from .unit import next_revision, record_revision

KIND_INCORPORATE = "INCORPORATE_MAPU"
KIND_VERIFY_ONLY = "VERIFY_ONLY"
KIND_INVALID = "INVALID_PROPOSAL"

VALIDATION_OK = "ACCEPTED"
VALIDATION_REJECTED = "REJECTED"
VALIDATION_NO_CHANGE = "NO_SEMANTIC_CHANGE"
VALIDATION_REPLAYED = "REPLAYED"


@dataclass
class AntuOutcome:
    antu_id: str
    status: str
    unit_revision: str | None
    version_id: str | None
    canonical_graph_hash: str | None
    semantic_change: bool
    detail: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"antu_id": self.antu_id, "status": self.status, "unit_revision": self.unit_revision,
                "version_id": self.version_id, "canonical_graph_hash": self.canonical_graph_hash,
                "semantic_change": self.semantic_change, "detail": self.detail}


def load_instruction(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _bump_version(version: str) -> str:
    parts = (version.split(".") + ["0", "0", "0"])[:3]
    return f"{parts[0]}.{int(parts[1]) + 1}.0"


def _verify_proposal(instruction: dict[str, Any], mapu_text: str | None) -> list[str]:
    problems: list[str] = []
    proposal = instruction.get("proposal") or {}
    for evidence in proposal.get("evidence") or []:
        if mapu_text is None:
            problems.append(f"evidence {evidence.get('evidence_id')} has no MAPU to verify against")
            continue
        start, end = evidence.get("char_start"), evidence.get("char_end")
        if not isinstance(start, int) or not isinstance(end, int):
            problems.append(f"evidence {evidence.get('evidence_id')} has no offsets")
            continue
        if mapu_text[start:end] != evidence.get("quote"):
            problems.append(f"evidence {evidence.get('evidence_id')} quote does not match the MAPU at its offsets")
        if evidence.get("source_sha256") and evidence["source_sha256"] != sha256_text(mapu_text):
            problems.append(f"evidence {evidence.get('evidence_id')} source hash does not match the MAPU")
    for entity in proposal.get("entities") or []:
        if not entity.get("entity_id") or not entity.get("name"):
            problems.append("proposed entity without identity or name")
    base_entities = set(instruction.get("_base_entity_ids") or [])
    proposed_entities = {entity["entity_id"] for entity in proposal.get("entities") or []}
    proposed_evidence = {item["evidence_id"] for item in proposal.get("evidence") or []}
    for relation in proposal.get("relations") or []:
        for endpoint in (relation.get("from_entity"), relation.get("to_entity")):
            if endpoint not in base_entities | proposed_entities:
                problems.append(f"relation {relation.get('relation_id')} points at an unknown endpoint {endpoint}")
        if not relation.get("evidence_ids"):
            problems.append(f"relation {relation.get('relation_id')} has no evidence")
        for reference in relation.get("evidence_ids") or []:
            if reference not in proposed_evidence:
                problems.append(f"relation {relation.get('relation_id')} references unknown evidence {reference}")
    for assertion in proposal.get("assertions") or []:
        if assertion.get("subject_entity") not in base_entities | proposed_entities:
            problems.append(f"assertion {assertion.get('assertion_id')} has an unknown subject")
        for reference in assertion.get("evidence_ids") or []:
            if reference not in proposed_evidence:
                problems.append(f"assertion {assertion.get('assertion_id')} references unknown evidence {reference}")
    return problems


def _merge(base_document: dict[str, Any], instruction: dict[str, Any], mapu: dict[str, Any],
           created_at: str) -> dict[str, Any]:
    """Append the verified proposal to the base canonical document; never modify the base."""
    proposal = instruction["proposal"]
    document = json.loads(json.dumps(base_document))
    canonical = document["canonical"]
    canonical["entities"] = canonical["entities"] + list(proposal.get("entities") or [])
    canonical["relations"] = canonical["relations"] + list(proposal.get("relations") or [])
    canonical["assertions"] = canonical["assertions"] + list(proposal.get("assertions") or [])
    canonical["evidence"] = canonical["evidence"] + list(proposal.get("evidence") or [])
    canonical["source_units"] = canonical["source_units"] + [instruction["unit"]]
    document["mapus"] = document["mapus"] + [mapu]
    coverage = dict(instruction["coverage"])
    coverage["entity_ids"] = coverage.get("entity_ids") or [e["entity_id"] for e in proposal.get("entities") or []]
    coverage["relation_ids"] = coverage.get("relation_ids") or [r["relation_id"] for r in proposal.get("relations") or []]
    canonical["coverage"] = canonical["coverage"] + [coverage]

    graph = {
        "kuyen_id": document["kuyen"]["kuyen_id"],
        "version": _bump_version(document["kuyen"]["version"]),
        "antu_id": instruction["antu_id"],
        "mapu_ids": sorted({item["mapu_id"] for item in document["mapus"]}),
        "schema_version": document["kuyen"]["schema_version"],
        "status": "ACCEPTED",
        "entities": canonical["entities"], "relations": canonical["relations"],
        "assertions": canonical["assertions"], "evidence": canonical["evidence"],
        "coverage": canonical["coverage"],
        "provenance": document["kuyen"]["provenance"],
    }
    graph["content_digest"] = digest({"entities": graph["entities"], "relations": graph["relations"],
                                       "assertions": graph["assertions"], "evidence": graph["evidence"]})[:20]
    graph["provenance_digest"] = digest(graph["provenance"])[:20]
    document["kuyen"] = {**document["kuyen"], "version": graph["version"], "antu_id": graph["antu_id"],
                         "mapu_ids": graph["mapu_ids"], "content_digest": graph["content_digest"],
                         "provenance_digest": graph["provenance_digest"],
                         "canonical_graph_hash": digest(graph),
                         "canonical_serialization_sha256": sha256_text(canonical_json(graph)),
                         "provenance": graph["provenance"]}
    document["counts"] = {"mapus": len(document["mapus"]), "entities": len(canonical["entities"]),
                          "relations": len(canonical["relations"]),
                          "assertions": len(canonical["assertions"]),
                          "evidence": len(canonical["evidence"]),
                          "coverage": len(canonical["coverage"]),
                          "source_units": len(canonical["source_units"])}
    document["_canonical_graph"] = graph
    return document


def execute(
    store: CanonicalStore,
    instruction: dict[str, Any],
    *,
    mapu_source: str | Path | None,
    created_at: str,
    identity: dict[str, Any],
    openviking_version: str | None = None,
    failpoint: Failpoint | None = None,
) -> AntuOutcome:
    """Execute one Antu deterministically. Idempotent by `idempotency_key`."""
    antu_id = instruction["antu_id"]
    key = instruction.get("idempotency_key") or antu_id
    previous = [event for event in events_for_antu(store, antu_id)
                if event["event_type"] in {"ANTU_COMPLETED", "ANTU_NO_SEMANTIC_CHANGE", "ANTU_REJECTED"}]
    if previous:
        last = previous[-1]
        append_event(store, "ANTU_RECEIVED", {
            "antu_id": antu_id, "idempotency_key": key, "leftraru_id": instruction["leftraru_id"],
            "purpose": instruction.get("purpose"), "kind": instruction.get("kind"),
            "replayed": True, "recorded_at": created_at})
        revision = next_revision(store)
        record_revision(store, leftraru_id=instruction["leftraru_id"], antu_id=antu_id,
                        revision=revision, status="REPLAYED",
                        input_version_id=instruction.get("base_version_id"),
                        output_version_id=last.get("version_id"),
                        canonical_graph_hash=last.get("canonical_graph_hash"),
                        semantic_change=False, created_at=created_at,
                        detail={"idempotency_key": key, "replayed_from_seq": last["seq"]})
        return AntuOutcome(antu_id, VALIDATION_REPLAYED, revision, last.get("version_id"),
                           last.get("canonical_graph_hash"), False,
                           {"idempotency_key": key, "replayed_from_seq": last["seq"],
                            "no_duplication": True})

    append_event(store, "ANTU_RECEIVED", {
        "antu_id": antu_id, "idempotency_key": key, "leftraru_id": instruction["leftraru_id"],
        "purpose": instruction.get("purpose"), "kind": instruction.get("kind"),
        "instruction": instruction.get("description"),
        "base_version_id": instruction.get("base_version_id"), "recorded_at": created_at})

    pointer = registry_current(store)
    base_version_id = instruction.get("base_version_id")
    if pointer is None or base_version_id is None:
        raise ConflictError("an Antu needs a committed store and an explicit base version")
    if pointer["version_id"] != base_version_id:
        reason = f"STALE_BASE: instruction targets {base_version_id}, current is {pointer['version_id']}"
        append_event(store, "ANTU_REJECTED", {"antu_id": antu_id, "reason": reason,
                                              "recorded_at": created_at})
        revision = next_revision(store)
        record_revision(store, leftraru_id=instruction["leftraru_id"], antu_id=antu_id, revision=revision,
                        status="REJECTED", input_version_id=base_version_id, output_version_id=None,
                        canonical_graph_hash=None, semantic_change=False, created_at=created_at,
                        detail={"reason": reason, "conflict": True})
        return AntuOutcome(antu_id, VALIDATION_REJECTED, revision, None, None, False,
                           {"reason": reason, "conflict": True})

    base_sidecar = load_sidecar(store, base_version_id)
    base_document = {"kuyen": base_sidecar["kuyen"], "canonical": base_sidecar["canonical"],
                     "mapus": base_sidecar["mapus"], "counts": base_sidecar["object_counts"]}
    instruction = dict(instruction)
    instruction["_base_entity_ids"] = [entity["entity_id"] for entity in base_document["canonical"]["entities"]]

    if instruction.get("kind") == KIND_VERIFY_ONLY:
        append_event(store, "ANTU_NO_SEMANTIC_CHANGE", {
            "antu_id": antu_id, "version_id": base_version_id,
            "canonical_graph_hash": base_document["kuyen"]["canonical_graph_hash"],
            "recorded_at": created_at, "reason": "VERIFY_ONLY produces no new knowledge"})
        revision = next_revision(store)
        record_revision(store, leftraru_id=instruction["leftraru_id"], antu_id=antu_id, revision=revision,
                        status="NO_SEMANTIC_CHANGE", input_version_id=base_version_id,
                        output_version_id=base_version_id,
                        canonical_graph_hash=base_document["kuyen"]["canonical_graph_hash"],
                        semantic_change=False, created_at=created_at,
                        detail={"operation": "VERIFY_ONLY", "new_version_created": False})
        return AntuOutcome(antu_id, VALIDATION_NO_CHANGE, revision, base_version_id,
                           base_document["kuyen"]["canonical_graph_hash"], False,
                           {"operation": "VERIFY_ONLY", "new_version_created": False})

    mapu_declaration = instruction.get("mapu") or {}
    if mapu_source is None:
        problems = _verify_proposal(instruction, None)
        mapu_text = ""
    else:
        mapu_text = Path(mapu_source).read_text(encoding="utf-8")
        if mapu_declaration.get("sha256") and mapu_declaration["sha256"] != sha256_text(mapu_text):
            problems = ["declared MAPU hash does not match the provided source"]
        else:
            problems = _verify_proposal(instruction, mapu_text)
    if instruction.get("kind") == KIND_INVALID and not problems:
        problems = ["instruction is declared invalid but the proposal passed validation"]
    if problems:
        append_event(store, "ANTU_REJECTED", {"antu_id": antu_id, "reasons": problems,
                                              "recorded_at": created_at})
        revision = next_revision(store)
        record_revision(store, leftraru_id=instruction["leftraru_id"], antu_id=antu_id, revision=revision,
                        status="REJECTED", input_version_id=base_version_id, output_version_id=None,
                        canonical_graph_hash=None, semantic_change=False, created_at=created_at,
                        detail={"reasons": problems})
        return AntuOutcome(antu_id, VALIDATION_REJECTED, revision, None, None, False,
                           {"reasons": problems, "accepted_version_untouched": base_version_id})

    mapu = {
        "mapu_id": mapu_declaration["mapu_id"],
        "version": mapu_declaration.get("version"),
        "revision": mapu_declaration.get("revision"),
        "source_uri": mapu_declaration["source_uri"],
        "sha256": sha256_text(mapu_text), "declared_sha256": mapu_declaration.get("sha256"),
        "sha256_matches_declared": mapu_declaration.get("sha256") in (None, sha256_text(mapu_text)),
        "media_type": mapu_declaration.get("media_type") or "text/plain",
        "source_type": mapu_declaration.get("source_type") or "text",
        "source_identity": mapu_declaration.get("source_identity") or "",
        "license": mapu_declaration.get("license"),
        "source_timestamp": mapu_declaration.get("source_timestamp"),
        "trust_level": mapu_declaration.get("trust_level") or "UNVERIFIED",
        "access_policy": mapu_declaration.get("access_policy") or "experimental",
        "metadata": mapu_declaration.get("metadata") or {},
        "content": mapu_text, "content_chars": len(mapu_text),
        "content_sha256": sha256_text(mapu_text),
        "source_file": str(mapu_declaration.get("source_file") or ""),
        "units": [instruction["unit"]["unit_id"]],
        "metadata_source": mapu_declaration.get("metadata_source"),
    }
    candidate = _merge(base_document, instruction, mapu, created_at)
    graph = candidate.pop("_canonical_graph")
    revision = next_revision(store)
    result = commit_version(
        store, document=candidate, identity=identity, antu_id=antu_id, unit_revision=revision,
        created_at=created_at, projector_version=PROJECTOR_VERSION,
        openviking_version=openviking_version, expected_parent_version_id=base_version_id,
        failpoint=failpoint,
    )
    record_revision(store, leftraru_id=instruction["leftraru_id"], antu_id=antu_id, revision=revision,
                    status="COMPLETED", input_version_id=base_version_id,
                    output_version_id=result["version"]["version_id"],
                    canonical_graph_hash=result["version"]["canonical_graph_hash"],
                    semantic_change=True, created_at=created_at,
                    detail={"mapu_id": mapu["mapu_id"], "mapu_sha256": mapu["content_sha256"],
                            "objects_added": {key: len(instruction["proposal"].get(key) or [])
                                              for key in ("entities", "relations", "assertions", "evidence")}})
    return AntuOutcome(antu_id, VALIDATION_OK, revision, result["version"]["version_id"],
                       result["version"]["canonical_graph_hash"], True,
                       {"parent_version_id": base_version_id, "mapu_id": mapu["mapu_id"],
                        "commit_id": result["commit_id"],
                        "operation_key": result["operation"]["operation_key"],
                        "canonical_graph": graph})
