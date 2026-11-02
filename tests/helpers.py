from __future__ import annotations
import json
from pathlib import Path
from typing import Any

from kuyen.models import ActorContext, Antu, CandidateBundle, Mapu

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SOURCE = (FIXTURES / "source.txt").read_text(encoding="utf-8")
SOURCE_URI = "viking://resources/kuyen/sources/MAPU-TEST/source.txt"
MAPU_ID = "MAPU-TEST"


def antu(**overrides: Any) -> dict[str, Any]:
    value = {
        "antu_id": "ANTU-KUYEN-TEST-001",
        "version": "1.0.0",
        "purpose": "Build a small controlled graph",
        "author": "agent-design",
        "scope": {"include": ["synthetic test source"], "exclude": []},
        "language": "es",
        "ontology_profile": "generic-v1",
        "entity_types": ["person", "organization"],
        "relation_types": ["coordinates", "located_in", "has_member"],
        "coverage_policy": "complete",
        "evidence_policy": "strict",
        "scalar_policy": "literal",
        "conflict_policy": "preserve_unresolved",
        "output_profile": "kuyen-native-v1",
    }
    value.update(overrides)
    return value


def actor(**overrides: Any) -> ActorContext:
    value = dict(
        leftraru_id="LR-TEST",
        authenticated_account="micro-test",
        authenticated_user="tester",
        service_identity="svc-kuyen-test",
        antu_author="agent-design",
        candidate_producer="openviking-knowledge-graph",
    )
    value.update(overrides)
    return ActorContext(**value)


def mapu() -> Mapu:
    return Mapu(
        mapu_id=MAPU_ID,
        version="1.0.0",
        source_uri=SOURCE_URI,
        content=SOURCE,
        sha256=__import__("hashlib").sha256(SOURCE.encode("utf-8")).hexdigest(),
        media_type="text/plain",
        source_type="synthetic",
        source_identity="fixture",
        ingestion_timestamp="2026-10-29T00:00:00+00:00",
        trust_level="UNVERIFIED",
        access_policy="experimental",
    )


def evidence(quote: str, evidence_id: str = "ev-test") -> dict[str, Any]:
    start = SOURCE.index(quote)
    return {
        "evidence_id": evidence_id,
        "mapu_id": MAPU_ID,
        "source_uri": SOURCE_URI,
        "source_sha256": mapu().sha256,
        "quote": quote,
        "char_start": start,
        "char_end": start + len(quote),
        "offset_unit": "unicode_codepoint",
        "extraction_method": "fixture",
    }


def candidate(*, valid: bool = True) -> dict[str, Any]:
    quote1 = "La Asociación Río Claro es una organización de productores de la zona."
    quote2 = "Elena Soto coordina la Asociación Río Claro desde 2021."
    entities = [
        {"id": "asociacion-rio-claro", "name": "Asociación Río Claro", "entity_type": "organization", "sources": [SOURCE_URI], "evidence_refs": ["ev-1"]},
        {"id": "elena-soto", "name": "Elena Soto", "entity_type": "person", "sources": [SOURCE_URI], "evidence_refs": ["ev-2"]},
    ]
    relations = [{
        "from": "elena-soto", "relation": "coordinates", "to": "asociacion-rio-claro",
        "label": "coordina", "polarity": "POSITIVE", "scope": "document",
        "sources": [SOURCE_URI], "evidence_refs": ["ev-2"],
    }]
    if not valid:
        relations[0]["to"] = "missing-entity"
    return {
        "entities": entities,
        "relations": relations,
        "assertions": [],
        "evidence": [evidence(quote1, "ev-1"), evidence(quote2, "ev-2")],
        "coverage": [{
            "source_uri": SOURCE_URI, "mapu_id": MAPU_ID, "unit_id": "whole-source",
            "section": "document", "state": "PROCESSED_WITH_OUTPUT",
            "entity_ids": ["asociacion-rio-claro", "elena-soto"],
            "relation_ids": [], "reason": None,
        }],
    }


def bundle(*, valid: bool = True) -> CandidateBundle:
    return CandidateBundle.from_dict(candidate(valid=valid))
