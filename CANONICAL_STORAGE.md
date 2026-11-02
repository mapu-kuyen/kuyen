# CANONICAL STORAGE

```
<memory>/
├── FORMAT.json              store format, hash algorithm, durability, writer model
├── objects/sha256/xx/<sha256>   content-addressed blobs (read-only, 0444)
├── versions/<version_id>/manifest.json   the single commit point
├── index/versions.jsonl     append-only version index
├── refs/CURRENT             pointer to the current version
├── refs/history/            pointer history
├── ledger/antu.jsonl        hash-chained Antü ledger
├── outbox/<operation>.json  projection requests
├── projections/<id>.json    projection registry
├── staging/                 disposable work area for an in-flight commit
└── locks/writer.lock        advisory single-writer lock
```

## Content addressing

The name of a blob **is** its SHA-256. Writing an existing hash is a no-op, so identical
content is stored once across versions and re-committing identical knowledge costs no
space. Blobs are written `0444`: the store is append-only by construction.

## Commit protocol

```
1. write objects (idempotent; content addressed)
2. build + verify the sidecar and the correspondence mapping
3. write the manifest into staging/
4. fsync and atomically publish versions/<id>/manifest.json      <-- the commit point
5. append to index/versions.jsonl
6. compare-and-set refs/CURRENT
7. append VERSION_COMMITTED to the ledger
8. enqueue the projection request in the outbox
```

Steps 5–8 are idempotent and replayable: after an interruption between 4 and 8,
`memory.recover()` completes the work. A version that never reached step 4 does not exist
and its staging is discarded.

## Durability

Writes go through a temporary file, `fsync`, atomic `rename` and a directory `fsync`.
This is *crash consistency for the process*, not a claim of power-loss protection: that
was not tested (see PLATFORM_COMPATIBILITY.md).

## Concurrency

The store is single-writer by design. A writer takes an advisory `flock` on
`locks/writer.lock`; readers take no lock and always see the last published manifest.
Multiple concurrent writers are not supported and not claimed.

## Verification

`memory.verify()` re-checks: every blob hash, every manifest and its blobs, every index
entry, every parent link, the CURRENT hash, the ledger chain and the unit history. It
returns problems instead of raising so an operator can inspect them.
