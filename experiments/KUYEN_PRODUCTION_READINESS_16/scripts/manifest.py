"""SHA-256 manifest of this audit and the verdict it reaches.

    python3 experiments/KUYEN_PRODUCTION_READINESS_16/scripts/manifest.py

The manifest covers this experiment only. The state of the working tree and of the artefacts of
experiments 13, 14 and 15 is hashed in `evidence/working_tree_sha256.json`, so "nothing was
touched" is a comparison and not a promise.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import subprocess

EXPERIMENT = pathlib.Path(__file__).resolve().parents[1]
ROOT = EXPERIMENT.parents[1]
SKIP = {".DS_Store"}


def digest(path: pathlib.Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def git(*args: str) -> str:
    completed = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True,
                               check=False)
    return completed.stdout.strip()


def main() -> int:
    artifacts: dict[str, str] = {}
    for path in sorted(EXPERIMENT.rglob("*")):
        if not path.is_file() or path.name in SKIP or path.name == "MANIFEST.json" \
                or "__pycache__" in path.parts:
            continue
        artifacts[str(path.relative_to(EXPERIMENT))] = digest(path)
    state = json.loads((EXPERIMENT / "evidence" / "state_initial.json").read_text(
        encoding="utf-8"))
    gap = json.loads((EXPERIMENT / "evidence" / "module_gap.json").read_text(encoding="utf-8"))
    ci_runs = json.loads((EXPERIMENT / "evidence" / "ci_runs.json").read_text(encoding="utf-8"))
    payload = {
        "experiment": EXPERIMENT.name,
        "decision": "NOT_READY",
        "pushed": False,
        "git": {"branch": state["branch"], "head_at_audit_start": state["head"],
                "head_contains_this_manifest":
                    "the commit that carries this file; a manifest cannot contain its own hash",
                "origin_main": state["origin_main"],
                "ahead_of_origin_main": state["ahead_of_origin_main"],
                "version_head": state["version_head"],
                "version_worktree": state["version_worktree"]},
        "clean_checkout": {"path": "/tmp/kuyen_production_clean_16",
                           "suite": "no colecciona: ModuleNotFoundError kuyen.semantics.schema",
                           "first_import_failure": gap["first_import_failure"]},
        "workspace_copy": {"path": "/tmp/kuyen16_diag_b",
                           "suite": "527 passed, 3 skipped, 0 failed"},
        "missing_from_history": gap["missing_from_history"],
        "working_tree": state["counts"],
        "ci": {"runs": ci_runs.get("total_count"),
               "conclusions": sorted({run.get("conclusion")
                                      for run in ci_runs.get("workflow_runs", [])}),
               "branch_without_run": state["branch"]},
        "recommended_version": "0.3.0",
        "artifacts": artifacts,
    }
    (EXPERIMENT / "MANIFEST.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{len(artifacts)} artifacts · decision={payload['decision']} · pushed=False")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
