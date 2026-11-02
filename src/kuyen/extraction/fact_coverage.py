"""Independent factual-coverage evaluation for the K02 experiment.

Document-unit coverage is not factual coverage. This module checks the seven
expected facts plus a deliberately absent control against the materialized
candidate. It does not replace KÜYEN validators; it is a second gate used by the
experiment before publication.
"""
from __future__ import annotations

import csv
import json
import re
import unicodedata
from pathlib import Path
from typing import Any

from ..models import CandidateBundle


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFD", text or "")
    text = "".join(char for char in text if unicodedata.category(char) != "Mn")
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def contains_all(text: str, parts: list[str]) -> bool:
    value = normalize(text)
    return all(normalize(part) in value for part in parts)


def load_ground_truth(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _entities(bundle: CandidateBundle) -> dict[str, Any]:
    return {entity.id: entity for entity in bundle.entities}


def _evidence(bundle: CandidateBundle) -> dict[str, Any]:
    return {item.evidence_id: item for item in bundle.evidence}


def _has_evidence(bundle: CandidateBundle, refs: list[str], quote: str) -> bool:
    evidence = _evidence(bundle)
    needle = quote.strip()
    for ref in refs:
        item = evidence.get(ref)
        if item is None:
            continue
        if item.quote.strip() == needle or needle in item.quote or item.quote in needle:
            return True
    return False


def _relation(bundle, entities, predicate: str, from_parts: list[str], to_parts: list[str]):
    for relation in bundle.relations:
        if relation.relation != predicate:
            continue
        source = entities.get(relation.from_entity)
        target = entities.get(relation.to_entity)
        if source and target and contains_all(source.name, from_parts) and contains_all(target.name, to_parts):
            return relation
    return None


def _assertion(bundle, entities, predicate: str, subject_parts: list[str], **conditions):
    for assertion in bundle.assertions:
        subject = entities.get(assertion.subject)
        if assertion.predicate != predicate or not subject or not contains_all(subject.name, subject_parts):
            continue
        if "polarity" in conditions and assertion.polarity != conditions["polarity"]:
            continue
        value = assertion.value
        if "number" in conditions:
            if value is None or value.value is None:
                continue
            try:
                if float(value.value) != float(conditions["number"]):
                    continue
            except (TypeError, ValueError):
                continue
        if "unit" in conditions:
            if value is None or normalize(conditions["unit"]) not in normalize(str(value.unit or "")):
                continue
        if "text_contains" in conditions:
            text = str(value.value) if value is not None and value.value is not None else ""
            if not contains_all(text, conditions["text_contains"]):
                continue
        return assertion
    return None


def evaluate_fact_coverage(bundle: CandidateBundle, ground_truth: dict[str, Any]) -> dict[str, Any]:
    entities = _entities(bundle)
    rows: list[dict[str, Any]] = []
    supported = partial = unsupported = not_observed = 0
    for fact in ground_truth.get("facts", []):
        fact_id = fact["id"]
        status = "NOT_OBSERVED"
        matched: list[str] = []
        evidence_ok = False
        if fact["type"] == "absent_control":
            positive = [
                item for item in bundle.assertions
                if item.polarity == "POSITIVE" and item.value is not None
                and contains_all(str(item.value.value or ""), fact.get("text_contains", []))
            ]
            positive += [
                item for item in bundle.relations
                if contains_all(item.relation, fact.get("text_contains", []))
            ]
            status = "CONTRADICTED" if positive else "ABSENT_CONFIRMED"
            matched = ["positive_export"] if positive else []
        elif fact["type"] == "entity":
            for entity in bundle.entities:
                if contains_all(entity.name, fact.get("name_contains", [])) and entity.entity_type == fact.get("entity_type"):
                    matched.append(entity.id)
                    evidence_ok = _has_evidence(bundle, entity.evidence_refs, fact.get("evidence_quote", ""))
                    break
        elif fact["type"] == "relation":
            relation = _relation(bundle, entities, fact["predicate"], fact.get("from_contains", []), fact.get("to_contains", []))
            if relation is not None:
                matched.append(relation.relation)
                evidence_ok = _has_evidence(bundle, relation.evidence_refs, fact.get("evidence_quote", ""))
        elif fact["type"] == "assertion":
            conditions = {key: fact[key] for key in ("number", "unit", "text_contains", "polarity") if key in fact}
            assertion = _assertion(bundle, entities, fact["predicate"], fact.get("subject_contains", []), **conditions)
            if assertion is not None:
                matched.append(assertion.predicate)
                evidence_ok = _has_evidence(bundle, assertion.evidence_refs, fact.get("evidence_quote", ""))
        elif fact["type"] == "entity_relation_or_assertion":
            for entity in bundle.entities:
                if contains_all(entity.name, fact.get("entity_name_contains", [])) and entity.entity_type == fact.get("entity_type"):
                    matched.append(entity.id)
                    evidence_ok = _has_evidence(bundle, entity.evidence_refs, fact.get("evidence_quote", ""))
                    break
            if matched:
                relation = None
                for predicate in fact.get("relation_predicates", []):
                    relation = _relation(bundle, entities, predicate, fact.get("entity_name_contains", []), fact.get("target_contains", []))
                    if relation:
                        break
                assertion = None
                if relation is None:
                    assertion = _assertion(
                        bundle, entities, "has_value", fact.get("entity_name_contains", []),
                        text_contains=fact.get("assertion_text_contains", []),
                    )
                if relation is not None:
                    matched.append(f"relation:{relation.relation}")
                    evidence_ok = evidence_ok or _has_evidence(bundle, relation.evidence_refs, fact.get("evidence_quote", ""))
                elif assertion is not None:
                    matched.append("assertion:has_value")
                    evidence_ok = evidence_ok or _has_evidence(bundle, assertion.evidence_refs, fact.get("evidence_quote", ""))
        if status == "NOT_OBSERVED":
            if matched and evidence_ok:
                status = "OBSERVED_SUPPORTED"
                supported += 1
            elif matched:
                status = "OBSERVED_PARTIAL"
                partial += 1
            else:
                status = "NOT_OBSERVED"
                not_observed += 1
        elif fact["type"] == "absent_control" and status == "CONTRADICTED":
            unsupported += 1
        rows.append({
            "fact_id": fact_id, "status": status, "matched": ";".join(matched),
            "evidence_ok": evidence_ok, "critical": bool(fact.get("critical", True)),
        })
    total = int(ground_truth.get("expected_total", 7))
    absent = next((row for row in rows if row["fact_id"] == ground_truth.get("absent_control", "F00")), None)
    absent_ok = bool(absent and absent["status"] == "ABSENT_CONFIRMED")
    return {
        "expected_total": total, "supported": supported, "partial": partial,
        "unsupported": unsupported, "not_observed": not_observed, "ambiguous": 0,
        "fact_coverage": round(supported / total, 4) if total else 0.0,
        "absent_control": absent["status"] if absent else "MISSING",
        "absent_control_ok": absent_ok,
        "accepted": supported == total and absent_ok,
        "facts": rows,
    }


def write_fact_coverage_csv(path: str | Path, result: dict[str, Any]) -> None:
    with Path(path).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["fact_id", "status", "matched", "evidence_ok", "critical"])
        writer.writeheader()
        writer.writerows(result["facts"])
