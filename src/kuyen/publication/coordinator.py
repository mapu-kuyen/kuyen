"""Governed, recoverable publication coordinator."""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Callable

from ..errors import PublicationAdapterError, PublicationConflictError
from ..ports.publication import OpenVikingPublicationPort
from .models import (
    PublicationPlan, PublicationRecord, PublicationStatus, PublicationVerification,
)
from .registry import PublicationRegistry
from .verifier import PublicationVerifier


class PublicationCoordinator:
    def __init__(
        self, registry: PublicationRegistry, verifier: PublicationVerifier | None = None,
        *, acl_timeout_s: float = 15.0,
    ):
        self.registry = registry
        self.verifier = verifier or PublicationVerifier()
        self.acl_timeout_s = acl_timeout_s

    async def publish(
        self,
        plan: PublicationPlan,
        *,
        actor: dict[str, Any],
        adapter: OpenVikingPublicationPort,
        acl: dict[str, Any] | None = None,
        setup_adapter: OpenVikingPublicationPort | None = None,
        verification_adapter_factory: Callable[[], OpenVikingPublicationPort] | None = None,
    ) -> PublicationRecord:
        existing = self._find(plan.publication_id)
        if existing is not None:
            if existing.content_digest != plan.content_digest or existing.publication_digest != plan.publication_digest:
                raise PublicationConflictError("publication identity collision")
            if existing.status is PublicationStatus.VERIFIED:
                # Idempotent repetition: verify the existing provider copy again;
                # never rewrite the accepted payload.
                verification = await self.verifier.verify_plan(
                    plan, verification_adapter_factory() if verification_adapter_factory else adapter,
                    independent=verification_adapter_factory is not None,
                )
                if verification.ok:
                    return existing
                raise PublicationConflictError("existing VERIFIED publication no longer verifies")
            if existing.status is PublicationStatus.PUBLISHED and verification_adapter_factory is not None:
                return await self._verify_existing(existing, plan, verification_adapter_factory)
            if existing.status in {PublicationStatus.PUBLICATION_PARTIAL, PublicationStatus.PUBLICATION_FAILED}:
                existing = self.registry.transition(plan.publication_id, PublicationStatus.PUBLISHING)
            else:
                return existing

        if existing is None:
            record = PublicationRecord(
                publication_id=plan.publication_id, kuyen_id=plan.kuyen_id, version=plan.version,
                content_digest=plan.content_digest, publication_digest=plan.publication_digest,
                target_uri=plan.target_uri, actor=actor,
                source_policy=plan.source_policy,
                expected_files=[item.to_dict() for item in plan.artifacts],
            )
            self.registry.create(record)
            existing = record
        existing = self.registry.transition(plan.publication_id, PublicationStatus.PUBLISHING)
        try:
            preflight = await self._preflight(plan, setup_adapter or adapter, acl)
            if preflight == "existing":
                record = self.registry.transition(
                    plan.publication_id, PublicationStatus.PUBLISHED,
                    acl=await self._safe_acl(plan, setup_adapter or adapter),
                    written_files=[item.to_dict() for item in plan.artifacts],
                )
            else:
                record = await self._write_payload(plan, adapter, acl, acl_port=setup_adapter or adapter)
        except Exception as exc:  # noqa: BLE001
            partial = await self._has_partial_payload(plan, adapter)
            status = PublicationStatus.PUBLICATION_PARTIAL if partial else PublicationStatus.PUBLICATION_FAILED
            error = self._error(exc)
            record = self.registry.transition(plan.publication_id, status, error=error)
            return record

        if record.status is PublicationStatus.PUBLISHED and verification_adapter_factory is not None:
            return await self._verify_existing(record, plan, verification_adapter_factory)
        return record

    async def verify_existing(
        self,
        record: PublicationRecord,
        plan: PublicationPlan,
        factory: Callable[[], OpenVikingPublicationPort],
    ) -> PublicationRecord:
        return await self._verify_existing(record, plan, factory)

    async def _verify_existing(
        self,
        record: PublicationRecord,
        plan: PublicationPlan,
        factory: Callable[[], OpenVikingPublicationPort],
    ) -> PublicationRecord:
        if record.status is PublicationStatus.PUBLISHED:
            record = self.registry.transition(record.publication_id, PublicationStatus.VERIFYING)
        verification = await self.verifier.verify_plan(plan, factory(), independent=True)
        status = PublicationStatus.VERIFIED if verification.ok else PublicationStatus.VERIFICATION_FAILED
        if record.status is not PublicationStatus.VERIFYING:
            # A repeated VERIFIED record stays VERIFIED; a failed independent
            # check is still surfaced as an error without rewriting provider data.
            if not verification.ok:
                raise PublicationConflictError("independent read-back failed")
            return record
        return self.registry.transition(
            record.publication_id, status,
            verification=verification.to_dict(),
            verified_files=verification.files,
            error=None if verification.ok else {"code": "VERIFICATION_FAILED", "errors": verification.errors},
        )

    def _find(self, publication_id: str) -> PublicationRecord | None:
        from ..errors import PublicationNotFoundError
        try:
            return self.registry.get(publication_id)
        except PublicationNotFoundError:
            return None

    async def _preflight(
        self, plan: PublicationPlan, port: OpenVikingPublicationPort,
        acl: dict[str, Any] | None,
    ) -> str:
        current = await port.stat(plan.target_uri)
        if current is not None:
            try:
                marker = json.loads(await port.read(plan.manifest_artifact.uri))
            except Exception as exc:  # noqa: BLE001
                raise PublicationConflictError(
                    f"target exists without a readable closure marker: {plan.target_uri}"
                ) from exc
            if marker.get("publication_digest") != plan.publication_digest:
                raise PublicationConflictError("target URI exists with a different publication digest")
            verification = await self.verifier.verify_plan(plan, port)
            if not verification.ok:
                raise PublicationConflictError("target exists but its payload does not verify")
            return "existing"
        await self._ensure_directories(plan, port, acl)
        return "new"

    async def _ensure_directories(
        self, plan: PublicationPlan, port: OpenVikingPublicationPort,
        acl: dict[str, Any] | None,
    ) -> None:
        kuyen_uri = plan.target_uri.split("/versions/", 1)[0]
        namespace_uri = kuyen_uri.rsplit("/", 1)[0]
        versions_uri = f"{kuyen_uri}/versions"
        acl_for_dirs = None if hasattr(port, "acl_set") else acl
        for uri in (namespace_uri, kuyen_uri, versions_uri, plan.target_uri):
            if await port.stat(uri) is None:
                await port.mkdir(uri, acl=acl_for_dirs)
        if acl and not hasattr(port, "acl_set"):
            await self._wait_acl(plan.target_uri, acl, port)

    async def _wait_acl(
        self, uri: str, acl: dict[str, Any], port: OpenVikingPublicationPort,
    ) -> None:
        expected = {str(item.get("principal")): str(item.get("level")) for item in acl.get("entries") or []}
        deadline = time.monotonic() + self.acl_timeout_s
        last: dict[str, Any] = {}
        while time.monotonic() < deadline:
            last = await port.acl_get(uri)
            effective = {str(item.get("principal")): str(item.get("level")) for item in (last.get("effective_entries") or [])}
            if last.get("acl_mode") == acl.get("acl_mode") and all(effective.get(key) == value for key, value in expected.items()):
                return
            await asyncio.sleep(0.5)
        raise PublicationAdapterError(f"ACL did not become effective: {uri}")

    async def _write_payload(
        self, plan: PublicationPlan, port: OpenVikingPublicationPort,
        acl: dict[str, Any] | None, *, acl_port: OpenVikingPublicationPort | None = None,
    ) -> PublicationRecord:
        operations = [
            {"uri": item.uri, "content": item.content.decode("utf-8"), "mode": "create"}
            for item in plan.artifacts
        ]
        await port.batch_write(plan.target_uri, operations, wait=True)
        await port.wait_processed()
        if acl and hasattr(port, "acl_set"):
            await port.acl_set(plan.target_uri, acl)
            await self._wait_acl(plan.target_uri, acl, port)
        verification = await self.verifier.verify_plan(plan, port, require_marker=False)
        if not verification.ok:
            return self.registry.transition(
                plan.publication_id, PublicationStatus.PUBLICATION_PARTIAL,
                written_files=[item.to_dict() for item in plan.artifacts],
                acl=await self._safe_acl(plan, acl_port or port),
                verification=verification.to_dict(),
                error={"code": "PAYLOAD_VERIFICATION_FAILED", "errors": verification.errors},
            )
        await port.write(
            plan.manifest_artifact.uri,
            plan.manifest_artifact.content.decode("utf-8"),
            mode="create", wait=True,
        )
        final_check = await self.verifier.verify_plan(plan, port)
        if not final_check.ok:
            return self.registry.transition(
                plan.publication_id, PublicationStatus.PUBLICATION_PARTIAL,
                written_files=[item.to_dict() for item in plan.artifacts],
                acl=await self._safe_acl(plan, acl_port or port),
                verification=final_check.to_dict(),
                error={"code": "CLOSURE_MARKER_VERIFICATION_FAILED", "errors": final_check.errors},
            )
        return self.registry.transition(
            plan.publication_id, PublicationStatus.PUBLISHED,
            written_files=[item.to_dict() for item in plan.artifacts],
            verified_files=final_check.files,
            acl=await self._safe_acl(plan, port),
            verification=final_check.to_dict(),
            error=None,
        )

    async def _has_partial_payload(self, plan: PublicationPlan, port: OpenVikingPublicationPort) -> bool:
        for item in plan.artifacts:
            try:
                if await port.stat(item.uri) is not None:
                    return True
            except Exception:  # noqa: BLE001
                return True
        return False

    async def _safe_acl(self, plan: PublicationPlan, port: OpenVikingPublicationPort) -> dict[str, Any]:
        try:
            return await port.acl_get(plan.target_uri)
        except Exception as exc:  # noqa: BLE001
            return {"error": type(exc).__name__}

    @staticmethod
    def _error(exc: Exception) -> dict[str, Any]:
        return {
            "code": getattr(exc, "code", "PUBLICATION_FAILED"),
            "message": str(exc)[:500],
        }
