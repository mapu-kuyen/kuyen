# PUBLIC API

The public surface is `kuyen` (package root) and `kuyen.errors`. Everything else is
internal and may change without notice.

```python
from kuyen import KuyenMemory, build_document, __version__
from kuyen.errors import (KuyenError, StoreError, CommitError, ConflictError,
                          ValidationRejected, BackupError, ProjectionError)
```

## KuyenMemory

### Construction

| Operation | Contract |
| --- | --- |
| `KuyenMemory.create(path, *, leftraru_id, purpose="canonical memory")` | Creates a new store and records the owning unit. Raises `StoreError` if the path already holds a store. |
| `KuyenMemory.open(path)` | Opens an existing store read/write. Raises `StoreError` if the path is not a canonical store or the format is unsupported. Never creates or repairs. |
| `memory.path` | `pathlib.Path` of the store root. |
| `memory.store` | Low-level store (`kuyen.storage.store.CanonicalStore`) for adapters. |

### Reading

| Operation | Contract |
| --- | --- |
| `memory.status()` | Snapshot: store format, unit, current pointer, counts, integrity report. |
| `memory.current()` | Current `MemoryVersion` or `None` for an empty memory. |
| `memory.versions()` | All versions, oldest first. |
| `memory.history()` | Unit revisions (one per Antü execution). |
| `memory.ledger()` | The hash-chained Antü event ledger. |
| `memory.lineage(version_id=None)` | Ancestor chain of a version. |
| `memory.graph(version_id=None)` | Canonical graph of a version; hash-verified before returning. Raises `StoreError` if there is no version. |
| `memory.sidecar(version_id=None)` | The canonical sidecar of a version. |
| `memory.source_unit(unit_id, version_id=None)` | One SOURCE_UNIT with its verified text slice. |
| `memory.evidence_of(claim_id, version_id=None)` | Evidence objects supporting a claim. |
| `memory.trace(claim_id, version_id=None)` | claim → evidence → SOURCE_UNIT → MAPU, by identifiers. |

### Antü lifecycle

| Operation | Contract |
| --- | --- |
| `memory.execute_antu(antu, *, mapu_source=None)` | Validates and prepares. Returns `AntuExecution` with `status` in `VALIDATED`, `REJECTED`, `NO_SEMANTIC_CHANGE`, `CONFLICT`, `REPLAYED`. Commits nothing. |
| `memory.commit(execution)` | Persists a `VALIDATED` execution and returns `CommitResult`. A `REPLAYED` execution returns the already committed version. Any other state raises `CommitError`. |
| `memory.record_failed_antu(antu, *, reason)` | Records a failed execution (ledger + unit revision) with no version. |
| `memory.import_canonical(document, *, antu_id="ANTU-IMPORT")` | Commits an externally produced canonical document (bootstrap or new version). |

### Integrity, backup, recovery

| Operation | Contract |
| --- | --- |
| `memory.verify()` | `{"ok": bool, "problems": [str], "versions": [...], "current": id}`. Never raises. |
| `memory.pending()` | Report of an interrupted commit, if any. |
| `memory.recover()` | Replays an interrupted commit; never touches accepted versions. |
| `memory.backup(target)` | Verified backup; returns backup id, version count, root hash. |
| `KuyenMemory.verify_backup(path)` | Raises `BackupError` when the backup does not verify. |
| `KuyenMemory.restore(backup, target)` | Restores into an empty path and returns the memory. Raises `BackupError` on a corrupt backup or non-empty target. |
| `KuyenMemory.recover_from_store(path, *, workdir)` | Rebuilds every version from the store alone and verifies the canonical hash. |

### Projections

| Operation | Contract |
| --- | --- |
| `memory.projections()` | Projection registry entries. |
| `memory.enqueue_projection(version_id, ...)` | Queues a projection request (outbox). |
| `memory.pending_projections()` | Outbox operations. |
| `memory.project(client=..., openviking_version=...)` | Executes pending projections against an external engine. Optional. |
| `memory.reconcile(client=None)` | Compares registered projections with the canonical store. |

## build_document

```python
build_document(graph, mapu_texts, *, mapu_versions=None, source_uris=None) -> dict
```

Builds the canonical document of an accepted graph: canonical record, MAPU records
with content hashes, SOURCE_UNIT inventory with verified slices and object counts.
Raises `ExportError` when a required key or a declared source text is missing.

## Guarantees

1. Deterministic: identical inputs produce identical digests and identifiers.
2. Immutable: an accepted version is never rewritten; a new Antü creates a new version.
3. Validated writes only: no unvalidated semantic write is persisted.
4. Traceable: every claim reaches SOURCE_UNIT and MAPU by identifier.
5. Fail closed: unreadable, corrupted or unsupported state raises or is reported, never guessed.
6. Independent: no operation of the core requires OpenViking, an LLM or a network.

## Compatibility

Contracts are versioned independently (see [VERSIONING.md](VERSIONING.md)): store format
`1.0.0`, sidecar schema `1.0.0`, outbox `1.0.0`, backup `1.0.0`. A store written by a
version of KÜYEN that declares the same format is readable; a different format is refused
with `StoreError` instead of being best-effort parsed.
