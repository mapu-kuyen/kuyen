"""Coverage metrics separated into processing and knowledge dimensions."""
from __future__ import annotations

from typing import Any, Iterable

from ..models import CoverageState, KuyenGraph
from .sections import SectionUnit

TERMINAL_OK = {
    CoverageState.PROCESSED_WITH_OUTPUT.value,
    CoverageState.PROCESSED_NO_GRAPH_FACTS.value,
}


def coverage_metrics(
    graph: KuyenGraph,
    *,
    expected: dict[str, list[SectionUnit]] | None = None,
) -> dict[str, Any]:
    """Account for document units and graph facts without merging the two.

    Processing coverage answers "which MAPU slices were accounted for?".
    Knowledge coverage answers "which expected references produced graph facts?".
    """
    ledger = {(item.mapu_id, item.unit_id): item for item in graph.coverage}
    expected_units = expected or {}
    expected_ids = {(unit.mapu_id, unit.unit_id) for units in expected_units.values() for unit in units}
    present_ids = set(ledger)
    states: dict[str, int] = {}
    for item in graph.coverage:
        states[item.state.value] = states.get(item.state.value, 0) + 1
    with_output = sum(1 for item in graph.coverage if item.entity_ids or item.relation_ids)
    return {
        "profile": "document-sections-v1" if expected_units else "producer-ledger",
        "units_expected": len(expected_ids) if expected_ids else len(ledger),
        "units_in_ledger": len(ledger),
        "units_with_output": with_output,
        "units_without_output": sum(1 for item in graph.coverage if not item.entity_ids and not item.relation_ids),
        "units_missing": sorted(f"{m}:{u}" for m, u in expected_ids - present_ids),
        "units_unexpected": sorted(f"{m}:{u}" for m, u in present_ids - expected_ids) if expected_ids else [],
        "states": states,
        "processing_complete": bool(expected_ids) and expected_ids <= present_ids and all(
            item.state.value in TERMINAL_OK for item in graph.coverage
        ),
        "knowledge_facts": {
            "entities": len(graph.entities),
            "relations": len(graph.relations),
            "assertions": len(graph.assertions),
            "evidence": len(graph.evidence),
        },
    }


def iter_unaccounted_spans(units: Iterable[SectionUnit], graph: KuyenGraph) -> list[str]:
    """Units whose declared content hash does not match the deterministic slice."""
    by_id = {(item.mapu_id, item.unit_id): item for item in graph.coverage}
    mismatched = []
    for unit in units:
        item = by_id.get((unit.mapu_id, unit.unit_id))
        if item is not None and item.content_sha256 and item.content_sha256 != unit.content_sha256:
            mismatched.append(f"{unit.mapu_id}:{unit.unit_id}")
    return mismatched
