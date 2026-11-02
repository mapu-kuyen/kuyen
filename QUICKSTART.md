# QUICKSTART

This walkthrough runs against the installed package and uses only the public API.
The executable copy lives in [`examples/quickstart.py`](examples/quickstart.py).

## 1. Create a memory

```python
from kuyen import KuyenMemory

memory = KuyenMemory.create("./memory", leftraru_id="LR-0001", purpose="wine domain")
```

`create` makes the store, records the owning Leftraru unit once and returns a memory
whose `current()` is `None`. Opening an existing memory with `KuyenMemory.open(path)`
never creates or repairs anything.

## 2. Commit the first canonical version

Knowledge enters through a canonical document: an accepted graph plus the source texts
that support it.

```python
from kuyen import build_document

document = build_document(graph, {mapu_id: source_text})
result = memory.import_canonical(document)
print(result.version.version_id, result.version.kuyen_version)   # VER-…, 1.0.0
```

`build_document` verifies that every evidence quote is inside its SOURCE_UNIT and
records the content hash of each MAPU. It never rewrites the text.

## 3. Read the memory

```python
memory.current()          # the current MemoryVersion
memory.versions()         # all versions, oldest first
memory.graph()            # canonical objects of the current version
memory.graph(version_id)  # any historical version
memory.history()          # one unit revision per Antü execution
memory.status()           # store, unit, current, counts and integrity
```

## 4. Execute an Antü

An Antü is an instruction with a proposal. Executing it validates the proposal; it does
**not** commit it.

```python
execution = memory.execute_antu(antu, mapu_source="MAPU-02.txt")
assert execution.status in {"VALIDATED", "REJECTED", "NO_SEMANTIC_CHANGE", "CONFLICT", "REPLAYED"}
```

The validator checks identities, predicates, polarity, temporality, evidence offsets,
MAPU hashes, coverage and referential integrity. A rejected Antü is recorded in the
ledger and produces no version.

## 5. Commit

```python
result = memory.commit(execution)      # raises CommitError if the execution is not VALIDATED
print(result.version.parent_version_id, result.version.kuyen_version)
```

## 6. Trace a claim back to the source

```python
for item in memory.trace(relation_id)["evidence"]:
    print(item["quote"], item["source_unit_id"], item["mapu_id"])
```

## 7. Back up, restore, recover

```python
memory.backup("./backup-kuyen")
restored = KuyenMemory.restore("./backup-kuyen", "./memory-restored")
report = KuyenMemory.recover_from_store(memory.path, workdir="./recovery")
assert all(version["reconstruction"]["accepted"] for version in report["versions"])
```

None of these steps needs OpenViking, a model or a network connection.

## 8. Verify integrity at any time

```python
report = memory.verify()
assert report["ok"], report["problems"]
```

## Licence

Licensed under the Apache License, Version 2.0 — see [`LICENSE`](LICENSE) or
<https://www.apache.org/licenses/LICENSE-2.0.txt>. The idempotent `SPDX` identifier is
`Apache-2.0`. The licence covers the software only; it does not grant rights over the KÜYEN
name or marks.
