# BACKUP AND RECOVERY

## Backup

```python
memory.backup("./backup-kuyen")   # -> backup_id, versions, root_hash, integrity_status
```

A backup copies the canonical store (objects, versions, index, refs, ledger, unit history)
and writes `BACKUP_MANIFEST.json` with the hash of every file, a `root_hash` over that
manifest, the current version and the format versions. `integrity_status` is `SEALED`.

## Verify

```python
KuyenMemory.verify_backup("./backup-kuyen")   # raises BackupError if anything is off
```

Missing files, undeclared files, wrong hashes and a wrong root hash are all refused. A
backup that does not verify is never restored.

## Restore

```python
restored = KuyenMemory.restore("./backup-kuyen", "./memory-restored")
```

The destination is validated before anything is created or copied
(`KUYEN_RELEASE_CANDIDATE_05`, B2):

| destination | result |
|---|---|
| does not exist | created (missing parents included) |
| exists and is empty | **used**: the backup is copied into it |
| exists and is not empty | **refused**, contents left byte-for-byte intact |
| is a file | **refused** |
| is a symbolic link | **refused** (nothing is written through an indirection) |
| is the backup itself, lives inside it, or contains it | **refused** |
| already holds a restore | **refused** (it is not empty) |

Restore re-verifies the backup first, copies it, then re-checks the registry, ledger, unit
history and every version, and returns a memory whose `verify()` is `ok`. Restored versions
keep their exact identifiers and hashes. If the copy fails, only what this operation created
is removed: an existing empty destination is left empty again and the backup is never
modified.

Restore never overwrites another store: a destination that already contains a store is not
empty, so it is refused. Replacing a store is an operator decision, never a side effect of
recovery.

## Interrupted commits

```python
report = memory.recover()   # also available as memory.pending() as a read-only report
```

A commit publishes its manifest and only then indexes it, records it in the ledger, queues
its projection and moves `CURRENT`. `recover()` finishes those last stages and never
invents a version. A leftover staging directory is classified **from the store**
(`KUYEN_RELEASE_CANDIDATE_05`, B1):

| state | meaning | what recovery does |
|---|---|---|
| `NOT_PUBLISHED` | `INTENT.json` names a version whose manifest does not exist | the commit died before the commit point: the staging is removed |
| `PUBLISHED_COMPLETE` | the manifest exists and every later stage already happened | the staging is removed; `actions_completed` is empty |
| `PUBLISHED_PARTIAL` | the manifest exists and some later stage is missing | the missing stages run, then the staging is removed |
| `UNCLASSIFIED` | no readable `INTENT.json`, or a manifest that contradicts it | **kept** and reported in `staging_kept`: recovery never destroys what it cannot attribute |

If a version is published and no `CURRENT` exists, `recover()` adopts it
(`current_adopted`) and records a `RECONCILIATION` event; with more than one candidate it
reports the fork (`current_ambiguous`) instead of guessing. Everything is conditional on the
absence of its own evidence, so a second `recover()` changes nothing.

## Store-only recovery

```python
report = KuyenMemory.recover_from_store(memory.path, workdir="./recovery")
```

Recovery needs the canonical store and this package. Nothing else: no OpenViking, no
projection, no fixture, no network. For every version it materializes the persisted
artifacts, reconstructs the canonical graph from the sidecar and compares the rebuilt hash
with the committed manifest. Each result reports `accepted`, `status` and `hashes_match`.

## What is claimed and what is not

* **Claimed:** logical recovery of every accepted version from the store alone; restore of
a verified backup into a new path; detection of corrupted backups and objects.
* **Not claimed:** protection against power loss (no `fsync`-on-power-failure test was run),
and physical/volume independence — a backup on the same disk is a logical copy, not a
separate failure domain. Keep backups on another volume.
