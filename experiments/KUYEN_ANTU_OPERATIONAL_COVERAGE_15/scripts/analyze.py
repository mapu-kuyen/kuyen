"""Acceptance checks and comparison for KUYEN_ANTU_OPERATIONAL_COVERAGE_15.

Every check reads the graph that was actually committed, not the proposal: the experiment claims
that a relation, an entity and an attribute were edited through a real Antü, so the proof is the
new version, the preserved properties and the still readable previous version.

    python3 scripts/analyze.py
"""
from __future__ import annotations

import csv
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from kuyen import KuyenMemory  # noqa: E402

EXPERIMENT = pathlib.Path(__file__).resolve().parents[1]
EVIDENCE = EXPERIMENT / "evidence"
WORK = pathlib.Path("/tmp/kuyen13_work/instances")
K004 = "KUYEN-004"
K005 = "KUYEN-005"


def open_memory(name: str) -> KuyenMemory:
    return KuyenMemory.open(WORK / name / "memory")


def entity(memory: KuyenMemory, name_part: str, version: str | None = None) -> dict:
    for item in memory.graph(version)["entities"]:
        if name_part.casefold() in str(item.get("name") or "").casefold():
            return item
    raise AssertionError(f"no entity matching {name_part!r}")


def relation(memory: KuyenMemory, predicate: str, source: str, target: str,
             version: str | None = None) -> dict:
    graph = memory.graph(version)
    names = {item["entity_id"]: str(item.get("name") or "") for item in graph["entities"]}
    for item in graph["relations"]:
        if item.get("predicate") != predicate:
            continue
        if source.casefold() in names.get(item["from_entity"], "").casefold() and \
                target.casefold() in names.get(item["to_entity"], "").casefold():
            return item
    raise AssertionError(f"no relation {predicate} from {source} to {target}")



def main() -> int:
    runs = json.loads((EVIDENCE / "real_runs.json").read_text(encoding="utf-8"))
    before = json.loads((EVIDENCE / "state_before.json").read_text(encoding="utf-8"))
    after = json.loads((EVIDENCE / "state_after.json").read_text(encoding="utf-8"))
    checks: dict[str, dict] = {}

    def check(key: str, ok: bool, detail: object) -> None:
        checks[key] = {"ok": bool(ok), "detail": detail}

    memory = open_memory(K004)
    versions = [item.version_id for item in memory.versions()]
    base = before["memories"][K004]["current"]
    current = memory.graph()

    # §3 — the relation addition reached the graph with its own provenance and no evidence.
    added = relation(memory, "part_of", "Diversificación", "Transición Ecológica")
    check("relation_added", added["status"] == "INSTRUCTED",
          {"relation_id": added["relation_id"], "status": added["status"],
           "origin": (added.get("origin") or {}).get("kind"),
           "evidence_ids": added.get("evidence_ids"), "polarity": added.get("polarity")})
    check("relation_has_no_documentary_evidence",
          added["evidence_ids"] == [] and added["sources"] == []
          and (added.get("origin") or {}).get("kind") == "ANTU_INSTRUCTION", added.get("origin"))
    check("relation_absent_from_the_base_version",
          all(item["relation_id"] != added["relation_id"]
              for item in memory.graph(base)["relations"]), base)
    check("relation_count", len(current["relations"]) == 15, len(current["relations"]))

    # §4 — the entity update kept the identity, the relations and the previous value.
    renamed = [item for item in current["entities"]
               if "Guájares" in str(item.get("name") or "") and "Central" in str(item.get("name"))]
    old = [item for item in memory.graph(base)["entities"]
           if item["entity_id"] == renamed[0]["entity_id"]]
    check("entity_renamed_in_place",
          len(renamed) == 1 and renamed[0]["entity_id"] == old[0]["entity_id"],
          {"entity_id": renamed[0]["entity_id"], "before": old[0]["name"],
           "after": renamed[0]["name"], "aliases": renamed[0]["aliases"]})
    check("entity_kept_its_relations",
          sum(1 for item in current["relations"]
              if renamed[0]["entity_id"] in (item["from_entity"], item["to_entity"]))
          >= sum(1 for item in memory.graph(base)["relations"]
                 if renamed[0]["entity_id"] in (item["from_entity"], item["to_entity"])),
          renamed[0]["entity_id"])
    revisions = [item for item in (renamed[0].get("revisions") or [])
                 if isinstance(item.get("previous"), dict) and item["previous"].get("name")]
    revision = revisions[-1] if revisions else {}
    check("entity_revision_records_the_previous_value",
          revision.get("previous", {}).get("name") == old[0]["name"] and revision.get("antu_id"),
          revision)
    check("entity_kept_documentary_support",
          bool(renamed[0].get("evidence_ids")) and renamed[0].get("amended") is True
          and bool(renamed[0].get("instruction_edits")),
          {"evidence_ids": len(renamed[0].get("evidence_ids") or []),
           "origin": renamed[0].get("origin") and renamed[0]["origin"].get("kind"),
           "amended": renamed[0].get("amended")})

    # §5 — the attribute lives on the entity, typed by the schema, without inventing statements.
    schema_attributes = current["schema"]["entity_types"]["product"]["attributes"]
    central = entity(memory, "Central Hidráulica")
    check("attribute_declared_in_the_schema", "estado_operativo" in schema_attributes,
          {key: schema_attributes.get(key, {}).get("value_type") for key in schema_attributes})
    check("attribute_value_committed",
          (central.get("metadata") or {}).get("estado_operativo") == "en mantenimiento",
          central.get("metadata"))
    check("attribute_change_is_versioned",
          ((central.get("revisions") or [{}])[-1].get("previous") == "operativa"),
          (central.get("revisions") or [{}])[-1])
    check("attribute_did_not_create_assertions",
          len(current["assertions"]) == len(memory.graph(base)["assertions"]),
          {"before": len(memory.graph(base)["assertions"]),
           "after": len(current["assertions"])})


    # §6 — a long instruction with several changes, on another memory.
    other = open_memory(K005)
    monroig = entity(other, "Monroig")
    participates = relation(other, "participates_in", "Monroig", "AQUALICIOUS")
    check("long_instruction_committed_three_operations",
          runs["runs"]["K005-LONG"]["status"] == "COMMITTED"
          and len(runs["runs"]["K005-LONG"]["applied"]) == 3,
          [item["op"] for item in runs["runs"]["K005-LONG"]["applied"]])
    check("long_instruction_relation_present",
          participates["status"] == "INSTRUCTED" and participates["evidence_ids"] == [],
          {"relation_id": participates["relation_id"], "status": participates["status"]})
    check("long_instruction_attribute_present",
          (monroig.get("metadata") or {}).get("rol") == "investigador del CSIC",
          monroig.get("metadata"))
    check("long_instruction_schema_present",
          "rol" in other.graph()["schema"]["entity_types"]["person"]["attributes"],
          other.graph()["schema"]["entity_types"]["person"]["attributes"].get("rol"))

    # §6 — the nesting defect: the same request before and after the normaliser correction.
    pre = json.loads((EVIDENCE / "pre_fix_raw_responses.json").read_text(encoding="utf-8"))
    nested = pre["runs"]["K004-DRY-LONG"]
    check("pre_fix_the_model_did_produce_operations",
          not (nested.get("proposal") or {}).get("operations")
          and '"operations"' in (nested.get("raw_response") or ""),
          {"kuyen_read": len((nested.get("proposal") or {}).get("operations") or []),
           "model_wrote": (nested.get("raw_response") or "").count("operation_id")})
    post = runs["runs"]["K004-DRY-LONG"]
    check("post_fix_the_same_request_produced_operations",
          len(post.get("operations") or []) >= 2,
          [item["op"] for item in post.get("operations") or []])

    # §7 — the outcomes a run can report, and never a limitation as an absence of change.
    reported = sorted({item.get("outcome") for item in runs["runs"].values()})
    check("outcomes_are_distinguished", len(reported) >= 4, reported)
    check("no_limitation_reported_as_no_changes",
          all(item.get("status") != "NO_CHANGES" or item.get("outcome") in
              ("NO_CHANGES", "ALREADY_SATISFIED") for item in runs["runs"].values()),
          {key: (item.get("status"), item.get("outcome"))
           for key, item in runs["runs"].items()})

    # integrity and independence of the ten memories
    integrity = {name: state["verify"] for name, state in after["memories"].items()}
    check("ten_memories_verify", all(integrity.values()) and len(integrity) == 10, integrity)
    untouched = [name for name in after["memories"]
                 if before["memories"][name]["versions"] == after["memories"][name]["versions"]]
    check("eight_memories_untouched", len(untouched) == 8, untouched)
    check("versions_only_grew_where_authorised",
          set(after["memories"][K004]["versions"]) >= set(before["memories"][K004]["versions"])
          and len(after["memories"][K004]["versions"]) == 5
          and len(after["memories"][K005]["versions"]) == 5,
          {K004: len(after["memories"][K004]["versions"]),
           K005: len(after["memories"][K005]["versions"])})
    check("previous_versions_still_readable",
          memory.graph(base)["version"] != memory.graph()["version"]
          and memory.verify()["ok"] is True, {"base": base, "current": versions[-1]})


    accepted = sum(1 for item in checks.values() if item["ok"])
    payload = {"experiment": EXPERIMENT.name, "checks": checks, "accepted": accepted,
               "total": len(checks), "ok": accepted == len(checks)}
    (EVIDENCE / "acceptance.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    with (EXPERIMENT / "benchmarks" / "runs.csv").open("w", encoding="utf-8",
                                                       newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["antu_id", "kuyen", "case", "status", "outcome", "applied",
                         "declined", "rejected", "version", "seconds", "prompt_tokens",
                         "completion_tokens", "cost_usd", "lost"])
        for key, item in runs["runs"].items():
            usage = item.get("usage") or {}
            writer.writerow([key, item.get("kuyen"), item.get("case"), item.get("status"),
                             item.get("outcome"), len(item.get("applied") or []),
                             len(item.get("declined") or []),
                             len(item.get("rejected") or []),
                             item.get("version_after"), item.get("seconds"),
                             usage.get("prompt_tokens"), usage.get("completion_tokens"),
                             usage.get("cost_usd"),
                             len((item.get("preservation") or {}).get("lost") or [])])
    print(f"acceptance: {accepted}/{len(checks)}")
    for key, item in checks.items():
        print(f"  [{'ok' if item['ok'] else 'FAIL'}] {key}")
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

