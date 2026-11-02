"""Normalize provider candidates into KÜYEN's own canonical model.

The provider's entity IDs are not trusted as KÜYEN IDs. Relations are remapped
through a candidate-ID table, so an unknown endpoint remains visible to the
structural validator instead of being silently dropped.
"""
from __future__ import annotations

from typing import Any

from ..canonical import normalized_name, stable_id
from ..models import (
    Assertion,
    EpistemicStatus,
    CandidateBundle,
    CandidateEvidence,
    Entity,
    KuyenGraph,
    Mapu,
    Polarity,
    Relation,
    Value,
)


def _evidence_id(item: CandidateEvidence) -> str:
    return stable_id(
        "ev",
        {
            "mapu_id": item.mapu_id,
            "source_sha256": item.source_sha256,
            "source_uri": item.source_uri,
            "start": item.char_start,
            "end": item.char_end,
            "quote": item.quote,
        },
    )


def _entity_id(item) -> tuple[str, str]:
    if item.id:
        return (
            stable_id("ent", {"namespace": item.source_namespace, "source_id": item.id, "type": item.entity_type}),
            "source_id",
        )
    return stable_id("ent", {"type": item.entity_type, "name": normalized_name(item.name)}), "content"


def _relation_id(from_entity: str, predicate: str, to_entity: str, polarity: str, scope: str, temporal: str | None) -> str:
    return stable_id(
        "rel",
        {
            "from": from_entity,
            "predicate": predicate,
            "to": to_entity,
            "polarity": polarity,
            "scope": scope,
            "temporal": temporal,
        },
    )


def normalize_bundle(
    *,
    bundle: CandidateBundle,
    antu_id: str,
    mapus: list[Mapu],
    version: str,
    provenance: dict[str, Any],
) -> KuyenGraph:
    evidence_by_candidate: dict[str, CandidateEvidence] = {}
    evidence: list[CandidateEvidence] = []
    for item in bundle.evidence:
        candidate_id = item.evidence_id
        item.evidence_id = _evidence_id(item)
        evidence_by_candidate.setdefault(candidate_id, item)
        evidence_by_candidate.setdefault(item.evidence_id, item)
        evidence.append(item)

    # Candidate IDs are only relation keys. They are never exposed as KÜYEN IDs.
    candidate_to_entity: dict[str, str] = {}
    candidate_to_entities: dict[str, list[str]] = {}
    entities: list[Entity] = []
    for item in bundle.entities:
        entity_id, identity_basis = _entity_id(item)
        candidate_to_entity[f"{item.source_namespace}:{item.id}"] = entity_id
        if item.id:
            candidate_to_entities.setdefault(item.id, []).append(entity_id)
            if len(candidate_to_entities[item.id]) == 1:
                candidate_to_entity[item.id] = entity_id
            else:
                candidate_to_entity.pop(item.id, None)
        else:
            candidate_to_entities.setdefault(item.name, []).append(entity_id)
            if len(candidate_to_entities[item.name]) == 1:
                candidate_to_entity[item.name] = entity_id
            else:
                candidate_to_entity.pop(item.name, None)
        entity = Entity(
            entity_id=entity_id,
            entity_type=item.entity_type,
            name=item.name,
            aliases=list(dict.fromkeys(item.aliases)),
            description=item.description,
            evidence_ids=[
                evidence_by_candidate[x].evidence_id
                for x in item.evidence_refs
                if x in evidence_by_candidate
            ],
            sources=list(dict.fromkeys(item.sources)),
            source_entity_id=item.id or None,
            source_namespace=item.source_namespace,
            identity_basis=identity_basis,
            metadata={"candidate_id": item.id},
            origin_entity_id=item.id or None,
            canonical_entity_id=entity_id,
            identity_status="SAME_STABLE_ID" if item.id else "NOT_ASSESSED",
        )
        entities.append(entity)

    def resolve_endpoint(value: str) -> str | None:
        # Namespaced endpoints are exact; bare IDs are usable only when unique.
        return candidate_to_entity.get(value)

    relations: list[Relation] = []
    seen_relation_ids: set[str] = set()
    for item in bundle.relations:
        from_entity = resolve_endpoint(item.from_entity)
        to_entity = resolve_endpoint(item.to_entity)
        from_status = "RESOLVED" if from_entity else ("MISSING" if not item.from_entity else "UNRESOLVED")
        to_status = "RESOLVED" if to_entity else ("MISSING" if not item.to_entity else "UNRESOLVED")
        # Preserve the exact provider ID when unresolved; never use "".
        from_entity = from_entity or item.from_entity
        to_entity = to_entity or item.to_entity
        # The canonical predicate is the graph predicate. It is the preserved
        # native term when no ontology correspondence exists, so an UNMAPPED
        # relation keeps its meaning instead of collapsing into related_to.
        canonical_predicate = item.canonical_predicate or item.relation
        relation_id = _relation_id(
            from_entity, canonical_predicate, to_entity, item.polarity, item.scope, item.temporal_scope
        )
        seen_relation_ids.add(relation_id)
        relations.append(
            Relation(
                relation_id=relation_id,
                from_entity=from_entity,
                predicate=canonical_predicate,
                to_entity=to_entity,
                label=item.label,
                polarity=_polarity(item.polarity),
                scope=item.scope,
                temporal_scope=item.temporal_scope,
                temporal=item.temporal,
                evidence_ids=[
                    evidence_by_candidate[x].evidence_id
                    for x in item.evidence_refs
                    if x in evidence_by_candidate
                ],
                sources=list(dict.fromkeys(item.sources)),
                source_from_entity=item.from_entity,
                source_to_entity=item.to_entity,
                from_normalization_status=from_status,
                to_normalization_status=to_status,
                normalization_reason=(
                    "unknown provider endpoint" if from_status == "UNRESOLVED" or to_status == "UNRESOLVED"
                    else ("empty provider endpoint" if from_status == "MISSING" or to_status == "MISSING" else None)
                ),
                # The canonical predicate is authoritative for the graph. The
                # source predicate is only what the producer actually declared:
                # it is never back-filled from the carrier, because a missing
                # source predicate means unknown provenance, not an exact match.
                source_predicate=item.source_predicate,
                canonical_predicate=canonical_predicate,
                provider_predicate=item.provider_predicate or item.relation,
                display_label=item.display_label or item.label,
                provider_label=item.provider_label or item.label,
                source_label=item.label,
                mapping_status=item.mapping_status or "UNRESOLVED",
                mapping_rule_id=item.mapping_rule_id,
                mapping_version=item.mapping_version,
                provider_projection_status=item.provider_projection_status or "EXACT",
            )
        )

    assertions: list[Assertion] = []
    for item in bundle.assertions:
        subject = candidate_to_entity.get(item.subject, "")
        object_entity = (
            candidate_to_entity.get(item.object_entity or "", "")
            if item.object_entity
            else None
        )
        value = item.value
        if value is not None and not isinstance(value, Value):
            value = Value(value_type="string", value=value)
        assertion_id = stable_id(
            "asrt",
            {
                "subject": subject,
                "predicate": item.predicate,
                "object_entity": object_entity,
                "value": value.to_dict() if value else None,
                "polarity": item.polarity,
                "scope": item.scope,
                "temporal": item.temporal_scope,
            },
        )
        proposed = None
        proposed_raw = item.proposed_status
        if proposed_raw:
            try:
                proposed = EpistemicStatus(proposed_raw)
            except ValueError:
                proposed = None
        assertions.append(
            Assertion(
                assertion_id=assertion_id,
                subject_entity=subject,
                predicate=item.predicate,
                object_entity=object_entity,
                value=value,
                polarity=_polarity(item.polarity),
                scope=item.scope,
                temporal_scope=item.temporal_scope,
                temporal=item.temporal,
                evidence_ids=[
                    evidence_by_candidate[x].evidence_id
                    for x in item.evidence_refs
                    if x in evidence_by_candidate
                ],
                sources=list(dict.fromkeys(item.sources)),
                proposed_status=proposed,
                proposed_status_raw=proposed_raw,
            )
        )

    relation_key_to_id = {}
    for item, relation in zip(bundle.relations, relations):
        relation_key_to_id[
            (item.from_entity, item.relation, item.to_entity, item.polarity, item.scope, item.temporal_scope)
        ] = relation.relation_id
    coverage = []
    for unit in bundle.coverage:
        coverage.append(
            type(unit)(
                source_uri=unit.source_uri,
                mapu_id=unit.mapu_id,
                unit_id=unit.unit_id,
                state=unit.state,
                section=unit.section,
                content_sha256=unit.content_sha256,
                entity_ids=sorted({
                    entity_id for x in unit.entity_ids for entity_id in candidate_to_entities.get(x, [])
                }) if unit.entity_ids else [],
                relation_ids=sorted({
                    relation_key_to_id[key]
                    for key in relation_key_to_id
                    if key[0] in unit.entity_ids or key[2] in unit.entity_ids
                }),
                reason=unit.reason,
            )
        )

    entities.sort(key=lambda item: item.entity_id)
    relations.sort(key=lambda item: item.relation_id)
    assertions.sort(key=lambda item: item.assertion_id)
    evidence.sort(key=lambda item: item.evidence_id)
    coverage.sort(key=lambda item: (item.mapu_id, item.unit_id))

    graph_payload = {
        "antu_id": antu_id,
        "version": version,
        "mapu_ids": sorted(item.mapu_id for item in mapus),
        "entities": sorted((entity.to_dict() for entity in entities), key=lambda x: x["entity_id"]),
        "relations": sorted((relation.to_dict() for relation in relations), key=lambda x: x["relation_id"]),
        "assertions": sorted((assertion.to_dict() for assertion in assertions), key=lambda x: x["assertion_id"]),
        "evidence": sorted((item.to_dict() for item in evidence), key=lambda x: x["evidence_id"]),
        "coverage": sorted((item.to_dict() for item in coverage), key=lambda x: (x["mapu_id"], x["unit_id"])),
    }
    digest = stable_id("content", graph_payload).split("_", 1)[1]
    graph = KuyenGraph(
        kuyen_id=f"KUY-{digest[:12]}",
        version=version,
        antu_id=antu_id,
        mapu_ids=[item.mapu_id for item in mapus],
        entities=entities,
        relations=relations,
        assertions=assertions,
        evidence=evidence,
        coverage=coverage,
        provenance={**provenance, "candidate": bundle.raw.get("provenance", {})},
        content_digest=digest,
    )
    graph.provenance_digest = stable_id("provenance", graph.provenance).split("_", 1)[1]
    return graph


def _polarity(value: str) -> Polarity:
    try:
        return Polarity(value)
    except ValueError:
        return Polarity.POSITIVE
