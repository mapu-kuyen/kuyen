# PLATFORM COMPATIBILITY

## Guaranteed

| Aspect | Requirement |
| --- | --- |
| Python | 3.10, 3.11, 3.12, 3.13 |
| Operating system | POSIX (Linux, macOS) |
| File system | atomic `rename` within one directory, `os.replace` |
| Locking | advisory `fcntl.flock` (single writer) |
| Permissions | `chmod` on files and directories; blobs are made read-only |
| Encoding | UTF-8, NFC-normalized canonical strings |
| Filesystem features | no sparse files, no extended attributes, no hard-link requirement |

The canonical store depends on POSIX semantics for atomic rename and advisory locking.
Those guarantees are **not** weakened for portability.

## Tested

macOS (Darwin, APFS) with CPython 3.13: full product suite, wheel install, sdist install,
backup/restore, store-only recovery.

## Untested (do not claim)

* Windows: no `fcntl`, different rename semantics — the store is expected to work but is
  **not** validated. Not supported in this release.
* Network file systems (NFS/SMB): advisory locking and rename semantics differ.
* Power-loss durability: `fsync` is used, but no power-loss test was executed.
* Multi-writer concurrency: single-writer by design.
* Python 3.9 and earlier: unsupported (uses `X | Y` type syntax and `tomllib`).

## Resource behaviour

Memory footprint is proportional to the document being validated, not to the store size;
reads stream blobs and manifests. No daemon, no background thread, no external service.
