"""Security posture: nothing invalid is accepted, nothing untrusted is executed."""
from __future__ import annotations

import json

import pytest

from kuyen import KuyenMemory
from kuyen.errors import StoreError
from kuyen.storage.store import CanonicalStore


class TestPathSafety:
    def test_version_ids_cannot_escape_the_store(self, live_memory: KuyenMemory) -> None:
        for candidate in ("../../etc/passwd", "VER-..%2f..", "/absolute"):
            with pytest.raises(StoreError):
                live_memory.graph(candidate)

    def test_a_blob_identifier_cannot_escape_the_store(self, live_memory: KuyenMemory) -> None:
        with pytest.raises(StoreError):
            live_memory.store.get_blob("../../../etc/passwd")

    def test_an_unsupported_store_format_is_refused(self, live_memory: KuyenMemory) -> None:
        format_path = live_memory.path / "FORMAT.json"
        payload = json.loads(format_path.read_text(encoding="utf-8"))
        payload["store_format_version"] = "9.9.9"
        format_path.chmod(0o644)
        format_path.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises((StoreError, ValueError)):
            CanonicalStore(live_memory.path)


class TestFailClosed:
    def test_unvalidated_state_is_never_persisted(self, live_memory: KuyenMemory, antu_file) -> None:
        import pytest as _pytest

        from kuyen.errors import CommitError

        antu, path = antu_file
        broken = dict(antu, antu_id="ANTU-BROKEN-1")
        broken["proposal"] = dict(antu["proposal"])
        broken["proposal"]["relations"] = [dict(antu["proposal"]["relations"][0],
                                                from_entity="ent_ffffffffffffffffffff")]
        execution = live_memory.execute_antu(broken, mapu_source=path)
        assert execution.status == "REJECTED"
        with _pytest.raises(CommitError):
            live_memory.commit(execution)
        assert len(live_memory.versions()) == 1

    def test_a_truncated_ledger_line_is_reported(self, live_memory: KuyenMemory) -> None:
        ledger = live_memory.path / "ledger" / "antu.jsonl"
        ledger.chmod(0o644)
        with ledger.open("a", encoding="utf-8") as handle:
            handle.write('{"seq": 1, "event_type": "ANTU_RECEIVED"')
        report = live_memory.verify()
        assert report["ok"] is False

    def test_a_missing_current_pointer_is_a_defect_once_committed(self, live_memory: KuyenMemory) -> None:
        current = live_memory.path / "refs" / "CURRENT"
        current.chmod(0o644)
        current.unlink()
        assert live_memory.verify()["ok"] is False
