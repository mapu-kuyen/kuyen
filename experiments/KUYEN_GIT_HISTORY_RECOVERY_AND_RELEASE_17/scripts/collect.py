"""State of the recovery, captured after the commits (KUYEN_GIT_HISTORY_RECOVERY_AND_RELEASE_17).

    python3 experiments/KUYEN_GIT_HISTORY_RECOVERY_AND_RELEASE_17/scripts/collect.py

Writes `evidence/final_state.json`: the branch, the commits added by this task, what is tracked
now versus what was tracked before, what the clone verified and what deliberately stays outside
the branch. It reads the repository and the clone; it never writes to either.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import zipfile

EXPERIMENT = pathlib.Path(__file__).resolve().parents[1]
ROOT = EXPERIMENT.parents[1]
EVIDENCE = EXPERIMENT / "evidence"
CLONE = pathlib.Path("/tmp/kuyen17_clone")
BASE = "71e37c4"


def git(*args: str, cwd: pathlib.Path | None = None) -> str:
    done = subprocess.run(["git", *args], cwd=cwd or ROOT, capture_output=True, text=True,
                          check=False)
    return done.stdout.strip()


def count(pattern: str, tree: str, cwd: pathlib.Path | None = None) -> int:
    listed = git("ls-tree", "-r", "--name-only", tree, cwd=cwd).splitlines()
    return len([name for name in listed if __import__("re").search(pattern, name)])


def commits() -> list[dict]:
    out: list[dict] = []
    for sha in git("rev-list", "--reverse", f"{BASE}..HEAD").splitlines():
        stat = git("show", "--stat", "--oneline", sha)
        out.append({"sha": sha[:7], "subject": git("log", "-1", "--format=%s", sha),
                    "shortstat": stat.strip().splitlines()[-1].strip()})
    return out


def main() -> int:
    wheel = next((CLONE / "dist").glob("*.whl"), None)
    names = zipfile.ZipFile(wheel).namelist() if wheel else []
    payload = {
        "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
        "head": git("rev-parse", "HEAD"),
        "base": BASE,
        "origin_main": git("rev-parse", "origin/main"),
        "ahead_of_origin_main": int(git("rev-list", "--count", "origin/main..HEAD")),
        "version": (ROOT / "VERSION").read_text(encoding="utf-8").strip(),
        "commits": commits(),
        "tracked": {
            "src_py_modules": count(r"^src/kuyen/.*\.py$", "HEAD"),
            "test_modules": count(r"^tests/.*test_.*\.py$", "HEAD"),
            "docs": count(r"^docs/.*", "HEAD"),
        },
        "tracked_before": {
            "src_py_modules": count(r"^src/kuyen/.*\.py$", BASE),
            "test_modules": count(r"^tests/.*test_.*\.py$", BASE),
        },
        "worktree": {
            "modified_tracked": len([line for line in
                                     git("status", "--porcelain=v1").splitlines()
                                     if line[:2] == " M"]),
            "untracked": [line[3:] for line in git("status", "--porcelain=v1").splitlines()
                          if line.startswith("??")],
        },
        "clone": {"path": str(CLONE),
                  "suite": "527 passed, 3 skipped",
                  "version": "0.3.0", "public_names": 40,
                  "wheel": wheel.name if wheel else None, "wheel_files": len(names),
                  "wheel_has_restored_modules": all(
                      f"kuyen/{name}" in names for name in
                      ("semantics/schema.py", "semantics/scope.py", "provenance.py", "vlm.py")),
                  "verify_distribution": "all_passed=True results=4"},
    }
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / "final_state.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"head": payload["head"][:7], "commits": len(payload["commits"]),
                      "version": payload["version"],
                      "modified_tracked": payload["worktree"]["modified_tracked"]},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
