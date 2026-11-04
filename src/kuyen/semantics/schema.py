"""The schema a version carries, and the pure edits an Antü may perform on it.

KUYEN_DISTRIBUTED_ANTU_APPLICABILITY_12, §6 and §7. A KÜYEN publishes knowledge *and* the
structure that knowledge is expressed in, so "add the field RUT to Persona" is a real,
versioned change of the memory instead of a note about it:

* the schema of a version comes from the ontology profile the instance was created with;
* it is serialised inside the canonical document, so it is hashed with the version and
  travels with the history;
* `ADD_FIELD` / `UPDATE_FIELD` / `RETRACT_FIELD` produce a new schema; the transforms here are
  pure, so the previous schema is never mutated.

A field is a declared attribute of an entity type. It does not create values: declaring that
`person` may carry `rut` is a schema statement, and filling it in is `DATA_WRITE`.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Mapping

from ..canonical import digest
from ..errors import InvalidRequestError

SCHEMA_NAME = "KUYEN_GRAPH_SCHEMA"
SCHEMA_VERSION = "1.0.0"
FIELD_VALUE_TYPES = ("text", "integer", "number", "boolean", "date", "any")
DECLARED_BY_ONTOLOGY = "ONTOLOGY_PROFILE"
DECLARED_BY_ANTU = "ANTU_INSTRUCTION"


class SchemaError(InvalidRequestError):
    """The schema declaration or a schema edit cannot be read."""

    code = "GRAPH_SCHEMA_INVALID"


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def normalize_field_name(name: Any) -> str:
    """A field name is a stable identifier: lower snake case, no spaces, no accents."""
    raw = _text(name)
    if not raw:
        raise SchemaError("a field needs a name")
    cleaned = "".join(char if (char.isalnum() or char == "_") else "_" for char in raw.lower())
    cleaned = "_".join(part for part in cleaned.split("_") if part)
    if not cleaned:
        raise SchemaError(f"field name {raw!r} has no usable characters")
    if not cleaned[0].isalpha():
        cleaned = f"f_{cleaned}"
    return cleaned


def normalize_field(value: Mapping[str, Any] | str) -> dict[str, Any]:
    """Canonical form of a field declaration (`value_type` defaults to `text`)."""
    if isinstance(value, str):
        value = {"name": value}
    name = normalize_field_name(value.get("name") or value.get("field"))
    value_type = _text(value.get("value_type")) or "text"
    if value_type not in FIELD_VALUE_TYPES:
        raise SchemaError(f"unknown value_type {value_type!r} for field {name}")
    return {
        "name": name,
        "value_type": value_type,
        "required": bool(value.get("required", False)),
        "label": _text(value.get("label")),
        "description": _text(value.get("description")),
        "declared_by": _text(value.get("declared_by")) or DECLARED_BY_ANTU,
    }


@dataclass
class GraphSchema:
    """The structure of one version: entity types, their fields, predicates and relations."""

    profile: str
    profile_version: str
    entity_types: dict[str, dict[str, Any]] = field(default_factory=dict)
    scalar_predicates: dict[str, Any] = field(default_factory=dict)
    relation_types: dict[str, Any] = field(default_factory=dict)
    lineage: list[str] = field(default_factory=list)
    declared_by: str = DECLARED_BY_ONTOLOGY

    # ---------- construction ----------
    @classmethod
    def from_ontology(cls, ontology: Any) -> "GraphSchema":
        """The schema a KÜYEN is created with: its ontology profile, made explicit."""
        entity_types: dict[str, dict[str, Any]] = {}
        for name, spec in sorted((ontology.entity_types or {}).items()):
            spec = dict(spec or {})
            attributes = {}
            for field_name, field_spec in sorted((spec.get("attributes") or {}).items()):
                declared = normalize_field({**dict(field_spec or {}), "name": field_name})
                declared["declared_by"] = DECLARED_BY_ONTOLOGY
                attributes[declared["name"]] = declared
            entity_types[str(name)] = {
                "description": _text(spec.get("description")),
                "attributes": attributes,
            }
        relation_types = {
            str(name): {"label": spec.label, "from_types": list(spec.from_types),
                        "to_types": list(spec.to_types), "directed": bool(spec.directed)}
            for name, spec in sorted((ontology.relation_types or {}).items())
        }
        return cls(profile=str(ontology.profile), profile_version=str(ontology.version),
                   entity_types=entity_types,
                   scalar_predicates=copy.deepcopy(dict(ontology.scalar_predicates or {})),
                   relation_types=relation_types,
                   lineage=list(ontology.lineage or ()), declared_by=DECLARED_BY_ONTOLOGY)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | None) -> "GraphSchema | None":
        if value is None:
            return None
        if not isinstance(value, Mapping):
            raise SchemaError("the schema must be an object")
        unknown = sorted(set(value) - {"schema_name", "schema_version", "profile",
                                       "profile_version", "entity_types", "scalar_predicates",
                                       "relation_types", "lineage", "declared_by"})
        if unknown:
            raise SchemaError(f"unknown schema field: {unknown[0]}")
        profile = _text(value.get("profile")) or "unresolved"
        profile_version = _text(value.get("profile_version")) or "0.0.0"
        entity_types: dict[str, dict[str, Any]] = {}
        for name, spec in sorted((value.get("entity_types") or {}).items()):
            spec = dict(spec or {})
            attributes: dict[str, Any] = {}
            for field_name, field_spec in sorted((spec.get("attributes") or {}).items()):
                declared = normalize_field({**dict(field_spec or {}), "name": field_name})
                declared["declared_by"] = _text((field_spec or {}).get("declared_by")) \
                    or DECLARED_BY_ANTU
                attributes[declared["name"]] = declared
            entity_types[str(name)] = {"description": _text(spec.get("description")),
                                       "attributes": attributes}
        return cls(profile=profile, profile_version=profile_version,
                   entity_types=entity_types,
                   scalar_predicates=copy.deepcopy(dict(value.get("scalar_predicates") or {})),
                   relation_types=copy.deepcopy(dict(value.get("relation_types") or {})),
                   lineage=[str(item) for item in (value.get("lineage") or [])],
                   declared_by=_text(value.get("declared_by")) or DECLARED_BY_ONTOLOGY)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_name": SCHEMA_NAME, "schema_version": SCHEMA_VERSION,
            "profile": self.profile, "profile_version": self.profile_version,
            "declared_by": self.declared_by,
            "entity_types": copy.deepcopy(self.entity_types),
            "scalar_predicates": copy.deepcopy(self.scalar_predicates),
            "relation_types": copy.deepcopy(self.relation_types),
            "lineage": list(self.lineage),
        }

    def digest(self) -> str:
        return digest(self.to_dict())[:20]

    # ---------- queries ----------
    def has_entity_type(self, entity_type: Any) -> bool:
        return str(entity_type or "") in self.entity_types

    def type_names(self) -> list[str]:
        return sorted(self.entity_types)

    def fields_of(self, entity_type: Any) -> dict[str, dict[str, Any]]:
        return dict((self.entity_types.get(str(entity_type or "")) or {}).get("attributes") or {})

    def field(self, entity_type: Any, name: Any) -> dict[str, Any] | None:
        try:
            normalized = normalize_field_name(name)
        except SchemaError:
            return None
        return self.fields_of(entity_type).get(normalized)
    # ---------- pure transforms (the previous schema is never mutated) ----------
    def with_added_field(self, entity_type: str, declaration: Mapping[str, Any] | str, *,
                         antu_id: str | None = None) -> "GraphSchema":
        entity_type = str(entity_type or "").strip()
        if not self.has_entity_type(entity_type):
            raise SchemaError(f"entity type {entity_type!r} is not part of this schema")
        field_spec = normalize_field(
            {"name": declaration} if isinstance(declaration, str) else declaration)
        current = self.fields_of(entity_type)
        if field_spec["name"] in current:
            raise SchemaError(
                f"field {field_spec['name']!r} already exists on {entity_type!r}")
        field_spec["declared_by"] = DECLARED_BY_ANTU
        return self._with_fields(entity_type, {**current, field_spec["name"]: field_spec},
                                 antu_id=antu_id)

    def with_updated_field(self, entity_type: str, declaration: Mapping[str, Any] | str, *,
                           antu_id: str | None = None) -> "GraphSchema":
        entity_type = str(entity_type or "").strip()
        field_spec = normalize_field(
            {"name": declaration} if isinstance(declaration, str) else declaration)
        current = self.fields_of(entity_type)
        if field_spec["name"] not in current:
            raise SchemaError(f"field {field_spec['name']!r} does not exist on {entity_type!r}")
        merged = {**current[field_spec["name"]], **{key: value for key, value in field_spec.items()
                                                    if value is not None}}
        merged["declared_by"] = DECLARED_BY_ANTU
        return self._with_fields(entity_type, {**current, field_spec["name"]: merged},
                                 antu_id=antu_id)

    def with_removed_field(self, entity_type: str, name: Any, *,
                           antu_id: str | None = None) -> "GraphSchema":
        entity_type = str(entity_type or "").strip()
        normalized = normalize_field_name(name)
        current = self.fields_of(entity_type)
        if normalized not in current:
            raise SchemaError(f"field {normalized!r} does not exist on {entity_type!r}")
        remaining = {key: value for key, value in current.items() if key != normalized}
        return self._with_fields(entity_type, remaining, antu_id=antu_id)

    def _with_fields(self, entity_type: str, attributes: Mapping[str, Any], *,
                     antu_id: str | None) -> "GraphSchema":
        entity_types = copy.deepcopy(self.entity_types)
        entity_types[entity_type]["attributes"] = copy.deepcopy(dict(attributes))
        lineage = list(self.lineage)
        lineage.append(f"antu:{antu_id}" if antu_id else "antu:unspecified")
        return GraphSchema(profile=self.profile, profile_version=self.profile_version,
                           entity_types=entity_types,
                           scalar_predicates=copy.deepcopy(self.scalar_predicates),
                           relation_types=copy.deepcopy(self.relation_types),
                           lineage=lineage, declared_by=DECLARED_BY_ANTU)

    # ---------- views ----------
    def public_view(self) -> dict[str, Any]:
        """What a model may see of the schema: types, fields and their types. No data."""
        return {
            "schema_version": SCHEMA_VERSION,
            "profile": self.profile, "profile_version": self.profile_version,
            "entity_types": {
                name: {"description": spec.get("description"),
                       "fields": {field_name: {"value_type": field_spec.get("value_type"),
                                               "required": bool(field_spec.get("required")),
                                               "label": field_spec.get("label")}
                                  for field_name, field_spec in sorted(
                                      (spec.get("attributes") or {}).items())}}
                for name, spec in sorted(self.entity_types.items())
            },
            "scalar_predicates": sorted(self.scalar_predicates),
            "relation_types": sorted(self.relation_types),
        }

    def summary(self) -> dict[str, Any]:
        return {"profile": self.profile, "profile_version": self.profile_version,
                "entity_types": self.type_names(),
                "fields": {name: sorted(self.fields_of(name)) for name in self.type_names()},
                "declared_by": self.declared_by, "digest": self.digest(),
                "lineage": list(self.lineage)}
