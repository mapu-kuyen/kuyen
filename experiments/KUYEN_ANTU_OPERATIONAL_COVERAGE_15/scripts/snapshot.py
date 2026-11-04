"""Before/after state of the ten real KÜYEN and of the preserved experiment artefacts.

`snapshot.py before|after` writes `evidence/state_<phase>.json`: for every memory, its versions,
its current pointer, its integrity verdict and per-object counts. It also hashes every file of
experiments 13 and 14, so "the previous experiments were not modified" is a checkable claim and
not a promise.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from kuyen import KuyenMemory  # noqa: E402

EXPERIMENT = pathlib.Path(__file__).resolve().parents[1]
WORK = pathlib.Path("/tmp/kuyen13_work/instances")
PRESERVED = ("KUYEN_TEN_REAL_MAPU_AND_ANTU_OPERATIONS_13",
             "KUYEN_ANTU_SEMANTIC_FIDELITY_HARDENING_14")


def digest(path: pathlib.Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def state() -> dict:
    memories: dict[str, dict] = {}
    for directory in sorted(WORK.iterdir()):
        memory = KuyenMemory.open(directory / "memory")
        graph = memory.graph()
        memories[directory.name] = {
            "current": (memory.current() or {}).version_id,
            "versions": [item.version_id for item in memory.versions()],
            "verify": memory.verify()["ok"],
            "counts": {"entities": len(graph.get("entities") or []),
                       "relations": len(graph.get("relations") or []),
                       "assertions": len(graph.get("assertions") or []),
                       "evidence": len(graph.get("evidence") or [])},
            "schema_fields": {name: sorted((spec.get("attributes") or {}))
                              for name, spec in (graph.get("schema") or {}).get(
                                  "entity_types", {}).items()},
        }
    preserved: dict[str, str] = {}
    for name in PRESERVED:
        for path in sorted((ROOT / "experiments" / name).rglob("*")):
            if path.is_file() and path.suffix not in (".zip",) and ".DS_Store" not in path.name:
                preserved[str(path.relative_to(ROOT))] = digest(path)
    return {"memories": memories, "preserved": preserved}


def main() -> int:
    phase = sys.argv[1] if len(sys.argv) > 1 else "before"
    payload = {"phase": phase, **state()}
    path = EXPERIMENT / "evidence" / f"state_{phase}.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    total = sum(len(item["versions"]) for item in payload["memories"].values())
    print(f"{path.name}: {len(payload['memories'])} memories, {total} versions, "
          f"{len(payload['preserved'])} preserved files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
