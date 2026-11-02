"""Evidence integrity and claim-support contracts.

An exact quote proves citation integrity. It does not prove that the quote
semantically entails the claim. Those dimensions stay separate. The deterministic
evaluator deliberately abstains from semantic support; a model evaluator may be
added later as ``MODEL_ASSESSED`` with the same non-absolute contract.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from ..canonical import canonical_digest


class EvidenceIntegrityStatus(str):
    VALID = "VALID"
    HASH_MISMATCH = "HASH_MISMATCH"
    URI_MISMATCH = "URI_MISMATCH"
    OFFSET_INVALID = "OFFSET_INVALID"
    QUOTE_MISMATCH = "QUOTE_MISMATCH"
    SOURCE_MISSING = "SOURCE_MISSING"
    NO_EVIDENCE = "NO_EVIDENCE"


class ClaimSupportStatus(str):
    SUPPORTS = "SUPPORTS"
    PARTIALLY_SUPPORTS = "PARTIALLY_SUPPORTS"
    CONTRADICTS = "CONTRADICTS"
    INSUFFICIENT = "INSUFFICIENT"
    AMBIGUOUS = "AMBIGUOUS"
    NOT_ASSESSED = "NOT_ASSESSED"


@dataclass(frozen=True)
class EvidenceIntegrity:
    evidence_id: str
    status: str
    quote_exact: bool
    offset_valid: bool
    source_hash_valid: bool
    source_uri_valid: bool
    detail: str = ""

    @property
    def valid(self) -> bool:
        return self.status == EvidenceIntegrityStatus.VALID

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "status": self.status,
            "quote_exact": self.quote_exact,
            "offset_valid": self.offset_valid,
            "source_hash_valid": self.source_hash_valid,
            "source_uri_valid": self.source_uri_valid,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class ClaimSupportAssessment:
    claim_id: str
    claim_kind: str
    status: str
    method: str
    rationale: str
    evidence_integrity: tuple[EvidenceIntegrity, ...] = ()
    confidence: float | None = None
    evaluator: str = "kuyen-deterministic-support-v1"
    evaluator_kind: str = "DETERMINISTIC"
    assessed: bool = False

    @property
    def mechanically_supported(self) -> bool:
        return bool(self.evidence_integrity) and all(item.valid for item in self.evidence_integrity)

    @property
    def semantic_entailment_established(self) -> bool:
        return self.status == ClaimSupportStatus.SUPPORTS and self.assessed

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "claim_kind": self.claim_kind,
            "status": self.status,
            "method": self.method,
            "rationale": self.rationale,
            "evidence_integrity": [item.to_dict() for item in self.evidence_integrity],
            "confidence": self.confidence,
            "evaluator": self.evaluator,
            "evaluator_kind": self.evaluator_kind,
            "assessed": self.assessed,
            "mechanically_supported": self.mechanically_supported,
            "semantic_entailment_established": self.semantic_entailment_established,
        }


class ClaimSupportEvaluator(Protocol):
    def assess(
        self,
        *,
        claim_id: str,
        claim_kind: str,
        evidence_ids: list[str],
        claim: Mapping[str, Any] | None = None,
    ) -> ClaimSupportAssessment:
        ...


class DeterministicClaimSupportEvaluator:
    """Checks citation integrity and explicitly abstains from semantics."""

    evaluator_id = "kuyen-deterministic-support-v1"

    def __init__(self, *, sources: Mapping[str, str], evidence: Mapping[str, Mapping[str, Any]]) -> None:
        self.sources = dict(sources)
        self.evidence = {key: dict(value) for key, value in evidence.items()}

    def check(self, evidence_id: str) -> EvidenceIntegrity:
        item = self.evidence.get(evidence_id)
        if item is None:
            return EvidenceIntegrity(evidence_id, EvidenceIntegrityStatus.NO_EVIDENCE, False, False, False, False, "evidence ID not present")
        source = self.sources.get(str(item.get("mapu_id") or ""))
        if source is None:
            return EvidenceIntegrity(evidence_id, EvidenceIntegrityStatus.SOURCE_MISSING, False, False, False, False, "MAPU source unavailable")
        quote = str(item.get("quote") or "")
        start = int(item.get("char_start", -1))
        end = int(item.get("char_end", -1))
        offset_valid = 0 <= start <= end <= len(source)
        quote_exact = offset_valid and source[start:end] == quote
        source_hash_valid = hashlib.sha256(source.encode("utf-8")).hexdigest() == str(item.get("source_sha256") or "")
        source_uri_valid = str(item.get("source_uri") or "").startswith("viking://")
        if not source_hash_valid:
            status = EvidenceIntegrityStatus.HASH_MISMATCH
        elif not source_uri_valid:
            status = EvidenceIntegrityStatus.URI_MISMATCH
        elif not offset_valid:
            status = EvidenceIntegrityStatus.OFFSET_INVALID
        elif not quote_exact:
            status = EvidenceIntegrityStatus.QUOTE_MISMATCH
        else:
            status = EvidenceIntegrityStatus.VALID
        return EvidenceIntegrity(
            evidence_id, status, quote_exact, offset_valid, source_hash_valid, source_uri_valid,
            "" if status == EvidenceIntegrityStatus.VALID else status,
        )

    def assess(
        self,
        *,
        claim_id: str,
        claim_kind: str,
        evidence_ids: list[str],
        claim: Mapping[str, Any] | None = None,
    ) -> ClaimSupportAssessment:
        checks = tuple(self.check(item) for item in evidence_ids)
        if not evidence_ids:
            return ClaimSupportAssessment(
                claim_id, claim_kind, ClaimSupportStatus.INSUFFICIENT,
                "MECHANICAL_EVIDENCE_ONLY", "no evidence reference", checks,
            )
        if not all(item.valid for item in checks):
            return ClaimSupportAssessment(
                claim_id, claim_kind, ClaimSupportStatus.INSUFFICIENT,
                "MECHANICAL_EVIDENCE_ONLY", "at least one citation is invalid", checks,
            )
        # Exact spans are necessary but not sufficient for semantic support.
        return ClaimSupportAssessment(
            claim_id, claim_kind, ClaimSupportStatus.NOT_ASSESSED,
            "MECHANICAL_EVIDENCE_ONLY",
            "citation integrity verified; semantic support not evaluated", checks,
        )


def integrity_report(
    *,
    evidence: list[Mapping[str, Any]],
    sources: Mapping[str, str],
) -> dict[str, Any]:
    evaluator = DeterministicClaimSupportEvaluator(
        sources=sources,
        evidence={str(item["evidence_id"]): item for item in evidence},
    )
    rows = [evaluator.check(str(item["evidence_id"])).to_dict() for item in evidence]
    return {
        "contract": "KUYEN_017_EVIDENCE_INTEGRITY_1.0",
        "evidence_count": len(rows),
        "valid": sum(1 for item in rows if item["status"] == EvidenceIntegrityStatus.VALID),
        "invalid": sum(1 for item in rows if item["status"] != EvidenceIntegrityStatus.VALID),
        "by_status": _counts(rows),
        "rows": rows,
        "digest": canonical_digest(rows),
    }


def _counts(rows: list[Mapping[str, Any]]) -> dict[str, int]:
    result: dict[str, int] = {}
    for row in rows:
        status = str(row["status"])
        result[status] = result.get(status, 0) + 1
    return dict(sorted(result.items()))
