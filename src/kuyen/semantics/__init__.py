"""Deterministic semantic-integrity primitives for KÜYEN 0.1.7."""
from .identity import (
    IdentityCandidate,
    IdentityDecision,
    IdentityGroup,
    IdentityResolutionPolicy,
    IdentityStatus,
    ResolutionStatus,
    build_identity_groups,
    classify_identity,
)
from .predicates import (
    PredicateMapping,
    PredicateMappingRegistry,
    PredicateMappingStatus,
    ProviderProjectionStatus,
    annotate_predicate_provenance,
    preserve_incompatible_relations,
)
from .support import (
    ClaimSupportAssessment,
    ClaimSupportEvaluator,
    ClaimSupportStatus,
    DeterministicClaimSupportEvaluator,
    EvidenceIntegrity,
    EvidenceIntegrityStatus,
    integrity_report,
)

__all__ = [
    "IdentityCandidate", "IdentityDecision", "IdentityGroup", "IdentityResolutionPolicy",
    "IdentityStatus", "ResolutionStatus", "build_identity_groups", "classify_identity",
    "PredicateMapping", "PredicateMappingRegistry", "PredicateMappingStatus",
    "ProviderProjectionStatus", "annotate_predicate_provenance",
    "preserve_incompatible_relations",
    "ClaimSupportAssessment", "ClaimSupportEvaluator", "ClaimSupportStatus",
    "DeterministicClaimSupportEvaluator", "EvidenceIntegrity", "EvidenceIntegrityStatus",
    "integrity_report",
]
