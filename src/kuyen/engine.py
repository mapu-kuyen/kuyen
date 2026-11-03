"""KÜYEN engine: the public boundary between agents and OpenViking."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import threading
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any

from .canonical import request_key as make_request_key
from ._version import resolve_version
from .config import KuyenConfig
from .coverage import inventory_sections
from .coverage.sections import SectionUnit
from .errors import (
    AdapterError, CandidateMaterializationError, ExecutionNotFoundError,
    ExecutionNotTerminalError, InvalidRequestError, KuyenError, VersionNotFoundError,
)
from .execution import (
    ExecutionHandle, ExecutionRecord, ExecutionRegistry, ExecutionState, new_execution_id,
)
from .models import ActorContext, Antu, BuildResult, CandidateBundle, KuyenGraph, Mapu, ValidationReport
from .materialization import CandidateMaterializer
from .normalization import normalize_bundle
from .publication.coordinator import PublicationCoordinator
from .publication.models import PublicationHandle, PublicationStatus
from .publication.planner import PublicationPlanner
from .publication.registry import PublicationRegistry
from .publication.verifier import PublicationVerifier
from .ontology import Ontology
from .ports.openviking import OpenVikingPort
from .security import redact, validate_actor
from .semantics import annotate_predicate_provenance, preserve_incompatible_relations
from .credentials import SecretReference
from .validation import AcceptanceGate, RequestValidator
from .versioning import VersionRegistry


class KuyenEngine:
    def __init__(
        self, config: KuyenConfig, *, adapter: OpenVikingPort | None = None,
        publication_adapter=None,
    ):
        self.config = config
        self.config.ensure_dirs()
        self._adapter = adapter
        self._publication_adapter = publication_adapter
        self.ontology = Ontology.load(config.ontology_path)
        self.registry = VersionRegistry(config.data_dir)
        self.executions = ExecutionRegistry(config.data_dir)
        self.publications = PublicationRegistry(config.data_dir)
        self.request_validator = RequestValidator()
        self.gate = AcceptanceGate()
        self.version = _implementation_version()

    def _skill_sha(self) -> str:
        path = self.config.skill_dir / "SKILL.md"
        if not path.is_file():
            raise InvalidRequestError(f"versioned Skill missing: {path}")
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def _expected_units(self, mapus: list[Mapu]):
        if self.config.coverage_profile == "document-chunks-v1":
            inventory = {}
            for item in mapus:
                raw = item.metadata.get("coverage_units") or []
                if not raw:
                    raise InvalidRequestError(f"MAPU {item.mapu_id} has no document-chunks-v1 inventory")
                inventory[item.mapu_id] = [SectionUnit(**entry) for entry in raw]
            return inventory
        if self.config.coverage_profile != "document-sections-v1":
            return None
        return {
            item.mapu_id: inventory_sections(item.content, mapu_id=item.mapu_id)
            for item in mapus
        }

    async def build_async(
        self,
        *,
        antu: dict[str, Any] | Antu,
        mapu_sources: list[Mapu],
        actor: ActorContext,
        adapter: OpenVikingPort | None = None,
        instruction: str | None = None,
        execution_id: str | None = None,
        progress: Any = None,
    ) -> BuildResult:
        """Ingest, compile through OpenViking, then accept or reject deterministically."""
        antu_obj = _coerce_antu(antu)
        validate_actor(actor, antu_obj)
        errors = self.request_validator.validate(antu_obj, mapu_sources, self.ontology)
        if errors:
            raise InvalidRequestError(
                "request validation failed",
                details={"issues": [item.to_dict() for item in errors]},
            )
        selected = adapter or self._adapter
        if selected is None:
            raise AdapterError("an OpenViking adapter is required for build")
        execution_id = execution_id or f"exec_{uuid.uuid4().hex}"
        skill_sha = self._skill_sha()
        execution_key = make_request_key(
            antu=antu_obj.to_dict(),
            mapus=[item.to_dict() for item in mapu_sources],
            implementation_version=self.version,
            ontology_version=self.ontology.version_id,
            skill_sha256=skill_sha,
            openviking_version="0.5.2.1",
            actor=actor.to_dict(),
        )
        try:
            health = await selected.health()
            if isinstance(health, dict) and health.get("status_code") not in (None, 200):
                raise AdapterError(f"OpenViking health check returned {health.get('status_code')}")
            detected_version = _health_version(health)
            source_uris: list[str] = []
            normalized_mapus: list[Mapu] = []
            for mapu in mapu_sources:
                uri = await selected.ensure_source(mapu, self.config.source_container_uri)
                normalized_mapus.append(replace(mapu, source_uri=uri))
                source_uris.append(uri)
            await selected.wait_processed(self.config.task_timeout_s)
            skill_uri = await selected.ensure_skill(str(self.config.skill_dir), "viking://agent/skills")
            to_uri = f"{self.config.candidate_container_uri.rstrip('/')}/{execution_key}"
            task_id = await selected.compile(
                # OpenViking compile accepts source directories, not individual
                # file URIs. The concrete file URIs above are still verified.
                from_uris=[self.config.source_container_uri],
                to_uri=to_uri,
                skill_uri=skill_uri,
                instruction=instruction or _graph_compile_instruction(antu_obj, normalized_mapus, to_uri),
            )
            snapshot = await selected.wait_task(task_id, self.config.task_timeout_s)
            if snapshot.status != "completed":
                report = self._blocked_report("OPENVIKING_TASK_FAILED", f"task ended {snapshot.status}")
                self.registry.record_rejected(
                    request_key=execution_key,
                    execution_id=execution_id,
                    candidate={"task_id": task_id, "task": snapshot.raw},
                    report=report,
                    reason=f"OPENVIKING_TASK_{snapshot.status.upper()}",
                )
                return BuildResult(
                    status="REJECTED", kuyen_id=None, request_key=execution_key,
                    execution_id=execution_id, version=antu_obj.version, graph_uri=None,
                    entity_count=0, relation_count=0, coverage={},
                    validation=report, provenance_manifest=None, content_digest=None,
                    error={"code": "OPENVIKING_TASK_FAILED", "task_id": task_id, "status": snapshot.status},
                )
            materialization = None
            inventory = self._expected_units(normalized_mapus)
            if hasattr(selected, "read_provider_artifacts"):
                artifacts: dict[str, str] = {}
                try:
                    artifacts = await selected.read_provider_artifacts(to_uri)
                    materialized = CandidateMaterializer(
                        mapus=normalized_mapus, antu=antu_obj,
                        coverage_inventory=inventory,
                        contract=self.config.provider_contract,
                        result_filename=self.config.provider_result_filename,
                    ).materialize(artifacts, provider={"task_id": task_id, "output_uri": to_uri})
                    bundle = materialized.bundle
                    materialization = materialized.manifest
                except CandidateMaterializationError as exc:
                    report = self._blocked_report("CANDIDATE_MATERIALIZATION_FAILED", exc.message)
                    self.registry.record_rejected(
                        request_key=execution_key, execution_id=execution_id,
                        candidate={"error": exc.to_dict(), "artifacts": sorted(artifacts)},
                        report=report, reason="CANDIDATE_MATERIALIZATION_FAILED",
                    )
                    return BuildResult(
                        status="REJECTED", kuyen_id=None, request_key=execution_key,
                        execution_id=execution_id, version=antu_obj.version, graph_uri=None,
                        entity_count=0, relation_count=0, coverage={},
                        validation=report, provenance_manifest=None, content_digest=None,
                        error=exc.to_dict(),
                    )
            else:
                bundle = await selected.read_candidate(to_uri)
            if progress:
                progress(ExecutionState.CANDIDATE_READY, {"task_id": task_id, "compile_status": snapshot.status})
                progress(ExecutionState.VALIDATING, {})
            return self._evaluate(
                antu=antu_obj, mapus=normalized_mapus, actor=actor, bundle=bundle,
                request_key=execution_key, execution_id=execution_id, skill_sha=skill_sha,
                task_id=task_id, to_uri=to_uri, materialization=materialization,
                openviking_version=detected_version,
            )
        except KuyenError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise AdapterError(f"OpenViking integration failed: {type(exc).__name__}: {exc}") from exc

    def build(
        self,
        *,
        antu: dict[str, Any] | Antu,
        mapu_sources: list[Mapu],
        actor: ActorContext,
        adapter: OpenVikingPort | None = None,
        instruction: str | None = None,
    ) -> BuildResult:
        """Synchronous public API. Use build_async inside an event loop."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(
                self.build_async(
                    antu=antu, mapu_sources=mapu_sources, actor=actor,
                    adapter=adapter, instruction=instruction,
                )
            )
        raise RuntimeError("build() cannot run inside an event loop; use build_async()")

    async def build_from_candidate_async(
        self,
        *,
        antu: dict[str, Any] | Antu,
        mapu_sources: list[Mapu],
        actor: ActorContext,
        candidate: CandidateBundle,
        request_key: str | None = None,
        execution_id: str | None = None,
        progress: Any = None,
    ) -> BuildResult:
        """Deterministic core path for tests and controlled pre-computed candidates."""
        antu_obj = _coerce_antu(antu)
        validate_actor(actor, antu_obj)
        errors = self.request_validator.validate(antu_obj, mapu_sources, self.ontology)
        if errors:
            raise InvalidRequestError("request validation failed", details={"issues": [item.to_dict() for item in errors]})
        execution_id = execution_id or f"exec_{uuid.uuid4().hex}"
        key = request_key or make_request_key(
            antu=antu_obj.to_dict(),
            mapus=[item.to_dict() for item in mapu_sources],
            implementation_version=self.version,
            ontology_version=self.ontology.version_id,
            skill_sha256=self._skill_sha(),
            openviking_version="0.5.2.1",
            actor=actor.to_dict(),
        )
        if progress:
            progress(ExecutionState.CANDIDATE_READY, {})
            progress(ExecutionState.VALIDATING, {})
        return self._evaluate(
            antu=antu_obj, mapus=mapu_sources, actor=actor, bundle=candidate,
            request_key=key, execution_id=execution_id, skill_sha=self._skill_sha(),
            task_id=None, to_uri=None,
        )

    def submit(
        self,
        *,
        antu: dict[str, Any] | Antu | None = None,
        mapu_sources: list[Mapu] | None = None,
        actor: ActorContext | None = None,
        adapter: OpenVikingPort | None = None,
        instruction: str | None = None,
        candidate: CandidateBundle | None = None,
        wait: bool = False,
        request: dict[str, Any] | Antu | None = None,
        mapus: list[Mapu] | None = None,
    ) -> ExecutionHandle:
        """Queue a build. `request`/`mapus` are compatibility aliases."""
        antu = antu if antu is not None else request
        mapu_sources = mapu_sources if mapu_sources is not None else mapus
        if antu is None:
            raise InvalidRequestError("submit requires an Antü request")
        if mapu_sources is None:
            raise InvalidRequestError("submit requires mapu_sources")
        if actor is None:
            raise InvalidRequestError("submit requires an actor context")
        antu_obj = _coerce_antu(antu)
        validate_actor(actor, antu_obj)
        errors = self.request_validator.validate(antu_obj, mapu_sources, self.ontology)
        if errors:
            raise InvalidRequestError("request validation failed", details={"issues": [item.to_dict() for item in errors]})
        if isinstance(candidate, dict):
            candidate = CandidateBundle.from_dict(candidate)
        selected = adapter or self._adapter
        if candidate is None and selected is None:
            raise AdapterError("submit requires an OpenViking adapter or a controlled candidate")
        skill_sha = self._skill_sha()
        execution_id = new_execution_id()
        request_key = make_request_key(
            antu=antu_obj.to_dict(), mapus=[item.to_dict() for item in mapu_sources],
            implementation_version=self.version, ontology_version=self.ontology.version_id,
            skill_sha256=skill_sha, openviking_version="0.5.2.1", actor=actor.to_dict(),
        )
        record = ExecutionRecord(
            execution_id=execution_id, request_key=request_key, antu_id=antu_obj.antu_id,
            mapu_ids=[item.mapu_id for item in mapu_sources], actor=actor.to_dict(),
            state=ExecutionState.PENDING,
        )
        self.executions.create(record)
        thread = threading.Thread(
            target=self._execute_submission,
            kwargs={
                "execution_id": execution_id, "antu": antu_obj, "mapus": mapu_sources,
                "actor": actor, "adapter": selected, "candidate": candidate,
                "instruction": instruction, "request_key": request_key,
            }, daemon=True,
        )
        thread.start()
        if wait:
            thread.join()
        current = self.executions.get(execution_id)
        if not wait:
            # The handle is the acceptance snapshot; work may already be RUNNING.
            return ExecutionHandle(
                execution_id=record.execution_id, request_key=record.request_key,
                state=ExecutionState.PENDING, updated_at=record.created_at,
            )
        return ExecutionHandle(
            execution_id=current.execution_id, request_key=current.request_key,
            state=current.state, updated_at=current.updated_at, error=current.error,
        )

    def get_status(self, execution_id: str) -> ExecutionHandle:
        record = self.executions.get(execution_id)
        return ExecutionHandle(
            execution_id=record.execution_id, request_key=record.request_key,
            state=record.state, updated_at=record.updated_at, error=record.error,
        )

    def get_result(self, execution_id: str) -> BuildResult:
        record = self.executions.get(execution_id)
        if record.state not in {ExecutionState.ACCEPTED, ExecutionState.REJECTED, ExecutionState.FAILED}:
            raise ExecutionNotTerminalError(f"execution is {record.state.value}")
        if record.result:
            return BuildResult.from_dict(record.result)
        return BuildResult(
            status="BLOCKED", kuyen_id=None, request_key=record.request_key,
            execution_id=record.execution_id, version=record.version or "",
            graph_uri=None, entity_count=0, relation_count=0, coverage={},
            validation=ValidationReport(accepted=False),
            provenance_manifest=record.manifest_path, content_digest=None,
            error=record.error or {"code": "EXECUTION_FAILED"},
        )

    def get_version(self, kuyen_id: str, *, actor: ActorContext | None = None) -> dict[str, Any]:
        if not re.fullmatch(r"KUY-[a-f0-9]{12}", kuyen_id):
            raise VersionNotFoundError(kuyen_id)
        root = self.registry.versions / kuyen_id
        manifests = sorted(root.glob("*/manifest.json")) if root.is_dir() else []
        if not manifests:
            raise VersionNotFoundError(kuyen_id)
        path = manifests[-1]
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if actor is not None:
            entry = next((item for item in self.registry.list_versions() if item.get("kuyen_id") == kuyen_id), None)
            entry_actor = (entry or {}).get("actor") or {}
            if entry_actor.get("leftraru_id") != actor.leftraru_id or entry_actor.get("authenticated_account") != actor.authenticated_account:
                raise VersionNotFoundError(kuyen_id)
        hashes_ok = all(
            hashlib.sha256((path.parent / rel).read_bytes()).hexdigest() == digest
            for rel, digest in (manifest.get("files") or {}).items()
        )
        graph = json.loads((path.parent / "graph.json").read_text(encoding="utf-8"))
        return {
            "kuyen_id": kuyen_id, "version": manifest.get("version"),
            "path": str(path.parent), "manifest": manifest, "graph": graph,
            "hashes_verified": hashes_ok,
        }

    def list_versions(self, *, request_key: str | None = None, actor: ActorContext | None = None) -> list[dict[str, Any]]:
        entries = self.registry.list_versions(request_key=request_key)
        if actor is not None:
            entries = [
                item for item in entries
                if (item.get("actor") or {}).get("leftraru_id") == actor.leftraru_id
                and (item.get("actor") or {}).get("authenticated_account") == actor.authenticated_account
            ]
        return entries

    def _make_publication_adapter(self):
        # Imported here so that importing the core never needs an HTTP client.
        from .adapters.openviking_publication import SdkOpenVikingPublicationAdapter

        return SdkOpenVikingPublicationAdapter(
            url=self.config.openviking_url,
            credential_reference=SecretReference(self.config.openviking_api_key_env),
        )

    def _local_version_dir(self, kuyen_id: str, version: str | None = None) -> Path:
        if not re.fullmatch(r"KUY-[a-f0-9]{12}", kuyen_id):
            raise VersionNotFoundError(kuyen_id)
        root = self.registry.versions / kuyen_id
        candidates = sorted(root.glob("*/manifest.json")) if root.is_dir() else []
        if version:
            candidates = [item for item in candidates if item.parent.name == version]
        if not candidates:
            raise VersionNotFoundError(kuyen_id if not version else f"{kuyen_id}@{version}")
        return candidates[-1].parent

    def _publication_plan(
        self, kuyen_id: str, version: str | None = None, *,
        namespace: str | None = None, source_policy: str | None = None,
    ):
        local_dir = self._local_version_dir(kuyen_id, version)
        planner = PublicationPlanner(
            root_uri=self.config.publication_root_uri,
            namespace=namespace or self.config.publication_namespace,
            ontology=self.ontology,
        )
        policy = source_policy or ("include_content" if self.config.publish_source_content else "references_only")
        return planner.plan(local_dir, source_policy=policy)

    def publish(
        self,
        *,
        kuyen_id: str,
        actor: ActorContext,
        version: str | None = None,
        adapter=None,
        setup_adapter=None,
        verification_adapter_factory=None,
        acl: dict[str, Any] | None = None,
        namespace: str | None = None,
        source_policy: str | None = None,
    ) -> PublicationHandle:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.publish_async(
                kuyen_id=kuyen_id, actor=actor, version=version, adapter=adapter,
                setup_adapter=setup_adapter,
                verification_adapter_factory=verification_adapter_factory, acl=acl,
                namespace=namespace, source_policy=source_policy,
            ))
        raise RuntimeError("publish() cannot run inside an event loop; use publish_async()")

    async def publish_async(
        self,
        *,
        kuyen_id: str,
        actor: ActorContext,
        version: str | None = None,
        adapter=None,
        setup_adapter=None,
        verification_adapter_factory=None,
        acl: dict[str, Any] | None = None,
        namespace: str | None = None,
        source_policy: str | None = None,
    ) -> PublicationHandle:
        if not all(str(getattr(actor, name, "")).strip() for name in (
            "leftraru_id", "authenticated_account", "authenticated_user",
            "service_identity", "antu_author", "candidate_producer",
        )):
            raise InvalidRequestError("publication actor is incomplete")
        plan = self._publication_plan(kuyen_id, version, namespace=namespace, source_policy=source_policy)
        if acl is None and self.config.publication_acl_entries:
            acl = {
                "acl_mode": self.config.publication_acl_mode,
                "entries": [dict(item) for item in self.config.publication_acl_entries],
            }
        port = adapter or self._publication_adapter or self._make_publication_adapter()
        factory = verification_adapter_factory
        if factory is None and adapter is None:
            factory = self._make_publication_adapter
        coordinator = PublicationCoordinator(self.publications, PublicationVerifier())
        record = await coordinator.publish(
            plan, actor=actor.to_dict(), adapter=port, acl=acl,
            setup_adapter=setup_adapter,
            verification_adapter_factory=factory,
        )
        return record.handle

    def get_publication_status(self, publication_id: str) -> PublicationHandle:
        return self.publications.get(publication_id).handle

    async def verify_publication_async(self, publication_id: str, adapter=None):
        record = self.publications.get(publication_id)
        plan = self._publication_plan(record.kuyen_id, record.version, source_policy=record.source_policy)
        port = adapter or self._make_publication_adapter()
        verification = await PublicationVerifier().verify_plan(plan, port, independent=True)
        current = record
        if record.status is PublicationStatus.PUBLISHED:
            current = self.publications.transition(publication_id, PublicationStatus.VERIFYING)
        if current.status is PublicationStatus.VERIFYING:
            self.publications.transition(
                publication_id,
                PublicationStatus.VERIFIED if verification.ok else PublicationStatus.VERIFICATION_FAILED,
                verification=verification.to_dict(), verified_files=verification.files,
                error=None if verification.ok else {"code": "VERIFICATION_FAILED", "errors": verification.errors},
            )
        elif current.status is PublicationStatus.VERIFIED and not verification.ok:
            self.publications.transition(
                publication_id, PublicationStatus.VERIFICATION_FAILED,
                verification=verification.to_dict(), verified_files=verification.files,
                error={"code": "VERIFICATION_FAILED", "errors": verification.errors},
            )
        return verification

    def verify_publication(self, publication_id: str, adapter=None):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.verify_publication_async(publication_id, adapter=adapter))
        raise RuntimeError("verify_publication() cannot run inside an event loop; use verify_publication_async()")

    async def get_published_version_async(
        self, *, kuyen_id: str, publication_digest: str, actor: ActorContext, adapter=None,
    ) -> dict[str, Any]:
        matches = [
            item for item in self.publications.list()
            if item.kuyen_id == kuyen_id and item.publication_digest == publication_digest
        ]
        if not matches:
            from .errors import PublicationNotFoundError
            raise PublicationNotFoundError(publication_digest)
        record = matches[-1]
        if (
            record.actor.get("leftraru_id") != actor.leftraru_id
            or record.actor.get("authenticated_account") != actor.authenticated_account
        ):
            from .errors import PublicationNotFoundError
            raise PublicationNotFoundError(publication_digest)
        plan = self._publication_plan(kuyen_id, record.version, source_policy=record.source_policy)
        port = adapter or self._make_publication_adapter()
        verification = await PublicationVerifier().verify_plan(plan, port, independent=True)
        if not verification.ok:
            from .errors import PublicationVerificationError
            raise PublicationVerificationError("published version did not verify", details={"errors": verification.errors})
        graph_text = await port.read(f"{plan.target_uri}/kuyen.json")
        return {
            "kuyen_id": kuyen_id, "publication_id": record.publication_id,
            "publication_digest": publication_digest, "target_uri": plan.target_uri,
            "graph": json.loads(graph_text), "manifest": verification.manifest,
            "verification": verification.to_dict(),
        }

    def get_published_version(self, *, kuyen_id: str, publication_digest: str, actor: ActorContext, adapter=None):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.get_published_version_async(
                kuyen_id=kuyen_id, publication_digest=publication_digest, actor=actor, adapter=adapter,
            ))
        raise RuntimeError("get_published_version() cannot run inside an event loop; use get_published_version_async()")

    def _execute_submission(self, *, execution_id: str, antu: Antu, mapus: list[Mapu], actor: ActorContext, adapter, candidate, instruction, request_key):
        def progress(state: ExecutionState, meta: dict[str, Any]):
            self.executions.transition(execution_id, state, **meta)

        try:
            self.executions.transition(execution_id, ExecutionState.RUNNING)
            if candidate is not None:
                result = asyncio.run(self.build_from_candidate_async(
                    antu=antu, mapu_sources=mapus, actor=actor, candidate=candidate,
                    request_key=request_key, execution_id=execution_id, progress=progress,
                ))
            else:
                result = asyncio.run(self.build_async(
                    antu=antu, mapu_sources=mapus, actor=actor, adapter=adapter,
                    instruction=instruction, execution_id=execution_id, progress=progress,
                ))
            final = ExecutionState.ACCEPTED if result.status == "ACCEPTED" else ExecutionState.REJECTED
            self.executions.transition(
                execution_id, final, result=result.to_dict(),
                manifest_path=result.provenance_manifest, graph_uri=result.graph_uri,
                version=result.version, validation_status=result.status,
            )
        except Exception as exc:  # noqa: BLE001
            if isinstance(exc, KuyenError):
                error = _sanitize_secret(exc.to_dict(), os.environ.get(self.config.openviking_api_key_env))
            else:
                error = {
                    "code": "EXECUTION_FAILED",
                    "message": _redact_secret_text(f"{type(exc).__name__}: {exc}", self.config.openviking_api_key_env)[:500],
                }
            self.executions.transition(
                execution_id, ExecutionState.FAILED, error=redact(error),
                compile_status="FAILED", validation_status="FAILED",
            )

    def _evaluate(
        self,
        *,
        antu: Antu,
        mapus: list[Mapu],
        actor: ActorContext,
        bundle: CandidateBundle,
        request_key: str,
        execution_id: str,
        skill_sha: str,
        task_id: str | None,
        to_uri: str | None,
        materialization: dict[str, Any] | None = None,
        openviking_version: str | None = None,
    ) -> BuildResult:
        expected_units = self._expected_units(mapus)
        provenance = {
            "implementation": "kuyen",
            "implementation_version": self.version,
            "schema_version": "kuyen-native-v1",
            "ontology": self.ontology.version_id,
            "skill_sha256": skill_sha,
            "openviking_version": openviking_version or "unknown",
            "actor": actor.to_dict(),
            "antu_id": antu.antu_id,
            "antu_version": antu.version,
            "request_key": request_key,
            "execution_id": execution_id,
            "task_id": task_id,
            "candidate_uri": to_uri,
            "coverage_profile": self.config.coverage_profile,
            "materialization": materialization,
            "coverage_inventory": (
                {
                    mapu_id: [unit.to_dict() for unit in units]
                    for mapu_id, units in expected_units.items()
                }
                if expected_units is not None else None
            ),
            "mapus": [
                {
                    "mapu_id": item.mapu_id,
                    "version": item.version,
                    "source_uri": item.source_uri,
                    "sha256": item.sha256,
                }
                for item in mapus
            ],
        }
        # Declare the predicate layer before normalization: source / canonical /
        # provider projection and the correspondence state. Legacy payloads and
        # direction-incompatible terms get an explicit state, never a silent
        # related_to with EXACT.
        predicate_provenance = annotate_predicate_provenance(bundle, self.ontology)
        provenance["predicate_provenance"] = predicate_provenance
        relation_preservation = preserve_incompatible_relations(bundle, self.ontology)
        provenance["relation_preservation"] = relation_preservation
        graph = normalize_bundle(
            bundle=bundle, antu_id=antu.antu_id, mapus=mapus,
            version=antu.version, provenance=provenance,
        )
        report = self.gate.validate(
            graph=graph, antu=antu, mapus=mapus, ontology=self.ontology,
            expected_units=expected_units,
        )
        if not report.accepted:
            self.registry.record_rejected(
                request_key=request_key, execution_id=execution_id,
                candidate=redact(bundle.raw or {"entities": [], "relations": []}),
                report=report, reason="VALIDATION_REJECTED",
            )
            return BuildResult(
                status="REJECTED", kuyen_id=graph.kuyen_id, request_key=request_key,
                execution_id=execution_id, version=antu.version, graph_uri=None,
                entity_count=len(graph.entities), relation_count=len(graph.relations),
                coverage=_coverage_summary(graph), validation=report,
                provenance_manifest=None, content_digest=graph.content_digest,
                error={"code": "VALIDATION_REJECTED", "issues": [item.to_dict() for item in report.errors]},
            )
        graph.status = "ACCEPTED"
        entry = self.registry.persist_accepted(
            graph, request_key=request_key, execution_id=execution_id, report=report,
            mapus=mapus,
        )
        return BuildResult(
            status="ACCEPTED", kuyen_id=graph.kuyen_id, request_key=request_key,
            execution_id=execution_id, version=graph.version,
            graph_uri=entry.get("graph_uri"), entity_count=len(graph.entities),
            relation_count=len(graph.relations), coverage=_coverage_summary(graph),
            validation=report, provenance_manifest=entry.get("manifest_path"),
            content_digest=graph.content_digest, reused=bool(entry.get("reused")),
        )

    def _blocked_report(self, code: str, message: str):
        from .models import ValidationIssue, ValidationReport
        return ValidationReport(
            structural="NOT_RUN", evidence="NOT_RUN", ontology="NOT_RUN", coverage="NOT_RUN",
            issues=[ValidationIssue(code=code, message=message, path="openviking")],
            accepted=False,
        )

    async def close(self) -> None:
        if self._adapter is not None:
            await self._adapter.close()


def _coerce_antu(value: dict[str, Any] | Antu) -> Antu:
    if isinstance(value, Antu):
        return value
    try:
        return Antu.from_dict(value)
    except InvalidRequestError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise InvalidRequestError(f"Antü is invalid: {exc}") from exc


def _implementation_version() -> str:
    """Implementation version reported by the engine.

    Delegates to the single resolution mechanism in ``._version`` so the installed
    runtime, the source checkout and the distribution metadata can never disagree.
    There is deliberately no numeric fallback: a guessed version is worse than a
    loud failure.
    """
    return resolve_version()


def _redact_secret_text(value: str, env_name: str) -> str:
    secret = os.environ.get(env_name)
    return value.replace(secret, "[REDACTED]") if secret else value


def _sanitize_secret(value: Any, secret: str | None) -> Any:
    if not secret:
        return value
    if isinstance(value, str):
        return value.replace(secret, "[REDACTED]")
    if isinstance(value, dict):
        return {key: _sanitize_secret(child, secret) for key, child in value.items()}
    if isinstance(value, list):
        return [_sanitize_secret(child, secret) for child in value]
    return value


def _health_version(health: Any) -> str | None:
    """Read the provider version from a `/health` response, or None when unreadable.

    Provenance must record the version that actually answered, never an expected one.
    """
    if not isinstance(health, dict):
        return None
    body = health.get("body")
    if isinstance(body, dict):
        return str(body.get("version") or "") or None
    if isinstance(body, str):
        try:
            return str(json.loads(body).get("version") or "") or None
        except Exception:  # noqa: BLE001
            return None
    return None


def _graph_compile_instruction(antu: Antu, mapus: list[Mapu], to_uri: str) -> str:
    """Instruction for the candidate compilation, in the contract the runtime must produce.

    The Skill explains *how* to read and extract; this instruction fixes *what* artifacts
    KÜYEN materializes and which identity they must carry, so the candidate can be validated
    instead of guessed:

    * the MAPU identity (`mapu_id`, `source_uri`, `source_sha256`) is given, never taken from
      the Skill illustration;
    * the **native tree** is requested (`entities/<slug>.md` + `relations.jsonl` +
      `assertions.jsonl`), because that is what the Skill actually writes. A monolithic
      `kuyen_result.json` is neither asked for nor required: a real compilation of a real
      document produced a malformed one that blocked an otherwise valid tree
      (KUYEN_PRODUCTIVE_GRAPH_11, §8.1);
    * every fact carries a literal quote; the offsets are optional because KÜYEN locates an
      exact quote deterministically, so a runtime that cannot compute them must omit them
      instead of writing 0;
    * `polarity` is explicit (`POSITIVE`/`NEGATIVE`) — KÜYEN does not admit an undeclared
      polarity — and `modality`/`attribution` are declared when the source implies them.
    """
    sources = "\n".join(
        f"- mapu_id={mapu.mapu_id} source_uri={mapu.source_uri} source_sha256={mapu.sha256}"
        for mapu in mapus
    )
    return "\n".join([
        f"Compile the source into a KÜYEN candidate for Antü {antu.antu_id}@{antu.version}.",
        f"Write the native artifact tree in {to_uri}:",
        "- one file `entities/<slug>.md` per entity, with a YAML frontmatter block that",
        '  declares `id`, `name`, `entity_type`, `description`, `aliases`, `sources` and',
        '  `evidence`, plus the prose body;',
        "- one file `relations.jsonl` with one JSON object per line;",
        "- one file `assertions.jsonl` with one JSON object per line.",
        "Do NOT write `kuyen_result.json` or any other aggregate file.",
        'Relation line: {"from","to","relation","label","polarity","sources","evidence"}.',
        'Assertion line: {"subject","predicate","value":{"value_type","value","unit"},'
        '"polarity","modality","attribution","sources","evidence"}.',
        "Entity evidence entry: {\"quote\",\"source_uri\",\"mapu_id\"} plus OPTIONAL "
        "\"char_start\"/\"char_end\" only when both are exact absolute offsets; otherwise omit "
        "both fields. Never write 0 as a placeholder.",
        "`quote` MUST be text copied verbatim from the source, character for character: "
        "KÜYEN locates it in the MAPU and refuses a paraphrase, a summary, a translation or a "
        "reconstructed sentence. If you cannot copy an exact fragment, omit the evidence.",
        "`polarity` is mandatory: POSITIVE or NEGATIVE. `modality` is one of FACT, FORECAST, "
        "ESTIMATE, OPINION, CONDITIONAL, UNKNOWN; a forecast is never FACT. `attribution` is "
        "the literal name of the third party the claim is credited to, or omit it.",
        "`sources` and every `evidence.source_uri` must be EXACTLY the source_uri below "
        "(the file, not its parent directory); `mapu_id` must be exactly the one below:",
        sources,
        "Extract only facts the source states. Keep Spanish. A negation stays negative; a "
        "forecast is not a fact; a claim attributed to a third party keeps that attribution.",
    ])



def _coverage_summary(graph: KuyenGraph) -> dict[str, Any]:
    states: dict[str, int] = {}
    for item in graph.coverage:
        states[item.state.value] = states.get(item.state.value, 0) + 1
    return {
        "unit_count": len(graph.coverage),
        "states": states,
        "complete": all(
            item.state.value in {"PROCESSED_WITH_OUTPUT", "PROCESSED_NO_GRAPH_FACTS"}
            for item in graph.coverage
        ) if graph.coverage else False,
    }
