"""Explicit ownership of provider and KÜYEN artifact paths.

The provider agent chooses its output paths; KÜYEN only reads them. KÜYEN writes
its canonical candidate under its own data directory. A path can have exactly one
owner, and provider paths must stay inside the provider output root.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath

from ..errors import CandidateMaterializationError

PROVIDER_OWNER = "OPENVIKING_AGENT"
KUYEN_OWNER = "KUYEN_MATERIALIZER"


def normalize_provider_path(path: str) -> str:
    """Validate and normalize a provider-relative path."""
    if not isinstance(path, str) or not path.strip():
        raise CandidateMaterializationError("provider artifact path is empty")
    if "\\" in path:
        raise CandidateMaterializationError(f"provider artifact path uses backslashes: {path}")
    if path.startswith("/") or path.startswith("viking://") or "://" in path:
        raise CandidateMaterializationError(f"provider artifact path is absolute or a URI: {path}")
    pure = PurePosixPath(path)
    if pure.is_absolute() or ".." in pure.parts:
        raise CandidateMaterializationError(f"provider artifact path escapes the output root: {path}")
    if any(part in {"", "."} for part in pure.parts):
        raise CandidateMaterializationError(f"provider artifact path is not canonical: {path}")
    return pure.as_posix()


def relative_provider_path(output_uri: str, artifact_uri: str) -> str:
    """Map a concrete artifact URI to a path relative to the output root."""
    root = output_uri.rstrip("/")
    artifact = artifact_uri.rstrip("/")
    if artifact == root:
        raise CandidateMaterializationError(f"artifact URI equals the output root: {artifact_uri}")
    if not artifact.startswith(root + "/"):
        raise CandidateMaterializationError(
            f"artifact URI is outside the output root: {artifact_uri} (root {output_uri})"
        )
    return normalize_provider_path(artifact[len(root) + 1:])


@dataclass(frozen=True)
class PathClaim:
    path: str
    owner: str
    purpose: str

    def to_dict(self) -> dict[str, str]:
        return {"path": self.path, "owner": self.owner, "purpose": self.purpose}


class PathOwnershipRegistry:
    """One writer per path. Claims by different owners are a hard conflict."""

    def __init__(self) -> None:
        self._claims: dict[str, PathClaim] = {}

    def claim(self, path: str, *, owner: str, purpose: str) -> PathClaim:
        normalized = normalize_provider_path(path)
        existing = self._claims.get(normalized)
        if existing is not None and existing.owner != owner:
            raise CandidateMaterializationError(
                f"path {normalized} is claimed by {existing.owner} and {owner}",
                details={"path": normalized, "owners": [existing.owner, owner]},
            )
        claim = PathClaim(path=normalized, owner=owner, purpose=purpose)
        self._claims[normalized] = claim
        return claim

    def assert_unique(self, paths: list[str]) -> list[str]:
        seen: dict[str, int] = {}
        for path in paths:
            normalized = normalize_provider_path(path)
            seen[normalized] = seen.get(normalized, 0) + 1
        duplicates = {path: count for path, count in seen.items() if count > 1}
        if duplicates:
            raise CandidateMaterializationError(
                "provider output contains duplicate paths",
                details={"duplicates": duplicates},
            )
        return sorted(seen)

    def claims(self) -> list[PathClaim]:
        return [self._claims[key] for key in sorted(self._claims)]

    def to_dict(self) -> dict[str, list[dict[str, str]]]:
        grouped: dict[str, list[dict[str, str]]] = {}
        for claim in self.claims():
            grouped.setdefault(claim.owner, []).append(claim.to_dict())
        return grouped
