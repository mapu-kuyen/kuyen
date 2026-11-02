"""Component B - OpenViking Native Projector.

Emits only what the native artifact contract can hold:
`entities/<id>.md` plus one `relations.jsonl` line per
{from, relation, label, to, evidence}. The canonical predicate is always emitted
literally; nothing is replaced by `related_to`. A projection that cannot
represent the canonical contract is labelled `LOSSY_NATIVE_PROJECTION` and every
transformation, loss and collision is recorded in the projection manifest.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..canonical import canonical_json, digest, sha256_text
from ..errors import ProjectionError
from ..contracts import NATIVE_ENTITY_KEYS, NATIVE_RELATION_KEYS, PROJECTOR_VERSION

PREDICATE_RE = re.compile(r"^[a-z][a-z0-9_]*$")
PATH_SAFE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

TRANSFORM_NONE = "NONE_LITERAL"
TRANSFORM_PATH_SANITIZED = "NATIVE_ID_SANITIZED"

LOSS_FIELDS = (
    "relation_id", "polarity", "scope", "temporal_scope", "temporal", "evidence_ids",
    "mapping_status", "provider_projection_status", "semantic_status",
)


@dataclass
class ProjectionResult:
    artifacts: dict[str, str] = field(default_factory=dict)
    manifest: dict[str, Any] = field(default_factory=dict)

    @property
    def projection_id(self) -> str:
        return self.manifest.get("projection_id", "")

    def relations(self) -> list[dict[str, Any]]:
        return [json.loads(line) for line in self.artifacts.get("native/relations.jsonl", "").splitlines() if line.strip()]


class NativeProjector:
    version = PROJECTOR_VERSION
    policy = {
        "predicate_policy": "LITERAL",
        "fallback_predicate": None,
        "native_id_source": "canonical_entity_id",
        "collision_policy": "EXPLICIT_GROUPING_NO_MERGE_OF_CANONICAL_OBJECTS",
        "lossy_label": "LOSSY_NATIVE_PROJECTION",
    }

    def project(self, document: dict[str, Any]) -> ProjectionResult:
        entities = document["canonical"]["entities"]
        relations = document["canonical"]["relations"]
        if not entities:
            raise ProjectionError("native projection requires at least one entity")

        artifacts: dict[str, str] = {}
        native_id_by_canonical, unprojectable = {}, []
        for entity in sorted(entities, key=lambda item: item["entity_id"]):
            entity_id = entity["entity_id"]
            if not PATH_SAFE_RE.match(entity_id) or entity_id in {".", ".."}:
                unprojectable.append({"object_type": "entity", "canonical_id": entity_id,
                                      "reason": "IDENTIFIER_NOT_PATH_SAFE",
                                      "canonical_object_sha256": digest(entity)})
                continue
            artifacts[f"native/entities/{entity_id}.md"] = _entity_markdown(entity)
            native_id_by_canonical[entity_id] = entity_id

        lines: list[dict[str, Any]] = []
        transforms: list[dict[str, Any]] = []
        relation_rows: list[dict[str, Any]] = []
        for relation in sorted(relations, key=lambda item: item["relation_id"]):
            if relation["from_entity"] not in native_id_by_canonical or relation["to_entity"] not in native_id_by_canonical:
                unprojectable.append({"object_type": "relation", "canonical_id": relation["relation_id"],
                                      "reason": "ENDPOINT_NOT_PROJECTED",
                                      "canonical_object_sha256": digest(relation)})
                continue
            evidence = sorted({str(item) for item in (relation.get("sources") or [])})
            if not evidence:
                unprojectable.append({"object_type": "relation", "canonical_id": relation["relation_id"],
                                      "reason": "NATIVE_CONTRACT_REQUIRES_EVIDENCE",
                                      "canonical_object_sha256": digest(relation)})
                continue
            predicate = str(relation.get("predicate") or "")
            if not PREDICATE_RE.match(predicate):
                transforms.append({
                    "object_type": "relation", "canonical_id": relation["relation_id"],
                    "field": "predicate", "value_sent": predicate, "value_persisted": predicate,
                    "transformation": TRANSFORM_NONE, "contract_conforming": False,
                    "reason": "NATIVE_CONTRACT_REQUIRES_LOWERCASE_SNAKE_CASE",
                    "loss": "NONE_IN_CONTENT_BUT_NATIVE_CONTRACT_DEVIATION",
                })
            line = {
                "from": native_id_by_canonical[relation["from_entity"]],
                "relation": predicate,
                "label": str(relation.get("display_label") or relation.get("label") or predicate),
                "to": native_id_by_canonical[relation["to_entity"]],
                "evidence": evidence,
            }
            lines.append(line)
            relation_rows.append({"canonical_id": relation["relation_id"], "native_key": _native_key(line),
                                  "line": line, "losses": _losses_for(relation)})

        lines.sort(key=lambda item: (item["from"], item["relation"], item["to"]))
        # The native contract requires one line per (from, relation, to) triple with merged
        # evidence. Deduplicating here is what makes the many-to-one loss observable.
        deduped: list[dict[str, Any]] = []
        by_key: dict[str, dict[str, Any]] = {}
        for line in lines:
            key = _native_key(line)
            existing = by_key.get(key)
            if existing is None:
                by_key[key] = {"from": line["from"], "relation": line["relation"],
                               "label": line["label"], "to": line["to"],
                               "evidence": list(line["evidence"])}
                deduped.append(by_key[key])
                continue
            for uri in line["evidence"]:
                if uri not in existing["evidence"]:
                    existing["evidence"].append(uri)
            existing["evidence"].sort()
        lines = deduped
        grouped: dict[str, dict[str, Any]] = {}
        for row in relation_rows:
            entry = grouped.setdefault(row["native_key"], {"native_key": row["native_key"], "line": row["line"],
                                                          "canonical_ids": [], "losses": []})
            entry["canonical_ids"].append(row["canonical_id"])
            for loss in row["losses"]:
                if loss not in entry["losses"]:
                    entry["losses"].append(loss)
        collision_groups = [entry for entry in grouped.values() if len(entry["canonical_ids"]) > 1]

        # the native contract documents the key order; keep it stable and readable
        relations_jsonl = "".join(json.dumps(line, ensure_ascii=False, separators=(",", ":")) + "\n"
                                 for line in lines)
        artifacts["native/relations.jsonl"] = relations_jsonl

        artifact_hashes = {name: sha256_text(text) for name, text in sorted(artifacts.items())}
        manifest = {
            "schema_name": "KUYEN_NATIVE_PROJECTION",
            "schema_version": "1.0.0",
            "projector": {"name": "openviking-native-projector", "version": self.version, "policy": self.policy},
            "kuyen": {"kuyen_id": document["kuyen"]["kuyen_id"], "version": document["kuyen"]["version"],
                      "canonical_graph_hash": document["kuyen"]["canonical_graph_hash"]},
            "classification": "LOSSY_NATIVE_PROJECTION",
            "native_contract": {
                "artifact": "entities/<entity-id>.md + relations.jsonl",
                "relation_keys": list(NATIVE_RELATION_KEYS),
                "entity_keys": list(NATIVE_ENTITY_KEYS),
            },
            "artifacts": artifact_hashes,
            "counts": {
                "canonical_entities": len(entities),
                "native_entities": sum(1 for name in artifacts if name.startswith("native/entities/")),
                "canonical_relations": len(relations),
                "native_relation_lines": len(lines),
                "collision_groups": len(collision_groups),
                "collision_absorbed_relations": sum(len(group["canonical_ids"]) - 1 for group in collision_groups),
                "unprojectable_objects": len(unprojectable),
                "transformations": len(transforms),
            },
            "collision_groups": collision_groups,
            "transformations": transforms,
            "unprojectable": unprojectable,
            "unrepresented_canonical_fields": {
                "relation": list(LOSS_FIELDS),
                "assertion": ["*"],
                "evidence": ["*"],
                "source_unit": ["*"],
            },
            "projection_scope": {
                "represents": ["entity identity/name/type/description/aliases/sources", "relation endpoints", "relation label", "relation predicate literal", "source references as evidence strings"],
                "does_not_represent": ["relation identity", "polarity", "scope", "temporality", "evidence identity and offsets", "assertions", "SOURCE_UNIT", "predicate mapping layer"],
            },
        }
        manifest["projection_id"] = digest({key: value for key, value in manifest.items() if key != "projection_id"})
        return ProjectionResult(artifacts=artifacts, manifest=manifest)

    def materialize(self, document: dict[str, Any], root: str | Path) -> dict[str, str]:
        root = Path(root)
        result = self.project(document)
        written = {}
        for name, text in result.artifacts.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            written[name] = str(path)
        return written


def _native_key(line: dict[str, Any]) -> str:
    return f"{line['from']}|{line['relation']}|{line['to']}"


def _losses_for(relation: dict[str, Any]) -> list[str]:
    losses = []
    for name in LOSS_FIELDS:
        if relation.get(name) not in (None, "", [], {}):
            losses.append(name)
    return losses


def _yaml_scalar(value: str) -> str:
    text = str(value)
    if text == "" or text != text.strip() or any(ch in text for ch in ':#{}[],&*!|>"\'%@`'):
        return json.dumps(text, ensure_ascii=False)
    return text


def _entity_markdown(entity: dict[str, Any]) -> str:
    lines = ["---", "type: entity", f"id: {_yaml_scalar(entity['entity_id'])}",
             f"title: {_yaml_scalar(entity.get('name') or entity['entity_id'])}",
             f"entity_type: {_yaml_scalar(entity.get('entity_type') or 'thing')}",
             f"description: {_yaml_scalar(entity.get('description') or '')}"]
    aliases = sorted(entity.get("aliases") or [])
    if aliases:
        lines.append("aliases:")
        lines.extend(f"  - {_yaml_scalar(item)}" for item in aliases)
    else:
        lines.append("aliases: []")
    sources = sorted(str(item) for item in (entity.get("sources") or []))
    lines.append("sources:" if sources else "sources: []")
    lines.extend(f"  - {_yaml_scalar(item)}" for item in sources)
    lines.append("---")
    lines.append("")
    lines.append("## Overview")
    lines.append("")
    lines.append(str(entity.get("description") or "").strip() or f"{entity.get('name')}.")
    lines.append("")
    return "\n".join(lines)
