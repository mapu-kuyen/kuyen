"""Structural validation of a canonical document (the object that is committed).

KUYEN_PACKAGE_HARDENING_01, finding A1. The canonical path — `build_document` →
`import_canonical`, and the Antü merge — works with plain dictionaries, while
`validators.py` validates the typed candidate graph (`EvidenceValidator`,
`GraphStructuralValidator`). Because that dictionary path did not run those rules, the
public ingestion boundary accepted fake evidence, objects that declared SOURCE_VERIFIED
support without evidence, and duplicated identities.

This module applies the *same* rules to canonical dictionaries. It introduces no new
semantics: it enforces what DATA_MODEL.md already states ("a quote that does not appear at
its offsets is rejected"; every object carries evidence and an explicit support status) and
what the two validators above already implement for the candidate graph.
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Iterable, Mapping, Sequence

from ..semantics import origin as origins

VERIFIED_STATUS = "SOURCE_VERIFIED"
MODALITIES = {"FACT", "FORECAST", "ESTIMATE", "OPINION", "CONDITIONAL", "UNKNOWN"}
CANONICAL_POLARITIES = {"POSITIVE", "NEGATIVE"}

# label, canonical collection, identity field
OBJECT_COLLECTIONS: tuple[tuple[str, str, str], ...] = (
    ("entity", "entities", "entity_id"),
    ("relation", "relations", "relation_id"),
    ("assertion", "assertions", "assertion_id"),
    ("evidence", "evidence", "evidence_id"),
)


def _as_list(value: Any) -> list[Mapping[str, Any]]:
    return [item for item in (value or [])]


def _duplicate_problems(label: str, items: Sequence[Mapping[str, Any]], field: str,
                        base_ids: Mapping[str, Iterable[str]] | None) -> list[str]:
    problems: list[str] = []
    for value, count in Counter(item.get(field) for item in items).items():
        if value is not None and count > 1:
            problems.append(f"DUPLICATE_ID: {label} {value} appears {count} times")
    if base_ids:
        known = set(base_ids.get(f"{label}_ids") or ())
        for item in items:
            if item.get(field) in known:
                problems.append(
                    f"DUPLICATE_ID: {label} {item.get(field)} already exists in the base version")
    return problems


def _evidence_problems(evidence: Mapping[str, Any],
                       mapus: Mapping[str, Mapping[str, Any]]) -> list[str]:
    """EvidenceValidator's rules, applied to the canonical dictionaries."""
    identifier = evidence.get("evidence_id")
    mapu = mapus.get(evidence.get("mapu_id"))
    if mapu is None:
        return [f"EVIDENCE_SOURCE_UNKNOWN: {identifier} cites MAPU {evidence.get('mapu_id')!r}"]
    content = str(mapu.get("content") or "")
    start, end = evidence.get("char_start"), evidence.get("char_end")
    if not isinstance(start, int) or not isinstance(end, int):
        return [f"EVIDENCE_OFFSET_INVALID: {identifier} has no integer offsets"]
    if start < 0 or end < start:
        return [f"EVIDENCE_OFFSET_INVALID: {identifier} declares offsets {start}:{end}"]
    if end > len(content):
        return [f"EVIDENCE_OFFSET_OUT_OF_RANGE: {identifier} end {end} exceeds the source length {len(content)}"]
    problems: list[str] = []
    quote = evidence.get("quote")
    if not quote:
        problems.append(f"EVIDENCE_QUOTE_EMPTY: {identifier} has no quote")
    elif content[start:end] != quote:
        problems.append(
            f"EVIDENCE_QUOTE_MISMATCH: {identifier} does not match the source at {start}:{end}")
    declared_hash = evidence.get("source_sha256")
    if declared_hash and declared_hash != mapu.get("content_sha256"):
        problems.append(
            f"EVIDENCE_HASH_MISMATCH: {identifier} declares a source hash that is not the MAPU hash")
    declared_uri = evidence.get("source_uri")
    if declared_uri and mapu.get("source_uri") and declared_uri != mapu.get("source_uri"):
        problems.append(
            f"EVIDENCE_URI_MISMATCH: {identifier} cites a different source_uri than its MAPU")
    return problems


def _verification_problems(objects: Iterable[tuple[str, str, Sequence[Mapping[str, Any]]]]) -> list[str]:
    """A declared verification status requires evidence (ASSERTION_EVIDENCE_MISSING)."""
    problems: list[str] = []
    for label, field, items in objects:
        reported: set[Any] = set()
        for item in items:
            identifier = item.get(field)
            if identifier in reported:
                continue
            for key in ("status", "evidence_status"):
                if str(item.get(key) or "").upper() == VERIFIED_STATUS and not _as_list(item.get("evidence_ids")):
                    problems.append(
                        f"EVIDENCE_MISSING: {label} {identifier} declares {key}={VERIFIED_STATUS} "
                        "without evidence")
                    reported.add(identifier)
                    break
    return problems


def _semantic_problems(label: str, items: Sequence[Mapping[str, Any]]) -> list[str]:
    """Origin and modality constraints of a canonical statement (brief §4 and §5.4)."""
    problems: list[str] = []
    for item in items:
        identifier = item.get("assertion_id") or item.get("relation_id") or item.get("entity_id")
        record = item.get("origin")
        problems.extend(origins.problems(
            record, status=item.get("status"), evidence_status=item.get("evidence_status"),
            label=label, identifier=identifier))
        polarity = item.get("polarity")
        if polarity is not None and str(polarity).upper() not in CANONICAL_POLARITIES:
            problems.append(
                f"POLARITY_NOT_ADMITTED: {label} {identifier} declares polarity {polarity!r}; "
                "the canonical set only carries POSITIVE or NEGATIVE")
        modality = item.get("modality")
        if modality is not None and str(modality).upper() not in MODALITIES:
            problems.append(
                f"MODALITY_INVALID: {label} {identifier} declares modality {modality!r}")
    return problems


def validate_canonical_objects(*, entities: Any = (), relations: Any = (), assertions: Any = (),
                               evidence: Any = (), mapus: Any = (),
                               base_ids: Mapping[str, Iterable[str]] | None = None) -> list[str]:
    """Return every structural problem found in one canonical object set.

    `base_ids` maps `<label>_ids` to the identities already present in the base version;
    it is used by the Antü path, where a proposal is merged into an accepted document.
    """
    collections = {"entities": _as_list(entities), "relations": _as_list(relations),
                   "assertions": _as_list(assertions), "evidence": _as_list(evidence)}
    problems: list[str] = []
    for label, key, field in OBJECT_COLLECTIONS:
        problems.extend(_duplicate_problems(label, collections[key], field, base_ids))
    by_mapu = {item.get("mapu_id"): item for item in _as_list(mapus)}
    for item in collections["evidence"]:
        problems.extend(_evidence_problems(item, by_mapu))
    problems.extend(_verification_problems(
        (label, field, collections[key]) for label, key, field in OBJECT_COLLECTIONS
        if label != "evidence"))
    for label, key, _field in OBJECT_COLLECTIONS:
        if label != "evidence":
            problems.extend(_semantic_problems(label, collections[key]))
    return problems
