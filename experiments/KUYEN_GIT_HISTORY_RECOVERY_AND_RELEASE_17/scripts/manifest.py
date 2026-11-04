"""SHA-256 manifest of the recovery report and the facts it claims.

    python3 experiments/KUYEN_GIT_HISTORY_RECOVERY_AND_RELEASE_17/scripts/manifest.py

The manifest covers this experiment only; the state of the product files before the intervention
and the necessity matrix are its own evidence files.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import subprocess

EXPERIMENT = pathlib.Path(__file__).resolve().parents[1]
ROOT = EXPERIMENT.parents[1]


def digest(path: pathlib.Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def git(*args: str) -> str:
    done = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=False)
    return done.stdout.strip()


def main() -> int:
    artifacts: dict[str, str] = {}
    for path in sorted(EXPERIMENT.rglob("*")):
        if not path.is_file() or path.name in {".DS_Store", "MANIFEST.json"} \
                or "__pycache__" in path.parts:
            continue
        artifacts[str(path.relative_to(EXPERIMENT))] = digest(path)
    state = json.loads((EXPERIMENT / "evidence" / "final_state.json").read_text(
        encoding="utf-8"))
    payload = {
        "experiment": EXPERIMENT.name,
        "branch": state["branch"],
        "version": state["version"],
        "head_before": state["base"],
        "head_at_audit": state["head"],
        "head_contains_this_manifest":
            "the commit that carries this file; a manifest cannot contain its own hash",
        "commits_added": [item["sha"] for item in state["commits"]],
        "tracked": state["tracked"],
        "tracked_before": state["tracked_before"],
        "clone": state["clone"],
        "worktree_modified_tracked": state["worktree"]["modified_tracked"],
        "push": {"performed": json.loads((EXPERIMENT / "evidence" / "push.json").read_text())
                 if (EXPERIMENT / "evidence" / "push.json").exists() else {"performed": False}},
        "artifacts": artifacts,
    }
    (EXPERIMENT / "MANIFEST.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{len(artifacts)} artifacts · version {payload['version']} · "
          f"commits {len(payload['commits_added'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
