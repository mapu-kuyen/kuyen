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
# The quote decided the span and the declared offsets disagreed with it. The evidence is
# kept and the declared hint is recorded; nothing is silently "fixed" (KUYEN_PRODUCTIVE_GRAPH_11, §5.2).
QUOTE_AUTHORITATIVE = "QUOTE_AUTHORITATIVE"
# Declared offsets were not even a usable span (not integers, negative or reversed).
DECLARED_OFFSET_IGNORED = "DECLARED_OFFSET_IGNORED"
DOCUMENT_REFERENCE = "DOCUMENT_REFERENCE"
AMBIGUOUS_QUOTE = "AMBIGUOUS_QUOTE"
INVALID_QUOTE = "INVALID_QUOTE"
INVALID_OFFSET = "INVALID_OFFSET"
INVALID_HASH = "INVALID_HASH"
URI_MISMATCH = "URI_MISMATCH"
UNSUPPORTED_UNIT = "UNSUPPORTED_OFFSET_UNIT"
SOURCE_UNKNOWN = "SOURCE_UNKNOWN"
NO_EVIDENCE = "NO_EVIDENCE"
# KÜYEN owns MAPU identity: a declared MAPU that is not in this context is refused
# instead of being replaced by the context's only MAPU (KUYEN_PRODUCTIVE_GRAPH_11, §5.1).
MAPU_ID_NOT_IN_CONTEXT = "MAPU_ID_NOT_IN_CONTEXT"
MAPU_RESOLVED_BY_CONTEXT = "MAPU_RESOLVED_BY_CONTEXT"
SOURCE_UNIT_MISMATCH = "SOURCE_UNIT_MISMATCH"
# No declared polarity, or a polarity the canonical set cannot carry: the object is not
# admitted instead of becoming POSITIVE (KUYEN_PRODUCTIVE_GRAPH_11, §5.3).
POLARITY_UNKNOWN = "POLARITY_UNKNOWN"
MODALITY_UNRECOGNIZED = "MODALITY_UNRECOGNIZED"
# Evidence read without MAPU context: preserved, never presented as verified.
DECLARED_UNVERIFIED = "DECLARED_UNVERIFIED"

CANONICAL_POLARITIES = ("POSITIVE", "NEGATIVE")
MODALITIES = ("FACT", "FORECAST", "ESTIMATE", "OPINION", "CONDITIONAL", "UNKNOWN")

# The policy every materialized object is admitted under. Recorded in the manifest so a
# reader never has to guess which rule produced the offsets or the polarity.
EVIDENCE_POLICY = {
    "mapu_identity": "context-authority-v1",
    "offsets": "quote-authority-v1",
    "polarity": "explicit-only-v1",
    "modality": "declared-or-unknown-v1",
    "source_unit": "verified-when-declared-v1",
}


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
        mapus: list[Mapu] | None,
        antu: Antu | None = None,
        coverage_inventory: dict[str, list[SectionUnit]] | None = None,
        contract: str = CONTRACT_ID,
        result_filename: str = RESULT_FILENAME,
        verify_evidence: bool = True,
    ) -> None:
        if verify_evidence and not mapus:
            raise CandidateMaterializationError("materialization requires at least one MAPU")
        self.mapus = {item.mapu_id: item for item in (mapus or [])}
        self.antu = antu
        # Without MAPU context evidence cannot be verified. It is still *preserved* and
        # marked NOT_EVALUATED instead of being dropped: the deprecated compatibility
        # reader keeps every declared quote, offset and hash so nothing is lost
        # (KUYEN_PRODUCTIVE_GRAPH_11, §5.5).
        self.verify_evidence = verify_evidence
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

    def _mapu_for(self, raw: dict[str, Any]) -> tuple[Mapu | None, str | None]:
        """Resolve the MAPU an evidence entry belongs to, without guessing an identity.

        A declared `mapu_id` is authoritative in the sense that KÜYEN *checks* it: when
        the producer names a MAPU that is not in this context the entry is refused with
        `MAPU_ID_NOT_IN_CONTEXT` and the single-MAPU fallback never runs. When no identity
        is declared at all, the URI decides, and KÜYEN records that it resolved the MAPU
        from the context instead of presenting it as a declaration
        (KUYEN_PRODUCTIVE_GRAPH_11, §5.1).
        """
        declared = str(raw.get("mapu_id") or "").strip()
        uri = str(raw.get("source_uri") or "").strip()
        if declared:
            return (self.mapus[declared], None) if declared in self.mapus \
                else (None, MAPU_ID_NOT_IN_CONTEXT)
        for mapu in sorted(self.mapus.values(), key=lambda item: item.mapu_id):
            root = mapu.source_uri.rstrip("/")
            if uri == root or uri.startswith(root + "/"):
                return mapu, MAPU_RESOLVED_BY_CONTEXT
        if len(self.mapus) == 1:
            return next(iter(self.mapus.values())), MAPU_RESOLVED_BY_CONTEXT
        return None, SOURCE_UNKNOWN

    def _locate_quote(self, content: str, quote: str, context: str | None) -> list[int]:
        """Every occurrence of `quote`, narrowed by `context` when it is ambiguous."""
        occurrences: list[int] = []
        position = content.find(quote)
        while position != -1:
            occurrences.append(position)
            position = content.find(quote, position + 1)
        if len(occurrences) <= 1 or not context:
            return occurrences
        return [position for position in occurrences
                if context in content[max(0, position - len(context)):position + len(quote) + len(context)]]

    def _source_unit_problem(self, mapu: Mapu, raw: dict[str, Any], start: int, end: int) -> str | None:
        """Verify that a declared SOURCE_UNIT really contains the resolved span."""
        declared = str(raw.get("source_unit_id") or "").strip()
        if not declared:
            return None
        units = self.coverage_inventory.get(mapu.mapu_id) or []
        if not units:
            return None
        candidates = [unit for unit in units if getattr(unit, "unit_id", None) == declared]
        if not candidates:
            return f"declared SOURCE_UNIT {declared} is not in the inventory of MAPU {mapu.mapu_id}"
        unit_start = getattr(candidates[0], "char_start", None)
        unit_end = getattr(candidates[0], "char_end", None)
        if not isinstance(unit_start, int) or not isinstance(unit_end, int):
            return None
        if not (unit_start <= start and end <= unit_end):
            return (f"resolved span {start}:{end} is outside SOURCE_UNIT {declared} "
                    f"({unit_start}:{unit_end})")
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
        if not self.verify_evidence:
            return self._declared_evidence(kind, item_id, raw)
        mapu, mapu_resolution = self._mapu_for(raw)
        quote = str(raw.get("quote") or "")
        uri = str(raw.get("source_uri") or "")
        provided_sha = str(raw.get("source_sha256") or "")
        unit = str(raw.get("offset_unit") or "unicode_codepoint")
        declared_unit = str(raw.get("source_unit_id") or "").strip() or None
        if unit != "unicode_codepoint":
            self._record(kind, item_id, UNSUPPORTED_UNIT, f"offset_unit={unit}")
            return None
        if not quote:
            if mapu is not None and (uri or raw.get("sources")):
                self._record(kind, item_id, DOCUMENT_REFERENCE, "URI only; not a quote", mapu=mapu)
            else:
                self._record(kind, item_id, NO_EVIDENCE, "no quote or source URI", mapu=mapu)
            return None
        if mapu_resolution == MAPU_ID_NOT_IN_CONTEXT:
            self._record(kind, item_id, MAPU_ID_NOT_IN_CONTEXT,
                         f"declared mapu_id={raw.get('mapu_id')!r} is not in this context",
                         quote=quote)
            return None
        if mapu is None:
            self._record(kind, item_id, SOURCE_UNKNOWN, "no MAPU matches the evidence", quote=quote)
            return None
        if mapu_resolution == MAPU_RESOLVED_BY_CONTEXT:
            self._record(kind, item_id, MAPU_RESOLVED_BY_CONTEXT,
                         "no MAPU identity declared; resolved from the context", mapu=mapu, quote=quote)
        if provided_sha and provided_sha != mapu.sha256:
            self._record(kind, item_id, INVALID_HASH, "source_sha256 does not match the MAPU", mapu=mapu, quote=quote)
            return None
        root = mapu.source_uri.rstrip("/")
        if uri and not (uri == root or uri.startswith(root + "/")):
            self._record(kind, item_id, URI_MISMATCH, "source_uri is outside the MAPU resource", mapu=mapu, quote=quote)
            return None

        # The quote is the authority: it is located deterministically and the declared
        # offsets are kept as auxiliary information, never as the address of the evidence.
        declared_start, declared_end = raw.get("char_start"), raw.get("char_end")
        declared_hint = None
        if declared_start is not None or declared_end is not None:
            declared_hint = {"char_start": declared_start, "char_end": declared_end}
        occurrences = self._locate_quote(mapu.content, quote, raw.get("context"))
        if not occurrences:
            self._record(kind, item_id, INVALID_QUOTE,
                         "quote does not occur in the MAPU; declared offsets are not authority",
                         mapu=mapu, quote=quote)
            return None
        if len(occurrences) > 1:
            self._record(kind, item_id, AMBIGUOUS_QUOTE,
                         f"quote occurs {len(occurrences)} times and the context does not disambiguate it",
                         mapu=mapu, quote=quote)
            return None
        start = occurrences[0]
        end = start + len(quote)
        reason: str | None = None
        extraction = "llm"
        if declared_hint is None:
            classification = OFFSET_RESOLVED_UNIQUE
            extraction = "llm_offset_resolved_unique"
            reason = "offsets absent; unique quote located deterministically"
        elif not (isinstance(declared_start, int) and isinstance(declared_end, int)) \
                or declared_start < 0 or declared_end < declared_start:
            classification = DECLARED_OFFSET_IGNORED
            extraction = "llm_offset_resolved_declared_ignored"
            reason = ("declared offsets are not a usable span; the deterministic location of the "
                      "unique quote is the address of the evidence")
        elif (declared_start, declared_end) == (start, end):
            classification = EXACT_SPAN
        else:
            classification = QUOTE_AUTHORITATIVE
            extraction = "llm_offset_resolved_quote_authority"
            reason = (f"declared offsets {declared_start}:{declared_end} disagree with the quote, which "
                      f"occurs exactly once at {start}:{end}; declared offsets are recorded as auxiliary")
        source_unit_problem = self._source_unit_problem(mapu, raw, start, end)
        if source_unit_problem is not None:
            self._record(kind, item_id, SOURCE_UNIT_MISMATCH, source_unit_problem,
                         mapu=mapu, quote=quote, start=start, end=end)
            return None
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
            context=raw.get("context"), source_unit_id=declared_unit,
            declared_offsets=declared_hint,
        )
        self.evidence_pool.setdefault(evidence_id, evidence)
        existing = self.evidence_pool[evidence_id]
        if existing is not evidence:
            # The same verified span declared twice is one evidence record. Auxiliary
            # hints are merged, never dropped: the record keeps every declaration.
            if evidence.source_unit_id and not existing.source_unit_id:
                existing.source_unit_id = evidence.source_unit_id
            if evidence.context and not existing.context:
                existing.context = evidence.context
            if evidence.declared_offsets and not existing.declared_offsets:
                existing.declared_offsets = evidence.declared_offsets
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

    def _declared_evidence(self, kind: str, item_id: str, raw: dict[str, Any]) -> CandidateEvidence | None:
        """Keep a declared evidence entry exactly as proposed, without claiming verification.

        This is the only path that produces evidence without a MAPU context (the
        deprecated `read_candidate` compatibility reader). Nothing is discarded and
        nothing is upgraded: `validation_status` stays NOT_EVALUATED and the decision
        says why.
        """
        quote = str(raw.get("quote") or "")
        uri = str(raw.get("source_uri") or "")
        mapu_id = str(raw.get("mapu_id") or "")
        if not quote and not uri:
            self._record(kind, item_id, NO_EVIDENCE, "no quote or source URI")
            return None
        declared_start, declared_end = raw.get("char_start"), raw.get("char_end")
        evidence_id = stable_id(
            "ev",
            {"mapu_id": mapu_id, "source_sha256": str(raw.get("source_sha256") or ""),
             "source_uri": uri, "start": declared_start, "end": declared_end, "quote": quote},
        )
        evidence = CandidateEvidence(
            evidence_id=evidence_id, mapu_id=mapu_id, source_uri=uri,
            source_sha256=str(raw.get("source_sha256") or ""), quote=quote,
            char_start=declared_start if isinstance(declared_start, int) else -1,
            char_end=declared_end if isinstance(declared_end, int) else -1,
            extraction_method="declared_unverified", validation_status="NOT_EVALUATED",
            context=raw.get("context"),
            source_unit_id=str(raw.get("source_unit_id") or "") or None,
            declared_offsets=({"char_start": declared_start, "char_end": declared_end}
                              if declared_start is not None or declared_end is not None else None),
        )
        self.evidence_pool.setdefault(evidence_id, evidence)
        self._record(kind, item_id, DECLARED_UNVERIFIED,
                     "no MAPU context: evidence preserved as declared, verification not claimed",
                     evidence_id=evidence_id, quote=quote,
                     start=evidence.char_start if evidence.char_start >= 0 else None,
                     end=evidence.char_end if evidence.char_end >= 0 else None)
        return evidence

    def _admit_polarity(self, kind: str, item_id: str, raw: dict[str, Any]) -> str | None:
        """Return the polarity to store, or None when the object cannot be admitted.

        Absence is never turned into POSITIVE: the object stays out of the canonical set
        and the reason is recorded in the materialization manifest
        (KUYEN_PRODUCTIVE_GRAPH_11, §5.3).
        """
        declared = _text(raw.get("polarity"))
        if not self.verify_evidence:
            # Compatibility reader: the candidate domain can represent UNKNOWN, so the
            # declared value is preserved as-is and no admission decision is taken here.
            return declared.upper() if declared else "UNKNOWN"
        if declared is None:
            self._record(kind, item_id, POLARITY_UNKNOWN,
                         "no polarity declared; the object is not admitted to the canonical set")
            return None
        declared = declared.upper()
        if declared not in CANONICAL_POLARITIES:
            self._record(kind, item_id, POLARITY_UNKNOWN,
                         f"polarity {declared!r} cannot be stored in the canonical set; "
                         "the object stays pending")
            return None
        return declared

    def _modality(self, kind: str, item_id: str, raw: dict[str, Any]) -> str:
        """Declared modality, or UNKNOWN. A claim is never assumed to be a fact."""
        declared = _text(raw.get("modality"))
        if declared is None:
            return "UNKNOWN"
        declared = declared.upper()
        if declared not in MODALITIES:
            self._record(kind, item_id, MODALITY_UNRECOGNIZED,
                         f"modality {declared!r} is not part of the contract; recorded as UNKNOWN")
            return "UNKNOWN"
        return declared

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
            "evidence_policy": dict(EVIDENCE_POLICY),
            "warnings": list(self.warnings),
            "decisions": [],
            "evidence": {},
            "coverage": {},
            "candidate_hash": None,
        }
        provider_result: dict[str, Any] | None = None
        if self.result_filename in artifacts:
            try:
                payload = self._parse_result_json(artifacts[self.result_filename])
                data = normalize_provider_result(payload)
            except CandidateMaterializationError as exc:
                # A malformed aggregate result must not destroy a valid native tree. The
                # defect is recorded, not hidden, and the tree is the contract the Skill
                # actually writes (measured in a real compilation, KUYEN_PRODUCTIVE_GRAPH_11).
                if not self._has_native_structured(artifacts):
                    raise
                manifest["warnings"].append(
                    f"{self.result_filename} ignored: {exc.message}")
                manifest["provider_schema"] = NATIVE_CONTRACT_ID
                manifest["structured_result_ignored"] = {
                    "artifact": self.result_filename, "reason": exc.message}
                bundle = self._native_structured_bundle(artifacts)
                manifest["mode"] = "native_structured_after_invalid_structured_result"
            else:
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
            polarity = self._admit_polarity("relation", f"{source}:{predicate}:{target}", raw)
            if polarity is None:
                continue
            relations.append(CandidateRelation(
                from_entity=source, to_entity=target, relation=predicate,
                label=str(raw.get("label") or predicate),
                polarity=polarity,
                scope=str(raw.get("scope") or "document"),
                temporal_scope=raw.get("temporal_scope"),
                temporal=TemporalScope.from_dict(raw.get("temporal")),
                evidence_refs=refs, sources=sources,
                modality=self._modality("relation", f"{source}:{predicate}:{target}", raw),
                attribution=_text(raw.get("attribution")),
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
            polarity = self._admit_polarity("assertion", f"{subject}:{predicate}", raw)
            if polarity is None:
                continue
            assertions.append(CandidateAssertion(
                subject=subject, predicate=predicate, object_entity=object_entity, value=value,
                polarity=polarity,
                scope=str(raw.get("scope") or "document"),
                temporal_scope=raw.get("temporal_scope"),
                temporal=TemporalScope.from_dict(raw.get("temporal")),
                evidence_refs=refs, sources=sources,
                proposed_status=(str(raw.get("epistemic_status") or raw.get("proposed_status"))
                                 if (raw.get("epistemic_status") or raw.get("proposed_status")) else None),
                modality=self._modality("assertion", f"{subject}:{predicate}", raw),
                attribution=_text(raw.get("attribution")),
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
            item_id = f"{source}:{predicate}:{target}"
            polarity = self._admit_polarity("relation", item_id, row)
            if polarity is None:
                continue
            relations.append(CandidateRelation(
                from_entity=source, to_entity=target, relation=predicate,
                label=str(row.get("label") or predicate),
                polarity=polarity,
                scope=str(row.get("scope") or "document"),
                temporal_scope=row.get("temporal_scope"),
                temporal=TemporalScope.from_dict(row.get("temporal")),
                evidence_refs=refs, sources=sources,
                # The native row declares the predicate the producer chose. Recording it as
                # the *source* predicate is not an invention: it is what the producer wrote,
                # and it is what lets KÜYEN preserve a term its ontology does not know as an
                # explicit UNMAPPED projection instead of refusing the whole candidate
                # (measured in a live OpenViking 0.5.0 compilation, KUYEN_PRODUCTIVE_GRAPH_11).
                source_predicate=_text(row.get("source_predicate")) or predicate,
                canonical_predicate=_text(row.get("canonical_predicate")) or predicate,
                provider_predicate=_text(row.get("provider_predicate")),
                display_label=_text(row.get("display_label")),
                provider_label=_text(row.get("provider_label")),
                mapping_status=_text(row.get("mapping_status")),
                mapping_rule_id=_text(row.get("mapping_rule_id")),
                mapping_version=_text(row.get("mapping_version")),
                provider_projection_status=_text(row.get("provider_projection_status")),
                modality=self._modality("relation", item_id, row),
                attribution=_text(row.get("attribution")),
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
            item_id = f"{subject}:{predicate}"
            refs, sources = self._evidence_for_item("assertion", item_id, {**row, "evidence": evidence})
            polarity = self._admit_polarity("assertion", item_id, row)
            if polarity is None:
                continue
            assertions.append(CandidateAssertion(
                subject=subject, predicate=predicate, object_entity=object_entity, value=value,
                polarity=polarity,
                scope=str(row.get("scope") or "document"),
                temporal_scope=row.get("temporal_scope"),
                temporal=TemporalScope.from_dict(row.get("temporal")),
                evidence_refs=refs, sources=sources,
                proposed_status=(str(row.get("epistemic_status") or row.get("proposed_status"))
                                 if (row.get("epistemic_status") or row.get("proposed_status")) else None),
                modality=self._modality("assertion", item_id, row),
                attribution=_text(row.get("attribution")),
                # the native row declares the assertion predicate: preserved, never invented
                source_predicate=_text(row.get("source_predicate")) or predicate,
                canonical_predicate=_text(row.get("canonical_predicate")) or predicate,
                mapping_status=_text(row.get("mapping_status")),
                mapping_rule_id=_text(row.get("mapping_rule_id")),
                mapping_version=_text(row.get("mapping_version")),
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
