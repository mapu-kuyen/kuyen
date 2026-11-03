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
from . import origin
from .origin import (
    ORIGIN_ANTU,
    ORIGIN_DOCUMENT,
    ORIGIN_INFERENCE,
    ORIGIN_KINDS,
    ORIGIN_PRIOR,
    ORIGIN_UNSPECIFIED,
    antu_origin,
    document_origin,
    inference_origin,
    is_documentary,
    prior_origin,
    public_view as origin_view,
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
    "origin", "ORIGIN_ANTU", "ORIGIN_DOCUMENT", "ORIGIN_INFERENCE", "ORIGIN_KINDS",
    "ORIGIN_PRIOR", "ORIGIN_UNSPECIFIED", "antu_origin", "document_origin",
    "inference_origin", "is_documentary", "prior_origin", "origin_view",
    "IdentityCandidate", "IdentityDecision", "IdentityGroup", "IdentityResolutionPolicy",
    "IdentityStatus", "ResolutionStatus", "build_identity_groups", "classify_identity",
    "PredicateMapping", "PredicateMappingRegistry", "PredicateMappingStatus",
    "ProviderProjectionStatus", "annotate_predicate_provenance",
    "preserve_incompatible_relations",
    "ClaimSupportAssessment", "ClaimSupportEvaluator", "ClaimSupportStatus",
    "DeterministicClaimSupportEvaluator", "EvidenceIntegrity", "EvidenceIntegrityStatus",
    "integrity_report",
]
