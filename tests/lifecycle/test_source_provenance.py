"""M4 — a source keeps the provenance of the bytes it came from.

KUYEN_SEMANTIC_SECURITY_HARDENING_04. `build_document` hashed the *string* it received, so a
CRLF file read with universal newlines was stored with the hash of its LF-normalised text:
the evidence offsets and the declared hash no longer corresponded to the original file. The
contract tested here is explicit:

* the original bytes are hashed (`source_bytes_sha256`) and decoded without newline
translation, so `content.encode(encoding) == original bytes` holds;
* the text hash (`content_sha256`) is the one evidence offsets address, and the offset unit
  is declared (`unicode_codepoint`);
* a document without the bytes declares that its hash addresses the decoded text, so it can
  never be mistaken for a bytes hash.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

import fixtures_produc as fixtures
from kuyen import KuyenMemory, build_document
from kuyen.errors import ExportError

MAPU = fixtures.MAPU_ID
URI = fixtures.SOURCE_URI

SCENARIOS = {
    "lf": ("uno\ndos\ntres\n", "dos"),
    "crlf": ("uno\r\ndos\r\ntres\r\n", "dos"),
    "cr": ("uno\rdos\rtres\r", "dos"),
    "unicode": ("ñandú 日本語 🚀\nsegunda línea\n", "日本語 🚀"),
    "mixed": ("uno\r\ndos\ntres\r", "dos"),
    "adjacent_to_newlines": ("cabecera\nquote\ncola\n", "\nquote\n"),
}


def graph_with(text: str, quote: str) -> dict:
    graph = fixtures.make_graph()
    start = text.index(quote)
    graph["evidence"][0].update({"quote": quote, "char_start": start,
                                 "char_end": start + len(quote),
                                 "source_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                                 "offset_unit": "unicode_codepoint"})
    unit = graph["provenance"]["coverage_inventory"][MAPU][0]
    unit.update({"char_start": 0, "char_end": len(text), "chars": len(text),
                 "content_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()})
    return graph


def document_for(text: str, raw: bytes | None, quote: str) -> dict:
    graph = graph_with(text, quote)
    kwargs = {"source_bytes": {MAPU: raw}} if raw is not None else {}
    return build_document(graph, {MAPU: text}, mapu_versions={MAPU: "1.0.0"},
                          source_uris={MAPU: URI}, **kwargs)


class TestBytesProvenance:
    @pytest.mark.parametrize("label", sorted(SCENARIOS))
    def test_offsets_and_hashes_address_the_original_bytes(self, label: str) -> None:
        text, quote = SCENARIOS[label]
        raw = text.encode("utf-8")
        document = document_for(text, raw, quote)
        mapu = document["mapus"][0]

        assert mapu["source_bytes_sha256"] == hashlib.sha256(raw).hexdigest()
        assert mapu["source_hash_scope"] == "SOURCE_BYTES"
        assert mapu["encoding"] == "utf-8"
        assert mapu["newline_policy"] == "PRESERVED"
        assert mapu["offset_unit"] == "unicode_codepoint"
        assert mapu["content_sha256"] == hashlib.sha256(text.encode("utf-8")).hexdigest()
        assert mapu["content"].encode("utf-8") == raw, "the text must be the decoded bytes"

        evidence = document["canonical"]["evidence"][0]
        start, end = evidence["char_start"], evidence["char_end"]
        assert mapu["content"][start:end] == evidence["quote"] == quote

    @pytest.mark.parametrize("label", sorted(SCENARIOS))
    def test_a_store_accepts_it_verifies_it_and_keeps_it_after_restore(
            self, label: str, tmp_path: Path) -> None:
        text, quote = SCENARIOS[label]
        document = document_for(text, text.encode("utf-8"), quote)
        memory = KuyenMemory.create(tmp_path / f"store-{label}", leftraru_id="LR-M4")
        memory.import_canonical(document)
        assert memory.verify()["ok"] is True

        evidence = memory.graph()["evidence"][0]
        mapu = next(item for item in memory.sidecar()["mapus"] if item["mapu_id"] == MAPU)
        assert mapu["source_bytes_sha256"] == hashlib.sha256(text.encode("utf-8")).hexdigest()
        assert mapu["content"][evidence["char_start"]:evidence["char_end"]] == quote

        backup = tmp_path / f"backup-{label}"
        memory.backup(backup)
        restored = KuyenMemory.restore(backup, tmp_path / f"restored-{label}")
        assert restored.verify()["ok"] is True
        restored_mapu = next(item for item in restored.sidecar()["mapus"]
                             if item["mapu_id"] == MAPU)
        assert restored_mapu["source_bytes_sha256"] == mapu["source_bytes_sha256"]
        assert restored_mapu["content"] == mapu["content"]

    def test_bytes_that_do_not_decode_to_the_declared_text_are_rejected(self) -> None:
        text, quote = SCENARIOS["crlf"]
        different = text.replace("\r\n", "\n").encode("utf-8")
        with pytest.raises(ExportError):
            document_for(text, different, quote)


class TestTextOnlyProvenance:
    def test_a_document_without_bytes_declares_the_text_scope(self) -> None:
        text, quote = SCENARIOS["crlf"]
        mapu = document_for(text, None, quote)["mapus"][0]

        assert mapu["source_hash_scope"] == "DECODED_TEXT"
        assert mapu["source_bytes_sha256"] is None
        assert mapu["offset_unit"] == "unicode_codepoint"
        assert mapu["content_sha256"] == hashlib.sha256(text.encode("utf-8")).hexdigest()

    def test_an_empty_source_is_a_valid_provenance_record(self) -> None:
        graph = fixtures.make_graph()
        graph["evidence"] = []
        graph["assertions"] = []
        graph["relations"] = []
        for entity in graph["entities"]:
            entity["evidence_ids"] = []
            entity["status"] = "PROPOSED"
        graph["provenance"]["coverage_inventory"][MAPU] = []
        document = build_document(graph, {MAPU: ""}, mapu_versions={MAPU: "1.0.0"},
                                  source_uris={MAPU: URI},
                                  source_bytes={MAPU: b""})
        mapu = document["mapus"][0]
        assert mapu["content"] == ""
        assert mapu["source_bytes_sha256"] == hashlib.sha256(b"").hexdigest()
        assert document["canonical"]["source_units"] == []


class TestAntuSourceProvenance:
    def test_a_crlf_source_is_incorporated_with_the_hash_of_its_bytes(
            self, live_memory: KuyenMemory, tmp_path: Path) -> None:
        antu = fixtures.make_antu(antu_id="ANTU-CRLF",
                                  base_version_id=live_memory.current().version_id)
        quote = antu["proposal"]["evidence"][0]["quote"]
        header = "Cabecera de la fuente" + chr(10)
        crlf_text = (header + antu["unit"]["content"]).replace(chr(10), chr(13) + chr(10))
        raw = crlf_text.encode("utf-8")
        start = crlf_text.index(quote)
        source = tmp_path / "MAPU-CRLF.txt"
        source.write_bytes(raw)
        antu["unit"].update({"content": crlf_text, "char_end": len(crlf_text),
                             "chars": len(crlf_text),
                             "content_sha256": hashlib.sha256(raw).hexdigest()})
        antu["coverage"]["content_sha256"] = hashlib.sha256(raw).hexdigest()
        antu["mapu"]["sha256"] = hashlib.sha256(raw).hexdigest()
        antu["proposal"]["evidence"][0].update({
            "char_start": start, "char_end": start + len(quote),
            "source_sha256": hashlib.sha256(raw).hexdigest()})

        execution = live_memory.execute_antu(antu, mapu_source=source)

        assert execution.status == "VALIDATED", execution.to_dict()
        live_memory.commit(execution)
        memory = KuyenMemory.open(live_memory.path)
        merged = next(item for item in memory.sidecar()["mapus"]
                      if item["mapu_id"] == "MAPU-TEST-02")
        assert merged["source_bytes_sha256"] == hashlib.sha256(raw).hexdigest()
        assert merged["source_hash_scope"] == "SOURCE_BYTES"
        assert merged["newline_policy"] == "PRESERVED"
        assert merged["content"].encode("utf-8") == raw
        assert merged["declared_sha256_matches"] == "SOURCE_BYTES"
        assert memory.verify()["ok"] is True

    def test_a_declared_hash_of_a_different_file_is_rejected(
            self, live_memory: KuyenMemory, tmp_path: Path) -> None:
        antu = fixtures.make_antu(antu_id="ANTU-WRONG-HASH",
                                  base_version_id=live_memory.current().version_id)
        source = tmp_path / "MAPU-WRONG.txt"
        source.write_bytes(antu["unit"]["content"].encode("utf-8"))
        antu["mapu"]["sha256"] = hashlib.sha256(b"otra fuente").hexdigest()

        execution = live_memory.execute_antu(antu, mapu_source=source)

        assert execution.status == "REJECTED"
        assert any("hash" in reason.lower() for reason in execution.detail["reasons"])
