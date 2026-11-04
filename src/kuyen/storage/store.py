"""Canonical Memory Store: the independent, content-addressed, fsync'd repository.

Layout
------
    FORMAT.json                     store format + hash algorithm (never changes in place)
    objects/sha256/<ab>/<hash>      immutable content-addressed blobs (mode 0444)
    versions/<version_id>/manifest.json   one immutable version record
    index/versions.jsonl            append-only index of accepted versions
    refs/CURRENT                    the single current pointer (atomic replace)
    refs/history/<version_id>.json  pointer history
    ledger/antu.jsonl               hash-chained Antu events
    outbox/<key>.json               durable projection operations
    projections/<id>.json           projection registry entries
    staging/<commit_id>/            pre-commit area (never authoritative)
    locks/writer.lock               advisory writer lock (flock)

The store uses only the local filesystem, never OpenViking, never a network call and
never the process memory of a previous run.
"""
from __future__ import annotations

import errno
import fcntl
import os
import re
import shutil
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from ..canonical import canonical_json_pretty, digest, fsync_dir, read_json, sha256_bytes, sha256_file, write_atomic
from ..errors import StoreError
from ..contracts import STORE_ADAPTER_VERSION, STORE_FORMAT_VERSION

HASH_ALGORITHM = "sha256"

# Re-entrancy bookkeeping for the writer lock (KUYEN_LEDGER_RECOVERY_HARDENING_02, M1).
# `flock` is per open file description, so a second descriptor opened by the same process
# blocks against the first: nesting the lock must reuse the held descriptor instead of
# opening another one.
_WRITER_SCOPES = threading.local()


@dataclass(frozen=True)
class StoreConfig:
    root: Path
    format_version: str = STORE_FORMAT_VERSION
    adapter_version: str = STORE_ADAPTER_VERSION


BLOB_NAME_RE = re.compile(r"[0-9a-f]{64}")


class CanonicalStore:
    def __init__(self, root: str | Path, *, create: bool = False, lock_timeout: float = 10.0) -> None:
        self.root = Path(root)
        self.lock_timeout = lock_timeout
        self._lock_handle = None
        if create:
            self._initialize()
        if not (self.root / "FORMAT.json").is_file():
            raise StoreError(f"not a canonical store (missing FORMAT.json): {self.root}")
        self.format = read_json(self.root / "FORMAT.json")
        if self.format.get("hash_algorithm") != HASH_ALGORITHM:
            raise StoreError(f"unsupported hash algorithm: {self.format.get('hash_algorithm')}")
        if self.format.get("store_format_version") != STORE_FORMAT_VERSION:
            raise StoreError(f"unsupported store format: {self.format.get('store_format_version')}")

    # -- layout -------------------------------------------------------------
    def _initialize(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        for relative in ("objects/sha256", "versions", "index", "refs/history", "ledger", "outbox",
                         "projections", "staging", "locks"):
            (self.root / relative).mkdir(parents=True, exist_ok=True)
        format_path = self.root / "FORMAT.json"
        if not format_path.is_file():
            write_atomic(format_path, canonical_json_pretty({
                "store_format_version": STORE_FORMAT_VERSION,
                "hash_algorithm": HASH_ALGORITHM,
                "addressing": "content-addressed blobs by sha256 of the stored bytes",
                "durability": "write+fsync+atomic rename+directory fsync",
                "writer_model": "single writer per store (advisory flock); readers do not lock",
                "created_at": None,
            }))

    @property
    def objects_dir(self) -> Path:
        return self.root / "objects/sha256"

    @property
    def versions_dir(self) -> Path:
        return self.root / "versions"

    @property
    def index_path(self) -> Path:
        return self.root / "index/versions.jsonl"

    @property
    def current_path(self) -> Path:
        return self.root / "refs/CURRENT"

    @property
    def ledger_path(self) -> Path:
        return self.root / "ledger/antu.jsonl"

    @property
    def outbox_dir(self) -> Path:
        return self.root / "outbox"

    @property
    def projections_dir(self) -> Path:
        return self.root / "projections"

    @property
    def staging_dir(self) -> Path:
        return self.root / "staging"

    def blob_path(self, content_hash: str) -> Path:
        if len(content_hash) != 64 or any(ch not in "0123456789abcdef" for ch in content_hash):
            raise StoreError(f"invalid content hash: {content_hash!r}")
        return self.objects_dir / content_hash[:2] / content_hash

    # -- blobs --------------------------------------------------------------
    def put_blob(self, payload: bytes | str) -> str:
        data = payload.encode("utf-8") if isinstance(payload, str) else payload
        content_hash = sha256_bytes(data)
        path = self.blob_path(content_hash)
        if path.is_file():
            if sha256_file(path) != content_hash:
                raise StoreError(f"corrupt blob already present at {path}")
            return content_hash
        write_atomic(path, data, mode=0o444)
        os.chmod(path, 0o444)
        return content_hash

    def get_blob(self, content_hash: str) -> bytes:
        path = self.blob_path(content_hash)
        if not path.is_file():
            raise StoreError(f"missing blob {content_hash}")
        data = path.read_bytes()
        if sha256_bytes(data) != content_hash:
            raise StoreError(f"blob {content_hash} does not match its content")
        return data

    def has_blob(self, content_hash: str) -> bool:
        return self.blob_path(content_hash).is_file()

    # -- writer lock --------------------------------------------------------
    @contextmanager
    def writer_lock(self, *, timeout: float | None = None) -> Iterator[None]:
        """Advisory writer lock, exclusive across threads and processes, re-entrant per thread.

        A second *thread* or *process* is blocked (each opens its own descriptor, and
        `flock` conflicts between descriptors). The same thread may nest the lock: the
        write API wraps a whole operation and the ledger/history primitives it calls take
        the lock again, so nesting must not open a second descriptor that would block
        against itself.
        """
        scopes = getattr(_WRITER_SCOPES, "depth", None)
        if scopes is None:
            scopes = {}
            _WRITER_SCOPES.depth = scopes
        key = str(self.root.resolve())
        if scopes.get(key):
            scopes[key] += 1
            try:
                yield
            finally:
                scopes[key] -= 1
            return

        path = self.root / "locks/writer.lock"
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = path.open("a+")
        deadline = time.time() + (timeout if timeout is not None else self.lock_timeout)
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as exc:
                if exc.errno not in (errno.EACCES, errno.EAGAIN):
                    handle.close()
                    raise
                if time.time() >= deadline:
                    handle.close()
                    raise StoreError("writer lock is held by another process (single-writer store)") from None
                time.sleep(0.02)
        scopes[key] = 1
        try:
            handle.seek(0)
            handle.truncate()
            handle.write(f"pid={os.getpid()} at={time.time()}\n")
            handle.flush()
            yield
        finally:
            scopes.pop(key, None)
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            finally:
                handle.close()

    def writer_lock_held(self) -> bool:
        path = self.root / "locks/writer.lock"
        if not path.is_file():
            return False
        with path.open("a+") as handle:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                return True
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            return False

    # -- current pointer ----------------------------------------------------
    def read_current(self) -> dict[str, Any] | None:
        if not self.current_path.is_file():
            return None
        return read_json(self.current_path)

    def write_current(self, pointer: dict[str, Any], *, expected_previous_version_id: str | None,
                      failpoint=None) -> dict[str, Any]:
        """Compare-and-swap on the CURRENT pointer; the only way it may change."""
        current = self.read_current()
        observed = (current or {}).get("version_id")
        if observed != expected_previous_version_id:
            raise StoreError(f"current pointer moved: expected {expected_previous_version_id!r}, found {observed!r}")
        payload = {**pointer, "updated_at": pointer.get("updated_at")}
        if failpoint:
            failpoint("during_current_update")
        write_atomic(self.current_path, canonical_json_pretty(payload))
        previous_id = (current or {}).get("version_id", "GENESIS")
        if previous_id != "GENESIS":
            from .versions import validate_version_id  # local: avoids an import cycle
            validate_version_id(previous_id)
        write_atomic(self.root / "refs/history" / f"{previous_id}.json",
                     canonical_json_pretty({"replaced_by": payload.get("version_id"),
                                            "replaced_at": payload.get("updated_at"),
                                            "previous": current}))
        return payload

    # -- verification -------------------------------------------------------
    def verify_objects(self, *, deep: bool = True) -> dict[str, Any]:
        """Every file under `objects/` must be a blob named by its own SHA-256.

        An abandoned `write_atomic` temporary is inert: no reader ever opens it and its name
        is not a content address, so it is counted and ignored instead of being reported as
        corruption (a crash is not damage). Any other unexpected file is reported, because
        nothing but a blob belongs there (KUYEN_SEMANTIC_SECURITY_HARDENING_04, review of the
        previous experiment).
        """
        problems, checked, ignored = [], 0, 0
        for path in sorted(self.objects_dir.rglob("*")):
            if not path.is_file():
                continue
            if path.name.startswith(".tmp-"):
                ignored += 1
                continue
            checked += 1
            expected = path.name
            if not BLOB_NAME_RE.fullmatch(expected):
                problems.append({"blob": str(path.relative_to(self.root)), "problem": "UNEXPECTED_FILE"})
                continue
            if deep and sha256_file(path) != expected:
                problems.append({"blob": str(path.relative_to(self.root)), "problem": "HASH_MISMATCH"})
        return {"checked": checked, "ignored_temporaries": ignored, "problems": problems,
                "ok": not problems}

    def info(self) -> dict[str, Any]:
        stat = os.stat(self.root)
        total = sum(p.stat().st_size for p in self.root.rglob("*") if p.is_file())
        return {
            "root": str(self.root),
            "store_format_version": self.format.get("store_format_version"),
            "hash_algorithm": self.format.get("hash_algorithm"),
            "device_id": stat.st_dev,
            "filesystem": _filesystem_type(self.root),
            "blob_count": sum(1 for p in self.objects_dir.rglob("*") if p.is_file()),
            "version_count": sum(1 for p in self.versions_dir.iterdir() if p.is_dir()),
            "total_bytes": total,
            "writer_lock_held": self.writer_lock_held(),
        }

    def copy_to(self, target: str | Path, *, include_ledger: bool = True) -> Path:
        target = Path(target)
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(self.root, target)
        if not include_ledger:
            (target / "ledger/antu.jsonl").unlink(missing_ok=True)
        return target


def _filesystem_type(path: Path) -> str:
    try:
        completed = os.statvfs(path)
        return f"statvfs-block={completed.f_frsize}"
    except OSError:
        return "unknown"


def same_device(left: str | Path, right: str | Path) -> bool:
    return os.stat(left).st_dev == os.stat(right).st_dev


def digest_of_object(value: Any) -> str:
    return digest(value)
