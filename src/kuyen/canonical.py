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


def write_atomic(path: str | _Path, data: bytes | str, *, mode: int = 0o644) -> str:
    """Write through a temporary file, fsync it, rename it and fsync the directory."""
    target = _Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = data.encode("utf-8") if isinstance(data, str) else data
    temporary = target.parent / f".tmp-{target.name}-{_os.getpid()}"
    with temporary.open("wb") as handle:
        handle.write(payload)
        handle.flush()
        _os.fsync(handle.fileno())
    _os.chmod(temporary, mode)
    _os.replace(temporary, target)
    fsync_dir(target.parent)
    return sha256_bytes(payload)


def append_line(path: str | _Path, line: str) -> None:
    """Append one durable line (the primitive behind the append-only ledgers)."""
    target = _Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(line.rstrip("\n") + "\n")
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
