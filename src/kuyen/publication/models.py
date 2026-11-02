"""Publication-domain models; no provider calls happen here."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class PublicationStatus(str, Enum):
    NOT_PUBLISHED = "NOT_PUBLISHED"
    PUBLISHING = "PUBLISHING"
    VERIFYING = "VERIFYING"
    PUBLISHED = "PUBLISHED"
    VERIFIED = "VERIFIED"
    PUBLICATION_PARTIAL = "PUBLICATION_PARTIAL"
    PUBLICATION_FAILED = "PUBLICATION_FAILED"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"


TERMINAL_PUBLICATION_STATUSES = {
    PublicationStatus.PUBLISHED, PublicationStatus.VERIFIED,
    PublicationStatus.PUBLICATION_PARTIAL, PublicationStatus.PUBLICATION_FAILED,
    PublicationStatus.VERIFICATION_FAILED,
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class PublicationArtifact:
    path: str
    uri: str
    content: bytes
    sha256: str
    content_type: str = "text/plain"

    @property
    def size(self) -> int:
        return len(self.content)

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path, "uri": self.uri, "sha256": self.sha256,
            "size": self.size, "content_type": self.content_type,
        }


@dataclass
class PublicationPlan:
    publication_id: str
    kuyen_id: str
    version: str
    content_digest: str
    publication_digest: str
    target_uri: str
    artifacts: list[PublicationArtifact]
    manifest_artifact: PublicationArtifact
    local_version_dir: str
    access_profile: str = "restricted"
    source_policy: str = "references_only"
    metadata: dict[str, Any] = field(default_factory=dict)

    def artifact_map(self) -> dict[str, PublicationArtifact]:
        return {item.path: item for item in self.artifacts}


@dataclass
class PublicationHandle:
    publication_id: str
    kuyen_id: str
    content_digest: str
    publication_digest: str
    status: PublicationStatus
    target_uri: str
    updated_at: str
    error: dict[str, Any] | None = None
    build_status: str = "ACCEPTED"

    @property
    def publication_status(self) -> PublicationStatus:
        return self.status

    def to_dict(self) -> dict[str, Any]:
        return {
            "publication_id": self.publication_id, "kuyen_id": self.kuyen_id,
            "build_status": self.build_status,
            "content_digest": self.content_digest,
            "publication_digest": self.publication_digest,
            "publication_status": self.status.value, "target_uri": self.target_uri,
            "updated_at": self.updated_at, "error": self.error,
        }


@dataclass
class PublicationRecord:
    publication_id: str
    kuyen_id: str
    version: str
    content_digest: str
    publication_digest: str
    target_uri: str
    actor: dict[str, Any]
    source_policy: str = "references_only"
    build_status: str = "ACCEPTED"
    status: PublicationStatus = PublicationStatus.NOT_PUBLISHED
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    expected_files: list[dict[str, Any]] = field(default_factory=list)
    written_files: list[dict[str, Any]] = field(default_factory=list)
    verified_files: list[dict[str, Any]] = field(default_factory=list)
    acl: dict[str, Any] | None = None
    verification: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    transitions: list[dict[str, Any]] = field(default_factory=list)

    @property
    def handle(self) -> PublicationHandle:
        return PublicationHandle(
            publication_id=self.publication_id, kuyen_id=self.kuyen_id,
            content_digest=self.content_digest, publication_digest=self.publication_digest,
            status=self.status, target_uri=self.target_uri,
            updated_at=self.updated_at, error=self.error,
            build_status=self.build_status,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "publication_id": self.publication_id, "kuyen_id": self.kuyen_id,
            "version": self.version, "source_policy": self.source_policy,
            "content_digest": self.content_digest,
            "build_status": self.build_status,
            "publication_digest": self.publication_digest, "target_uri": self.target_uri,
            "actor": self.actor, "publication_status": self.status.value,
            "created_at": self.created_at, "updated_at": self.updated_at,
            "expected_files": self.expected_files, "written_files": self.written_files,
            "verified_files": self.verified_files, "acl": self.acl,
            "verification": self.verification, "error": self.error,
            "transitions": self.transitions,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "PublicationRecord":
        return cls(
            publication_id=value["publication_id"], kuyen_id=value["kuyen_id"],
            version=value.get("version", ""), source_policy=value.get("source_policy", "references_only"),
            content_digest=value.get("content_digest", ""), build_status=value.get("build_status", "ACCEPTED"),
            publication_digest=value.get("publication_digest", ""),
            target_uri=value.get("target_uri", ""), actor=dict(value.get("actor") or {}),
            status=PublicationStatus(value.get("publication_status", "NOT_PUBLISHED")),
            created_at=value.get("created_at") or utc_now(),
            updated_at=value.get("updated_at") or utc_now(),
            expected_files=list(value.get("expected_files") or []),
            written_files=list(value.get("written_files") or []),
            verified_files=list(value.get("verified_files") or []),
            acl=value.get("acl"), verification=value.get("verification"),
            error=value.get("error"), transitions=list(value.get("transitions") or []),
        )


@dataclass
class PublicationVerification:
    publication_id: str
    publication_digest: str
    status: PublicationStatus
    files: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    independent: bool = False
    manifest: dict[str, Any] | None = None
    read_at: str = field(default_factory=utc_now)

    @property
    def ok(self) -> bool:
        return self.status is PublicationStatus.VERIFIED

    def to_dict(self) -> dict[str, Any]:
        return {
            "publication_id": self.publication_id,
            "publication_digest": self.publication_digest,
            "publication_status": self.status.value,
            "files": self.files, "errors": self.errors,
            "independent": self.independent, "manifest": self.manifest,
            "read_at": self.read_at,
        }
