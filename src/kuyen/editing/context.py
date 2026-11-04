"""Deterministic context retrieval for a graph edit (§6.1).

The model never receives the store, a path or a credential: it receives a *view* of one
version of the graph built deterministically from the instruction. Two modes:

* `FULL_INDEX` — the graph is small enough to send complete, so nothing relevant can be
  missing;
* `KEYWORD_SELECTION` — the graph is large, so the objects that share keywords with the
  instruction are selected, their one-hop neighbours are added, and the selection reports
  exactly what it left out.

Whatever the mode, the returned `authorized_ids` is the operational scope of the edit: an
operation that targets an object outside it is refused as `TARGET_NOT_IN_CONTEXT`, even
when the object exists in the graph.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from ..semantics.scope import AntuScope
from ..semantics.schema import GraphSchema

SMALL_GRAPH_OBJECT_LIMIT = 200
_KEYWORD = re.compile(r"[0-9A-Za-zÁÉÍÓÚÜÑáéíóúüñ_]{4,}")
_STOPWORDS = frozenset({
    "para", "como", "este", "esta", "esto", "esos", "esas", "desde", "hasta", "entre",
    "sobre", "según", "segun", "cuando", "donde", "porque", "aunque", "también", "tambien",
    "debe", "deben", "debería", "deberia", "cambia", "cambiar", "corrige", "corregir",
    "agrega", "agregar", "añade", "anade", "anadir", "añadir", "retira", "retirar",
    "actualiza", "actualizar", "modifica", "modificar", "quiero", "necesito", "favor",
    "with", "that", "this", "from", "into", "should", "change", "update", "please",
})


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", str(text))
    return "".join(char for char in decomposed if not unicodedata.combining(char)).casefold()


def keywords(text: str) -> list[str]:
    """Deterministic keyword list of an instruction (accent-insensitive, no stopwords)."""
    seen: list[str] = []
    for match in _KEYWORD.finditer(_normalize(text)):
        token = match.group(0)
        if token in _STOPWORDS or token in seen:
            continue
        seen.append(token)
    return seen


@dataclass
class EditContext:
    version_id: str
    kuyen_id: str
    kuyen_version: str
    entities: list[dict[str, Any]] = field(default_factory=list)
    relations: list[dict[str, Any]] = field(default_factory=list)
    assertions: list[dict[str, Any]] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    mapu_ids: list[str] = field(default_factory=list)
    authorized_ids: dict[str, list[str]] = field(default_factory=dict)
    selection: dict[str, Any] = field(default_factory=dict)
    # §3/§4: the schema the model may see and the permissions it works under. Both are
    # filtered by the scope before the payload exists; nothing outside it is serialised.
    schema: dict[str, Any] | None = None
    capabilities: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        """The exact JSON object handed to the model: canonical ids, nothing invented."""
        payload: dict[str, Any] = {
            "version": {"version_id": self.version_id, "kuyen_id": self.kuyen_id,
                        "kuyen_version": self.kuyen_version},
            "mapu_ids": list(self.mapu_ids),
            "objects": {
                "entities": self.entities, "relations": self.relations,
                "assertions": self.assertions, "evidence": self.evidence,
            },
            "selection": dict(self.selection),
        }
        if self.schema is not None:
            payload["schema"] = self.schema
        if self.capabilities:
            payload["capabilities"] = dict(self.capabilities)
        return payload

    def is_authorized(self, identifier: str) -> bool:
        return any(identifier in ids for ids in self.authorized_ids.values())

    def kind_of(self, identifier: str) -> str | None:
        for kind, ids in self.authorized_ids.items():
            if identifier in ids:
                return kind
        return None


def _entity_text(entity: Mapping[str, Any]) -> str:
    return " ".join([
        str(entity.get("name") or ""), str(entity.get("entity_type") or ""),
        " ".join(str(x) for x in (entity.get("aliases") or [])),
        str(entity.get("description") or ""),
    ])


def _relation_text(relation: Mapping[str, Any]) -> str:
    return " ".join([
        str(relation.get("predicate") or ""), str(relation.get("label") or ""),
        str(relation.get("source_label") or ""), str(relation.get("canonical_predicate") or ""),
        str(relation.get("temporal_scope") or ""),
    ])


def _assertion_text(assertion: Mapping[str, Any]) -> str:
    value = assertion.get("value") or {}
    return " ".join([
        str(assertion.get("predicate") or ""),
        str(value.get("value")) if isinstance(value, Mapping) else "",
        str(value.get("unit")) if isinstance(value, Mapping) else "",
        str(value.get("context")) if isinstance(value, Mapping) else "",
        str(assertion.get("temporal_scope") or ""), str(assertion.get("attribution") or ""),
        str(assertion.get("support_rationale") or ""),
    ])


def _matches(text: str, tokens: Iterable[str]) -> bool:
    normalized = _normalize(text)
    return any(token in normalized for token in tokens)



def build_context(graph: Mapping[str, Any], instruction: str, *,
                  version_id: str, object_limit: int = SMALL_GRAPH_OBJECT_LIMIT,
                  scope: Any = None, schema: Mapping[str, Any] | None = None) -> EditContext:
    """Build the deterministic edit context of one graph version.

    The scope decides what exists for this Antü (§4): without `DATA_READ` no object of the
    graph is read at all — not filtered afterwards, never read — and without `SCHEMA_READ`
    the schema is not serialised. The payload is therefore incapable of carrying what this
    KÜYEN does not authorise, whatever the model later asks for.
    """
    scope = AntuScope.from_dict(scope)
    data_visible = scope.data_read
    entities = [dict(item) for item in (graph.get("entities") or [])] if data_visible else []
    relations = [dict(item) for item in (graph.get("relations") or [])] if data_visible else []
    assertions = [dict(item) for item in (graph.get("assertions") or [])] if data_visible else []
    evidence = ({str(item.get("evidence_id")): dict(item)
                 for item in (graph.get("evidence") or [])} if data_visible else {})
    total = len(entities) + len(relations) + len(assertions)
    tokens = keywords(instruction)

    if total <= object_limit:
        selected_entities = list(entities)
        selected_relations = list(relations)
        selected_assertions = list(assertions)
        mode = "FULL_INDEX"
    else:
        selected_entities = [item for item in entities if _matches(_entity_text(item), tokens)]
        selected_assertions = [item for item in assertions if _matches(_assertion_text(item), tokens)]
        selected_relations = [item for item in relations if _matches(_relation_text(item), tokens)]
        # One-hop closure around the selected entities: a relation or an assertion that
        # speaks about them is relevant even when its own wording does not match.
        entity_ids = {str(item.get("entity_id")) for item in selected_entities}
        for relation in relations:
            if relation.get("from_entity") in entity_ids or relation.get("to_entity") in entity_ids:
                if relation not in selected_relations:
                    selected_relations.append(relation)
        for assertion in assertions:
            if assertion.get("subject_entity") in entity_ids or assertion.get("object_entity") in entity_ids:
                if assertion not in selected_assertions:
                    selected_assertions.append(assertion)
        # Endpoints and subjects of everything selected must be present as entities.
        wanted: set[Any] = set()
        for relation in selected_relations:
            wanted.add(relation.get("from_entity"))
            wanted.add(relation.get("to_entity"))
        for assertion in selected_assertions:
            wanted.add(assertion.get("subject_entity"))
            if assertion.get("object_entity"):
                wanted.add(assertion.get("object_entity"))
        present = {str(item.get("entity_id")) for item in selected_entities}
        for entity in entities:
            if entity.get("entity_id") in wanted and entity.get("entity_id") not in present:
                selected_entities.append(entity)
        mode = "KEYWORD_SELECTION"

    selected_entities.sort(key=lambda item: str(item.get("entity_id")))
    selected_relations.sort(key=lambda item: str(item.get("relation_id")))
    selected_assertions.sort(key=lambda item: str(item.get("assertion_id")))

    referenced: set[str] = set()
    for group in (selected_entities, selected_relations, selected_assertions):
        for item in group:
            for identifier in item.get("evidence_ids") or []:
                referenced.add(str(identifier))
    selected_evidence = [evidence[identifier] for identifier in sorted(referenced)
                         if identifier in evidence]

    authorized = {
        "entity": [str(item.get("entity_id")) for item in selected_entities],
        "relation": [str(item.get("relation_id")) for item in selected_relations],
        "assertion": [str(item.get("assertion_id")) for item in selected_assertions],
        "evidence": [str(item.get("evidence_id")) for item in selected_evidence],
    }
    selection = {
        "mode": mode if data_visible else "DATA_WITHHELD",
        "object_limit": object_limit,
        "total_objects": total if data_visible else None,
        "included": {"entities": len(selected_entities), "relations": len(selected_relations),
                     "assertions": len(selected_assertions), "evidence": len(selected_evidence)},
        "excluded": {"entities": len(entities) - len(selected_entities),
                     "relations": len(relations) - len(selected_relations),
                     "assertions": len(assertions) - len(selected_assertions)},
        "truncated": mode != "FULL_INDEX" and (
            len(selected_entities) < len(entities)
            or len(selected_relations) < len(relations)
            or len(selected_assertions) < len(assertions)),
        "keywords": tokens,
        "note": ("objects outside `authorized_ids` are not part of this edit and an operation "
                 "targeting them is refused"),
    }
    if not data_visible:
        selection["data_withheld"] = {"reason": "DATA_READ is not granted to this Antü",
                                      "granted": list(scope.granted())}
    selection["scope"] = scope.public_dict()
    visible_schema = None
    if scope.schema_read:
        candidate_schema = schema if schema is not None else graph.get("schema")
        if candidate_schema is not None:
            visible_schema = GraphSchema.from_dict(candidate_schema).public_view()
    return EditContext(
        version_id=version_id, kuyen_id=str(graph.get("kuyen_id") or ""),
        kuyen_version=str(graph.get("version") or ""),
        entities=selected_entities, relations=selected_relations,
        assertions=selected_assertions, evidence=selected_evidence,
        schema=visible_schema, capabilities=scope.context_capabilities(),
        mapu_ids=[str(item) for item in (graph.get("mapu_ids") or [])],
        authorized_ids=authorized, selection=selection,
    )
