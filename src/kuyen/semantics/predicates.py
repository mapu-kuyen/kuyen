"""Versioned predicate preservation and provider projection.

The canonical graph is authoritative. A provider may require a narrower or more
generic relation vocabulary; that projection must be explicit and must never
replace the source predicate in the canonical record.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from ..canonical import canonical_digest


class PredicateMappingStatus(str):
    EXACT = "EXACT"
    MAPPED = "MAPPED"
    UNMAPPED = "UNMAPPED"
    LOSSY_PROJECTION = "LOSSY_PROJECTION"
    UNRESOLVED = "UNRESOLVED"
    NOT_ASSESSED = "NOT_ASSESSED"


class ProviderProjectionStatus(str):
    EXACT = "EXACT"
    LOSSY_PROJECTION = "LOSSY_PROJECTION"
    NOT_PROJECTED = "NOT_PROJECTED"


VALID_MAPPING_STATUSES = frozenset({
    "EXACT", "MAPPED", "UNMAPPED", "LOSSY_PROJECTION", "UNRESOLVED", "NOT_ASSESSED",
})
VALID_PROJECTION_STATUSES = frozenset({"EXACT", "LOSSY_PROJECTION", "NOT_PROJECTED"})


@dataclass(frozen=True)
class PredicateMapping:
    rule_id: str
    version: str
    source_predicate: str
    canonical_predicate: str
    provider_predicate: str | None
    mapping_status: str
    provider_projection_status: str
    conditions: Mapping[str, Any] = field(default_factory=dict)
    justification: str = ""
    evidence: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PredicateMapping":
        return cls(
            rule_id=str(value["rule_id"]),
            version=str(value["version"]),
            source_predicate=str(value["source_predicate"]),
            canonical_predicate=str(value["canonical_predicate"]),
            provider_predicate=value.get("provider_predicate"),
            mapping_status=str(value.get("mapping_status") or "UNRESOLVED"),
            provider_projection_status=str(value.get("provider_projection_status") or "NOT_PROJECTED"),
            conditions=dict(value.get("conditions") or {}),
            justification=str(value.get("justification") or ""),
            evidence=tuple(str(item) for item in (value.get("evidence") or [])),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "version": self.version,
            "source_predicate": self.source_predicate,
            "canonical_predicate": self.canonical_predicate,
            "provider_predicate": self.provider_predicate,
            "mapping_status": self.mapping_status,
            "provider_projection_status": self.provider_projection_status,
            "conditions": dict(self.conditions),
            "justification": self.justification,
            "evidence": list(self.evidence),
        }

    def applies_to(self, *, source_predicate: str, source_relation_ref: str | None = None,
                   from_type: str | None = None, to_type: str | None = None) -> bool:
        if self.source_predicate not in {source_predicate, "*"}:
            return False
        if self.conditions.get("source_relation_ref") not in {None, source_relation_ref}:
            return False
        if self.conditions.get("from_type") not in {None, from_type}:
            return False
        if self.conditions.get("to_type") not in {None, to_type}:
            return False
        return True



LEGACY_GENERIC_RULE = "legacy-generic-unverified-v1"
LEGACY_NATIVE_RULE = "legacy-native-term-v1"
LEGACY_PROVIDER_RULE = "legacy-provider-term-v1"
PROVIDER_LAYER_RULE = "provider-predicate-layer-v1"
CARRIER_PREDICATE = "related_to"


DEFAULT_RULE_IDS = frozenset({"", "normalizer-exact-v1"})


def _declared_layer(relation: Any) -> bool:
    """True when the producer declared the predicate layer itself.

    The dataclass defaults (``normalizer-exact-v1``) are placeholders, not a
    declaration, so they never count as provenance.
    """
    rule = str(relation.mapping_rule_id or "")
    return bool(relation.source_predicate or relation.canonical_predicate
                or relation.provider_predicate
                or (rule and rule not in DEFAULT_RULE_IDS))


def annotate_predicate_provenance(bundle: Any, ontology: Any) -> dict[str, Any]:
    """Declare the three predicate dimensions before normalization.

    Deterministic policy, no invention:

    * provider declared the predicate layer -> it is copied; only derivable
      values are completed, and the derivation is named in ``mapping_rule_id``;
    * legacy payload (only ``from``/``relation``/``to``):
        - unknown term -> native term preserved, ``UNMAPPED``, lossy projection;
        - ontology term -> ``MAPPED`` (the source expression is unknown, so it is
          never claimed as ``EXACT`` provenance);
        - ``related_to`` -> ``UNRESOLVED``: a legacy generic term may be a
          fallback, and calling it ``EXACT`` would be the historical defect;
    * ontology term whose direction is incompatible with the entity types ->
      native term preserved, ``UNMAPPED`` and lossy projection (a visible
      warning, never an erased relation).
    """
    entities = {item.id: item for item in getattr(bundle, "entities", [])}
    counts = {"provider_layer": 0, "legacy": 0, "direction_incompatible": 0, "by_status": {}}
    for relation in getattr(bundle, "relations", []):
        spec = ontology.relation(relation.relation)
        source = entities.get(relation.from_entity)
        target = entities.get(relation.to_entity)
        direction_ok = bool(spec) and bool(source) and bool(target) and ontology.accepts_direction(
            spec, source.entity_type, target.entity_type)
        if _declared_layer(relation) and "+canonical-from-source" in str(relation.mapping_rule_id or ""):
            # Already normalized by this policy: never derive twice.
            counts["provider_layer"] += 1
            status = relation.mapping_status or "UNRESOLVED"
            counts["by_status"][status] = counts["by_status"].get(status, 0) + 1
            continue
        if _declared_layer(relation):
            counts["provider_layer"] += 1
            declared_canonical = relation.canonical_predicate
            declared_status = relation.mapping_status
            source = relation.source_predicate
            derived_canonical = False
            # A carrier canonical (`related_to`, or the carrier itself) cannot be
            # the canonical predicate when a specific source expression exists:
            # an UNMAPPED relation means "no ontology equivalent", not "generic".
            # The canonical is then taken from the declared source expression and
            # the derivation is named in the rule id.
            if source and source != CARRIER_PREDICATE and declared_canonical in {
                    None, relation.relation, CARRIER_PREDICATE}:
                canonical = source
                derived_canonical = True
                status = declared_status or "UNMAPPED"
                if status in {"EXACT", "MAPPED"}:
                    status = "UNMAPPED"
            else:
                canonical = declared_canonical or source or relation.relation
                status = declared_status or (
                    "EXACT" if canonical == relation.relation == source else "UNMAPPED")
            relation.canonical_predicate = canonical
            relation.source_predicate = source
            relation.mapping_status = status
            # The external projection only accepts ontology terms. A declared
            # provider predicate that the ontology does not have cannot be
            # projected, so the projection is the carrier and the loss is stated.
            declared_provider = relation.provider_predicate
            if declared_provider and ontology.relation(declared_provider) is not None:
                relation.provider_predicate = declared_provider
            else:
                relation.provider_predicate = (
                    canonical if ontology.relation(canonical) is not None else CARRIER_PREDICATE)
            relation.provider_projection_status = relation.provider_projection_status or (
                "EXACT" if relation.provider_predicate == canonical else "LOSSY_PROJECTION")
            if relation.provider_predicate != canonical and relation.provider_projection_status == "EXACT":
                relation.provider_projection_status = "LOSSY_PROJECTION"
            if canonical != relation.relation and relation.display_label:
                # The carrier label is meaningless for a preserved predicate.
                relation.label = relation.display_label
            base_rule = relation.mapping_rule_id or PROVIDER_LAYER_RULE
            relation.mapping_rule_id = f"{base_rule}+canonical-from-source" if derived_canonical else base_rule
            relation.mapping_version = relation.mapping_version or "1.0.0"
            relation.display_label = relation.display_label or relation.label
            relation.provider_label = relation.provider_label or relation.label
        else:
            counts["legacy"] += 1
            if relation.relation == CARRIER_PREDICATE:
                relation.source_predicate = None
                relation.canonical_predicate = CARRIER_PREDICATE
                relation.provider_predicate = CARRIER_PREDICATE
                relation.mapping_status = "UNRESOLVED"
                relation.mapping_rule_id = LEGACY_GENERIC_RULE
                relation.mapping_version = "1.0.0"
                relation.provider_projection_status = "EXACT"
            elif spec is None:
                # No declaration and no ontology term: provenance cannot be
                # established, so the contract does not claim preservation and
                # leaves the relation for the hard PREDICATE_NOT_ALLOWED check.
                status = relation.mapping_status or "UNRESOLVED"
                counts["undeclared_unknown"] = counts.get("undeclared_unknown", 0) + 1
                counts["by_status"][status] = counts["by_status"].get(status, 0) + 1
                continue
            elif not direction_ok:
                counts["direction_incompatible"] += 1
                relation.source_predicate = relation.relation
                relation.canonical_predicate = relation.relation
                relation.provider_predicate = CARRIER_PREDICATE
                relation.display_label = relation.display_label or relation.label
                relation.provider_label = relation.provider_label or "se relaciona con"
                relation.mapping_status = "UNMAPPED"
                relation.mapping_rule_id = "legacy-direction-preservation-v1"
                relation.mapping_version = "1.0.0"
                relation.provider_projection_status = "LOSSY_PROJECTION"
            else:
                relation.source_predicate = None
                relation.canonical_predicate = relation.relation
                relation.provider_predicate = relation.relation
                relation.mapping_status = "MAPPED"
                relation.mapping_rule_id = LEGACY_PROVIDER_RULE
                relation.mapping_version = "1.0.0"
                relation.provider_projection_status = "EXACT"
        status = relation.mapping_status or "UNRESOLVED"
        counts["by_status"][status] = counts["by_status"].get(status, 0) + 1
    return counts


class PredicateMappingRegistry:
    """Load and query an immutable, versioned rule set."""

    def __init__(self, *, contract: str, rules: Iterable[PredicateMapping],
                 metadata: Mapping[str, Any] | None = None) -> None:
        self.contract = contract
        self.rules = tuple(rules)
        self.metadata = dict(metadata or {})
        self._validate()

    @classmethod
    def load(cls, path: str | Path) -> "PredicateMappingRegistry":
        target = Path(path)
        data = json.loads(target.read_text(encoding="utf-8"))
        return cls(
            contract=str(data["contract"]),
            rules=[PredicateMapping.from_dict(item) for item in data["rules"]],
            metadata={"path": str(target), "sha256": _sha256(target), **dict(data.get("metadata") or {})},
        )

    def _validate(self) -> None:
        seen: set[str] = set()
        for rule in self.rules:
            if rule.rule_id in seen:
                raise ValueError(f"duplicate predicate mapping rule: {rule.rule_id}")
            seen.add(rule.rule_id)
            if rule.mapping_status not in VALID_MAPPING_STATUSES:
                raise ValueError(f"invalid mapping status: {rule.mapping_status}")
            if rule.provider_projection_status not in VALID_PROJECTION_STATUSES:
                raise ValueError(f"invalid projection status: {rule.provider_projection_status}")
            if rule.mapping_status == "EXACT" and rule.canonical_predicate != rule.source_predicate:
                raise ValueError(f"EXACT rule changes predicate: {rule.rule_id}")
            if rule.mapping_status == "UNMAPPED" and rule.canonical_predicate != rule.source_predicate:
                raise ValueError(f"UNMAPPED rule invents canonical predicate: {rule.rule_id}")

    def find(self, *, source_predicate: str, source_relation_ref: str | None = None,
             from_type: str | None = None, to_type: str | None = None) -> PredicateMapping | None:
        matches = [
            rule for rule in self.rules
            if rule.applies_to(
                source_predicate=source_predicate, source_relation_ref=source_relation_ref,
                from_type=from_type, to_type=to_type,
            )
        ]
        matches.sort(key=lambda item: (
            item.conditions.get("source_relation_ref") is not None,
            item.conditions.get("from_type") is not None,
            item.conditions.get("to_type") is not None,
            item.rule_id,
        ), reverse=True)
        return matches[0] if matches else None

    def coverage(self) -> dict[str, Any]:
        by_status: dict[str, int] = {}
        for rule in self.rules:
            by_status[rule.mapping_status] = by_status.get(rule.mapping_status, 0) + 1
        return {
            "contract": self.contract,
            "rule_count": len(self.rules),
            "by_status": dict(sorted(by_status.items())),
            "rules_digest": canonical_digest([rule.to_dict() for rule in self.rules]),
        }


def preserve_incompatible_relations(bundle: Any, ontology: Any) -> dict[str, int]:
    """Annotate direction-incompatible relations without rewriting their predicate.

    The canonical graph keeps the source predicate. Only the native provider
    projection is reduced to ``related_to`` and is explicitly marked lossy. The
    rule is generic, versioned and does not add ontology terms.

    Relations whose predicate layer was already declared (``mapping_rule_id`` or
    ``source_predicate`` present) are left untouched: their provenance is
    authoritative and must not be rewritten by a direction heuristic.
    """
    entities = {item.id: item for item in getattr(bundle, "entities", [])}
    changed = 0
    skipped = 0
    for relation in getattr(bundle, "relations", []):
        if _declared_layer(relation):
            skipped += 1
            continue
        source = entities.get(relation.from_entity)
        target = entities.get(relation.to_entity)
        spec = ontology.relation(relation.relation)
        if not source or not target or spec is None:
            continue
        if ontology.accepts_direction(spec, source.entity_type, target.entity_type):
            continue
        relation.source_predicate = relation.relation
        relation.canonical_predicate = relation.relation
        relation.provider_predicate = "related_to"
        relation.display_label = relation.label
        relation.provider_label = "se relaciona con"
        relation.mapping_status = "UNMAPPED"
        relation.mapping_rule_id = "direction-preservation-v1"
        relation.mapping_version = "1.0.0"
        relation.provider_projection_status = "LOSSY_PROJECTION"
        changed += 1
    return {"direction_incompatible_preserved": changed, "already_declared_skipped": skipped}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
