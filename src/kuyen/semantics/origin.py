"""Explicit provenance of a statement: document, Antü instruction, prior version or inference.

KÜYEN_PRODUCTIVE_GRAPH_11, §4. A statement can enter memory through four legitimate
channels and they must never be confused:

* `DOCUMENT_EVIDENCE` — derived from a MAPU through OpenViking; verifiable quote,
  SOURCE_UNIT and Resource reference. It is the only origin that can be reported as
  `SOURCE_VERIFIED`.
* `ANTU_INSTRUCTION` — declared by a user instruction on an existing version. It is
  authorised knowledge, not documentary verification: KÜYEN keeps the literal
  instruction, its identity, the actor, the base version and the reason, and it never
  invents a MAPU, a SOURCE_UNIT, a quote or a hash for it.
* `PRIOR_VERSION` — carried over from an earlier version of the same memory.
* `INFERENCE_PENDING` — proposed but not admitted yet.

The record is stored as an `origin` object inside the canonical statement. Documents
written before this contract have no `origin` field; `normalize` classifies them from the
evidence they carry instead of rewriting them.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

ORIGIN_DOCUMENT = "DOCUMENT_EVIDENCE"
ORIGIN_ANTU = "ANTU_INSTRUCTION"
ORIGIN_PRIOR = "PRIOR_VERSION"
ORIGIN_INFERENCE = "INFERENCE_PENDING"
ORIGIN_UNSPECIFIED = "UNSPECIFIED"

ORIGIN_KINDS = (ORIGIN_DOCUMENT, ORIGIN_ANTU, ORIGIN_PRIOR, ORIGIN_INFERENCE, ORIGIN_UNSPECIFIED)
DOCUMENT_ONLY_ORIGINS = (ORIGIN_DOCUMENT,)

ORIGIN_SCHEMA_NAME = "KUYEN_STATEMENT_ORIGIN"
ORIGIN_SCHEMA_VERSION = "1.0.0"


def document_origin(*, evidence_ids: Sequence[str], mapu_ids: Sequence[str],
                    method: str = "openviking-knowledge-graph-skill") -> dict[str, Any]:
    """Provenance of a statement derived from documents (OpenViking → KÜYEN)."""
    return {
        "schema_name": ORIGIN_SCHEMA_NAME,
        "schema_version": ORIGIN_SCHEMA_VERSION,
        "kind": ORIGIN_DOCUMENT,
        "evidence_ids": [str(item) for item in evidence_ids],
        "mapu_ids": sorted({str(item) for item in mapu_ids if item}),
        "extraction_method": method,
        "antu": None,
    }


def antu_origin(*, antu_id: str, instruction: str, instruction_sha256: str,
                base_version_id: str, reason: str | None = None,
                actor: Mapping[str, Any] | None = None,
                operation_id: str | None = None,
                recorded_at: str | None = None,
                model: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Provenance of a statement that comes from an authorised Antü instruction.

    `actor` is recorded when it is known and stays `None` otherwise: the emitter is never
    invented. Nothing here claims documentary support, which is why this record can never
    be presented as `SOURCE_VERIFIED`.
    """
    return {
        "schema_name": ORIGIN_SCHEMA_NAME,
        "schema_version": ORIGIN_SCHEMA_VERSION,
        "kind": ORIGIN_ANTU,
        "antu_id": str(antu_id),
        "instruction": instruction,
        "instruction_sha256": instruction_sha256,
        "base_version_id": base_version_id,
        "operation_id": operation_id,
        "reason": reason,
        "actor": dict(actor) if actor else None,
        "recorded_at": recorded_at,
        "model": dict(model) if model else None,
        "evidence_ids": [],
        "mapu_ids": [],
        "documentary_verification": False,
    }



def prior_origin(*, version_id: str, object_id: str) -> dict[str, Any]:
    """Provenance of knowledge carried over unchanged from an earlier version."""
    return {
        "schema_name": ORIGIN_SCHEMA_NAME, "schema_version": ORIGIN_SCHEMA_VERSION,
        "kind": ORIGIN_PRIOR, "from_version_id": version_id, "from_object_id": object_id,
        "evidence_ids": [], "mapu_ids": [], "documentary_verification": False,
    }


def inference_origin(*, proposal_id: str, model: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Provenance of a proposal that has not been admitted to memory yet."""
    return {
        "schema_name": ORIGIN_SCHEMA_NAME, "schema_version": ORIGIN_SCHEMA_VERSION,
        "kind": ORIGIN_INFERENCE, "proposal_id": proposal_id,
        "model": dict(model) if model else None,
        "evidence_ids": [], "mapu_ids": [], "documentary_verification": False,
    }


def normalize(record: Mapping[str, Any] | None, *,
              evidence_ids: Sequence[str] = ()) -> dict[str, Any]:
    """Return the origin of a canonical object, deriving it for legacy documents.

    A statement without `origin` is classified from what it carries: documentary evidence
    means `DOCUMENT_EVIDENCE`; otherwise `UNSPECIFIED`. The derivation is explicit in the
    returned record (`derived: True`) so a reader can tell it apart from a declaration.
    """
    if isinstance(record, Mapping) and record.get("kind"):
        return dict(record)
    if evidence_ids:
        return {**document_origin(evidence_ids=evidence_ids, mapu_ids=()),
                "derived": True,
                "derived_reason": "no origin was declared; the object carries documentary evidence"}
    return {
        "schema_name": ORIGIN_SCHEMA_NAME, "schema_version": ORIGIN_SCHEMA_VERSION,
        "kind": ORIGIN_UNSPECIFIED, "evidence_ids": [], "mapu_ids": [],
        "documentary_verification": False, "derived": True,
        "derived_reason": "no origin was declared and the object carries no evidence",
    }


def is_documentary(record: Mapping[str, Any] | None) -> bool:
    """True only for origin records that can support `SOURCE_VERIFIED`."""
    return bool(record) and record.get("kind") in DOCUMENT_ONLY_ORIGINS


def problems(record: Mapping[str, Any] | None, *,
             status: str | None = None, evidence_status: str | None = None,
             label: str = "object", identifier: Any = None) -> list[str]:
    """Structural problems of one origin record, including its epistemic constraints.

    The invariant that matters (brief §4) is: an Antü-instruction statement must never be
    reported as documentary verification.
    """
    found: list[str] = []
    if record is None:
        return found
    if not isinstance(record, Mapping):
        return [f"ORIGIN_INVALID: {label} {identifier} carries a non-object origin"]
    kind = record.get("kind")
    if kind not in ORIGIN_KINDS:
        return [f"ORIGIN_KIND_INVALID: {label} {identifier} declares origin {kind!r}"]
    if kind == ORIGIN_ANTU:
        if not record.get("antu_id"):
            found.append(f"ORIGIN_ANTU_ID_MISSING: {label} {identifier} has no antu_id")
        if not record.get("instruction_sha256"):
            found.append(
                f"ORIGIN_ANTU_INSTRUCTION_MISSING: {label} {identifier} does not record the "
                "instruction it comes from")
        for key, value in (("status", status), ("evidence_status", evidence_status)):
            if str(value or "").upper() == "SOURCE_VERIFIED":
                found.append(
                    f"ORIGIN_ANTU_CANNOT_BE_SOURCE_VERIFIED: {label} {identifier} is an "
                    f"instruction and cannot declare {key}=SOURCE_VERIFIED")
    if kind == ORIGIN_DOCUMENT and not record.get("evidence_ids"):
        found.append(
            f"ORIGIN_DOCUMENT_WITHOUT_EVIDENCE: {label} {identifier} claims documentary "
            "origin without evidence")
    return found


def public_view(record: Mapping[str, Any] | None) -> dict[str, Any]:
    """Readable summary used by API results and reports (no secret, no prompt text)."""
    value = normalize(record)
    kind = value.get("kind")
    view: dict[str, Any] = {"kind": kind,
                            "documentary_verification": bool(value.get("documentary_verification"))}
    if kind == ORIGIN_ANTU:
        actor = value.get("actor")
        model = value.get("model")
        view.update({"antu_id": value.get("antu_id"),
                     "instruction_sha256": value.get("instruction_sha256"),
                     "base_version_id": value.get("base_version_id"),
                     "actor": (actor or {}).get("authenticated_user") if isinstance(actor, Mapping) else None,
                     "model": (model or {}).get("model") if isinstance(model, Mapping) else None})
    elif kind == ORIGIN_DOCUMENT:
        view.update({"evidence_ids": list(value.get("evidence_ids") or []),
                     "mapu_ids": list(value.get("mapu_ids") or [])})
    elif kind == ORIGIN_PRIOR:
        view.update({"from_version_id": value.get("from_version_id")})
    if value.get("derived"):
        view["derived"] = True
        view["derived_reason"] = value.get("derived_reason")
    return view
