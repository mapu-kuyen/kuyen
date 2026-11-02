"""Append-only, hash-chained Antu event ledger.

Each event carries `seq`, `prev_event_hash` and `event_hash`; removing, reordering or
altering an event breaks the chain. The ledger is the history of instructions and
executions; it is never rewritten and a rejected Antu stays in it forever.
"""
from __future__ import annotations

from typing import Any

from ..storage.store import CanonicalStore
from ..canonical import append_line, canonical_json, digest, sha256_text
from ..contracts import ANTU_EVENT_DOMAIN, LEDGER_FORMAT_VERSION

GENESIS = "0" * 64
EVENT_TYPES = ("ANTU_RECEIVED", "ANTU_REJECTED", "ANTU_COMPLETED", "ANTU_NO_SEMANTIC_CHANGE",
               "VERSION_COMMITTED", "PROJECTION_ENQUEUED", "PROJECTION_COMPLETED",
               "PROJECTION_FAILED", "RECONCILIATION", "BACKUP_CREATED", "RESTORE_VERIFIED")


def events(store: CanonicalStore) -> list[dict[str, Any]]:
    if not store.ledger_path.is_file():
        return []
    import json
    return [json.loads(line) for line in store.ledger_path.read_text(encoding="utf-8").splitlines() if line.strip()]


def last_event(store: CanonicalStore) -> dict[str, Any] | None:
    chain = events(store)
    return chain[-1] if chain else None


def append_event(store: CanonicalStore, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    if event_type not in EVENT_TYPES:
        raise ValueError(f"unknown event type: {event_type}")
    chain = events(store)
    previous = chain[-1]["event_hash"] if chain else GENESIS
    body = {
        "schema_name": ANTU_EVENT_DOMAIN,
        "schema_version": LEDGER_FORMAT_VERSION,
        "seq": len(chain) + 1,
        "event_type": event_type,
        "prev_event_hash": previous,
        **payload,
    }
    body["event_hash"] = sha256_text(canonical_json({key: value for key, value in body.items()
                                                     if key != "event_hash"}))
    append_line(store.ledger_path, canonical_json(body))
    return body


def read_tolerant(store: CanonicalStore) -> tuple[list[dict[str, Any]], list[str]]:
    """Read the ledger without ever raising: a damaged line is reported, not hidden."""
    import json

    if not store.ledger_path.is_file():
        return [], []
    chain: list[dict[str, Any]] = []
    problems: list[str] = []
    for number, line in enumerate(store.ledger_path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            chain.append(json.loads(line))
        except json.JSONDecodeError:
            problems.append(f"ledger line {number} is not valid JSON")
    return chain, problems


def verify_chain(store: CanonicalStore) -> dict[str, Any]:
    chain, problems = read_tolerant(store)
    previous = GENESIS
    for index, event in enumerate(chain, start=1):
        if event.get("seq") != index:
            problems.append(f"event {index}: unexpected seq {event.get('seq')}")
        if event.get("prev_event_hash") != previous:
            problems.append(f"event {index}: prev_event_hash does not link to the previous event")
        recomputed = sha256_text(canonical_json({key: value for key, value in event.items()
                                                 if key != "event_hash"}))
        if recomputed != event.get("event_hash"):
            problems.append(f"event {index}: event_hash mismatch")
        previous = event.get("event_hash")
    return {"ok": not problems, "problems": problems, "events": len(chain),
            "head": previous if chain else None}


def events_for_antu(store: CanonicalStore, antu_id: str) -> list[dict[str, Any]]:
    return [event for event in events(store) if event.get("antu_id") == antu_id]


def events_of_type(store: CanonicalStore, event_type: str) -> list[dict[str, Any]]:
    return [event for event in events(store) if event.get("event_type") == event_type]


def ledger_digest(store: CanonicalStore) -> str:
    return digest(events(store))
