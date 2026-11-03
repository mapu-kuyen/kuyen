"""Typed domain models. No external service calls happen here."""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

from ..canonical import stable_id
from ..errors import InvalidRequestError


class EpistemicStatus(str, Enum):
    SOURCE_VERIFIED = "SOURCE_VERIFIED"
    UNRESOLVED = "UNRESOLVED"
    CONTRADICTED = "CONTRADICTED"
    UNSUPPORTED = "UNSUPPORTED"
    NOT_EVALUATED = "NOT_EVALUATED"
    # Knowledge that comes from an authorised Antü instruction instead of a document.
    # It is a real, recorded provenance — it is simply not documentary verification, so
    # it must never be reported as SOURCE_VERIFIED (KUYEN_PRODUCTIVE_GRAPH_11, §4).
    INSTRUCTED = "INSTRUCTED"
    # An earlier statement kept in the record after a correction; `superseded_by`
    # points at the statement that replaced it.
    SUPERSEDED = "SUPERSEDED"
    RETRACTED = "RETRACTED"


class CoverageState(str, Enum):
    PROCESSED_WITH_OUTPUT = "PROCESSED_WITH_OUTPUT"
    PROCESSED_NO_GRAPH_FACTS = "PROCESSED_NO_GRAPH_FACTS"
    FAILED = "FAILED"
    SKIPPED_WITH_REASON = "SKIPPED_WITH_REASON"
    NOT_ATTEMPTED = "NOT_ATTEMPTED"


class Polarity(str, Enum):
    POSITIVE = "POSITIVE"
    NEGATIVE = "NEGATIVE"
    # Candidate-side only. The canonical schema admits POSITIVE/NEGATIVE; a candidate
    # whose polarity was never declared stays UNKNOWN and is *not* admitted instead of
    # being silently turned into an affirmative statement (KUYEN_PRODUCTIVE_GRAPH_11, §5.3).
    UNKNOWN = "UNKNOWN"


class Modality(str, Enum):
    """How the source states a claim. Absent modality is UNKNOWN, never FACT."""

    FACT = "FACT"
    FORECAST = "FORECAST"
    ESTIMATE = "ESTIMATE"
    OPINION = "OPINION"
    CONDITIONAL = "CONDITIONAL"
    UNKNOWN = "UNKNOWN"


def to_primitive(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if hasattr(value, "__dataclass_fields__"):
        return {key: to_primitive(item) for key, item in asdict(value).items()}
    if isinstance(value, Mapping):
        return {str(key): to_primitive(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_primitive(item) for item in value]
    return value


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ActorContext:
    leftraru_id: str
    authenticated_account: str
    authenticated_user: str
    service_identity: str
    antu_author: str
    candidate_producer: str
    request_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return to_primitive(self)


ANTU_ALLOWED_FIELDS = frozenset({
    "antu_id", "version", "purpose", "author", "scope", "language",
    "ontology_profile", "entity_types", "relation_types", "coverage_policy",
    "evidence_policy", "scalar_policy", "conflict_policy", "output_profile",
    "schema_version", "unresolved_policy", "extensions",
})
ANTU_SCOPE_ALLOWED_FIELDS = frozenset({"include", "exclude"})
SUPPORTED_ANTU_SCHEMA_VERSIONS = frozenset({"1.0.0", "1.1.0"})
ANTU_ALLOWED_EXTENSIONS = frozenset({"x-kuyen-fixture", "x-kuyen-fact-coverage", "x-kuyen-document-sections", "x-kuyen-temporal"})


@dataclass(frozen=True)
class Antu:
    antu_id: str
    version: str
    purpose: str
    include_scope: tuple[str, ...]
    exclude_scope: tuple[str, ...]
    language: str
    ontology_profile: str
    entity_types: tuple[str, ...]
    relation_types: tuple[str, ...]
    coverage_policy: str
    evidence_policy: str
    scalar_policy: str
    conflict_policy: str
    output_profile: str
    schema_version: str = "1.0.0"
    unresolved_policy: str = "allow"
    extensions: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict, compare=False)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "Antu":
        unknown = sorted(set(value) - ANTU_ALLOWED_FIELDS)
        if unknown:
            raise InvalidRequestError(
                f"unknown Antü field: {unknown[0]}",
                details={"code": "ANTU_UNKNOWN_FIELD", "path": unknown[0],
                         "field": unknown[0], "schema_version": str(value.get("schema_version", "1.0.0"))},
            )
        schema_version = str(value.get("schema_version", "1.0.0"))
        if schema_version not in SUPPORTED_ANTU_SCHEMA_VERSIONS:
            raise InvalidRequestError(
                f"unsupported Antü schema_version: {schema_version}",
                details={"code": "ANTU_SCHEMA_VERSION_UNSUPPORTED", "path": "schema_version",
                         "field": "schema_version", "schema_version": schema_version},
            )
        scope = value.get("scope") or {}
        if not isinstance(scope, Mapping):
            raise InvalidRequestError(
                "scope must be an object",
                details={"code": "ANTU_SCOPE_INVALID", "path": "scope", "field": "scope", "schema_version": schema_version},
            )
        scope_unknown = sorted(set(scope) - ANTU_SCOPE_ALLOWED_FIELDS)
        if scope_unknown:
            raise InvalidRequestError(
                f"unknown scope field: {scope_unknown[0]}",
                details={"code": "ANTU_UNKNOWN_FIELD", "path": f"scope.{scope_unknown[0]}", "field": scope_unknown[0], "schema_version": schema_version},
            )
        extensions = value.get("extensions") or {}
        if not isinstance(extensions, Mapping):
            raise InvalidRequestError(
                "extensions must be an object",
                details={"code": "ANTU_EXTENSIONS_INVALID", "path": "extensions", "field": "extensions", "schema_version": schema_version},
            )
        unknown_extensions = sorted(set(extensions) - ANTU_ALLOWED_EXTENSIONS)
        if unknown_extensions:
            raise InvalidRequestError(
                f"unknown Antü extension: {unknown_extensions[0]}",
                details={"code": "ANTU_UNKNOWN_EXTENSION", "path": f"extensions.{unknown_extensions[0]}", "field": unknown_extensions[0], "schema_version": schema_version},
            )
        required = ("antu_id", "version", "purpose", "ontology_profile", "output_profile")
        missing = [key for key in required if not str(value.get(key, "")).strip()]
        if missing:
            raise InvalidRequestError(
                f"Antu missing fields: {', '.join(missing)}",
                details={"code": "ANTU_REQUIRED_FIELD_MISSING", "path": missing[0], "field": missing[0], "schema_version": schema_version},
            )
        return cls(
            antu_id=str(value["antu_id"]),
            version=str(value["version"]),
            purpose=str(value["purpose"]),
            include_scope=tuple(str(x) for x in (scope.get("include") or [])),
            exclude_scope=tuple(str(x) for x in (scope.get("exclude") or [])),
            language=str(value.get("language", "es")),
            ontology_profile=str(value["ontology_profile"]),
            entity_types=tuple(str(x) for x in (value.get("entity_types") or [])),
            relation_types=tuple(str(x) for x in (value.get("relation_types") or [])),
            coverage_policy=str(value.get("coverage_policy", "complete")),
            evidence_policy=str(value.get("evidence_policy", "strict")),
            scalar_policy=str(value.get("scalar_policy", "literal")),
            conflict_policy=str(value.get("conflict_policy", "preserve_unresolved")),
            output_profile=str(value["output_profile"]),
            schema_version=schema_version,
            unresolved_policy=str(value.get("unresolved_policy", "allow")),
            extensions=dict(extensions),
            raw=dict(value),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "antu_id": self.antu_id,
            "version": self.version,
            "purpose": self.purpose,
            "scope": {"include": list(self.include_scope), "exclude": list(self.exclude_scope)},
            "language": self.language,
            "ontology_profile": self.ontology_profile,
            "entity_types": list(self.entity_types),
            "relation_types": list(self.relation_types),
            "coverage_policy": self.coverage_policy,
            "evidence_policy": self.evidence_policy,
            "scalar_policy": self.scalar_policy,
            "conflict_policy": self.conflict_policy,
            "output_profile": self.output_profile,
            "schema_version": self.schema_version,
            "unresolved_policy": self.unresolved_policy,
            "extensions": dict(self.extensions),
        }


@dataclass(frozen=True)
class Mapu:
    mapu_id: str
    version: str
    source_uri: str
    content: str
    sha256: str
    media_type: str = "text/plain"
    source_type: str = "text"
    source_identity: str = ""
    license: str | None = None
    source_timestamp: str | None = None
    ingestion_timestamp: str = ""
    trust_level: str = "UNVERIFIED"
    access_policy: str = "experimental"
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def byte_length(self) -> int:
        return len(self.content.encode("utf-8"))

    def verify(self) -> None:
        actual = hashlib.sha256(self.content.encode("utf-8")).hexdigest()
        if actual != self.sha256:
            raise ValueError(f"MAPU {self.mapu_id} hash mismatch: expected {self.sha256}, got {actual}")
        if not self.source_uri.startswith("viking://"):
            raise ValueError(f"MAPU {self.mapu_id} source_uri must be a viking:// URI")

    @classmethod
    def from_file(
        cls,
        *,
        mapu_id: str,
        version: str,
        source_uri: str,
        path: str | Path,
        **metadata: Any,
    ) -> "Mapu":
        content = Path(path).read_text(encoding="utf-8")
        return cls(
            mapu_id=mapu_id,
            version=version,
            source_uri=source_uri,
            content=content,
            sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            ingestion_timestamp=utc_now(),
            metadata=metadata,
        )

    def to_dict(self) -> dict[str, Any]:
        return to_primitive(self)


@dataclass
class CandidateEvidence:
    evidence_id: str
    mapu_id: str
    source_uri: str
    source_sha256: str
    quote: str
    char_start: int
    char_end: int
    offset_unit: str = "unicode_codepoint"
    extraction_method: str = "llm"
    validation_status: str = "NOT_EVALUATED"
    # Literal fragment around the quote, used only to disambiguate a repeated quote.
    context: str | None = None
    # Optional SOURCE_UNIT declared by the producer; KÜYEN verifies it, never trusts it.
    source_unit_id: str | None = None
    # Offsets exactly as the producer declared them. They are auxiliary: the located
    # quote is the authority for `char_start`/`char_end` (KUYEN_PRODUCTIVE_GRAPH_11, §5.2).
    declared_offsets: dict[str, Any] | None = None

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CandidateEvidence":
        return cls(
            evidence_id=str(value.get("evidence_id") or ""),
            mapu_id=str(value.get("mapu_id") or ""),
            source_uri=str(value.get("source_uri") or ""),
            source_sha256=str(value.get("source_sha256") or ""),
            quote=str(value.get("quote") or ""),
            char_start=int(value.get("char_start", -1)),
            char_end=int(value.get("char_end", -1)),
            offset_unit=str(value.get("offset_unit") or "unicode_codepoint"),
            extraction_method=str(value.get("extraction_method") or "llm"),
            validation_status=str(value.get("validation_status") or "NOT_EVALUATED"),
            context=value.get("context"),
            source_unit_id=value.get("source_unit_id"),
            declared_offsets=dict(value["declared_offsets"]) if value.get("declared_offsets") else None,
        )

    def to_dict(self) -> dict[str, Any]:
        return to_primitive(self)


@dataclass
class Entity:
    entity_id: str
    entity_type: str
    name: str
    aliases: list[str] = field(default_factory=list)
    description: str = ""
    evidence_ids: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    source_entity_id: str | None = None
    source_namespace: str | None = None
    identity_basis: str = "source_id"
    normalization_status: str = "RESOLVED"
    normalization_reason: str | None = None
    status: EpistemicStatus = EpistemicStatus.NOT_EVALUATED
    metadata: dict[str, Any] = field(default_factory=dict)
    # 0.1.7 identity levels. ``source_entity_id`` is the origin identity;
    # ``entity_id`` is the canonical KÜYEN identity. A resolved identity is an
    # explicit equivalence decision, never an automatic name-based merge.
    origin_entity_id: str | None = None
    canonical_entity_id: str | None = None
    identity_status: str = "NOT_ASSESSED"
    identity_group_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return to_primitive(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "Entity":
        return cls(
            entity_id=str(value["entity_id"]),
            entity_type=str(value["entity_type"]),
            name=str(value["name"]),
            aliases=[str(item) for item in (value.get("aliases") or [])],
            description=str(value.get("description") or ""),
            evidence_ids=[str(item) for item in (value.get("evidence_ids") or [])],
            sources=[str(item) for item in (value.get("sources") or [])],
            source_entity_id=value.get("source_entity_id"),
            source_namespace=value.get("source_namespace"),
            identity_basis=str(value.get("identity_basis") or "source_id"),
            normalization_status=str(value.get("normalization_status") or "RESOLVED"),
            normalization_reason=value.get("normalization_reason"),
            status=EpistemicStatus(str(value.get("status") or "NOT_EVALUATED")),
            metadata=dict(value.get("metadata") or {}),
            origin_entity_id=value.get("origin_entity_id"),
            canonical_entity_id=value.get("canonical_entity_id"),
            identity_status=str(value.get("identity_status") or "NOT_ASSESSED"),
            identity_group_id=value.get("identity_group_id"),
        )


@dataclass
class Value:
    value_type: str
    value: Any
    unit: str | None = None
    context: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return to_primitive(self)


@dataclass
class TemporalScope:
    kind: str = "UNKNOWN"
    expression: str | None = None
    start: str | None = None
    end: str | None = None
    frequency: str | None = None
    month: int | None = None
    day: int | None = None
    timezone: str | None = None
    precision: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return to_primitive(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | None) -> "TemporalScope | None":
        if not value:
            return None
        if not isinstance(value, Mapping):
            raise InvalidRequestError("temporal must be an object")
        return cls(
            kind=str(value.get("kind") or "UNKNOWN"),
            expression=value.get("expression"),
            start=value.get("start"), end=value.get("end"),
            frequency=value.get("frequency"),
            month=int(value["month"]) if value.get("month") is not None else None,
            day=int(value["day"]) if value.get("day") is not None else None,
            timezone=value.get("timezone"), precision=value.get("precision"),
        )


@dataclass
class Relation:
    relation_id: str
    from_entity: str
    predicate: str
    to_entity: str
    label: str
    polarity: Polarity = Polarity.POSITIVE
    scope: str = "document"
    temporal_scope: str | None = None
    temporal: TemporalScope | None = None
    evidence_ids: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    source_from_entity: str | None = None
    source_to_entity: str | None = None
    from_normalization_status: str = "RESOLVED"
    to_normalization_status: str = "RESOLVED"
    normalization_reason: str | None = None
    status: EpistemicStatus = EpistemicStatus.NOT_EVALUATED
    semantic_status: str = "NOT_ASSESSED"
    # 0.1.7 predicate preservation. ``predicate`` remains the canonical
    # predicate. ``source_predicate`` is what the producer actually proposed and
    # ``provider_predicate`` is only a lossy native storage projection.
    source_predicate: str | None = None
    canonical_predicate: str | None = None
    provider_predicate: str | None = None
    display_label: str | None = None
    provider_label: str | None = None
    mapping_status: str = "UNRESOLVED"
    mapping_rule_id: str | None = None
    mapping_version: str | None = None
    provider_projection_status: str | None = None
    source_label: str | None = None
    source_relation_ref: str | None = None
    # Semantic dimensions and explicit provenance (KUYEN_PRODUCTIVE_GRAPH_11, §4 and §5.4).
    modality: str = "UNKNOWN"
    attribution: str | None = None
    origin: dict[str, Any] | None = None
    supersedes: str | None = None
    superseded_by: str | None = None
    retracted: bool = False

    def to_dict(self) -> dict[str, Any]:
        return to_primitive(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "Relation":
        return cls(
            relation_id=str(value["relation_id"]),
            from_entity=str(value["from_entity"]),
            predicate=str(value["predicate"]),
            to_entity=str(value["to_entity"]),
            label=str(value.get("label") or value["predicate"]),
            polarity=Polarity(str(value.get("polarity") or "POSITIVE")),
            scope=str(value.get("scope") or "document"),
            temporal_scope=value.get("temporal_scope"),
            temporal=TemporalScope.from_dict(value.get("temporal")),
            evidence_ids=[str(item) for item in (value.get("evidence_ids") or [])],
            sources=[str(item) for item in (value.get("sources") or [])],
            source_from_entity=value.get("source_from_entity"),
            source_to_entity=value.get("source_to_entity"),
            from_normalization_status=str(value.get("from_normalization_status") or "RESOLVED"),
            to_normalization_status=str(value.get("to_normalization_status") or "RESOLVED"),
            normalization_reason=value.get("normalization_reason"),
            status=EpistemicStatus(str(value.get("status") or "NOT_EVALUATED")),
            semantic_status=str(value.get("semantic_status") or "NOT_ASSESSED"),
            source_predicate=value.get("source_predicate"),
            canonical_predicate=value.get("canonical_predicate"),
            provider_predicate=value.get("provider_predicate"),
            display_label=value.get("display_label"),
            provider_label=value.get("provider_label"),
            mapping_status=str(value.get("mapping_status") or "UNRESOLVED"),
            mapping_rule_id=value.get("mapping_rule_id"),
            mapping_version=value.get("mapping_version"),
            provider_projection_status=value.get("provider_projection_status"),
            source_label=value.get("source_label"),
            source_relation_ref=value.get("source_relation_ref"),
            modality=str(value.get("modality") or "UNKNOWN"),
            attribution=value.get("attribution"),
            origin=dict(value["origin"]) if isinstance(value.get("origin"), Mapping) else None,
            supersedes=value.get("supersedes"),
            superseded_by=value.get("superseded_by"),
            retracted=bool(value.get("retracted", False)),
        )


@dataclass
class Assertion:
    assertion_id: str
    subject_entity: str
    predicate: str
    object_entity: str | None = None
    value: Value | None = None
    polarity: Polarity = Polarity.POSITIVE
    scope: str = "document"
    temporal_scope: str | None = None
    temporal: TemporalScope | None = None
    evidence_ids: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    proposed_status: EpistemicStatus | None = None
    proposed_status_raw: str | None = None
    evidence_status: str = "NOT_EVALUATED"
    status: EpistemicStatus = EpistemicStatus.NOT_EVALUATED
    semantic_status: str = "NOT_ASSESSED"
    support_method: str | None = None
    support_rationale: str | None = None
    # Predicate layer of an assertion (mirrors `Relation`): the term the producer declared is
    # preserved instead of being silently replaced by a generic scalar predicate.
    source_predicate: str | None = None
    canonical_predicate: str | None = None
    mapping_status: str = "UNRESOLVED"
    mapping_rule_id: str | None = None
    mapping_version: str | None = None
    # Semantic dimensions of the statement (KUYEN_PRODUCTIVE_GRAPH_11, §5.4). An absent
    # modality is UNKNOWN, never FACT; attribution names the actor the claim is credited to.
    modality: str = "UNKNOWN"
    attribution: str | None = None
    # Explicit provenance of the statement: document evidence, Antü instruction or a
    # previous version. Never inferred from the presence of evidence alone.
    origin: dict[str, Any] | None = None
    supersedes: str | None = None
    superseded_by: str | None = None
    retracted: bool = False

    def to_dict(self) -> dict[str, Any]:
        return to_primitive(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "Assertion":
        raw_value = value.get("value")
        return cls(
            assertion_id=str(value["assertion_id"]),
            subject_entity=str(value["subject_entity"]),
            predicate=str(value["predicate"]),
            object_entity=value.get("object_entity"),
            value=Value(**raw_value) if isinstance(raw_value, Mapping) else None,
            polarity=Polarity(str(value.get("polarity") or "POSITIVE")),
            scope=str(value.get("scope") or "document"),
            temporal_scope=value.get("temporal_scope"),
            temporal=TemporalScope.from_dict(value.get("temporal")),
            evidence_ids=[str(item) for item in (value.get("evidence_ids") or [])],
            sources=[str(item) for item in (value.get("sources") or [])],
            proposed_status=(
                EpistemicStatus(str(value["proposed_status"]))
                if value.get("proposed_status") else None
            ),
            proposed_status_raw=value.get("proposed_status_raw"),
            evidence_status=str(value.get("evidence_status") or "NOT_EVALUATED"),
            status=EpistemicStatus(str(value.get("status") or "NOT_EVALUATED")),
            semantic_status=str(value.get("semantic_status") or "NOT_ASSESSED"),
            support_method=value.get("support_method"),
            support_rationale=value.get("support_rationale"),
            modality=str(value.get("modality") or "UNKNOWN"),
            attribution=value.get("attribution"),
            origin=dict(value["origin"]) if isinstance(value.get("origin"), Mapping) else None,
            supersedes=value.get("supersedes"),
            superseded_by=value.get("superseded_by"),
            retracted=bool(value.get("retracted", False)),
            source_predicate=value.get("source_predicate"),
            canonical_predicate=value.get("canonical_predicate"),
            mapping_status=str(value.get("mapping_status") or "UNRESOLVED"),
            mapping_rule_id=value.get("mapping_rule_id"),
            mapping_version=value.get("mapping_version"),
        )


@dataclass
class CoverageUnit:
    source_uri: str
    mapu_id: str
    unit_id: str
    state: CoverageState
    section: str | None = None
    content_sha256: str | None = None
    entity_ids: list[str] = field(default_factory=list)
    relation_ids: list[str] = field(default_factory=list)
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return to_primitive(self)
@dataclass
class CandidateEntity:
    id: str
    name: str
    entity_type: str
    aliases: list[str] = field(default_factory=list)
    description: str = ""
    sources: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    source_namespace: str = "candidate"

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CandidateEntity":
        return cls(
            id=str(value.get("id") or ""),
            name=str(value.get("name") or value.get("title") or value.get("id") or ""),
            entity_type=str(value.get("entity_type") or value.get("type") or ""),
            aliases=[str(x) for x in (value.get("aliases") or [])],
            description=str(value.get("description") or ""),
            sources=[str(x) for x in (value.get("sources") or [])],
            evidence_refs=[str(x) for x in (value.get("evidence_refs") or [])],
            source_namespace=str(value.get("source_namespace") or value.get("namespace") or "candidate"),
        )


@dataclass
class CandidateRelation:
    from_entity: str
    relation: str
    to_entity: str
    label: str = ""
    # No default to POSITIVE: an undeclared polarity stays UNKNOWN and the canonical set
    # does not admit it (KUYEN_PRODUCTIVE_GRAPH_11, §5.3).
    polarity: str = "UNKNOWN"
    scope: str = "document"
    temporal_scope: str | None = None
    temporal: TemporalScope | None = None
    evidence_refs: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    source_predicate: str | None = None
    canonical_predicate: str | None = None
    provider_predicate: str | None = None
    display_label: str | None = None
    provider_label: str | None = None
    # No correspondence state is assumed. A producer that does not declare the
    # predicate layer gets UNRESOLVED until a versioned rule says otherwise;
    # defaulting to EXACT is exactly the silent degradation this contract fixes.
    mapping_status: str = "UNRESOLVED"
    mapping_rule_id: str | None = None
    mapping_version: str | None = None
    provider_projection_status: str = "EXACT"
    # Declared semantic dimensions; absence is UNKNOWN modality and no attribution
    # (KUYEN_PRODUCTIVE_GRAPH_11, §5.4).
    modality: str = "UNKNOWN"
    attribution: str | None = None

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CandidateRelation":
        return cls(
            from_entity=str(value.get("from") or ""),
            relation=str(value.get("relation") or ""),
            to_entity=str(value.get("to") or ""),
            label=str(value.get("label") or value.get("relation") or ""),
            polarity=str(value.get("polarity") or "UNKNOWN"),
            scope=str(value.get("scope") or "document"),
            temporal_scope=value.get("temporal_scope"),
            temporal=TemporalScope.from_dict(value.get("temporal")),
            evidence_refs=[str(x) for x in (value.get("evidence_refs") or [])],
            sources=[str(x) for x in (value.get("sources") or value.get("evidence") or [])],
            source_predicate=value.get("source_predicate"),
            canonical_predicate=value.get("canonical_predicate"),
            provider_predicate=value.get("provider_predicate"),
            display_label=value.get("display_label"),
            provider_label=value.get("provider_label"),
            mapping_status=str(value.get("mapping_status") or "UNRESOLVED"),
            mapping_rule_id=value.get("mapping_rule_id"),
            mapping_version=value.get("mapping_version"),
            provider_projection_status=str(value.get("provider_projection_status") or "EXACT"),
            modality=str(value.get("modality") or "UNKNOWN"),
            attribution=value.get("attribution") if isinstance(value.get("attribution"), str) else None,
        )


@dataclass
class CandidateAssertion:
    subject: str
    predicate: str
    object_entity: str | None = None
    value: Value | None = None
    # Undeclared polarity is UNKNOWN, never POSITIVE (KUYEN_PRODUCTIVE_GRAPH_11, §5.3).
    polarity: str = "UNKNOWN"
    scope: str = "document"
    temporal_scope: str | None = None
    temporal: TemporalScope | None = None
    evidence_refs: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    proposed_status: str | None = None
    # Declared semantic dimensions; absence is UNKNOWN modality and no attribution.
    modality: str = "UNKNOWN"
    attribution: str | None = None
    # Predicate layer declared by the producer (native artifacts declare it literally).
    source_predicate: str | None = None
    canonical_predicate: str | None = None
    mapping_status: str = "UNRESOLVED"
    mapping_rule_id: str | None = None
    mapping_version: str | None = None

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CandidateAssertion":
        raw_value = value.get("value")
        parsed_value = None
        if isinstance(raw_value, Mapping):
            parsed_value = Value(
                value_type=str(raw_value.get("value_type") or raw_value.get("type") or "string"),
                value=raw_value.get("value"),
                unit=raw_value.get("unit"),
                context=raw_value.get("context"),
            )
        elif raw_value is not None:
            parsed_value = Value(
                value_type="integer" if isinstance(raw_value, int) and not isinstance(raw_value, bool) else "string",
                value=raw_value,
            )
        return cls(
            subject=str(value.get("subject") or ""),
            predicate=str(value.get("predicate") or ""),
            object_entity=value.get("object_entity") or value.get("object"),
            value=parsed_value,
            polarity=str(value.get("polarity") or "UNKNOWN"),
            scope=str(value.get("scope") or "document"),
            temporal_scope=value.get("temporal_scope"),
            temporal=TemporalScope.from_dict(value.get("temporal")),
            evidence_refs=[str(x) for x in (value.get("evidence_refs") or [])],
            sources=[str(x) for x in (value.get("sources") or [])],
            proposed_status=(
                str(value.get("epistemic_status") or value.get("proposed_status") or value.get("status"))
                if (value.get("epistemic_status") or value.get("proposed_status") or value.get("status")) else None
            ),
            modality=str(value.get("modality") or "UNKNOWN"),
            attribution=value.get("attribution") if isinstance(value.get("attribution"), str) else None,
            source_predicate=value.get("source_predicate"),
            canonical_predicate=value.get("canonical_predicate"),
            mapping_status=str(value.get("mapping_status") or "UNRESOLVED"),
            mapping_rule_id=value.get("mapping_rule_id"),
            mapping_version=value.get("mapping_version"),
        )

@dataclass
class CandidateBundle:
    entities: list[CandidateEntity]
    relations: list[CandidateRelation]
    assertions: list[CandidateAssertion] = field(default_factory=list)
    evidence: list[CandidateEvidence] = field(default_factory=list)
    coverage: list[CoverageUnit] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict, compare=False)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CandidateBundle":
        return cls(
            entities=[CandidateEntity.from_dict(x) for x in (value.get("entities") or [])],
            relations=[CandidateRelation.from_dict(x) for x in (value.get("relations") or [])],
            assertions=[CandidateAssertion.from_dict(x) for x in (value.get("assertions") or [])],
            evidence=[CandidateEvidence.from_dict(x) for x in (value.get("evidence") or [])],
            coverage=[
                CoverageUnit(
                    source_uri=str(x.get("source_uri") or ""),
                    mapu_id=str(x.get("mapu_id") or ""),
                    unit_id=str(x.get("unit_id") or ""),
                    state=CoverageState(str(x.get("state") or "NOT_ATTEMPTED")),
                    section=x.get("section"),
                    content_sha256=x.get("content_sha256"),
                    entity_ids=[str(y) for y in (x.get("entity_ids") or [])],
                    relation_ids=[str(y) for y in (x.get("relation_ids") or [])],
                    reason=x.get("reason"),
                )
                for x in (value.get("coverage") or [])
            ],
            raw=dict(value),
        )


@dataclass
class ValidationIssue:
    code: str
    message: str
    path: str = ""
    severity: str = "ERROR"
    evidence: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return to_primitive(self)


@dataclass
class ValidationReport:
    structural: str = "NOT_RUN"
    evidence: str = "NOT_RUN"
    ontology: str = "NOT_RUN"
    coverage: str = "NOT_RUN"
    epistemic: str = "NOT_RUN"
    temporal: str = "NOT_RUN"
    issues: list[ValidationIssue] = field(default_factory=list)
    accepted: bool = False

    @property
    def errors(self) -> list[ValidationIssue]:
        return [item for item in self.issues if item.severity == "ERROR"]

    def to_dict(self) -> dict[str, Any]:
        return {
            "structural": self.structural,
            "evidence": self.evidence,
            "ontology": self.ontology,
            "coverage": self.coverage,
            "epistemic": self.epistemic,
            "temporal": self.temporal,
            "accepted": self.accepted,
            "issues": [item.to_dict() for item in self.issues],
        }


@dataclass
class KuyenGraph:
    kuyen_id: str
    version: str
    antu_id: str
    mapu_ids: list[str]
    entities: list[Entity]
    relations: list[Relation]
    assertions: list[Assertion]
    evidence: list[CandidateEvidence]
    coverage: list[CoverageUnit]
    provenance: dict[str, Any]
    schema_version: str = "kuyen-native-v1"
    status: str = "CANDIDATE"
    content_digest: str = ""
    provenance_digest: str = ""

    def compute_content_digest(self) -> str:
        """Recompute the stable content digest from canonical fields.

        This mirrors the normalizer's digest payload and intentionally excludes
        volatile execution provenance and the graph identity itself.
        """
        payload = {
            "antu_id": self.antu_id,
            "version": self.version,
            "mapu_ids": sorted(self.mapu_ids),
            "entities": sorted((item.to_dict() for item in self.entities), key=lambda x: x["entity_id"]),
            "relations": sorted((item.to_dict() for item in self.relations), key=lambda x: x["relation_id"]),
            "assertions": sorted((item.to_dict() for item in self.assertions), key=lambda x: x["assertion_id"]),
            "evidence": sorted((item.to_dict() for item in self.evidence), key=lambda x: x["evidence_id"]),
            "coverage": sorted(
                (item.to_dict() for item in self.coverage),
                key=lambda x: (x["mapu_id"], x["unit_id"]),
            ),
        }
        return stable_id("content", payload).split("_", 1)[1]

    def compute_provenance_digest(self) -> str:
        return stable_id("provenance", self.provenance).split("_", 1)[1]

    def to_dict(self) -> dict[str, Any]:
        return {
            "kuyen_id": self.kuyen_id,
            "version": self.version,
            "antu_id": self.antu_id,
            "mapu_ids": sorted(self.mapu_ids),
            "schema_version": self.schema_version,
            "status": self.status,
            "entities": [x.to_dict() for x in sorted(self.entities, key=lambda item: item.entity_id)],
            "relations": [x.to_dict() for x in sorted(self.relations, key=lambda item: item.relation_id)],
            "assertions": [x.to_dict() for x in sorted(self.assertions, key=lambda item: item.assertion_id)],
            "evidence": [x.to_dict() for x in sorted(self.evidence, key=lambda item: item.evidence_id)],
            "coverage": [x.to_dict() for x in sorted(self.coverage, key=lambda item: (item.mapu_id, item.unit_id))],
            "provenance": self.provenance,
            "content_digest": self.content_digest,
            "provenance_digest": self.provenance_digest,
        }


@dataclass
class BuildResult:
    status: str
    kuyen_id: str | None
    request_key: str
    execution_id: str
    version: str
    graph_uri: str | None
    entity_count: int
    relation_count: int
    coverage: dict[str, Any]
    validation: ValidationReport
    provenance_manifest: str | None
    content_digest: str | None
    reused: bool = False
    error: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "kuyen_id": self.kuyen_id,
            "request_key": self.request_key,
            "execution_id": self.execution_id,
            "status": self.status,
            "version": self.version,
            "graph_uri": self.graph_uri,
            "entity_count": self.entity_count,
            "relation_count": self.relation_count,
            "coverage": self.coverage,
            "validation": self.validation.to_dict(),
            "provenance_manifest": self.provenance_manifest,
            "content_digest": self.content_digest,
            "reused": self.reused,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "BuildResult":
        raw_validation = value.get("validation") or {}
        issues = [ValidationIssue(**item) for item in (raw_validation.get("issues") or [])]
        validation = ValidationReport(
            structural=raw_validation.get("structural", "NOT_RUN"),
            evidence=raw_validation.get("evidence", "NOT_RUN"),
            ontology=raw_validation.get("ontology", "NOT_RUN"),
            coverage=raw_validation.get("coverage", "NOT_RUN"),
            epistemic=raw_validation.get("epistemic", "NOT_RUN"),
            issues=issues,
            accepted=bool(raw_validation.get("accepted", False)),
        )
        return cls(
            status=str(value.get("status") or "BLOCKED"),
            kuyen_id=value.get("kuyen_id"), request_key=str(value.get("request_key") or ""),
            execution_id=str(value.get("execution_id") or ""), version=str(value.get("version") or ""),
            graph_uri=value.get("graph_uri"), entity_count=int(value.get("entity_count") or 0),
            relation_count=int(value.get("relation_count") or 0), coverage=dict(value.get("coverage") or {}),
            validation=validation, provenance_manifest=value.get("provenance_manifest"),
            content_digest=value.get("content_digest"), reused=bool(value.get("reused", False)),
            error=value.get("error"),
        )

