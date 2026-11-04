"""M3 — what KÜYEN really detects, and what it must stop claiming.

KUYEN_SEMANTIC_SECURITY_HARDENING_04. `SECURITY.md` promised that "manifests, sidecar,
ledger chain, index, CURRENT and backups are hash-checked". The manifests were not: nothing
bound a manifest to its own content, so editing `counts` or emptying `object_hashes` left
`verify()` reporting `ok`. These tests hold the implementation and the documentation to the
same standard and record the limits that no root of trust can remove.

Detected = the store refuses or reports the change. Undetected = the change is consistent
with every hash KÜYEN has, which is only possible for someone who can rewrite the store;
`SECURITY.md` states that limit explicitly.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

import fixtures_produc as fixtures
from kuyen import KuyenMemory, build_document
from kuyen.canonical import canonical_json, temporary_name
from kuyen.storage.commit import verify_commit
from kuyen.storage.versions import read_version, verify_version
from kuyen.errors import StoreError


def seed(memory: KuyenMemory) -> str:
    """The live fixture already committed one version; return it."""
    pointer = memory.current()
    if pointer is not None:
        return pointer.version_id
    document = build_document(fixtures.make_graph(), {fixtures.MAPU_ID: fixtures.make_mapu_text()},
                              mapu_versions={fixtures.MAPU_ID: "1.0.0"},
                              source_uris={fixtures.MAPU_ID: fixtures.SOURCE_URI})
    memory.import_canonical(document)
    return memory.current().version_id


def store_path(memory: KuyenMemory) -> Path:
    return Path(memory.path)


def manifest_file(memory: KuyenMemory, version_id: str) -> Path:
    return store_path(memory) / "versions" / version_id / "manifest.json"


def rewrite(path: Path, **changes) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.update(changes)
    os.chmod(path, 0o644)
    path.write_text(canonical_json(payload), encoding="utf-8")


def blob_file(memory: KuyenMemory, content_hash: str) -> Path:
    return memory.store.blob_path(content_hash)


class TestDetected:
    def test_an_intact_store_is_accepted(self, live_memory: KuyenMemory) -> None:
        version_id = seed(live_memory)
        report = live_memory.verify()
        assert report["ok"] is True, report["problems"]
        assert verify_version(live_memory.store, version_id)["ok"] is True
        assert verify_commit(live_memory.store, version_id)["ok"] is True

    def test_a_corrupted_blob_is_detected(self, live_memory: KuyenMemory) -> None:
        version_id = seed(live_memory)
        manifest = read_version(live_memory.store, version_id).manifest
        blob = blob_file(live_memory, manifest["sidecar_blob"])
        os.chmod(blob, 0o644)
        blob.write_bytes(blob.read_bytes().replace(b'"kuyen_id"', b'"kuyen_Xd"'))

        report = live_memory.verify()
        assert report["ok"] is False
        assert any(manifest["sidecar_blob"] in problem or "mismatch" in problem.lower()
                   for problem in report["problems"]), report["problems"]

    def test_a_deleted_blob_is_detected(self, live_memory: KuyenMemory) -> None:
        version_id = seed(live_memory)
        manifest = read_version(live_memory.store, version_id).manifest
        blob_file(live_memory, manifest["integrity_blob"]).unlink()

        report = live_memory.verify()
        assert report["ok"] is False
        assert any(manifest["integrity_blob"] in problem or "integrity_blob" in problem
                   for problem in report["problems"]), report["problems"]

    @pytest.mark.parametrize("change", [
        {"counts": {"entities": 99}},
        {"object_hashes": {}},
        {"canonical_graph_hash": "0" * 64},
        {"sidecar_content_hash": "0" * 64},
        {"parent_version_id": "VER-ffffffffffff"},
        {"antu_id": "ANTU-FORGED"},
        {"kuyen_version": "9.9.9"},
    ])
    def test_a_manifest_edited_without_its_blobs_is_detected(self, live_memory: KuyenMemory,
                                                             change: dict) -> None:
        version_id = seed(live_memory)
        rewrite(manifest_file(live_memory, version_id), **change)

        report = live_memory.verify()
        assert report["ok"] is False, f"undetected manifest tampering: {change}"
        assert verify_version(live_memory.store, version_id)["ok"] is False

    def test_a_manifest_copied_into_another_version_directory_is_detected(
            self, live_memory: KuyenMemory) -> None:
        version_id = seed(live_memory)
        source = manifest_file(live_memory, version_id)
        forged = store_path(live_memory) / "versions" / "VER-0123456789ab" / "manifest.json"
        forged.parent.mkdir(parents=True)
        forged.write_bytes(source.read_bytes())

        verification = verify_version(live_memory.store, "VER-0123456789ab")
        assert verification["ok"] is False
        assert any("version_id" in problem for problem in verification["problems"])

    def test_an_edited_ledger_event_is_detected(self, live_memory: KuyenMemory) -> None:
        seed(live_memory)
        ledger = store_path(live_memory) / "ledger" / "antu.jsonl"
        lines = ledger.read_text(encoding="utf-8").splitlines()
        record = json.loads(lines[0])
        record["antu_id"] = "ANTU-REWRITTEN"
        lines[0] = canonical_json(record)
        os.chmod(ledger, 0o644)
        ledger.write_text("\n".join(lines) + "\n", encoding="utf-8")

        report = live_memory.verify()
        assert report["ok"] is False
        assert any("event_hash" in problem for problem in report["problems"])

    def test_an_unknown_version_is_reported_not_guessed(self, live_memory: KuyenMemory) -> None:
        seed(live_memory)
        with pytest.raises(StoreError):
            verify_version(live_memory.store, "VER-000000000000")


class TestDocumentedLimits:
    """What KÜYEN cannot detect, and must therefore stop claiming.

    There is no signature, no MAC and no external anchor, so a writer who can rewrite every
    artifact consistently produces a store that verifies. These tests pin the limit so that
    `SECURITY.md` cannot drift away from the implementation: if either case ever becomes
    detected, the documentation must change with it.
    """

    def test_a_rewritten_ledger_chain_is_not_detected(self, live_memory: KuyenMemory) -> None:
        seed(live_memory)
        ledger = store_path(live_memory) / "ledger" / "antu.jsonl"
        records = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()
                   if line.strip()]
        previous = "0" * 64
        for record in records:
            record["recorded_at"] = "2020-01-01T00:00:00Z"
            record["prev_event_hash"] = previous
            body = {key: value for key, value in record.items() if key != "event_hash"}
            record["event_hash"] = hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()
            previous = record["event_hash"]
        os.chmod(ledger, 0o644)
        ledger.write_text("".join(canonical_json(record) + "\n" for record in records),
                          encoding="utf-8")

        report = live_memory.verify()

        assert report["ok"] is True, report["problems"]

    def test_a_current_rollback_to_a_previous_version_is_not_detected(
            self, live_memory: KuyenMemory) -> None:
        first = seed(live_memory)
        antu = fixtures.make_antu(antu_id="ANTU-ROLLBACK",
                                  base_version_id=live_memory.current().version_id)
        source = Path(live_memory.path).parent / "MAPU-ROLLBACK.txt"
        source.write_text(antu["unit"]["content"], encoding="utf-8")
        live_memory.commit(live_memory.execute_antu(antu, mapu_source=source))
        assert live_memory.current().version_id != first

        current = store_path(live_memory) / "refs" / "CURRENT"
        payload = json.loads(current.read_text(encoding="utf-8"))
        first_graph_hash = read_version(live_memory.store, first).manifest["canonical_graph_hash"]
        payload["version_id"] = first
        payload["canonical_graph_hash"] = first_graph_hash
        os.chmod(current, 0o644)
        current.write_text(canonical_json(payload), encoding="utf-8")

        assert live_memory.verify()["ok"] is True


class TestCrashLeftovers:
    """Review of the previous experiment: a crash is not damage."""

    def test_an_abandoned_temporary_is_inert_not_corruption(self,
                                                            live_memory: KuyenMemory) -> None:
        version_id = seed(live_memory)
        store = live_memory.store
        manifest = read_version(store, version_id).manifest
        targets = [store.versions_dir / version_id / "manifest.json", store.current_path,
                   store.index_path, store.ledger_path, store.blob_path(manifest["sidecar_blob"])]
        for target in targets:
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary_name(target).write_bytes(b'{"partial": true')

        report = live_memory.verify()

        assert report["ok"] is True, report["problems"]
        assert store.verify_objects()["ignored_temporaries"] >= 1
        assert read_version(store, version_id).manifest == manifest
        assert live_memory.current().version_id == version_id

    def test_a_foreign_file_in_the_object_store_is_reported(self,
                                                          live_memory: KuyenMemory) -> None:
        seed(live_memory)
        intruder = live_memory.store.objects_dir / "ab" / "not-a-content-address"
        intruder.parent.mkdir(parents=True, exist_ok=True)
        intruder.write_bytes(b"payload")

        report = live_memory.verify()

        assert report["ok"] is False
        assert any("UNEXPECTED_FILE" in problem for problem in report["problems"])
