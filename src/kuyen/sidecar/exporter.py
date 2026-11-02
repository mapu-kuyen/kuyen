"""Component A - KUYEN Canonical Exporter.

Reads one accepted KUYEN artifact and produces an immutable, self-contained
canonical record. It never normalizes semantics, never merges objects, never
repairs data and never drops an unknown field: every deviation becomes an
explicit, recorded decision.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..canonical import canonical_json, digest, read_json, sha256_file, sha256_text
from ..errors import ContractError, ExportError
from ..contracts import EXPORTER_VERSION

EXP_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = Path(__file__).resolve().parents[4]

REQUIRED_GRAPH_KEYS = (
    "kuyen_id", "version", "antu_id", "mapu_ids", "schema_version", "status",
    "entities", "relations", "assertions", "evidence", "coverage", "provenance",
    "content_digest", "provenance_digest",
)


@dataclass
class ExportResult:
    document: dict[str, Any]
    diagnostics: dict[str, Any] = field(default_factory=dict)

    @property
    def canonical_graph_hash(self) -> str:
        return self.document["kuyen"]["canonical_graph_hash"]


def _unknown_fields(objects: list[dict[str, Any]], allowed: set[str], kind: str) -> list[dict[str, Any]]:
    findings = []
    for item in objects:
        extra = sorted(set(item) - allowed)
        if extra:
            findings.append({"kind": kind, "object_id": item.get(f"{kind}_id") or item.get("unit_id") or item.get("mapu_id"),
                             "unknown_fields": extra})
    return findings


def _missing_required(objects: list[dict[str, Any]], required: set[str], kind: str) -> list[dict[str, Any]]:
    findings = []
    for item in objects:
        missing = sorted(name for name in required if name not in item)
        if missing:
            findings.append({"kind": kind, "object_id": item.get(f"{kind}_id") or item.get("unit_id"),
                             "missing_fields": missing})
    return findings


def _resolve_mapu_file(mapu_id: str, sources_dir: Path) -> Path:
    direct = sources_dir / f"{mapu_id}.txt"
    if direct.is_file():
        return direct
    candidates = sorted(p for p in sources_dir.glob("*" ) if p.is_file())
    if len(candidates) == 1:
        return candidates[0]
    raise ExportError(f"cannot resolve the source file for MAPU {mapu_id} in {sources_dir}")


def _source_units(graph: dict[str, Any], mapu_id: str, content: str, source_uri: str) -> list[dict[str, Any]]:
    inventory = ((graph.get("provenance") or {}).get("coverage_inventory") or {}).get(mapu_id) or []
    units: list[dict[str, Any]] = []
    for entry in inventory:
        start, end = entry.get("char_start"), entry.get("char_end")
        slice_text = content[start:end] if isinstance(start, int) and isinstance(end, int) else None
        units.append({
            "unit_id": entry.get("unit_id"),
            "mapu_id": mapu_id,
            "section": entry.get("section"),
            "order": entry.get("order"),
            "char_start": start,
            "char_end": end,
            "chars": entry.get("chars"),
            "content_sha256": entry.get("content_sha256"),
            "source_uri": entry.get("source_uri") or source_uri,
            "state": entry.get("state"),
            "content": slice_text,
            "content_verified": (
                slice_text is not None
                and entry.get("content_sha256") is not None
                and sha256_text(slice_text) == entry.get("content_sha256")
            ),
        })
    return units


def export_population(
    population_dir: str | Path,
    *,
    graph_filename: str = "graph.json",
    sources_dirname: str = "sources",
    population_id: str | None = None,
    openviking_version: str = "",
) -> ExportResult:
    population_dir = Path(population_dir)
    graph_path = population_dir / graph_filename
    if not graph_path.is_file():
        raise ExportError(f"graph artifact not found: {graph_path}")
    graph = read_json(graph_path)
    missing_top = [key for key in REQUIRED_GRAPH_KEYS if key not in graph]
    if missing_top:
        raise ExportError(f"{graph_path}: missing required canonical keys {missing_top}")

    sources_dir = population_dir / sources_dirname
    if not sources_dir.is_dir():
        raise ExportError(f"sources directory not found: {sources_dir}")
    mapu_metadata_path = population_dir / "MAPU_METADATA.json"
    mapu_metadata: dict[str, Any] = read_json(mapu_metadata_path) if mapu_metadata_path.is_file() else {}

    mapus: list[dict[str, Any]] = []
    all_units: list[dict[str, Any]] = []
    for mapu_id in graph["mapu_ids"]:
        path = _resolve_mapu_file(mapu_id, sources_dir)
        content = path.read_text(encoding="utf-8")
        declared = (mapu_metadata.get(mapu_id) or {}) if isinstance(mapu_metadata, dict) else {}
        units = _source_units(graph, mapu_id, content, declared.get("source_uri") or f"viking://resources/{mapu_id}")
        all_units.extend(units)
        mapus.append({
            "mapu_id": mapu_id,
            "version": declared.get("version"),
            "revision": declared.get("revision"),
            "source_uri": declared.get("source_uri") or f"viking://resources/{mapu_id}",
            "sha256": sha256_text(content),
            "declared_sha256": declared.get("sha256"),
            "sha256_matches_declared": (declared.get("sha256") in (None, sha256_text(content))),
            "media_type": declared.get("media_type") or "text/plain",
            "source_type": declared.get("source_type") or "text",
            "source_identity": declared.get("source_identity") or "",
            "license": declared.get("license"),
            "source_timestamp": declared.get("source_timestamp"),
            "trust_level": declared.get("trust_level") or "UNVERIFIED",
            "access_policy": declared.get("access_policy") or "experimental",
            "metadata": declared.get("metadata") or {},
            "content": content,
            "content_chars": len(content),
            "content_sha256": sha256_text(content),
            "source_file": str(path.relative_to(population_dir)),
            "units": [unit["unit_id"] for unit in units],
            "metadata_source": str(mapu_metadata_path.relative_to(population_dir)) if mapu_metadata else None,
        })

    evidence_checks = []
    for item in graph.get("evidence") or []:
        mapu = next((m for m in mapus if m["mapu_id"] == item.get("mapu_id")), None)
        if mapu is None:
            evidence_checks.append({"evidence_id": item.get("evidence_id"), "check": "MAPU_NOT_EXPORTED", "ok": False})
            continue
        start, end = item.get("char_start"), item.get("char_end")
        quote_ok = isinstance(start, int) and isinstance(end, int) and mapu["content"][start:end] == item.get("quote")
        unit = next((u for u in all_units if u["mapu_id"] == item.get("mapu_id")
                     and isinstance(start, int) and u["char_start"] is not None
                     and u["char_start"] <= start < u["char_end"] and u["char_start"] < end <= u["char_end"]), None)
        evidence_checks.append({
            "evidence_id": item.get("evidence_id"),
            "check": "QUOTE_AT_OFFSETS", "ok": bool(quote_ok),
            "unit_id": (unit or {}).get("unit_id"),
            "source_sha256_matches_mapu": item.get("source_sha256") in (None, mapu["content_sha256"]),
        })

    snapshot_path = EXP_ROOT / "manifests" / "CONTRACT_SNAPSHOT.json"
    snapshot = read_json(snapshot_path) if snapshot_path.is_file() else {}
    allowed = {
        "entities": set((snapshot.get("entities") or {}).keys()),
        "relations": set((snapshot.get("relations") or {}).keys()),
        "assertions": set((snapshot.get("assertions") or {}).keys()),
        "evidence": set(snapshot.get("evidence_schema_required") or []) | {"evidence_id"},
        "source_units": {"unit_id", "mapu_id", "section", "order", "char_start", "char_end", "chars", "content_sha256", "source_uri", "state", "content", "content_verified"},
    }
    required = {
        "entities": {"entity_id", "entity_type", "name"},
        "relations": {"relation_id", "from_entity", "predicate", "to_entity"},
        "assertions": {"assertion_id", "subject_entity", "predicate"},
        "evidence": {"evidence_id", "mapu_id", "source_uri", "quote", "char_start", "char_end"},
    }
    unknown = []
    incomplete = []
    for kind in ("entities", "relations", "assertions", "evidence"):
        unknown.extend(_unknown_fields(graph.get(kind) or [], allowed[kind], kind))
        incomplete.extend(_missing_required(graph.get(kind) or [], required[kind], kind))
    unknown.extend(_unknown_fields(all_units, allowed["source_units"], "source_unit"))

    integrity = _referential_integrity(graph, all_units)
    canonical_graph_hash = digest(graph)
    document = {
        "kuyen": {
            "kuyen_id": graph["kuyen_id"],
            "version": graph["version"],
            "antu_id": graph["antu_id"],
            "mapu_ids": list(graph["mapu_ids"]),
            "schema_version": graph["schema_version"],
            "status": graph["status"],
            "content_digest": graph.get("content_digest"),
            "provenance_digest": graph.get("provenance_digest"),
            "provenance": graph.get("provenance") or {},
            "canonical_graph_hash": canonical_graph_hash,
            "source_graph_sha256": sha256_file(graph_path),
            "source_graph_path": str(graph_path.name),
            "source_graph_byte_length": graph_path.stat().st_size,
            "canonical_serialization_sha256": sha256_text(canonical_json(graph)),
        },
        "mapus": mapus,
        "canonical": {
            "entities": list(graph.get("entities") or []),
            "relations": list(graph.get("relations") or []),
            "assertions": list(graph.get("assertions") or []),
            "evidence": list(graph.get("evidence") or []),
            "coverage": list(graph.get("coverage") or []),
            "source_units": all_units,
        },
        "counts": {
            "mapus": len(mapus),
            "entities": len(graph.get("entities") or []),
            "relations": len(graph.get("relations") or []),
            "assertions": len(graph.get("assertions") or []),
            "evidence": len(graph.get("evidence") or []),
            "coverage": len(graph.get("coverage") or []),
            "source_units": len(all_units),
        },
    }
    diagnostics = {
        "population_id": population_id or population_dir.name,
        "population_dir": str(population_dir),
        "openviking_version": openviking_version,
        "graph_file_sha256": sha256_file(graph_path),
        "mapu_file_sha256": {m["mapu_id"]: m["content_sha256"] for m in mapus},
        "mapu_hash_matches_declared": all(m["sha256_matches_declared"] for m in mapus),
        "unknown_fields": unknown,
        "incomplete_objects": incomplete,
        "evidence_checks": evidence_checks,
        "evidence_checks_failed": [item for item in evidence_checks if not item["ok"]],
        "units_content_verified": all(u["content_verified"] for u in all_units),
        "referential_integrity": integrity,
        "schema_validation": validate_against_productive_schema(graph),
        "canonical_graph_hash": canonical_graph_hash,
        "mapu_content_reconstructable": _mapu_reconstructable(mapus, all_units),
        "exporter_version": EXPORTER_VERSION,
        "decisions": [
            {"decision": "NO_NORMALIZATION", "detail": "objects are copied verbatim; no merge, rename or repair"},
            {"decision": "UNKNOWN_FIELDS_RETAINED",
             "detail": f"{len(unknown)} object(s) carry fields not declared by the contract snapshot; retained verbatim"},
            {"decision": "SOURCE_UNIT_CONTENT_EMBEDDED",
             "detail": "each SOURCE_UNIT stores its text slice so the MAPU is reproducible without external files"},
        ],
    }
    return ExportResult(document=document, diagnostics=diagnostics)


def _mapu_reconstructable(mapus: list[dict[str, Any]], units: list[dict[str, Any]]) -> dict[str, Any]:
    result = {}
    for mapu in mapus:
        own = sorted([u for u in units if u["mapu_id"] == mapu["mapu_id"] and u.get("content") is not None],
                     key=lambda u: (u.get("order") if u.get("order") is not None else 0))
        joined = "".join(u["content"] for u in own) if own else ""
        contiguous = all(
            own[index]["char_end"] == own[index + 1]["char_start"] for index in range(len(own) - 1)
        ) if len(own) > 1 else bool(own)
        result[mapu["mapu_id"]] = {
            "unit_count": len(own),
            "contiguous": contiguous,
            "reconstructed_sha256": sha256_text(joined),
            "mapu_sha256": mapu["content_sha256"],
            "byte_exact": sha256_text(joined) == mapu["content_sha256"],
            "covers_full_document": bool(own) and own[0]["char_start"] == 0 and own[-1]["char_end"] == mapu["content_chars"],
        }
    return result


def _referential_integrity(graph: dict[str, Any], units: list[dict[str, Any]]) -> dict[str, Any]:
    entity_ids = [e["entity_id"] for e in graph.get("entities") or []]
    relation_ids = [r["relation_id"] for r in graph.get("relations") or []]
    assertion_ids = [a["assertion_id"] for a in graph.get("assertions") or []]
    evidence_ids = [e["evidence_id"] for e in graph.get("evidence") or []]
    entity_set, evidence_set = set(entity_ids), set(evidence_ids)
    return {
        "duplicate_entity_ids": _dupes(entity_ids),
        "duplicate_relation_ids": _dupes(relation_ids),
        "duplicate_assertion_ids": _dupes(assertion_ids),
        "duplicate_evidence_ids": _dupes(evidence_ids),
        "dangling_relation_endpoints": sorted(
            r["relation_id"] for r in graph.get("relations") or []
            if r["from_entity"] not in entity_set or r["to_entity"] not in entity_set),
        "dangling_evidence_refs": sorted({
            ref for group in ("entities", "relations", "assertions")
            for item in graph.get(group) or []
            for ref in item.get("evidence_ids") or [] if ref not in evidence_set}),
        "dangling_object_entity_refs": sorted(
            a["assertion_id"] for a in graph.get("assertions") or []
            if a.get("object_entity") and a["object_entity"] not in entity_set),
        "evidence_without_source_unit": sorted(
            e["evidence_id"] for e in graph.get("evidence") or []
            if not any(u["mapu_id"] == e.get("mapu_id") and isinstance(e.get("char_start"), int)
                       and (u["char_start"] or 0) <= e["char_start"] < (u["char_end"] or 0)
                       and (u["char_start"] or 0) < e["char_end"] <= (u["char_end"] or 0)
                       for u in units)),
    }


def _dupes(values: list[str]) -> list[str]:
    seen, dupes = set(), set()
    for value in values:
        if value in seen:
            dupes.add(value)
        seen.add(value)
    return sorted(dupes)


def validate_against_productive_schema(graph: dict[str, Any]) -> dict[str, Any]:
    """Deterministic validation with the productive JSON schema (read-only)."""
    try:
        import jsonschema
    except ImportError:  # pragma: no cover
        return {"status": "NOT_TESTED", "reason": "jsonschema not installed"}
    from ..contracts import schema_path as _schema_path

    schema_path = _schema_path("kuyen.schema.json")
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(graph, schema)
        return {"status": "VALID", "schema_sha256": sha256_file(schema_path)}
    except jsonschema.ValidationError as exc:
        return {"status": "INVALID", "schema_sha256": sha256_file(schema_path),
                "message": exc.message, "path": [str(item) for item in exc.path]}
