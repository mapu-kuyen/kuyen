"""Versioned, deterministic section inventories for MAPU coverage.

A unit is a contiguous character slice of the original MAPU text. Units are
derived only from the source bytes; the producer cannot choose the inventory.
Unicode code-point offsets are the same unit KÜYEN uses for evidence.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any

PROFILE_ID = "document-sections-v1"
HEADING = re.compile(r"^(#{2,6})[ \t]+(.+?)[ \t]*$", re.MULTILINE)


@dataclass(frozen=True)
class SectionUnit:
    mapu_id: str
    unit_id: str
    section: str
    order: int
    char_start: int
    char_end: int
    content_sha256: str
    chars: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "mapu_id": self.mapu_id,
            "unit_id": self.unit_id,
            "section": self.section,
            "order": self.order,
            "char_start": self.char_start,
            "char_end": self.char_end,
            "content_sha256": self.content_sha256,
            "chars": self.chars,
        }


def _unit(mapu_id: str, unit_id: str, section: str, order: int, text: str, start: int, end: int) -> SectionUnit:
    body = text[start:end]
    return SectionUnit(
        mapu_id=mapu_id,
        unit_id=unit_id,
        section=section,
        order=order,
        char_start=start,
        char_end=end,
        content_sha256=hashlib.sha256(body.encode("utf-8")).hexdigest(),
        chars=end - start,
    )


def inventory_sections(
    content: str, *, mapu_id: str, profile: str = PROFILE_ID,
) -> list[SectionUnit]:
    """Return the expected coverage units for a MAPU.

    `document-sections-v1`:
      - level 2..6 Markdown headings delimit units;
      - non-empty text before the first heading becomes `u00` / `preamble`;
      - a document without headings is one `u00` / `body` unit;
      - unit IDs are assigned in document order and are stable for the same bytes.
    """
    if profile != PROFILE_ID:
        raise ValueError(f"unsupported coverage profile: {profile}")
    matches = list(HEADING.finditer(content))
    if not matches:
        if not content:
            return []
        return [_unit(mapu_id, "u00", "body", 0, content, 0, len(content))]
    units: list[SectionUnit] = []
    if matches[0].start() > 0 and content[: matches[0].start()].strip():
        units.append(_unit(mapu_id, "u00", "preamble", 0, content, 0, matches[0].start()))
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
        title = match.group(2).strip() or f"section-{index + 1}"
        units.append(_unit(mapu_id, f"u{index + 1:02d}", title, len(units), content, start, end))
    return units
