"""Canonical and OpenViking-native serialization."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

from ..canonical import canonical_json
from ..models import Entity, KuyenGraph, Mapu, Relation


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class KuyenSerializer:
    @staticmethod
    def canonical_graph(graph: KuyenGraph) -> str:
        return canonical_json(graph.to_dict()) + "\n"

    @staticmethod
    def canonical_content(graph: KuyenGraph) -> str:
        """Stable content projection excluding volatile execution provenance."""
        return canonical_json({
            "antu_id": graph.antu_id,
            "version": graph.version,
            "mapu_ids": graph.mapu_ids,
            "entities": [item.to_dict() for item in sorted(graph.entities, key=lambda x: x.entity_id)],
            "relations": [item.to_dict() for item in sorted(graph.relations, key=lambda x: x.relation_id)],
            "assertions": [item.to_dict() for item in sorted(graph.assertions, key=lambda x: x.assertion_id)],
            "evidence": [item.to_dict() for item in sorted(graph.evidence, key=lambda x: x.evidence_id)],
            "coverage": [item.to_dict() for item in sorted(graph.coverage, key=lambda x: (x.mapu_id, x.unit_id))],
        }) + "\n"

    @staticmethod
    def entity_markdown(entity: Entity) -> str:
        frontmatter = {
            "type": "entity",
            "id": entity.entity_id,
            "title": entity.name,
            "entity_type": entity.entity_type,
            "description": entity.description,
            "aliases": entity.aliases,
            "sources": entity.sources,
        }
        return "---\n" + yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True).strip() + "\n---\n\n" + (entity.description or entity.name) + "\n"

    @staticmethod
    def relation_line(relation: Relation) -> str:
        # Keep only native fields. The native graph is a provider projection:
        # when KÜYEN had to use a less specific provider predicate, the canonical
        # graph remains authoritative and the projection is recorded on the
        # relation. No source predicate is lost from graph.json.
        item = {
            "from": relation.from_entity,
            "relation": relation.provider_predicate or relation.predicate,
            "label": relation.provider_label or relation.label,
            "to": relation.to_entity,
            "evidence": list(relation.sources),
        }
        return json.dumps(item, ensure_ascii=False, sort_keys=False) + "\n"

    def write_native(self, graph: KuyenGraph, root: str | Path) -> dict[str, str]:
        target = Path(root)
        entities_dir = target / "entities"
        entities_dir.mkdir(parents=True, exist_ok=True)
        files: dict[str, str] = {}
        for entity in sorted(graph.entities, key=lambda item: item.entity_id):
            path = entities_dir / f"{entity.entity_id}.md"
            path.write_text(self.entity_markdown(entity), encoding="utf-8")
            files[path.relative_to(target).as_posix()] = _sha(path)
        relations_path = target / "relations.jsonl"
        relations_path.write_text(
            "".join(self.relation_line(item) for item in sorted(graph.relations, key=lambda x: x.relation_id)), encoding="utf-8"
        )
        files["relations.jsonl"] = _sha(relations_path)
        return files

    def write_version(
        self, graph: KuyenGraph, root: str | Path, mapus: list[Mapu] | None = None
    ) -> dict[str, Any]:
        target = Path(root)
        target.mkdir(parents=True, exist_ok=False)
        files: dict[str, str] = {}
        payloads = {
            "graph.json": graph.to_dict(),
            "evidence.json": [item.to_dict() for item in graph.evidence],
            "coverage.json": [item.to_dict() for item in graph.coverage],
            "provenance.json": graph.provenance,
        }
        for name, payload in payloads.items():
            path = target / name
            path.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            files[name] = _sha(path)
        native_files = self.write_native(graph, target / "native")
        files.update({f"native/{key}": value for key, value in native_files.items()})
        if mapus:
            sources_dir = target / "sources"
            sources_dir.mkdir(parents=True, exist_ok=True)
            source_index = []
            for item in mapus:
                source_path = sources_dir / f"{item.mapu_id}.txt"
                source_path.write_text(item.content, encoding="utf-8")
                files[f"sources/{item.mapu_id}.txt"] = _sha(source_path)
                source_index.append({
                    "mapu_id": item.mapu_id, "version": item.version,
                    "source_uri": item.source_uri, "sha256": item.sha256,
                    "stored_path": f"sources/{item.mapu_id}.txt",
                })
            index_path = target / "sources.json"
            index_path.write_text(
                json.dumps(source_index, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            files["sources.json"] = _sha(index_path)
        manifest = {
            "kuyen_id": graph.kuyen_id,
            "version": graph.version,
            "schema_version": graph.schema_version,
            "antu_id": graph.antu_id,
            "mapu_ids": graph.mapu_ids,
            "content_digest": graph.content_digest,
            "provenance_digest": graph.provenance_digest,
            "files": files,
        }
        manifest_path = target / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        files["manifest.json"] = _sha(manifest_path)
        return manifest


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---\n"):
        raise ValueError("entity frontmatter missing")
    end = text.find("\n---", 4)
    if end < 0:
        raise ValueError("entity frontmatter incomplete")
    raw = text[4:end]
    body = text[end + 4 :].lstrip("\n")
    parsed = yaml.safe_load(raw) or {}
    if not isinstance(parsed, dict):
        raise ValueError("entity frontmatter must be a mapping")
    return parsed, body


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return [str(item) for item in value]


def read_native_entities(root: str | Path) -> list[dict[str, Any]]:
    base = Path(root) / "entities"
    if not base.is_dir():
        raise FileNotFoundError(f"entities directory missing: {base}")
    entities = []
    for path in sorted(base.glob("*.md")):
        meta, body = parse_frontmatter(path.read_text(encoding="utf-8"))
        meta["id"] = str(meta.get("id") or path.stem)
        meta["name"] = str(meta.get("title") or meta.get("name") or meta["id"])
        meta["entity_type"] = str(meta.get("entity_type") or meta.get("type") or "concept")
        meta["description"] = str(meta.get("description") or body.strip())
        meta["sources"] = _as_list(meta.get("sources"))
        meta["aliases"] = _as_list(meta.get("aliases"))
        entities.append(meta)
    return entities


def read_native_relations(root: str | Path) -> list[dict[str, Any]]:
    path = Path(root) / "relations.jsonl"
    if not path.is_file():
        raise FileNotFoundError(f"relations.jsonl missing: {path}")
    rows = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"relations.jsonl line {line_no}: {exc}") from exc
        if not isinstance(row, dict):
            raise ValueError(f"relations.jsonl line {line_no}: object required")
        rows.append(row)
    return rows
