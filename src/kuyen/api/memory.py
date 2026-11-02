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
from ..errors import (AntuConflictError, CommitError, ConflictError, StoreError, ValidationRejected)
from ..lifecycle.antu import _merge, _bump_version, _verify_proposal
from ..lifecycle.ledger import append_event, events, verify_chain
from ..lifecycle.unit import (ensure_unit, next_revision, read_state, record_revision, revisions,
                              verify_unit_history)
from ..models import KuyenGraph
from ..storage.commit import commit_version, pending_commits, recover_pending, verify_commit
from ..storage.registry import current, lineage, verify_registry
from ..storage.store import CanonicalStore
from ..storage.versions import list_versions, read_version, verify_version
from ..projection.native import document_from_sidecar, load_sidecar, project as run_projection
from ..projection.outbox import enqueue, list_operations, stats as outbox_stats
from ..projection.reconciliation import reconcile as reconcile_store
from ..sidecar import verify_sidecar
from ..backup.archive import create_backup, restore_backup, verify_backup
from ..recovery.rebuild import recover_store


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
        if digest(graph) != self._version(target).canonical_graph_hash:
            raise StoreError(f"version {target} does not match its canonical hash")
        return graph

    def sidecar(self, version_id: str | None = None) -> dict[str, Any]:
        target = version_id or (current(self._store) or {}).get("version_id")
        if not target:
            raise StoreError("this memory has no committed version yet")
        return load_sidecar(self._store, target)

    def source_unit(self, unit_id: str, version_id: str | None = None) -> dict[str, Any]:
        for unit in self.sidecar(version_id)["canonical"]["source_units"]:
            if unit["unit_id"] == unit_id:
                return unit
        raise StoreError(f"unknown SOURCE_UNIT {unit_id}")

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
        """claim -> evidence -> SOURCE_UNIT -> MAPU, by identifiers only."""
        sidecar = self.sidecar(version_id)
        evidence = self.evidence_of(claim_id, version_id)
        units = sidecar["canonical"]["source_units"]
        mapus = sidecar["mapus"]
        chain = []
        for item in evidence:
            unit = next((u for u in units if u["mapu_id"] == item["mapu_id"]
                         and (u.get("char_start") or 0) <= item["char_start"] < (u.get("char_end") or 0)), None)
            mapu = next((m for m in mapus if m["mapu_id"] == item["mapu_id"]), None)
            chain.append({"evidence_id": item["evidence_id"], "quote": item["quote"],
                          "char_start": item["char_start"], "char_end": item["char_end"],
                          "source_unit_id": (unit or {}).get("unit_id"),
                          "source_unit_section": (unit or {}).get("section"),
                          "mapu_id": item["mapu_id"],
                          "mapu_content_sha256": (mapu or {}).get("content_sha256")})
        return {"claim_id": claim_id, "evidence": chain}

    # -- Antu lifecycle -----------------------------------------------------
    def execute_antu(self, antu: dict[str, Any], *, mapu_source: str | Path | None = None) -> AntuExecution:
        """Validate an Antu and prepare the candidate; nothing is committed yet."""
        antu_id = antu.get("antu_id")
        if not antu_id:
            raise ValidationRejected("an Antu requires an antu_id")
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
        declaration = instruction.get("mapu") or {}
        if mapu_source is None:
            problems = _verify_proposal(instruction, None)
            mapu_text = ""
        else:
            mapu_text = Path(mapu_source).read_text(encoding="utf-8")
            if declaration.get("sha256") and declaration["sha256"] != sha256_text(mapu_text):
                problems = ["declared MAPU hash does not match the provided source"]
            else:
                problems = _verify_proposal(instruction, mapu_text)
        if problems:
            append_event(self._store, "ANTU_REJECTED", {"antu_id": antu_id, "reasons": problems,
                                                        "recorded_at": _now()})
            return AntuExecution(antu_id=antu_id, status="REJECTED", detail={"reasons": problems},
                                 base_version_id=base_version_id)
        mapu = {"mapu_id": declaration["mapu_id"], "version": declaration.get("version"),
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
                "units": [instruction["unit"]["unit_id"]], "metadata_source": declaration.get("metadata_source")}
        candidate = _merge(base_document, instruction, mapu, _now())
        candidate.pop("_canonical_graph", None)
        return AntuExecution(antu_id=antu_id, status="VALIDATED",
                             detail={"objects_declared": {key: len((antu.get("proposal") or {}).get(key) or [])
                                                          for key in ("entities", "relations", "assertions", "evidence")}},
                             base_version_id=base_version_id, candidate_document=candidate)

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
        versions = [{"version_id": record.version_id, "ok": verify_version(self._store, record.version_id)["ok"]}
                    for record in list_versions(self._store)]
        problems = (registry["problems"] + ledger["problems"] + unit["problems"] + object_problems
                    + [f"version {item['version_id']} failed verification" for item in versions if not item["ok"]])
        return {"ok": not problems, "problems": problems, "versions": versions,
                "current": (current(self._store) or {}).get("version_id")}

    def recover(self) -> dict[str, Any]:
        """Resume an interrupted commit, if any, without touching accepted versions."""
        return recover_pending(self._store, created_at=_now())

    def pending(self) -> dict[str, Any]:
        return pending_commits(self._store)

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
        for operation in list_operations(self._store):
            if operation["status"] == "DONE":
                continue
            entry = run_projection(self._store, operation["operation_key"], client=client,
                                   openviking_version=openviking_version, created_at=_now())
            append_event(self._store, "PROJECTION_COMPLETED", {"version_id": entry["version_id"],
                                                                "projection_id": entry["projection_id"],
                                                                "recorded_at": _now()})
            results.append(entry["projection_id"])
        return {"projections": results}

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
