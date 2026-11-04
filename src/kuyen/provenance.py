"""Source provenance: the original bytes, the decoded text and the offsets that address it.

KUYEN_SEMANTIC_SECURITY_HARDENING_04 (M4). A source has three identities that must not be
confused:

* `bytes_sha256` — SHA-256 of the **original file bytes**, exactly as they were read;
* `text` — the bytes decoded with a declared encoding, **without newline translation**, so
  `text.encode(encoding)` returns the original bytes for any UTF-8 source;
* `text_sha256` — SHA-256 of that decoded text, which is what evidence offsets address.

Offsets are always Unicode code points over `text` (`offset_unit = "unicode_codepoint"`).
Reading a file with `Path.read_text()` translates `\r\n` to `\n`, which silently breaks the
correspondence between the stored hash, the offsets and the file: use `read_source()`.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

DEFAULT_ENCODING = "utf-8"
OFFSET_UNIT = "unicode_codepoint"
NEWLINES_PRESERVED = "PRESERVED"
NEWLINES_UNKNOWN = "UNKNOWN"
SCOPE_SOURCE_BYTES = "SOURCE_BYTES"
SCOPE_DECODED_TEXT = "DECODED_TEXT"


class ProvenanceError(ValueError):
    """A source cannot be read with a declared encoding or is not a byte sequence."""


@dataclass(frozen=True)
class SourceText:
    bytes_sha256: str
    text: str
    text_sha256: str
    encoding: str
    newline_policy: str
    offset_unit: str
    source_bytes: int
    source_uri: str | None = None

    def to_record(self) -> dict[str, object]:
        """The provenance fields a canonical MAPU record carries."""
        return {"source_bytes_sha256": self.bytes_sha256,
                "source_hash_scope": SCOPE_SOURCE_BYTES,
                "encoding": self.encoding, "newline_policy": self.newline_policy,
                "offset_unit": self.offset_unit, "source_bytes": self.source_bytes}


def decode_source(data: bytes | bytearray, *, encoding: str = DEFAULT_ENCODING,
                  source_uri: str | None = None) -> SourceText:
    """Decode original bytes strictly, preserving every newline sequence."""
    if not isinstance(data, (bytes, bytearray)):
        raise ProvenanceError(f"source data must be bytes, not {type(data).__name__}")
    raw = bytes(data)
    try:
        text = raw.decode(encoding)
    except UnicodeDecodeError as exc:
        raise ProvenanceError(f"source is not valid {encoding}: {exc.reason} at byte {exc.start}") from exc
    return SourceText(bytes_sha256=hashlib.sha256(raw).hexdigest(), text=text,
                      text_sha256=hashlib.sha256(text.encode(encoding)).hexdigest(),
                      encoding=encoding, newline_policy=NEWLINES_PRESERVED,
                      offset_unit=OFFSET_UNIT, source_bytes=len(raw), source_uri=source_uri)


def read_source(path: str | Path, *, encoding: str = DEFAULT_ENCODING) -> SourceText:
    """Read a source file byte for byte (never through universal newlines)."""
    file = Path(path)
    if not file.is_file():
        raise ProvenanceError(f"source file not found: {file}")
    return decode_source(file.read_bytes(), encoding=encoding, source_uri=file.resolve().as_uri())


def text_only_record(*, encoding: str = DEFAULT_ENCODING) -> dict[str, object]:
    """Provenance fields when the caller supplies only text: the scope is declared, not faked."""
    return {"source_bytes_sha256": None, "source_hash_scope": SCOPE_DECODED_TEXT,
            "encoding": encoding, "newline_policy": NEWLINES_UNKNOWN,
            "offset_unit": OFFSET_UNIT, "source_bytes": None}
