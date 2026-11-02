"""Persistent local publication records and their valid state machine."""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

from ..errors import (
    InvalidStateTransitionError, PublicationConflictError, PublicationNotFoundError,
)
from .models import PublicationRecord, PublicationStatus, TERMINAL_PUBLICATION_STATUSES


PUBLICATION_TRANSITIONS: dict[PublicationStatus, set[PublicationStatus]] = {
    PublicationStatus.NOT_PUBLISHED: {PublicationStatus.PUBLISHING, PublicationStatus.PUBLICATION_FAILED},
    PublicationStatus.PUBLISHING: {
        PublicationStatus.PUBLISHED, PublicationStatus.PUBLICATION_PARTIAL,
        PublicationStatus.PUBLICATION_FAILED,
    },
    PublicationStatus.PUBLISHED: {PublicationStatus.VERIFYING, PublicationStatus.PUBLICATION_FAILED},
    PublicationStatus.VERIFYING: {
        PublicationStatus.VERIFIED, PublicationStatus.VERIFICATION_FAILED,
    },
    PublicationStatus.VERIFIED: {PublicationStatus.VERIFICATION_FAILED},
    # Recovery is explicit: a new attempt may inspect the real target and
    # resume safe writes, but it may never erase or overwrite a previous one.
    PublicationStatus.PUBLICATION_PARTIAL: {PublicationStatus.PUBLISHING},
    PublicationStatus.PUBLICATION_FAILED: {PublicationStatus.PUBLISHING},
    PublicationStatus.VERIFICATION_FAILED: {PublicationStatus.VERIFYING},
}


class PublicationRegistry:
    def __init__(self, data_dir: str | Path):
        self.root = Path(data_dir) / "publications"
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def _path(self, publication_id: str) -> Path:
        if not publication_id.startswith("PUB-") or "/" in publication_id:
            raise PublicationNotFoundError(publication_id)
        return self.root / f"{publication_id}.json"

    def create(self, record: PublicationRecord) -> None:
        with self._lock:
            path = self._path(record.publication_id)
            if path.exists():
                raise PublicationConflictError(f"publication already exists: {record.publication_id}")
            record.transitions.append({"state": record.status.value, "at": record.created_at})
            self._write(path, record)

    def get(self, publication_id: str) -> PublicationRecord:
        path = self._path(publication_id)
        if not path.is_file():
            raise PublicationNotFoundError(publication_id)
        return PublicationRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def transition(self, publication_id: str, status: PublicationStatus, **changes: Any) -> PublicationRecord:
        with self._lock:
            record = self.get(publication_id)
            if status != record.status and status not in PUBLICATION_TRANSITIONS[record.status]:
                raise InvalidStateTransitionError(f"{record.status.value} -> {status.value}")
            record.status = status
            from .models import utc_now
            record.updated_at = utc_now()
            for key, value in changes.items():
                if hasattr(record, key):
                    setattr(record, key, value)
            record.transitions.append({"state": status.value, "at": record.updated_at})
            self._write(self._path(publication_id), record)
            return record

    def list(self) -> list[PublicationRecord]:
        with self._lock:
            values = []
            for path in sorted(self.root.glob("PUB-*.json")):
                values.append(PublicationRecord.from_dict(json.loads(path.read_text(encoding="utf-8"))))
            return values

    @staticmethod
    def _write(path: Path, record: PublicationRecord) -> None:
        temp = path.with_suffix(".json.tmp")
        temp.write_text(json.dumps(record.to_dict(), indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temp, path)
