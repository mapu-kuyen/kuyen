"""Deterministic identifiers and serialization primitives."""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from typing import Any


def canonical_json(value: Any) -> str:
    """Stable UTF-8 JSON: sorted keys, no insignificant whitespace, no ASCII coercion."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def canonical_digest(value: Any) -> str:
    return sha256_text(canonical_json(value))


def normalized_name(value: str) -> str:
    """Conservative display-key normalization; source quotes are never normalized."""
    text = unicodedata.normalize("NFKC", value).strip().casefold()
    text = re.sub(r"\s+", " ", text)
    return text


def stable_id(prefix: str, payload: Any) -> str:
    """Collision-resistant deterministic ID; the full payload is in the hash."""
    digest = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    return f"{prefix}_{digest[:20]}"


def request_key(
    *,
    antu: dict[str, Any],
    mapus: list[dict[str, Any]],
    implementation_version: str,
    ontology_version: str,
    skill_sha256: str,
    openviking_version: str,
    actor: dict[str, Any] | None = None,
) -> str:
    payload = {
        "antu": antu,
        "actor": actor or {},
        "mapus": sorted(
            (
                {
                    "mapu_id": item["mapu_id"],
                    "version": item["version"],
                    "source_uri": item["source_uri"],
                    "sha256": item["sha256"],
                }
                for item in mapus
            ),
            key=lambda item: (item["mapu_id"], item["version"]),
        ),
        "implementation_version": implementation_version,
        "ontology_version": ontology_version,
        "skill_sha256": skill_sha256,
        "openviking_version": openviking_version,
    }
    return "req_" + sha256_text(canonical_json(payload))[:32]


# --- storage/lifecycle primitives (additive; existing functions unchanged) ---

import itertools as _itertools
import os as _os
from pathlib import Path as _Path


class CanonicalIOError(ValueError):
    """A canonical artifact could not be read or written deterministically."""


def nfc(value: str) -> str:
    """NFC normalization used for every canonical string."""
    return unicodedata.normalize("NFC", value)


def canonical_json_pretty(value: Any) -> str:
    """Canonical JSON with sorted keys, two-space indent and a trailing newline."""
    return json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: str | _Path) -> str:
    digest = hashlib.sha256()
    with _Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def digest(value: Any) -> str:
    """Content digest of a JSON-serializable value (alias of canonical_digest)."""
    return canonical_digest(value)


def fsync_dir(path: str | _Path) -> None:
    """Persist a directory entry where the platform allows it."""
    try:
        descriptor = _os.open(str(path), _os.O_RDONLY)
    except OSError:
        return
    try:
        _os.fsync(descriptor)
    except OSError:
        pass
    finally:
        _os.close(descriptor)


_TEMP_SEQUENCE = _itertools.count()


def temporary_name(target: _Path) -> Path:
    """A temporary path that no other writer of this process can reuse.

    The PID alone identified the temporary of every thread of a process, so two writers of
    the same destination fought over one file: one replaced it while the other was still
    writing, which lost data and raised `FileNotFoundError` on the loser
    (KUYEN_TRANSACTION_BOUNDARY_HARDENING_03, front 2).
    """
    return target.parent / (f".tmp-{target.name}-{_os.getpid()}-"
                            f"{next(_TEMP_SEQUENCE):x}-{_os.urandom(4).hex()}")


def write_atomic(path: str | _Path, data: bytes | str, *, mode: int = 0o644) -> str:
    """Write through a unique temporary file, fsync it, rename it and fsync the directory.

    The destination holds the previous content or the new one, never a mixture: the
    replacement is a single `os.replace` of a fully written and fsynced temporary. A failed
    write removes its own temporary so a leftover can never be mistaken for a result.
    """
    target = _Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = data.encode("utf-8") if isinstance(data, str) else data
    temporary = temporary_name(target)
    try:
        with temporary.open("wb") as handle:
            handle.write(payload)
            handle.flush()
            _os.fsync(handle.fileno())
        _os.chmod(temporary, mode)
        _os.replace(temporary, target)
    except BaseException:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise
    fsync_dir(target.parent)
    return sha256_bytes(payload)


def append_line(path: str | _Path, line: str) -> None:
    """Append one durable line (the primitive behind the append-only ledgers)."""
    target = _Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(line.rstrip("\n") + "\n")


REVERSE_CHUNK = 8192


def read_last_line(path: str | _Path, *, chunk: int = REVERSE_CHUNK) -> dict[str, Any]:
    """Inspect the *end* of an append-only JSONL file without reading all of it.

    Returns `line` (the last newline-terminated record, or None), `trailing` (bytes after
    the last newline: an interrupted write, in a file that is always written with a final
    newline) and `size`. The window grows until two newlines are inside it, so a record
    larger than one chunk is still returned whole; for a file of any size the cost is the
    cost of its last record, not the cost of the file.

    This is what lets an append avoid re-parsing the entire history
    (KUYEN_RELEASE_CANDIDATE_05, M6).
    """
    target = _Path(path)
    if not target.is_file():
        return {"line": None, "trailing": b"", "size": 0}
    with target.open("rb") as handle:
        handle.seek(0, _os.SEEK_END)
        size = handle.tell()
        if size == 0:
            return {"line": None, "trailing": b"", "size": 0}
        window = max(chunk, 1)
        while True:
            start = max(0, size - window)
            handle.seek(start)
            data = handle.read(size - start)
            if data.endswith(b"\n"):
                trailing = b""
                body = data[:-1]
            else:
                cut = data.rfind(b"\n")
                trailing = data[cut + 1:] if cut >= 0 else data
                body = data[:cut] if cut >= 0 else b""
            boundary = body.rfind(b"\n")
            if boundary >= 0:
                return {"line": body[boundary + 1:].decode("utf-8", "replace"),
                        "trailing": trailing, "size": size}
            if start == 0:
                # the whole file is one record: it is the last line, terminated or not
                return {"line": body.decode("utf-8", "replace") if body else None,
                        "trailing": trailing, "size": size}
            window *= 2


def iter_lines_reverse(path: str | _Path, *, chunk: int = REVERSE_CHUNK):
    """Yield the lines of an append-only file from the last one backwards, lazily.

    A lookup of the most recently written entry therefore reads one chunk instead of the
    whole file, while an entry that is not there still ends at the beginning of the file
    (KUYEN_RELEASE_CANDIDATE_05, M6).
    """
    target = _Path(path)
    if not target.is_file():
        return
    with target.open("rb") as handle:
        handle.seek(0, _os.SEEK_END)
        position = handle.tell()
        pending = b""
        while position > 0:
            step = min(chunk, position)
            position -= step
            handle.seek(position)
            pending = handle.read(step) + pending
            parts = pending.split(b"\n")
            pending = parts[0]
            for part in reversed(parts[1:]):
                if part.strip():
                    yield part.decode("utf-8", "replace")
        if pending.strip():
            yield pending.decode("utf-8", "replace")
        handle.flush()
        _os.fsync(handle.fileno())
    fsync_dir(target.parent)


def read_json(path: str | _Path) -> Any:
    """Read JSON or raise a typed error (never a silent empty value)."""
    try:
        return json.loads(_Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CanonicalIOError(f"{path}: malformed JSON: {exc}") from exc


def write_canonical(path: str | _Path, value: Any, *, mode: int = 0o644) -> str:
    """Write a pretty canonical JSON document atomically; return its sha256."""
    return write_atomic(path, canonical_json_pretty(value), mode=mode)


def referenced_digest(document: dict[str, Any], *, field: str = "sidecar_content_hash",
                      parent: str = "integrity") -> str:
    """Digest of a document excluding its own stamped hash (no circular reference)."""
    clone = json.loads(json.dumps(document, ensure_ascii=False))
    container = clone.get(parent) or {}
    container.pop(field, None)
    clone[parent] = container
    return canonical_digest(clone)
