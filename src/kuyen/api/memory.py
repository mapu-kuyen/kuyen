"""Public high-level API: the memory a Leftraru agent opens and governs.

Design rules:
  * the canonical store is the authority; a projection is optional scaffolding;
  * an Antu is executed (validated) before it can be committed;
  * nothing is committed if it is not validated and completely persisted;
  * every operation is deterministic and works without OpenViking, an LLM or a network.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..canonical import digest, read_json, sha256_text
from ..contracts import PROJECTOR_VERSION, SIDECAR_SCHEMA_VERSION, STORE_FORMAT_VERSION
from ..editing.diff import diff_documents, summarize as summarize_diff
from ..editing.editors import GraphEditorPort
from ..editing import outcome as edit_outcome
from ..semantics.scope import AntuScope, permissions_for
from ..editing.service import (STATUS_CLARIFICATION, STATUS_CONFLICT,
                               STATUS_INTERPRETATION_FAILED, STATUS_INTERPRETATION_INCOMPLETE,
                               STATUS_NO_CHANGES, STATUS_REJECTED, STATUS_VALIDATED, EditRun,
                               derive_antu_id, edit_provenance_record, run_edit)
from ..semantics.origin import public_view as origin_view
from ..errors import (AmbiguousSourceUnit, AntuConflictError, CommitError, ConflictError,
                      StoreError, ValidationRejected)
from ..lifecycle.antu import (_merge, _bump_version, _verify_proposal, seal_document,
                              validate_antu_structure)
from ..lifecycle.ledger import (append_event, events, read_classified, recovery_records,
                                repair_ledger, verify_chain)
from ..lifecycle.unit import (ensure_unit, next_revision, read_state, reconcile_unit_history,
                              record_revision, revisions, uncovered_versions, verify_unit_history)
from ..models import KuyenGraph
from ..storage.commit import (prepare_commit_artifacts, commit_version, pending_commits,
                              recover_pending, verify_commit)
from ..storage.registry import current, lineage, verify_registry
from ..storage.store import CanonicalStore
from ..storage.versions import list_versions, read_version, verify_version
from ..projection.native import document_from_sidecar, load_sidecar, project as run_projection
from ..provenance import read_source, text_only_record
from ..projection.outbox import (enqueue, list_operations, release_interrupted,
                                 stats as outbox_stats)
from ..projection.reconciliation import reconcile as reconcile_store
from ..sidecar import verify_sidecar
from ..backup.archive import create_backup, restore_backup, verify_backup
from ..recovery.rebuild import recover_store


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_operation(method):
    """Run a whole write operation under the store writer lock (M1).

    The lock is re-entrant, so the ledger and unit-history primitives the operation calls
    take it again without opening a second descriptor. This is what makes `next_revision`,
    `record_revision` and every `append_event` inside one Antu execution a single
    indivisible operation for threads and for processes.
    """
    import functools

    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._store.writer_lock():
            return method(self, *args, **kwargs)

    return wrapper


def _mapu_ids(sidecar: dict[str, Any]) -> set[str]:
    return {mapu.get("mapu_id") for mapu in sidecar.get("mapus") or [] if mapu.get("mapu_id")}


def _select_source_unit(units: list[dict[str, Any]], unit_id: str, *,
                        mapu_id: str | None) -> dict[str, Any]:
    """Return the single SOURCE_UNIT called `unit_id`, scoped to `mapu_id` when given.

    `unit_id` is local to its MAPU (DATA_MODEL.md), so the same identifier can exist in
    several documents of one version. A lookup that is not scoped by MAPU is ambiguous as
    soon as that happens; returning the first match would attribute evidence to the wrong
    document, so this returns a unit only when the selection is unique
    (KUYEN_SOURCE_UNIT_DISAMBIGUATION_03). Enumeration order is never a tie-breaker.
    """
    candidates = [unit for unit in units
                  if unit.get("unit_id") == unit_id
                  and (mapu_id is None or unit.get("mapu_id") == mapu_id)]
    if not candidates:
        where = f"MAPU {mapu_id}" if mapu_id is not None else "this version"
        raise StoreError(f"{where} has no SOURCE_UNIT {unit_id}",
                         details={"unit_id": unit_id, "mapu_id": mapu_id})
    if len(candidates) > 1:
        raise AmbiguousSourceUnit(
            f"SOURCE_UNIT {unit_id} exists in {len(candidates)} MAPUs "
            f"({', '.join(sorted(str(unit.get('mapu_id')) for unit in candidates))}); "
            f"resolve it with mapu_id",
            details={"unit_id": unit_id,
                     "candidates": sorted(str(unit.get("mapu_id")) for unit in candidates)})
    return candidates[0]


def _evidence_unit(sidecar: dict[str, Any], evidence: dict[str, Any],
                   mapus: dict[str, Any]) -> dict[str, Any]:
    """Resolve the SOURCE_UNIT an evidence belongs to and verify the whole chain.

    The evidence is not trusted to name its own document: the MAPU must exist in this
    version, a unit *of that MAPU* must contain the span, the unit's text must still match
    its hash and must still hold the quote at those offsets, and the declared source hash
    must be the MAPU's hash. Any inconsistency raises instead of returning a plausible but
    wrong source (KUYEN_SOURCE_UNIT_DISAMBIGUATION_03).
    """
    identifier = evidence.get("evidence_id")
    mapu_id = evidence.get("mapu_id")
    if mapu_id not in mapus:
        raise StoreError(f"evidence {identifier} cites MAPU {mapu_id!r}, which this version "
                         f"does not hold", details={"evidence_id": identifier, "mapu_id": mapu_id})
    start, end = evidence.get("char_start"), evidence.get("char_end")
    if not isinstance(start, int) or not isinstance(end, int) or start < 0 or end < start:
        raise StoreError(f"evidence {identifier} has no usable character span: {start}:{end}",
                         details={"evidence_id": identifier, "char_start": start,
                                  "char_end": end})
    units = [unit for unit in sidecar["canonical"]["source_units"]
             if unit.get("mapu_id") == mapu_id]
    containing = [unit for unit in units
                  if (unit.get("char_start") or 0) <= start and end <= (unit.get("char_end") or 0)]
    if not containing:
        raise StoreError(f"evidence {identifier} at {start}:{end} is not covered by any "
                         f"SOURCE_UNIT of MAPU {mapu_id}",
                         details={"evidence_id": identifier, "mapu_id": mapu_id,
                                  "char_start": start, "char_end": end})
    if len(containing) > 1:
        raise AmbiguousSourceUnit(
            f"evidence {identifier} at {start}:{end} is covered by {len(containing)} "
            f"SOURCE_UNITs of MAPU {mapu_id}",
            details={"evidence_id": identifier, "mapu_id": mapu_id,
                     "candidates": sorted(str(unit.get("unit_id")) for unit in containing)})
    unit = containing[0]
    content = str(unit.get("content") or "")
    if unit.get("content_sha256") and sha256_text(content) != unit["content_sha256"]:
        raise StoreError(f"SOURCE_UNIT {unit.get('unit_id')} of MAPU {mapu_id} does not match "
                         f"its content hash", details={"mapu_id": mapu_id,
                                                       "unit_id": unit.get("unit_id")})
    quote = evidence.get("quote")
    if quote is not None and content[start:end] != quote:
        raise StoreError(f"evidence {identifier} does not match the source at {start}:{end} of "
                         f"MAPU {mapu_id}", details={"evidence_id": identifier,
                                                     "mapu_id": mapu_id, "unit_id": unit.get("unit_id")})
    mapu = mapus[mapu_id]
    if evidence.get("source_sha256") and mapu.get("content_sha256") \
            and evidence["source_sha256"] != mapu["content_sha256"]:
        raise StoreError(f"evidence {identifier} declares a source hash that is not the hash "
                         f"of MAPU {mapu_id}", details={"evidence_id": identifier,
                                                        "mapu_id": mapu_id})
    return unit




@dataclass(frozen=True)
class MemoryVersion:
    version_id: str
    kuyen_id: str
    kuyen_version: str
    canonical_graph_hash: str
    parent_version_id: str | None
    antu_id: str
    unit_revision: str
    created_at: str
    counts: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"version_id": self.version_id, "kuyen_id": self.kuyen_id,
                "kuyen_version": self.kuyen_version, "canonical_graph_hash": self.canonical_graph_hash,
                "parent_version_id": self.parent_version_id, "antu_id": self.antu_id,
                "unit_revision": self.unit_revision, "created_at": self.created_at, "counts": self.counts}


@dataclass
class AntuExecution:
    """The result of executing an Antu **without** committing it."""

    antu_id: str
    status: str
    detail: dict[str, Any]
    base_version_id: str | None = None
    candidate_document: dict[str, Any] | None = None
    unit_revision: str | None = None
    committed_version_id: str | None = None

    @property
    def committable(self) -> bool:
        return self.status == "VALIDATED" and self.candidate_document is not None

    def to_dict(self) -> dict[str, Any]:
        return {"antu_id": self.antu_id, "status": self.status, "detail": self.detail,
                "base_version_id": self.base_version_id, "unit_revision": self.unit_revision,
                "committable": self.committable, "committed_version_id": self.committed_version_id}


@dataclass(frozen=True)
class CommitResult:
    version: MemoryVersion
    operation_key: str | None
    antu_id: str

    def to_dict(self) -> dict[str, Any]:
        return {"version": self.version.to_dict(), "operation_key": self.operation_key,
                "antu_id": self.antu_id}


@dataclass
class AntuEditResult:
    """The outcome of one Antü that edits the graph directly (no OpenViking, §2 camino B)."""

    antu_id: str
    status: str
    instruction: str
    base_version_id: str | None = None
    version_id: str | None = None
    #: Accepted operations, each with its lifecycle `status`: `VALIDATED` while the Antü has
    #: not been committed, `COMMITTED` only after the canonical commit (experiment 14, §9).
    operations: list[dict[str, Any]] = field(default_factory=list)
    #: What the deterministic applier actually did, with the previous value it replaced.
    applied: list[dict[str, Any]] = field(default_factory=list)
    rejected: list[dict[str, Any]] = field(default_factory=list)
    affected: dict[str, list[str]] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)
    evidence: list[str] = field(default_factory=list)
    validation: dict[str, Any] = field(default_factory=dict)
    clarification: dict[str, Any] | None = None
    conflict: dict[str, Any] | None = None
    model: dict[str, Any] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)
    diff: dict[str, Any] | None = None
    reasons: list[str] = field(default_factory=list)
    committed: bool = False
    # §2/§5: the portable identity and the local decision. The same Antü has one global
    # identity and one applicability result per KÜYEN.
    antu_global_id: str | None = None
    kuyen_id: str | None = None
    scope: dict[str, Any] = field(default_factory=dict)
    applicability: dict[str, int] = field(default_factory=dict)
    declined: list[dict[str, Any]] = field(default_factory=list)
    schema_changes: list[dict[str, Any]] = field(default_factory=list)
    #: §7: the operational outcome of the Antü in this KÜYEN, from the closed vocabulary of
    #: `editing.outcome`. It distinguishes a committed change from a satisfied request, a
    #: permission block, an invalid proposal and a failed interpretation.
    outcome: str = "NOT_EVALUATED"
    #: The same, operation by operation: a mixed Antü keeps one state per operation.
    outcomes: list[dict[str, Any]] = field(default_factory=list)
    run: EditRun | None = field(default=None, repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {"antu_id": self.antu_id, "antu_global_id": self.antu_global_id,
                "status": self.status, "outcome": self.outcome, "outcomes": list(self.outcomes),
                "instruction": self.instruction,
                "kuyen_id": self.kuyen_id,
                "base_version_id": self.base_version_id, "version_id": self.version_id,
                "operations": list(self.operations), "applied": list(self.applied),
                "rejected": list(self.rejected),
                "affected": {key: list(value) for key, value in self.affected.items()},
                "provenance": dict(self.provenance), "evidence": list(self.evidence),
                "validation": dict(self.validation), "clarification": self.clarification,
                "conflict": self.conflict, "model": dict(self.model),
                "context": dict(self.context), "diff": self.diff,
                "scope": dict(self.scope), "applicability": dict(self.applicability),
                "declined": list(self.declined),
                "schema_changes": list(self.schema_changes),
                "reasons": list(self.reasons), "committed": self.committed}


class KuyenMemory:
    """A governed canonical memory backed by its own immutable store."""

    def __init__(self, store: CanonicalStore) -> None:
        self._store = store

    # -- construction -------------------------------------------------------
    @classmethod
    def open(cls, path: str | Path) -> "KuyenMemory":
        """Open an existing canonical memory (read/write, no creation)."""
        return cls(CanonicalStore(path))

    @classmethod
    def create(cls, path: str | Path, *, leftraru_id: str, purpose: str = "canonical memory") -> "KuyenMemory":
        """Create a new, empty canonical memory for a Leftraru unit."""
        store = CanonicalStore(path, create=True)
        ensure_unit(store, leftraru_id=leftraru_id, purpose=purpose, created_at=_now())
        return cls(store)

    @property
    def path(self) -> Path:
        return self._store.root

    @property
    def store(self) -> CanonicalStore:
        return self._store

    # -- state --------------------------------------------------------------
    def status(self) -> dict[str, Any]:
        """Read-only snapshot of the memory."""
        pointer = current(self._store)
        return {"path": str(self._store.root), "store_format_version": STORE_FORMAT_VERSION,
                "unit": read_state(self._store), "current": pointer,
                "versions": len(list_versions(self._store)),
                "projections": len(list_projections(self._store)),
                "outbox": outbox_stats(self._store),
                "integrity": self.verify()}

    def current(self) -> MemoryVersion | None:
        pointer = current(self._store)
        return self._version(pointer["version_id"]) if pointer else None

    def versions(self) -> list[MemoryVersion]:
        return [self._version(record.version_id) for record in list_versions(self._store)]

    def history(self) -> list[dict[str, Any]]:
        """Unit revisions (one per Antu execution), oldest first."""
        return revisions(self._store)

    def ledger(self) -> list[dict[str, Any]]:
        return events(self._store)

    def ledger_state(self) -> dict[str, Any]:
        """Read-only classification of the ledger: intact, truncated tail or corrupt.

        Never raises and never repairs, so an operator can inspect a damaged ledger without
        the store being modified as a side effect of the inspection.
        """
        report = read_classified(self._store)
        return {"state": report["state"], "events": len(report["events"]),
                "problems": report["problems"], "tail": report["tail"],
                "recovery": recovery_records(self._store)}

    def lineage(self, version_id: str | None = None) -> list[MemoryVersion]:
        target = version_id or (current(self._store) or {}).get("version_id")
        if not target:
            return []
        return [self._version(item["version_id"]) for item in lineage(self._store, target)]

    def _version(self, version_id: str) -> MemoryVersion:
        manifest = read_version(self._store, version_id).manifest
        return MemoryVersion(version_id=manifest["version_id"], kuyen_id=manifest["kuyen_id"],
                             kuyen_version=manifest["kuyen_version"],
                             canonical_graph_hash=manifest["canonical_graph_hash"],
                             parent_version_id=manifest.get("parent_version_id"),
                             antu_id=manifest["antu_id"], unit_revision=manifest["unit_revision"],
                             created_at=manifest["created_at"], counts=manifest.get("counts") or {})

    # -- read memory --------------------------------------------------------
    def graph(self, version_id: str | None = None) -> dict[str, Any]:
        """Return the canonical graph of a version (current by default)."""
        target = version_id or (current(self._store) or {}).get("version_id")
        if not target:
            raise StoreError("this memory has no committed version yet")
        sidecar = load_sidecar(self._store, target)
        document = document_from_sidecar(sidecar)
        graph = {"kuyen_id": document["kuyen"]["kuyen_id"], "version": document["kuyen"]["version"],
                 "antu_id": document["kuyen"]["antu_id"], "mapu_ids": document["kuyen"]["mapu_ids"],
                 "schema_version": document["kuyen"]["schema_version"],
                 "status": document["kuyen"]["status"],
                 "entities": document["canonical"]["entities"],
                 "relations": document["canonical"]["relations"],
                 "assertions": document["canonical"]["assertions"],
                 "evidence": document["canonical"]["evidence"],
                 "coverage": document["canonical"]["coverage"],
                 "provenance": document["kuyen"]["provenance"],
                 "content_digest": document["kuyen"].get("content_digest"),
                 "provenance_digest": document["kuyen"].get("provenance_digest")}
        if "schema" in document:
            graph["schema"] = document["schema"]
        if digest(graph) != self._version(target).canonical_graph_hash:
            raise StoreError(f"version {target} does not match its canonical hash")
        return graph

    def sidecar(self, version_id: str | None = None) -> dict[str, Any]:
        target = version_id or (current(self._store) or {}).get("version_id")
        if not target:
            raise StoreError("this memory has no committed version yet")
        return load_sidecar(self._store, target)

    def source_unit(self, unit_id: str, version_id: str | None = None, *,
                    mapu_id: str | None = None) -> dict[str, Any]:
        """One SOURCE_UNIT with its verified text slice, resolved inside its MAPU.

        `unit_id` is local to a MAPU, so a version with two documents can hold two `u00`
        units. Pass `mapu_id` to select the document; without it the identifier must be
        unique, otherwise `AmbiguousSourceUnit` is raised — the first match is never
        returned (KUYEN_SOURCE_UNIT_DISAMBIGUATION_03).
        """
        sidecar = self.sidecar(version_id)
        if mapu_id is not None and mapu_id not in _mapu_ids(sidecar):
            raise StoreError(f"unknown MAPU {mapu_id}",
                             details={"mapu_id": mapu_id,
                                      "mapu_ids": sorted(_mapu_ids(sidecar))})
        return _select_source_unit(sidecar["canonical"]["source_units"], unit_id,
                                   mapu_id=mapu_id)

    def evidence_of(self, claim_id: str, version_id: str | None = None) -> list[dict[str, Any]]:
        """Evidence behind an entity, relation or assertion (traceability entry point)."""
        sidecar = self.sidecar(version_id)
        canonical = sidecar["canonical"]
        claim = next((item for group in ("entities", "relations", "assertions")
                      for item in canonical[group]
                      if claim_id in {item.get("entity_id"), item.get("relation_id"), item.get("assertion_id")}),
                     None)
        if claim is None:
            raise StoreError(f"unknown claim {claim_id}")
        wanted = set(claim.get("evidence_ids") or [])
        return [item for item in canonical["evidence"] if item["evidence_id"] in wanted]

    def trace(self, claim_id: str, version_id: str | None = None) -> dict[str, Any]:
        """claim -> evidence -> SOURCE_UNIT -> MAPU, resolved inside the evidence's own MAPU.

        Every step is checked, not merely looked up: the MAPU must exist in this version, a
        SOURCE_UNIT *of that MAPU* must contain the span, the unit's text must still match
        its hash and must still hold the quote at those offsets. A broken or crossed chain
        raises `StoreError` instead of returning a plausible but wrong document
        (KUYEN_SOURCE_UNIT_DISAMBIGUATION_03).
        """
        sidecar = self.sidecar(version_id)
        evidence = self.evidence_of(claim_id, version_id)
        mapus = {mapu["mapu_id"]: mapu for mapu in sidecar.get("mapus") or []}
        chain = []
        for item in evidence:
            unit = _evidence_unit(sidecar, item, mapus)
            chain.append({"evidence_id": item["evidence_id"], "quote": item["quote"],
                          "char_start": item["char_start"], "char_end": item["char_end"],
                          "source_unit_id": unit["unit_id"],
                          "source_unit_mapu_id": unit["mapu_id"],
                          "source_unit_section": unit.get("section"),
                          "mapu_id": item["mapu_id"],
                          "mapu_content_sha256": mapus[item["mapu_id"]].get("content_sha256")})
        return {"claim_id": claim_id, "evidence": chain}

    def diff(self, before: str | None = None, after: str | None = None) -> dict[str, Any]:
        """Reproducible difference between two versions of this memory (§3, §8.3).

        Defaults to `parent → current`, which is exactly the difference the last Antü
        produced.
        """
        pointer = current(self._store)
        if pointer is None:
            raise StoreError("this memory has no committed version yet")
        after_id = after or pointer["version_id"]
        before_id = before or self._version(after_id).parent_version_id
        if before_id is None:
            raise StoreError("the version has no parent to compare against",
                             details={"version_id": after_id})
        report = diff_documents(load_sidecar(self._store, before_id),
                                load_sidecar(self._store, after_id))
        report["summary"] = summarize_diff(report)
        return report

    def current_objects(self, group: str = "assertions",
                        version_id: str | None = None) -> list[dict[str, Any]]:
        """Objects of a collection that are current: not retracted and not superseded."""
        from ..editing.diff import current_objects as _current

        return _current(self.sidecar(version_id), group)

    # -- Antu lifecycle -----------------------------------------------------
    @_write_operation
    def execute_antu(self, antu: dict[str, Any], *, mapu_source: str | Path | None = None) -> AntuExecution:
        """Validate an Antu and prepare the candidate; nothing is committed yet."""
        structural = validate_antu_structure(antu)
        antu_id = antu.get("antu_id") if isinstance(antu, dict) else None
        if structural and isinstance(antu_id, str) and antu_id.strip():
            append_event(self._store, "ANTU_REJECTED", {"antu_id": antu_id,
                                                        "reasons": structural,
                                                        "recorded_at": _now()})
        if structural:
            raise ValidationRejected("ANTU_STRUCTURE_INVALID: " + "; ".join(structural[:6]),
                                     report={"problems": structural})
        pointer = current(self._store)
        if pointer is None:
            raise ValidationRejected("an Antu needs a committed base version")
        base_version_id = antu.get("base_version_id") or pointer["version_id"]
        previous = [event for event in events(self._store) if event.get("antu_id") == antu_id
                    and event["event_type"] in {"ANTU_COMPLETED", "ANTU_NO_SEMANTIC_CHANGE", "ANTU_REJECTED"}]
        if previous:
            last = previous[-1]
            return AntuExecution(antu_id=antu_id, status="REPLAYED",
                                 detail={"replayed_from_seq": last["seq"],
                                         "committed_version_id": last.get("version_id")},
                                 base_version_id=base_version_id,
                                 committed_version_id=last.get("version_id"))
        append_event(self._store, "ANTU_RECEIVED", {"antu_id": antu_id, "leftraru_id": antu.get("leftraru_id"),
                                                    "purpose": antu.get("purpose"), "kind": antu.get("kind"),
                                                    "base_version_id": base_version_id, "recorded_at": _now()})
        if base_version_id != pointer["version_id"]:
            reason = f"STALE_BASE: Antu targets {base_version_id}, current is {pointer['version_id']}"
            append_event(self._store, "ANTU_REJECTED", {"antu_id": antu_id, "reason": reason, "recorded_at": _now()})
            return AntuExecution(antu_id=antu_id, status="CONFLICT", detail={"reason": reason},
                                 base_version_id=base_version_id)
        sidecar = load_sidecar(self._store, base_version_id)
        base_document = document_from_sidecar(sidecar)
        if antu.get("kind") == "VERIFY_ONLY":
            append_event(self._store, "ANTU_NO_SEMANTIC_CHANGE", {
                "antu_id": antu_id, "version_id": base_version_id,
                "canonical_graph_hash": base_document["kuyen"]["canonical_graph_hash"],
                "recorded_at": _now(), "reason": "VERIFY_ONLY produces no new knowledge"})
            return AntuExecution(antu_id=antu_id, status="NO_SEMANTIC_CHANGE",
                                 detail={"new_version_created": False}, base_version_id=base_version_id)
        instruction = dict(antu)
        instruction["_base_entity_ids"] = [entity["entity_id"] for entity in base_document["canonical"]["entities"]]
        instruction["_base_object_ids"] = {
            "entity_ids": [item["entity_id"] for item in base_document["canonical"]["entities"]],
            "relation_ids": [item["relation_id"] for item in base_document["canonical"]["relations"]],
            "assertion_ids": [item["assertion_id"] for item in base_document["canonical"]["assertions"]],
            "evidence_ids": [item["evidence_id"] for item in base_document["canonical"]["evidence"]],}
        declaration = instruction.get("mapu") or {}
        source = None
        if mapu_source is None:
            problems = _verify_proposal(instruction, None, declaration=declaration,
                                        base_ids=instruction.get("_base_object_ids"))
            mapu_text = ""
        else:
            # bytes, strict decode, no newline translation: offsets and hashes must address
            # the file the evidence came from (KUYEN_SEMANTIC_SECURITY_HARDENING_04, M4)
            source = read_source(mapu_source)
            mapu_text = source.text
            declared = declaration.get("sha256")
            if declared and declared not in (source.bytes_sha256, source.text_sha256):
                problems = ["declared MAPU hash does not match the provided source"]
            else:
                problems = _verify_proposal(instruction, mapu_text, declaration=declaration,
                                            base_ids=instruction.get("_base_object_ids"))
        if problems:
            append_event(self._store, "ANTU_REJECTED", {"antu_id": antu_id, "reasons": problems,
                                                        "recorded_at": _now()})
            return AntuExecution(antu_id=antu_id, status="REJECTED", detail={"reasons": problems},
                                 base_version_id=base_version_id)
        source_provenance = source.to_record() if source is not None else text_only_record()
        source_provenance["declared_sha256_matches"] = (
            "SOURCE_BYTES" if source is not None and declaration.get("sha256") == source.bytes_sha256
            else "DECODED_TEXT" if source is not None and declaration.get("sha256") == source.text_sha256
            else None)
        mapu = {**source_provenance, "mapu_id": declaration["mapu_id"],
                "version": declaration.get("version"),
                "revision": declaration.get("revision"), "source_uri": declaration["source_uri"],
                "sha256": sha256_text(mapu_text), "declared_sha256": declaration.get("sha256"),
                "sha256_matches_declared": declaration.get("sha256") in (None, sha256_text(mapu_text)),
                "media_type": "text/plain", "source_type": "text",
                "source_identity": declaration.get("source_identity") or "",
                "license": declaration.get("license"), "source_timestamp": declaration.get("source_timestamp"),
                "trust_level": declaration.get("trust_level") or "UNVERIFIED",
                "access_policy": declaration.get("access_policy") or "experimental",
                "metadata": declaration.get("metadata") or {}, "content": mapu_text,
                "content_chars": len(mapu_text), "content_sha256": sha256_text(mapu_text),
                "source_file": str(declaration.get("source_file") or ""),
                "units": [instruction["unit"]["unit_id"]],
                "metadata_source": declaration.get("metadata_source")}
        candidate = _merge(base_document, instruction, mapu, _now())
        candidate.pop("_canonical_graph", None)
        # `VALIDATED` must mean "this candidate passes the commit validation right now".
        # The commit runs the same check again (it is the authority); running it here keeps
        # the state honest: a contract defect is a rejection, not a later surprise.
        try:
            prepare_commit_artifacts(candidate, created_at=_now(),
                                     projector_version=PROJECTOR_VERSION,
                                     openviking_version=None)
        except CommitError as exc:
            reasons = [str(exc)[:400]]
            append_event(self._store, "ANTU_REJECTED", {"antu_id": antu_id, "reasons": reasons,
                                                        "recorded_at": _now()})
            return AntuExecution(antu_id=antu_id, status="REJECTED", detail={"reasons": reasons},
                                 base_version_id=base_version_id)
        return AntuExecution(antu_id=antu_id, status="VALIDATED",
                             detail={"objects_declared": {key: len((antu.get("proposal") or {}).get(key) or [])
                                                          for key in ("entities", "relations", "assertions", "evidence")}},
                             base_version_id=base_version_id, candidate_document=candidate)

    @_write_operation
    def commit(self, execution: AntuExecution) -> CommitResult:
        """Commit a validated Antu; refuses anything that was not validated."""
        if execution.status == "REPLAYED":
            version_id = execution.committed_version_id
            if version_id is None:
                raise CommitError("the replay has no committed version to return")
            revision = next_revision(self._store)
            record_revision(self._store, leftraru_id=(read_state(self._store) or {}).get("leftraru_id", ""),
                            antu_id=execution.antu_id, revision=revision, status="REPLAYED",
                            input_version_id=execution.base_version_id, output_version_id=version_id,
                            canonical_graph_hash=self._version(version_id).canonical_graph_hash,
                            semantic_change=False, created_at=_now(), detail={"idempotent": True})
            return CommitResult(version=self._version(version_id), operation_key=None, antu_id=execution.antu_id)
        if not execution.committable:
            raise CommitError(f"an Antu in state {execution.status} cannot be committed")
        unit = read_state(self._store) or {}
        revision = next_revision(self._store)
        result = commit_version(
            self._store, document=execution.candidate_document,
            identity={"leftraru_id": unit.get("leftraru_id"),
                      "kuyen_id": execution.candidate_document["kuyen"]["kuyen_id"],
                      "kuyen_version": execution.candidate_document["kuyen"]["version"]},
            antu_id=execution.antu_id, unit_revision=revision, created_at=_now(),
            projector_version=PROJECTOR_VERSION, openviking_version=None,
            expected_parent_version_id=execution.base_version_id)
        record_revision(self._store, leftraru_id=unit.get("leftraru_id", ""), antu_id=execution.antu_id,
                        revision=revision, status="COMPLETED",
                        input_version_id=execution.base_version_id,
                        output_version_id=result["version"]["version_id"],
                        canonical_graph_hash=result["version"]["canonical_graph_hash"],
                        semantic_change=True, created_at=_now(),
                        detail={"commit_id": result["commit_id"],
                                "objects_added": execution.detail.get("objects_declared")})
        execution.committed_version_id = result["version"]["version_id"]
        execution.unit_revision = revision
        execution.status = "COMMITTED"
        return CommitResult(version=self._version(result["version"]["version_id"]),
                            operation_key=result["operation"]["operation_key"], antu_id=execution.antu_id)
    # -- direct Antü graph editing (no OpenViking) ---------------------------
    def apply_antu(self, instruction: str, *, editor: GraphEditorPort,
                   antu_id: str | None = None, actor: dict[str, Any] | None = None,
                   base_version_id: str | None = None, dry_run: bool = False,
                   object_limit: int | None = None,
                   scope: Any = None) -> AntuEditResult:
        """Interpret an Antü and commit the resulting version. OpenViking is never used.

        Concurrency: the interpretation happens outside the writer lock (it is a network
        call); the base version is re-checked inside the lock before anything is written,
        so an edit computed against a version that has already moved is refused with
        `STALE_BASE` instead of overwriting the newer knowledge. `scope` is the effective
        permission of this Antü in this KÜYEN (§4): it filters the context and it authorises
        every operation, here and again before the commit. Idempotency: an Antü whose
        identity already reached a terminal state in the ledger is replayed, never applied
        twice. Nothing is written at all when the interpretation is ambiguous, conflicts,
        produces no operation or fails validation.
        """
        text = " ".join(str(instruction or "").split())
        if not text:
            raise ValidationRejected("an Antü edit requires a non-empty instruction",
                                     report={"code": "INSTRUCTION_EMPTY"})
        antu_id = antu_id or derive_antu_id(text)
        pointer = current(self._store)
        if pointer is None:
            raise ValidationRejected("an Antü needs a committed base version",
                                     report={"code": "STORE_EMPTY"})
        target_base = base_version_id or pointer["version_id"]
        if target_base != pointer["version_id"]:
            return self._record_edit_rejection(
                antu_id=antu_id, instruction=text, base_version_id=target_base,
                code="STALE_BASE",
                reason=f"STALE_BASE: the Antü targets {target_base}, current is "
                       f"{pointer['version_id']}",
                dry_run=dry_run)
        replay = self._edit_replay(antu_id, text)
        if replay is not None:
            return replay
        sidecar = load_sidecar(self._store, target_base)
        document = document_from_sidecar(sidecar)
        graph = self.graph(target_base)
        graph_view = {**graph, "version_id": target_base}
        run = run_edit(instruction=text, antu_id=antu_id, base_document=document,
                       graph=graph_view, editor=editor, actor=actor,
                       object_limit=object_limit, scope=scope)
        return self._finish_edit(run, sidecar=sidecar, document=document,
                                 target_base=target_base, actor=actor, dry_run=dry_run)

    def _edit_replay(self, antu_id: str, instruction: str) -> AntuEditResult | None:
        terminal = {"ANTU_COMPLETED", "ANTU_REJECTED", "ANTU_NO_SEMANTIC_CHANGE",
                    "ANTU_CLARIFICATION_REQUIRED"}
        previous = [event for event in events(self._store)
                    if event.get("antu_id") == antu_id and event.get("event_type") in terminal]
        if not previous:
            return None
        last = previous[-1]
        return AntuEditResult(
            antu_id=antu_id, status="REPLAYED", instruction=instruction,
            base_version_id=last.get("base_version_id"), version_id=last.get("version_id"),
            provenance={"kind": "ANTU_INSTRUCTION", "antu_id": antu_id, "replayed": True},
            reasons=[f"the Antü already reached {last.get('event_type')} at seq "
                     f"{last.get('seq')}"], committed=False,
            outcome=edit_outcome.ALREADY_SATISFIED,
            outcomes=[{"operation_id": None, "op": None,
                       "outcome": edit_outcome.ALREADY_SATISFIED,
                       "detail": f"replayed from {last.get('event_type')}"}])


    def _record_edit_rejection(self, *, antu_id: str, instruction: str, base_version_id: str | None,
                               code: str, reason: str, dry_run: bool) -> AntuEditResult:
        if not dry_run:
            with self._store.writer_lock():
                append_event(self._store, "ANTU_REJECTED", {
                    "antu_id": antu_id, "kind": "GRAPH_EDIT", "code": code, "reason": reason,
                    "instruction": instruction, "recorded_at": _now()})
                unit = read_state(self._store) or {}
                record_revision(self._store, leftraru_id=unit.get("leftraru_id", ""),
                                antu_id=antu_id, revision=next_revision(self._store),
                                status="REJECTED", input_version_id=base_version_id,
                                output_version_id=None, canonical_graph_hash=None,
                                semantic_change=False, created_at=_now(),
                                detail={"code": code, "reason": reason})
        return AntuEditResult(antu_id=antu_id, status="REJECTED", instruction=instruction,
                              base_version_id=base_version_id, reasons=[reason],
                              conflict={"code": code, "reason": reason},
                              outcome=edit_outcome.INVALID_PROPOSAL,
                              outcomes=[{"operation_id": None, "op": None,
                                         "outcome": edit_outcome.INVALID_PROPOSAL,
                                         "detail": f"{code}: {reason}"}])



    def _edit_result(self, run: EditRun, *, version_id: str | None,
                     committed: bool = False) -> AntuEditResult:
        validation = run.validation.to_dict() if run.validation else {}
        lifecycle = "COMMITTED" if committed else "VALIDATED"
        operations = [{**dict(item), "status": lifecycle}
                      for item in (validation.get("accepted") or [])]
        # An applied change exists only in the working candidate until the commit persists.
        # If the Antü is rejected afterwards, the record says so instead of looking confirmed.
        applied_lifecycle = "COMMITTED" if committed else "DISCARDED"
        applied = [{**dict(item), "status": applied_lifecycle}
                   for item in ((run.application or {}).get("applied") or [])]
        # §7: what happened, operation by operation, with the commit flag the caller owns.
        declined = validation.get("declined") or []
        outcomes = edit_outcome.operation_outcomes(
            status=run.status, committed=committed,
            accepted=validation.get("accepted") or [], declined=declined,
            rejected=validation.get("rejected") or [])
        return AntuEditResult(
            antu_id=run.antu_id, status=run.status, instruction=run.instruction,
            base_version_id=run.base_version_id, version_id=version_id,
            operations=operations, applied=applied,
            rejected=validation.get("rejected") or [],
            outcome=edit_outcome.run_outcome(run.status, committed=committed,
                                             declined=declined),
            outcomes=outcomes,

            affected=dict((run.application or {}).get("affected") or {}),
            provenance=origin_view({"kind": "ANTU_INSTRUCTION", "antu_id": run.antu_id,
                                    "instruction_sha256": run.instruction_sha256,
                                    "base_version_id": run.base_version_id,
                                    "actor": None, "model": run.model}),
            evidence=[], validation=validation, clarification=run.clarification,
            conflict=run.conflict, model=dict(run.model),
            context=dict(run.context.selection), diff=run.diff,
            reasons=list(run.reasons), committed=False, run=run,
            antu_global_id=derive_antu_id(run.instruction), kuyen_id=self._kuyen_id(),
            scope=dict(run.scope), applicability=run.applicability, declined=run.declined,
            schema_changes=list((run.application or {}).get("schema_changes") or []))

    def _kuyen_id(self) -> str | None:
        """The identity of this memory, read from the current version.

        The identity belongs to the store, not to the unit state: the same Antü has to record
        which KÜYEN evaluated it (§2).
        """
        pointer = current(self._store) or {}
        target = pointer.get("version_id")
        if not target:
            return None
        try:
            return self._version(target).kuyen_id
        except Exception:  # noqa: BLE001 - a missing manifest is not an identity
            return None

    @staticmethod
    def _scope_violations(run: EditRun) -> list[str]:
        """Operations that the effective scope does not authorise, checked at commit time."""
        scope = AntuScope.from_dict(run.scope or None)
        problems: list[str] = []
        for operation in (run.validation.accepted if run.validation else []):
            missing = scope.missing(permissions_for(operation.op))
            if missing:
                needed = ", ".join(missing)
                problems.append(f"PERMISSION_REQUIRED: {operation.op} needs {needed} and this "
                                "KÜYEN does not grant it")
        changes = (run.application or {}).get("schema_changes") or []
        if changes and not scope.schema_write:
            problems.append("PERMISSION_REQUIRED: the candidate changes the schema and this "
                            "KÜYEN does not grant SCHEMA_WRITE")
        return problems

    def _record_edit_outcome(self, run: EditRun, *, target_base: str,
                             graph: dict[str, Any] | None = None,
                             reasons: list[str] | None = None) -> None:
        """Write the ledger trail of one edit attempt (inside the writer lock)."""
        append_event(self._store, "ANTU_RECEIVED", {
            "antu_id": run.antu_id, "antu_global_id": derive_antu_id(run.instruction),
            "kuyen_id": self._kuyen_id(),
            "kind": "GRAPH_EDIT", "instruction": run.instruction,
            "instruction_sha256": run.instruction_sha256, "base_version_id": target_base,
            "context_sha256": run.request.context_sha256,
            "prompt_sha256": run.request.prompt_sha256,
            "scope": dict(run.scope), "model": run.model, "recorded_at": _now()})
        append_event(self._store, "ANTU_EDIT_PROPOSED", {
            "antu_id": run.antu_id, "status": run.status,
            "proposal_sha256": run.model.get("proposal_sha256"),
            "operations": [item.op for item in (
                run.validation.accepted if run.validation else [])],
            "rejected": [item.code for item in (
                run.validation.rejected if run.validation else [])],
            "applicability": run.applicability,
            "declined": [item.to_dict() for item in (
                run.validation.declined if run.validation else [])],
            "recorded_at": _now()})
        unit = read_state(self._store) or {}
        if run.status == STATUS_CLARIFICATION:
            append_event(self._store, "ANTU_CLARIFICATION_REQUIRED", {
                "antu_id": run.antu_id, "question": (run.clarification or {}).get("question"),
                "recorded_at": _now()})
            # The unit revision records what happened to the graph, not the wording of the
            # decision: a clarification changed nothing. The exact ANTÜ status stays in the
            # ledger event and in `detail.edit_status`, so `verify()` keeps accepting the
            # history it was given (KUYEN_TEN_REAL_MAPU_AND_ANTU_OPERATIONS_13).
            status = "NO_SEMANTIC_CHANGE"
        elif run.status == STATUS_NO_CHANGES:
            append_event(self._store, "ANTU_NO_SEMANTIC_CHANGE", {
                "antu_id": run.antu_id, "version_id": target_base,
                "reason": (run.reasons[0] if run.reasons
                           else "the interpretation produced no operation"),
                "recorded_at": _now()})
            status = "NO_SEMANTIC_CHANGE"
        elif run.status in (STATUS_CONFLICT, STATUS_REJECTED, STATUS_INTERPRETATION_FAILED,
                            STATUS_INTERPRETATION_INCOMPLETE) or reasons:
            # An incomplete interpretation is not "no change" (§6): it is written as a
            # terminal attempt whose `edit_status` says exactly why nothing was applied.
            append_event(self._store, "ANTU_REJECTED", {
                "antu_id": run.antu_id, "kind": "GRAPH_EDIT", "status": run.status,
                "code": run.code, "reasons": reasons or run.reasons, "recorded_at": _now()})
            status = "REJECTED"

        else:
            status = None
        if status is not None:
            record_revision(self._store, leftraru_id=unit.get("leftraru_id", ""),
                            antu_id=run.antu_id, revision=next_revision(self._store),
                            status=status, input_version_id=target_base,
                            output_version_id=None if status == "REJECTED" else target_base,
                            canonical_graph_hash=None, semantic_change=False,
                            created_at=_now(),
                            detail={"kind": "GRAPH_EDIT",
                                    "edit_status": run.status,
                                    "reasons": reasons or run.reasons})


    def _finish_edit(self, run: EditRun, *, sidecar: dict[str, Any],
                     document: dict[str, Any], target_base: str,
                     actor: dict[str, Any] | None, dry_run: bool) -> AntuEditResult:
        """Validate the candidate against the canonical commit rules, then commit or record."""
        record = self._edit_result(run, version_id=None)
        if run.status != STATUS_VALIDATED:
            if not dry_run:
                with self._store.writer_lock():
                    self._record_edit_outcome(run, target_base=target_base)
            return record
        candidate = dict(run.candidate_document or {})
        # Defence in depth (§4): the scope that authorised the interpretation is checked again
        # on the accepted operations immediately before anything is written.
        violations = self._scope_violations(run)
        if violations:
            run.status = "REJECTED"
            run.reasons.extend(violations)
            record = self._edit_result(run, version_id=None)
            if not dry_run:
                with self._store.writer_lock():
                    self._record_edit_outcome(run, target_base=target_base, reasons=violations)
            return record
        provenance = dict(candidate["kuyen"].get("provenance") or {})
        base_version = str(document["kuyen"]["version"])
        new_version = _bump_version(base_version)
        edit_record = edit_provenance_record(run)
        edit_record["version"] = new_version
        provenance["edits"] = [*list(provenance.get("edits") or []), edit_record]
        candidate["kuyen"] = {**candidate["kuyen"], "provenance": provenance}
        graph = seal_document(candidate, version=new_version, antu_id=run.antu_id)
        try:
            prepare_commit_artifacts(candidate, created_at=_now(),
                                     projector_version=PROJECTOR_VERSION, openviking_version=None)
        except CommitError as exc:
            run.status = "REJECTED"
            run.reasons.append(str(exc)[:400])
            record = self._edit_result(run, version_id=None)
            if not dry_run:
                with self._store.writer_lock():
                    self._record_edit_outcome(run, target_base=target_base,
                                              reasons=[str(exc)[:400]])
            return record
        if dry_run:
            return record
        with self._store.writer_lock():
            pointer = current(self._store)
            if pointer is None or pointer["version_id"] != target_base:
                observed = (pointer or {}).get("version_id")
                reason = (f"STALE_BASE: the Antü was evaluated against {target_base} but the "
                          f"current version is {observed}")
                append_event(self._store, "ANTU_REJECTED", {
                    "antu_id": run.antu_id, "kind": "GRAPH_EDIT", "code": "STALE_BASE",
                    "reason": reason, "base_version_id": target_base, "recorded_at": _now()})
                unit = read_state(self._store) or {}
                record_revision(self._store, leftraru_id=unit.get("leftraru_id", ""),
                                antu_id=run.antu_id, revision=next_revision(self._store),
                                status="REJECTED", input_version_id=target_base,
                                output_version_id=None, canonical_graph_hash=None,
                                semantic_change=False, created_at=_now(),
                                detail={"code": "STALE_BASE", "reason": reason})
                return AntuEditResult(
                    antu_id=run.antu_id, status="CONFLICT", instruction=run.instruction,
                    base_version_id=target_base,
                    conflict={"code": "STALE_BASE", "reason": reason},
                    reasons=[reason], run=run,
                    outcome=edit_outcome.INVALID_PROPOSAL,
                    outcomes=[{"operation_id": None, "op": None,
                               "outcome": edit_outcome.INVALID_PROPOSAL,
                               "detail": f"STALE_BASE: {reason}"}])

            self._record_edit_outcome(run, target_base=target_base, graph=graph)
            unit = read_state(self._store) or {}
            revision = next_revision(self._store)
            result = commit_version(
                self._store, document=candidate,
                identity={"leftraru_id": unit.get("leftraru_id"), "kuyen_id": graph["kuyen_id"],
                          "kuyen_version": graph["version"]},
                antu_id=run.antu_id, unit_revision=revision, created_at=_now(),
                projector_version=PROJECTOR_VERSION, openviking_version=None,
                expected_parent_version_id=target_base)
            record_revision(self._store, leftraru_id=unit.get("leftraru_id", ""),
                            antu_id=run.antu_id, revision=revision, status="COMPLETED",
                            input_version_id=target_base,
                            output_version_id=result["version"]["version_id"],
                            canonical_graph_hash=result["version"]["canonical_graph_hash"],
                            semantic_change=True, created_at=_now(),
                            detail={"commit_id": result["commit_id"], "kind": "GRAPH_EDIT",
                                    "operations": [item["op"] for item in record.operations]})
            record.version_id = result["version"]["version_id"]
            record.committed = True
            record.status = "COMMITTED"
            # §7: the outcome follows the commit, not the candidate. Only now is an operation
            # confirmed, and only now is the Antü `COMMITTED` instead of `NOT_EVALUATED`.
            record.outcome = edit_outcome.COMMITTED
            for item in record.outcomes:
                if item.get("outcome") == edit_outcome.NOT_EVALUATED:
                    item["outcome"] = edit_outcome.COMMITTED
            # Only now, with the canonical commit persisted, is an operation confirmed.
            for item in record.operations:
                item["status"] = "COMMITTED"
            for item in record.applied:
                item["status"] = "COMMITTED"
            record.provenance = {**record.provenance,
                                 "canonical_graph_hash": result["version"]["canonical_graph_hash"],
                                 "commit_id": result["commit_id"]}
            return record


    @_write_operation
    def record_failed_antu(self, antu: dict[str, Any], *, reason: str) -> dict[str, Any]:
        """Record a failed execution without creating a version."""
        antu_id = antu.get("antu_id") or "ANTU-UNKNOWN"
        append_event(self._store, "ANTU_REJECTED", {"antu_id": antu_id, "reasons": [reason],
                                                    "recorded_at": _now()})
        revision = next_revision(self._store)
        unit = read_state(self._store) or {}
        return record_revision(self._store, leftraru_id=unit.get("leftraru_id", ""), antu_id=antu_id,
                               revision=revision, status="REJECTED",
                               input_version_id=antu.get("base_version_id"), output_version_id=None,
                               canonical_graph_hash=None, semantic_change=False, created_at=_now(),
                               detail={"reasons": [reason]})

    # -- ingestion ----------------------------------------------------------
    @_write_operation
    def import_canonical(self, document: dict[str, Any], *, antu_id: str = "ANTU-IMPORT") -> CommitResult:
        """Commit an externally produced canonical document (bootstrap or new version)."""
        pointer = current(self._store)
        unit = read_state(self._store) or {}
        revision = next_revision(self._store)
        append_event(self._store, "ANTU_RECEIVED", {"antu_id": antu_id, "leftraru_id": unit.get("leftraru_id"),
                                                    "purpose": "import canonical document", "kind": "IMPORT",
                                                    "base_version_id": (pointer or {}).get("version_id"),
                                                    "recorded_at": _now()})
        result = commit_version(
            self._store, document=document,
            identity={"leftraru_id": unit.get("leftraru_id"), "kuyen_id": document["kuyen"]["kuyen_id"],
                      "kuyen_version": document["kuyen"]["version"]},
            antu_id=antu_id, unit_revision=revision, created_at=_now(),
            projector_version=PROJECTOR_VERSION, openviking_version=None,
            expected_parent_version_id=(pointer or {}).get("version_id"))
        record_revision(self._store, leftraru_id=unit.get("leftraru_id", ""), antu_id=antu_id,
                        revision=revision, status="COMPLETED",
                        input_version_id=(pointer or {}).get("version_id"),
                        output_version_id=result["version"]["version_id"],
                        canonical_graph_hash=result["version"]["canonical_graph_hash"],
                        semantic_change=True, created_at=_now(), detail={"import": True})
        return CommitResult(version=self._version(result["version"]["version_id"]),
                            operation_key=result["operation"]["operation_key"], antu_id=antu_id)

    # -- integrity, recovery, backup ---------------------------------------
    def verify(self) -> dict[str, Any]:
        registry = verify_registry(self._store)
        ledger = verify_chain(self._store)
        unit = verify_unit_history(self._store)
        objects = self._store.verify_objects()
        object_problems = [f"{item['blob']}: {item['problem']}" if isinstance(item, dict) else str(item)
                           for item in objects["problems"]]
        versions = []
        version_problems = []
        for record in list_versions(self._store):
            check = verify_version(self._store, record.version_id)
            versions.append({"version_id": record.version_id, "ok": check["ok"],
                             "problems": check["problems"]})
            version_problems.extend(f"version {record.version_id}: {problem}"
                                    for problem in check["problems"])
        problems = (registry["problems"] + ledger["problems"] + unit["problems"] + object_problems
                    + version_problems)
        return {"ok": not problems, "problems": problems, "versions": versions,
                "current": (current(self._store) or {}).get("version_id"),
                "registry": {"ok": registry["ok"], "versions": registry["versions"],
                             "indexed": registry["indexed"], "current": registry["current"]},
                "ledger": {"state": ledger.get("state"), "events": ledger.get("events"),
                           "tail": ledger.get("tail"), "recovery": ledger.get("recovery")},
                "objects": {"ok": objects["ok"], "blobs": objects.get("blobs"),
                            "ignored_temporaries": objects.get("ignored_temporaries")},
                "unit_history": {"ok": unit.get("ok"), "revisions": unit.get("revisions"),
                                 "unreconciled": unit.get("unreconciled") or []}}

    def recover(self) -> dict[str, Any]:
        """Repair a recoverable ledger tail and resume an interrupted commit.

        Only an incomplete *final* record is repaired, and its original bytes are kept in
        `ledger/quarantine/`. Corruption anywhere else fails closed (StoreError) with nothing
        modified. The operation is idempotent: a second run finds an intact ledger and no
        pending commit, and writes no new artifacts.
        """
        stamp = _now()
        repair = repair_ledger(self._store, created_at=stamp)
        pending = recover_pending(self._store, created_at=stamp)
        released = release_interrupted(self._store, released_at=stamp)
        history = reconcile_unit_history(self._store, created_at=stamp)
        return {**pending, "ledger": repair,
                "projections": {"released": released},
                "unit_history": history}

    def pending(self) -> dict[str, Any]:
        """Interrupted work: incomplete commits and versions without their unit revision."""
        report = pending_commits(self._store)
        report["unreconciled"] = [manifest["version_id"]
                                  for manifest in uncovered_versions(self._store)]
        return report

    def reconcile(self, client: Any | None = None) -> dict[str, Any]:
        return reconcile_store(self._store, client=client)

    def backup(self, target: str | Path) -> dict[str, Any]:
        manifest = create_backup(self._store, target, created_at=_now())
        append_event(self._store, "BACKUP_CREATED", {"backup_id": manifest["backup_id"],
                                                    "versions": manifest["version_count"], "recorded_at": _now()})
        return {"backup_id": manifest["backup_id"], "versions": manifest["version_count"],
                "root_hash": manifest["root_hash"], "files": manifest["file_count"],
                "path": str(target), "integrity_status": manifest["integrity_status"]}

    @staticmethod
    def verify_backup(path: str | Path) -> dict[str, Any]:
        """Fail closed: a backup that does not verify raises instead of reporting ok."""
        from ..errors import BackupError as _BackupError

        report = verify_backup(path)
        if not report["ok"]:
            raise _BackupError(f"backup failed verification: {report['problems'][:3]}")
        return report

    @classmethod
    def restore(cls, backup_path: str | Path, target: str | Path) -> "KuyenMemory":
        restore_backup(backup_path, target, created_at=_now())
        return cls(CanonicalStore(target))

    @staticmethod
    def recover_from_store(path: str | Path, *, workdir: str | Path,
                           contract_snapshot: str | Path | None = None) -> dict[str, Any]:
        """Full independent reconstruction of every version from the store alone.

        Only the canonical store and this package are needed: no OpenViking instance,
        no projection, no fixture. The contract snapshot defaults to the contract of
        the running package.
        """
        from ..contracts import contract_snapshot as _snapshot

        workdir = Path(workdir)
        workdir.mkdir(parents=True, exist_ok=True)
        snapshot = Path(contract_snapshot) if contract_snapshot else workdir / "CONTRACT_SNAPSHOT.json"
        if not snapshot.is_file():
            _snapshot(snapshot)
        return recover_store(path, workdir=workdir, contract_snapshot=snapshot,
                             contract_src=Path(__file__).resolve().parents[1] / "schemas")

    # -- projections --------------------------------------------------------
    def projections(self) -> list[dict[str, Any]]:
        return list_projections(self._store)

    def pending_projections(self) -> list[dict[str, Any]]:
        return list_operations(self._store)

    def project(self, *, client: Any, openviking_version: str,
                instance_tag: str | None = None) -> dict[str, Any]:
        """Execute every pending projection against an external engine."""
        results = []
        skipped = []
        for operation in list_operations(self._store):
            # `run_projection` claims the operation under the writer lock and returns None
            # when it is already done or held by another runner: no operation is executed
            # twice and the completion event is recorded in the same critical section as
            # the registry entry and the DONE status (front 1).
            entry = run_projection(self._store, operation["operation_key"], client=client,
                                   openviking_version=openviking_version, created_at=_now())
            if entry is None:
                skipped.append(operation["operation_key"])
                continue
            results.append(entry["projection_id"])
        return {"projections": results, "skipped": skipped}

    def enqueue_projection(self, version_id: str, *, projector_version: str = PROJECTOR_VERSION,
                           openviking_version: str | None = None,
                           instance_tag: str | None = None) -> dict[str, Any]:
        version = self._version(version_id)
        return enqueue(self._store, version_id=version_id, kuyen_id=version.kuyen_id,
                       kuyen_version=version.kuyen_version,
                       canonical_graph_hash=version.canonical_graph_hash,
                       projector_version=projector_version, openviking_version=openviking_version,
                       created_at=_now(), antu_id="ANTU-PROJECTION", instance_tag=instance_tag)


def list_projections(store: CanonicalStore) -> list[dict[str, Any]]:
    return [read_json(path) for path in sorted(store.projections_dir.glob("*.json"))]
