"""Deterministic publication plans built from an already accepted local version."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..canonical import canonical_json
from ..errors import PublicationConflictError
from ..ontology import Ontology
from ..serialization import read_native_entities, read_native_relations
from .models import PublicationArtifact, PublicationPlan


SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
NATIVE_ENTITY_KEYS = {
    "type", "id", "title", "name", "entity_type", "description", "aliases", "sources",
}
NATIVE_RELATION_KEYS = {"from", "relation", "label", "to", "evidence"}


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _read(path: Path) -> bytes:
    if not path.is_file():
        raise PublicationConflictError(f"local version artifact missing: {path}")
    return path.read_bytes()


@dataclass(frozen=True)
class LocalVersion:
    root: Path
    manifest: dict[str, Any]
    graph: dict[str, Any]
    provenance: dict[str, Any]
    kuyen_id: str
    version: str
    content_digest: str
    mapu_refs: list[dict[str, Any]]
    files: dict[str, str]


def load_local_version(root: str | Path) -> LocalVersion:
    target = Path(root)
    manifest_path = target / "manifest.json"
    if not manifest_path.is_file():
        raise PublicationConflictError(f"local manifest missing: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    files = manifest.get("files") or {}
    if not isinstance(files, dict):
        raise PublicationConflictError("local manifest files must be a mapping")
    for rel, expected in files.items():
        path = target / rel
        if not path.is_file() or _sha_bytes(path.read_bytes()) != expected:
            raise PublicationConflictError(f"local manifest hash mismatch: {rel}")
    graph = json.loads(_read(target / "graph.json"))
    provenance = json.loads(_read(target / "provenance.json"))
    kuyen_id = str(manifest.get("kuyen_id") or "")
    version = str(manifest.get("version") or "")
    content_digest = str(manifest.get("content_digest") or "")
    if not SAFE_SEGMENT.match(kuyen_id) or not SAFE_SEGMENT.match(version) or not SAFE_SEGMENT.match(content_digest):
        raise PublicationConflictError("local version identifiers are not URI-safe")
    if graph.get("kuyen_id") != kuyen_id or graph.get("content_digest") != content_digest:
        raise PublicationConflictError("local graph and manifest identity disagree")
    mapu_refs = list(provenance.get("mapus") or [])
    if not mapu_refs:
        raise PublicationConflictError("local provenance has no MAPU references")
    return LocalVersion(
        root=target, manifest=manifest, graph=graph, provenance=provenance,
        kuyen_id=kuyen_id, version=version, content_digest=content_digest,
        mapu_refs=mapu_refs, files=dict(files),
    )


def _native_artifacts(version: LocalVersion, ontology: Ontology) -> list[PublicationArtifact]:
    native = version.root / "native"
    entities = read_native_entities(native)
    relations = read_native_relations(native)
    entity_ids = {str(item.get("id") or "") for item in entities}
    if "" in entity_ids or len(entity_ids) != len(entities):
        raise PublicationConflictError("native entity IDs are missing or duplicated")
    for entity in entities:
        if set(entity) - NATIVE_ENTITY_KEYS:
            raise PublicationConflictError(f"native entity has non-native fields: {entity.get('id')}")
        if not ontology.has_entity_type(str(entity.get("entity_type") or "")):
            raise PublicationConflictError(f"native entity type is not in ontology: {entity.get('id')}")
    seen = set()
    for row in relations:
        if set(row) - NATIVE_RELATION_KEYS:
            raise PublicationConflictError("native relation has non-native fields")
        key = (row.get("from"), row.get("relation"), row.get("to"))
        if key in seen:
            raise PublicationConflictError(f"duplicate native relation: {key}")
        seen.add(key)
        if key[0] not in entity_ids or key[2] not in entity_ids:
            raise PublicationConflictError(f"native relation endpoint is not published: {key}")
        if ontology.relation(str(row.get("relation") or "")) is None:
            raise PublicationConflictError(f"native relation predicate is not in ontology: {key[1]}")
    artifacts: list[PublicationArtifact] = []
    for path in sorted((native / "entities").glob("*.md")):
        rel = path.relative_to(native).as_posix()
        content = _read(path)
        artifacts.append(PublicationArtifact(rel, "", content, _sha_bytes(content), "text/markdown"))
    content = _read(native / "relations.jsonl")
    artifacts.append(PublicationArtifact("relations.jsonl", "", content, _sha_bytes(content), "application/x-ndjson"))
    return artifacts


def _canonical_artifacts(version: LocalVersion, source_policy: str) -> list[PublicationArtifact]:
    artifacts: list[PublicationArtifact] = []
    for rel, target, content_type in (
        ("graph.json", "kuyen.json", "application/json"),
        ("evidence.json", "evidence.json", "application/json"),
        ("coverage.json", "coverage.json", "application/json"),
        ("provenance.json", "provenance.json", "application/json"),
        ("manifest.json", "kuyen_manifest.json", "application/json"),
    ):
        content = _read(version.root / rel)
        artifacts.append(PublicationArtifact(target, "", content, _sha_bytes(content), content_type))
    references = [
        {
            "mapu_id": item.get("mapu_id"), "version": item.get("version"),
            "source_uri": item.get("source_uri"), "sha256": item.get("sha256"),
            "stored_path": f"sources/{item.get('mapu_id')}.txt" if source_policy == "include_content" else None,
        }
        for item in version.mapu_refs
    ]
    content = (canonical_json(references) + "\n").encode("utf-8")
    artifacts.append(PublicationArtifact("sources.json", "", content, _sha_bytes(content), "application/json"))
    if source_policy == "include_content":
        for item in version.mapu_refs:
            mapu_id = str(item.get("mapu_id") or "")
            if not SAFE_SEGMENT.match(mapu_id):
                raise PublicationConflictError(f"MAPU id is not URI-safe: {mapu_id}")
            content = _read(version.root / "sources" / f"{mapu_id}.txt")
            artifacts.append(PublicationArtifact(f"sources/{mapu_id}.txt", "", content, _sha_bytes(content), "text/plain"))
    elif source_policy != "references_only":
        raise PublicationConflictError(f"unsupported source policy: {source_policy}")
    return artifacts

class PublicationPlanner:
    def __init__(self, *, root_uri: str, namespace: str, ontology: Ontology):
        root = root_uri.rstrip("/")
        if not root.startswith("viking://resources/"):
            raise ValueError("publication root must be under viking://resources/")
        if not SAFE_SEGMENT.match(namespace):
            raise ValueError("publication namespace is not URI-safe")
        self.root_uri = root
        self.namespace = namespace
        self.ontology = ontology

    def plan(
        self,
        local_version_dir: str | Path,
        *,
        source_policy: str = "references_only",
        access_profile: str = "restricted",
    ) -> PublicationPlan:
        version = load_local_version(local_version_dir)
        target_uri = f"{self.root_uri}/{self.namespace}/{version.kuyen_id}/versions/{version.content_digest}"
        base_artifacts = [
            *_native_artifacts(version, self.ontology),
            *_canonical_artifacts(version, source_policy),
        ]
        artifacts = [
            PublicationArtifact(
                path=item.path, uri=f"{target_uri}/{item.path}", content=item.content,
                sha256=item.sha256, content_type=item.content_type,
            )
            for item in sorted(base_artifacts, key=lambda x: x.path)
        ]
        identity = {
            "schema_version": "kuyen.publication.v1",
            "kuyen_id": version.kuyen_id,
            "version": version.version,
            "content_digest": version.content_digest,
            "graph_schema_version": version.graph.get("schema_version"),
            "ontology": version.provenance.get("ontology"),
            "mapus": sorted(
                (
                    {
                        "mapu_id": item.get("mapu_id"), "version": item.get("version"),
                        "source_uri": item.get("source_uri"), "sha256": item.get("sha256"),
                    }
                    for item in version.mapu_refs
                ),
                key=lambda x: (str(x["mapu_id"]), str(x["version"])),
            ),
            "access_profile": access_profile,
            "source_policy": source_policy,
            "artifacts": [item.to_dict() for item in artifacts],
            "target_uri": target_uri,
        }
        publication_digest = _sha_bytes((canonical_json(identity) + "\n").encode("utf-8"))
        publication_id = f"PUB-{publication_digest[:12]}"
        publication_json = {
            "schema_version": "kuyen.publication.v1",
            "publication_id": publication_id, "kuyen_id": version.kuyen_id,
            "local_version": version.version, "content_digest": version.content_digest,
            "publication_digest": publication_digest, "target_uri": target_uri,
            "access_profile": access_profile, "source_policy": source_policy,
            "state": "PREPARED",
        }
        publication_content = (json.dumps(publication_json, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
        artifacts.append(PublicationArtifact(
            "publication.json", f"{target_uri}/publication.json", publication_content,
            _sha_bytes(publication_content), "application/json",
        ))
        artifacts.sort(key=lambda x: x.path)
        manifest_payload = {
            "schema_version": "kuyen.publication-manifest.v1",
            "publication_id": publication_id, "kuyen_id": version.kuyen_id,
            "local_version": version.version, "content_digest": version.content_digest,
            "publication_digest": publication_digest, "target_uri": target_uri,
            "access_profile": access_profile, "source_policy": source_policy,
            "state": "COMPLETE", "closed": True,
            "files": [item.to_dict() for item in artifacts],
        }
        manifest_content = (json.dumps(manifest_payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
        manifest_artifact = PublicationArtifact(
            "publication_manifest.json", f"{target_uri}/publication_manifest.json",
            manifest_content, _sha_bytes(manifest_content), "application/json",
        )
        return PublicationPlan(
            publication_id=publication_id, kuyen_id=version.kuyen_id, version=version.version,
            content_digest=version.content_digest, publication_digest=publication_digest,
            target_uri=target_uri, artifacts=artifacts, manifest_artifact=manifest_artifact,
            local_version_dir=str(version.root), access_profile=access_profile,
            source_policy=source_policy,
            metadata={"ontology": version.provenance.get("ontology"), "mapus": version.mapu_refs},
        )
