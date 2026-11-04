"""Comparative analysis of experiment 13 (baseline) and experiment 14 (hardening).

Every number is read from the recorded runs; nothing is typed by hand.
"""
from __future__ import annotations

import csv
import glob
import json
import pathlib

EXPERIMENT = pathlib.Path(__file__).resolve().parents[1]
ROOT = EXPERIMENT.parents[1]
EXP13 = ROOT / "experiments/KUYEN_TEN_REAL_MAPU_AND_ANTU_OPERATIONS_13"
EVIDENCE = EXPERIMENT / "evidence"
BENCH = EXPERIMENT / "benchmarks"


def exp13_runs() -> list[dict]:
    rows = []
    for path in sorted(glob.glob(str(EXP13 / "evidence/KUYEN-*/antu/*.json"))):
        data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
        result = data.get("result") or {}
        committed = data.get("status") == "COMMITTED"
        usage = data.get("usage") or {}
        rows.append({
            "experiment": "13", "kuyen": data["kuyen_id"], "antu": data["antu_id"],
            "case": data.get("category"), "status": data.get("status"),
            "committed": committed,
            "proposed": len(((data.get("proposal") or {}).get("operations")) or []),
            "applied": len(result.get("operations") or []) if committed else 0,
            "declined": len(result.get("declined") or []),
            "rejected": len(result.get("rejected") or []),
            "semantic_violations": "n/a",
            "seconds": data.get("seconds"),
            "input_tokens": usage.get("prompt_tokens", ""),
            "output_tokens": usage.get("completion_tokens", ""),
            "cost_usd": usage.get("cost_usd", ""),
        })
    return rows


def exp14_runs() -> list[dict]:
    data = json.loads((EVIDENCE / "real_runs.json").read_text(encoding="utf-8"))["runs"]
    rows = []
    for key, run in sorted(data.items()):
        checks = run.get("semantic_checks") or []
        violations = sum(len(check.get("violations") or []) for check in checks)
        usage = run.get("usage") or {}
        rows.append({
            "experiment": "14", "kuyen": run.get("kuyen"), "antu": run.get("antu_id"),
            "case": run.get("case"), "status": run.get("status"),
            "committed": bool(run.get("committed")),
            "proposed": len(((run.get("proposal") or {}).get("operations")) or []),
            "applied": len([item for item in (run.get("applied") or [])
                            if item.get("status") == "COMMITTED"]),
            "declined": len(run.get("declined") or []),
            "rejected": len(run.get("rejected") or []),
            "semantic_violations": violations,
            "seconds": run.get("seconds"),
            "input_tokens": usage.get("prompt_tokens", ""),
            "output_tokens": usage.get("completion_tokens", ""),
            "cost_usd": usage.get("cost_usd", ""),
        })
    return rows


def main() -> int:
    BENCH.mkdir(parents=True, exist_ok=True)
    rows = exp13_runs() + exp14_runs()
    fields = ["experiment", "kuyen", "antu", "case", "status", "committed", "proposed",
              "applied", "declined", "rejected", "semantic_violations", "seconds",
              "input_tokens", "output_tokens", "cost_usd"]
    with (BENCH / "runs.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    summary: dict = {}
    for experiment in ("13", "14"):
        subset = [row for row in rows if row["experiment"] == experiment]
        summary[experiment] = {
            "evaluations": len(subset),
            "committed": sum(1 for row in subset if row["committed"]),
            "no_changes": sum(1 for row in subset if row["status"] == "NO_CHANGES"),
            "rejected": sum(1 for row in subset if row["status"] == "REJECTED"),
            "clarification": sum(1 for row in subset if row["status"] == "CLARIFICATION_REQUIRED"),
            "failed": sum(1 for row in subset if row["status"] == "FAILED"),
            "semantic_violations": sum(int(row["semantic_violations"])
                                       for row in subset
                                       if str(row["semantic_violations"]).isdigit()),
            "cost_usd": round(sum(float(row["cost_usd"] or 0) for row in subset), 6),
            "seconds": round(sum(float(row["seconds"] or 0) for row in subset), 2),
        }
    (EVIDENCE / "comparison.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
