"""Append-only, hash-chained Antu event ledger.

Each event carries `seq`, `prev_event_hash` and `event_hash`; removing, reordering or
altering an event breaks the chain. The ledger is the history of instructions and
executions; it is never rewritten and a rejected Antu stays in it forever.

Concurrency (KUYEN_LEDGER_RECOVERY_HARDENING_02, M1)
---------------------------------------------------
`append_event` reads the tail, computes `seq`/`prev_event_hash` and appends while holding
the store's writer lock, so the sequence assignment and the chain link are one indivisible
operation for threads and for processes. A second writer always sees the event the first
one published.

Damage (KUYEN_LEDGER_RECOVERY_HARDENING_02, M2)
----------------------------------------------
Reading never guesses: `read_classified()` distinguishes an intact ledger, an incomplete
final record left by an interrupted write (`TRUNCATED_TAIL`) and real corruption
(`CORRUPT`). Only the truncated tail is repairable, and repairing it never discards
evidence: the original bytes are copied to `ledger/quarantine/` and a deterministic record
is written to `ledger/recovery/` before the file is shortened.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..storage.store import CanonicalStore
from ..canonical import (append_line, canonical_json, canonical_json_pretty, digest, read_last_line,
                         sha256_bytes, sha256_text, write_atomic)
from ..contracts import ANTU_EVENT_DOMAIN, LEDGER_FORMAT_VERSION
from ..errors import StoreError

GENESIS = "0" * 64
EVENT_TYPES = ("ANTU_RECEIVED", "ANTU_REJECTED", "ANTU_COMPLETED", "ANTU_NO_SEMANTIC_CHANGE",
               "ANTU_CLARIFICATION_REQUIRED", "ANTU_EDIT_PROPOSED",
               "VERSION_COMMITTED", "PROJECTION_ENQUEUED", "PROJECTION_COMPLETED",
               "PROJECTION_FAILED", "RECONCILIATION", "BACKUP_CREATED", "RESTORE_VERIFIED")

STATE_INTACT = "INTACT"
STATE_TRUNCATED = "TRUNCATED_TAIL"
STATE_CORRUPT = "CORRUPT"


def quarantine_dir(store: CanonicalStore) -> Path:
    return Path(store.root) / "ledger/quarantine"


def recovery_dir(store: CanonicalStore) -> Path:
    return Path(store.root) / "ledger/recovery"


def read_classified(store: CanonicalStore) -> dict[str, Any]:
    """Read the ledger and classify its damage without ever raising.

    Returns `events` (the valid prefix), `problems`, `state` and, when the last record was
    left unfinished, `tail` with its exact byte length and hash. A complete final line
    always ends with a newline (`append_line` guarantees it), so an unterminated last chunk
    is either an interrupted write or a record whose newline was lost.
    """
    path = Path(store.ledger_path)
    if not path.is_file():
        return {"events": [], "problems": [], "state": STATE_INTACT, "tail": None}
    raw = path.read_bytes()
    chunks = raw.split(b"\n")
    tail_bytes = b""
    if chunks and chunks[-1] != b"":
        tail_bytes = chunks[-1]
        chunks = chunks[:-1]
    events: list[dict[str, Any]] = []
    problems: list[str] = []
    for number, chunk in enumerate(chunks, start=1):
        if not chunk.strip():
            continue
        try:
            events.append(json.loads(chunk.decode("utf-8")))
        except (json.JSONDecodeError, UnicodeDecodeError):
            problems.append(f"ledger line {number} is not valid JSON")
    tail: dict[str, Any] | None = None
    if tail_bytes.strip():
        parsable = False
        try:
            json.loads(tail_bytes.decode("utf-8"))
            parsable = True
        except (json.JSONDecodeError, UnicodeDecodeError):
            parsable = False
        tail = {"line": len(chunks) + 1, "bytes": len(tail_bytes),
                "sha256": sha256_bytes(tail_bytes), "parsable": parsable,
                "preview": tail_bytes.decode("utf-8", "replace")[:120]}
    state = STATE_INTACT
    if problems:
        state = STATE_CORRUPT
    elif tail is not None:
        state = STATE_TRUNCATED
    return {"events": events, "problems": problems, "state": state, "tail": tail}


def read_tolerant(store: CanonicalStore) -> tuple[list[dict[str, Any]], list[str]]:
    """Compatibility wrapper: the valid prefix plus the problems found (never raises)."""
    report = read_classified(store)
    problems = list(report["problems"])
    if report["tail"] is not None:
        problems.append(f"ledger line {report['tail']['line']} is an incomplete record "
                        f"({report['tail']['bytes']} bytes, no final newline)")
    return report["events"], problems


def events(store: CanonicalStore) -> list[dict[str, Any]]:
    """The valid prefix of the chain.

    A final incomplete record does not block reads (it is reported by `verify()` and
    repaired by the next write or by `recover()`), but real corruption fails closed instead
    of returning a shorter chain as if nothing had happened.
    """
    report = read_classified(store)
    if report["state"] == STATE_CORRUPT:
        raise StoreError("ledger is corrupt: " + "; ".join(report["problems"][:3]))
    return report["events"]


def recovery_records(store: CanonicalStore) -> list[dict[str, Any]]:
    """Recovery records written by `repair_ledger`, oldest first (read-only, never raises)."""
    folder = recovery_dir(store)
    if not folder.is_dir():
        return []
    records = []
    for path in sorted(folder.glob("*.json")):
        try:
            records.append(json.loads(path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, UnicodeDecodeError):
            records.append({"recovery_id": path.stem, "state": "UNREADABLE",
                            "problem": f"recovery record {path.name} is not valid JSON"})
    return records


def repair_ledger(store: CanonicalStore, *, created_at: str | None = None) -> dict[str, Any]:
    """Repair a ledger whose *final* record was left incomplete; never touches anything else.

    The original bytes are preserved in `ledger/quarantine/`, a deterministic record is
    written in `ledger/recovery/` **before** the file is touched and completed afterwards,
    and only the unterminated tail is removed (or completed with its missing newline when
    the record itself parses). Corruption anywhere else fails closed: no automatic repair
    and no record discarded.
    """
    report = read_classified(store)
    if report["state"] == STATE_INTACT:
        return {"state": STATE_INTACT, "repaired": False, "recovery_id": None}
    if report["state"] == STATE_CORRUPT:
        raise StoreError("ledger is corrupt and cannot be repaired automatically: "
                         + "; ".join(report["problems"][:3]))
    with store.writer_lock():
        report = read_classified(store)          # another writer may have repaired it
        if report["state"] == STATE_INTACT:
            return {"state": STATE_INTACT, "repaired": False, "recovery_id": None}
        if report["state"] == STATE_CORRUPT:
            raise StoreError("ledger is corrupt and cannot be repaired automatically: "
                             + "; ".join(report["problems"][:3]))
        tail = report["tail"]
        path = Path(store.ledger_path)
        raw = path.read_bytes()
        complete = raw[: len(raw) - tail["bytes"]]
        tail_bytes = raw[len(raw) - tail["bytes"]:]
        if tail["parsable"]:
            action = "COMPLETED_FINAL_NEWLINE"
            repaired_bytes = complete + tail_bytes + b"\n"
            removed_bytes = 0
        else:
            action = "DROPPED_INCOMPLETE_RECORD"
            repaired_bytes = complete
            removed_bytes = tail["bytes"]
        original_sha256 = sha256_bytes(raw)
        recovery_id = "REC-" + digest({"original_sha256": original_sha256,
                                       "removed_sha256": tail["sha256"],
                                       "action": action, "line": tail["line"]})[:16]
        quarantine = quarantine_dir(store)
        quarantine.mkdir(parents=True, exist_ok=True)
        quarantined = quarantine / f"{original_sha256}.jsonl"
        if not quarantined.is_file():
            quarantined.write_bytes(raw)
        recovery_path = recovery_dir(store)
        recovery_path.mkdir(parents=True, exist_ok=True)
        target = recovery_path / f"{recovery_id}.json"
        record = {
            "schema_name": "KUYEN_LEDGER_RECOVERY",
            "schema_version": "1.0.0",
            "recovery_id": recovery_id,
            "created_at": created_at,
            "state": "PREPARED",
            "problem": STATE_TRUNCATED,
            "action": action,
            "ledger_path": "ledger/antu.jsonl",
            "original_sha256": original_sha256,
            "original_bytes": len(raw),
            "quarantine_file": f"ledger/quarantine/{original_sha256}.jsonl",
            "incomplete_line": tail["line"],
            "incomplete_bytes": tail["bytes"],
            "incomplete_sha256": tail["sha256"],
            "incomplete_parsable": tail["parsable"],
            "incomplete_preview": tail["preview"],
            "removed_bytes": removed_bytes,
            "events_before": len(report["events"]),
            "head_before": (report["events"][-1]["event_hash"] if report["events"] else GENESIS),
            "events_after": None,
            "head_after": None,
            "note": ("the incomplete record is preserved byte for byte in quarantine and is "
                     "never presented as a confirmed event"),
        }
        write_atomic(target, canonical_json_pretty(record))
        write_atomic(path, repaired_bytes)
        after = read_classified(store)
        record.update({"state": "COMPLETED", "events_after": len(after["events"]),
                       "head_after": (after["events"][-1]["event_hash"]
                                      if after["events"] else GENESIS)})
        write_atomic(target, canonical_json_pretty(record))
        return {"state": after["state"], "repaired": True, "recovery_id": recovery_id,
                "action": action, "removed_bytes": removed_bytes,
                "quarantine_file": record["quarantine_file"],
                "events": len(after["events"]), "recovery_record": str(target.relative_to(store.root))}


def last_event(store: CanonicalStore) -> dict[str, Any] | None:
    chain = events(store)
    return chain[-1] if chain else None


def read_tail(store: CanonicalStore) -> dict[str, Any]:
    """The head of the chain, read from the end of the ledger instead of from its start.

    A commit appends three events and every append used to re-parse the whole history
    twice, so the cost of recording history grew with the history itself
    (KUYEN_RELEASE_CANDIDATE_05, M6). The append only needs `seq` and `prev_event_hash`,
    which are in the last record: reading it costs the size of one record, whatever the
    age of the store.

    `usable` is False when the end of the file is not a well-formed, self-consistent
    record (an unterminated chunk, a line that is not JSON, a missing `seq` or
    `event_hash`). The caller then takes the full, repairing path, so an interrupted
    write is still repaired exactly as M2 requires and real corruption still fails closed.
    """
    path = Path(store.ledger_path)
    end = read_last_line(path)
    if end["trailing"]:
        return {"usable": False, "reason": "the final record is incomplete (no final newline)",
                "seq": 0, "head": GENESIS, "size": end["size"]}
    if end["line"] is None:
        if end["size"]:
            return {"usable": False, "reason": "the final record is empty",
                    "seq": 0, "head": GENESIS, "size": end["size"]}
        return {"usable": True, "reason": None, "seq": 0, "head": GENESIS, "size": 0}
    try:
        record = json.loads(end["line"])
    except json.JSONDecodeError:
        return {"usable": False, "reason": "the final record is not valid JSON",
                "seq": 0, "head": GENESIS, "size": end["size"]}
    if not isinstance(record, dict) or not isinstance(record.get("seq"), int) \
            or not isinstance(record.get("event_hash"), str):
        return {"usable": False, "reason": "the final record has no seq/event_hash",
                "seq": 0, "head": GENESIS, "size": end["size"]}
    return {"usable": True, "reason": None, "seq": record["seq"],
            "head": record["event_hash"], "size": end["size"]}


def append_event(store: CanonicalStore, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Append one event: read the tail, assign seq, link the hash and write, as one operation.

    The whole read-modify-append runs under the store's re-entrant writer lock, so the
    sequence number and `prev_event_hash` cannot be computed from a stale tail (M1).

    The tail is read from the end of the file (M6), so appending does not re-validate the
    whole chain; a chain whose *middle* is damaged is reported by `events()`/`verify_chain`
    (fail closed for readers) and is never silently rewritten. When the tail itself is not
    a usable record the full reading path runs first: it repairs a final incomplete record
    exactly as M2 specifies and refuses a damaged ledger.
    """
    if event_type not in EVENT_TYPES:
        raise ValueError(f"unknown event type: {event_type}")
    with store.writer_lock():
        tail = read_tail(store)
        if not tail["usable"]:
            repair_ledger(store)
            tail = read_tail(store)
            if not tail["usable"]:
                raise StoreError(f"ledger tail cannot be used: {tail['reason']}")
        body = {
            "schema_name": ANTU_EVENT_DOMAIN,
            "schema_version": LEDGER_FORMAT_VERSION,
            "seq": tail["seq"] + 1,
            "event_type": event_type,
            "prev_event_hash": tail["head"],
            **payload,
        }
        body["event_hash"] = sha256_text(canonical_json({key: value for key, value in body.items()
                                                         if key != "event_hash"}))
        append_line(store.ledger_path, canonical_json(body))
    return body


def verify_chain(store: CanonicalStore) -> dict[str, Any]:
    """Verify sequence, links and hashes; report the damage class and the repairs made."""
    report = read_classified(store)
    chain = report["events"]
    problems = list(report["problems"])
    if report["tail"] is not None:
        problems.append(f"ledger line {report['tail']['line']} is an incomplete record "
                        f"({report['tail']['bytes']} bytes, no final newline)")
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
    records = recovery_records(store)
    return {"ok": not problems, "problems": problems, "events": len(chain),
            "head": previous if chain else None, "state": report["state"],
            "tail": report["tail"],
            "recovery": {"repaired": bool(records),
                         "records": [{"recovery_id": item.get("recovery_id"),
                                      "state": item.get("state"),
                                      "action": item.get("action"),
                                      "events_before": item.get("events_before"),
                                      "events_after": item.get("events_after"),
                                      "quarantine_file": item.get("quarantine_file")}
                                     for item in records]}}


def events_for_antu(store: CanonicalStore, antu_id: str) -> list[dict[str, Any]]:
    return [event for event in events(store) if event.get("antu_id") == antu_id]


def events_of_type(store: CanonicalStore, event_type: str) -> list[dict[str, Any]]:
    return [event for event in events(store) if event.get("event_type") == event_type]


def ledger_digest(store: CanonicalStore) -> str:
    return digest(events(store))
