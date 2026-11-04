# PUBLIC API

The public surface is `kuyen` (package root) and `kuyen.errors`. Everything else is
internal and may change without notice.

```python
from kuyen import KuyenMemory, build_document, __version__
from kuyen.errors import (KuyenError, StoreError, AmbiguousSourceUnit, CommitError,
                          ConflictError, ValidationRejected, BackupError, ProjectionError)
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
| `memory.source_unit(unit_id, version_id=None, *, mapu_id=None)` | One SOURCE_UNIT with its verified text slice. `unit_id` is local to a MAPU: pass `mapu_id` to select the document; without it the identifier must be unique, otherwise `AmbiguousSourceUnit` is raised — the first match is never returned. Raises `StoreError` when the MAPU or the unit does not exist. |
| `memory.evidence_of(claim_id, version_id=None)` | Evidence objects supporting a claim. |
| `memory.trace(claim_id, version_id=None)` | claim → evidence → SOURCE_UNIT → MAPU, resolved inside the evidence's own MAPU and verified (MAPU, unit span, unit hash, quote at its offsets). Raises `StoreError` if any step of the chain does not verify. |

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
| `memory.verify()` | `{"ok": bool, "problems": [str], "versions": [...], "current": id, "registry": {...}, "objects": {...}, "ledger": {...}, "unit_history": {...}}`. Never raises. |
| `memory.pending()` | Report of an interrupted commit, if any: leftover staging, unconfirmed versions, unindexed objects. |
| `memory.recover()` | Finishes an interrupted commit and repairs an incomplete ledger tail. Returns `completed`, `staging_discarded`, `staging_kept`, `current_advanced`, `current_adopted`, `current_ambiguous`, `ledger`, `projections`, `unit_history`. Idempotent; never touches accepted versions. |
| `memory.backup(target)` | Verified backup; returns backup id, version count, root hash. |
| `KuyenMemory.verify_backup(path)` | Raises `BackupError` when the backup does not verify. |
| `KuyenMemory.restore(backup, target)` | Restores into a missing or **empty** directory and returns the memory. Raises `BackupError` on a corrupt backup, a non-empty target, a file, a symbolic link, or a target related to the backup itself. |
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
build_document(graph, mapu_texts, *, mapu_versions=None, source_uris=None,
               source_bytes=None, encodings=None) -> dict
```

Builds the canonical document of an accepted graph: canonical record, MAPU records
with content hashes, SOURCE_UNIT inventory with verified slices and object counts.
`source_bytes` passes the original bytes of each MAPU: they are hashed as bytes
(`source_bytes_sha256`, `source_hash_scope`) and recorded with `encoding`, `newline_policy`
and `offset_unit`, so a CRLF document and its LF conversion stay distinguishable. Raises
`ExportError` when a required key or a declared source text is missing, or when the bytes
do not decode to the declared text.

## Guarantees

1. Deterministic: identical inputs produce identical digests and identifiers.
2. Immutable: an accepted version is never rewritten; a new Antü creates a new version.
3. Validated writes only: no unvalidated semantic write is persisted.
4. Traceable: every claim reaches SOURCE_UNIT and MAPU by identifier, and a
   SOURCE_UNIT is resolved inside its own MAPU (a repeated `unit_id` across documents is
   refused, never guessed).
5. Fail closed: unreadable, corrupted or unsupported state raises or is reported, never guessed.
6. Independent: no operation of the core requires OpenViking, an LLM or a network.

## Compatibility

Contracts are versioned independently (see [VERSIONING.md](VERSIONING.md)): store format
`1.0.0`, sidecar schema `1.0.0`, outbox `1.0.0`, backup `1.0.0`. A store written by a
version of KÜYEN that declares the same format is readable; a different format is refused
with `StoreError` instead of being best-effort parsed.

## Direct Antü editing (0.3.0)

```python
from kuyen import (KuyenMemory, apply_graph_edit, incorporate_document, classify_antu,
                   EditorConfig, OpenAICompatibleGraphEditor, RecordedGraphEditor,
                   ANTU_KIND_DOCUMENT, ANTU_KIND_GRAPH_EDIT)
```

| Operation | Contract |
| --- | --- |
| `memory.apply_antu(instruction, *, editor, antu_id=None, actor=None, base_version_id=None, dry_run=False)` | Interprets, validates, applies and commits one edit Antü. Returns `AntuEditResult`. OpenViking is never used. |
| `memory.diff(before=None, after=None)` | Deterministic difference between two versions (default: parent → current). |
| `memory.current_objects(group="assertions", version_id=None)` | Objects that are neither retracted nor superseded. |
| `kuyen.apply_graph_edit(memory, instruction, *, editor, ...)` | The same operation through the product entry point, with the Antü kind asserted. |
| `kuyen.incorporate_document(memory, *, engine, antu, mapus, actor, adapter=None)` | Runs one document Antü end to end and commits the accepted version. Returns `DocumentIncorporation`. |
| `kuyen.classify_antu(antu)` | `DOCUMENT_INGESTION` or `GRAPH_EDIT`; raises on an unknown kind. |

`AntuEditResult` always exposes `status`, `base_version_id`, `version_id`, `operations`,
`rejected`, `affected`, `provenance`, `validation`, `clarification`, `conflict`, `model`,
`context`, `diff`, `reasons` and `committed`.

`EditorConfig.from_env()` reads `KUYEN_EDITOR_*`; the credential is an environment variable
name, never a value in the configuration. `RecordedGraphEditor` replays a recorded proposal
keyed by `prompt_sha256` and is what makes an edit reproducible without a model.

Contract details, states and limitations: [docs/GRAPH_EDIT_ANTU.md](docs/GRAPH_EDIT_ANTU.md)
(ES) and [docs/GRAPH_EDIT_ANTU.en.md](docs/GRAPH_EDIT_ANTU.en.md) (EN).
