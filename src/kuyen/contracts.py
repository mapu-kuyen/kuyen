"""Versioned contracts of the KUYEN product.

Seven identity/version domains are kept strictly separate; no domain reuses another
domain's number. These constants are public API: producers and adapters can rely on
them.
"""
from __future__ import annotations

from dataclasses import dataclass

STORE_FORMAT_VERSION = "1.0.0"
LEDGER_FORMAT_VERSION = "1.0.0"
OUTBOX_FORMAT_VERSION = "1.0.0"
PROJECTION_FORMAT_VERSION = "1.0.0"
PROJECTION_REGISTRY_FORMAT_VERSION = "1.0.0"
CORRESPONDENCE_FORMAT_VERSION = "1.0.0"
BACKUP_FORMAT_VERSION = "1.0.0"
VERSION_FORMAT_VERSION = "1.0.0"
SIDECAR_SCHEMA_NAME = "KUYEN_CANONICAL_SIDECAR"
SIDECAR_SCHEMA_VERSION = "1.0.0"
EXPORTER_VERSION = "1.0.0"
PROJECTOR_VERSION = "1.0.0"
RECONSTRUCTOR_VERSION = "1.0.0"
STORE_ADAPTER_VERSION = "1.0.0"
BACKUP_ADAPTER_VERSION = "1.0.0"
ANTU_PROCESSOR_VERSION = "1.0.0"
SUPPORTED_SIDECAR_SCHEMAS = ("1.0.0",)
SUPPORTED_SIDECAR_SCHEMA_VERSIONS = SUPPORTED_SIDECAR_SCHEMAS
SUPPORTED_GRAPH_SCHEMAS = ("kuyen-native-v1",)
NATIVE_RELATION_KEYS = ("from", "relation", "label", "to", "evidence")
NATIVE_ENTITY_KEYS = ("type", "id", "title", "entity_type", "description", "aliases", "sources")
EVENT_TYPES = ("ANTU_RECEIVED", "ANTU_REJECTED", "ANTU_COMPLETED", "ANTU_NO_SEMANTIC_CHANGE",
               "VERSION_COMMITTED", "PROJECTION_ENQUEUED", "PROJECTION_COMPLETED",
               "PROJECTION_FAILED", "RECONCILIATION", "BACKUP_CREATED", "RESTORE_VERIFIED")


@dataclass(frozen=True)
class VersionDomains:
    """The independent version domains an artifact can carry."""

    leftraru_id: str
    unit_revision: str
    kuyen_id: str
    kuyen_version: str
    mapu_revisions: tuple = ()
    sidecar_schema_version: str = SIDECAR_SCHEMA_VERSION
    openviking_version: str | None = None
    store_format_version: str = STORE_FORMAT_VERSION

    def to_dict(self) -> dict:
        return {"leftraru_id": self.leftraru_id, "unit_revision": self.unit_revision,
                "kuyen_id": self.kuyen_id, "kuyen_version": self.kuyen_version,
                "mapu_revisions": list(self.mapu_revisions),
                "sidecar_schema_version": self.sidecar_schema_version,
                "openviking_version": self.openviking_version,
                "store_format_version": self.store_format_version}


# Aliases used by the promoted modules (single source of truth above).
SCHEMA_NAME = SIDECAR_SCHEMA_NAME
SCHEMA_VERSION = SIDECAR_SCHEMA_VERSION
PROJECTION_SCHEMA_NAME = "KUYEN_NATIVE_PROJECTION"
PROJECTION_SCHEMA_VERSION = PROJECTION_FORMAT_VERSION
MAPPING_SCHEMA_NAME = "KUYEN_NATIVE_CORRESPONDENCE_MANIFEST"
MAPPING_SCHEMA_VERSION = CORRESPONDENCE_FORMAT_VERSION
SUPPORTED_KUYEN_SCHEMA_VERSIONS = SUPPORTED_GRAPH_SCHEMAS
VERSION_DOMAIN = "KUYEN_CANONICAL_MEMORY_VERSION"
ANTU_EVENT_DOMAIN = "KUYEN_ANTU_EVENT"
PROJECTION_DOMAIN = "KUYEN_NATIVE_PROJECTION"
BACKUP_DOMAIN = "KUYEN_CANONICAL_BACKUP"


def schema_path(name: str):
    """Absolute path of a contract schema shipped as package data."""
    from pathlib import Path as _Path

    return _Path(__file__).resolve().parent / "schemas" / name


CONTRACT_CONSTANTS = (
    "STORE_FORMAT_VERSION", "LEDGER_FORMAT_VERSION", "OUTBOX_FORMAT_VERSION",
    "PROJECTION_FORMAT_VERSION", "CORRESPONDENCE_FORMAT_VERSION", "BACKUP_FORMAT_VERSION",
    "VERSION_FORMAT_VERSION", "SIDECAR_SCHEMA_NAME", "SIDECAR_SCHEMA_VERSION",
    "EXPORTER_VERSION", "PROJECTOR_VERSION", "RECONSTRUCTOR_VERSION",
    "STORE_ADAPTER_VERSION", "BACKUP_ADAPTER_VERSION", "ANTU_PROCESSOR_VERSION",
)


def contract_snapshot_document() -> dict:
    """The contract as a canonical, hashable document."""
    import sys as _sys

    module = _sys.modules[__name__]
    return {name: getattr(module, name) for name in CONTRACT_CONSTANTS}


def contract_snapshot(path) -> str:
    """Write the contract snapshot to `path`; return its sha256."""
    import json as _json
    import hashlib as _hashlib
    from pathlib import Path as _Path

    payload = _json.dumps(contract_snapshot_document(), sort_keys=True, indent=2) + "\n"
    target = _Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(payload, encoding="utf-8")
    return _hashlib.sha256(payload.encode("utf-8")).hexdigest()
