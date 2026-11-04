"""Measure, in the stores, what experiment 13's confirmed assertions actually lost."""
from __future__ import annotations

import glob
import json
import pathlib
import sys

EXPERIMENT = pathlib.Path(__file__).resolve().parents[1]
ROOT = EXPERIMENT.parents[1]
sys.path.insert(0, str(ROOT / "src"))

from kuyen import KuyenMemory  # noqa: E402

EXP13 = ROOT / "experiments/KUYEN_TEN_REAL_MAPU_AND_ANTU_OPERATIONS_13"
WORK = pathlib.Path("/tmp/kuyen13_work/instances")


def audit() -> dict:
    findings = []
    for path in sorted(glob.glob(str(EXP13 / "evidence/KUYEN-*/antu/*.json"))):
        data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
        if data.get("status") != "COMMITTED":
            continue
        result = data.get("result") or {}
        version = data.get("version_after")
        operations = {str(item.get("operation_id")): item for item in result.get("operations") or []}
        memory = KuyenMemory.open(WORK / data["kuyen_id"] / "memory")
        graph = memory.graph(version)
        operations = {str(item.get("operation_id")): item
                      for item in result.get("operations") or []}
        by_id = {str(obj.get("assertion_id")): obj for obj in graph.get("assertions") or []}
        for new in graph.get("assertions") or []:
            supersedes = new.get("supersedes")
            if not supersedes or supersedes not in by_id:
                continue
            old = by_id[supersedes]
            operation = next((item for item in operations.values()
                              if str((item.get("target") or {}).get("assertion_id")) == supersedes),
                             None)
            if operation is None:
                continue
            requested = {key for key in (operation.get("value") or {}) if not key.startswith("_")}
            lost = []
            for prop in ("modality", "polarity", "attribution", "scope"):
                if prop in requested:
                    continue
                if old.get(prop) != new.get(prop):
                    lost.append({"property": prop, "before": old.get(prop),
                                 "after": new.get(prop)})
            if "value" in requested:
                for field in ("unit", "context", "value_type"):
                    before_value = (old.get("value") or {}).get(field)
                    after_value = (new.get("value") or {}).get(field)
                    if before_value != after_value:
                        lost.append({"property": f"value.{field}", "before": before_value,
                                     "after": after_value})
            findings.append({"kuyen": data["kuyen_id"], "antu": data["antu_id"],
                             "version": version, "old": supersedes,
                             "new": new.get("assertion_id"), "requested": sorted(requested),
                             "lost": lost})
    return {"assertions_replaced": len(findings),
            "with_semantic_loss": sum(1 for item in findings if item["lost"]),
            "properties_lost": sum(len(item["lost"]) for item in findings),
            "findings": findings}


if __name__ == "__main__":
    report = audit()
    (EXPERIMENT / "evidence/baseline_semantic_audit.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in
                      ("assertions_replaced", "with_semantic_loss", "properties_lost")},
                     indent=2))
    for item in report["findings"]:
        if item["lost"]:
            print(item["kuyen"], item["antu"], item["lost"])


def audit_experiment14() -> dict:
    """The same audit over experiment 14's confirmed runs."""
    data = json.loads((EXPERIMENT / "evidence/real_runs.json").read_text(encoding="utf-8"))["runs"]
    findings = []
    for run in data.values():
        if not run.get("committed") or not run.get("version_after"):
            continue
        memory = KuyenMemory.open(WORK / run["kuyen"] / "memory")
        graph = memory.graph(run["version_after"])
        by_id = {str(obj.get("assertion_id")): obj for obj in graph.get("assertions") or []}
        operations = {str(item.get("operation_id")): item for item in run.get("operations") or []}
        for new in graph.get("assertions") or []:
            supersedes = new.get("supersedes")
            if not supersedes or supersedes not in by_id:
                continue
            old = by_id[supersedes]
            operation = next((item for item in operations.values()
                              if str((item.get("target") or {}).get("assertion_id")) == supersedes),
                             None)
            if operation is None:
                continue
            requested = {key for key in (operation.get("value") or {}) if not key.startswith("_")}
            lost = []
            for prop in ("modality", "polarity", "attribution", "scope"):
                if prop in requested:
                    continue
                if old.get(prop) != new.get(prop):
                    lost.append({"property": prop, "before": old.get(prop),
                                 "after": new.get(prop)})
            if "value" in requested:
                for field in ("unit", "context", "value_type"):
                    before_value = (old.get("value") or {}).get(field)
                    after_value = (new.get("value") or {}).get(field)
                    if before_value != after_value:
                        lost.append({"property": f"value.{field}", "before": before_value,
                                     "after": after_value})
            findings.append({"kuyen": run["kuyen"], "antu": run["antu_id"],
                             "version": run["version_after"], "old": supersedes,
                             "new": new.get("assertion_id"), "requested": sorted(requested),
                             "lost": lost})
    return {"assertions_replaced": len(findings),
            "with_semantic_loss": sum(1 for item in findings if item["lost"]),
            "properties_lost": sum(len(item["lost"]) for item in findings),
            "findings": findings}
