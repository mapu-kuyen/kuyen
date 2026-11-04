"""Collect the evidence of the production-readiness audit (KUYEN_PRODUCTION_READINESS_16).

The audit answers one question: does the *published history* install and run, or does it only
run in the working tree? Every number in `REPORT.md` comes from one of these collectors, and the
script never modifies the repository, the working tree or the clean checkout.

    python3 experiments/KUYEN_PRODUCTION_READINESS_16/scripts/collect.py

Environment (defaults are the ones used in the report):

    KUYEN_REPO            repository root                (~/…/kuyen_hardening_01/kuyen)
    KUYEN_CLEAN           clean worktree at HEAD         (/tmp/kuyen_production_clean_16)
    KUYEN_WORKSPACE_COPY  diagnostic copy of the whole    (/tmp/kuyen16_diag_b)
                          working tree (HEAD + the 69 entries)
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
import zipfile

EXPERIMENT = pathlib.Path(__file__).resolve().parents[1]
EVIDENCE = EXPERIMENT / "evidence"
REPO = pathlib.Path(os.environ.get("KUYEN_REPO", "/private/tmp/kuyen_hardening_01/kuyen"))
CLEAN = pathlib.Path(os.environ.get("KUYEN_CLEAN", "/tmp/kuyen_production_clean_16"))
WORKSPACE_COPY = pathlib.Path(os.environ.get("KUYEN_WORKSPACE_COPY", "/tmp/kuyen16_diag_b"))
PRESERVED = ("KUYEN_TEN_REAL_MAPU_AND_ANTU_OPERATIONS_13",
             "KUYEN_ANTU_SEMANTIC_FIDELITY_HARDENING_14",
             "KUYEN_ANTU_OPERATIONAL_COVERAGE_15")


def git(*args: str) -> str:
    completed = subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True,
                               check=False)
    return completed.stdout.strip()


def digest(path: pathlib.Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def status_entries() -> list[dict[str, str]]:
    entries = []
    for line in git("status", "--porcelain=v1").splitlines():
        if not line.strip():
            continue
        entries.append({"state": line[:2].strip(), "path": line[3:]})
    return entries


def _split_own(entries: list[dict[str, str]]) -> tuple[list[dict], list[dict]]:
    """Separate the pre-existing work from the directory this audit created."""
    own = str(EXPERIMENT.relative_to(REPO))
    preexisting = [item for item in entries if not item["path"].startswith(own)]
    this_audit = [item for item in entries if item["path"].startswith(own)]
    return preexisting, this_audit


def git_state() -> dict:
    entries = status_entries()
    preexisting, this_audit = _split_own(entries)
    behind, ahead = git("rev-list", "--left-right", "--count", "origin/main...HEAD").split()
    tags = {}
    for tag in git("tag", "-l").splitlines():
        tags[tag] = git("rev-parse", f"{tag}^{{commit}}")
    return {
        "root": str(REPO),
        "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
        "head": git("rev-parse", "HEAD"),
        "head_short": git("rev-parse", "--short", "HEAD"),
        "head_subject": git("log", "-1", "--format=%s"),
        "origin_url": git("remote", "get-url", "origin"),
        "upstream": git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}") or None,
        "origin_main": git("rev-parse", "origin/main"),
        "ahead_of_origin_main": int(ahead),
        "behind_origin_main": int(behind),
        "tags": tags,
        "version_worktree": (REPO / "VERSION").read_text(encoding="utf-8").strip(),
        "version_head": git("show", "HEAD:VERSION"),
        "version_origin_main": git("show", "origin/main:VERSION"),
        "counts": {
            "preexisting_total": len(preexisting),
            "preexisting_modified": sum(1 for item in preexisting if item["state"] == "M"),
            "preexisting_untracked": sum(1 for item in preexisting if item["state"] == "??"),
            "this_audit": len(this_audit),
            "total_now": len(entries),
        },
        "preexisting_entries": preexisting,
        "this_audit_entries": this_audit,
        "commits": [line.split(" ", 1) for line in
                    git("log", "--format=%h %s", "origin/main..HEAD").splitlines()],
    }



def known_files(entry: dict) -> list[pathlib.Path]:
    """The files an entry of `git status` covers (a directory is walked)."""
    target = REPO / entry["path"]
    if target.is_dir():
        return sorted(path for path in target.rglob("*")
                      if path.is_file() and "__pycache__" not in path.parts
                      and ".DS_Store" not in path.name)
    return [target] if target.is_file() else []


def working_tree_manifest(state: dict) -> dict:
    """SHA-256 of everything the audit promises not to touch."""
    files: dict[str, str] = {}
    for entry in state["preexisting_entries"]:
        for path in known_files(entry):
            files[str(path.relative_to(REPO))] = digest(path)
    preserved: dict[str, str] = {}
    for name in PRESERVED:
        for path in sorted((REPO / "experiments" / name).rglob("*")):
            if path.is_file() and path.suffix != ".zip" and ".DS_Store" not in path.name \
                    and "__pycache__" not in path.parts:
                preserved[str(path.relative_to(REPO))] = digest(path)
    return {"working_tree_files": files, "preserved_experiments": preserved,
            "counts": {"working_tree": len(files), "preserved": len(preserved)}}


def tracked_modules() -> list[str]:
    return [line for line in git("ls-tree", "-r", "--name-only", "HEAD", "src/").splitlines()
            if line.endswith(".py")]


def module_gap() -> dict:
    """Which modules the code imports and the published history does not contain."""
    shipped = set(tracked_modules())
    present = sorted(str(path.relative_to(REPO)) for path in (REPO / "src").rglob("*.py")
                     if "__pycache__" not in path.parts)
    missing = [path for path in present if path not in shipped]
    importers: dict[str, list[str]] = {}
    for path in sorted((REPO / "src").rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for module in missing:
            stem = pathlib.Path(module).stem
            if re.search(rf"from \.+[\w.]*\b{stem} import|\bimport {stem}\b", text):
                importers.setdefault(module, []).append(str(path.relative_to(REPO)))
    return {"modules_in_source": len(present), "modules_at_head": len(shipped),
            "missing_from_history": missing,
            "importers": {key: sorted(set(value)) for key, value in importers.items()},
            "first_import_failure": import_failure()}


def import_failure() -> str:
    completed = subprocess.run([sys.executable, "-c", "import kuyen"], cwd=CLEAN,
                               capture_output=True, text=True,
                               env={**os.environ, "PYTHONPATH": "src"})
    if completed.returncode == 0:
        return "import ok"
    return (completed.stderr or completed.stdout).strip().splitlines()[-1]



def distribution() -> dict:
    """What the clean checkout builds, ships and installs."""
    wheel = next((CLEAN / "dist").glob("*.whl"), None)
    sdist = next((CLEAN / "dist").glob("*.tar.gz"), None)
    payload: dict = {"clean_dir": str(CLEAN), "wheel": wheel.name if wheel else None,
                     "sdist": sdist.name if sdist else None}
    if wheel:
        names = zipfile.ZipFile(wheel).namelist()
        payload["wheel_files"] = len(names)
        payload["wheel_suspicious"] = [name for name in names
                                       if any(part in name for part in
                                              (".env", "experiments/", "tests/", "runs/",
                                               ".coverage", "scripts/"))]
        payload["wheel_python_modules"] = sorted(name for name in names
                                                 if name.startswith("kuyen/")
                                                 and name.endswith(".py"))
    workspace_wheel = next((WORKSPACE_COPY / "dist").glob("*.whl"), None)
    if workspace_wheel:
        payload["workspace_wheel"] = workspace_wheel.name
        payload["workspace_wheel_files"] = len(zipfile.ZipFile(workspace_wheel).namelist())
    return payload


def api_surface() -> dict:
    """The public names, read from the diagnostic copy where the package imports."""
    completed = subprocess.run(
        [sys.executable, "-c",
         "import json, kuyen; print(json.dumps({'version': kuyen.__version__,"
         " 'all': sorted(kuyen.__all__)}))"],
        cwd=WORKSPACE_COPY, capture_output=True, text=True,
        env={**os.environ, "PYTHONPATH": "src"})
    if completed.returncode != 0:
        return {"error": completed.stderr.strip().splitlines()[-1]}
    return json.loads(completed.stdout)


def docs_audit() -> dict:
    """Which documents exist in the history and what the public API doc mentions."""
    committed = [line for line in git("ls-tree", "-r", "--name-only", "HEAD").splitlines()
                 if line.endswith(".md")]
    present = sorted(str(path.relative_to(REPO)) for path in REPO.rglob("*.md")
                     if ".git" not in path.parts and "experiments" not in path.parts
                     and "__pycache__" not in path.parts)
    public = (REPO / "PUBLIC_API.md").read_text(encoding="utf-8")
    topics = {"outcome vocabulary": "outcome", "editing operations": "UPDATE_ENTITY",
              "VLM configuration": "VlmProviderConfig", "OpenViking": "OpenViking",
              "embeddings": "embedding"}
    return {"committed_docs": committed, "docs_in_workspace": present,
            "public_api_mentions": {topic: needle in public
                                    for topic, needle in topics.items()},
            "bilingual_pairs": [name for name in committed if name.endswith(".en.md")],
            "headers": {path.name: path.read_text(encoding="utf-8", errors="ignore")
                        .splitlines()[0]
                        for path in sorted(REPO.glob("*.md"))}}


def main() -> int:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    state = git_state()
    for name, payload in (
            ("state_initial.json", state),
            ("working_tree_sha256.json", working_tree_manifest(state)),
            ("module_gap.json", module_gap()),
            ("distribution.json", distribution()),
            ("api_surface.json", api_surface()),
            ("docs_audit.json", docs_audit())):
        (EVIDENCE / name).write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                                     encoding="utf-8")
    print(json.dumps({"head": state["head_short"], "counts": state["counts"],
                      "ahead_of_origin_main": state["ahead_of_origin_main"],
                      "version_head": state["version_head"],
                      "version_worktree": state["version_worktree"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

