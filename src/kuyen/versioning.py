"""Immutable accepted-version registry and rejected-attempt archive."""
from __future__ import annotations

import json
import os
import shutil
import threading
from pathlib import Path
from typing import Any

from .canonical import canonical_json
from .errors import VersionConflictError
from .models import KuyenGraph, ValidationReport
from .serialization import KuyenSerializer


class VersionRegistry:
    def __init__(self, data_dir: str | Path):
        self.data_dir = Path(data_dir)
        self.versions = self.data_dir / "versions"
        self.rejected = self.data_dir / "rejected"
        self.staging = self.data_dir / "staging"
        self.registry_path = self.data_dir / "registry.json"
        self.serializer = KuyenSerializer()
        self._lock = threading.RLock()
        for path in (self.versions, self.rejected, self.staging):
            path.mkdir(parents=True, exist_ok=True)

    def _registry(self) -> dict[str, Any]:
        if not self.registry_path.is_file():
            return {"schema_version": "kuyen.registry.v1", "entries": []}
        return json.loads(self.registry_path.read_text(encoding="utf-8"))

    def lookup(self, request_key: str) -> dict[str, Any] | None:
        for entry in self._registry().get("entries", []):
            if entry.get("request_key") == request_key and entry.get("status") == "ACCEPTED":
                return entry
        return None

    def _write_entry(self, entry: dict[str, Any]) -> None:
        data = self._registry()
        data.setdefault("entries", []).append(entry)
        data["entries"].sort(key=lambda item: (item.get("request_key", ""), item.get("version", "")))
        temp = self.registry_path.with_suffix(".json.tmp")
        temp.write_text(canonical_json(data) + "\n", encoding="utf-8")
        os.replace(temp, self.registry_path)

    def persist_accepted(
        self,
        graph: KuyenGraph,
        *,
        request_key: str,
        execution_id: str,
        report: ValidationReport,
        mapus: list[Any] | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            return self._persist_accepted(graph, request_key=request_key, execution_id=execution_id, report=report, mapus=mapus)

    def _persist_accepted(
        self,
        graph: KuyenGraph,
        *,
        request_key: str,
        execution_id: str,
        report: ValidationReport,
        mapus: list[Any] | None = None,
    ) -> dict[str, Any]:
        existing = self.lookup(request_key)
        if existing:
            if existing.get("content_digest") != graph.content_digest:
                raise VersionConflictError("request_key already accepted with a different content digest")
            return {**existing, "reused": True}
        version_dir = self.versions / graph.kuyen_id / graph.version
        if version_dir.exists():
            manifest = json.loads((version_dir / "manifest.json").read_text(encoding="utf-8"))
            if manifest.get("content_digest") != graph.content_digest:
                raise VersionConflictError("version directory already exists with different content")
            return {"kuyen_id": graph.kuyen_id, "version": graph.version, "path": str(version_dir), "graph_uri": f"viking://resources/kuyen/{graph.kuyen_id}/{graph.version}", "content_digest": graph.content_digest, "reused": True}
        staging = self.staging / execution_id
        if staging.exists():
            shutil.rmtree(staging)
        manifest = self.serializer.write_version(graph, staging, mapus=mapus)
        # Validate the staged manifest before making it visible.
        if manifest.get("content_digest") != graph.content_digest:
            raise VersionConflictError("staged manifest digest mismatch")
        version_dir.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staging, version_dir)
        entry = {
            "request_key": request_key,
            "execution_id": execution_id,
            "kuyen_id": graph.kuyen_id,
            "version": graph.version,
            "content_digest": graph.content_digest,
            "provenance_digest": graph.provenance_digest,
            "manifest_path": str(version_dir / "manifest.json"),
            "graph_uri": f"viking://resources/kuyen/{graph.kuyen_id}/{graph.version}",
            "status": "ACCEPTED",
            "actor": graph.provenance.get("actor", {}),
            "validation": report.to_dict(),
        }
        self._write_entry(entry)
        return {**entry, "reused": False}

    def list_versions(self, request_key: str | None = None) -> list[dict[str, Any]]:
        entries = self._registry().get("entries", [])
        if request_key is not None:
            entries = [item for item in entries if item.get("request_key") == request_key]
        return sorted(entries, key=lambda item: (item.get("kuyen_id", ""), item.get("version", "")))

    def record_rejected(
        self,
        *,
        request_key: str,
        execution_id: str,
        candidate: dict[str, Any],
        report: ValidationReport,
        reason: str,
    ) -> Path:
        target = self.rejected / execution_id
        target.mkdir(parents=True, exist_ok=False)
        (target / "candidate.json").write_text(
            json.dumps(candidate, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (target / "validation.json").write_text(
            json.dumps(report.to_dict(), indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (target / "decision.json").write_text(
            json.dumps(
                {"request_key": request_key, "execution_id": execution_id, "status": "REJECTED", "reason": reason},
                indent=2,
                sort_keys=True,
            ) + "\n",
            encoding="utf-8",
        )
        return target
