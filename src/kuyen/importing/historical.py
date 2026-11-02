"""Historical native-graph import with explicit term and evidence compatibility.

The importer is deliberately *not* an acceptance path. It preserves the source
system's IDs, types, predicates, labels and evidence references, records whether
each term exists in the selected profile, and reports every limitation. It never
retypes an entity, renames a predicate, merges identities or upgrades document
evidence to a verified span.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..canonical import stable_id
from ..ontology import Ontology
from ..serialization.serializer import read_native_entities, read_native_relations

NATIVE_PRESERVED = "NATIVE_PRESERVED"
UNMAPPED_NATIVE = "UNMAPPED_NATIVE"
DOMAIN_RANGE_INCOMPATIBLE_NATIVE = "DOMAIN_RANGE_INCOMPATIBLE_NATIVE"
NATIVE_LABEL_PRESERVED = "NATIVE_LABEL_PRESERVED"

EXACT_SPAN = "EXACT_SPAN"
DOCUMENT_REFERENCE = "DOCUMENT_REFERENCE"
INVALID_SPAN = "INVALID_SPAN"
NO_EVIDENCE = "NO_EVIDENCE"


@dataclass
class ImportedEntity:
    native_id: str
    kuyen_id: str
    name: str
    entity_type: str
    description: str
    aliases: list[str]
    sources: list[str]
    evidence_class: str
    type_status: str
    source_file: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "native_id": self.native_id, "kuyen_id": self.kuyen_id, "name": self.name,
            "entity_type": self.entity_type, "description": self.description,
            "aliases": self.aliases, "sources": self.sources,
            "evidence_class": self.evidence_class, "type_status": self.type_status,
            "source_file": self.source_file,
        }


@dataclass
class ImportedRelation:
    source_index: int
    native_from: str
    native_to: str
    native_predicate: str
    native_label: str
    kuyen_from: str | None
    kuyen_to: str | None
    endpoint_status: str
    predicate_status: str
    direction_status: str
    label_status: str
    evidence_class: str
    sources: list[str]
    quote: str | None = None
    char_start: int | None = None
    char_end: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_index": self.source_index,
            "native_from": self.native_from, "native_to": self.native_to,
            "native_predicate": self.native_predicate, "native_label": self.native_label,
            "kuyen_from": self.kuyen_from, "kuyen_to": self.kuyen_to,
            "endpoint_status": self.endpoint_status,
            "predicate_status": self.predicate_status,
            "direction_status": self.direction_status,
            "label_status": self.label_status,
            "evidence_class": self.evidence_class,
            "sources": self.sources,
            "quote": self.quote, "char_start": self.char_start, "char_end": self.char_end,
            "raw": self.raw,
        }


@dataclass
class HistoricalImport:
    namespace: str
    system_version: str
    ontology_id: str
    source_directory: str
    source_hashes: dict[str, str]
    entities: list[ImportedEntity]
    relations: list[ImportedRelation]
    limitations: list[str] = field(default_factory=list)

    @property
    def type_report(self) -> dict[str, Any]:
        observed = sorted({item.entity_type for item in self.entities})
        return {
            "observed": observed,
            "preserved": sorted({item.entity_type for item in self.entities if item.type_status == NATIVE_PRESERVED}),
            "unmapped": sorted({item.entity_type for item in self.entities if item.type_status == UNMAPPED_NATIVE}),
        }

    @property
    def predicate_report(self) -> dict[str, Any]:
        observed = sorted({item.native_predicate for item in self.relations})
        unmapped = sorted({item.native_predicate for item in self.relations if item.predicate_status == UNMAPPED_NATIVE})
        incompatible = sorted({
            item.native_predicate for item in self.relations
            if item.direction_status == DOMAIN_RANGE_INCOMPATIBLE_NATIVE
        })
        return {
            "observed": observed,
            "preserved": [x for x in observed if x not in unmapped],
            "unmapped": unmapped,
            "domain_range_incompatible": incompatible,
        }

    @property
    def evidence_report(self) -> dict[str, Any]:
        counts: dict[str, int] = {}
        for item in self.relations:
            counts[item.evidence_class] = counts.get(item.evidence_class, 0) + 1
        entity_counts: dict[str, int] = {}
        for item in self.entities:
            entity_counts[item.evidence_class] = entity_counts.get(item.evidence_class, 0) + 1
        return {
            "relations": counts,
            "entities": entity_counts,
            "has_exact_spans": counts.get(EXACT_SPAN, 0) > 0,
            "all_relations_exact": bool(self.relations) and all(
                item.evidence_class == EXACT_SPAN for item in self.relations
            ),
            "all_entities_exact": bool(self.entities) and all(
                item.evidence_class == EXACT_SPAN for item in self.entities
            ),
        }

    def to_dict(self) -> dict[str, Any]:
        strict_blockers = []
        if self.predicate_report["unmapped"]:
            strict_blockers.append("unmapped native predicates")
        if self.type_report["unmapped"]:
            strict_blockers.append("unmapped native entity types")
        if not self.evidence_report["all_relations_exact"]:
            strict_blockers.append("relations without exact spans")
        if not self.evidence_report["all_entities_exact"]:
            strict_blockers.append("entities without exact spans")
        return {
            "contract": "KUYEN_HISTORICAL_IMPORT_1.0",
            "namespace": self.namespace,
            "system_version": self.system_version,
            "ontology": self.ontology_id,
            "source_directory": self.source_directory,
            "source_hashes": self.source_hashes,
            "counts": {"entities": len(self.entities), "relations": len(self.relations)},
            "entities": [item.to_dict() for item in self.entities],
            "relations": [item.to_dict() for item in self.relations],
            "compatibility": {
                "entity_types": self.type_report,
                "predicates": self.predicate_report,
                "evidence": self.evidence_report,
                "ids_preserved": True,
                "labels_preserved": True,
                "strict_acceptance_available": not strict_blockers,
                "strict_blockers": strict_blockers,
                "mapping_applied": False,
            },
            "limitations": self.limitations,
            "note": (
                "Import only. The graph was not extracted again by KÜYEN and is not an "
                "ACCEPTED KÜYEN version."
            ),
        }


def _sha(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _evidence_class(row: dict[str, Any], source_text: str | None) -> tuple[str, dict[str, Any]]:
    quote = row.get("evidence_quote")
    start = row.get("evidence_start_offset")
    end = row.get("evidence_end_offset")
    if isinstance(quote, str) and quote and isinstance(start, int) and isinstance(end, int):
        detail = {"quote": quote, "char_start": start, "char_end": end}
        if source_text is not None:
            return (EXACT_SPAN if source_text[start:end] == quote else INVALID_SPAN, detail)
        return (EXACT_SPAN, detail)
    if row.get("evidence"):
        return (DOCUMENT_REFERENCE, {})
    return (NO_EVIDENCE, {})


def import_historical_graph(
    directory: str | Path,
    *,
    ontology: Ontology,
    namespace: str,
    system_version: str,
    source_text_path: str | Path | None = None,
    limitations: list[str] | None = None,
) -> HistoricalImport:
    """Load native artifacts and report compatibility without changing them."""
    root = Path(directory)
    source_text = Path(source_text_path).read_text(encoding="utf-8") if source_text_path else None
    entities_raw = read_native_entities(root)
    relations_raw = read_native_relations(root)
    hashes = {}
    for path in sorted([*(root / "entities").glob("*.md"), root / "relations.jsonl"]):
        if path.is_file():
            hashes[path.relative_to(root).as_posix()] = _sha(path)
    entities: list[ImportedEntity] = []
    native_to_kuyen: dict[str, str] = {}
    entity_by_id: dict[str, ImportedEntity] = {}
    for item in entities_raw:
        native_id = str(item["id"])
        kuyen_id = stable_id(
            "ent", {"namespace": namespace, "source_id": native_id, "type": item["entity_type"]}
        )
        entity = ImportedEntity(
            native_id=native_id, kuyen_id=kuyen_id, name=str(item["name"]),
            entity_type=str(item["entity_type"]), description=str(item.get("description") or ""),
            aliases=list(item.get("aliases") or []), sources=list(item.get("sources") or []),
            evidence_class=EXACT_SPAN if item.get("evidence_quote") else (
                DOCUMENT_REFERENCE if item.get("sources") else NO_EVIDENCE
            ),
            type_status=NATIVE_PRESERVED if ontology.has_entity_type(item["entity_type"]) else UNMAPPED_NATIVE,
            source_file=f"entities/{native_id}.md",
        )
        entities.append(entity)
        entity_by_id[native_id] = entity
        native_to_kuyen.setdefault(native_id, kuyen_id)
    relations: list[ImportedRelation] = []
    for index, row in enumerate(relations_raw):
        native_from = str(row.get("from") or "")
        native_to = str(row.get("to") or "")
        predicate = str(row.get("relation") or "")
        label = str(row.get("label") or predicate)
        spec = ontology.relation(predicate)
        evidence_class, detail = _evidence_class(row, source_text)
        source_entity = entity_by_id.get(native_from)
        target_entity = entity_by_id.get(native_to)
        endpoint_status = "RESOLVED" if source_entity and target_entity else "UNRESOLVED_NATIVE_ENDPOINT"
        if spec is None:
            direction_status = "NOT_APPLICABLE"
        elif source_entity and target_entity and not ontology.accepts_direction(
            spec, source_entity.entity_type, target_entity.entity_type
        ):
            direction_status = DOMAIN_RANGE_INCOMPATIBLE_NATIVE
        else:
            direction_status = "COMPATIBLE"
        relations.append(ImportedRelation(
            source_index=index, native_from=native_from, native_to=native_to,
            native_predicate=predicate, native_label=label,
            kuyen_from=native_to_kuyen.get(native_from), kuyen_to=native_to_kuyen.get(native_to),
            endpoint_status=endpoint_status,
            predicate_status=NATIVE_PRESERVED if spec is not None else UNMAPPED_NATIVE,
            direction_status=direction_status,
            label_status=NATIVE_LABEL_PRESERVED if spec is not None and label != spec.label else "LABEL_UNCHANGED",
            evidence_class=evidence_class, sources=list(row.get("evidence") or []),
            quote=detail.get("quote"), char_start=detail.get("char_start"), char_end=detail.get("char_end"),
            raw=row,
        ))
    return HistoricalImport(
        namespace=namespace, system_version=system_version, ontology_id=ontology.version_id,
        source_directory=str(root), source_hashes=hashes, entities=entities, relations=relations,
        limitations=list(limitations or []),
    )
