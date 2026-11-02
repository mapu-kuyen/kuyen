"""Deterministic materialization of a provider proposal into a KÜYEN candidate.

The provider proposes; KÜYEN materializes. Provider IDs are preserved, evidence is
verified against the MAPU, coverage is derived from KÜYEN's inventory, and every
decision is recorded in a manifest. KÜYEN never writes to the provider output.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

from ..canonical import stable_id
from ..coverage import SectionUnit
from ..errors import CandidateMaterializationError
from ..models import (
    Antu, TemporalScope,
    CandidateAssertion,
    CandidateBundle,
    CandidateEntity,
    CandidateEvidence,
    CandidateRelation,
    CoverageState,
    CoverageUnit,
    Mapu,
    Value,
)
from ..serialization.serializer import parse_frontmatter
from .contract import CONTRACT_ID, LEGACY_SIDECAR, NATIVE_CONTRACT_ID, RESULT_FILENAME, normalize_provider_result
from .paths import KUYEN_OWNER, PROVIDER_OWNER, PathOwnershipRegistry

EXACT_SPAN = "EXACT_SPAN"
OFFSET_RESOLVED_UNIQUE = "OFFSET_RESOLVED_UNIQUE"
DOCUMENT_REFERENCE = "DOCUMENT_REFERENCE"
AMBIGUOUS_QUOTE = "AMBIGUOUS_QUOTE"
INVALID_QUOTE = "INVALID_QUOTE"
INVALID_OFFSET = "INVALID_OFFSET"
INVALID_HASH = "INVALID_HASH"
URI_MISMATCH = "URI_MISMATCH"
UNSUPPORTED_UNIT = "UNSUPPORTED_OFFSET_UNIT"
SOURCE_UNKNOWN = "SOURCE_UNKNOWN"
NO_EVIDENCE = "NO_EVIDENCE"


def _text(value: Any) -> str | None:
    """Optional provider string: empty/absent stays None, never invented."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


@dataclass
class EvidenceDecision:
    item_kind: str
    item_id: str
    classification: str
    reason: str | None
    evidence_id: str | None = None
    mapu_id: str | None = None
    quote: str | None = None
    char_start: int | None = None
    char_end: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_kind": self.item_kind, "item_id": self.item_id,
            "classification": self.classification, "reason": self.reason,
            "evidence_id": self.evidence_id, "mapu_id": self.mapu_id,
            "quote": self.quote, "char_start": self.char_start, "char_end": self.char_end,
        }


@dataclass
class MaterializationResult:
    bundle: CandidateBundle
    manifest: dict[str, Any] = field(default_factory=dict)


class CandidateMaterializer:
    def __init__(
        self,
        *,
        mapus: list[Mapu],
        antu: Antu,
        coverage_inventory: dict[str, list[SectionUnit]] | None = None,
        contract: str = CONTRACT_ID,
        result_filename: str = RESULT_FILENAME,
    ) -> None:
        if not mapus:
            raise CandidateMaterializationError("materialization requires at least one MAPU")
        self.mapus = {item.mapu_id: item for item in mapus}
        self.antu = antu
        self.coverage_inventory = {
            mapu_id: [SectionUnit(**item) if isinstance(item, dict) else item for item in units]
            for mapu_id, units in (coverage_inventory or {}).items()
        }
        self.contract = contract
        self.result_filename = result_filename
        self.registry = PathOwnershipRegistry()
        self.evidence_pool: dict[str, CandidateEvidence] = {}
        self.decisions: list[EvidenceDecision] = []
        self.warnings: list[str] = []

    # ---------- evidence ----------

    def _mapu_for(self, raw: dict[str, Any]) -> Mapu | None:
        mapu_id = str(raw.get("mapu_id") or "")
        if mapu_id and mapu_id in self.mapus:
            return self.mapus[mapu_id]
        uri = str(raw.get("source_uri") or "")
        for mapu in self.mapus.values():
            root = mapu.source_uri.rstrip("/")
            if uri == root or uri.startswith(root + "/"):
                return mapu
        if len(self.mapus) == 1:
            return next(iter(self.mapus.values()))
        return None

    def _record(self, kind: str, item_id: str, classification: str, reason: str | None,
                *, evidence_id: str | None = None, mapu: Mapu | None = None,
                quote: str | None = None, start: int | None = None, end: int | None = None) -> EvidenceDecision:
        decision = EvidenceDecision(
            item_kind=kind, item_id=item_id, classification=classification, reason=reason,
            evidence_id=evidence_id, mapu_id=mapu.mapu_id if mapu else None,
            quote=quote, char_start=start, char_end=end,
        )
        self.decisions.append(decision)
        return decision

    def _resolve_evidence(self, kind: str, item_id: str, raw: dict[str, Any]) -> CandidateEvidence | None:
        mapu = self._mapu_for(raw)
        quote = str(raw.get("quote") or "")
        uri = str(raw.get("source_uri") or "")
        provided_sha = str(raw.get("source_sha256") or "")
        unit = str(raw.get("offset_unit") or "unicode_codepoint")
        if unit != "unicode_codepoint":
            self._record(kind, item_id, UNSUPPORTED_UNIT, f"offset_unit={unit}")
            return None
        if not quote:
            if mapu is not None and (uri or raw.get("sources")):
                self._record(kind, item_id, DOCUMENT_REFERENCE, "URI only; not a quote", mapu=mapu)
            else:
                self._record(kind, item_id, NO_EVIDENCE, "no quote or source URI", mapu=mapu)
            return None
        if mapu is None:
            self._record(kind, item_id, SOURCE_UNKNOWN, "no MAPU matches the evidence", quote=quote)
            return None
        if provided_sha and provided_sha != mapu.sha256:
            self._record(kind, item_id, INVALID_HASH, "source_sha256 does not match the MAPU", mapu=mapu, quote=quote)
            return None
        root = mapu.source_uri.rstrip("/")
        if uri and not (uri == root or uri.startswith(root + "/")):
            self._record(kind, item_id, URI_MISMATCH, "source_uri is outside the MAPU resource", mapu=mapu, quote=quote)
            return None
        start = raw.get("char_start")
        end = raw.get("char_end")
        if start is not None and end is not None:
            if not isinstance(start, int) or not isinstance(end, int):
                self._record(kind, item_id, INVALID_OFFSET, "offsets are not integers", mapu=mapu, quote=quote)
                return None
            if not 0 <= start <= end <= len(mapu.content) or mapu.content[start:end] != quote:
                self._record(kind, item_id, INVALID_OFFSET, "source[char_start:char_end] != quote", mapu=mapu, quote=quote, start=start, end=end)
                return None
            classification = EXACT_SPAN
            extraction = "llm"
            reason = None
        else:
            occurrences = []
            position = mapu.content.find(quote)
            while position != -1:
                occurrences.append(position)
                position = mapu.content.find(quote, position + 1)
            if not occurrences:
                self._record(kind, item_id, INVALID_QUOTE, "quote does not occur in the MAPU", mapu=mapu, quote=quote)
                return None
            if len(occurrences) > 1:
                self._record(kind, item_id, AMBIGUOUS_QUOTE, f"quote occurs {len(occurrences)} times", mapu=mapu, quote=quote)
                return None
            start = occurrences[0]
            end = start + len(quote)
            classification = OFFSET_RESOLVED_UNIQUE
            extraction = "llm_offset_resolved_unique"
            reason = "offsets absent; unique quote located deterministically"
        evidence_id = stable_id(
            "ev",
            {
                "mapu_id": mapu.mapu_id, "source_sha256": mapu.sha256,
                "source_uri": mapu.source_uri, "start": start, "end": end, "quote": quote,
            },
        )
        evidence = CandidateEvidence(
            evidence_id=evidence_id, mapu_id=mapu.mapu_id, source_uri=mapu.source_uri,
            source_sha256=mapu.sha256, quote=quote, char_start=start, char_end=end,
            offset_unit="unicode_codepoint", extraction_method=extraction,
        )
        self.evidence_pool.setdefault(evidence_id, evidence)
        self._record(kind, item_id, classification, reason, evidence_id=evidence_id, mapu=mapu, quote=quote, start=start, end=end)
        return evidence

    def _evidence_for_item(self, kind: str, item_id: str, item: dict[str, Any]) -> tuple[list[str], list[str]]:
        refs: list[str] = []
        first_mapu: Mapu | None = None
        raw_evidence = item.get("evidence") or []
        if not isinstance(raw_evidence, list):
            raw_evidence = [raw_evidence]
        for raw in raw_evidence:
            if not isinstance(raw, dict):
                self._record(kind, item_id, NO_EVIDENCE, "evidence entry is not an object")
                continue
            evidence = self._resolve_evidence(kind, item_id, raw)
            if evidence is not None:
                refs.append(evidence.evidence_id)
                first_mapu = first_mapu or self.mapus.get(evidence.mapu_id)
        sources = [str(x) for x in (item.get("sources") or []) if str(x).strip()]
        if not sources and first_mapu is not None:
            sources = [first_mapu.source_uri]
        if not item.get("evidence") and sources:
            self._resolve_evidence(kind, item_id, {"source_uri": sources[0]})
        return sorted(set(refs)), list(dict.fromkeys(sources))

    @staticmethod
    def _value(raw: Any) -> Value | None:
        if raw is None:
            return None
        if isinstance(raw, dict):
            return Value(
                value_type=str(raw.get("value_type") or raw.get("type") or "string"),
                value=raw.get("value"), unit=raw.get("unit"), context=raw.get("context"),
            )
        if isinstance(raw, bool):
            return Value(value_type="boolean", value=raw)
        if isinstance(raw, int):
            return Value(value_type="integer", value=raw)
        if isinstance(raw, float):
            return Value(value_type="number", value=raw)
        return Value(value_type="string", value=str(raw))

    def _parse_result_json(self, text: str) -> Any:
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            stripped = text.strip()
            if stripped.startswith("```"):
                lines = stripped.splitlines()
                if lines and lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                try:
                    payload = json.loads("\n".join(lines))
                except json.JSONDecodeError:
                    payload = None
                if payload is not None:
                    self.warnings.append("stripped a Markdown fence around the provider result")
                    return payload
            raise CandidateMaterializationError(
                f"{self.result_filename} is not valid JSON: {exc}"
            ) from exc

    # ---------- entry ----------

    def materialize(self, artifacts: dict[str, str], *, provider: dict[str, Any] | None = None) -> MaterializationResult:
        if not isinstance(artifacts, dict) or not artifacts:
            raise CandidateMaterializationError("provider output is empty")
        paths = self.registry.assert_unique(list(artifacts))
        for path in paths:
            self.registry.claim(path, owner=PROVIDER_OWNER, purpose="provider_output")
        self.registry.claim("staging/kuyen_candidates.json", owner=KUYEN_OWNER, purpose="canonical_candidate")
        manifest: dict[str, Any] = {
            "contract": "kuyen-materialization-v1",
            "provider": dict(provider or {}),
            "artifacts": {
                path: {
                    "sha256": hashlib.sha256(artifacts[path].encode("utf-8")).hexdigest(),
                    "chars": len(artifacts[path]),
                }
                for path in paths
            },
            "path_ownership": self.registry.to_dict(),
            "provider_schema": None,
            "mode": None,
            "warnings": list(self.warnings),
            "decisions": [],
            "evidence": {},
            "coverage": {},
            "candidate_hash": None,
        }
        provider_result: dict[str, Any] | None = None
        if self.result_filename in artifacts:
            payload = self._parse_result_json(artifacts[self.result_filename])
            data = normalize_provider_result(payload)
            provider_result = data
            manifest["provider_schema"] = data["schema_version"]
            manifest["warnings"].extend(data["warnings"])
            bundle = self._structured_bundle(data)
            manifest["mode"] = "structured_provider_result"
        elif self._has_native_structured(artifacts):
            provider_result = None
            manifest["provider_schema"] = NATIVE_CONTRACT_ID
            bundle = self._native_structured_bundle(artifacts)
            manifest["mode"] = "native_structured"
        elif LEGACY_SIDECAR in artifacts:
            bundle = self._legacy_bundle(artifacts[LEGACY_SIDECAR])
            manifest["mode"] = "legacy_sidecar"
            manifest["warnings"].append("legacy sidecar read; evidence is verified by the KÜYEN validators")
        else:
            bundle = self._native_bundle(artifacts)
            manifest["mode"] = "native_fallback"
            manifest["warnings"].append("no structured result; native fallback cannot carry scalar assertions")
        manifest["decisions"] = [item.to_dict() for item in self.decisions]
        manifest["warnings"] = list(dict.fromkeys(list(self.warnings) + manifest["warnings"]))
        counts: dict[str, int] = {}
        for item in self.decisions:
            counts[item.classification] = counts.get(item.classification, 0) + 1
        manifest["evidence"] = counts
        manifest["coverage"] = self._coverage_summary(bundle)
        manifest["candidate_hash"] = self._candidate_hash(bundle)
        bundle.raw = {"provider_result": provider_result, "materialization": manifest}
        return MaterializationResult(bundle=bundle, manifest=manifest)

    def _structured_bundle(self, data: dict[str, Any]) -> CandidateBundle:
        entities: list[CandidateEntity] = []
        seen: set[str] = set()
        for raw in data["entities"]:
            provider_id = str(raw.get("provider_id") or raw.get("id") or "").strip()
            entity_type = str(raw.get("entity_type") or raw.get("type") or "").strip()
            name = str(raw.get("name") or raw.get("title") or provider_id).strip()
            if not provider_id or not entity_type:
                raise CandidateMaterializationError("entity requires provider_id and entity_type")
            if provider_id in seen:
                raise CandidateMaterializationError(
                    f"provider entity ID is duplicated: {provider_id}",
                    details={"provider_id": provider_id},
                )
            seen.add(provider_id)
            refs, sources = self._evidence_for_item("entity", provider_id, raw)
            entities.append(CandidateEntity(
                id=provider_id, name=name, entity_type=entity_type,
                aliases=[str(x) for x in (raw.get("aliases") or [])],
                description=str(raw.get("description") or ""),
                sources=sources, evidence_refs=refs, source_namespace="provider",
            ))
        relations: list[CandidateRelation] = []
        for raw in data["relations"]:
            source = str(raw.get("from") or "").strip()
            target = str(raw.get("to") or "").strip()
            predicate = str(raw.get("predicate") or raw.get("relation") or "").strip()
            if not source or not target or not predicate:
                raise CandidateMaterializationError("relation requires from, to and predicate")
            refs, sources = self._evidence_for_item("relation", f"{source}:{predicate}:{target}", raw)
            relations.append(CandidateRelation(
                from_entity=source, to_entity=target, relation=predicate,
                label=str(raw.get("label") or predicate),
                polarity=str(raw.get("polarity") or "POSITIVE"),
                scope=str(raw.get("scope") or "document"),
                temporal_scope=raw.get("temporal_scope"),
                temporal=TemporalScope.from_dict(raw.get("temporal")),
                evidence_refs=refs, sources=sources,
                # Predicate layer: copied verbatim, never invented. When the
                # provider omits it the fields stay None and the correspondence
                # policy in `kuyen.semantics` decides, explicitly and auditable.
                source_predicate=_text(raw.get("source_predicate")),
                canonical_predicate=_text(raw.get("canonical_predicate")),
                provider_predicate=_text(raw.get("provider_predicate")),
                display_label=_text(raw.get("display_label")),
                provider_label=_text(raw.get("provider_label")),
                mapping_status=_text(raw.get("mapping_status")),
                mapping_rule_id=_text(raw.get("mapping_rule_id")),
                mapping_version=_text(raw.get("mapping_version")),
                provider_projection_status=_text(raw.get("provider_projection_status")),
            ))
        assertions: list[CandidateAssertion] = []
        for raw in data["assertions"]:
            subject = str(raw.get("subject") or "").strip()
            predicate = str(raw.get("predicate") or "").strip()
            if not subject or not predicate:
                raise CandidateMaterializationError("assertion requires subject and predicate")
            value = self._value(raw.get("value"))
            object_entity = str(raw.get("object_entity") or "") or None
            if value is None and object_entity is None:
                raise CandidateMaterializationError("assertion requires value or object_entity")
            refs, sources = self._evidence_for_item("assertion", f"{subject}:{predicate}", raw)
            assertions.append(CandidateAssertion(
                subject=subject, predicate=predicate, object_entity=object_entity, value=value,
                polarity=str(raw.get("polarity") or "POSITIVE"),
                scope=str(raw.get("scope") or "document"),
                temporal_scope=raw.get("temporal_scope"),
                temporal=TemporalScope.from_dict(raw.get("temporal")),
                evidence_refs=refs, sources=sources,
                proposed_status=(str(raw.get("epistemic_status") or raw.get("proposed_status"))
                                 if (raw.get("epistemic_status") or raw.get("proposed_status")) else None),
            ))
        coverage = self._derive_coverage(entities, relations, assertions, data["coverage"])
        return CandidateBundle(
            entities=entities, relations=relations, assertions=assertions,
            evidence=list(self.evidence_pool.values()), coverage=coverage,
        )


    def _has_native_structured(self, artifacts: dict[str, str]) -> bool:
        if "relations.jsonl" in artifacts or "assertions.jsonl" in artifacts:
            return True
        return any(
            path.startswith("entities/") and path.endswith(".md")
            and (content.startswith("---\n") or re.match(r"^(id|provider_id)\s*:", content.lstrip("\n")))
            for path, content in artifacts.items()
        )

    def _jsonl_rows(self, text: str, name: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for line_number, line in enumerate(text.splitlines(), 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise CandidateMaterializationError(
                    f"{name} line {line_number} is not JSON: {exc}"
                ) from exc
            if not isinstance(row, dict):
                raise CandidateMaterializationError(f"{name} line {line_number} is not an object")
            rows.append(row)
        return rows


    def _parse_entity_header(self, content: str, path: str):
        try:
            return parse_frontmatter(content)
        except ValueError as exc:
            stripped = content.lstrip("\n")
            first = stripped.splitlines()[0] if stripped else ""
            if re.match(r"^(id|provider_id)\s*:", first):
                separator = stripped.find("\n---")
                if separator != -1:
                    import yaml

                    meta = yaml.safe_load(stripped[:separator]) or {}
                    if isinstance(meta, dict):
                        self.warnings.append(
                            f"{path}: opening frontmatter delimiter missing; parsed YAML header"
                        )
                        return meta, stripped[separator + 4:].lstrip("\n")
                import yaml

                try:
                    meta = yaml.safe_load(stripped)
                except yaml.YAMLError:
                    meta = None
                if isinstance(meta, dict) and meta.get("id") and meta.get("entity_type"):
                    self.warnings.append(
                        f"{path}: frontmatter delimiters missing; parsed the whole file as YAML"
                    )
                    return meta, ""
            raise CandidateMaterializationError(f"{path}: {exc}") from exc

    def _native_structured_bundle(self, artifacts: dict[str, str]) -> CandidateBundle:
        entities: list[CandidateEntity] = []
        seen: set[str] = set()
        for path, content in sorted(artifacts.items()):
            if not (path.startswith("entities/") and path.endswith(".md")):
                continue
            meta, body = self._parse_entity_header(content, path)
            provider_id = str(meta.get("id") or meta.get("provider_id") or "").strip()
            entity_type = str(meta.get("entity_type") or meta.get("type") or "").strip()
            if not provider_id or not entity_type:
                raise CandidateMaterializationError(f"{path}: entity requires id and entity_type")
            if provider_id in seen:
                raise CandidateMaterializationError(
                    f"provider entity ID is duplicated: {provider_id}",
                    details={"provider_id": provider_id, "path": path},
                )
            seen.add(provider_id)
            evidence = meta.get("evidence") or []
            if not isinstance(evidence, list):
                evidence = [evidence]
            refs, sources = self._evidence_for_item("entity", provider_id, {**meta, "evidence": evidence})
            aliases = meta.get("aliases") or []
            aliases = [aliases] if isinstance(aliases, str) else [str(item) for item in aliases]
            entities.append(CandidateEntity(
                id=provider_id, name=str(meta.get("name") or meta.get("title") or provider_id),
                entity_type=entity_type, aliases=aliases,
                description=str(meta.get("description") or body.strip()),
                sources=sources, evidence_refs=refs, source_namespace="provider",
            ))
        relations: list[CandidateRelation] = []
        for row in self._jsonl_rows(artifacts.get("relations.jsonl", ""), "relations.jsonl"):
            source = str(row.get("from") or "").strip()
            target = str(row.get("to") or "").strip()
            predicate = str(row.get("relation") or row.get("predicate") or "").strip()
            if not source or not target or not predicate:
                raise CandidateMaterializationError("relations.jsonl row requires from, to and relation")
            evidence = row.get("evidence") or []
            if not isinstance(evidence, list):
                evidence = [evidence]
            refs, sources = self._evidence_for_item("relation", f"{source}:{predicate}:{target}", {**row, "evidence": evidence})
            relations.append(CandidateRelation(
                from_entity=source, to_entity=target, relation=predicate,
                label=str(row.get("label") or predicate),
                polarity=str(row.get("polarity") or "POSITIVE"),
                scope=str(row.get("scope") or "document"),
                temporal_scope=row.get("temporal_scope"),
                temporal=TemporalScope.from_dict(row.get("temporal")),
                evidence_refs=refs, sources=sources,
            ))
        assertions: list[CandidateAssertion] = []
        for row in self._jsonl_rows(artifacts.get("assertions.jsonl", ""), "assertions.jsonl"):
            subject = str(row.get("subject") or "").strip()
            predicate = str(row.get("predicate") or "").strip()
            if not subject or not predicate:
                raise CandidateMaterializationError("assertions.jsonl row requires subject and predicate")
            value = self._value(row.get("value"))
            object_entity = str(row.get("object_entity") or "") or None
            if value is None and object_entity is None:
                raise CandidateMaterializationError("assertions.jsonl row requires value or object_entity")
            evidence = row.get("evidence") or []
            if not isinstance(evidence, list):
                evidence = [evidence]
            refs, sources = self._evidence_for_item("assertion", f"{subject}:{predicate}", {**row, "evidence": evidence})
            assertions.append(CandidateAssertion(
                subject=subject, predicate=predicate, object_entity=object_entity, value=value,
                polarity=str(row.get("polarity") or "POSITIVE"),
                scope=str(row.get("scope") or "document"),
                temporal_scope=row.get("temporal_scope"),
                temporal=TemporalScope.from_dict(row.get("temporal")),
                evidence_refs=refs, sources=sources,
                proposed_status=(str(row.get("epistemic_status") or row.get("proposed_status"))
                                 if (row.get("epistemic_status") or row.get("proposed_status")) else None),
            ))
        if not entities:
            raise CandidateMaterializationError("native structured output contains no entity files")
        coverage_data: list[dict[str, Any]] = []
        if "coverage.json" in artifacts:
            try:
                payload = json.loads(artifacts["coverage.json"])
            except json.JSONDecodeError as exc:
                self.warnings.append(f"coverage.json ignored: {exc}")
            else:
                if isinstance(payload, dict):
                    payload = payload.get("coverage") or []
                if isinstance(payload, list):
                    coverage_data = [item for item in payload if isinstance(item, dict)]
        coverage = self._derive_coverage(entities, relations, assertions, coverage_data)
        return CandidateBundle(
            entities=entities, relations=relations, assertions=assertions,
            evidence=list(self.evidence_pool.values()), coverage=coverage,
        )

    # ---------- legacy and native fallback ----------

    def _legacy_bundle(self, text: str) -> CandidateBundle:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise CandidateMaterializationError(f"legacy sidecar is not valid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise CandidateMaterializationError("legacy sidecar must be a JSON object")
        return CandidateBundle.from_dict(payload)

    def _native_bundle(self, artifacts: dict[str, str]) -> CandidateBundle:
        entities: list[CandidateEntity] = []
        relations: list[CandidateRelation] = []
        for path, content in sorted(artifacts.items()):
            if path.startswith("entities/") and path.endswith(".md"):
                meta, body = parse_frontmatter(content)
                provider_id = str(meta.get("id") or "").strip()
                entity_type = str(meta.get("entity_type") or "").strip()
                if not provider_id or not entity_type:
                    self.warnings.append(f"{path}: not a native entity frontmatter; skipped")
                    continue
                sources = meta.get("sources") or []
                sources = [sources] if isinstance(sources, str) else [str(x) for x in sources]
                aliases = meta.get("aliases") or []
                aliases = [aliases] if isinstance(aliases, str) else [str(x) for x in aliases]
                entities.append(CandidateEntity(
                    id=provider_id, name=str(meta.get("title") or meta.get("name") or provider_id),
                    entity_type=entity_type, aliases=aliases,
                    description=str(meta.get("description") or body.strip()),
                    sources=sources, evidence_refs=[], source_namespace="provider",
                ))
                self._record("entity", provider_id, DOCUMENT_REFERENCE, "native artifact carries only sources")
        relation_text = artifacts.get("relations.jsonl")
        if relation_text:
            for line_number, line in enumerate(relation_text.splitlines(), 1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise CandidateMaterializationError(
                        f"relations.jsonl line {line_number} is not JSON: {exc}"
                    ) from exc
                if not isinstance(row, dict):
                    raise CandidateMaterializationError(f"relations.jsonl line {line_number} is not an object")
                source = str(row.get("from") or "")
                target = str(row.get("to") or "")
                predicate = str(row.get("relation") or "")
                if not source or not target or not predicate:
                    raise CandidateMaterializationError(f"relations.jsonl line {line_number} misses endpoints")
                sources = row.get("evidence") or []
                sources = [sources] if isinstance(sources, str) else [str(x) for x in sources]
                relations.append(CandidateRelation(
                    from_entity=source, to_entity=target, relation=predicate,
                    label=str(row.get("label") or predicate), sources=sources,
                    evidence_refs=[],
                ))
                self._record("relation", f"{source}:{predicate}:{target}", DOCUMENT_REFERENCE, "native relation carries only sources")
        coverage = self._derive_coverage(entities, relations, [], [])
        return CandidateBundle(entities=entities, relations=relations, assertions=[], evidence=[], coverage=coverage)

    # ---------- coverage ----------

    def _derive_coverage(
        self,
        entities: list[CandidateEntity],
        relations: list[CandidateRelation],
        assertions: list[CandidateAssertion],
        provider_coverage: list[dict[str, Any]],
    ) -> list[CoverageUnit]:
        if not self.coverage_inventory:
            return []
        known_units = {
            unit.unit_id
            for units in self.coverage_inventory.values()
            for unit in units
        }
        claims: dict[str, dict[str, Any]] = {}
        unknown: list[str] = []
        for raw in provider_coverage:
            unit_id = str(raw.get("unit_id") or "").strip()
            if not unit_id:
                continue
            if unit_id not in known_units:
                unknown.append(unit_id)
                continue
            claims[unit_id] = raw
        if unknown:
            self.warnings.append(f"provider coverage contained unknown units: {sorted(set(unknown))}")
        self._coverage_unknown = sorted(set(unknown))
        result: list[CoverageUnit] = []
        for mapu_id, units in self.coverage_inventory.items():
            mapu = self.mapus.get(mapu_id)
            if mapu is None:
                continue
            for unit in units:
                in_unit = [
                    item for item in self.evidence_pool.values()
                    if item.mapu_id == mapu_id and item.char_start is not None
                    and unit.char_start <= item.char_start < unit.char_end
                ]
                entity_ids: set[str] = set()
                for evidence in in_unit:
                    for entity in entities:
                        if evidence.evidence_id in entity.evidence_refs:
                            entity_ids.add(entity.id)
                    for relation in relations:
                        if evidence.evidence_id in relation.evidence_refs:
                            entity_ids.add(relation.from_entity)
                            entity_ids.add(relation.to_entity)
                    for assertion in assertions:
                        if evidence.evidence_id in assertion.evidence_refs:
                            entity_ids.add(assertion.subject)
                claim = claims.get(unit.unit_id) or {}
                claimed_state = str(claim.get("state") or "").upper()
                reason = claim.get("reason")
                if entity_ids:
                    state = CoverageState.PROCESSED_WITH_OUTPUT
                    reason = None
                elif claimed_state == "PROCESSED_NO_GRAPH_FACTS":
                    state = CoverageState.PROCESSED_NO_GRAPH_FACTS
                elif claimed_state == "SKIPPED_WITH_REASON":
                    state = CoverageState.SKIPPED_WITH_REASON
                elif claimed_state == "FAILED":
                    state = CoverageState.FAILED
                elif claimed_state == "PROCESSED_WITH_OUTPUT":
                    state = CoverageState.PROCESSED_NO_GRAPH_FACTS
                    reason = "provider claimed output but no verified evidence falls in this unit"
                else:
                    state = CoverageState.NOT_ATTEMPTED
                    reason = None
                result.append(CoverageUnit(
                    source_uri=mapu.source_uri, mapu_id=mapu_id, unit_id=unit.unit_id,
                    state=state, section=unit.section, content_sha256=unit.content_sha256,
                    entity_ids=sorted(entity_ids), relation_ids=[], reason=reason,
                ))
        return result

    def _coverage_summary(self, bundle: CandidateBundle) -> dict[str, Any]:
        states: dict[str, int] = {}
        for unit in bundle.coverage:
            states[unit.state.value] = states.get(unit.state.value, 0) + 1
        return {
            "inventory_units": sum(len(units) for units in self.coverage_inventory.values()),
            "ledger_units": len(bundle.coverage),
            "states": states,
            "unknown_provider_units": getattr(self, "_coverage_unknown", []),
            "derived_from": "evidence_spans + provider hints for no-fact/skip/fail",
        }

    @staticmethod
    def _candidate_hash(bundle: CandidateBundle) -> str:
        from ..canonical import canonical_json

        payload = {
            "entities": [
                {"id": item.id, "name": item.name, "entity_type": item.entity_type,
                 "aliases": item.aliases, "description": item.description,
                 "sources": item.sources, "evidence_refs": item.evidence_refs,
                 "source_namespace": item.source_namespace}
                for item in sorted(bundle.entities, key=lambda x: x.id)
            ],
            "relations": [
                {"from": item.from_entity, "to": item.to_entity, "relation": item.relation,
                 "label": item.label, "polarity": item.polarity, "scope": item.scope,
                 "temporal_scope": item.temporal_scope, "temporal": item.temporal.to_dict() if item.temporal else None,
                 "evidence_refs": item.evidence_refs}
                for item in bundle.relations
            ],
            "assertions": [
                {"subject": item.subject, "predicate": item.predicate, "value": item.value.to_dict() if item.value else None,
                 "polarity": item.polarity, "scope": item.scope, "temporal_scope": item.temporal_scope,
                 "evidence_refs": item.evidence_refs}
                for item in bundle.assertions
            ],
            "evidence": [item.to_dict() for item in bundle.evidence],
            "coverage": [item.to_dict() for item in bundle.coverage],
        }
        return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
