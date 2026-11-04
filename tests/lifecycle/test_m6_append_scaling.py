"""M6 — recording history must not cost the history itself.

Audited defect (KUYEN_RELEASE_CANDIDATE_05, M6): every `append_event` re-parsed the whole
ledger twice (`repair_ledger` + `events`), so the cost of one event grew with the number of
events already recorded: 1.1 ms at 100 events, 9.8 ms at 2 000 (measured), i.e. quadratic
in the size of the history. The same happened with the index: every commit read every line
to prove that the version was not indexed yet.

Contract after the correction:
  * an append reads the *tail* of the ledger, not the ledger;
  * the sequence number and the chain link still come from the last published record;
  * an interrupted final record is still repaired exactly as M2 requires;
  * a damaged *middle* is still refused by every reader (`events`, `verify`) and is never
    rewritten — the write path does not re-validate the whole chain, and that is stated;
  * the index lookup finds the newest entry without reading the whole file.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from kuyen import KuyenMemory
from kuyen.canonical import canonical_json
from kuyen.errors import StoreError
from kuyen.lifecycle import ledger as ledger_module


def seed(store, count: int) -> list[dict]:
    for index in range(count):
        ledger_module.append_event(store, "ANTU_RECEIVED",
                                   {"antu_id": f"ANTU-M6-{index:06d}",
                                    "recorded_at": "2026-01-01T00:00:00+00:00"})
    return ledger_module.events(store)


def last_record(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8").strip().splitlines()[-1])


class ReadCounter:
    """Counts the bytes read from one file, transparently, through `Path.open`."""

    def __init__(self, target: Path) -> None:
        self.target = Path(target).resolve()
        self.bytes = 0
        self.opens = 0
        self._real = Path.open

    def __enter__(self) -> "ReadCounter":
        counter = self

        class Counting:
            def __init__(self, handle):
                self._handle = handle

            def read(self, *args):
                data = self._handle.read(*args)
                counter.bytes += len(data)
                return data

            def readlines(self, *args):
                lines = self._handle.readlines(*args)
                counter.bytes += sum(len(line) for line in lines)
                return lines

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return self._handle.__exit__(*exc)

            def __getattr__(self, name):
                return getattr(self._handle, name)

            def __iter__(self):
                for line in self._handle:
                    counter.bytes += len(line)
                    yield line

        def counting_open(path_self, *args, **kwargs):
            handle = counter._real(path_self, *args, **kwargs)
            try:
                same = Path(path_self).resolve() == counter.target
            except OSError:
                same = False
            if same:
                counter.opens += 1
                return Counting(handle)
            return handle

        Path.open = counting_open  # type: ignore[method-assign]
        return self

    def __exit__(self, *exc) -> None:
        Path.open = self._real  # type: ignore[method-assign]


class TestAppendDoesNotReadTheHistory:
    def test_append_never_parses_the_whole_ledger(self, memory: KuyenMemory, monkeypatch) -> None:
        seed(memory.store, 40)
        path = Path(memory.path) / "ledger/antu.jsonl"

        def forbidden(*args, **kwargs):  # pragma: no cover - it must never run
            raise AssertionError("append_event must not read the whole ledger")

        monkeypatch.setattr(ledger_module, "read_classified", forbidden)
        event = ledger_module.append_event(memory.store, "ANTU_RECEIVED",
                                           {"antu_id": "ANTU-M6-NEW", "recorded_at": "now"})
        assert event["seq"] == 41
        assert last_record(path)["event_hash"] == event["event_hash"]

    def test_append_reads_bytes_that_do_not_grow_with_the_ledger(self, memory: KuyenMemory) -> None:
        seed(memory.store, 1500)
        path = Path(memory.path) / "ledger/antu.jsonl"
        size = path.stat().st_size
        assert size > 400_000

        with ReadCounter(path) as counter:
            ledger_module.append_event(memory.store, "ANTU_RECEIVED",
                                       {"antu_tail": True, "recorded_at": "now"})
        # the fix reads one record; before it, the append read the file twice
        assert counter.bytes < 64 * 1024
        assert counter.bytes < size / 8

    def test_the_chain_still_links_and_verifies(self, memory: KuyenMemory) -> None:
        ledger = seed(memory.store, 5)
        event = ledger_module.append_event(memory.store, "ANTU_RECEIVED",
                                           {"antu_id": "ANTU-M6-LINK", "recorded_at": "now"})
        assert event["prev_event_hash"] == ledger[-1]["event_hash"]
        assert event["seq"] == len(ledger) + 1
        report = ledger_module.verify_chain(memory.store)
        assert report["ok"] is True
        assert report["events"] == len(ledger) + 1
        assert report["head"] == event["event_hash"]


class TestTailRepairStillApplies:
    """The cheap path must never skip the M2 repair it replaced."""

    def test_an_interrupted_final_record_is_repaired_before_appending(self, memory: KuyenMemory) -> None:
        seed(memory.store, 5)
        path = Path(memory.path) / "ledger/antu.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            handle.write('{"schema_name": "KUYEN_ANTU_EVENT", "seq": 6')

        event = ledger_module.append_event(memory.store, "ANTU_RECEIVED",
                                           {"antu_id": "ANTU-M6-AFTER-CRASH", "recorded_at": "now"})
        assert event["seq"] == 6
        recovery = ledger_module.recovery_records(memory.store)
        assert recovery and recovery[-1]["state"] == "COMPLETED"
        assert recovery[-1]["action"] == "DROPPED_INCOMPLETE_RECORD"
        assert ledger_module.verify_chain(memory.store)["ok"] is True

    def test_an_unterminated_record_that_parses_only_loses_its_missing_newline(
            self, memory: KuyenMemory) -> None:
        seed(memory.store, 3)
        path = Path(memory.path) / "ledger/antu.jsonl"
        path.write_bytes(path.read_bytes().rstrip(b"\n"))

        event = ledger_module.append_event(memory.store, "ANTU_RECEIVED",
                                           {"antu_id": "ANTU-M6-NO-NEWLINE", "recorded_at": "now"})
        assert event["seq"] == 4
        assert ledger_module.recovery_records(memory.store)[-1]["action"] == "COMPLETED_FINAL_NEWLINE"
        assert ledger_module.verify_chain(memory.store)["ok"] is True


class TestMiddleCorruptionStillFailsClosedForReaders:
    def test_readers_refuse_a_damaged_chain_and_the_history_is_not_rewritten(
            self, memory: KuyenMemory) -> None:
        seed(memory.store, 4)
        path = Path(memory.path) / "ledger/antu.jsonl"
        lines = path.read_text(encoding="utf-8").splitlines()
        lines[1] = "{not-json"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        damaged = path.read_bytes()

        assert memory.ledger_state()["state"] == "CORRUPT"
        with pytest.raises(StoreError):
            memory.ledger()

        # the write path links to the last published record and never rewrites the history
        ledger_module.append_event(memory.store, "ANTU_RECEIVED",
                                   {"antu_id": "ANTU-M6-CORRUPT", "recorded_at": "now"})
        assert path.read_bytes().startswith(damaged)
        assert memory.ledger_state()["state"] == "CORRUPT"
        with pytest.raises(StoreError):
            memory.ledger()
        assert memory.verify()["ok"] is False


class TestIndexLookupDoesNotScanEveryVersion:
    def test_reindexing_the_newest_version_reads_one_chunk(self, memory: KuyenMemory,
                                                           monkeypatch) -> None:
        from kuyen.storage import registry

        path = memory.store.index_path
        entry = {"version_id": "VER-" + "0" * 12, "kuyen_id": "KUY-x", "kuyen_version": "1.0.0",
                 "canonical_graph_hash": "0" * 64, "parent_version_id": None,
                 "antu_id": "ANTU-INDEX", "unit_revision": "REV-0001",
                 "created_at": "2026-01-01T00:00:00+00:00", "mapu_revisions": []}
        lines = []
        for number in range(600):
            entry["version_id"] = "VER-" + f"{number:012x}"
            lines.append(canonical_json(entry))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        assert path.stat().st_size > 60_000

        seen: list[str] = []
        original = registry.read_json_string

        def counting(line: str):
            seen.append(line)
            return original(line)

        monkeypatch.setattr(registry, "read_json_string", counting)
        registry.index_version(memory.store, {"version_id": "VER-" + f"{599:012x}",
                                             "kuyen_id": "KUY-x", "kuyen_version": "1.0.0",
                                             "canonical_graph_hash": "0" * 64,
                                             "parent_version_id": None, "antu_id": "ANTU-INDEX",
                                             "unit_revision": "REV-0001",
                                             "created_at": "2026-01-01T00:00:00+00:00",
                                             "mapu_revisions": []})
        assert len(seen) == 1, f"the lookup scanned {len(seen)} lines"
        assert path.read_text(encoding="utf-8").count("VER-") == 600

    def test_an_absent_version_is_still_appended_exactly_once(self, memory: KuyenMemory) -> None:
        from kuyen.storage import registry

        manifest = {"version_id": "VER-" + "a" * 12, "kuyen_id": "KUY-x",
                    "kuyen_version": "1.0.0", "canonical_graph_hash": "0" * 64,
                    "parent_version_id": None, "antu_id": "ANTU-INDEX",
                    "unit_revision": "REV-0001",
                    "created_at": "2026-01-01T00:00:00+00:00", "mapu_revisions": []}
        registry.index_version(memory.store, manifest)
        registry.index_version(memory.store, manifest)
        registry.index_version(memory.store, manifest)
        entries = registry.index_entries(memory.store)
        assert [entry["version_id"] for entry in entries] == [manifest["version_id"]]
