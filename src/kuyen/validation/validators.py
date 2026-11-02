"""Deterministic validation. No LLM, network or hidden normalization."""
from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any

from ..models import (
    Antu,
    CoverageState,
    EpistemicStatus,
    KuyenGraph,
    Mapu,
    ValidationIssue,
    ValidationReport,
)
from ..ontology import Ontology


SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def issue(code: str, message: str, path: str = "", severity: str = "ERROR", evidence: str | None = None) -> ValidationIssue:
    return ValidationIssue(code=code, message=message, path=path, severity=severity, evidence=evidence)


class RequestValidator:
    def validate(self, antu: Antu, mapus: list[Mapu], ontology: Ontology) -> list[ValidationIssue]:
        errors: list[ValidationIssue] = []
        if not ID_RE.match(antu.antu_id):
            errors.append(issue("ANTU_ID_INVALID", "antu_id is not a stable identifier", "antu_id"))
        if not SEMVER.match(antu.version):
            errors.append(issue("ANTU_VERSION_INVALID", "Antü version must be semver", "version"))
        if not antu.purpose.strip():
            errors.append(issue("ANTU_PURPOSE_EMPTY", "purpose is required", "purpose"))
        if not antu.include_scope:
            errors.append(issue("ANTU_SCOPE_EMPTY", "positive scope is required", "scope.include"))
        if set(antu.include_scope) & set(antu.exclude_scope):
            errors.append(issue("ANTU_SCOPE_OVERLAP", "include and exclude scopes overlap", "scope"))
        if antu.ontology_profile != ontology.profile:
            errors.append(issue("ONTOLOGY_PROFILE_MISMATCH", f"expected {ontology.profile}", "ontology_profile"))
        if antu.coverage_policy not in {"complete", "require_terminal", "complete_with_reasons", "not_required"}:
            errors.append(issue("COVERAGE_POLICY_INVALID", antu.coverage_policy, "coverage_policy"))
        if antu.evidence_policy not in {"strict", "document"}:
            errors.append(issue("EVIDENCE_POLICY_INVALID", antu.evidence_policy, "evidence_policy"))
        if antu.scalar_policy not in {"literal", "allow_entities"}:
            errors.append(issue("SCALAR_POLICY_INVALID", antu.scalar_policy, "scalar_policy"))
        if antu.conflict_policy not in {"preserve_unresolved", "reject_conflict"}:
            errors.append(issue("CONFLICT_POLICY_INVALID", antu.conflict_policy, "conflict_policy"))
        if antu.output_profile != "kuyen-native-v1":
            errors.append(issue("OUTPUT_PROFILE_UNSUPPORTED", antu.output_profile, "output_profile"))
        if antu.schema_version not in {"1.0.0", "1.1.0"}:
            errors.append(issue("ANTU_SCHEMA_VERSION_UNSUPPORTED", antu.schema_version, "schema_version"))
        if antu.unresolved_policy not in {"allow", "reject"}:
            errors.append(issue("UNRESOLVED_POLICY_INVALID", antu.unresolved_policy, "unresolved_policy"))
        unknown_types = [x for x in antu.entity_types if x not in ontology.entity_types]
        if unknown_types:
            errors.append(issue("ENTITY_TYPE_UNKNOWN", ",".join(unknown_types), "entity_types"))
        unknown_relations = [x for x in antu.relation_types if x not in ontology.relation_types]
        if unknown_relations:
            errors.append(issue("RELATION_TYPE_UNKNOWN", ",".join(unknown_relations), "relation_types"))
        if not mapus:
            errors.append(issue("MAPU_MISSING", "at least one MAPU is required", "mapu_sources"))
        ids = Counter(item.mapu_id for item in mapus)
        for mapu_id, count in ids.items():
            if count > 1:
                errors.append(issue("MAPU_DUPLICATE", mapu_id, "mapu_sources"))
        for mapu in mapus:
            if not re.fullmatch(r"MAPU-[A-Za-z0-9._-]+", mapu.mapu_id):
                errors.append(issue("MAPU_ID_INVALID", mapu.mapu_id, "mapu_sources"))
            try:
                mapu.verify()
            except ValueError as exc:
                errors.append(issue("MAPU_INVALID", str(exc), f"mapu:{mapu.mapu_id}"))
            if not mapu.content.strip():
                errors.append(issue("MAPU_CONTENT_EMPTY", mapu.mapu_id, f"mapu:{mapu.mapu_id}"))
            if len(mapu.sha256) != 64 or not re.fullmatch(r"[a-f0-9]{64}", mapu.sha256):
                errors.append(issue("MAPU_HASH_FORMAT", mapu.mapu_id, f"mapu:{mapu.mapu_id}"))
        return errors


class OntologyValidator:
    def validate(self, graph: KuyenGraph, antu: Antu, ontology: Ontology) -> list[ValidationIssue]:
        errors: list[ValidationIssue] = []
        allowed_entities = set(antu.entity_types) or set(ontology.entity_types)
        allowed_relations = set(antu.relation_types) or set(ontology.relation_types)
        entity_by_id = {item.entity_id: item for item in graph.entities}
        labels: dict[str, set[str]] = {}
        for entity in graph.entities:
            if entity.entity_type not in allowed_entities:
                errors.append(issue("ENTITY_TYPE_NOT_ALLOWED", entity.entity_type, f"entity:{entity.entity_id}"))
            if entity.entity_type in {"quantity_value", "temporal_value"} and antu.scalar_policy == "literal":
                errors.append(issue("SCALAR_ENTITY_NOT_ALLOWED", "scalars must remain values", f"entity:{entity.entity_id}"))
        valid_mapping_statuses = {
            "EXACT", "MAPPED", "UNMAPPED", "LOSSY_PROJECTION", "UNRESOLVED", "NOT_ASSESSED",
        }
        for relation in graph.relations:
            spec = ontology.relation(relation.predicate)
            status = str(relation.mapping_status or "UNRESOLVED")
            # A preserved native predicate is a valid relation: its meaning was
            # declared by the producer, the ontology simply has no equivalent
            # term. It is accepted only with an explicit correspondence state and
            # recorded provenance; anything else keeps the hard error.
            preserved_native = (
                spec is None
                and status in {"UNMAPPED", "UNRESOLVED"}
                and bool(relation.source_predicate or relation.mapping_rule_id)
            )
            if spec is None or relation.predicate not in allowed_relations:
                if preserved_native:
                    errors.append(issue(
                        "NATIVE_PREDICATE_PRESERVED_UNMAPPED",
                        relation.predicate,
                        f"relation:{relation.relation_id}",
                        severity="WARNING",
                        evidence=(f"mapping_status={status} "
                                  f"rule={relation.mapping_rule_id} "
                                  f"source_predicate={relation.source_predicate or '<unknown>'}"),
                    ))
                    if status not in valid_mapping_statuses:
                        errors.append(issue(
                            "PREDICATE_MAPPING_STATUS_INVALID", relation.mapping_status,
                            f"relation:{relation.relation_id}",
                        ))
                    labels.setdefault(relation.predicate, set()).add(relation.label)
                    continue
                errors.append(issue("PREDICATE_NOT_ALLOWED", relation.predicate, f"relation:{relation.relation_id}"))
                continue
            if status not in valid_mapping_statuses:
                errors.append(issue(
                    "PREDICATE_MAPPING_STATUS_INVALID", relation.mapping_status,
                    f"relation:{relation.relation_id}",
                ))
            labels.setdefault(relation.predicate, set()).add(relation.label)
            source = entity_by_id.get(relation.from_entity)
            target = entity_by_id.get(relation.to_entity)
            if source and target and not ontology.accepts_direction(spec, source.entity_type, target.entity_type):
                # An unmapped native predicate is preserved verbatim. Its domain
                # and range are not silently retyped, so the incompatibility is a
                # visible warning rather than a reason to erase the relation.
                if str(relation.mapping_status or "") in {"UNMAPPED", "UNRESOLVED", "LOSSY_PROJECTION"}:
                    errors.append(issue(
                        "RELATION_TYPE_PRESERVED_UNMAPPED",
                        f"{source.entity_type}->{target.entity_type}",
                        f"relation:{relation.relation_id}",
                        severity="WARNING",
                        evidence=f"source_predicate={relation.source_predicate or relation.predicate}",
                    ))
                else:
                    errors.append(issue("RELATION_TYPE_INCOMPATIBLE", f"{source.entity_type}->{target.entity_type}", f"relation:{relation.relation_id}"))
        for predicate, values in labels.items():
            if len(values) > 1:
                errors.append(issue("INCONSISTENT_LABEL", predicate, f"relation:{predicate}"))
        for assertion in graph.assertions:
            if assertion.object_entity is not None:
                spec = ontology.relation(assertion.predicate)
                if spec is None:
                    errors.append(issue("ASSERTION_PREDICATE_UNKNOWN", assertion.predicate, f"assertion:{assertion.assertion_id}"))
                continue
            spec = ontology.scalar_predicates.get(assertion.predicate)
            if spec is None:
                errors.append(issue("SCALAR_PREDICATE_UNKNOWN", assertion.predicate, f"assertion:{assertion.assertion_id}"))
            elif assertion.value is not None:
                allowed = set(spec.get("value_types") or [])
                if allowed and assertion.value.value_type not in allowed:
                    errors.append(issue("SCALAR_VALUE_TYPE_INCOMPATIBLE", assertion.value.value_type, f"assertion:{assertion.assertion_id}"))
        groups: dict[tuple[Any, ...], list[Any]] = {}
        for assertion in graph.assertions:
            key = (assertion.subject_entity, assertion.predicate, assertion.polarity.value, assertion.scope, assertion.temporal_scope)
            groups.setdefault(key, []).append(assertion)
        for key, items in groups.items():
            values = {
                (item.object_entity, json.dumps(item.value.to_dict(), sort_keys=True) if item.value else None)
                for item in items
            }
            if len(values) > 1:
                if antu.conflict_policy == "reject_conflict":
                    errors.append(issue("CONFLICT_DETECTED", str(key), f"assertion:{key[1]}"))
                elif key[1] == "has_value":
                    # The generic scalar predicate can carry different
                    # attributes of the same subject. Different values are a
                    # preservation signal, not proof of contradiction.
                    errors.append(issue(
                        "CONFLICT_PRESERVED_UNASSESSED", str(key), f"assertion:{key[1]}",
                        severity="WARNING",
                        evidence=f"{len(values)} distinct values retained",
                    ))
                else:
                    # A specific scalar predicate with the same subject, scope
                    # and temporal scope and different values is a structural
                    # contradiction; the conflicting values are preserved.
                    for item in items:
                        item.status = EpistemicStatus.CONTRADICTED
        return errors


class EpistemicValidator:
    def validate(self, graph: KuyenGraph, antu: Antu) -> list[ValidationIssue]:
        errors: list[ValidationIssue] = []
        allowed = {item.value for item in EpistemicStatus}
        for assertion in graph.assertions:
            path = f"assertion:{assertion.assertion_id}"
            if assertion.proposed_status_raw:
                if assertion.proposed_status_raw not in allowed:
                    errors.append(issue("EPISTEMIC_STATUS_INVALID", assertion.proposed_status_raw, path))
                if assertion.proposed_status is EpistemicStatus.SOURCE_VERIFIED:
                    errors.append(issue("CANDIDATE_STATUS_NOT_AUTHORIZED", "candidate cannot self-assign SOURCE_VERIFIED", path))
            if assertion.status in {
                EpistemicStatus.UNRESOLVED, EpistemicStatus.UNSUPPORTED,
                EpistemicStatus.NOT_EVALUATED,
            } and antu.unresolved_policy == "reject":
                errors.append(issue("UNRESOLVED_POLICY_REJECT", assertion.status.value, path))
        return errors


class GraphStructuralValidator:
    def validate(self, graph: KuyenGraph, antu: Antu) -> list[ValidationIssue]:
        errors: list[ValidationIssue] = []
        entity_ids = [item.entity_id for item in graph.entities]
        relation_ids = [item.relation_id for item in graph.relations]
        assertion_ids = [item.assertion_id for item in graph.assertions]
        evidence_ids = {item.evidence_id for item in graph.evidence}
        for label, values in (("entity", entity_ids), ("relation", relation_ids), ("assertion", assertion_ids)):
            for value, count in Counter(values).items():
                if count > 1:
                    errors.append(issue("DUPLICATE_ID", f"{label} {value} repeated", f"{label}:{value}"))
                    if label == "entity":
                        sources = [
                            x.source_entity_id for x in graph.entities
                            if x.entity_id == value and x.source_entity_id
                        ]
                        errors.append(issue("ENTITY_ID_COLLISION", f"{value} sources={sources}", f"entity:{value}"))
        for value in (*entity_ids, *relation_ids, *assertion_ids):
            if not value or not ID_RE.match(value):
                errors.append(issue("ID_INVALID", value, "graph"))
        entity_set = set(entity_ids)
        for entity in graph.entities:
            if not entity.name.strip():
                errors.append(issue("ENTITY_NAME_EMPTY", entity.entity_id, f"entity:{entity.entity_id}"))
            if not entity.entity_type.strip():
                errors.append(issue("ENTITY_TYPE_EMPTY", entity.entity_id, f"entity:{entity.entity_id}"))
            if antu.evidence_policy == "strict" and not entity.evidence_ids:
                errors.append(issue("ENTITY_EVIDENCE_MISSING", entity.entity_id, f"entity:{entity.entity_id}"))
            for ref in entity.evidence_ids:
                if ref not in evidence_ids:
                    errors.append(issue("EVIDENCE_REF_UNKNOWN", ref, f"entity:{entity.entity_id}"))
        seen_triples: set[tuple[Any, ...]] = set()
        for relation in graph.relations:
            if not relation.from_entity:
                errors.append(issue("ENDPOINT_ID_MISSING", "from endpoint is empty", f"relation:{relation.relation_id}"))
            elif relation.from_entity not in entity_set:
                errors.append(issue("ORPHAN_ENDPOINT", relation.from_entity, f"relation:{relation.relation_id}"))
            if not relation.to_entity:
                errors.append(issue("ENDPOINT_ID_MISSING", "to endpoint is empty", f"relation:{relation.relation_id}"))
            elif relation.to_entity not in entity_set:
                errors.append(issue("ORPHAN_ENDPOINT", relation.to_entity, f"relation:{relation.relation_id}"))
            if relation.from_entity == relation.to_entity:
                errors.append(issue("SELF_RELATION", relation.relation_id, f"relation:{relation.relation_id}"))
            if not relation.label.strip():
                errors.append(issue("RELATION_LABEL_EMPTY", relation.relation_id, f"relation:{relation.relation_id}"))
            triple = (
                relation.from_entity, relation.predicate, relation.to_entity,
                relation.polarity.value, relation.scope, relation.temporal_scope,
            )
            if triple in seen_triples:
                errors.append(issue("DUPLICATE_RELATION", relation.relation_id, f"relation:{relation.relation_id}"))
            seen_triples.add(triple)
            if antu.evidence_policy == "strict" and not relation.evidence_ids:
                errors.append(issue("RELATION_EVIDENCE_MISSING", relation.relation_id, f"relation:{relation.relation_id}"))
            if antu.evidence_policy == "strict" and not relation.sources:
                errors.append(issue("RELATION_SOURCE_MISSING", relation.relation_id, f"relation:{relation.relation_id}"))
            for ref in relation.evidence_ids:
                if ref not in evidence_ids:
                    errors.append(issue("EVIDENCE_REF_UNKNOWN", ref, f"relation:{relation.relation_id}"))
        for assertion in graph.assertions:
            if assertion.subject_entity not in entity_set:
                errors.append(issue("ASSERTION_SUBJECT_UNKNOWN", assertion.subject_entity, f"assertion:{assertion.assertion_id}"))
            if assertion.object_entity is not None and assertion.object_entity not in entity_set:
                errors.append(issue("ASSERTION_OBJECT_UNKNOWN", assertion.object_entity, f"assertion:{assertion.assertion_id}"))
            if (assertion.object_entity is None) == (assertion.value is None):
                errors.append(issue("ASSERTION_OBJECT_SHAPE", "exactly one of object_entity/value required", f"assertion:{assertion.assertion_id}"))
            if antu.evidence_policy == "strict" and not assertion.evidence_ids:
                errors.append(issue("ASSERTION_EVIDENCE_MISSING", assertion.assertion_id, f"assertion:{assertion.assertion_id}"))
            for ref in assertion.evidence_ids:
                if ref not in evidence_ids:
                    errors.append(issue("EVIDENCE_REF_UNKNOWN", ref, f"assertion:{assertion.assertion_id}"))
        if len(graph.entities) > 10000 or len(graph.relations) > 50000:
            errors.append(issue("GRAPH_TOO_LARGE", "hard safety limit exceeded", "graph"))
        return errors


class EvidenceValidator:
    def validate(self, graph: KuyenGraph, mapus: list[Mapu]) -> list[ValidationIssue]:
        errors: list[ValidationIssue] = []
        by_id = {item.mapu_id: item for item in mapus}
        seen: set[str] = set()
        for evidence in graph.evidence:
            path = f"evidence:{evidence.evidence_id}"
            if evidence.evidence_id in seen:
                errors.append(issue("EVIDENCE_DUPLICATE", evidence.evidence_id, path))
            seen.add(evidence.evidence_id)
            mapu = by_id.get(evidence.mapu_id)
            if mapu is None:
                errors.append(issue("EVIDENCE_SOURCE_UNKNOWN", evidence.mapu_id, path))
                continue
            if evidence.source_sha256 != mapu.sha256:
                errors.append(issue("EVIDENCE_HASH_MISMATCH", evidence.source_sha256, path))
            if evidence.source_uri != mapu.source_uri:
                errors.append(issue("EVIDENCE_URI_MISMATCH", evidence.source_uri, path))
            if evidence.offset_unit != "unicode_codepoint":
                errors.append(issue("OFFSET_UNIT_UNSUPPORTED", evidence.offset_unit, path))
            if evidence.char_start < 0 or evidence.char_end < evidence.char_start:
                errors.append(issue("EVIDENCE_OFFSET_INVALID", f"{evidence.char_start}:{evidence.char_end}", path))
                continue
            if evidence.char_end > len(mapu.content):
                errors.append(issue("EVIDENCE_OFFSET_OUT_OF_RANGE", str(evidence.char_end), path))
                continue
            actual = mapu.content[evidence.char_start:evidence.char_end]
            if actual != evidence.quote:
                errors.append(
                    issue(
                        "EVIDENCE_QUOTE_MISMATCH",
                        "source slice does not equal quote",
                        path,
                        evidence=f"expected={actual[:120]!r} quote={evidence.quote[:120]!r}",
                    )
                )
            if not evidence.quote:
                errors.append(issue("EVIDENCE_QUOTE_EMPTY", evidence.evidence_id, path))
        return errors


class CoverageValidator:
    def validate(
        self,
        graph: KuyenGraph,
        antu: Antu,
        mapus: list[Mapu],
        expected_units: dict[str, list[Any]] | None = None,
    ) -> list[ValidationIssue]:
        errors: list[ValidationIssue] = []
        if antu.coverage_policy == "not_required":
            return errors
        coverage = graph.coverage
        if not coverage:
            errors.append(issue("COVERAGE_LEDGER_MISSING", "complete/require_terminal policy requires a ledger", "coverage"))
            return errors
        mapu_by_id = {item.mapu_id: item for item in mapus}
        entity_ids = {item.entity_id for item in graph.entities}
        relation_ids = {item.relation_id for item in graph.relations}
        seen_units: set[tuple[str, str]] = set()
        source_units: set[str] = set()
        expected_index = {
            (mapu_id, unit.unit_id): unit
            for mapu_id, units in (expected_units or {}).items()
            for unit in units
        }
        for unit in coverage:
            path = f"coverage:{unit.unit_id}"
            if unit.mapu_id not in mapu_by_id:
                errors.append(issue("COVERAGE_MAPU_UNKNOWN", unit.mapu_id, path))
                continue
            key = (unit.mapu_id, unit.unit_id)
            if key in seen_units:
                errors.append(issue("COVERAGE_UNIT_DUPLICATE", unit.unit_id, path))
            seen_units.add(key)
            source_units.add(unit.mapu_id)
            if unit.source_uri != mapu_by_id[unit.mapu_id].source_uri:
                errors.append(issue("COVERAGE_SOURCE_URI_MISMATCH", unit.source_uri, path))
            if expected_units is not None:
                expected = expected_index.get(key)
                if expected is None:
                    errors.append(issue(
                        "COVERAGE_UNIT_UNEXPECTED", unit.unit_id,
                        path, evidence="unit is not part of the deterministic inventory",
                    ))
                elif unit.content_sha256 and unit.content_sha256 != expected.content_sha256:
                    errors.append(issue(
                        "COVERAGE_UNIT_HASH_MISMATCH", unit.unit_id,
                        path, evidence=f"expected={expected.content_sha256}",
                    ))
            if antu.coverage_policy in {"complete", "complete_with_reasons"} and unit.state in {
                CoverageState.FAILED, CoverageState.NOT_ATTEMPTED
            }:
                errors.append(issue("COVERAGE_UNIT_INCOMPLETE", unit.state.value, path))
            if antu.coverage_policy == "complete" and unit.state is CoverageState.SKIPPED_WITH_REASON:
                errors.append(issue("COVERAGE_UNIT_INCOMPLETE", unit.state.value, path))
            if antu.coverage_policy == "complete_with_reasons" and unit.state is CoverageState.SKIPPED_WITH_REASON:
                if not (unit.reason or "").strip():
                    errors.append(issue("COVERAGE_SKIP_REASON_MISSING", unit.unit_id, path))
            if antu.coverage_policy == "require_terminal" and unit.state is CoverageState.NOT_ATTEMPTED:
                errors.append(issue("COVERAGE_UNIT_NOT_ATTEMPTED", unit.unit_id, path))
            if unit.state is CoverageState.PROCESSED_WITH_OUTPUT:
                if not unit.entity_ids and not unit.relation_ids:
                    errors.append(issue(
                        "COVERAGE_OUTPUT_EMPTY",
                        "PROCESSED_WITH_OUTPUT must reference at least one entity or relation",
                        path,
                    ))
                for entity_id in unit.entity_ids:
                    if entity_id not in entity_ids:
                        errors.append(issue("COVERAGE_ENTITY_UNKNOWN", entity_id, path))
                for relation_id in unit.relation_ids:
                    if relation_id not in relation_ids:
                        errors.append(issue("COVERAGE_RELATION_UNKNOWN", relation_id, path))
        if expected_units is not None:
            for key, expected in expected_index.items():
                if key not in seen_units:
                    errors.append(issue(
                        "COVERAGE_EXPECTED_UNIT_MISSING",
                        f"{key[0]}:{key[1]} ({expected.section})", "coverage",
                    ))
        for mapu_id in mapu_by_id:
            if mapu_id not in source_units:
                errors.append(issue("COVERAGE_SOURCE_MISSING", mapu_id, "coverage"))
        return errors


class TemporalValidator:
    KINDS = {"POINT", "INTERVAL", "RECURRENCE", "SEASON", "APPROXIMATE", "UNKNOWN"}

    def validate(self, graph: KuyenGraph, antu: Antu) -> list[ValidationIssue]:
        errors: list[ValidationIssue] = []
        for item in [*graph.relations, *graph.assertions]:
            temporal = getattr(item, "temporal", None)
            if temporal is None:
                continue
            path = f"temporal:{getattr(item, 'relation_id', None) or getattr(item, 'assertion_id', None)}"
            if temporal.kind not in self.KINDS:
                errors.append(issue("TEMPORAL_KIND_INVALID", temporal.kind, path))
            if temporal.month is not None and not 1 <= temporal.month <= 12:
                errors.append(issue("TEMPORAL_MONTH_INVALID", str(temporal.month), path))
            if temporal.day is not None and not 1 <= temporal.day <= 31:
                errors.append(issue("TEMPORAL_DAY_INVALID", str(temporal.day), path))
            if temporal.kind == "RECURRENCE" and not temporal.frequency:
                errors.append(issue("TEMPORAL_FREQUENCY_MISSING", "RECURRENCE", path))
            if temporal.kind == "INTERVAL" and (not temporal.start or not temporal.end):
                errors.append(issue("TEMPORAL_INTERVAL_BOUNDS_MISSING", "INTERVAL", path))
            if temporal.kind in {"POINT", "APPROXIMATE", "SEASON", "RECURRENCE"} and not temporal.expression:
                errors.append(issue("TEMPORAL_EXPRESSION_MISSING", temporal.kind, path))
        return errors


class AcceptanceGate:
    """Hard gate: no score can compensate a structural or evidence error."""

    def __init__(self) -> None:
        self.structural = GraphStructuralValidator()
        self.evidence = EvidenceValidator()
        self.ontology = OntologyValidator()
        self.coverage = CoverageValidator()
        self.epistemic = EpistemicValidator()
        self.temporal = TemporalValidator()

    def validate(
        self, *, graph: KuyenGraph, antu: Antu, mapus: list[Mapu], ontology: Ontology,
        expected_units: dict[str, list[Any]] | None = None,
    ) -> ValidationReport:
        structural_issues = self.structural.validate(graph, antu)
        ontology_issues = self.ontology.validate(graph, antu, ontology)
        evidence_issues = self.evidence.validate(graph, mapus)
        coverage_issues = self.coverage.validate(graph, antu, mapus, expected_units=expected_units)
        temporal_issues = self.temporal.validate(graph, antu)
        if not evidence_issues:
            for entity in graph.entities:
                if entity.evidence_ids:
                    # Exact mention evidence verifies the mention, not every
                    # claim that may later be attached to the entity.
                    entity.status = EpistemicStatus.SOURCE_VERIFIED
            for relation in graph.relations:
                # Citation integrity is recorded separately from claim support.
                # It never upgrades a relation to SOURCE_VERIFIED on its own.
                if relation.evidence_ids and relation.semantic_status == "SUPPORTS":
                    relation.status = EpistemicStatus.SOURCE_VERIFIED
                elif relation.evidence_ids and relation.status is EpistemicStatus.NOT_EVALUATED:
                    relation.status = EpistemicStatus.UNRESOLVED
            for assertion in graph.assertions:
                assertion.evidence_status = "SOURCE_VERIFIED" if assertion.evidence_ids else "NOT_EVALUATED"
                if assertion.status is EpistemicStatus.CONTRADICTED:
                    pass
                elif assertion.proposed_status is EpistemicStatus.SOURCE_VERIFIED:
                    assertion.status = EpistemicStatus.NOT_EVALUATED
                elif assertion.proposed_status is not None:
                    assertion.status = assertion.proposed_status
                elif assertion.semantic_status == "SUPPORTS":
                    assertion.status = EpistemicStatus.SOURCE_VERIFIED
                elif assertion.evidence_ids:
                    assertion.status = EpistemicStatus.UNRESOLVED
        epistemic_issues = self.epistemic.validate(graph, antu)
        issues = [*structural_issues, *evidence_issues, *ontology_issues, *coverage_issues, *epistemic_issues, *temporal_issues]

        def status(values):
            # Warnings are explicit preservation signals, not gate failures.
            return "PASS" if not any(item.severity == "ERROR" for item in values) else "FAIL"

        return ValidationReport(
            structural=status(structural_issues),
            evidence=status(evidence_issues),
            ontology=status(ontology_issues),
            coverage=status(coverage_issues),
            epistemic=status(epistemic_issues),
            temporal=status(temporal_issues),
            issues=issues,
            accepted=not any(item.severity == "ERROR" for item in issues),
        )
