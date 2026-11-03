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

from .api import AntuEditResult, AntuExecution, CommitResult, KuyenMemory, MemoryVersion
from .contracts import SIDECAR_SCHEMA_VERSION, STORE_FORMAT_VERSION, VersionDomains
from .editing import (EditorConfig, GraphEditorPort, OpenAICompatibleGraphEditor,
                      RecordedGraphEditor)
from .ingest import build_document
from .product import (ANTU_KIND_DOCUMENT, ANTU_KIND_GRAPH_EDIT, ANTU_KINDS,
                      DocumentIncorporation, apply_graph_edit, classify_antu,
                      incorporate_document)
from .vlm import OpenVikingVlmRuntime, VlmConfigurationError, VlmProviderConfig

__version__ = resolve_version()
__all__ = [
    "KuyenMemory", "AntuExecution", "CommitResult", "MemoryVersion", "build_document",
    "AntuEditResult", "classify_antu", "incorporate_document", "apply_graph_edit",
    "DocumentIncorporation", "ANTU_KIND_DOCUMENT", "ANTU_KIND_GRAPH_EDIT", "ANTU_KINDS",
    "GraphEditorPort", "EditorConfig", "OpenAICompatibleGraphEditor", "RecordedGraphEditor",
    "VersionDomains", "STORE_FORMAT_VERSION", "SIDECAR_SCHEMA_VERSION",
    "KuyenEngine", "KuyenConfig", "load_config", "ExecutionHandle", "ExecutionState",
    "PublicationHandle", "PublicationStatus",
    "ActorContext", "Antu",
    "CandidateBundle", "CandidateEvidence", "CandidateEntity", "CandidateRelation",
    "CoverageState", "CoverageUnit", "Mapu", "ValidationReport",
    # VLM provider configuration for the KÜYEN-managed OpenViking instance
    "VlmProviderConfig", "OpenVikingVlmRuntime", "VlmConfigurationError",
]

