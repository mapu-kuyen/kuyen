"""Build a canonical document from an accepted KUYEN graph plus its MAPU texts.

This is the ingestion boundary of the product: the caller supplies an already
accepted graph (produced by extraction or by any external producer) and the source
texts; KUYEN builds the canonical record, verifies evidence offsets and derives the
SOURCE_UNIT inventory. Nothing is normalized, merged or repaired.
"""
from __future__ import annotations

from typing import Any, Mapping

from .canonical import canonical_json, digest, sha256_text
from .errors import ExportError

REQUIRED_GRAPH_KEYS = ("kuyen_id", "version", "antu_id", "mapu_ids", "schema_version", "status",
                       "entities", "relations", "assertions", "evidence", "coverage", "provenance",
                       "content_digest", "provenance_digest")


def build_document(graph: Mapping[str, Any], mapu_texts: Mapping[str, str],
                   *, mapu_versions: Mapping[str, str] | None = None,
                   source_uris: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Return the canonical document for an accepted graph and its sources."""
    missing = [key for key in REQUIRED_GRAPH_KEYS if key not in graph]
    if missing:
        raise ExportError(f"graph is missing required canonical keys: {missing}")
    mapu_versions = dict(mapu_versions or {})
    source_uris = dict(source_uris or {})
    mapus: list[dict[str, Any]] = []
    units: list[dict[str, Any]] = []
    for mapu_id in graph["mapu_ids"]:
        if mapu_id not in mapu_texts:
            raise ExportError(f"no source text was supplied for MAPU {mapu_id}")
        content = mapu_texts[mapu_id]
        source_uri = source_uris.get(mapu_id, f"viking://resources/{mapu_id}")
        inventory = ((graph.get("provenance") or {}).get("coverage_inventory") or {}).get(mapu_id) or []
        for entry in inventory:
            start, end = entry.get("char_start"), entry.get("char_end")
            slice_text = content[start:end] if isinstance(start, int) and isinstance(end, int) else None
            units.append({"unit_id": entry.get("unit_id"), "mapu_id": mapu_id,
                          "section": entry.get("section"), "order": entry.get("order"),
                          "char_start": start, "char_end": end, "chars": entry.get("chars"),
                          "content_sha256": entry.get("content_sha256"),
                          "source_uri": entry.get("source_uri") or source_uri,
                          "state": entry.get("state"), "content": slice_text,
                          "content_verified": (slice_text is not None and entry.get("content_sha256") is not None
                                               and sha256_text(slice_text) == entry.get("content_sha256"))})
        mapus.append({"mapu_id": mapu_id, "version": mapu_versions.get(mapu_id),
                      "source_uri": source_uri, "sha256": sha256_text(content),
                      "content": content, "content_chars": len(content),
                      "content_sha256": sha256_text(content), "units": [u["unit_id"] for u in units
                                                                        if u["mapu_id"] == mapu_id],
                      "media_type": "text/plain", "trust_level": "UNVERIFIED",
                      "access_policy": "experimental", "metadata": {}})
    canonical_graph_hash = digest(graph)
    return {
        "kuyen": {"kuyen_id": graph["kuyen_id"], "version": graph["version"],
                  "antu_id": graph["antu_id"], "mapu_ids": list(graph["mapu_ids"]),
                  "schema_version": graph["schema_version"], "status": graph["status"],
                  "content_digest": graph.get("content_digest"),
                  "provenance_digest": graph.get("provenance_digest"),
                  "provenance": graph.get("provenance") or {},
                  "canonical_graph_hash": canonical_graph_hash,
                  "source_graph_sha256": sha256_text(canonical_json(graph)),
                  "canonical_serialization_sha256": sha256_text(canonical_json(graph))},
        "mapus": mapus,
        "canonical": {"entities": list(graph.get("entities") or []),
                      "relations": list(graph.get("relations") or []),
                      "assertions": list(graph.get("assertions") or []),
                      "evidence": list(graph.get("evidence") or []),
                      "coverage": list(graph.get("coverage") or []),
                      "source_units": units},
        "counts": {"mapus": len(mapus), "entities": len(graph.get("entities") or []),
                   "relations": len(graph.get("relations") or []),
                   "assertions": len(graph.get("assertions") or []),
                   "evidence": len(graph.get("evidence") or []),
                   "coverage": len(graph.get("coverage") or []),
                   "source_units": len(units)},
    }
