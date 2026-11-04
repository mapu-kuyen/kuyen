"""Effective permissions of one Antü in one KÜYEN (KUYEN_DISTRIBUTED_ANTU_APPLICABILITY_12).

A portable Antü says *what* to change; the scope says *what this KÜYEN authorises*. The four
permissions are evaluated separately and none implies another:

* `SCHEMA_READ`  — may see the schema in force (entity types and their declared fields);
* `SCHEMA_WRITE` — may change that schema;
* `DATA_READ`    — may see entities, relations, assertions and evidence;
* `DATA_WRITE`   — may change them.

The scope is enforced twice, and neither enforcement is a prompt instruction: when the
context is built (`editing.context.build_context` sends nothing outside the scope) and again
when an operation is authorised (`editing.validator`), inside the writer lock, so a model
that ignores its prompt cannot reach data it was never given.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Iterable, Mapping

from ..editing.operations import (ADD_ASSERTION, ADD_ENTITY, ADD_FIELD, ADD_RELATION,
                                 RETRACT_ASSERTION, RETRACT_ENTITY, RETRACT_FIELD,
                                 RETRACT_RELATION, UPDATE_ASSERTION, UPDATE_ATTRIBUTE,
                                 UPDATE_ENTITY, UPDATE_FIELD, UPDATE_RELATION)

SCHEMA_READ = "SCHEMA_READ"
SCHEMA_WRITE = "SCHEMA_WRITE"
DATA_READ = "DATA_READ"
DATA_WRITE = "DATA_WRITE"
PERMISSIONS = (SCHEMA_READ, SCHEMA_WRITE, DATA_READ, DATA_WRITE)

#: Permissions an operation needs. Reading is required whenever the decision depends on the
#: current state (which is every operation except adding something wholly new).
OPERATION_PERMISSIONS: dict[str, tuple[str, ...]] = {
    ADD_ENTITY: (DATA_WRITE,),
    UPDATE_ENTITY: (DATA_READ, DATA_WRITE),
    RETRACT_ENTITY: (DATA_READ, DATA_WRITE),
    ADD_ASSERTION: (DATA_WRITE,),
    UPDATE_ASSERTION: (DATA_READ, DATA_WRITE),
    RETRACT_ASSERTION: (DATA_READ, DATA_WRITE),
    ADD_RELATION: (DATA_WRITE,),
    UPDATE_RELATION: (DATA_READ, DATA_WRITE),
    RETRACT_RELATION: (DATA_READ, DATA_WRITE),
    UPDATE_ATTRIBUTE: (DATA_READ, DATA_WRITE),
    ADD_FIELD: (SCHEMA_READ, SCHEMA_WRITE),
    UPDATE_FIELD: (SCHEMA_READ, SCHEMA_WRITE),
    RETRACT_FIELD: (SCHEMA_READ, SCHEMA_WRITE),
}

SCHEMA_PERMISSIONS = (SCHEMA_READ, SCHEMA_WRITE)
DATA_PERMISSIONS = (DATA_READ, DATA_WRITE)


class ScopeError(ValueError):
    """The scope declaration itself is unreadable."""

    code = "ANTU_SCOPE_INVALID"


def permissions_for(operation: str) -> tuple[str, ...]:
    """Permissions one operation needs; an unknown operation needs none (it is refused)."""
    return OPERATION_PERMISSIONS.get(str(operation or "").strip().upper(), ())


def _as_bool(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "si", "sí", "on"}
    return bool(value)
@dataclass(frozen=True)
class AntuScope:
    """The effective permissions of one Antü on one KÜYEN."""

    schema_read: bool = True
    schema_write: bool = True
    data_read: bool = True
    data_write: bool = True
    source: str = "default"

    @classmethod
    def from_dict(cls, value: "AntuScope | Mapping[str, Any] | Iterable[str] | None", *,
                  default: bool = True) -> "AntuScope":
        """Read a scope from booleans, a list of granted permissions or nothing.

        A list of granted permissions is closed: whatever is not named is not granted. A
        mapping of booleans is absolute. Nothing means the documented default.
        """
        if isinstance(value, AntuScope):
            return value
        if value is None:
            return cls(schema_read=default, schema_write=default,
                       data_read=default, data_write=default, source="default")
        if isinstance(value, str):
            value = [value]
        if isinstance(value, Mapping):
            # An explicit boolean wins: `public_dict()` reports both the booleans and the
            # derived lists, and reading it back must reproduce the same scope.
            explicit = any(key in value for key in ("schema_read", "schema_write",
                                                    "data_read", "data_write"))
            grants = None if explicit else (value.get("permissions") or value.get("granted"))
            if grants is not None:
                scope = cls.from_dict(list(grants), default=False)
                return replace(scope, source=str(value.get("source") or "declared"))
            unknown = sorted(set(value) - {item.lower() for item in PERMISSIONS}
                             - {"source", "granted", "denied", "permissions"})
            if unknown:
                raise ScopeError(f"unknown scope field: {unknown[0]}")
            return cls(
                schema_read=_as_bool(value.get("schema_read"), default=default),
                schema_write=_as_bool(value.get("schema_write"), default=default),
                data_read=_as_bool(value.get("data_read"), default=default),
                data_write=_as_bool(value.get("data_write"), default=default),
                source=str(value.get("source") or "declared"),
            )
        granted = {str(item).strip().upper() for item in value}
        unknown = sorted(granted - set(PERMISSIONS))
        if unknown:
            raise ScopeError(f"unknown permission: {unknown[0]}")
        return cls(schema_read=SCHEMA_READ in granted, schema_write=SCHEMA_WRITE in granted,
                   data_read=DATA_READ in granted, data_write=DATA_WRITE in granted,
                   source="declared")

    # ---------- queries ----------
    def granted(self) -> tuple[str, ...]:
        return tuple(name for name in PERMISSIONS if self.allows(name))

    def denials(self) -> tuple[str, ...]:
        return tuple(name for name in PERMISSIONS if not self.allows(name))

    def allows(self, permission: str) -> bool:
        name = str(permission or "").strip().upper()
        mapping = {SCHEMA_READ: self.schema_read, SCHEMA_WRITE: self.schema_write,
                   DATA_READ: self.data_read, DATA_WRITE: self.data_write}
        if name not in mapping:
            raise ScopeError(f"unknown permission: {permission}")
        return bool(mapping[name])

    def missing(self, permissions: Iterable[str]) -> list[str]:
        return [name for name in permissions if not self.allows(name)]

    def allows_operation(self, operation: str) -> bool:
        return not self.missing(permissions_for(operation))

    # ---------- views ----------
    def public_dict(self) -> dict[str, Any]:
        return {"schema_read": self.schema_read, "schema_write": self.schema_write,
                "data_read": self.data_read, "data_write": self.data_write,
                "granted": list(self.granted()), "denied": list(self.denials()),
                "source": self.source}

    def context_capabilities(self) -> dict[str, Any]:
        """What the model is told about its own limits: names only, never graph content."""
        return {"granted": list(self.granted()), "denied": list(self.denials()),
                "schema_visible": self.schema_read, "data_visible": self.data_read,
                "note": ("operations outside these permissions are refused by KÜYEN before "
                         "anything is written")}
