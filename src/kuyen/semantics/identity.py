"""Deterministic entity-identity proposals; never automatic merges.

The graph may contain several origin identities with the same display name. That
is a candidate, not proof of identity. A merge requires an explicit decision with
additional evidence (stable external ID, alias relation, or a reviewed rule).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping

from ..canonical import canonical_digest, normalized_name


class IdentityStatus(str):
    SAME_STABLE_ID = "SAME_STABLE_ID"
    POSSIBLE_DUPLICATE = "POSSIBLE_DUPLICATE"
    HOMONYM = "HOMONYM"
    ALIAS = "ALIAS"
    DISTINCT_ENTITY = "DISTINCT_ENTITY"
    UNRESOLVED_IDENTITY = "UNRESOLVED_IDENTITY"


class ResolutionStatus(str):
    PROPOSED = "PROPOSED"
    EVIDENCE_PENDING = "EVIDENCE_PENDING"
    CONFIRMED_SAME_ENTITY = "CONFIRMED_SAME_ENTITY"
    CONFIRMED_DISTINCT = "CONFIRMED_DISTINCT"
    REJECTED = "REJECTED"
    UNRESOLVED = "UNRESOLVED"


@dataclass(frozen=True)
class IdentityResolutionPolicy:
    policy_id: str = "identity-conservative-v1"
    version: str = "1.0.0"
    require_external_id_for_confirmation: bool = True
    allow_alias_confirmation: bool = True
    allow_name_only_merge: bool = False
    require_evidence_for_equivalence: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "version": self.version,
            "require_external_id_for_confirmation": self.require_external_id_for_confirmation,
            "allow_alias_confirmation": self.allow_alias_confirmation,
            "allow_name_only_merge": self.allow_name_only_merge,
            "require_evidence_for_equivalence": self.require_evidence_for_equivalence,
        }


@dataclass
class IdentityCandidate:
    candidate_id: str
    entity_id: str
    entity_type: str
    name: str
    normalized_name: str
    namespace: str
    source_entity_id: str | None
    aliases: list[str]
    unit_id: str | None = None
    section: str | None = None
    evidence_refs: list[str] = field(default_factory=list)
    incoming_relation_ids: list[str] = field(default_factory=list)
    outgoing_relation_ids: list[str] = field(default_factory=list)
    external_id: str | None = None
    match_signals: list[str] = field(default_factory=list)
    identity_status: str = IdentityStatus.UNRESOLVED_IDENTITY
    resolution_status: str = ResolutionStatus.UNRESOLVED
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "entity_id": self.entity_id,
            "entity_type": self.entity_type,
            "name": self.name,
            "normalized_name": self.normalized_name,
            "namespace": self.namespace,
            "source_entity_id": self.source_entity_id,
            "aliases": list(self.aliases),
            "unit_id": self.unit_id,
            "section": self.section,
            "evidence_refs": list(self.evidence_refs),
            "incoming_relation_ids": list(self.incoming_relation_ids),
            "outgoing_relation_ids": list(self.outgoing_relation_ids),
            "external_id": self.external_id,
            "match_signals": list(self.match_signals),
            "identity_status": self.identity_status,
            "resolution_status": self.resolution_status,
            "reason": self.reason,
        }


@dataclass
class IdentityGroup:
    group_id: str
    normalized_name: str
    entity_type: str
    candidates: list[IdentityCandidate]
    group_status: str
    resolution_status: str
    automatic_merges: int = 0
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "group_id": self.group_id,
            "normalized_name": self.normalized_name,
            "entity_type": self.entity_type,
            "group_status": self.group_status,
            "resolution_status": self.resolution_status,
            "automatic_merges": self.automatic_merges,
            "reason": self.reason,
            "candidates": [item.to_dict() for item in self.candidates],
            "pair_candidates": [
                {
                    "entity_a": left.entity_id,
                    "entity_b": right.entity_id,
                    "identity_similarity": "NAME_TYPE_EXACT",
                    "resolution_status": self.resolution_status,
                    "resolution_policy": "identity-conservative-v1",
                    "automatic_merge": False,
                }
                for index, left in enumerate(self.candidates)
                for right in self.candidates[index + 1:]
            ],
        }


@dataclass(frozen=True)
class IdentityDecision:
    decision_id: str
    group_id: str
    entity_ids: tuple[str, ...]
    status: str
    reason: str
    evidence_refs: tuple[str, ...] = ()
    policy_id: str = "identity-conservative-v1"
    policy_version: str = "1.0.0"
    automatic_merge: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "group_id": self.group_id,
            "entity_ids": list(self.entity_ids),
            "status": self.status,
            "reason": self.reason,
            "evidence_refs": list(self.evidence_refs),
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "automatic_merge": self.automatic_merge,
        }


def _external_id(entity: Mapping[str, Any]) -> str | None:
    metadata = entity.get("metadata") or {}
    for key in ("external_id", "wikidata_id", "stable_id"):
        if metadata.get(key):
            return str(metadata[key])
    return None


def classify_identity(
    left: IdentityCandidate,
    right: IdentityCandidate,
    *,
    policy: IdentityResolutionPolicy | None = None,
) -> tuple[str, str, str]:
    """Return (identity_status, resolution_status, reason) for one pair."""
    policy = policy or IdentityResolutionPolicy()
    if left.external_id and right.external_id:
        if left.external_id == right.external_id:
            return IdentityStatus.SAME_STABLE_ID, ResolutionStatus.CONFIRMED_SAME_ENTITY, "same external identifier"
        return IdentityStatus.DISTINCT_ENTITY, ResolutionStatus.CONFIRMED_DISTINCT, "different external identifiers"
    if left.source_entity_id and left.source_entity_id == right.source_entity_id and left.namespace == right.namespace:
        return IdentityStatus.SAME_STABLE_ID, ResolutionStatus.CONFIRMED_SAME_ENTITY, "same origin namespace and source ID"
    if policy.allow_alias_confirmation and left.normalized_name != right.normalized_name:
        left_aliases = {normalized_name(item) for item in [left.name, *left.aliases]}
        right_aliases = {normalized_name(item) for item in [right.name, *right.aliases]}
        if right.normalized_name in left_aliases or left.normalized_name in right_aliases:
            return IdentityStatus.ALIAS, ResolutionStatus.PROPOSED, "one name is present in the other's aliases"
    if policy.require_external_id_for_confirmation:
        return IdentityStatus.POSSIBLE_DUPLICATE, ResolutionStatus.UNRESOLVED, "same name and type; no stable external identifier"
    return IdentityStatus.POSSIBLE_DUPLICATE, ResolutionStatus.PROPOSED, "same name and type; policy allows proposal only"


def build_identity_groups(
    entities: Iterable[Mapping[str, Any]],
    *,
    relations: Iterable[Mapping[str, Any]] = (),
    unit_lookup: Callable[[int], str | None] | None = None,
    section_lookup: Callable[[str], str | None] | None = None,
    evidence_by_id: Mapping[str, Mapping[str, Any]] | None = None,
    policy: IdentityResolutionPolicy | None = None,
) -> list[IdentityGroup]:
    policy = policy or IdentityResolutionPolicy()
    evidence_by_id = evidence_by_id or {}
    relation_list = list(relations)
    entity_list = list(entities)
    by_name: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for entity in entity_list:
        key = (normalized_name(str(entity.get("name") or "")), str(entity.get("entity_type") or ""))
        by_name.setdefault(key, []).append(entity)

    groups: list[IdentityGroup] = []
    for (name_key, entity_type), members in sorted(by_name.items()):
        if len(members) < 2:
            continue
        candidates: list[IdentityCandidate] = []
        for entity in members:
            entity_id = str(entity.get("entity_id") or "")
            evidence_refs = [str(item) for item in (entity.get("evidence_ids") or [])]
            first_evidence = evidence_by_id.get(evidence_refs[0]) if evidence_refs else None
            unit_id = None
            if first_evidence and unit_lookup is not None:
                unit_id = unit_lookup(int(first_evidence.get("char_start", -1)))
            incoming = sorted(
                str(item.get("relation_id")) for item in relation_list
                if item.get("to_entity") == entity_id
            )
            outgoing = sorted(
                str(item.get("relation_id")) for item in relation_list
                if item.get("from_entity") == entity_id
            )
            candidates.append(IdentityCandidate(
                candidate_id=f"idc_{canonical_digest({'entity_id': entity_id, 'name': name_key, 'type': entity_type})[:20]}",
                entity_id=entity_id,
                entity_type=entity_type,
                name=str(entity.get("name") or ""),
                normalized_name=name_key,
                namespace=str(entity.get("source_namespace") or ""),
                source_entity_id=entity.get("source_entity_id"),
                aliases=[str(item) for item in (entity.get("aliases") or [])],
                unit_id=unit_id,
                section=section_lookup(unit_id) if unit_id and section_lookup else None,
                evidence_refs=evidence_refs,
                incoming_relation_ids=incoming,
                outgoing_relation_ids=outgoing,
                external_id=_external_id(entity),
            ))
        statuses: list[tuple[str, str, str]] = []
        for index, left in enumerate(candidates):
            for right in candidates[index + 1:]:
                statuses.append(classify_identity(left, right, policy=policy))
        if any(item[1] == ResolutionStatus.CONFIRMED_DISTINCT for item in statuses):
            group_status, resolution, reason = IdentityStatus.DISTINCT_ENTITY, ResolutionStatus.CONFIRMED_DISTINCT, "at least one pair has a confirmed distinct identifier"
        elif any(item[1] == ResolutionStatus.CONFIRMED_SAME_ENTITY for item in statuses):
            group_status, resolution, reason = IdentityStatus.SAME_STABLE_ID, ResolutionStatus.CONFIRMED_SAME_ENTITY, "at least one pair has a stable shared identifier"
        elif any(item[0] == IdentityStatus.ALIAS for item in statuses):
            group_status, resolution, reason = IdentityStatus.ALIAS, ResolutionStatus.PROPOSED, "alias relation present but not confirmed"
        else:
            group_status, resolution, reason = IdentityStatus.POSSIBLE_DUPLICATE, ResolutionStatus.UNRESOLVED, "same name and type; no confirming evidence"
        for candidate in candidates:
            candidate.identity_status = group_status
            candidate.resolution_status = resolution
            candidate.reason = reason
        group_id = f"idg_{canonical_digest({'name': name_key, 'type': entity_type})[:20]}"
        groups.append(IdentityGroup(
            group_id=group_id,
            normalized_name=name_key,
            entity_type=entity_type,
            candidates=candidates,
            group_status=group_status,
            resolution_status=resolution,
            automatic_merges=0,
            reason=reason,
        ))
    return groups
