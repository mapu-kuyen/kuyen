# ARCHITECTURE

KÜYEN is a library with a small public surface and explicit internal boundaries.

```
src/kuyen/
├── __init__.py          public surface: KuyenMemory, build_document, __version__
├── _version.py           single version resolver (VERSION file, then metadata)
├── api/memory.py         KuyenMemory: the high-level contract
├── contracts.py          versioned contract constants and asset locations
├── errors.py             one error hierarchy for the whole product
├── canonical.py          canonical JSON, digests, atomic writes, fsync helpers
├── ingest.py             accepted graph + MAPU texts -> canonical document
├── models/               canonical dataclasses (Entity, Relation, Assertion, …)
├── validation/           deterministic validators (no LLM, no network)
├── materialization/      candidate -> canonical graph materialization
├── normalization/        conservative identity normalization
├── semantics/            predicate preservation and polarity/temporality rules
├── coverage/             coverage inventory and closure
├── serialization/        native file serialization
├── sidecar/              canonical sidecar, exporter, reconstruction
├── storage/              store, immutable versions, registry, commit protocol
├── lifecycle/            unit revisions, hash-chained ledger, Antü execution
├── projection/           native projector, correspondence map, outbox, reconciliation
├── backup/               verified backup and restore
├── recovery/             independent store-only recovery
├── publication/          governed external publication planning
├── ports/                publication port interfaces
├── adapters/             optional OpenViking SDK adapter
├── query/                read helpers over a graph
├── extraction/, importing/, coverage/   optional candidate production
└── schemas/, config/, skills/            runtime assets (package data)
```

## Boundaries that matter

**The core is independent.** `storage`, `lifecycle`, `sidecar`, `projection` (native),
`backup` and `recovery` import nothing from OpenViking, no model SDK and no HTTP client.
They use the standard library plus the canonical primitives.

**Validation precedes persistence.** `execute_antu` runs the deterministic validators and
returns an execution; only `commit` writes a version. There is no code path that persists
a proposal that was not validated.

**One commit point.** A version exists the moment its `manifest.json` is atomically
published. Everything before that is staging and can be replayed; everything after is
idempotent side work (index, CURRENT, ledger, outbox, projection).

**The projection is disposable.** A native projection, an external projection and the
outbox are regenerable views. Losing them costs nothing that the store cannot rebuild.

**Assets are package data.** Schemas, ontology profiles and the versioned Skill ship
inside the wheel; nothing resolves through `Path.cwd()` in a way that breaks an installed
package.

## Request path of an Antü

```
Antü (instruction + proposal)
   -> lifecycle.antu.execute / api.execute_antu     validators, no writes to versions
   -> storage.commit.commit_version                 objects -> sidecar -> manifest -> CURRENT
   -> lifecycle.unit.record_revision                one unit revision
   -> lifecycle.ledger.append_event                 hash-chained event
   -> projection.outbox.enqueue                     projectionrequest (regenerable)
```

## Failure model

Every stage fails closed. A corrupted object, sidecar, manifest, ledger line, pointer or
backup is reported as a problem and never silently accepted. `verify()` and
`recover_from_store()` return data instead of raising, so an operator can see exactly what
is wrong.
