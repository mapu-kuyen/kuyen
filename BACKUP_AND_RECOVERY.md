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

The target must be empty. Restore re-verifies the backup, copies it, then re-checks the
registry, ledger, unit history and every version, and returns a memory whose `verify()`
is `ok`. Restored versions keep their exact identifiers and hashes.

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
