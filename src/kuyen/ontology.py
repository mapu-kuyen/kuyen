"""Versioned ontology loading and compatibility checks.

A profile may extend a base ontology. Composition is explicit, acyclic and
recorded in `lineage`; the base file is never modified. A profile only adds or
specializes terms for its own domain; it does not change the meaning of another
profile.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .errors import OntologyError


@dataclass(frozen=True)
class RelationSpec:
    predicate: str
    label: str
    from_types: tuple[str, ...]
    to_types: tuple[str, ...]
    directed: bool = True


@dataclass
class Ontology:
    profile: str
    version: str
    entity_types: dict[str, dict[str, Any]]
    relation_types: dict[str, RelationSpec]
    scalar_predicates: dict[str, dict[str, Any]] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)
    description: str = ""
    domain: str = ""
    extends: str | None = None
    lineage: tuple[str, ...] = ()
    source_path: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def version_id(self) -> str:
        return f"{self.profile}@{self.version}"

    def has_entity_type(self, value: str) -> bool:
        return value in self.entity_types

    def relation(self, value: str) -> RelationSpec | None:
        return self.relation_types.get(value)

    def accepts_direction(self, spec: RelationSpec, from_type: str, to_type: str) -> bool:
        if spec.from_types and from_type not in spec.from_types:
            return False
        if spec.to_types and to_type not in spec.to_types:
            return False
        return True

    def term_status(self, kind: str, value: str) -> str:
        if kind == "entity_type":
            return "NATIVE_PRESERVED" if self.has_entity_type(value) else "UNMAPPED_NATIVE"
        if kind == "predicate":
            return "NATIVE_PRESERVED" if self.relation(value) is not None else "UNMAPPED_NATIVE"
        raise ValueError(f"unsupported term kind: {kind}")

    @classmethod
    def load(cls, path: str | Path) -> "Ontology":
        return cls._load(Path(path), seen=())

    @classmethod
    def _load(cls, target: Path, *, seen: tuple[str, ...]) -> "Ontology":
        if not target.is_file():
            raise OntologyError(f"Ontology file not found: {target}")
        resolved = str(target.resolve())
        if resolved in seen:
            raise OntologyError(f"Ontology extends cycle: {' -> '.join([*seen, resolved])}")
        try:
            data = yaml.safe_load(target.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            raise OntologyError(f"Ontology YAML invalid: {exc}") from exc
        if not isinstance(data, dict):
            raise OntologyError("Ontology must be a mapping")
        profile = str(data.get("profile") or "")
        version = str(data.get("version") or "")
        if not profile or not version:
            raise OntologyError("Ontology requires profile and version")
        entity_types = data.get("entity_types") or {}
        relation_types = data.get("relation_types") or {}
        scalar_predicates = data.get("scalar_predicates") or {}
        if not isinstance(entity_types, dict) or not isinstance(relation_types, dict) or not isinstance(scalar_predicates, dict):
            raise OntologyError("entity_types, relation_types and scalar_predicates must be mappings")
        extends = data.get("extends")
        base: Ontology | None = None
        if extends:
            base_path = cls._resolve_extends(target, str(extends))
            base = cls._load(base_path, seen=(*seen, resolved))
        merged_entities = dict(base.entity_types) if base else {}
        merged_entities.update(entity_types)
        merged_relations = dict(base.relation_types) if base else {}
        merged_relations.update(_parse_relations(relation_types))
        merged_scalars = dict(base.scalar_predicates) if base else {}
        merged_scalars.update(scalar_predicates)
        metadata = {
            key: data[key] for key in (
                "status", "schema_compatibility", "origin", "evidence_policy",
                "known_native_limitations", "migration_rules",
            ) if key in data
        }
        return cls(
            profile=profile, version=version,
            entity_types=merged_entities, relation_types=merged_relations,
            scalar_predicates=merged_scalars, raw=dict(data),
            description=str(data.get("description") or ""),
            domain=str(data.get("domain") or ""),
            extends=str(extends) if extends else None,
            lineage=(*(base.lineage if base else ()), f"{profile}@{version}"),
            source_path=str(target),
            metadata=metadata,
        )

    @staticmethod
    def _resolve_extends(target: Path, extends: str) -> Path:
        raw = Path(extends)
        if raw.is_absolute():
            return raw
        if "/" in extends or extends.endswith((".yaml", ".yml")):
            return (target.parent / raw).resolve()
        candidate = target.parent / f"{extends}.yaml"
        if candidate.is_file():
            return candidate
        return (target.parent.parent / f"{extends}.yaml").resolve()


def _parse_relations(relation_types: dict[str, Any]) -> dict[str, RelationSpec]:
    parsed: dict[str, RelationSpec] = {}
    for name, spec in relation_types.items():
        if not isinstance(spec, dict):
            raise OntologyError(f"Relation {name} must be a mapping")
        parsed[str(name)] = RelationSpec(
            predicate=str(name),
            label=str(spec.get("label") or name),
            from_types=tuple(str(x) for x in (spec.get("from_types") or [])),
            to_types=tuple(str(x) for x in (spec.get("to_types") or [])),
            directed=bool(spec.get("directed", True)),
        )
    return parsed
