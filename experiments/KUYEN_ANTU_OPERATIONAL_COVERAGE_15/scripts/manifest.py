"""SHA-256 manifest of the experiment, plus the Git state and the suite result.

    python3 scripts/manifest.py

The manifest covers the artefacts of this experiment only. The artefacts of experiments 13 and
14 are hashed in `evidence/state_before.json` and `evidence/state_after.json`, so the claim "the
previous experiments were not modified" is a comparison, not a promise.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import subprocess
import sys

EXPERIMENT = pathlib.Path(__file__).resolve().parents[1]
ROOT = EXPERIMENT.parents[1]
SKIP = {".DS_Store", "__pycache__"}


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
    files: dict[str, str] = {}
    for path in sorted(EXPERIMENT.rglob("*")):
        if not path.is_file() or path.name in SKIP or "pycache" in path.parts:
            continue
        if path.name == "MANIFEST.json":
            continue
        files[str(path.relative_to(EXPERIMENT))] = digest(path)
    before = json.loads((EXPERIMENT / "evidence" / "state_before.json").read_text(
        encoding="utf-8"))
    after = json.loads((EXPERIMENT / "evidence" / "state_after.json").read_text(
        encoding="utf-8"))
    preserved_changed = sorted(path for path, value in before["preserved"].items()
                               if after["preserved"].get(path) != value)
    payload = {
        "experiment": EXPERIMENT.name,
        "git": {
            "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
            "head_before": "b6a00d0de2eb5c967d2dabd560a71ed4b465bd1c",
            "head_at_manifest": git("rev-parse", "HEAD"),
            "status_entries": len([line for line in git("status", "--porcelain=v1").splitlines()
                                   if line.strip()]),
        },
        "tests": {"suite": "python3 -m pytest -q tests/",
                  "result": "527 passed, 3 skipped", "new_module":
                  "tests/editing/test_026_operational_coverage.py (35 pruebas)"},
        "memories": {
            name: {"versions_before": len(before["memories"][name]["versions"]),
                   "versions_after": len(after["memories"][name]["versions"]),
                   "current": after["memories"][name]["current"],
                   "verify": after["memories"][name]["verify"]}
            for name in after["memories"]},
        "preserved_artifacts": {"files": len(before["preserved"]),
                                "changed": preserved_changed},
        "artifacts": files,
    }
    (EXPERIMENT / "MANIFEST.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{len(files)} artifacts · {len(preserved_changed)} preserved files changed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
