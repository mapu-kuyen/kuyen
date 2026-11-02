"""KÜYEN consolidated development baseline."""
from ._version import resolve_version
from .engine import KuyenEngine
from .execution import ExecutionHandle, ExecutionState
from .publication import PublicationHandle, PublicationStatus
from .config import KuyenConfig, load_config
from .models import (
    ActorContext,
    Antu,
    CandidateBundle,
    CandidateEvidence,
    CandidateEntity,
    CandidateRelation,
    CoverageState,
    CoverageUnit,
    Mapu,
    ValidationReport,
)

from .api import AntuExecution, CommitResult, KuyenMemory, MemoryVersion
from .contracts import SIDECAR_SCHEMA_VERSION, STORE_FORMAT_VERSION, VersionDomains
from .ingest import build_document

__version__ = resolve_version()
__all__ = [
    "KuyenMemory", "AntuExecution", "CommitResult", "MemoryVersion", "build_document",
    "VersionDomains", "STORE_FORMAT_VERSION", "SIDECAR_SCHEMA_VERSION",
    "KuyenEngine", "KuyenConfig", "load_config", "ExecutionHandle", "ExecutionState",
    "PublicationHandle", "PublicationStatus",
    "ActorContext", "Antu",
    "CandidateBundle", "CandidateEvidence", "CandidateEntity", "CandidateRelation",
    "CoverageState", "CoverageUnit", "Mapu", "ValidationReport",
]
