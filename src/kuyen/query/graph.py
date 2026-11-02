"""Deterministic, read-only navigation over an accepted KÜYEN graph.

The API never mutates the graph, never invokes an LLM and never treats a display
name as an identity. A caller can inspect original/canonical/provider predicates,
evidence, temporal scope, epistemic state and identity-resolution state.
"""
from __future__ import annotations

import copy
from collections import deque
from typing import Any, Iterable, Mapping

from ..canonical import canonical_digest, normalized_name


class QueryContractError(ValueError):
    pass


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return list(value) if isinstance(value, (list, tuple, set)) else [value]


def _predicate(item: Mapping[str, Any], layer: str) -> str:
    if layer == "source":
        return str(item.get("source_predicate") or item.get("predicate") or "")
    if layer == "provider":
        return str(item.get("provider_predicate") or item.get("predicate") or "")
    return str(item.get("canonical_predicate") or item.get("predicate") or "")


class GraphQuery:
    def __init__(self, graph: Mapping[str, Any], *, authorized_namespaces: Iterable[str] | None = None) -> None:
        self._graph = copy.deepcopy(dict(graph))
        self._authorized = set(authorized_namespaces) if authorized_namespaces is not None else None
        self._validate()
        self._build_indexes()

    def _validate(self) -> None:
        for key in ("kuyen_id", "version", "entities", "relations", "assertions", "evidence"):
            if key not in self._graph:
                raise QueryContractError(f"graph is missing {key}")
        for key in ("entities", "relations", "assertions", "evidence"):
            if not isinstance(self._graph[key], list):
                raise QueryContractError(f"graph.{key} must be a list")

    def _allowed_entity(self, item: Mapping[str, Any]) -> bool:
        if self._authorized is None:
            return True
        namespace = str(item.get("source_namespace") or "")
        return not namespace or namespace in self._authorized

    def _relation_visible(self, item: Mapping[str, Any]) -> bool:
        if self._authorized is None:
            return True
        return self._entities.get(str(item.get("from_entity")), {}).get("source_namespace") in self._authorized \
            and self._entities.get(str(item.get("to_entity")), {}).get("source_namespace") in self._authorized

    def _build_indexes(self) -> None:
        self._entities = {str(item["entity_id"]): item for item in self._graph["entities"]}
        self._relations = {str(item["relation_id"]): item for item in self._graph["relations"]}
        self._assertions = {str(item["assertion_id"]): item for item in self._graph["assertions"]}
        self._evidence = {str(item["evidence_id"]): item for item in self._graph["evidence"]}
        self._entity_type: dict[str, list[str]] = {}
        self._namespace: dict[str, list[str]] = {}
        self._source_entity_id: dict[str, list[str]] = {}
        self._exact_name: dict[str, list[str]] = {}
        self._alias: dict[str, list[str]] = {}
        for entity in self._graph["entities"]:
            entity_id = str(entity["entity_id"])
            if not self._allowed_entity(entity):
                continue
            _append(self._entity_type, str(entity.get("entity_type") or ""), entity_id)
            _append(self._namespace, str(entity.get("source_namespace") or ""), entity_id)
            if entity.get("source_entity_id"):
                _append(self._source_entity_id, str(entity["source_entity_id"]), entity_id)
            _append(self._exact_name, str(entity.get("name") or ""), entity_id)
            for alias in _as_list(entity.get("aliases")):
                _append(self._alias, str(alias), entity_id)

        self._rel_from: dict[str, list[str]] = {}
        self._rel_to: dict[str, list[str]] = {}
        self._rel_predicate: dict[str, list[str]] = {}
        self._rel_source_predicate: dict[str, list[str]] = {}
        self._rel_canonical_predicate: dict[str, list[str]] = {}
        self._rel_provider_predicate: dict[str, list[str]] = {}
        self._rel_polarity: dict[str, list[str]] = {}
        self._rel_temporal: dict[str, list[str]] = {}
        self._rel_evidence: dict[str, list[str]] = {}
        for relation in self._graph["relations"]:
            relation_id = str(relation["relation_id"])
            if not self._relation_visible(relation):
                continue
            for index, value in (
                (self._rel_from, relation.get("from_entity")),
                (self._rel_to, relation.get("to_entity")),
                (self._rel_predicate, relation.get("predicate")),
                (self._rel_source_predicate, _predicate(relation, "source")),
                (self._rel_canonical_predicate, _predicate(relation, "canonical")),
                (self._rel_provider_predicate, _predicate(relation, "provider")),
                (self._rel_polarity, relation.get("polarity")),
                (self._rel_temporal, (relation.get("temporal") or {}).get("kind")),
            ):
                if value:
                    _append(index, str(value), relation_id)
            for evidence_id in _as_list(relation.get("evidence_ids")):
                _append(self._rel_evidence, str(evidence_id), relation_id)

        self._assertion_subject: dict[str, list[str]] = {}
        self._assertion_predicate: dict[str, list[str]] = {}
        self._assertion_temporal: dict[str, list[str]] = {}
        self._assertion_evidence: dict[str, list[str]] = {}
        for assertion in self._graph["assertions"]:
            assertion_id = str(assertion["assertion_id"])
            for index, value in (
                (self._assertion_subject, assertion.get("subject_entity")),
                (self._assertion_predicate, assertion.get("predicate")),
                (self._assertion_temporal, (assertion.get("temporal") or {}).get("kind")),
            ):
                if value:
                    _append(index, str(value), assertion_id)
            for evidence_id in _as_list(assertion.get("evidence_ids")):
                _append(self._assertion_evidence, str(evidence_id), assertion_id)

    # ---------- public read-only API ----------

    def get_entity(self, entity_id: str) -> dict[str, Any] | None:
        item = self._entities.get(entity_id)
        return copy.deepcopy(item) if item and self._allowed_entity(item) else None

    def find_entities(
        self, *, entity_type: str | None = None, namespace: str | None = None,
        exact_name: str | None = None, alias: str | None = None,
        source_entity_id: str | None = None, identity_status: str | None = None,
    ) -> list[dict[str, Any]]:
        if exact_name is not None:
            ids = self._exact_name.get(exact_name, [])
        elif alias is not None:
            ids = self._alias.get(alias, [])
        elif source_entity_id is not None:
            ids = self._source_entity_id.get(source_entity_id, [])
        elif entity_type is not None:
            ids = self._entity_type.get(entity_type, [])
        elif namespace is not None:
            ids = self._namespace.get(namespace, [])
        else:
            ids = list(self._entities)
        result = []
        for entity_id in ids:
            item = self._entities.get(entity_id)
            if item is None or not self._allowed_entity(item):
                continue
            if entity_type is not None and item.get("entity_type") != entity_type:
                continue
            if namespace is not None and item.get("source_namespace") != namespace:
                continue
            if exact_name is not None and item.get("name") != exact_name:
                continue
            if alias is not None and alias not in _as_list(item.get("aliases")):
                continue
            if source_entity_id is not None and item.get("source_entity_id") != source_entity_id:
                continue
            if identity_status is not None and item.get("identity_status") != identity_status:
                continue
            result.append(copy.deepcopy(item))
        return sorted(result, key=lambda x: x["entity_id"])

    def get_relations(
        self, *, from_entity: str | None = None, to_entity: str | None = None,
        predicate: str | None = None, polarity: str | None = None,
        source_predicate: str | None = None, canonical_predicate: str | None = None,
        provider_predicate: str | None = None, temporal_kind: str | None = None,
        semantic_status: str | None = None,
    ) -> list[dict[str, Any]]:
        if from_entity is not None:
            ids = self._rel_from.get(from_entity, [])
        elif to_entity is not None:
            ids = self._rel_to.get(to_entity, [])
        elif source_predicate is not None:
            ids = self._rel_source_predicate.get(source_predicate, [])
        elif canonical_predicate is not None:
            ids = self._rel_canonical_predicate.get(canonical_predicate, [])
        elif provider_predicate is not None:
            ids = self._rel_provider_predicate.get(provider_predicate, [])
        elif predicate is not None:
            ids = sorted(set(
                self._rel_predicate.get(predicate, [])
                + self._rel_source_predicate.get(predicate, [])
                + self._rel_canonical_predicate.get(predicate, [])
                + self._rel_provider_predicate.get(predicate, [])
            ))
        elif polarity is not None:
            ids = self._rel_polarity.get(polarity, [])
        elif temporal_kind is not None:
            ids = self._rel_temporal.get(temporal_kind, [])
        else:
            ids = list(self._relations)
        result = []
        for relation_id in ids:
            item = self._relations.get(relation_id)
            if item is None or not self._relation_visible(item):
                continue
            if from_entity is not None and item.get("from_entity") != from_entity:
                continue
            if to_entity is not None and item.get("to_entity") != to_entity:
                continue
            if predicate is not None and predicate not in {
                _predicate(item, "source"), _predicate(item, "canonical"), _predicate(item, "provider"),
            }:
                continue
            if source_predicate is not None and _predicate(item, "source") != source_predicate:
                continue
            if canonical_predicate is not None and _predicate(item, "canonical") != canonical_predicate:
                continue
            if provider_predicate is not None and _predicate(item, "provider") != provider_predicate:
                continue
            if polarity is not None and item.get("polarity") != polarity:
                continue
            if temporal_kind is not None and (item.get("temporal") or {}).get("kind") != temporal_kind:
                continue
            if semantic_status is not None and item.get("semantic_status") != semantic_status:
                continue
            result.append(copy.deepcopy(item))
        return sorted(result, key=lambda x: x["relation_id"])

    def get_assertions(
        self, *, subject: str | None = None, predicate: str | None = None,
        temporal_scope: str | None = None, temporal_kind: str | None = None,
        object_entity: str | None = None, semantic_status: str | None = None,
        polarity: str | None = None, status: str | None = None,
    ) -> list[dict[str, Any]]:
        if subject is not None:
            ids = self._assertion_subject.get(subject, [])
        elif predicate is not None:
            ids = self._assertion_predicate.get(predicate, [])
        elif temporal_kind is not None:
            ids = self._assertion_temporal.get(temporal_kind, [])
        else:
            ids = list(self._assertions)
        result = []
        for assertion_id in ids:
            item = self._assertions.get(assertion_id)
            if item is None:
                continue
            if subject is not None and item.get("subject_entity") != subject:
                continue
            if predicate is not None and item.get("predicate") != predicate:
                continue
            if temporal_scope is not None and item.get("temporal_scope") != temporal_scope:
                continue
            if temporal_kind is not None and (item.get("temporal") or {}).get("kind") != temporal_kind:
                continue
            if object_entity is not None and item.get("object_entity") != object_entity:
                continue
            if semantic_status is not None and item.get("semantic_status") != semantic_status:
                continue
            if polarity is not None and item.get("polarity") != polarity:
                continue
            if status is not None and item.get("status") != status:
                continue
            result.append(copy.deepcopy(item))
        return sorted(result, key=lambda x: x["assertion_id"])

    def get_evidence(
        self, *, entity_id: str | None = None, relation_id: str | None = None,
        assertion_id: str | None = None,
    ) -> list[dict[str, Any]]:
        refs: list[str] = []
        if entity_id is not None:
            refs = list((self._entities.get(entity_id) or {}).get("evidence_ids") or [])
        elif relation_id is not None:
            refs = list((self._relations.get(relation_id) or {}).get("evidence_ids") or [])
        elif assertion_id is not None:
            refs = list((self._assertions.get(assertion_id) or {}).get("evidence_ids") or [])
        return [copy.deepcopy(self._evidence[item]) for item in sorted(set(refs)) if item in self._evidence]

    def explain_claim(self, claim_id: str) -> dict[str, Any] | None:
        relation = self._relations.get(claim_id)
        assertion = self._assertions.get(claim_id)
        if relation is None and assertion is None:
            return None
        if relation is not None:
            kind = "relation"
            item = relation
            subject_id = relation.get("from_entity")
            object_id = relation.get("to_entity")
        else:
            kind = "assertion"
            item = assertion
            subject_id = assertion.get("subject_entity")
            object_id = assertion.get("object_entity")
        evidence = self.get_evidence(
            relation_id=claim_id if kind == "relation" else None,
            assertion_id=claim_id if kind == "assertion" else None,
        )
        return {
            "claim_id": claim_id,
            "claim_kind": kind,
            "claim": copy.deepcopy(item),
            "subject": self.get_entity(str(subject_id)) if subject_id else None,
            "object": self.get_entity(str(object_id)) if object_id else None,
            "source_predicate": _predicate(item, "source"),
            "canonical_predicate": _predicate(item, "canonical"),
            "provider_predicate": _predicate(item, "provider"),
            "temporal": copy.deepcopy(item.get("temporal")),
            "polarity": item.get("polarity"),
            "epistemic_status": item.get("status"),
            "semantic_status": item.get("semantic_status") or "NOT_ASSESSED",
            "support_method": item.get("support_method"),
            "evidence": evidence,
            "trace": {
                "mapu_ids": sorted({str(row.get("mapu_id")) for row in evidence}),
                "source_uris": sorted({str(row.get("source_uri")) for row in evidence}),
                "evidence_ids": [row["evidence_id"] for row in evidence],
            },
        }

    def traverse(
        self, start_entity_id: str, *, predicates: Iterable[str] | None = None, max_depth: int = 2,
    ) -> dict[str, Any]:
        if start_entity_id not in self._entities:
            raise QueryContractError(f"unknown start entity: {start_entity_id}")
        wanted = set(predicates or [])
        queue: deque[tuple[str, int]] = deque([(start_entity_id, 0)])
        visited = {start_entity_id}
        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []
        while queue:
            current, depth = queue.popleft()
            node = self.get_entity(current)
            if node is not None:
                nodes.append(node)
            if depth >= max_depth:
                continue
            for relation in self.get_relations(from_entity=current):
                if wanted and not ({_predicate(relation, "source"), _predicate(relation, "canonical"),
                                   _predicate(relation, "provider")} & wanted):
                    continue
                edges.append(copy.deepcopy(relation))
                target = str(relation.get("to_entity") or "")
                if target and target not in visited:
                    visited.add(target)
                    queue.append((target, depth + 1))
        return {
            "start_entity_id": start_entity_id,
            "max_depth": max_depth,
            "predicates": sorted(wanted),
            "nodes": sorted(nodes, key=lambda x: x["entity_id"]),
            "edges": sorted(edges, key=lambda x: x["relation_id"]),
            "node_count": len(nodes),
            "edge_count": len(edges),
        }

    def index_manifest(self) -> dict[str, Any]:
        payload = {
            "graph_digest": self._graph.get("content_digest") or canonical_digest(self._graph),
            "kuyen_id": self._graph.get("kuyen_id"),
            "version": self._graph.get("version"),
            "index_version": "kuyen-query-index-v1",
            "entity_count": len(self._entities),
            "relation_count": len(self._relations),
            "assertion_count": len(self._assertions),
            "evidence_count": len(self._evidence),
            "indexes": {
                "entity_id": len(self._entities),
                "entity_type": len(self._entity_type),
                "namespace": len(self._namespace),
                "source_entity_id": len(self._source_entity_id),
                "exact_name": len(self._exact_name),
                "alias": len(self._alias),
                "predicate": len(self._rel_predicate),
                "source_predicate": len(self._rel_source_predicate),
                "canonical_predicate": len(self._rel_canonical_predicate),
                "provider_predicate": len(self._rel_provider_predicate),
                "from_entity": len(self._rel_from),
                "to_entity": len(self._rel_to),
                "polarity": len(self._rel_polarity),
                "temporal_kind": len(self._rel_temporal),
                "assertion_subject": len(self._assertion_subject),
                "assertion_predicate": len(self._assertion_predicate),
                "assertion_temporal": len(self._assertion_temporal),
                "evidence_relation": len(self._rel_evidence),
                "evidence_assertion": len(self._assertion_evidence),
            },
        }
        payload["index_digest"] = canonical_digest(payload["indexes"])
        return payload


def _append(index: dict[str, list[str]], key: str, value: str) -> None:
    index.setdefault(key, []).append(value)
