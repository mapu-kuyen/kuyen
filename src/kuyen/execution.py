"""Persistent operational state for asynchronous KÜYEN submissions."""
from __future__ import annotations

import json
import os
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from .errors import ExecutionNotFoundError, InvalidStateTransitionError


class ExecutionState(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    CANDIDATE_READY = "CANDIDATE_READY"
    VALIDATING = "VALIDATING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"


TERMINAL = {ExecutionState.ACCEPTED, ExecutionState.REJECTED, ExecutionState.FAILED}
TRANSITIONS: dict[ExecutionState, set[ExecutionState]] = {
    ExecutionState.PENDING: {ExecutionState.RUNNING, ExecutionState.FAILED},
    ExecutionState.RUNNING: {
        ExecutionState.CANDIDATE_READY, ExecutionState.VALIDATING,
        ExecutionState.ACCEPTED, ExecutionState.REJECTED, ExecutionState.FAILED,
    },
    ExecutionState.CANDIDATE_READY: {ExecutionState.VALIDATING, ExecutionState.FAILED},
    ExecutionState.VALIDATING: {ExecutionState.ACCEPTED, ExecutionState.REJECTED, ExecutionState.FAILED},
    ExecutionState.ACCEPTED: set(),
    ExecutionState.REJECTED: set(),
    ExecutionState.FAILED: set(),
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ExecutionHandle:
    execution_id: str
    request_key: str
    state: ExecutionState
    updated_at: str
    error: dict[str, Any] | None = None

    @property
    def status(self) -> str:
        return self.state.value

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL

    def to_dict(self) -> dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "request_key": self.request_key,
            "status": self.state.value,
            "updated_at": self.updated_at,
            "error": self.error,
        }


@dataclass
class ExecutionRecord:
    execution_id: str
    request_key: str
    antu_id: str
    mapu_ids: list[str]
    actor: dict[str, Any]
    state: ExecutionState = ExecutionState.PENDING
    created_at: str = field(default_factory=now)
    updated_at: str = field(default_factory=now)
    task_id: str | None = None
    compile_status: str | None = None
    validation_status: str | None = None
    error: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    manifest_path: str | None = None
    graph_uri: str | None = None
    version: str | None = None
    transitions: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "execution_id": self.execution_id, "request_key": self.request_key,
            "antu_id": self.antu_id, "mapu_ids": self.mapu_ids, "actor": self.actor,
            "state": self.state.value, "created_at": self.created_at,
            "updated_at": self.updated_at, "task_id": self.task_id,
            "compile_status": self.compile_status, "validation_status": self.validation_status,
            "error": self.error, "result": self.result,
            "manifest_path": self.manifest_path, "graph_uri": self.graph_uri,
            "version": self.version, "transitions": self.transitions,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ExecutionRecord":
        return cls(
            execution_id=value["execution_id"], request_key=value["request_key"],
            antu_id=value["antu_id"], mapu_ids=list(value.get("mapu_ids") or []),
            actor=dict(value.get("actor") or {}),
            state=ExecutionState(value.get("state", "PENDING")),
            created_at=value.get("created_at") or now(), updated_at=value.get("updated_at") or now(),
            task_id=value.get("task_id"), compile_status=value.get("compile_status"),
            validation_status=value.get("validation_status"), error=value.get("error"),
            result=value.get("result"), manifest_path=value.get("manifest_path"),
            graph_uri=value.get("graph_uri"), version=value.get("version"),
            transitions=list(value.get("transitions") or []),
        )


class ExecutionRegistry:
    """One JSON file per execution, atomically replaced; no secrets are stored."""

    def __init__(self, data_dir: str | Path):
        self.root = Path(data_dir) / "executions"
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def _path(self, execution_id: str) -> Path:
        if not execution_id.startswith("exec_") or "/" in execution_id:
            raise ExecutionNotFoundError(execution_id)
        return self.root / f"{execution_id}.json"

    def create(self, record: ExecutionRecord) -> None:
        with self._lock:
            path = self._path(record.execution_id)
            if path.exists():
                raise InvalidStateTransitionError(f"execution already exists: {record.execution_id}")
            record.transitions.append({"state": record.state.value, "at": record.created_at})
            self._write(path, record)

    def get(self, execution_id: str) -> ExecutionRecord:
        path = self._path(execution_id)
        if not path.is_file():
            raise ExecutionNotFoundError(execution_id)
        return ExecutionRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def transition(self, execution_id: str, state: ExecutionState, **changes: Any) -> ExecutionRecord:
        with self._lock:
            record = self.get(execution_id)
            if record.state in TERMINAL and state != record.state:
                raise InvalidStateTransitionError(f"terminal {record.state.value} -> {state.value}")
            if state != record.state and state not in TRANSITIONS[record.state]:
                raise InvalidStateTransitionError(f"{record.state.value} -> {state.value}")
            record.state = state
            record.updated_at = now()
            for key, value in changes.items():
                if hasattr(record, key):
                    setattr(record, key, value)
            record.transitions.append({"state": state.value, "at": record.updated_at})
            self._write(self._path(execution_id), record)
            return record

    def list(self, request_key: str | None = None) -> list[ExecutionRecord]:
        with self._lock:
            records = []
            for path in sorted(self.root.glob("exec_*.json")):
                record = ExecutionRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))
                if request_key is None or record.request_key == request_key:
                    records.append(record)
            return records

    @staticmethod
    def _write(path: Path, record: ExecutionRecord) -> None:
        temp = path.with_suffix(".json.tmp")
        temp.write_text(json.dumps(record.to_dict(), indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temp, path)


def new_execution_id() -> str:
    return f"exec_{uuid.uuid4().hex}"
