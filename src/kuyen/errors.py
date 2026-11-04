"""Typed errors for the KÜYEN control plane."""

from __future__ import annotations

from typing import Any


class KuyenError(Exception):
    """Base error with a stable machine-readable code."""

    code = "KUYEN_ERROR"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}


class InvalidRequestError(KuyenError):
    code = "INVALID_REQUEST"


class MapuValidationError(KuyenError):
    code = "MAPU_INVALID"


class OntologyError(KuyenError):
    code = "ONTOLOGY_INVALID"


class AdapterError(KuyenError):
    code = "OPENVIKING_ERROR"


class TaskTimeoutError(AdapterError):
    code = "OPENVIKING_TASK_TIMEOUT"


class IngestionTimeoutError(AdapterError):
    code = "OPENVIKING_INGESTION_TIMEOUT"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None):
        super().__init__(message, details=details)
        self.message = message


class CandidateError(KuyenError):
    code = "CANDIDATE_INVALID"


class CandidateMaterializationError(CandidateError):
    code = "CANDIDATE_MATERIALIZATION_FAILED"


class OpenAIProviderError(KuyenError):
    code = "OPENAI_PROVIDER_ERROR"


class OpenAIBudgetExceededError(OpenAIProviderError):
    code = "OPENAI_BUDGET_EXCEEDED"


class OpenAIExtractionError(OpenAIProviderError):
    code = "OPENAI_EXTRACTION_FAILED"


class OpenAIConfigurationError(OpenAIProviderError):
    """The caller asked for OpenAI extraction but the configuration is not usable.

    Raised *before* any extraction is attempted (KUYEN_OPENAI_DOCUMENT_TO_GRAPH_E2E_01).
    The message names the environment variable that needs configuration and never
    contains its value: the credential is read only inside the trusted process.
    """
    code = "OPENAI_CONFIGURATION_BLOCKED"


class ValidationRejected(KuyenError):
    code = "RESULT_REJECTED"

    def __init__(self, message: str, *, report: dict[str, Any] | None = None):
        super().__init__(message, details={"report": report or {}})
        self.report = report or {}


class VersionConflictError(KuyenError):
    code = "VERSION_CONFLICT"


class ExecutionNotFoundError(KuyenError):
    code = "EXECUTION_NOT_FOUND"


class ExecutionNotTerminalError(KuyenError):
    code = "EXECUTION_NOT_TERMINAL"


class InvalidStateTransitionError(KuyenError):
    code = "INVALID_STATE_TRANSITION"


class CredentialUnavailableError(AdapterError):
    code = "CREDENTIAL_UNAVAILABLE"


class UnsupportedCapabilityError(KuyenError):
    code = "UNSUPPORTED_CAPABILITY"


class VersionNotFoundError(KuyenError):
    code = "VERSION_NOT_FOUND"


class PublicationConflictError(KuyenError):
    code = "PUBLICATION_CONFLICT"


class PublicationNotFoundError(KuyenError):
    code = "PUBLICATION_NOT_FOUND"


class PublicationVerificationError(KuyenError):
    code = "PUBLICATION_VERIFICATION_FAILED"


class PublicationAdapterError(AdapterError):
    code = "OPENVIKING_PUBLICATION_ERROR"


class StoreError(KuyenError):
    """The canonical store could not complete an operation."""
    code = "STORE_ERROR"


class ImmutableViolation(StoreError):
    """An immutable artifact was about to be overwritten with different content."""
    code = "IMMUTABLE_VIOLATION"


class AmbiguousSourceUnit(StoreError):
    """A SOURCE_UNIT identifier resolves to more than one unit and nothing disambiguates it.

    `unit_id` is local to its MAPU (see `DATA_MODEL.md`), so a version that holds two
    documents can legitimately contain two `u00` units. Resolving that identifier without a
    MAPU is ambiguous, and returning the first match would attribute evidence to the wrong
    document; the lookup therefore fails instead of guessing
    (KUYEN_SOURCE_UNIT_DISAMBIGUATION_03).
    """
    code = "AMBIGUOUS_SOURCE_UNIT"


class CommitError(KuyenError):
    """A canonical commit was refused or could not be completed."""
    code = "COMMIT_ERROR"


class ConflictError(KuyenError):
    """An operation conflicts with the current canonical state."""
    code = "CONFLICT"


class AntuConflictError(ConflictError):
    """An Antu targets a base version that is no longer current."""
    code = "ANTU_CONFLICT"


class BackupError(KuyenError):
    """A backup or restore failed verification."""
    code = "BACKUP_ERROR"


class ProjectionError(KuyenError):
    """A projection could not be built, registered or verified."""
    code = "PROJECTION_ERROR"


class ContractError(KuyenError):
    """A canonical artifact violated its contract."""
    code = "CONTRACT_ERROR"


class ExportError(ContractError):
    """A canonical export could not be produced."""
    code = "EXPORT_ERROR"


class SidecarError(ContractError):
    """The canonical sidecar is missing, unreadable or failed verification."""
    code = "SIDECAR_ERROR"


class MappingError(ContractError):
    """The correspondence manifest is invalid."""
    code = "MAPPING_ERROR"


class ReconstructionError(ContractError):
    """A canonical memory could not be reconstructed."""
    code = "RECONSTRUCTION_ERROR"


class InjectedFailure(KuyenError):
    """Raised by a fail point; only used against disposable store copies."""
    code = "INJECTED_FAILURE"
