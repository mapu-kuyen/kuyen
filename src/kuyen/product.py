"""The two ways of evolving a KÜYEN, kept operationally apart (§2, §7, §9).

`DOCUMENT_INGESTION` goes through OpenViking and KÜYEN's canonical admission;
`GRAPH_EDIT` goes through a language model that only proposes and KÜYEN's deterministic
edit path. This module is the single place where the two are classified and dispatched, so
the wrong engine can never be executed for a given Antü:

* `incorporate_document` never calls a graph editor;
* `apply_graph_edit` never touches OpenViking, a MAPU or the document path.

A real document is still the only way to obtain `SOURCE_VERIFIED` knowledge. An edit is
authorised knowledge with its own provenance and is never presented as documental.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .api.memory import AntuEditResult, KuyenMemory
from .editing.editors import GraphEditorPort
from .errors import AdapterError, InvalidRequestError
from .ingest import build_document
from .models import ActorContext, Mapu

ANTU_KIND_DOCUMENT = "DOCUMENT_INGESTION"
ANTU_KIND_GRAPH_EDIT = "GRAPH_EDIT"
ANTU_KINDS = (ANTU_KIND_DOCUMENT, ANTU_KIND_GRAPH_EDIT)


def classify_antu(antu: Mapping[str, Any] | str) -> str:
    """Classify an Antü by what it needs: a document (OpenViking) or a graph edit (LLM).

    An unknown kind is refused instead of being guessed: executing the wrong engine is the
    failure this classification exists to prevent.
    """
    kind = antu if isinstance(antu, str) else str(antu.get("kind") or "")
    kind = kind.strip().upper()
    if kind in ("", "INCORPORATE_MAPU", "DOCUMENT", "DOCUMENT_INGESTION"):
        return ANTU_KIND_DOCUMENT
    if kind in ("GRAPH_EDIT", "EDIT", "ANTU_EDIT"):
        return ANTU_KIND_GRAPH_EDIT
    raise InvalidRequestError(
        f"unknown Antü kind {kind!r}; expected one of {list(ANTU_KINDS)}",
        details={"code": "ANTU_KIND_UNKNOWN", "kind": kind})


@dataclass
class DocumentIncorporation:
    """What a document Antü produced, in terms of the canonical memory."""

    antu_id: str
    status: str
    kuyen_id: str | None = None
    version_id: str | None = None
    parent_version_id: str | None = None
    entity_ids: list[str] = field(default_factory=list)
    relation_ids: list[str] = field(default_factory=list)
    assertion_ids: list[str] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    mapu_ids: list[str] = field(default_factory=list)
    counts: dict[str, Any] = field(default_factory=dict)
    validation: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)
    issues: list[dict[str, Any]] = field(default_factory=list)
    source_units: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {"antu_id": self.antu_id, "status": self.status, "kind": ANTU_KIND_DOCUMENT,
                "kuyen_id": self.kuyen_id, "version_id": self.version_id,
                "parent_version_id": self.parent_version_id,
                "entity_ids": list(self.entity_ids), "relation_ids": list(self.relation_ids),
                "assertion_ids": list(self.assertion_ids),
                "evidence_ids": list(self.evidence_ids), "mapu_ids": list(self.mapu_ids),
                "counts": dict(self.counts), "validation": dict(self.validation),
                "provenance": dict(self.provenance), "issues": list(self.issues),
                "source_units": self.source_units}



def incorporate_document(memory: KuyenMemory, *, engine: Any, antu: Mapping[str, Any],
                         mapus: list[Mapu], actor: ActorContext,
                         adapter: Any = None, instruction: str | None = None) -> DocumentIncorporation:
    """Run one document Antü end to end: OpenViking → KÜYEN validation → new version.

    The engine compiles the MAPU with the real Skill; KÜYEN materializes and validates the
    candidate; only an `ACCEPTED` candidate becomes a canonical version, and it is committed
    through the same `import_canonical` boundary an external producer would use. A rejected
    candidate is recorded in the ledger and never becomes a version.
    """
    if classify_antu(antu) is not ANTU_KIND_DOCUMENT:
        raise InvalidRequestError(
            "this Antü is a graph edit; document ingestion was not executed",
            details={"code": "WRONG_ANTU_PATH", "expected": ANTU_KIND_DOCUMENT})
    if not mapus:
        raise InvalidRequestError("a document Antü requires at least one MAPU",
                                  details={"code": "MAPU_MISSING"})
    antu_id = str(antu.get("antu_id") or "")
    result = engine.build(antu=antu, mapu_sources=mapus, actor=actor,
                          adapter=adapter, instruction=instruction)
    if result.status != "ACCEPTED" or not result.kuyen_id:
        current = memory.current()
        memory.record_failed_antu(
            {"antu_id": antu_id, "base_version_id": current.version_id if current else None},
            reason=f"DOCUMENT_ANTU_{result.status}")
        return DocumentIncorporation(
            antu_id=antu_id, status=result.status,
            validation=result.validation.to_dict(),
            issues=[item.to_dict() for item in result.validation.issues],
            provenance={"kind": "DOCUMENT_ANTU", "rejected_at": "engine"})
    version = engine.get_version(result.kuyen_id, actor=actor)
    graph = version["graph"]
    if not version.get("hashes_verified", False):
        raise AdapterError("the engine's accepted graph does not match its own hashes",
                           details={"code": "ENGINE_GRAPH_TAMPERED",
                                    "kuyen_id": result.kuyen_id})
    provenance_mapus = {item["mapu_id"]: item for item in
                        (graph.get("provenance") or {}).get("mapus") or []}
    document = build_document(
        graph, {item.mapu_id: item.content for item in mapus},
        mapu_versions={key: value.get("version") for key, value in provenance_mapus.items()},
        source_uris={key: value.get("source_uri") for key, value in provenance_mapus.items()})
    parent = memory.current().version_id if memory.current() else None
    commit = memory.import_canonical(document, antu_id=antu_id)
    sidecar = memory.sidecar(commit.version.version_id)
    canonical = sidecar["canonical"]
    return DocumentIncorporation(
        antu_id=antu_id, status="COMMITTED", kuyen_id=commit.version.kuyen_id,
        version_id=commit.version.version_id, parent_version_id=parent,
        entity_ids=sorted(item["entity_id"] for item in canonical["entities"]),
        relation_ids=sorted(item["relation_id"] for item in canonical["relations"]),
        assertion_ids=sorted(item["assertion_id"] for item in canonical["assertions"]),
        evidence_ids=sorted(item["evidence_id"] for item in canonical["evidence"]),
        mapu_ids=sorted(graph.get("mapu_ids") or []),
        counts=dict(commit.version.counts),
        validation=result.validation.to_dict(),
        provenance={"kind": "DOCUMENT_ANTU", "engine": "openviking",
                    "openviking_version": (graph.get("provenance") or {}).get("openviking_version"),
                    "skill_sha256": (graph.get("provenance") or {}).get("skill_sha256"),
                    "materialization": (graph.get("provenance") or {}).get("materialization"),
                    "operation_key": commit.operation_key},
        source_units=len(canonical.get("source_units") or []))


def apply_graph_edit(memory: KuyenMemory, instruction: str, *, editor: GraphEditorPort,
                     antu_id: str | None = None, actor: Mapping[str, Any] | None = None,
                     base_version_id: str | None = None, dry_run: bool = False) -> AntuEditResult:
    """Run one direct edit Antü. OpenViking is never started from this path."""
    if not isinstance(instruction, str) or not instruction.strip():
        raise InvalidRequestError("a graph edit requires a literal instruction",
                                  details={"code": "INSTRUCTION_EMPTY"})
    return memory.apply_antu(instruction, editor=editor, antu_id=antu_id,
                             actor=dict(actor) if actor else None,
                             base_version_id=base_version_id, dry_run=dry_run)
