"""The Antü graph-edit flow: instruction in, validated candidate version out (§2, §6.3).

The flow is deliberately explicit and has no hidden steps:

    instruction + base version
        → deterministic context        (editing.context)
        → request to the editor port   (editing.prompt, editing.editors)
        → parsed proposal              (editing.operations)
        → deterministic validation     (editing.validator)
        → deterministic application    (editing.applier)
        → candidate document           (sealed by the caller with lifecycle.antu.seal_document)

This module never reads or writes the store: the caller (KuyenMemory) owns the lock, the
base version check and the commit.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Mapping

from ..canonical import sha256_text
from ..semantics.origin import antu_origin
from .applier import GraphEditApplier
from .context import EditContext, build_context
from .diff import diff_documents
from .editors import GraphEditorPort
from .operations import (CLARIFICATION_REQUIRED, CONFLICT, NO_CHANGES,
                        GraphEditProposal, parse_proposal)
from .prompt import GraphEditRequest, build_request
from .validator import EditValidator, ValidationOutcome

STATUS_VALIDATED = "VALIDATED"
STATUS_NO_CHANGES = "NO_CHANGES"
STATUS_CLARIFICATION = "CLARIFICATION_REQUIRED"
STATUS_CONFLICT = "CONFLICT"
STATUS_REJECTED = "REJECTED"
STATUS_INTERPRETATION_FAILED = "INTERPRETATION_FAILED"


def derive_antu_id(instruction: str) -> str:
    """Stable Antü identity derived from the instruction text (idempotency key)."""
    return "ANTU-" + hashlib.sha256(instruction.strip().encode("utf-8")).hexdigest()[:16]


@dataclass
class EditRun:
    antu_id: str
    status: str
    instruction: str
    instruction_sha256: str
    base_version_id: str
    context: EditContext
    request: GraphEditRequest
    proposal: GraphEditProposal | None = None
    validation: ValidationOutcome | None = None
    candidate_document: dict[str, Any] | None = None
    application: dict[str, Any] | None = None
    diff: dict[str, Any] | None = None
    model: dict[str, Any] = field(default_factory=dict)
    clarification: dict[str, Any] | None = None
    conflict: dict[str, Any] | None = None
    reasons: list[str] = field(default_factory=list)

    @property
    def committable(self) -> bool:
        return self.status == STATUS_VALIDATED and self.candidate_document is not None

    def to_dict(self) -> dict[str, Any]:
        return {"antu_id": self.antu_id, "status": self.status,
                "instruction": self.instruction, "instruction_sha256": self.instruction_sha256,
                "base_version_id": self.base_version_id,
                "context": dict(self.context.selection),
                "request": {"prompt_sha256": self.request.prompt_sha256,
                            "context_sha256": self.request.context_sha256},
                "proposal": self.proposal.to_dict() if self.proposal else None,
                "validation": self.validation.to_dict() if self.validation else None,
                "application": dict(self.application or {}),
                "diff": self.diff, "model": dict(self.model),
                "clarification": self.clarification, "conflict": self.conflict,
                "reasons": list(self.reasons)}


def run_edit(*, instruction: str, antu_id: str, base_document: Mapping[str, Any],
             graph: Mapping[str, Any], editor: GraphEditorPort,
             actor: Mapping[str, Any] | None, recorded_at: str | None = None,
             object_limit: int | None = None) -> EditRun:
    """Interpret one instruction against one version and return the validated candidate."""
    text = " ".join(str(instruction or "").split())
    if not text:
        raise ValueError("an Antü edit requires a non-empty instruction")
    version_id = str(graph.get("version_id") or base_document.get("version_id") or "")
    context_kwargs = {} if object_limit is None else {"object_limit": object_limit}
    context = build_context(graph, text, version_id=version_id, **context_kwargs)
    request = build_request(antu_id, text, context)
    instruction_sha = sha256_text(text)
    run = EditRun(antu_id=antu_id, status=STATUS_INTERPRETATION_FAILED, instruction=text,
                  instruction_sha256=instruction_sha, base_version_id=version_id,
                  context=context, request=request,
                  model=dict(editor.metadata()) if hasattr(editor, "metadata") else {})
    raw = editor.interpret(request)
    usage = getattr(editor, "last_usage", None)
    if usage is not None and hasattr(usage, "to_dict"):
        run.model = {**run.model, "usage": usage.to_dict()}
    run.model["proposal_sha256"] = sha256_text(raw[: 1 << 20])
    try:
        proposal = parse_proposal(raw)
    except Exception as exc:  # noqa: BLE001 - a contract defect is a rejection, not a crash
        run.reasons.append(str(exc))
        run.status = STATUS_INTERPRETATION_FAILED
        return run
    run.proposal = proposal
    if proposal.base_version_id and proposal.base_version_id != version_id:
        run.status = STATUS_CONFLICT
        run.conflict = {"code": "STALE_BASE", "proposed": proposal.base_version_id,
                        "current": version_id}
        run.reasons.append("STALE_BASE: the editor answered for another version")
        return run
    if proposal.status == CLARIFICATION_REQUIRED:
        run.status = STATUS_CLARIFICATION
        run.clarification = dict(proposal.clarification or {})
        run.reasons.append("the instruction is ambiguous")
        return run
    if proposal.status == CONFLICT:
        run.status = STATUS_CONFLICT
        run.conflict = dict(proposal.conflict or {"reason": proposal.interpretation})
        run.reasons.append("the instruction conflicts with the current knowledge")
        return run
    if proposal.status == NO_CHANGES or not proposal.operations:
        run.status = STATUS_NO_CHANGES
        run.reasons.append("the interpretation produced no operation")
        return run
    validation = EditValidator(context, instruction=text, antu_id=antu_id,
                               version_ids={
                                   "entity": [str(item.get("entity_id"))
                                              for item in (graph.get("entities") or [])],
                                   "relation": [str(item.get("relation_id"))
                                                for item in (graph.get("relations") or [])],
                                   "assertion": [str(item.get("assertion_id"))
                                                 for item in (graph.get("assertions") or [])],
                               }).validate(proposal)
    run.validation = validation
    if not validation.ok:
        run.status = STATUS_REJECTED
        run.reasons.extend(f"{item.code}: {item.message}" for item in validation.rejected)
        run.reasons.extend(validation.problems)
        return run
    applier = GraphEditApplier(
        antu_id=antu_id, instruction=text, instruction_sha256=instruction_sha,
        base_version_id=version_id, actor=actor, model=run.model, recorded_at=recorded_at)
    application = applier.apply(base_document, validation.accepted)
    run.application = application.to_dict()
    run.candidate_document = application.document
    run.diff = diff_documents(base_document, application.document)
    run.status = STATUS_VALIDATED
    return run


def edit_provenance_record(run: EditRun) -> dict[str, Any]:
    """The compact record an edited version keeps in its graph provenance."""
    return {
        "antu_id": run.antu_id,
        "kind": "GRAPH_EDIT",
        "instruction": run.instruction,
        "instruction_sha256": run.instruction_sha256,
        "base_version_id": run.base_version_id,
        "operations": [item.to_dict() for item in (run.validation.accepted if run.validation else [])],
        "rejected": [item.to_dict() for item in (run.validation.rejected if run.validation else [])],
        "model": dict(run.model),
        "context": dict(run.context.selection),
        "status": run.status,
        "origin": antu_origin(
            antu_id=run.antu_id, instruction=run.instruction,
            instruction_sha256=run.instruction_sha256, base_version_id=run.base_version_id),
    }
