#!/usr/bin/env python3
"""Verify that the shipped quickstart works from the built wheel and from the sdist.

KUYEN_RELEASE_QUICKSTART_REPAIR_02. This is a *package-level* check and it is
deliberately not part of the ordinary suite: it builds (or accepts) the two
distribution artifacts, installs each one in its own throw-away virtual environment and
runs `examples/quickstart.py` from a temporary directory outside the repository.

Usage::

    python scripts/verify_distribution.py
    python scripts/verify_distribution.py --no-build \\
        --wheel dist/kuyen-0.2.1rc1-py3-none-any.whl \\
        --sdist dist/kuyen-0.2.1rc1.tar.gz
    python scripts/verify_distribution.py --python 3.11 --python 3.13 --json-out report.json

Exit code is 0 only when every (artifact, interpreter) combination passes.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EXAMPLE = REPO / "examples" / "quickstart.py"
DEFAULT_PYTHONS = ("3.11", "3.13")

# Runs inside the throw-away environment: opens the memory the example produced and
# reports, as JSON, what an external user can verify through the public API.
INSPECT = r"""
import json, sys
from kuyen import KuyenMemory
import kuyen

memory = KuyenMemory.open(sys.argv[1])
sidecar = memory.sidecar()
uris = {mapu["mapu_id"]: mapu["source_uri"] for mapu in sidecar["mapus"]}
evidence = sidecar["canonical"]["evidence"]
print(json.dumps({
    "import_path": kuyen.__file__,
    "package_version": kuyen.__version__,
    "versions": len(memory.versions()),
    "current": memory.current().version_id if memory.current() else None,
    "parent": memory.current().parent_version_id if memory.current() else None,
    "verify_ok": memory.verify()["ok"],
    "problems": memory.verify()["problems"],
    "evidence": len(evidence),
    "evidence_uris_match_mapu": all(item["source_uri"] == uris[item["mapu_id"]]
                                    for item in evidence),
    "mapu_uris": uris,
}))
"""


def find_python(requested: str) -> str | None:
    """Locate an interpreter for a version spec such as '3.11'."""
    if Path(requested).exists():
        return requested
    candidate = shutil.which(requested)
    if candidate:
        return candidate
    for name in (f"python{requested}", f"python{requested.replace('.', '')}"):
        candidate = shutil.which(name)
        if candidate:
            return candidate
    return None


def run(cmd: list[str], *, cwd: Path | None = None,
        env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(cwd) if cwd else None, env=env,
                          capture_output=True, text=True, timeout=1800)


def build_artifacts(workdir: Path) -> tuple[Path, Path]:
    dist = workdir / "dist"
    result = run([sys.executable, "-m", "build", "--outdir", str(dist)], cwd=REPO)
    if result.returncode != 0:
        raise SystemExit(f"build failed:\n{result.stdout}\n{result.stderr}")
    return next(dist.glob("*.whl")), next(dist.glob("*.tar.gz"))


def pip(venv_dir: Path) -> str:
    return str(venv_dir / "bin" / "pip")


def python(venv_dir: Path) -> str:
    return str(venv_dir / "bin" / "python")


def verify_one(python_spec: str, artifact: Path, kind: str, workdir: Path) -> dict:
    """Install one artifact in a clean venv and run the example from outside the repo."""
    record: dict = {"python": python_spec, "artifact": artifact.name, "kind": kind}
    interpreter = find_python(python_spec)
    if interpreter is None:
        record.update(passed=False, skipped=True,
                      reason=f"interpreter {python_spec} not available")
        return record
    root = Path(tempfile.mkdtemp(prefix=f"kuyen-{kind}-{python_spec}-", dir=workdir))
    venv_dir = root / "venv"
    # `python -m venv` is the only way to build the environment with a *different*
    # interpreter: venv.EnvBuilder always clones the interpreter running this script.
    created = run([interpreter, "-m", "venv", str(venv_dir)])
    if created.returncode != 0:
        record.update(passed=False, reason=f"venv creation failed: {created.stderr[-500:]}")
        return record
    record["interpreter"] = run([python(venv_dir), "-V"]).stdout.strip()
    record["interpreter_matches_request"] = python_spec in record["interpreter"]

    install = run([pip(venv_dir), "install", "--quiet", str(artifact)])
    record["install_ok"] = install.returncode == 0
    record["install_log"] = (install.stdout + install.stderr)[-2000:]
    if not record["install_ok"]:
        record.update(passed=False)
        return record

    check = run([pip(venv_dir), "check"])
    record["pip_check_ok"] = check.returncode == 0
    record["pip_check"] = (check.stdout + check.stderr).strip()

    # The example is copied out of the repository and run from a temporary directory,
    # with no PYTHONPATH, so nothing can be imported from the source tree.
    run_dir = root / "run"
    run_dir.mkdir()
    shutil.copy2(EXAMPLE, run_dir / "quickstart.py")
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    executed = run([python(venv_dir), str(run_dir / "quickstart.py"), str(root / "demo")],
                   cwd=run_dir, env=env)
    record["example_exit"] = executed.returncode
    record["example_stdout"] = executed.stdout
    record["example_stderr"] = executed.stderr[-3000:]
    record["evidence_uri_mismatch"] = "EVIDENCE_URI_MISMATCH" in (executed.stdout
                                                                  + executed.stderr)
    record["committed_two_versions"] = "parent VER-" in executed.stdout
    record["verify_line"] = next((line for line in executed.stdout.splitlines()
                                  if line.startswith("verify: ")), "")

    inspected = run([python(venv_dir), "-c", INSPECT, str(root / "demo" / "memory")])
    record["inspect_ok"] = inspected.returncode == 0
    if inspected.returncode == 0:
        state = json.loads(inspected.stdout.strip().splitlines()[-1])
        record["state"] = state
        record["imported_from_site_packages"] = "site-packages" in state["import_path"]
        record["imported_from_repository"] = str(REPO) in state["import_path"]
    else:
        record["inspect_stderr"] = inspected.stderr[-2000:]

    state = record.get("state", {})
    record["passed"] = bool(
        record["install_ok"]
        and record["pip_check_ok"]
        and record["example_exit"] == 0
        and not record["evidence_uri_mismatch"]
        and record.get("committed_two_versions")
        and record["inspect_ok"]
        and record.get("interpreter_matches_request")
        and record.get("imported_from_site_packages")
        and not record.get("imported_from_repository")
        and state.get("versions") == 2
        and state.get("verify_ok") is True
        and state.get("evidence_uris_match_mapu") is True
    )
    return record



def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--no-build", action="store_true",
                        help="use the artifacts given by --wheel/--sdist")
    parser.add_argument("--wheel")
    parser.add_argument("--sdist")
    parser.add_argument("--python", action="append", dest="pythons",
                        help="interpreter version to test (repeatable); default 3.11 and 3.13")
    parser.add_argument("--json-out", help="write the full result as JSON")
    args = parser.parse_args(argv)

    workdir = Path(tempfile.mkdtemp(prefix="kuyen-dist-verify-"))
    if args.no_build:
        if not (args.wheel and args.sdist):
            parser.error("--no-build requires --wheel and --sdist")
        wheel, sdist = Path(args.wheel).resolve(), Path(args.sdist).resolve()
    else:
        wheel, sdist = build_artifacts(workdir)

    pythons = args.pythons or list(DEFAULT_PYTHONS)
    results = []
    for kind, artifact in (("wheel", wheel), ("sdist", sdist)):
        for spec in pythons:
            record = verify_one(spec, artifact, kind, workdir)
            results.append(record)
            status = "SKIP" if record.get("skipped") else ("PASS" if record["passed"] else "FAIL")
            print(f"[{status}] {kind:5s} py{spec}  {record.get('interpreter', '')}  "
                  f"{artifact.name}")
            if status == "FAIL":
                print(f"        example_exit={record.get('example_exit')} "
                      f"pip_check={record.get('pip_check')!r}")
                if record.get("example_stderr"):
                    tail = record["example_stderr"].strip().splitlines()[-1:]
                    print("        stderr:", tail)

    summary = {
        "generated_at_utc": datetime.datetime.now(datetime.timezone.utc)
                            .isoformat().replace("+00:00", "Z"),
        "repository": str(REPO),
        "artifacts": {"wheel": str(wheel), "sdist": str(sdist)},
        "results": results,
        "all_passed": all(record["passed"] for record in results if not record.get("skipped")),
        "skipped": [f"{record['kind']}/py{record['python']}"
                    for record in results if record.get("skipped")],
    }
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(summary, indent=2, default=str),
                                       encoding="utf-8")
    print(f"\nall_passed={summary['all_passed']}  results={len(results)}  "
          f"skipped={summary['skipped']}")
    return 0 if summary["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
