"""Independent read-back and byte-level verification of a publication."""
from __future__ import annotations

import hashlib
import json
from typing import Any

from ..ports.publication import OpenVikingPublicationPort
from .models import PublicationPlan, PublicationStatus, PublicationVerification


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


async def _read_text(port: OpenVikingPublicationPort, uri: str) -> str:
    value = await port.read(uri)
    if not isinstance(value, str):
        raise TypeError(f"publication artifact is not text: {uri}")
    return value


class PublicationVerifier:
    async def verify_plan(
        self,
        plan: PublicationPlan,
        port: OpenVikingPublicationPort,
        *,
        independent: bool = False,
        require_marker: bool = True,
    ) -> PublicationVerification:
        errors: list[str] = []
        files: list[dict[str, Any]] = []
        manifest: dict[str, Any] = {}
        if require_marker:
            try:
                raw_manifest = await _read_text(port, plan.manifest_artifact.uri)
                manifest = json.loads(raw_manifest)
            except Exception as exc:  # noqa: BLE001
                return PublicationVerification(
                    publication_id=plan.publication_id,
                    publication_digest=plan.publication_digest,
                    status=PublicationStatus.VERIFICATION_FAILED,
                    errors=[f"CLOSURE_MANIFEST_UNREADABLE:{type(exc).__name__}"],
                    independent=independent,
                )
            if not manifest.get("closed") or manifest.get("state") != "COMPLETE":
                errors.append("CLOSURE_MANIFEST_NOT_CLOSED")
            if manifest.get("publication_digest") != plan.publication_digest:
                errors.append("PUBLICATION_DIGEST_MISMATCH")
            if manifest.get("content_digest") != plan.content_digest:
                errors.append("CONTENT_DIGEST_MISMATCH")
        declared = {str(item.get("path")): item for item in (manifest.get("files") or [])}
        expected = {item.path: item for item in plan.artifacts}
        if require_marker and set(declared) != set(expected):
            errors.append("FILE_SET_MISMATCH")
        for path, item in expected.items():
            try:
                text = await _read_text(port, item.uri)
                digest = _sha(text.encode("utf-8"))
                actual_size = len(text.encode("utf-8"))
            except Exception as exc:  # noqa: BLE001
                errors.append(f"FILE_UNREADABLE:{path}:{type(exc).__name__}")
                continue
            declared_item = declared.get(path) or {}
            if digest != item.sha256:
                errors.append(f"FILE_HASH_MISMATCH:{path}")
            if declared_item.get("sha256") not in (None, digest):
                errors.append(f"MANIFEST_HASH_MISMATCH:{path}")
            if actual_size != item.size:
                errors.append(f"FILE_SIZE_MISMATCH:{path}")
            files.append({"path": path, "sha256": digest, "size": actual_size, "ok": digest == item.sha256})
        if require_marker:
            try:
                marker_text = await _read_text(port, plan.manifest_artifact.uri)
                marker_digest = _sha(marker_text.encode("utf-8"))
                if marker_digest != plan.manifest_artifact.sha256:
                    errors.append("CLOSURE_MARKER_HASH_MISMATCH")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"CLOSURE_MARKER_UNREADABLE:{type(exc).__name__}")
        return PublicationVerification(
            publication_id=plan.publication_id,
            publication_digest=plan.publication_digest,
            status=PublicationStatus.VERIFIED if not errors else PublicationStatus.VERIFICATION_FAILED,
            files=files, errors=errors, independent=independent, manifest=manifest,
        )

    async def verify_target(
        self,
        target_uri: str,
        publication_digest: str,
        content_digest: str,
        expected_artifacts: dict[str, dict[str, Any]],
        port: OpenVikingPublicationPort,
        *,
        independent: bool = False,
    ) -> PublicationVerification:
        """Verify using only the provider and frozen expected hashes."""
        errors: list[str] = []
        files: list[dict[str, Any]] = []
        try:
            manifest_text = await _read_text(port, f"{target_uri}/publication_manifest.json")
            manifest = json.loads(manifest_text)
        except Exception as exc:  # noqa: BLE001
            return PublicationVerification(
                publication_id="", publication_digest=publication_digest,
                status=PublicationStatus.VERIFICATION_FAILED,
                errors=[f"CLOSURE_MANIFEST_UNREADABLE:{type(exc).__name__}"],
                independent=independent,
            )
        if not manifest.get("closed") or manifest.get("state") != "COMPLETE":
            errors.append("CLOSURE_MANIFEST_NOT_CLOSED")
        if manifest.get("publication_digest") != publication_digest:
            errors.append("PUBLICATION_DIGEST_MISMATCH")
        if manifest.get("content_digest") != content_digest:
            errors.append("CONTENT_DIGEST_MISMATCH")
        declared = {str(item.get("path")): item for item in (manifest.get("files") or [])}
        if set(declared) != set(expected_artifacts):
            errors.append("FILE_SET_MISMATCH")
        for path, expected in expected_artifacts.items():
            uri = str(expected.get("uri") or f"{target_uri}/{path}")
            try:
                text = await _read_text(port, uri)
                digest = _sha(text.encode("utf-8"))
            except Exception as exc:  # noqa: BLE001
                errors.append(f"FILE_UNREADABLE:{path}:{type(exc).__name__}")
                continue
            if digest != expected.get("sha256") or digest != (declared.get(path) or {}).get("sha256"):
                errors.append(f"FILE_HASH_MISMATCH:{path}")
            files.append({"path": path, "sha256": digest, "size": len(text.encode("utf-8")), "ok": digest == expected.get("sha256")})
        return PublicationVerification(
            publication_id=str(manifest.get("publication_id") or ""),
            publication_digest=publication_digest,
            status=PublicationStatus.VERIFIED if not errors else PublicationStatus.VERIFICATION_FAILED,
            files=files, errors=errors, independent=independent, manifest=manifest,
        )
