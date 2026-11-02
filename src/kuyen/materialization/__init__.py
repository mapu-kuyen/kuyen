"""Deterministic materialization of provider proposals into KÜYEN candidates."""
from .contract import CONTRACT_ID, LEGACY_SIDECAR, NATIVE_CONTRACT_ID, RESULT_FILENAME
from .materializer import CandidateMaterializer, MaterializationResult
from .paths import KUYEN_OWNER, PROVIDER_OWNER, PathOwnershipRegistry

__all__ = [
    "CONTRACT_ID", "LEGACY_SIDECAR", "NATIVE_CONTRACT_ID", "RESULT_FILENAME",
    "CandidateMaterializer", "MaterializationResult",
    "KUYEN_OWNER", "PROVIDER_OWNER", "PathOwnershipRegistry",
]
